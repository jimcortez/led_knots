"""
Jog bend knot creation using CadQuery.

Creates a jog bend knot by sweeping an LED circle cross-section
along a 2D jog bend path. The path construction is the focus here;
"""

import logging

from cadquery.func import spline

from led_knots.core import draw_part
from led_knots.core.config import Config

logger = logging.getLogger(__name__)


def build(config: Config) -> None:
    path = spline(
        [
            (0, 0, 0),
            (0, config.output_bounds.width / 2, config.output_bounds.height / 2),
            (0, config.output_bounds.width, config.output_bounds.height),
        ],
        tgts=[(0, 0, 1), (0, 0, 1)],
    )
    draw_part(path, config)
