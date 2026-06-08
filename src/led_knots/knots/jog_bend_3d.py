"""
Jog bend 3D knot creation using CadQuery.

Creates a jog bend 3D knot by sweeping an LED circle cross-section
along a 3D jog bend path. The path construction is the focus here;
the cross-section geometry is handled by the led_circle module.

Uses build_ribbon_aux_spine(path, config) to constrain twist from config
(min_90_degree_twist_distance) and align bends with the flexible axis.
"""

import logging

from cadquery.func import spline

from led_knots.core import draw_part, build_ribbon_aux_spine
from led_knots.core.config import Config

logger = logging.getLogger(__name__)


def build(config: Config) -> None:
    width = config.output_bounds.width
    height = config.output_bounds.height
    spine_offset_radius = 5.0

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

    aux_spine, initial_rotation = build_ribbon_aux_spine(
        path,
        config,
        num_samples=40,
        spine_offset_radius=spine_offset_radius,
    )

    draw_part(path, config, aux=aux_spine, rotation_z=initial_rotation)
