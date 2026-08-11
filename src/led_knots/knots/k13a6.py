"""Slot 13 of the knotbook: K13a6 (Knot Atlas). 13 crossings, alternating.

Path source matches knotbook.ipynb cell "Knot 13a6": the catalogue DT code for
K13a6, converted by dowker_to_knot with relaxation.

Config: knot_configs/k13a6.yaml

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
    k = knot_from_name("K13a6", num_points=NUM_POINTS, relax_steps=RELAX_STEPS)
    draw_knot_points(k.points, config)
