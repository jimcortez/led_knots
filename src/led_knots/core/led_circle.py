"""
LED circle cross-section creation for CadQuery.

This module provides a function to create a 2D LED circle cross-section
that can be swept along a path to create 3D geometry.
"""

import cadquery as cq
from cadquery.func import *


def _validate_led_circle_face_geometry(
    outer_radius: float,
    inner_radius: float,
    rect_inner_x: float,
    rect_inner_y: float,
    rect_inner_half_x: float,
    rect_inner_half_y: float,
    oval_x: float,
    oval_y: float,
    min_oval_wall_thickness: float,
    connector_top_length: float,
    connector_top_center_y: float,
    connector_width: float,
    oval_top_y: float,
    result_shape,
) -> bool:
    """
    Validate the LED circle geometry created with functional API. Only prints when validations fail.
    
    Args:
        result_shape: The result from create_led_circle_face (Face or Compound)
    
    Returns:
        True if all validations pass, False otherwise
    """
    has_errors = False
    
    # Check 1: Rectangle fits in oval
    rect_fits_x = rect_inner_x < oval_x
    rect_fits_y = rect_inner_y < oval_y
    rect_fits = rect_fits_x and rect_fits_y
    
    # Check if rectangle corners fit in ellipse (critical for ellipse geometry)
    try:
        corner_check = (rect_inner_half_x / (oval_x/2))**2 + (rect_inner_half_y / (oval_y/2))**2
        corners_fit = corner_check <= 1.0
    except:
        corners_fit = True
    
    if not (rect_fits and corners_fit):
        has_errors = True
        print("VALIDATION ERROR: Rectangle does not fit in oval")
        if not rect_fits_x:
            print(f"  - X dimension: {rect_inner_x} >= {oval_x}")
        if not rect_fits_y:
            print(f"  - Y dimension: {rect_inner_y} >= {oval_y}")
        if not corners_fit:
            print(f"  - Rectangle corners extend outside ellipse: {corner_check:.4f} > 1.0")
    
    # Check 2: Oval wall thickness meets minimum
    oval_wall_x = (oval_x - rect_inner_x) / 2
    oval_wall_y = (oval_y - rect_inner_y) / 2
    wall_x_ok = oval_wall_x >= min_oval_wall_thickness
    wall_y_ok = oval_wall_y >= min_oval_wall_thickness
    
    if not (wall_x_ok and wall_y_ok):
        has_errors = True
        print("VALIDATION ERROR: Oval wall thickness below minimum")
        if not wall_x_ok:
            print(f"  - X wall: {oval_wall_x:.3f} mm < {min_oval_wall_thickness} mm")
        if not wall_y_ok:
            print(f"  - Y wall: {oval_wall_y:.3f} mm < {min_oval_wall_thickness} mm")
    
    # Check 3: Oval fits in inner ring (CRITICAL)
    oval_half_x = oval_x / 2
    oval_half_y = oval_y / 2
    max_oval_half = max(oval_half_x, oval_half_y)
    max_allowed = inner_radius * 0.95
    oval_fits = max_oval_half <= max_allowed
    extension = max_oval_half - inner_radius if max_oval_half > inner_radius else 0
    
    if not oval_fits or extension > 0:
        has_errors = True
        print("VALIDATION ERROR: Oval extends beyond inner ring (CRITICAL)")
        print(f"  - Inner ring radius: {inner_radius:.3f} mm")
        print(f"  - Max oval half-dimension: {max_oval_half:.3f} mm")
        print(f"  - Max allowed (95% of inner_radius): {max_allowed:.3f} mm")
        if extension > 0:
            print(f"  - ⚠️  OVAL EXTENDS BEYOND INNER RING BY {extension:.3f} mm! ⚠️")
            print(f"  - This will cause sweep failures!")
    
    # Check 4: Connector dimensions are valid
    connector_valid = connector_top_length > 0 and connector_width > 0
    if not connector_valid:
        has_errors = True
        print("VALIDATION ERROR: Invalid connector dimensions")
        if connector_top_length <= 0:
            print(f"  - Length: {connector_top_length:.3f} mm (must be > 0)")
        if connector_width <= 0:
            print(f"  - Width: {connector_width:.3f} mm (must be > 0)")
    
    # Check 5: Connector overlaps properly (extends into curved surfaces)
    connector_bottom = connector_top_center_y - connector_top_length / 2
    connector_top = connector_top_center_y + connector_top_length / 2
    # Connector should extend below oval_top_y (overlap with oval) and above inner_radius (overlap with ring)
    connector_overlaps_oval = connector_bottom < oval_top_y  # Extends below oval edge
    connector_overlaps_ring = connector_top > inner_radius  # Extends above ring edge
    connector_overlaps = connector_overlaps_oval and connector_overlaps_ring
    
    if not connector_overlaps:
        has_errors = True
        print("VALIDATION ERROR: Connector does not overlap properly")
        if not connector_overlaps_oval:
            print(f"  - Connector bottom: {connector_bottom:.3f} mm (should be < {oval_top_y:.3f} mm to overlap)")
        if not connector_overlaps_ring:
            print(f"  - Connector top: {connector_top:.3f} mm (should be > {inner_radius:.3f} mm to overlap)")
    
    # Check 6: Connector doesn't extend too far beyond inner ring
    # The connector should overlap into the ring, but not extend beyond the outer radius
    # (The outer ring extends from inner_radius to outer_radius, so connector can extend into this range)
    max_extent = max(oval_half_x, oval_half_y, connector_top)
    # Allow connector to extend into the ring (up to outer_radius), but warn if it's excessive
    max_allowed = inner_radius * 1.1  # Allow up to 10% beyond inner_radius for overlap
    fits_in_ring = max_extent <= max_allowed
    
    if not fits_in_ring:
        has_errors = True
        print("VALIDATION ERROR: Connector extends too far beyond inner ring")
        print(f"  - Overall max extent: {max_extent:.3f} mm > max allowed: {max_allowed:.3f} mm")
        print(f"  - Inner radius: {inner_radius:.3f} mm")
    
    # Check 7: All dimensions are positive
    all_positive = (rect_inner_x > 0 and rect_inner_y > 0 and 
                   oval_x > 0 and oval_y > 0 and 
                   connector_top_length > 0 and connector_width > 0 and
                   inner_radius > 0)
    
    if not all_positive:
        has_errors = True
        print("VALIDATION ERROR: Some dimensions are not positive")
    
    # Check 8: Shape validity
    try:
        shape_valid = result_shape.isValid()
    except:
        shape_valid = False
    
    if not shape_valid:
        has_errors = True
        print("VALIDATION ERROR: Result shape is invalid")
        try:
            shape_area = result_shape.Area()
            if shape_area <= 0:
                print(f"  - CRITICAL: Result shape is empty (area: {shape_area:.6f} mm²)!")
        except:
            pass
    
    # Check 9: Shape type and structure
    try:
        # Check if it's a Compound or Face
        is_compound = hasattr(result_shape, 'Solids') or hasattr(result_shape, 'Faces')
        # For functional API, result should be a Face or Compound
        # If it's a Compound, we can check the number of faces
        if is_compound:
            try:
                faces = result_shape.Faces()
                face_count = len(faces) if faces else 0
                # Expected: outer ring (1 face), center oval (1 face), top connector (1 face), bottom connector (1 face) = 4 faces
                # But after fuse, it might be fewer faces if they're connected
                face_count_ok = face_count >= 1  # At least 1 face after fusion
                if not face_count_ok:
                    has_errors = True
                    print(f"VALIDATION ERROR: Compound has no faces: {face_count}")
            except:
                # If we can't get faces, that's okay - might be a different shape type
                pass
        else:
            # It's a single Face, which is also valid
            try:
                face_area = result_shape.Area()
                if face_area <= 0:
                    has_errors = True
                    print(f"VALIDATION ERROR: Face has zero or negative area: {face_area:.6f} mm²")
            except:
                pass
    except Exception as e:
        has_errors = True
        print(f"VALIDATION ERROR: Could not check shape structure: {e}")
    
    # Check 10: Face connectivity (with overlap)
    connector_bottom_y = connector_top_center_y - connector_top_length / 2
    connector_top_y = connector_top_center_y + connector_top_length / 2
    # Connector should overlap (extend into) the oval and ring
    connector_overlaps_oval = connector_bottom_y < oval_top_y  # Extends below oval edge
    connector_overlaps_ring = connector_top_y > inner_radius  # Extends above ring edge
    
    connector_x_min = 0.5 - connector_width / 2
    connector_x_max = 0.5 + connector_width / 2
    oval_x_min = 0.5 - oval_x / 2
    oval_x_max = 0.5 + oval_x / 2
    ring_x_min = 0.5 - inner_radius
    ring_x_max = 0.5 + inner_radius
    
    connector_in_ring_x = (connector_x_min >= ring_x_min and connector_x_max <= ring_x_max)
    connectivity_ok = connector_overlaps_oval and connector_overlaps_ring and connector_in_ring_x
    
    if not connectivity_ok:
        has_errors = True
        print("VALIDATION ERROR: Face connectivity issues")
        if not connector_overlaps_oval:
            print(f"  - Connector bottom does not overlap oval: {connector_bottom_y:.3f} should be < {oval_top_y:.3f}")
        if not connector_overlaps_ring:
            print(f"  - Connector top does not overlap inner ring: {connector_top_y:.3f} should be > {inner_radius:.3f}")
        if not connector_in_ring_x:
            print(f"  - Connector X range [{connector_x_min:.3f}, {connector_x_max:.3f}] extends beyond ring X range [{ring_x_min:.3f}, {ring_x_max:.3f}]")
    
    return not has_errors


