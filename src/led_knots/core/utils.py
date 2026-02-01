"""
Shared utilities for creating knots from paths using loft operations in CadQuery.

This module provides a generic framework for creating knot variants by:
1. Taking a path (Wire) - defined in each knot variant file
2. Creating frames along the path
3. Generating sections at each frame (using any section generator function)
4. Lofting the sections together

This abstracts away the complexity of section management and loft operations,
making it easy to create new knot variants. Each knot variant file should define
its own unique path, while this module handles the shared lofting logic.
"""

import argparse
import logging
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple, Union
import numpy as np

import cadquery as cq
from cadquery.func import sweep, spline
from .cache_utils import cache_key_for_part
from .led_circle import create_led_circle_face

logger = logging.getLogger(__name__)

# Logging will be configured by parse_args() when --verbose flag is used


# ============================================================================
# FRAME GENERATORS (for compatibility with older code)
# ============================================================================

def constant_up_frame_generator(path, t):
    """
    Generate a frame with constant up vector (Z-axis).
    
    Args:
        path: CadQuery Wire or Edge
        t: Parameter along path (0 to 1)
        
    Returns:
        Tuple of (position, tangent, normal, binormal)
    """
    pos = path.positionAt(t)
    tangent_vec = path.tangentAt(t)
    tangent = np.array([tangent_vec.x, tangent_vec.y, tangent_vec.z])
    tangent = tangent / np.linalg.norm(tangent)
    
    # Use Z as up vector
    up = np.array([0, 0, 1])
    
    # Compute normal and binormal
    binormal = np.cross(tangent, up)
    binormal_mag = np.linalg.norm(binormal)
    if binormal_mag < 1e-6:
        # Tangent is parallel to Z, use X as up
        up = np.array([1, 0, 0])
        binormal = np.cross(tangent, up)
        binormal_mag = np.linalg.norm(binormal)
    binormal = binormal / binormal_mag
    normal = np.cross(binormal, tangent)
    
    return (pos.x, pos.y, pos.z), tangent, normal, binormal


def tangent_based_frame_generator(path, t):
    """
    Generate a frame based on tangent direction.
    
    Args:
        path: CadQuery Wire or Edge
        t: Parameter along path (0 to 1)
        
    Returns:
        Tuple of (position, tangent, normal, binormal)
    """
    pos = path.positionAt(t)
    tangent_vec = path.tangentAt(t)
    tangent = np.array([tangent_vec.x, tangent_vec.y, tangent_vec.z])
    tangent = tangent / np.linalg.norm(tangent)
    
    # Use curvature direction as normal if available
    # For now, fall back to constant up
    return constant_up_frame_generator(path, t)


# ============================================================================
# COMMAND LINE PARSING
# ============================================================================

