"""
Jog bend 3D knot creation using CadQuery.

Creates a jog bend 3D knot by sweeping an LED circle cross-section
along a 3D jog bend path. The path construction is the focus here;
the cross-section geometry is handled by the led_circle module.

The LED strip cross-section is ribbon-like (wider than tall):
- Flexible axis: Can bend around Y (short dimension)
- Rigid axis: Cannot bend sharply around X (wide dimension)
- Twist axis: Can twist around Z (along the path tangent)

Uses build_ribbon_aux_spine(path, config) to constrain twist from config
(min_90_degree_twist_distance) and align bends with the flexible axis.
"""

import logging

from cadquery.func import spline

from led_knots.core import (
    draw_part,
    get_config,
    build_ribbon_aux_spine,
)

logger = logging.getLogger(__name__)

config = get_config(
    name="Jog Bend 3D Knot",
    description="Create and render a jog bend 3D knot",
)

# Use output bounds from config (path must fit; twist must fit min_90_degree_twist_distance or error is raised)
width = config.output_bounds.width
height = config.output_bounds.height
spine_offset_radius = 5.0

# Create the sweep path from config bounds
path = spline(
    [
        (0, 0, 0),
        (width / 2, width / 2, height / 2),
        (width, width, height),
    ],
    tgts=[
        (0, 0, 1),
        (0, 1, 0),
        (0, 0, 1),
    ],
)

# Raises ValueError if twist cannot be achieved within min_90_degree_twist_distance
aux_spine, initial_rotation = build_ribbon_aux_spine(
    path,
    config,
    num_samples=40,
    spine_offset_radius=spine_offset_radius,
)

# Create, sweep, and render the part (draw_part uses path + aux + rotation_z)
draw_part(path, config, aux=aux_spine, rotation_z=initial_rotation)
