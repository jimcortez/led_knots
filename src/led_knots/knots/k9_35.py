"""
K9_35 knot creation using CadQuery.

Creates a 9_35 knot by sweeping an LED circle cross-section along a path built
from its Dowker-Thistlethwaite code.

Outside the 15-knot knotbook set; slot 9 there is 9_2 (see k9_2.py).

Uses build_ribbon_aux_spine(path, config) to constrain twist from config
(min_90_degree_twist_distance) and align bends with the flexible axis.
"""

import logging

from pyknotid.spacecurves import Knot
from cadquery.func import spline

from led_knots.core import draw_part, build_ribbon_aux_spine, scale_pyknot_points
from led_knots.core.config import Config

logger = logging.getLogger(__name__)


def build(config: Config) -> None:
    spine_offset_radius = 5.0

    dt_code_9_35 = [8, 12, 16, 14, 18, 4, 2, 6, 10]
    k = Knot.from_dowker_code(dt_code_9_35)
    knot_points = scale_pyknot_points(
        k.points,
        width=config.output_bounds.width,
        height=config.output_bounds.height,
        length=config.output_bounds.length,
        padding=config.tube_settings.outer_radius
    )

    path = spline(knot_points[:-1])

    aux_spine, initial_rotation = build_ribbon_aux_spine(
        path,
        config,
        num_samples=150,
        spine_offset_radius=spine_offset_radius,
    )

    draw_part(path, config, aux=aux_spine, rotation_z=initial_rotation)
