"""
Ring knot creation using CadQuery.

Creates a ring knot by sweeping an LED circle cross-section
along a ring path. The path construction is the focus here;
"""

import logging
from cadquery.func import circle
from cadquery.occ_impl.shapes import spline
from pyknotid.spacecurves import Knot
from led_knots.core import draw_part, get_config, scale_pyknot_points
from pyknotid.make import unknot
import numpy as np

logger = logging.getLogger(__name__)

# Load configuration
config = get_config(
    name="Ring Knot",
    description="Create and render a ring knot"
)

spine_offset_radius = 5.0

# Generate the trefoil knot path using pyknotid, scaled to config output bounds.
# More points give a smoother path; 150 balances smoothness and build time.
# k = unknot(num_points=150)
num_points = 150
data = np.zeros((num_points, 3), dtype=np.float64)
ts = np.linspace(0, 2*np.pi, num_points)
data[:, 0] = 3*np.sin(ts)
data[:, 1] = 3*np.cos(ts)
# data[:, 2] = np.sin(3*ts)
k = Knot(data)

knot_points = scale_pyknot_points(
    k.points,
    width=config.output_bounds.width,
    height=config.output_bounds.width,
    length=config.output_bounds.height,
    padding=config.tube_settings.outer_radius,
    preserve_aspect_ratio=False,
)

# Open path (closed path causes face overlap)
path = spline(knot_points[:-1])

# Create, sweep, and render the part
draw_part(path, config, rotation_z=0.0)
