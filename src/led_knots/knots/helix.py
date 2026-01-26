"""
Helix knot creation using CadQuery.

Creates a helix knot by sweeping an LED circle cross-section
along a helical path. The path construction is the focus here;
"""

from cadquery import Wire
from led_knots.core import draw_part, get_config

# Load configuration
config = get_config(
    name="Helix Knot",
    description="Create and render a helix knot"
)

path = Wire.makeHelix(
    pitch=config.output_bounds.height / 2,
    height=config.output_bounds.height,
    radius=config.output_bounds.width / 2
)

# Create, sweep, and render the part
draw_part(path, config, rotation_z=45)
