"""
Jog bend 3D knot creation using CadQuery.

Creates a jog bend 3D knot by sweeping an LED circle cross-section
along a 3D jog bend path. The path construction is the focus here;
the cross-section geometry is handled by the led_circle module.

The LED strip cross-section is ribbon-like (wider than tall):
- Flexible axis: Can bend around Y (short dimension)
- Rigid axis: Cannot bend sharply around X (wide dimension)
- Twist axis: Can twist around Z (along the path tangent)

This module implements orientation optimization to pre-twist the ribbon so that
bends occur in the flexible direction, respecting per-axis bending tolerances.
"""

import logging
from cadquery.func import *

from led_knots.core import (
    get_config,
    render_part,
    sample_path_curvature,
    compute_optimal_twist_angles,
    build_variable_twist_spine,
)
from led_knots.core import create_led_circle_face

logger = logging.getLogger(__name__)


def main():
    """Generate and render the jog bend 3D knot."""
    logging.basicConfig(level=logging.DEBUG)
    config = get_config(name="Jog Bend 3D Knot", description="Create and render a jog bend 3D knot")

    # Geometry parameters
    tube_radius = 15
    height = 100.0                    # Height of the pipe (mm)
    width = 100.0
    wall_thickness = 1.0             # Wall thickness (mm)
    min_oval_wall_thickness = 2.0
    oval_wall_thickness = 2.0

    # LED strip bending tolerances (curvature = 1/radius)
    # flexible_tolerance: Max curvature allowed in flexible direction (bending lengthwise)
    #   0.01 = 1/100mm = 100mm minimum bend radius
    # rigid_tolerance: Max curvature allowed in rigid direction (bending widthwise)
    #   0.002 = 1/500mm = 500mm minimum bend radius
    flexible_tolerance = 0.01
    rigid_tolerance = 0.002

    # Orientation optimization parameters
    num_samples = 50                  # Number of sample points for curvature analysis
    initial_rotation = 0.0           # Initial rotation of the face (degrees)
    spine_offset_radius = 5.0         # Distance to offset auxiliary spine from path (mm)
    max_twist_rate = 2.0              # Maximum twist rate (degrees per mm)
    smoothing_window = 7              # Window size for Gaussian smoothing

    # Create the sweep path
    path = spline(
        [
            (0, 0, 0), 
            (width / 2, width / 2, height / 2),  # Middle of jog
            (width, width, height)  # Final point
        ], 
        tgts=[
            (0, 0, 1), 
            (0, 1, 0),
            (0, 0, 1),
        ]  
    )

    # Analyze path curvature
    logger.info("Analyzing path curvature...")
    curvature_data = sample_path_curvature(path, num_samples=num_samples)

    # Log curvature info
    max_curvature = max(s['curvature'] for s in curvature_data)
    avg_curvature = sum(s['curvature'] for s in curvature_data) / len(curvature_data)
    logger.info("Path curvature: max=%.6f (1/mm), avg=%.6f (1/mm)", max_curvature, avg_curvature)
    logger.info(
        "Equivalent min radius: %.1f mm",
        1 / max_curvature if max_curvature > 0 else float('inf')
    )

    # Compute optimal twist angles to keep bends within tolerance
    logger.info("Computing optimal twist angles...")
    twist_angles = compute_optimal_twist_angles(
        curvature_data,
        initial_rotation=initial_rotation,
        flexible_tolerance=flexible_tolerance,
        rigid_tolerance=rigid_tolerance,
        max_twist_rate=max_twist_rate,
        smoothing_window=smoothing_window,
    )

    # Log twist angle info
    min_twist = min(twist_angles)
    max_twist = max(twist_angles)
    twist_range = max_twist - min_twist
    logger.info("Twist angles: min=%.1f°, max=%.1f°, range=%.1f°", min_twist, max_twist, twist_range)

    # Build auxiliary spine to control face orientation during sweep
    logger.info("Building auxiliary spine for orientation control...")
    aux_spine = build_variable_twist_spine(
        path,
        twist_angles,
        spine_offset_radius=spine_offset_radius,
    )

    # Create the cross-section face oriented to the path start
    # Note: rotation_z is handled by the twist angles now, so we use initial_rotation
    faces = create_led_circle_face(
        tube_radius, 
        wall_thickness=wall_thickness, 
        oval_wall_thickness=oval_wall_thickness, 
        orient_to_path=path,
        rotation_z=initial_rotation,
    )

    # Sweep the face along the path with auxiliary spine controlling orientation
    logger.info("Sweeping face along path with orientation control...")
    result = sweep(faces, path, aux=aux_spine)

    # Render the jog bend knot based on config (export, server, cache, etc.)
    render_part(result, config)


if __name__ == "__main__":
    main()
