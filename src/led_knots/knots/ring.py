"""Slot 1 of the knotbook: k1_1, the unknot, drawn as a plain ring.

Path source matches knotbook.ipynb cell "Ring Knot (k1_1)": a parametric
circle of radius 3 in pyknotid units, wrapped in a Knot for consistency with
the other slots.

Config: knot_configs/k1_1-ring.yaml

Scaled with preserve_aspect_ratio=False into (width, width, height) so the
circle fills the plate, and opened with a 10-point gap so the ring reads as a
cut loop rather than a closed torus. No aux spine: the path is planar and the
twist schedule would be uniformly zero.
"""

import logging

import numpy as np
from pyknotid.spacecurves import Knot

from led_knots.core import draw_knot_points
from led_knots.core.config import Config

logger = logging.getLogger(__name__)


def build(config: Config) -> None:
    num_points = 200
    data = np.zeros((num_points, 3), dtype=np.float64)
    ts = np.linspace(0, 2 * np.pi, num_points)
    data[:, 0] = 3 * np.sin(ts)
    data[:, 1] = 3 * np.cos(ts)
    k = Knot(data)

    draw_knot_points(
        k.points,
        config,
        drop_last=10,
        bounds=(
            config.output_bounds.width,
            config.output_bounds.width,
            config.output_bounds.height,
        ),
        preserve_aspect_ratio=False,
        aux=False,
    )
