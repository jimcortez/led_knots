"""
Harmonious color palettes and assembly helpers for multi-part viewer display.
"""

from __future__ import annotations

import colorsys
from typing import List, Tuple

import cadquery as cq

ColorRGBA = Tuple[float, float, float, float]
ColorRGB = Tuple[float, float, float]

# Achromatic bases (e.g. preview.color '#b3b3b3') have s≈0; boost so parts differ in the viewer.
_MIN_PALETTE_SATURATION = 0.72
_MIN_PALETTE_VALUE = 0.55


class ColoredShape:
    """Wrap a tessellatable solid so cadquery-web-viewer picks up per-object face color."""

    def __init__(self, shape: object, color: ColorRGBA) -> None:
        self.wrapped = shape
        self.color = color


def palette_rgba(base_rgb: ColorRGB, n: int) -> List[ColorRGBA]:
    """
    Build *n* viewer face colors from a base RGB in [0, 1].

    For n >= 2, hues are evenly spaced on the wheel (diad, triad, etc.) while
    saturation and value follow the base color.
    """
    if n < 1:
        raise ValueError(f"palette_rgba requires n >= 1 (got {n})")
    r, g, b = (float(base_rgb[0]), float(base_rgb[1]), float(base_rgb[2]))
    if n == 1:
        return [(r, g, b, 1.0)]

    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if s < 0.12:
        s = _MIN_PALETTE_SATURATION
    if v < _MIN_PALETTE_VALUE:
        v = _MIN_PALETTE_VALUE
    out: List[ColorRGBA] = []
    for i in range(n):
        hi = (h + i / n) % 1.0
        ri, gi, bi = colorsys.hsv_to_rgb(hi, s, v)
        out.append((float(ri), float(gi), float(bi), 1.0))
    return out


def _is_tessellatable_solid(obj: object) -> bool:
    if isinstance(obj, str):
        return False
    if hasattr(obj, "BoundingBox"):
        return True
    # cadquery / OCP TopoDS solids
    type_name = type(obj).__name__
    return type_name in ("Solid", "Compound")


def iter_assembly_leaf_solids(assy: cq.Assembly) -> List[Tuple[str, object]]:
    """
    Return named leaf solids from an assembly in ``traverse()`` order.

    Skips the root node (non-solid ``obj``) and any non-tessellatable children.
    """
    parts: List[Tuple[str, object]] = []
    for name, node in assy.traverse():
        obj = node.obj
        if not _is_tessellatable_solid(obj):
            continue
        parts.append((str(name), obj))
    return parts


def colored_assembly_shapes(
    assy: cq.Assembly, base_rgb: ColorRGB
) -> Tuple[List[str], List[ColoredShape]]:
    """Assign a harmonious palette to each leaf solid in *assy*."""
    leaves = iter_assembly_leaf_solids(assy)
    colors = palette_rgba(base_rgb, len(leaves))
    names = [name for name, _ in leaves]
    shapes = [ColoredShape(solid, color) for (_, solid), color in zip(leaves, colors)]
    return names, shapes
