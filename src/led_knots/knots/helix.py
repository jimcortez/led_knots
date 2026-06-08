"""
Helix knot creation using CadQuery.

Creates a helix knot by sweeping an LED circle cross-section
along a helical path. The path construction is the focus here;
"""

import logging
import math

from cadquery import Wire

from led_knots.core import draw_part
from led_knots.core.config import Config

logger = logging.getLogger(__name__)


def calculate_helix_angle(pitch, radius, in_degrees=True):
    """
    Calculates the pitch angle of a helix.

    Args:
        pitch (float): The vertical distance of one full helix turn (mm).
        radius (float): The radius of the helix cylinder (mm).
        in_degrees (bool): If True, returns result in degrees. Otherwise, radians.

    Returns:
        float: The pitch angle.
    """
    if radius <= 0:
        raise ValueError("Radius must be greater than zero.")

    circumference = 2 * math.pi * radius
    angle_rad = math.atan(pitch / circumference)

    if in_degrees:
        return math.degrees(angle_rad)

    return angle_rad


def build(config: Config) -> None:
    path = Wire.makeHelix(
        pitch=config.output_bounds.height / 2,
        height=config.output_bounds.height,
        radius=config.output_bounds.width / 2,
    )

    rotation_z = 90 - calculate_helix_angle(
        config.output_bounds.height / 2,
        config.output_bounds.width / 2,
    )
    aux = Wire.makeHelix(
        pitch=config.output_bounds.height / 2,
        height=config.output_bounds.height,
        radius=config.output_bounds.width,
    )

    draw_part(path, config, aux=aux, rotation_z=rotation_z)
