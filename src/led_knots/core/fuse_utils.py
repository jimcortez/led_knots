"""
Fuse multi-solid CadQuery geometry into a single body.

Tube models such as braided rope and pyramid-studded tubes return a
``Compound`` of many solids for fast construction. Before SLA optimization,
export, or mesh analysis, those solids are boolean-fused into one body so
downstream stages see a single watertight-ish part rather than hundreds of
disconnected lumps.
"""

from __future__ import annotations

import heapq
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


def _fuse_solids_balanced(solids: list, *, name: str):
    """
    Fuse many solids by repeatedly unioning the two smallest remaining bodies.

    Keeps boolean operands similar in size (O(n log n) mesh work) instead of
    growing one accumulator through every input (O(n²) in the worst case).
    """
    n = len(solids)
    heap: list[tuple[float, int, object]] = [
        (_solid_volume(s), i, s) for i, s in enumerate(solids)
    ]
    heapq.heapify(heap)

    tie = n
    bar = tqdm(
        total=n - 1,
        desc=f"Fusing solids for {name}",
        unit="merge",
        disable=not sys.stderr.isatty(),
    )
    try:
        while len(heap) > 1:
            _, _, a = heapq.heappop(heap)
            _, _, b = heapq.heappop(heap)
            merged = fuse(a, b)
            tie += 1
            heapq.heappush(heap, (_solid_volume(merged), tie, merged))
            bar.update(1)
    finally:
        bar.close()

    return heap[0][2]


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
    merged = clean(_fuse_solids_balanced(solids, name=name))

    remaining = _solid_count(merged)
    logger.info(
        "Fuse complete for %s: %d solid(s) remaining.",
        name,
        remaining,
    )
    if remaining > 1:
        logger.warning(
            "%s: %d physically separate lumps remain after fuse "
            "(solids do not touch; STL will still tessellate as one file).",
            name,
            remaining,
        )

    if wrapper is not None:
        return wrapper.newObject([merged])
    return merged
