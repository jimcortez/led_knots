"""
Fuse multi-solid CadQuery geometry into a single body.

Tube models such as braided rope and pyramid-studded tubes return a
``Compound`` of many solids for fast construction. Before SLA optimization,
export, or mesh analysis, those solids are boolean-fused into one body so
downstream stages see a single watertight-ish part rather than hundreds of
disconnected lumps.
"""

from __future__ import annotations

import gc
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


def _release() -> None:
    """Drop refs that OCC keeps alive via Python wrappers.

    Boolean fuse/clean leave large intermediate B-rep shapes referenced until
    Python collects their wrappers; calling this after releasing a batch keeps
    peak memory bounded when fusing hundreds of solids (e.g. braid strands).
    """
    gc.collect()


def _assert_single_solid(shape, *, name: str) -> None:
    """Raise if a fused result is not exactly one connected solid.

    A multi-lump result means the inputs did not actually touch, so the fuse
    produced disconnected geometry that would export as a single STL while
    physically being several pieces. Fail loudly rather than ship that.
    """
    remaining = _solid_count(shape)
    if remaining > 1:
        raise RuntimeError(
            f"{name}: {remaining} physically separate lumps remain after fuse "
            "(solids do not touch)"
        )


def _fuse_solids_map_reduce(solids: list, *, name: str, show_progress: bool = True):
    """
    Fuse many solids in map-reduce rounds: pair neighbors, then pair results.

    Callers place the largest solid first (e.g. core tube) followed by many
    smaller bodies of nearly equal volume (e.g. braid strands). Pair
    ``solids[1:]`` so those smaller bodies merge together first; the lead
    solid is fused last (carried forward when a round has an odd count).

    ``show_progress=False`` suppresses the per-merge bar; streaming callers that
    fuse many small batches drive their own outer progress bar instead.
    """
    current = solids[1:] + [solids[0]]
    n = len(current)
    bar = tqdm(
        total=n - 1,
        desc=f"Fusing solids for {name}",
        unit="merge",
        disable=show_progress is False or not sys.stderr.isatty(),
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

    logger.info(
        "Fuse complete for %s: %d solid(s) remaining.",
        name,
        _solid_count(merged),
    )
    _assert_single_solid(merged, name=name)

    if wrapper is not None:
        return wrapper.newObject([merged])
    return merged
