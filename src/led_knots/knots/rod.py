"""
Rod knot creation using CadQuery.

Creates a straight vertical pipe by sweeping an LED circle cross-section
along a vertical path. The path construction is the focus here;
"""

import logging

from cadquery.func import spline

from led_knots.core import draw_part
from led_knots.core.config import Config

logger = logging.getLogger(__name__)


def build(config: Config) -> None:
    path = spline([(0, 0, 0), (0, 0, config.output_bounds.height)])
    draw_part(path, config)
