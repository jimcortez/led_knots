"""
Drain / vent hole auto-drilling for trapped resin cavities.

For each cavity flagged by the analyzer as ``is_trapped``, this drills a
straight cylinder along the build axis (world Z) through the part's
Z-extents at the cavity's (x, y) centroid. The cylinder cuts both the
top wall (vent — equalises pressure during peel) and the bottom wall
(drain — lets resin escape under gravity post-print).

This module ASSUMES the part has already been rotated into the build
orientation (i.e. ``orientation.auto_apply=True`` was used). Without
auto-apply, the build axis in the part frame is unknown and drilling
along world Z would produce holes in arbitrary directions relative to
how the print actually orients on the plate.
"""

from __future__ import annotations

import logging
import sys
from typing import List, Tuple, Union

import cadquery as cq
import numpy as np
from tqdm.auto import tqdm

from .analysis import Cavity
from .settings import DrainHoleSettings

logger = logging.getLogger(__name__)

_PartT = Union[cq.Workplane, cq.Solid, cq.Compound]


def _solid_of(part: _PartT):
    if hasattr(part, "val"):
        return part.val()
    return part


def drill_drain_holes(
    part: _PartT,
    cavities: List[Cavity],
    settings: DrainHoleSettings,
) -> Tuple[_PartT, List[Cavity]]:
    """Drill drain/vent cylinders through every trapped cavity.

    Returns ``(part_with_holes, drilled_cavities)``. ``drilled_cavities``
    is the subset of ``cavities`` that were actually drilled (cavities
    smaller than ``settings.min_cavity_volume_mm3`` are skipped).

    The cylinder spans ``(z_min - margin, z_max + margin)`` of the part's
    AABB so the boolean cut cleanly punctures both the top and bottom
    walls of any sealed pocket along the way.
    """
    if not settings.enabled:
        return part, []
    trapped = [
        c for c in cavities if c.is_trapped and c.volume_mm3 >= settings.min_cavity_volume_mm3
    ]
    if not trapped:
        return part, []

    solid = _solid_of(part)
    bb = solid.BoundingBox()
    z_min = float(bb.zmin) - settings.margin_mm
    z_max = float(bb.zmax) + settings.margin_mm
    height = z_max - z_min
    if height <= 0:
        logger.warning("drill_drain_holes: degenerate Z-extents (height=%.3f)", height)
        return part, []
    z_center = (z_min + z_max) / 2.0
    radius = settings.diameter_mm / 2.0

    drilled: List[Cavity] = []
    out_solid = solid
    bar = tqdm(
        trapped,
        total=len(trapped),
        desc="Drilling drain holes",
        unit="cavity",
        disable=not sys.stderr.isatty(),
    )
    for cav in bar:
        cx, cy, _ = cav.centroid
        # Build a Z-aligned cylinder centered at (cx, cy, z_center) using
        # CadQuery's high-level API. cq.Solid.makeCylinder builds along
        # +Z with its base at the provided origin, so shift so it spans
        # [z_min, z_max].
        cyl = cq.Solid.makeCylinder(
            radius,
            height,
            cq.Vector(float(cx), float(cy), z_min),
            cq.Vector(0.0, 0.0, 1.0),
        )
        try:
            out_solid = out_solid.cut(cyl)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "drill_drain_holes: cut failed for cavity vol=%.0f mm³ at (%.1f, %.1f, %.1f): %r",
                cav.volume_mm3,
                cx,
                cy,
                cav.centroid[2],
                exc,
            )
            continue
        drilled.append(cav)

    if not drilled:
        return part, []
    logger.info(
        "[optimize] drilled %d drain/vent hole(s), Ø%.2fmm",
        len(drilled),
        settings.diameter_mm,
    )
    return out_solid, drilled
