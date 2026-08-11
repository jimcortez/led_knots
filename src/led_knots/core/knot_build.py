"""Shared scaffold for turning pyknotid point data into a swept knot part.

Every pyknotid-derived knot module does the same four things: scale the raw
points into the configured build volume, open the loop into a spline, solve a
twist schedule against an offset aux spine, and hand both to draw_part. This
collapses that into one call so a knot module is just its path source.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

import numpy as np
from cadquery.func import spline

from .config import Config
from .path_utils import build_ribbon_aux_spine
from .pyknot_utils import scale_pyknot_points
from .utils import draw_part


def draw_knot_points(
    points: np.ndarray,
    config: Config,
    *,
    drop_last: int = 1,
    bounds: Optional[Tuple[float, float, float]] = None,
    preserve_aspect_ratio: bool = True,
    aux: bool = True,
    num_samples: int = 150,
    spine_offset_radius: float = 5.0,
) -> None:
    """
    Scale pyknotid points into the build volume, open the loop, and draw it.

    Args:
        points: Raw closed-loop points from pyknotid, shape (n, 3), in
            pyknotid's own units. The closing point must not be repeated.
        config: Render config; supplies output_bounds and tube_settings.
        drop_last: Trailing points to discard, which is what cuts the physical
            gap in the otherwise closed loop. 1 leaves a hairline seam; the
            ring uses 10 for a visible break.
        bounds: (width, height, length) to scale into, overriding
            config.output_bounds. Only needed by planar knots that want a
            different axis mapping than the default one.
        preserve_aspect_ratio: Passed to scale_pyknot_points. False stretches
            each axis independently to fill the box.
        aux: Build a twist-constrained aux spine (build_ribbon_aux_spine). Set
            False for paths with no meaningful curvature, or planar paths that
            need no twist schedule.
        num_samples: Samples along the path for the twist solver.
        spine_offset_radius: Radial offset of the aux spine, in mm.

    Raises:
        ValueError: From build_ribbon_aux_spine when the path bends faster
            than min_90_degree_twist_distance allows. The fix is a larger
            output_bounds in that knot's config, not a change here.
    """
    if bounds is None:
        bounds = (
            config.output_bounds.width,
            config.output_bounds.height,
            config.output_bounds.length,
        )
    width, height, length = bounds

    knot_points = scale_pyknot_points(
        points,
        width=width,
        height=height,
        length=length,
        padding=config.tube_settings.outer_radius,
        preserve_aspect_ratio=preserve_aspect_ratio,
    )

    path = spline(knot_points[:-drop_last] if drop_last else knot_points)

    if not aux:
        draw_part(path, config, rotation_z=0.0)
        return

    aux_spine, initial_rotation = build_ribbon_aux_spine(
        path,
        config,
        num_samples=num_samples,
        spine_offset_radius=spine_offset_radius,
    )

    draw_part(path, config, aux=aux_spine, rotation_z=initial_rotation)


__all__ = ["draw_knot_points"]
