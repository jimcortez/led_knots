"""Slot 11 of the knotbook: K11a6 (Knot Atlas). 11 crossings, alternating.

Path source matches knotbook.ipynb cell "Knot 11a6": the catalogue DT code for
K11a6, converted by dowker_to_knot with relaxation.

Config: knot_configs/k11a6.yaml

num_points/relax_steps are verified settings: relaxation can push a strand
through another and silently yield a different knot, so these were checked
with Knot.identify(). See test_knot_topology.py.
"""

import logging

from led_knots.core import draw_knot_points, knot_from_name
from led_knots.core.config import Config

logger = logging.getLogger(__name__)

NUM_POINTS = 200
RELAX_STEPS = 400


def build(config: Config) -> None:
    k = knot_from_name("K11a6", num_points=NUM_POINTS, relax_steps=RELAX_STEPS)
    draw_knot_points(k.points, config)
