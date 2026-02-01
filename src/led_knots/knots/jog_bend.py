"""
Jog bend knot creation using CadQuery.

Creates a jog bend knot by sweeping an LED circle cross-section
along a 2D jog bend path. The path construction is the focus here;
"""

import logging
from cadquery.func import spline
from led_knots.core import draw_part, get_config

logger = logging.getLogger(__name__)

# Load configuration
config = get_config(
    name="Jog Bend Knot",
    description="Create and render a jog bend knot"
)

path = spline(
    [
        (0, 0, 0), 
        (0, config.output_bounds.width / 2, config.output_bounds.height / 2),  # Middle of jog
        (0, config.output_bounds.width, config.output_bounds.height)  # Final point
    ], 
    tgts=[(0, 0, 1), (0, 0, 1)]  # Start and end both pointing up in Z direction
)

# Create, sweep, and render the part
draw_part(path, config)
