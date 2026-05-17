from __future__ import annotations

import logging

import cadquery as cq
from cadquery.func import *  # match project functional API style

from led_knots.core import get_config, render_part

logger = logging.getLogger(__name__)


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
        try:
            # Fillet the circular edges on the top and bottom faces.
            solid = wp.faces(">Z or <Z").edges().fillet(f).val()
        except Exception as e:
            logger.warning(
                "Fillet(%.3f mm) failed; falling back to smaller fillet. (%s)", f, e
            )
            f2 = min(0.5, f * 0.66)
            if f2 > 0:
                try:
                    solid = wp.faces(">Z or <Z").edges().fillet(f2).val()
                except Exception as e2:
                    logger.warning("Fallback fillet(%.3f mm) also failed. (%s)", f2, e2)

    return solid


def main() -> None:
    config = get_config(name="Planet Spacer", description="Create and render a thick washer-like spacer")
    spacer = build_planet_spacer()
    render_part(spacer, config)


if __name__ == "__main__":
    main()
