"""Slot 15 of the knotbook: K15n3 (Knot Atlas). 15 crossings, non-alternating.

Path source matches knotbook.ipynb cell "Knot 15n3": the catalogue DT code for
K15n3, converted by dowker_to_knot with relaxation. The DT code carries
negative entries, which is how the catalogue marks a non-alternating knot;
dowker_to_representation passes them through unchanged.

Config: knot_configs/k15n3.yaml

NUM_POINTS is 600 for the reason spelled out in k12a6.py, and this is the slot
where it matters most: at 200 points the relaxed curve identifies as 6_2 -- a
6-crossing knot standing in for a 15-crossing one, with nothing raised. See
test_knot_topology.py.
"""

import logging

from led_knots.core import draw_knot_points, knot_from_name
from led_knots.core.config import Config

logger = logging.getLogger(__name__)

NUM_POINTS = 600
RELAX_STEPS = 400


def build(config: Config) -> None:
    k = knot_from_name("K15n3", num_points=NUM_POINTS, relax_steps=RELAX_STEPS)
    draw_knot_points(k.points, config)
