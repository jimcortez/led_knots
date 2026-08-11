"""Slot 5 of the knotbook: 5_2, the three-twist knot. 5 crossings.

Path source matches knotbook.ipynb cell "Knot 5: Three Twist (k5_2)":
pyknotid.make.k5_2.

Config: knot_configs/k5_2-three-twist.yaml
"""

import logging

import pyknotid.make as mk

from led_knots.core import draw_knot_points
from led_knots.core.config import Config

logger = logging.getLogger(__name__)


def build(config: Config) -> None:
    k = mk.k5_2(num_points=200)
    draw_knot_points(k.points, config)
