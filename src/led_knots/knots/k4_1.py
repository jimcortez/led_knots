"""Slot 4 of the knotbook: 4_1, the figure-eight knot. 4 crossings.

Path source matches knotbook.ipynb cell "Knot 4 (k4_1)": pyknotid.make.k4_1.

Config: knot_configs/k4_1-figure-eight.yaml
"""

import logging

import pyknotid.make as mk

from led_knots.core import draw_knot_points
from led_knots.core.config import Config

logger = logging.getLogger(__name__)


def build(config: Config) -> None:
    k = mk.k4_1(num_points=200)
    draw_knot_points(k.points, config)