def create_led_circle_face(
    outer_radius: float,
    wall_thickness: float,
    rect_inner_x: float = 4.0,
    rect_inner_y: float = 12.0,
    min_oval_wall_thickness: float = 2.0,
    oval_wall_thickness: float = 2.0,
    connector_width: float = 1.0,
    orient_to_path: Wire = None,
    rotation_z: float = 90.0,
):
    """
    Create a 2D LED circle cross-section using the CadQuery functional API.
    
    This is a functional API version of create_led_circle_sections that uses
    the free function API from cadquery.func instead of the Workplane API.
    
    The design consists of:
    - Outer ring: annulus with outer_radius and wall_thickness
    - Center oval: ellipse with rectangular inner cavity (rect size is fixed, oval resizes)
    - Connecting rectangles: top and bottom connectors linking inner ring to center oval
    
    This matches the geometry defined in scad/led_circle.scad.
    
    Args:
        outer_radius: Outer radius of the main ring in mm
        wall_thickness: Wall thickness of the outer ring in mm
        rect_inner_x: Inner X dimension of center rectangle in mm (default: 4.0) - MUST be exact size
        rect_inner_y: Inner Y dimension of center rectangle in mm (default: 12.0) - MUST be exact size
        min_oval_wall_thickness: Minimum distance from oval edge to any point on rectangle in mm (default: 2.0)
        oval_wall_thickness: Actual wall thickness around rectangle for oval sizing in mm (default: 2.0)
                           Must be >= min_oval_wall_thickness
        connector_width: Width of connecting rectangles in mm (default: 1.0)
        orient_to_path: If provided (Wire object), orient the result to the path's start point and tangent.
                        The result will be positioned at the path's start point with the normal aligned to the path's tangent.
        rotation_z: Rotation angle in degrees around Z axis (around profile center). Default: 90.0
        
    Returns:
        Face or Compound representing the complete 2D cross-section ready for sweeping
    """
    # Validate parameters
    if oval_wall_thickness < min_oval_wall_thickness:
        raise ValueError(f"oval_wall_thickness ({oval_wall_thickness}) must be >= min_oval_wall_thickness ({min_oval_wall_thickness})")
    
    # Calculate dimensions for outer ring
    inner_radius = outer_radius - wall_thickness
    
    # Rectangle dimensions stay exactly as specified - NEVER scaled
    # The rectangle is the fixed reference point
    rect_inner_half_x = rect_inner_x / 2
    rect_inner_half_y = rect_inner_y / 2
    
    # Calculate oval dimensions based on rectangle + oval_wall_thickness
    # Oval must be at least min_oval_wall_thickness away from rectangle at all points
    oval_x = rect_inner_x + 2 * oval_wall_thickness
    oval_y = rect_inner_y + 2 * oval_wall_thickness
    
    # Scale oval if it's too large to fit within inner ring
    # The oval should fit within the inner radius
    # For an ellipse centered at origin, we compare half-dimensions to the radius
    max_oval_half_size = inner_radius * 0.95  # Leave some margin
    max_half_dimension = max(oval_x / 2, oval_y / 2)
    
    if max_half_dimension > max_oval_half_size:
        # Scale down the oval to fit within inner ring
        scale_factor = max_oval_half_size / max_half_dimension
        oval_x = oval_x * scale_factor
        oval_y = oval_y * scale_factor
        
        # Verify scaled oval still maintains minimum wall thickness
        actual_wall_x = (oval_x - rect_inner_x) / 2
        actual_wall_y = (oval_y - rect_inner_y) / 2
        
        # If scaling violated minimum wall thickness, we need to find a compromise
        # Try to use minimum wall thickness, but ensure it still fits in the ring
        if actual_wall_x < min_oval_wall_thickness or actual_wall_y < min_oval_wall_thickness:
            # Calculate what the oval size would be with minimum wall thickness
            min_oval_x = rect_inner_x + 2 * min_oval_wall_thickness
            min_oval_y = rect_inner_y + 2 * min_oval_wall_thickness
            min_oval_max_half = max(min_oval_x / 2, min_oval_y / 2)
            
            # CRITICAL: Check against actual inner_radius, not max_oval_half_size
            # If minimum wall thickness oval fits within actual inner radius, use it
            if min_oval_max_half <= inner_radius:
                oval_x = min_oval_x
                oval_y = min_oval_y
            # else: keep the scaled version (which fits but may violate minimum)
    
    # Final verification: ensure oval fits within inner ring (CRITICAL CHECK)
    # ALWAYS check against actual inner_radius to be absolutely sure it fits
    final_max_half = max(oval_x / 2, oval_y / 2)
    if final_max_half > inner_radius:
        # Force it to fit by scaling down to fit within actual inner radius
        final_scale = inner_radius / final_max_half
        oval_x = oval_x * final_scale
        oval_y = oval_y * final_scale
        print(f"  ⚠️  WARNING: Oval extended beyond inner ring! Forced scaling to fit.")
        print(f"     - Before: max half-dimension = {final_max_half:.3f} mm (inner_radius = {inner_radius:.3f} mm)")
        print(f"     - After: {oval_x:.3f} x {oval_y:.3f} mm (max half = {max(oval_x/2, oval_y/2):.3f} mm)")
    
    # Double-check: ensure it's definitely within inner radius (with small tolerance for floating point)
    final_check = max(oval_x / 2, oval_y / 2)
    tolerance = 0.001  # 1 micron tolerance
    if final_check > inner_radius + tolerance:
        raise ValueError(f"CRITICAL: Oval still extends beyond inner ring! "
                        f"Max half-dimension: {final_check:.3f} mm > inner_radius: {inner_radius:.3f} mm")
    
    # Calculate connector dimensions
    # Connectors connect from inner ring (at inner_radius) to the oval edge
    # The oval extends to oval_y/2 in the Y direction (centered at 0)
    oval_top_y = oval_y / 2
    
    # Calculate overlap extensions to ensure connectors overlap with curved surfaces
    # Since flat rectangles meet curved surfaces, we extend the connectors to overlap
    # This ensures proper attachment rather than just touching
    
    # Overlap amount: extend connectors by this amount into the curved surfaces
    # This accounts for the curvature and ensures solid attachment
    # Use a conservative overlap that's proportional to connector width
    overlap_amount = min(0.15, connector_width * 0.15)  # 0.15mm or 15% of width, whichever is smaller
    
    # Extend connector above inner_radius to overlap with the inner ring (circle)
    # The inner ring is a circle centered at (0.5, 0) with radius inner_radius
    # Ensure we don't extend beyond the outer ring boundary
    max_allowed_y = outer_radius - 0.1  # Leave small margin from outer edge
    connector_top_y = min(inner_radius + overlap_amount, max_allowed_y)
    
    # Extend connector below oval_top_y to overlap with the oval (ellipse)
    # The oval is an ellipse centered at (0.5, 0) extending to oval_y/2 in Y direction
    connector_bottom_y = max(oval_top_y - overlap_amount, -oval_y / 2 + 0.1)  # Don't extend beyond oval bottom
    
    # Calculate new connector length and center position
    connector_top_length = connector_top_y - connector_bottom_y
    connector_top_center_y = (connector_top_y + connector_bottom_y) / 2
    
    # CRITICAL: For an ellipse, we must ensure the rectangle corners fit inside the ellipse
    # An ellipse with semi-axes a, b contains point (x, y) if (x/a)² + (y/b)² ≤ 1
    # Rectangle corners are at (±rect_inner_x/2, ±rect_inner_y/2)
    # We need: (rect_inner_x/2 / (oval_x/2))² + (rect_inner_y/2 / (oval_y/2))² ≤ 1
    # Which simplifies to: (rect_inner_x/oval_x)² + (rect_inner_y/oval_y)² ≤ 1
    oval_semi_x = oval_x / 2
    oval_semi_y = oval_y / 2
    rect_half_x = rect_inner_x / 2
    rect_half_y = rect_inner_y / 2
    
    # Check if rectangle corners fit in ellipse
    corner_fit_check = (rect_half_x / oval_semi_x)**2 + (rect_half_y / oval_semi_y)**2
    rectangle_fits_in_ellipse = corner_fit_check <= 1.0
    
    if not rectangle_fits_in_ellipse:
        # Rectangle doesn't fit - need to scale oval to ensure rectangle fits
        # We need: (rect_half_x / new_oval_semi_x)² + (rect_half_y / new_oval_semi_y)² = 1
        # With aspect ratio preserved: new_oval_semi_y = new_oval_semi_x * (oval_semi_y / oval_semi_x)
        # Solving: (rect_half_x / new_oval_semi_x)² + (rect_half_y / (new_oval_semi_x * ratio))² = 1
        aspect_ratio = oval_semi_y / oval_semi_x
        # We want the corner to be exactly on the ellipse, so:
        # (rect_half_x / new_oval_semi_x)² + (rect_half_y / (new_oval_semi_x * aspect_ratio))² = 1
        # Factor out 1/new_oval_semi_x²: (1/new_oval_semi_x²) * (rect_half_x² + rect_half_y²/aspect_ratio²) = 1
        # new_oval_semi_x² = rect_half_x² + rect_half_y²/aspect_ratio²
        new_oval_semi_x = (rect_half_x**2 + (rect_half_y / aspect_ratio)**2)**0.5
        new_oval_semi_y = new_oval_semi_x * aspect_ratio
        oval_x = new_oval_semi_x * 2
        oval_y = new_oval_semi_y * 2
        # Recalculate semi-axes after scaling
        oval_semi_x = oval_x / 2
        oval_semi_y = oval_y / 2
        print(f"  WARNING: Rectangle corners didn't fit in ellipse! Scaled oval to {oval_x:.3f} x {oval_y:.3f} mm")
    
    if oval_semi_x <= 0 or oval_semi_y <= 0:
        raise ValueError(f"Invalid ellipse parameters: oval_semi_x={oval_semi_x:.6f}, oval_semi_y={oval_semi_y:.6f}. "
                        f"oval_x={oval_x:.6f}, oval_y={oval_y:.6f}")
    
    # Create geometry using functional API
    # All shapes are created in XY plane (orient_for_z_up=True, so keep in XY)
    profile_center_x = 0.5
    profile_center_y = 0.0
    
    # Helper function to rotate around profile center
    def rotate_around_center(shape):
        if rotation_z == 0:
            return shape
        return (shape.moved(x=-profile_center_x, y=-profile_center_y)
                   .moved(rz=rotation_z)
                   .moved(x=profile_center_x, y=profile_center_y))
    
    # Outer ring: annulus (outer circle - inner circle)
    outer_ring_base = (face(circle(outer_radius)) - face(circle(inner_radius))).moved(x=0.5)
    outer_ring = rotate_around_center(outer_ring_base)
    
    # Center oval with rectangular inner cavity: difference (oval - rectangle)
    # OpenCASCADE ellipse requires major >= minor; it places major along X, minor along Y.
    # We need oval_semi_x in X, oval_semi_y in Y. Use ellipse(major, minor) then rotate 90°
    # so major ends up in Y and minor in X.
    ellipse_r1 = max(oval_semi_x, oval_semi_y)
    ellipse_r2 = min(oval_semi_x, oval_semi_y)
    if ellipse_r1 <= 0 or ellipse_r2 <= 0:
        raise ValueError(f"Invalid ellipse semi-axes: r1={ellipse_r1:.6f}, r2={ellipse_r2:.6f}")
    ell_edge = ellipse(ellipse_r1, ellipse_r2)
    if oval_semi_y > oval_semi_x:
        ell_edge = ell_edge.moved(rz=90)  # major was Y, rotate so oval_semi_x in X, oval_semi_y in Y
    center_oval_base = (face(ell_edge) - face(rect(rect_inner_x, rect_inner_y))).moved(x=0.5)
    center_oval = rotate_around_center(center_oval_base)
    
    # Connecting rectangles: top and bottom connectors
    top_connector_base = plane(connector_width, connector_top_length).moved(x=0.5, y=connector_top_center_y)
    top_connector = rotate_around_center(top_connector_base)
    bottom_connector_base = plane(connector_width, connector_top_length).moved(x=0.5, y=-connector_top_center_y)
    bottom_connector = rotate_around_center(bottom_connector_base)
    
    # Combine all faces using fuse
    result = clean(fuse(outer_ring, center_oval, top_connector, bottom_connector))
    
    # If orient_to_path is provided, orient the result to the path
    if orient_to_path is not None:
        face_plane = Plane(origin=orient_to_path.startPoint(), normal=orient_to_path.tangentAt(0))
        result = result.moved(Location(face_plane))
    
    # Validate geometry (only prints when validations fail)
    _validate_led_circle_face_geometry(
        outer_radius=outer_radius,
        inner_radius=inner_radius,
        rect_inner_x=rect_inner_x,
        rect_inner_y=rect_inner_y,
        rect_inner_half_x=rect_inner_half_x,
        rect_inner_half_y=rect_inner_half_y,
        oval_x=oval_x,
        oval_y=oval_y,
        min_oval_wall_thickness=min_oval_wall_thickness,
        connector_top_length=connector_top_length,
        connector_top_center_y=connector_top_center_y,
        connector_width=connector_width,
        oval_top_y=oval_top_y,
        result_shape=result,
    )
    
    return result


