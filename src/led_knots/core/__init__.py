"""
Core utilities for LED knot generation.

This module provides shared utilities for creating knot models including:
- Command line argument parsing
- Path curvature analysis and spine helpers (path_utils)
- LED circle cross-section creation
- Model rendering and export
"""

from .utils import (
    parse_args,
    parse_render_args,
    render_part,
    draw_part,
    build_tube_from_path,
)
from .pyknot_utils import (
    scale_pyknot_points,
    dt_code_for,
    dowker_to_representation,
    resample_closed_points,
    relax_knot_points,
    dowker_to_knot,
    knot_from_name,
)
from .path_utils import (
    sample_path_curvature,
    sample_path_for_profiles,
    compute_optimal_twist_angles,
    build_variable_twist_spine,
    build_ribbon_aux_spine,
)

from .led_circle import (
    create_led_circle_face,
    create_led_circle_quad_tube_face,
    create_led_circle_tube_face,
    create_solid_circle_face,
    create_square_face,
)

from .knot_build import draw_knot_points

from .config import get_config, load_config
from .cache_utils import cache_key_for_part

__all__ = [
    # Utils
    'parse_args',
    'parse_render_args',
    'render_part',
    'draw_part',
    'build_tube_from_path',
    'scale_pyknot_points',
    'dt_code_for',
    'dowker_to_representation',
    'resample_closed_points',
    'relax_knot_points',
    'dowker_to_knot',
    'knot_from_name',
    'sample_path_curvature',
    'sample_path_for_profiles',
    'compute_optimal_twist_angles',
    'build_variable_twist_spine',
    'build_ribbon_aux_spine',
    # Knot build scaffold
    'draw_knot_points',
    # LED Circle
    'create_led_circle_face',
    'create_led_circle_quad_tube_face',
    'create_led_circle_tube_face',
    'create_solid_circle_face',
    'create_square_face',
    # Config
    'get_config',
    'load_config',
    # Cache
    'cache_key_for_part',
]
