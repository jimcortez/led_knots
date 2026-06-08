"""
Quarter turn knot creation using CadQuery.

Creates a quarter turn knot by sweeping an LED circle cross-section
along a 90-degree turn path. The path construction is the focus here;
"""

import logging

from cadquery.func import spline

from led_knots.core import draw_part
from led_knots.core.config import Config

logger = logging.getLogger(__name__)


def build(config: Config) -> None:
    path = spline(
        [(0, 0, 0), (0, config.output_bounds.height, config.output_bounds.height)],
        tgts=[(0, 0, 1), (0, 1, 0)],
    )
    draw_part(path, config)
