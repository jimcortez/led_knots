"""
Quarter turn knot creation using CadQuery.

Creates a quarter turn knot by sweeping an LED circle cross-section
along a 90-degree turn path. The path construction is the focus here;
the cross-section geometry is handled by the led_circle module.
"""

import logging
import cadquery as cq
from cadquery.func import *

from led_knots.core import parse_args, render_part
from led_knots.core import create_led_circle_face


def main():
    """Generate and render the quarter turn knot."""
    logging.basicConfig(level=logging.DEBUG)

    tube_radius = 15
    height = 100.0                    # Height of the pipe (mm)
    wall_thickness = 1.0             # Wall thickness (mm)
    oval_wall_thickness = 2.0

    args = parse_args(description="Create and render a quarter turn knot")

    path = spline([(0, 0, 0), (0, height, height)], tgts=[(0, 0, 1), (0, 1, 0)])

    faces = create_led_circle_face(
        tube_radius, 
        wall_thickness=wall_thickness, 
        oval_wall_thickness=oval_wall_thickness, 
        orient_to_path=path)

    result = sweep(faces, path)

    # Render the quarter turn knot based on command line arguments
    render_part(result, "Quarter Turn Knot", args)


if __name__ == "__main__":
    main()
