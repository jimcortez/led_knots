"""
LED Knots - Mathematical knot models for LED strip housings.

This package provides tools for generating 3D printable mathematical knot models
designed to house LED strips. Built using the CadQuery CAD engine.

Subpackages:
    core: Core utilities for path analysis, rendering, and LED circle cross-sections
    knots: Individual knot generator modules

Example usage:
    # Run a specific knot generator
    python -m led_knots.knots.trefoil --export trefoil.stl
    
    # Use the core utilities in custom code
    from led_knots.core import create_led_circle_face, parse_args, render_part
"""

__version__ = "0.1.0"

# Re-export commonly used items from core
from .core import (
    # Utilities
    parse_args,
    render_part,
    scale_pyknot_points,
    sample_path_curvature,
    compute_optimal_twist_angles,
    build_variable_twist_spine,
    # LED Circle creation
    create_led_circle_face,
    create_led_circle_tube_face,
    create_solid_circle_face,
    create_square_face,
)

__all__ = [
    # Version
    '__version__',
    # Utilities
    'parse_args',
    'render_part',
    'scale_pyknot_points',
    'sample_path_curvature',
    'compute_optimal_twist_angles',
    'build_variable_twist_spine',
    # LED Circle creation
    'create_led_circle_face',
    'create_led_circle_tube_face',
    'create_solid_circle_face',
    'create_square_face',
]