def create_dev_circle_face(
    outer_radius: float,
    wall_thickness: float,
    rect_inner_x: float = 4.0,
    rect_inner_y: float = 12.0,
    min_oval_wall_thickness: float = 2.0,
    oval_wall_thickness: float = 2.0,
    connector_width: float = 1.0,
    orient_to_path: Wire = None,
    rotation_z: float = 90.0,
):
    """
    Create a simple filled circle face for development/testing purposes.
    
    This is a simplified version of create_led_circle_face that returns
    just a simple filled circle with no complex geometry or validation.
    
    Args:
        outer_radius: Outer radius of the circle in mm
        wall_thickness: Ignored (kept for signature compatibility)
        rect_inner_x: Ignored (kept for signature compatibility)
        rect_inner_y: Ignored (kept for signature compatibility)
        min_oval_wall_thickness: Ignored (kept for signature compatibility)
        oval_wall_thickness: Ignored (kept for signature compatibility)
        connector_width: Ignored (kept for signature compatibility)
        orient_to_path: If provided (Wire object), orient the result to the path's start point and tangent.
                        The result will be positioned at the path's start point with the normal aligned to the path's tangent.
        rotation_z: Rotation angle in degrees around Z axis (around profile center). Default: 90.0
        
    Returns:
        Face representing a simple filled circle
    """
    # Create simple filled circle in XY plane (orient_for_z_up=True, so keep in XY)
    profile_center_x = 0.5
    profile_center_y = 0.0
    
    # Helper function to rotate around profile center
    def rotate_around_center(shape):
        if rotation_z == 0:
            return shape
        return (shape.moved(x=-profile_center_x, y=-profile_center_y)
                   .moved(rz=rotation_z)
                   .moved(x=profile_center_x, y=profile_center_y))
    
    # Create a simple filled circle
    circle_base = face(circle(outer_radius)).moved(x=0.5)
    result = rotate_around_center(circle_base)
    
    # If orient_to_path is provided, orient the result to the path
    if orient_to_path is not None:
        face_plane = Plane(origin=orient_to_path.startPoint(), normal=orient_to_path.tangentAt(0))
        result = result.moved(Location(face_plane))
    
    return result


