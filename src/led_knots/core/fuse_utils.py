"""
Fuse multi-solid CadQuery geometry into a single body.

Tube models such as braided rope and pyramid-studded tubes return a
``Compound`` of many solids for fast construction. Before SLA optimization,
export, or mesh analysis, those solids are boolean-fused into one body so
downstream stages see a single watertight-ish part rather than hundreds of
disconnected lumps.
"""

from __future__ import annotations

import logging
import sys
from typing import Union

import cadquery as cq
from cadquery.func import clean, fuse
from tqdm.auto import tqdm

logger = logging.getLogger(__name__)

_PartT = Union[cq.Workplane, cq.Solid, cq.Compound, cq.Assembly]


def _solid_count(shape) -> int:
    if isinstance(shape, cq.Compound):
        return len(shape.Solids())
    return 1


def _solid_volume(solid) -> float:
    vol = solid.Volume()
    if vol > 0:
        return vol
    bb = solid.BoundingBox()
    return (bb.xmax - bb.xmin) * (bb.ymax - bb.ymin) * (bb.zmax - bb.zmin)


def _fuse_solids_map_reduce(solids: list, *, name: str):
    """
    Fuse many solids in map-reduce rounds: pair neighbors, then pair results.

    Solids are sorted by ascending volume so smaller bodies merge together
    first and the largest solid is fused last (carried forward when a round
    has an odd count).
    """
    current = sorted(solids, key=_solid_volume)
    n = len(current)
    bar = tqdm(
        total=n - 1,
        desc=f"Fusing solids for {name}",
        unit="merge",
        disable=not sys.stderr.isatty(),
    )
    try:
        while len(current) > 1:
            nxt: list = []
            i = 0
            while i < len(current):
                if i + 1 < len(current):
                    nxt.append(clean(fuse(current[i], current[i + 1])))
                    bar.update(1)
                    i += 2
                else:
                    nxt.append(current[i])
                    i += 1
            current = nxt
    finally:
        bar.close()

    return current[0]


def fuse_part_solids(part: _PartT, *, name: str = "part") -> _PartT:
    """
    Boolean-fuse every solid in ``part`` into one body when needed.

    Assemblies are returned unchanged (segmentation handles those separately).
    Single-solid inputs are returned unchanged.
    """
    if isinstance(part, cq.Assembly):
        return part

    wrapper: cq.Workplane | None = None
    if hasattr(part, "val"):
        wrapper = part
        solid = part.val()
    else:
        solid = part

    if not isinstance(solid, cq.Compound):
        return part

    solids = list(solid.Solids())
    n = len(solids)
    if n <= 1:
        if n == 1 and wrapper is not None:
            return wrapper.newObject([solids[0]])
        return solids[0] if n == 1 else part

    logger.info("Fusing %d solids into one body for %s...", n, name)
    merged = _fuse_solids_map_reduce(solids, name=name)

    remaining = _solid_count(merged)
    logger.info(
        "Fuse complete for %s: %d solid(s) remaining.",
        name,
        remaining,
    )
    if remaining > 1:
        raise RuntimeError(
            f"{name}: {remaining} physically separate lumps remain after fuse "
            "(solids do not touch)"
        )

    if wrapper is not None:
        return wrapper.newObject([merged])
    return merged
