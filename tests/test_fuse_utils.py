"""Tests for boolean fusion of multi-solid tube geometry."""

from __future__ import annotations

import cadquery as cq
from cadquery.occ_impl.shapes import Compound

from led_knots.core.fuse_utils import fuse_part_solids


def test_fuse_overlapping_solids_into_one_body() -> None:
    a = cq.Workplane("XY").box(2, 2, 2).val()
    b = cq.Workplane("XY").move(1, 0).box(2, 2, 2).val()
    compound = Compound.makeCompound([a, b])

    fused = fuse_part_solids(compound, name="overlap")

    assert len(fused.Solids()) == 1


def test_fuse_single_solid_is_noop() -> None:
    box = cq.Workplane("XY").box(1, 1, 1).val()
    assert fuse_part_solids(box, name="single") is box


def test_fuse_assembly_is_noop() -> None:
    assy = cq.Assembly(name="test")
    assy.add(cq.Workplane("XY").box(1, 1, 1).val(), name="a")
    assert fuse_part_solids(assy, name="assy") is assy
