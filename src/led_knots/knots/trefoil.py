"""Slot 3 of the knotbook: 3_1, the trefoil. 3 crossings.

Path source matches knotbook.ipynb cell "Trefoil Knot (k3_1)":
pyknotid.make.trefoil, the closed-form parametric trefoil.

Config: knot_configs/k3_1-trefoil.yaml
"""

import logging

from pyknotid.make import trefoil as make_trefoil

from led_knots.core import draw_knot_points
from led_knots.core.config import Config

logger = logging.getLogger(__name__)


def build(config: Config) -> None:
    k = make_trefoil(num_points=200)
    draw_knot_points(k.points, config)
