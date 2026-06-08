"""
Ring knot creation using CadQuery.

Creates a ring knot by sweeping an LED circle cross-section
along a ring path. The path construction is the focus here;
"""

import logging

import numpy as np
from cadquery.occ_impl.shapes import spline
from pyknotid.spacecurves import Knot

from led_knots.core import draw_part, scale_pyknot_points
from led_knots.core.config import Config

logger = logging.getLogger(__name__)


def build(config: Config) -> None:
    num_points = 150
    data = np.zeros((num_points, 3), dtype=np.float64)
    ts = np.linspace(0, 2 * np.pi, num_points)
    data[:, 0] = 3 * np.sin(ts)
    data[:, 1] = 3 * np.cos(ts)
    k = Knot(data)

    knot_points = scale_pyknot_points(
        k.points,
        width=config.output_bounds.width,
        height=config.output_bounds.width,
        length=config.output_bounds.height,
        padding=config.tube_settings.outer_radius,
        preserve_aspect_ratio=False,
    )

    path = spline(knot_points[:-10])
    draw_part(path, config, rotation_z=0.0)
