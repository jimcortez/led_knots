"""Tests for boolean fusion of multi-solid tube geometry."""

from __future__ import annotations

import cadquery as cq
import pytest
from cadquery.occ_impl.shapes import Compound

from led_knots.core.fuse_utils import (
    _assert_single_solid,
    _fuse_solids_map_reduce,
    fuse_part_solids,
)


def test_fuse_overlapping_solids_into_one_body() -> None:
    a = cq.Workplane("XY").box(2, 2, 2).val()
    b = cq.Workplane("XY").move(1, 0).box(2, 2, 2).val()
    compound = Compound.makeCompound([a, b])

    fused = fuse_part_solids(compound, name="overlap")

    assert len(fused.Solids()) == 1


def test_fuse_many_overlapping_solids_into_one_body() -> None:
    solids = [
        cq.Workplane("XY").move(i, 0).box(2, 2, 2).val()
        for i in range(5)
    ]
    compound = Compound.makeCompound(solids)

    fused = fuse_part_solids(compound, name="many")

    assert len(fused.Solids()) == 1


def test_fuse_single_solid_is_noop() -> None:
    box = cq.Workplane("XY").box(1, 1, 1).val()
    assert fuse_part_solids(box, name="single") is box


def test_fuse_assembly_is_noop() -> None:
    assy = cq.Assembly(name="test")
    assy.add(cq.Workplane("XY").box(1, 1, 1).val(), name="a")
    assert fuse_part_solids(assy, name="assy") is assy


def test_fuse_separate_lumps_raises() -> None:
    a = cq.Workplane("XY").box(2, 2, 2).val()
    b = cq.Workplane("XY").move(10, 0).box(2, 2, 2).val()
    compound = Compound.makeCompound([a, b])

    with pytest.raises(RuntimeError, match="physically separate lumps"):
        fuse_part_solids(compound, name="separate")


def test_map_reduce_quiet_matches_default_volume() -> None:
    solids = [
        cq.Workplane("XY").move(i, 0).box(2, 2, 2).val()
        for i in range(5)
    ]
    loud = _fuse_solids_map_reduce(list(solids), name="loud", show_progress=True)
    quiet = _fuse_solids_map_reduce(list(solids), name="quiet", show_progress=False)
    assert quiet.Volume() == pytest.approx(loud.Volume(), rel=1e-9)
    assert len(quiet.Solids()) == 1


def test_assert_single_solid_raises_on_multi_lump() -> None:
    a = cq.Workplane("XY").box(2, 2, 2).val()
    b = cq.Workplane("XY").move(10, 0).box(2, 2, 2).val()
    compound = Compound.makeCompound([a, b])
    with pytest.raises(RuntimeError, match="physically separate lumps"):
        _assert_single_solid(compound, name="lumps")


def test_assert_single_solid_passes_on_one_solid() -> None:
    solid = cq.Workplane("XY").box(2, 2, 2).val()
    _assert_single_solid(solid, name="ok")
