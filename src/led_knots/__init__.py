"""
LED Knots - Mathematical knot models for LED strip housings.

This package provides tools for generating 3D printable mathematical knot models
designed to house LED strips. Built using the CadQuery CAD engine.

Subpackages:
    core: Core utilities for path analysis, rendering, and LED circle cross-sections
    knots: Knot path builders (discovered by filename via knot_type in config)
    parts: Accessory part builders (discovered by filename via part_type in config)

Example usage:
    render-knot knot_configs/test_short_rod_led_tube.yaml
    render-part part_configs/hang_clamp.yaml

    from led_knots.core import create_led_circle_face, render_part
"""

__version__ = "0.1.0"

# Re-export commonly used items from core
from .core import (
    # Utilities
    parse_args,
    parse_render_args,
    render_part,
    scale_pyknot_points,
    dt_code_for,
    dowker_to_knot,
    knot_from_name,
    draw_knot_points,
    sample_path_curvature,
    compute_optimal_twist_angles,
    build_variable_twist_spine,
    # LED Circle creation
    create_led_circle_face,
    create_led_circle_quad_tube_face,
    create_led_circle_tube_face,
    create_solid_circle_face,
    create_square_face,
)

__all__ = [
    # Version
    '__version__',
    # Utilities
    'parse_args',
    'parse_render_args',
    'render_part',
    'scale_pyknot_points',
    'dt_code_for',
    'dowker_to_knot',
    'knot_from_name',
    'draw_knot_points',
    'sample_path_curvature',
    'compute_optimal_twist_angles',
    'build_variable_twist_spine',
    # LED Circle creation
    'create_led_circle_face',
    'create_led_circle_quad_tube_face',
    'create_led_circle_tube_face',
    'create_solid_circle_face',
    'create_square_face',
]
