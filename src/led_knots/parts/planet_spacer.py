from __future__ import annotations

import cadquery as cq
from cadquery.func import *  # match project functional API style

from led_knots.core import render_part
from led_knots.core.config import Config


MM_PER_IN = 25.4


def build_planet_spacer(
    outer_diameter_in: float = 1.75,
    height_in: float = 0.25,
    hole_diameter_in: float = 0.25,
    fillet_mm: float = 0.75,
) -> cq.Solid:
    """
    Build a thick washer-like spacer.

    Local coordinates:
    - Spacer axis is +Z.
    - Solid is centered about Z=0 for nicer previews/exports.
    """
    outer_r = 0.5 * float(outer_diameter_in) * MM_PER_IN
    inner_r = 0.5 * float(hole_diameter_in) * MM_PER_IN
    height_mm = float(height_in) * MM_PER_IN

    if inner_r <= 0 or outer_r <= 0:
        raise ValueError("Radii must be positive.")
    if inner_r >= outer_r:
        raise ValueError("Hole radius must be smaller than outer radius.")
    if height_mm <= 0:
        raise ValueError("Height must be positive.")

    ring_face = face(wire(circle(outer_r)), wire(circle(inner_r)))
    solid = extrude(ring_face, (0, 0, height_mm)).moved(Location((0, 0, -height_mm / 2.0)))

    f = float(max(0.0, fillet_mm))
    if f > 0:
        wp = cq.Workplane("XY").add(solid)
        solid = wp.faces(">Z or <Z").edges().fillet(f).val()

    return solid


def build(config: Config) -> None:
    spacer = build_planet_spacer()
    render_part(spacer, config)
