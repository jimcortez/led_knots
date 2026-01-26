"""
Rod knot creation using CadQuery.

Creates a straight vertical pipe by sweeping an LED circle cross-section
along a vertical path. The path construction is the focus here;
"""

from cadquery.func import spline
from led_knots.core import draw_part, get_config

# Load configuration
config = get_config(
    name="Rod Knot",
    description="Create and render a rod knot (straight vertical pipe)"
)

path = spline([(0, 0, 0), (0, 0, config.output_bounds.height)])

# Create, sweep, and render the part
draw_part(path, config)
