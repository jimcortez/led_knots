"""Slot 12 of the knotbook: K12a6 (Knot Atlas). 12 crossings, alternating.

Path source matches knotbook.ipynb cell "Knot 12a6": the catalogue DT code for
K12a6, converted by dowker_to_knot with relaxation.

Config: knot_configs/k12a6.yaml

NUM_POINTS is 600 rather than the 200 the lower slots use. Relaxation moves
strands past each other when the curve is coarser than the gaps between
strands, and at 12+ crossings 200 points is coarse enough that the relaxed
curve comes out as an entirely different, much simpler knot -- silently, with
no error. 600 was the smallest tested count whose relaxed curve still
identifies as K12a6. See test_knot_topology.py.
"""

import logging

from led_knots.core import draw_knot_points, knot_from_name
from led_knots.core.config import Config

logger = logging.getLogger(__name__)

NUM_POINTS = 600
RELAX_STEPS = 400


def build(config: Config) -> None:
    k = knot_from_name("K12a6", num_points=NUM_POINTS, relax_steps=RELAX_STEPS)
    draw_knot_points(k.points, config)