def parse_args(description: str = "Create and render a knot model"):
    """
    Parse command line arguments for knot rendering.
    
    Args:
        description: Description for the argument parser
        
    Returns:
        argparse.Namespace: Parsed arguments with:
            - export: Optional filepath to export the model to (STL, STEP format)
            - server: Boolean flag (not used for CadQuery, but kept for compatibility)
            - verbose: Boolean flag to enable DEBUG level logging
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        '--export',
        type=str,
        metavar='FILEPATH',
        help='Export the model to the specified file path. Supported formats: .stl, .step, .stp, .3mf'
    )
    parser.add_argument(
        '--server',
        action='store_true',
        help='Start the yacv server for web viewing'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose (DEBUG level) logging'
    )
    parser.add_argument(
        '--no-cache',
        action='store_true',
        help='Never use cache; always sweep and render'
    )
    parser.add_argument(
        '--only-cache',
        action='store_true',
        help='Only render if a cached GLB exists; do not sweep on cache miss'
    )
    args = parser.parse_args()
    
    # Configure logging if verbose flag is set
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    
    return args


# ============================================================================
# PYKNOT SCALING UTILITIES
# ============================================================================

def scale_pyknot_points(points: np.ndarray, width: float, height: float, length: float) -> np.ndarray:
    """
    Scale pyknot points to fit within a bounding box while preserving aspect ratio.
    
    Calculates the bounding box of the input points and scales them uniformly
    to fit within the specified width, height, and length constraints.
    
    Args:
        points: numpy array of shape (n, 3) containing (x, y, z) coordinates
        width: Target width for the x dimension (mm)
        height: Target height for the y dimension (mm)
        length: Target length for the z dimension (mm)
        
    Returns:
        numpy array of scaled points with the same shape as input
    """
    # Calculate the bounding box of the original points
    min_x, max_x = points[:, 0].min(), points[:, 0].max()
    min_y, max_y = points[:, 1].min(), points[:, 1].max()
    min_z, max_z = points[:, 2].min(), points[:, 2].max()
    
    # Calculate the spans (ranges) for each dimension
    span_x = max_x - min_x
    span_y = max_y - min_y
    span_z = max_z - min_z
    
    # Calculate scale factors to fit within width (x), height (y), and length (z)
    scale_x = width / span_x if span_x > 0 else 1.0
    scale_y = height / span_y if span_y > 0 else 1.0
    scale_z = length / span_z if span_z > 0 else 1.0
    
    # Use the minimum scale factor to preserve aspect ratio and ensure it fits
    scale_factor = min(scale_x, scale_y, scale_z)
    
    # Scale the points
    return points * scale_factor


# ============================================================================
# DISPLAY AND EXPORT UTILITIES
# ============================================================================

def render_part(
    part: Union[cq.Workplane, cq.Solid, cq.Compound, bytes],
    config,
    cache_path: Optional[Union[str, Path]] = None,
):
    """
    Render the part based on configuration.

    Args:
        part: The Workplane, Solid, Compound, or GLB bytes (from cache) to render.
        config: Config object with export, server, name, no_cache, etc.
        cache_path: Optional path to write GLB bytes after building (when part is solid
                    and not config.no_cache). Ignored when part is bytes.
    """
    name = config.name or "Knot"
    is_glb_bytes = isinstance(part, bytes)
    # Set environment variable before importing yacv_server if we only want export
    if config.export.filepath and not config.server:
        os.environ['YACV_DISABLE_SERVER'] = '1'

    # Import yacv_server (server will auto-start unless disabled)
    from yacv_server import yacv, show

    if is_glb_bytes:
        glb_bytes = part
        # Pre-built GLB from cache: show and/or write to export path
        if config.export.filepath:
            file_ext = os.path.splitext(config.export.filepath)[1].lower()
            if file_ext in ['.glb', '.gltf']:
                export_dir = os.path.dirname(config.export.filepath)
                if export_dir and not os.path.exists(export_dir):
                    os.makedirs(export_dir, exist_ok=True)
                with open(config.export.filepath, 'wb') as f:
                    f.write(glb_bytes)
                logger.info("Exported %s to %s (GLB format)", name, config.export.filepath)
                return
            # Other formats not supported when part is from cache
            logger.error("Export format %s not supported when using cached GLB", file_ext)
            sys.exit(2)
        show(glb_bytes, names=name)
        if config.server:
            if yacv.server_thread is None:
                yacv.start()
            logger.info("Server started. View %s in the web interface.", name)
            if yacv.server is not None:
                logger.info("Server URL: http://%s:%s", yacv.server.server_name, yacv.server.server_port)
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                logger.info("Shutting down server...")
                yacv.stop()
        return

    # Part is a solid/workplane
    if isinstance(part, (cq.Solid, cq.Compound)):
        solid = part
    elif hasattr(part, 'val'):
        solid = part.val()
    else:
        solid = part

    # If export is specified, export to the filepath
    if config.export.filepath:
        export_dir = os.path.dirname(config.export.filepath)
        if export_dir and not os.path.exists(export_dir):
            os.makedirs(export_dir, exist_ok=True)
        file_ext = os.path.splitext(config.export.filepath)[1].lower()

        if file_ext == '.stl':
            cq.exporters.export(
                solid,
                config.export.filepath,
                tolerance=config.export.tolerance,
                angularTolerance=config.export.angular_tolerance
            )
            logger.info("Exported %s to %s (STL format)", name, config.export.filepath)
            return
        if file_ext in ['.step', '.stp']:
            cq.exporters.export(
                solid,
                config.export.filepath,
                tolerance=config.export.tolerance,
                angularTolerance=config.export.angular_tolerance
            )
            logger.info("Exported %s to %s (STEP format)", name, config.export.filepath)
            return
        if file_ext == '.3mf':
            cq.exporters.export(
                solid,
                config.export.filepath,
                tolerance=config.export.tolerance,
                angularTolerance=config.export.angular_tolerance
            )
            logger.info("Exported %s to %s (3MF format)", name, config.export.filepath)
            return
        if file_ext in ['.glb', '.gltf']:
            show(solid, names=name)
            export_data = yacv.export(name)
            if export_data is None:
                logger.error("Could not export %s", name)
                sys.exit(1)
            glb_data, _ = export_data
            with open(config.export.filepath, 'wb') as f:
                f.write(glb_data)
            logger.info("Exported %s to %s (GLB format)", name, config.export.filepath)
            if cache_path is not None and not getattr(config, 'no_cache', False):
                cache_path = Path(cache_path) if not isinstance(cache_path, Path) else cache_path
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                with open(cache_path, 'wb') as f:
                    f.write(glb_data)
                logger.debug("Wrote cache %s", cache_path)
            return

        logger.error(
            "Unknown export file extension '%s'. Supported: .stl, .step, .stp, .3mf, .glb, .gltf.",
            file_ext
        )
        sys.exit(2)

    # Display path (no export): show solid, optionally write GLB to cache
    show(solid, names=name)
    if cache_path is not None and not getattr(config, 'no_cache', False):
        export_data = yacv.export(name)
        if export_data is not None:
            glb_data, _ = export_data
            cache_path = Path(cache_path) if not isinstance(cache_path, Path) else cache_path
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, 'wb') as f:
                f.write(glb_data)
            logger.debug("Wrote cache %s", cache_path)

    if config.server:
        if yacv.server_thread is None:
            yacv.start()
        logger.info("Server started. View %s in the web interface.", name)
        if yacv.server is not None:
            logger.info("Server URL: http://%s:%s", yacv.server.server_name, yacv.server.server_port)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down server...")
            yacv.stop()


def draw_part(path, config, aux=None, **face_kwargs):
    """
    Create and render a part by sweeping an LED circle face along a path.

    When --export is set, always sweeps and renders (and writes to cache unless --no-cache).
    Otherwise, uses cache when available (unless --no-cache); on cache hit skips the sweep.
    With --only-cache, only renders if a cached GLB exists; does not sweep on cache miss.

    Args:
        path: CadQuery Wire or Edge representing the sweep path
        config: Config object with tube_settings, export, server, name, no_cache, only_cache
        aux: Optional auxiliary path for sweep orientation
        **face_kwargs: Additional keyword arguments to pass to create_led_circle_face
                       (e.g., rotation_z). orient_to_path is set automatically.

    Returns:
        The swept solid/compound result, or None when rendering from cache or on only-cache miss.
    """
    cache_dir = getattr(config.server_settings, 'cache_dir', None)
    cache_stem = cache_key_for_part(
        config.name, path, aux=aux, face_kwargs=face_kwargs, config=config
    )
    cache_path = None
    if cache_dir is not None:
        cache_path = Path(cache_dir) / f"{cache_stem}.glb"

    # When --export is set: always sweep, render, and (unless --no-cache) write to cache
    if config.export.filepath:
        logger.debug("Export requested; sweeping and rendering (cache write if not --no-cache)")
        face_shape = create_led_circle_face(
            **config.tube_settings.to_led_circle_face_kwargs(
                orient_to_path=path,
                **face_kwargs
            )
        )
        result = sweep(face_shape, path, aux=aux)
        render_part(result, config, cache_path=cache_path)
        return result

    # --only-cache: only render if cached GLB exists
    if getattr(config, 'only_cache', False):
        if cache_path is None or not cache_path.exists():
            logger.info("Object not in cache (--only-cache); skipping sweep.")
            return None
        with open(cache_path, 'rb') as f:
            glb_bytes = f.read()
        logger.info("Rendering from cache: %s", cache_path)
        render_part(glb_bytes, config)
        return None

    # Cache hit: use cached GLB instead of sweeping
    if cache_path is not None and cache_path.exists() and not getattr(config, 'no_cache', False):
        with open(cache_path, 'rb') as f:
            glb_bytes = f.read()
        logger.info("Cache hit; rendering from cache: %s", cache_path)
        render_part(glb_bytes, config)
        return None

    # Cache miss: sweep and render, then write to cache if not --no-cache
    logger.debug("Cache miss; sweeping and rendering.")
    face_shape = create_led_circle_face(
        **config.tube_settings.to_led_circle_face_kwargs(
            orient_to_path=path,
            **face_kwargs
        )
    )
    result = sweep(face_shape, path, aux=aux)
    render_part(result, config, cache_path=cache_path)
    return result


def print_part_info(part: cq.Workplane, name: str, parameters: dict):
    """
    Print comprehensive information about a part.
    
    Args:
        part: The Workplane to analyze
        name: Name of the part
        parameters: Dictionary of parameters to print
    """
    solid = part.val()
    
    print("\n" + "="*80)
    print(f"{name.upper()} MODEL STRUCTURE")
    print("="*80)
    
    print("\n--- PARAMETERS ---")
    for key, value in parameters.items():
        print(f"  {key}: {value}")
    
    print("\n--- GEOMETRY PROPERTIES ---")
    print(f"  Volume: {solid.Volume():.2f} mm³")
    print(f"  Surface area: {solid.Area():.2f} mm²")
    
    # Bounding box
    bbox = solid.BoundingBox()
    print(f"  Bounding box:")
    print(f"    X: [{bbox.xmin:.2f}, {bbox.xmax:.2f}] mm (span: {bbox.xmax - bbox.xmin:.2f} mm)")
    print(f"    Y: [{bbox.ymin:.2f}, {bbox.ymax:.2f}] mm (span: {bbox.ymax - bbox.ymin:.2f} mm)")
    print(f"    Z: [{bbox.zmin:.2f}, {bbox.zmax:.2f}] mm (span: {bbox.zmax - bbox.zmin:.2f} mm)")
    
    # Topology information
    print(f"\n--- TOPOLOGY ---")
    print(f"  Number of faces: {len(solid.Faces())}")
    print(f"  Number of edges: {len(solid.Edges())}")
    print(f"  Number of vertices: {len(solid.Vertices())}")
    
    # Check if it's a valid solid
    print(f"\n--- VALIDATION ---")
    print(f"  Is valid solid: {solid.isValid()}")
    
    print("\n" + "="*80 + "\n")


# ============================================================================
# PATH CURVATURE ANALYSIS
# ============================================================================

def _normalize(v: np.ndarray) -> np.ndarray:
    """Normalize a vector, returning zero vector if magnitude is too small."""
    mag = np.linalg.norm(v)
    if mag < 1e-10:
        return np.zeros_like(v)
    return v / mag


def sample_path_curvature(path, num_samples: int = 50) -> list:
    """
    Sample the path and compute curvature data at each point.
    
    Uses finite differences to compute the curvature vector at each sample point.
    The curvature direction points toward the center of curvature (the normal vector
    in the Frenet-Serret frame).
    
    Args:
        path: A CadQuery Wire object representing the sweep path
        num_samples: Number of sample points along the path (default: 50)
        
    Returns:
        List of dicts, each containing:
          - t: parameter value (0 to 1)
          - point: (x, y, z) position tuple
          - tangent: unit tangent vector as numpy array
          - curvature: curvature magnitude (1/radius of curvature)
          - curvature_direction: unit vector pointing toward center of curvature
    """
    samples = []
    
    # Small delta for finite difference computation
    dt = 1.0 / (num_samples - 1)
    epsilon = dt * 0.01  # Small perturbation for derivative estimation
    
    for i in range(num_samples):
        t = i / (num_samples - 1)
        
        # Get position at t
        point = path.positionAt(t)
        point_tuple = (point.x, point.y, point.z)
        
        # Get tangent at t (already provided by CadQuery)
        tangent_vec = path.tangentAt(t)
        tangent = _normalize(np.array([tangent_vec.x, tangent_vec.y, tangent_vec.z]))
        
        # Compute curvature using finite differences of the tangent
        # Curvature = |dT/ds| where s is arc length
        # We approximate dT/dt and divide by |dr/dt| to get dT/ds
        
        t_prev = max(0, t - epsilon)
        t_next = min(1, t + epsilon)
        
        # Get tangents at neighboring points
        tangent_prev_vec = path.tangentAt(t_prev)
        tangent_next_vec = path.tangentAt(t_next)
        tangent_prev = _normalize(np.array([tangent_prev_vec.x, tangent_prev_vec.y, tangent_prev_vec.z]))
        tangent_next = _normalize(np.array([tangent_next_vec.x, tangent_next_vec.y, tangent_next_vec.z]))
        
        # Get positions at neighboring points for arc length estimation
        pos_prev = path.positionAt(t_prev)
        pos_next = path.positionAt(t_next)
        pos_prev_arr = np.array([pos_prev.x, pos_prev.y, pos_prev.z])
        pos_next_arr = np.array([pos_next.x, pos_next.y, pos_next.z])
        
        # Estimate arc length between prev and next
        arc_length = np.linalg.norm(pos_next_arr - pos_prev_arr)
        
        # Compute dT/ds (rate of change of tangent with respect to arc length)
        if arc_length > 1e-10:
            dT_ds = (tangent_next - tangent_prev) / arc_length
        else:
            dT_ds = np.zeros(3)
        
        # Curvature magnitude is |dT/ds|
        curvature = np.linalg.norm(dT_ds)
        
        # Curvature direction (normal) is the normalized dT/ds
        curvature_direction = _normalize(dT_ds)
        
        samples.append({
            't': t,
            'point': point_tuple,
            'tangent': tangent,
            'curvature': curvature,
            'curvature_direction': curvature_direction,
        })
    
    return samples


def compute_optimal_twist_angles(
    curvature_data: list,
    initial_rotation: float = 0.0,
    flexible_tolerance: float = 0.01,
    rigid_tolerance: float = 0.002,
    max_twist_rate: float = 2.0,
    smoothing_window: int = 7,
) -> list:
    """
    Compute optimal twist angles at each sample point to keep bends within tolerance.
    
    The LED strip cross-section is ribbon-like:
    - Flexible axis (local Y): Can bend easily in this direction
    - Rigid axis (local X): Cannot bend sharply in this direction
    
    When path curvature exceeds the rigid tolerance, the face must twist so that
    the flexible axis aligns with the curvature direction.
    
    This implementation uses parallel transport to maintain a consistent local
    coordinate frame, and computes incremental twist adjustments to avoid
    oscillation.
    
    Args:
        curvature_data: List of dicts from sample_path_curvature()
        initial_rotation: Starting rotation angle in degrees (default: 0)
        flexible_tolerance: Max curvature (1/mm) allowed in flexible direction (default: 0.01)
        rigid_tolerance: Max curvature (1/mm) allowed in rigid direction (default: 0.002)
        max_twist_rate: Maximum twist rate in degrees per mm of path length (default: 2.0)
        smoothing_window: Window size for Gaussian smoothing of twist angles (default: 7)
        
    Returns:
        List of twist angles in degrees, one for each sample point
    """
    n = len(curvature_data)
    if n == 0:
        return []
    
    if n == 1:
        return [initial_rotation]
    
    # Use parallel transport to maintain a consistent reference frame
    # This prevents the oscillation caused by recomputing the frame at each point
    prev_local_x = None
    prev_local_y = None
    
    # First pass: compute desired twist adjustments using parallel transport
    desired_twists = np.zeros(n)
    
    for i, sample in enumerate(curvature_data):
        curvature = sample['curvature']
        curvature_dir = sample['curvature_direction']
        tangent = sample['tangent']
        
        # Build/update local coordinate frame using parallel transport
        if i == 0:
            # Initialize the local frame
            if abs(tangent[2]) < 0.9:
                ref = np.array([0, 0, 1])
            else:
                ref = np.array([1, 0, 0])
            prev_local_x = _normalize(np.cross(tangent, ref))
            prev_local_y = _normalize(np.cross(tangent, prev_local_x))
        else:
            # Parallel transport: project previous frame onto plane perpendicular to tangent
            prev_local_x_proj = prev_local_x - np.dot(prev_local_x, tangent) * tangent
            proj_mag = np.linalg.norm(prev_local_x_proj)
            if proj_mag > 1e-6:
                prev_local_x = prev_local_x_proj / proj_mag
            prev_local_y = _normalize(np.cross(tangent, prev_local_x))
        
        # Skip twist computation if curvature is negligible
        if curvature < 1e-6:
            desired_twists[i] = 0.0
            continue
        
        # Project curvature direction onto the local XY plane
        curv_x = np.dot(curvature_dir, prev_local_x)
        curv_y = np.dot(curvature_dir, prev_local_y)
        
        # Calculate how much curvature is in the rigid direction at the current twist
        # The face is rotated by the accumulated twist, so we need to account for that
        current_twist_rad = math.radians(initial_rotation + sum(desired_twists[:i]))
        
        # Rotate the curvature components by the current twist
        cos_t = math.cos(current_twist_rad)
        sin_t = math.sin(current_twist_rad)
        rigid_component = abs(curvature * (curv_x * cos_t + curv_y * sin_t))
        
        if rigid_component > rigid_tolerance:
            # Need to twist to reduce rigid component
            # The curvature angle in the local frame
            curv_angle = math.atan2(curv_y, curv_x)
            
            # Target twist should align flexible axis (90° offset) with curvature
            # This is an incremental adjustment from the current accumulated twist
            target_total = math.degrees(curv_angle) - 90.0 - initial_rotation
            current_total = sum(desired_twists[:i])
            
            # Compute incremental twist needed
            delta = target_total - current_total
            
            # Normalize delta to [-180, 180]
            while delta > 180:
                delta -= 360
            while delta < -180:
                delta += 360
            
            desired_twists[i] = delta
        else:
            desired_twists[i] = 0.0
    
    # Second pass: compute cumulative twist with rate limiting
    cumulative_twist = np.zeros(n)
    cumulative_twist[0] = 0.0
    
    for i in range(1, n):
        # Get arc length for rate limiting
        prev_point = np.array(curvature_data[i - 1]['point'])
        curr_point = np.array(curvature_data[i]['point'])
        segment_length = max(np.linalg.norm(curr_point - prev_point), 0.1)
        
        # Target cumulative twist is the sum of all desired increments up to this point
        target = sum(desired_twists[:i + 1])
        
        # Limit the rate of change
        max_delta = max_twist_rate * segment_length
        delta = target - cumulative_twist[i - 1]
        
        # Clamp the change
        if abs(delta) > max_delta:
            delta = max_delta if delta > 0 else -max_delta
        
        cumulative_twist[i] = cumulative_twist[i - 1] + delta
    
    # Apply Gaussian smoothing for a gradual transition
    if smoothing_window > 1 and n > smoothing_window:
        kernel_size = smoothing_window
        sigma = kernel_size / 3.0
        x = np.arange(kernel_size) - kernel_size // 2
        kernel = np.exp(-x**2 / (2 * sigma**2))
        kernel = kernel / kernel.sum()
        
        padded = np.pad(cumulative_twist, kernel_size // 2, mode='edge')
        smoothed = np.convolve(padded, kernel, mode='valid')
        
        if len(smoothed) > n:
            smoothed = smoothed[:n]
        elif len(smoothed) < n:
            smoothed = np.pad(smoothed, (0, n - len(smoothed)), mode='edge')
        
        cumulative_twist = smoothed
    
    # Add initial rotation to get final twist angles
    twist_angles = cumulative_twist + initial_rotation
    
    return twist_angles.tolist()


def build_variable_twist_spine(
    path,
    twist_angles: list,
    spine_offset_radius: float = 5.0,
):
    """
    Build an auxiliary spine that encodes variable twist along the path.
    
    The auxiliary spine is used by CadQuery's sweep operation to control the
    orientation of the cross-section as it moves along the path. The spine
    runs parallel to the main path but offset perpendicular to the tangent,
    with the offset direction rotating according to the twist angles.
    
    Uses parallel transport to maintain a consistent local coordinate frame
    along curved paths, preventing frame discontinuities that can cause
    sweep failures.
    
    Args:
        path: A CadQuery Wire or Edge object representing the main sweep path
        twist_angles: List of twist angles in degrees, one for each sample point
        spine_offset_radius: Distance to offset the spine from the main path (default: 5.0)
        
    Returns:
        A CadQuery Edge object representing the auxiliary spine (spline)
    """
    n = len(twist_angles)
    if n < 2:
        raise ValueError("Need at least 2 twist angles to build auxiliary spine")
    
    spine_points = []
    prev_local_x = None
    prev_local_y = None
    
    for i in range(n):
        t = i / (n - 1)
        
        # Get position and tangent at this parameter
        pos = path.positionAt(t)
        tangent_vec = path.tangentAt(t)
        tangent = _normalize(np.array([tangent_vec.x, tangent_vec.y, tangent_vec.z]))
        
        if i == 0:
            # Initialize the local coordinate frame at the start
            # Choose a reference vector not parallel to the tangent
            if abs(tangent[2]) < 0.9:
                ref = np.array([0, 0, 1])
            else:
                ref = np.array([1, 0, 0])
            
            # Create initial local X and Y axes
            prev_local_x = _normalize(np.cross(tangent, ref))
            prev_local_y = _normalize(np.cross(tangent, prev_local_x))
        else:
            # Parallel transport: project previous local_x onto the plane
            # perpendicular to the current tangent to maintain consistency
            prev_local_x_proj = prev_local_x - np.dot(prev_local_x, tangent) * tangent
            proj_mag = np.linalg.norm(prev_local_x_proj)
            
            if proj_mag > 1e-6:
                prev_local_x = prev_local_x_proj / proj_mag
            # If projection is too small, keep previous (shouldn't happen for smooth paths)
            
            prev_local_y = _normalize(np.cross(tangent, prev_local_x))
        
        # Get the twist angle for this point and convert to radians
        twist_rad = math.radians(twist_angles[i])
        
        # Calculate the offset direction based on twist angle
        # The offset rotates in the plane perpendicular to the tangent
        offset_dir = prev_local_x * math.cos(twist_rad) + prev_local_y * math.sin(twist_rad)
        
        # Calculate the spine point
        spine_point = np.array([pos.x, pos.y, pos.z]) + offset_dir * spine_offset_radius
        spine_points.append(tuple(spine_point))
    
    # Create a spline through the spine points
    aux_spine = spline(spine_points)
    
    return aux_spine
