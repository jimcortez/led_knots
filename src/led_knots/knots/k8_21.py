"""Slot 8 of the knotbook: 8_21. 8 crossings.

Path source matches knotbook.ipynb cell "Knot 8_21": pyknotid.make.k8_21.

Config: knot_configs/k8_21.yaml
"""

import logging

import pyknotid.make as mk

from led_knots.core import draw_knot_points
from led_knots.core.config import Config

logger = logging.getLogger(__name__)


def build(config: Config) -> None:
    k = mk.k8_21(num_points=200)
    draw_knot_points(k.points, config)
