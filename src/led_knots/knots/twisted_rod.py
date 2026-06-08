"""
Twisted rod knot creation using CadQuery.

Creates a straight vertical pipe with a 90-degree twist by sweeping a
cross-section along a path with an auxiliary spine that controls the rotation.
The end face is rotated 90 degrees around the z-axis from the first face.
"""

import logging
import math

from cadquery.func import spline

from led_knots.core import draw_part
from led_knots.core.config import Config

logger = logging.getLogger(__name__)


def create_helix_points(height, radius, total_rotation_deg, num_points=50):
    """
    Create points along a helix for the auxiliary spine.

    Args:
        height: Height of the helix (mm)
        radius: Radius of the helix (mm)
        total_rotation_deg: Total angular rotation of the helix (degrees)
        num_points: Number of points to generate

    Returns:
        List of (x, y, z) tuples representing helix points
    """
    points = []
    total_rotation_rad = math.radians(total_rotation_deg)

    for i in range(num_points):
        t = i / (num_points - 1)
        theta = t * total_rotation_rad
        x = radius * math.cos(theta)
        y = radius * math.sin(theta)
        z = t * height
        points.append((x, y, z))

    return points


def build(config: Config) -> None:
    height = config.output_bounds.height
    total_rotation = 90.0
    aux_radius = 10.0

    path = spline([(0, 0, 0), (0, 0, height)], tgts=[(0, 0, 1), (0, 0, 1)])

    helix_points = create_helix_points(
        height=height,
        radius=aux_radius,
        total_rotation_deg=total_rotation,
        num_points=50,
    )
    aux_spine = spline(helix_points)

    draw_part(path, config, aux=aux_spine)
