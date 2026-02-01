"""
Quarter turn knot creation using CadQuery.

Creates a quarter turn knot by sweeping an LED circle cross-section
along a 90-degree turn path. The path construction is the focus here;
"""

import logging
from cadquery.func import spline
from led_knots.core import draw_part, get_config

logger = logging.getLogger(__name__)

# Load configuration
config = get_config(
    name="Quarter Turn Knot",
    description="Create and render a quarter turn knot"
)

path = spline(
    [(0, 0, 0), (0, config.output_bounds.height, config.output_bounds.height)],
    tgts=[(0, 0, 1), (0, 1, 0)]
)

# Create, sweep, and render the part
draw_part(path, config)
