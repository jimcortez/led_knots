"""
Helix knot creation using CadQuery.

Creates a helix knot by sweeping an LED circle cross-section
along a helical path. The path construction is the focus here; the cross-section
geometry is handled by the led_circle module.
"""

import logging
import math
from cadquery.func import *
import cadquery as cq

from led_knots.core import parse_args, render_part
from led_knots.core import create_led_circle_face


def main():
    """Generate and render the helix knot."""
    logging.basicConfig(level=logging.DEBUG)

    tube_radius = 15
    height = 200.0                    # Height of the pipe (mm)
    width = 100.0
    wall_thickness = 1.0             # Wall thickness (mm)
    oval_wall_thickness = 2.0

    args = parse_args(description="Create and render a helix knot")

    path = Wire.makeHelix(pitch=height / 2, height=height, radius=width / 2)

    faces = create_led_circle_face(
        tube_radius, 
        wall_thickness=wall_thickness, 
        oval_wall_thickness=oval_wall_thickness, 
        orient_to_path=path,
        rotation_z=45)

    result = sweep(faces, path)

    # Render the helix knot based on command line arguments
    render_part(result, "Helix Knot", args)


if __name__ == "__main__":
    main()
