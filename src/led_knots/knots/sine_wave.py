"""
Sine wave knot creation using CadQuery.

Creates a sine wave knot by sweeping an LED circle cross-section
along a sine wave path. The path construction is the focus here;
"""

import logging
import math
from cadquery.func import spline

from led_knots.core import draw_part, get_config

logger = logging.getLogger(__name__)

# Load configuration
config = get_config(
    name="Sine Wave Knot",
    description="Create and render a sine wave knot"
)

# Generate points along a sine wave path
# Number of periods (complete sine waves)
num_periods = 2
# Points per period (more points = smoother curve)
points_per_period = 8
num_points = num_periods * points_per_period + 1

# Amplitude of the sine wave (half the width)
amplitude = config.output_bounds.width / 2

# Generate sine wave points
sine_points = []
for i in range(num_points):
    z = (i / (num_points - 1)) * config.output_bounds.height
    # Sine wave: y oscillates as z increases
    # Using 2*pi*num_periods to get the desired number of periods
    y = amplitude * math.sin(2 * math.pi * num_periods * (i / (num_points - 1)))
    sine_points.append((0, y, z))

path = spline(
    sine_points,
    tgts=[(0, 0, 1), (0, 0, 1)]  # Start and end both pointing up in Z direction
)

# Create, sweep, and render the part
draw_part(path, config)
