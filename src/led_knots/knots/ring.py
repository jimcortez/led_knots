"""
Ring knot creation using CadQuery.

Creates a ring knot by sweeping an LED circle cross-section
along a ring path. The path construction is the focus here; the cross-section
geometry is handled by the led_circle module.
"""

import logging
import math
import cadquery as cq
from cadquery.func import *

from led_knots.core import parse_args, render_part
from led_knots.core import create_led_circle_face


def main():
    """Generate and render the ring knot."""
    logging.basicConfig(level=logging.DEBUG)

    tube_radius = 15
    height = 100.0                    # Height of the pipe (mm)
    width = 100.0
    wall_thickness = 1.0             # Wall thickness (mm)
    oval_wall_thickness = 2.0

    args = parse_args(description="Create and render a ring knot")

    path = circle(width)

    faces = create_led_circle_face(
        tube_radius, 
        wall_thickness=wall_thickness, 
        oval_wall_thickness=oval_wall_thickness, 
        orient_to_path=path,
        rotation_z=0)

    result = sweep(faces, path)

    # Render the ring knot based on command line arguments
    render_part(result, "Ring Knot", args)


if __name__ == "__main__":
    main()
