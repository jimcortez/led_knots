"""Slot 2 of the knotbook: k2_1, the (2,1) torus knot.

Path source matches knotbook.ipynb cell "k2_1":
pyknotid.make.torus_knot(p=2, q=1).

Config: knot_configs/k2_1.yaml

There is no knot with 2 crossings, and the (2,1) torus knot is topologically
the unknot -- it is a once-twisted loop, not a distinct knot type. It fills
this slot deliberately, as the visual step between the flat ring (k1_1) and
the trefoil (k3_1).
"""

import logging

from pyknotid.make import torus_knot

from led_knots.core import draw_knot_points
from led_knots.core.config import Config

logger = logging.getLogger(__name__)


def build(config: Config) -> None:
    k = torus_knot(p=2, q=1, num=200)
    draw_knot_points(k.points, config)
