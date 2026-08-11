"""Slot 9 of the knotbook: 9_2. 9 crossings.

Path source matches knotbook.ipynb cell "Knot 9 (k9_2)": the catalogue DT code
for 9_2, converted by dowker_to_knot with relaxation.

Config: knot_configs/k9_2.yaml

A different 9-crossing knot from k9_35.py, which stays in the repo but is
outside the 15-knot set.

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
    k = knot_from_name("9_2", num_points=NUM_POINTS, relax_steps=RELAX_STEPS)
    draw_knot_points(k.points, config)
