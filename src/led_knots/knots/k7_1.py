"""Slot 7 of the knotbook: 7_1, the septoil. 7 crossings.

Path source matches knotbook.ipynb cell "Knot 7: Septoil (k7_1)": the
catalogue DT code for 7_1, converted by dowker_to_knot with relaxation.

Config: knot_configs/k7_1-septoil.yaml

This replaces an earlier TorusKnot(p=7, q=2) construction. 7_1 *is* the (7,2)
torus knot, so the topology is unchanged, but the relaxed DT layout reads much
closer to the Knot Atlas drawing than the analytic torus winding did.

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
    k = knot_from_name("7_1", num_points=NUM_POINTS, relax_steps=RELAX_STEPS)
    draw_knot_points(k.points, config)
