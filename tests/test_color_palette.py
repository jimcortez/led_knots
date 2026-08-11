"""Tests for harmonious multi-part viewer palettes."""

from __future__ import annotations

import colorsys

import cadquery as cq
import pytest
from cadquery.func import box

from led_knots.core.color_palette import (
    ColoredShape,
    iter_assembly_leaf_solids,
    palette_rgba,
)


def _hue(rgb: tuple[float, float, float]) -> float:
    return colorsys.rgb_to_hsv(*rgb)[0]


def test_palette_n1_returns_base():
    base = (0.7, 0.7, 0.7)
    got = palette_rgba(base, 1)
    assert len(got) == 1
    assert got[0][:3] == pytest.approx(base)
    assert got[0][3] == 1.0


def test_palette_length_matches_n():
    base = (0.5, 0.6, 0.7)
    for n in (1, 2, 3, 5):
        assert len(palette_rgba(base, n)) == n


def test_palette_n2_complementary_hues():
    base = (0.9, 0.2, 0.2)
    colors = palette_rgba(base, 2)
    h0 = _hue(colors[0][:3])
    h1 = _hue(colors[1][:3])
    assert abs((h1 - h0) % 1.0 - 0.5) < 0.05 or abs((h1 - h0) % 1.0 + 0.5) < 0.05


def test_palette_gray_base_produces_distinct_colors():
    base = (0.7, 0.7, 0.7)
    colors = palette_rgba(base, 3)
    rgbs = [c[:3] for c in colors]
    assert len({tuple(round(x, 2) for x in rgb) for rgb in rgbs}) == 3


def test_palette_n3_triad_hues():
    base = (0.2, 0.5, 0.9)
    colors = palette_rgba(base, 3)
    hues = [_hue(c[:3]) for c in colors]
    assert abs((hues[1] - hues[0]) % 1.0 - 1 / 3) < 0.05
    assert abs((hues[2] - hues[1]) % 1.0 - 1 / 3) < 0.05


def test_palette_invalid_n():
    with pytest.raises(ValueError):
        palette_rgba((0.5, 0.5, 0.5), 0)


def test_colored_shape_exposes_color():
    wp = box(1, 1, 1)
    solid = wp.val() if hasattr(wp, "val") else wp
    c = ColoredShape(solid, (1.0, 0.0, 0.0, 1.0))
    assert c.color == (1.0, 0.0, 0.0, 1.0)
    assert hasattr(c, "wrapped")


def test_iter_assembly_leaf_solids_two_parts():
    assy = cq.Assembly("test")
    assy = assy.add(box(1, 1, 1), name="part_a")
    assy = assy.add(box(1, 1, 1).translate((3, 0, 0)), name="part_b")
    leaves = iter_assembly_leaf_solids(assy)
    assert len(leaves) == 2
    assert [n for n, _ in leaves] == ["part_a", "part_b"]
