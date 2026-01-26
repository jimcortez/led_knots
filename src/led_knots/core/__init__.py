"""
Core utilities for LED knot generation.

This module provides shared utilities for creating knot models including:
- Command line argument parsing
- Path curvature analysis
- LED circle cross-section creation
- Model rendering and export
"""

from .utils import (
    parse_args,
    print_part_info,
    render_part,
    draw_part,
    scale_pyknot_points,
    sample_path_curvature,
    compute_optimal_twist_angles,
    build_variable_twist_spine,
    constant_up_frame_generator,
    tangent_based_frame_generator,
)

from .led_circle import (
    create_led_circle_face,
    create_dev_circle_face,
    create_dev_square_face,
)

from .config import get_config

__all__ = [
    # Utils
    'parse_args',
    'print_part_info',
    'render_part',
    'draw_part',
    'scale_pyknot_points',
    'sample_path_curvature',
    'compute_optimal_twist_angles',
    'build_variable_twist_spine',
    'constant_up_frame_generator',
    'tangent_based_frame_generator',
    # LED Circle
    'create_led_circle_face',
    'create_dev_circle_face',
    'create_dev_square_face',
    # Config
    'get_config',
]