def create_dev_square_face(
    outer_radius: float,
    wall_thickness: float,
    rect_inner_x: float = 4.0,
    rect_inner_y: float = 12.0,
    min_oval_wall_thickness: float = 2.0,
    oval_wall_thickness: float = 2.0,
    connector_width: float = 1.0,
    orient_to_path: Wire = None,
    rotation_z: float = 90.0,
):
    """
    Create a simple filled square face for development/testing purposes.
    
    This is a simplified version of create_led_circle_face that returns
    just a simple filled square with no complex geometry or validation.
    
    Args:
        outer_radius: Outer radius of the circle in mm
        wall_thickness: Ignored (kept for signature compatibility)
        rect_inner_x: Ignored (kept for signature compatibility)
        rect_inner_y: Ignored (kept for signature compatibility)
        min_oval_wall_thickness: Ignored (kept for signature compatibility)
        oval_wall_thickness: Ignored (kept for signature compatibility)
        connector_width: Ignored (kept for signature compatibility)
        orient_to_path: If provided (Wire object), orient the result to the path's start point and tangent.
                        The result will be positioned at the path's start point with the normal aligned to the path's tangent.
        rotation_z: Rotation angle in degrees around Z axis (around profile center). Default: 90.0
        
    Returns:
        Face representing a simple filled square
    """
    # Create simple filled square in XY plane (orient_for_z_up=True, so keep in XY)
    profile_center_x = 0.5
    profile_center_y = 0.0
    
    # Helper function to rotate around profile center
    def rotate_around_center(shape):
        if rotation_z == 0:
            return shape
        return (shape.moved(x=-profile_center_x, y=-profile_center_y)
                   .moved(rz=rotation_z)
                   .moved(x=profile_center_x, y=profile_center_y))
    
    # Create a simple filled square
    square_base = face(rect(outer_radius*2, outer_radius*2)).moved(x=0.5)
    result = rotate_around_center(square_base)
    
    # If orient_to_path is provided, orient the result to the path
    if orient_to_path is not None:
        face_plane = Plane(origin=orient_to_path.startPoint(), normal=orient_to_path.tangentAt(0))
        result = result.moved(Location(face_plane))
    
    return result
