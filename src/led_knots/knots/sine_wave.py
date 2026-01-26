"""
Sine wave knot creation using CadQuery.

Creates a sine wave knot by sweeping an LED circle cross-section
along a sine wave path. The path construction is the focus here; the cross-section
geometry is handled by the led_circle module.
"""

import logging
import math
import cadquery as cq
from cadquery.func import *

from led_knots.core import parse_args, render_part
from led_knots.core import create_led_circle_face


def main():
    """Generate and render the sine wave knot."""
    logging.basicConfig(level=logging.DEBUG)

    tube_radius = 15
    height = 100.0                    # Height of the pipe (mm)
    width = 300.0
    wall_thickness = 1.0             # Wall thickness (mm)
    oval_wall_thickness = 2.0

    args = parse_args(description="Create and render a sine wave knot")

    # Generate points along a sine wave path
    # Number of periods (complete sine waves)
    num_periods = 2
    # Points per period (more points = smoother curve)
    points_per_period = 8
    num_points = num_periods * points_per_period + 1

    # Amplitude of the sine wave (half the width)
    amplitude = width / 2

    # Generate sine wave points
    sine_points = []
    for i in range(num_points):
        z = (i / (num_points - 1)) * height
        # Sine wave: y oscillates as z increases
        # Using 2*pi*num_periods to get the desired number of periods
        y = amplitude * math.sin(2 * math.pi * num_periods * (i / (num_points - 1)))
        sine_points.append((0, y, z))

    path = spline(
        sine_points,
        tgts=[(0, 0, 1), (0, 0, 1)]  # Start and end both pointing up in Z direction
    )

    faces = create_led_circle_face(
        tube_radius, 
        wall_thickness=wall_thickness, 
        oval_wall_thickness=oval_wall_thickness,
        orient_to_path=path,
        rotation_z=0)

    result = sweep(faces, path)

    # Render the sine wave knot based on command line arguments
    render_part(result, "Sine Wave Knot", args)


if __name__ == "__main__":
    main()
