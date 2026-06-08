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
    merged = solids[0]
    bar = tqdm(
        solids[1:],
        total=n - 1,
        desc=f"Fusing solids for {name}",
        unit="solid",
        disable=not sys.stderr.isatty(),
    )
    for body in bar:
        merged = fuse(merged, body)
    merged = clean(merged)

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
