"""
Sine wave knot creation using CadQuery.

Creates a sine wave knot by sweeping an LED circle cross-section
along a sine wave path. The path construction is the focus here;
"""

import logging
import math

from cadquery.func import spline

from led_knots.core import draw_part
from led_knots.core.config import Config

logger = logging.getLogger(__name__)


def build(config: Config) -> None:
    num_periods = 2
    points_per_period = 8
    num_points = num_periods * points_per_period + 1
    amplitude = config.output_bounds.width / 2

    sine_points = []
    for i in range(num_points):
        z = (i / (num_points - 1)) * config.output_bounds.height
        y = amplitude * math.sin(2 * math.pi * num_periods * (i / (num_points - 1)))
        sine_points.append((0, y, z))

    path = spline(
        sine_points,
        tgts=[(0, 0, 1), (0, 0, 1)],
    )
    draw_part(path, config)
