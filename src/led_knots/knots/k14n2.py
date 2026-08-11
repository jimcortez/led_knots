"""Slot 14 of the knotbook: K14n2 (Knot Atlas). 14 crossings, non-alternating.

Path source matches knotbook.ipynb cell "Knot 14n2": the catalogue DT code for
K14n2, converted by dowker_to_knot with relaxation. The DT code carries
negative entries, which is how the catalogue marks a non-alternating knot;
dowker_to_representation passes them through unchanged.

Config: knot_configs/k14n2.yaml

NUM_POINTS is 600 for the reason spelled out in k12a6.py: at 200 points the
relaxed curve silently becomes a different, simpler knot. See
test_knot_topology.py.
"""

import logging

from led_knots.core import draw_knot_points, knot_from_name
from led_knots.core.config import Config

logger = logging.getLogger(__name__)

NUM_POINTS = 600
RELAX_STEPS = 400


def build(config: Config) -> None:
    k = knot_from_name("K14n2", num_points=NUM_POINTS, relax_steps=RELAX_STEPS)
    draw_knot_points(k.points, config)
