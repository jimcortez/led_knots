"""
Ring knot creation using CadQuery.

Creates a ring knot by sweeping an LED circle cross-section
along a ring path. The path construction is the focus here;
"""

import logging
from cadquery.func import circle
from led_knots.core import draw_part, get_config

logger = logging.getLogger(__name__)

# Load configuration
config = get_config(
    name="Ring Knot",
    description="Create and render a ring knot"
)

path = circle(config.output_bounds.width)

# Create, sweep, and render the part
draw_part(path, config)
