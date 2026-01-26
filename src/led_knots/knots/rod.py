"""
Rod knot creation using CadQuery.

Creates a straight vertical pipe by sweeping an LED circle cross-section
along a vertical path. The path construction is the focus here; the cross-section
geometry is handled by the led_circle module.
"""

import logging
import cadquery as cq
from cadquery.func import *

from led_knots.core import parse_args, print_part_info, render_part
from led_knots.core import create_led_circle_face


def create_faces(outer_size=14.5):
    """Create the LED circle face geometry."""
    # Ring profile: outer ring + inner ring (half size, same thickness)
    inner_size = outer_size * 0.90  # outer ring hole 90% the size of the outer
    thickness = outer_size - inner_size

    # Inner ring: half the size of outer, same thickness
    inner_ring_outer_r = outer_size / 2
    inner_ring_inner_r = inner_ring_outer_r - thickness

    # Outer ring
    outer_full = face(circle(outer_size))
    outer = outer_full - face(circle(inner_size))

    # Inner ring
    inner = face(circle(inner_ring_outer_r))

    # Inner hole
    inner_hole = plane(inner_ring_inner_r * 1.75, inner_ring_outer_r)

    # Bar
    rect_shape = plane(2 * outer_size, thickness) * outer_full

    # combine and return
    return clean(fuse(inner, outer, (rect_shape)) - inner_hole)


def main():
    """Generate and render the rod knot."""
    logging.basicConfig(level=logging.DEBUG)

    tube_radius = 15
    height = 100.0                    # Height of the pipe (mm)
    wall_thickness = 1.0             # Wall thickness (mm)
    oval_wall_thickness = 2.0

    args = parse_args(description="Create and render a rod knot (straight vertical pipe)")

    path = spline([(0, 0, 0), (0, 0, height)], tgts=[(0, 0, 1), (0, 0, 1)])

    face_shape = create_faces()
    face_plane = Plane(origin=path.startPoint(), normal=path.tangentAt(0))
    face_shape.move(Location(face_plane))

    result = sweep(face_shape, path)

    # Render the rod based on command line arguments
    render_part(result, "Rod Knot", args)


if __name__ == "__main__":
    main()
