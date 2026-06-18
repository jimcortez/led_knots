"""Tests for the finger pulse-sensor holder part."""

from __future__ import annotations

import sys

import pytest

from led_knots.core.config import Config
from led_knots.core.utils import parse_render_args
from led_knots.parts.finger_sensor_holder import (
    FingerSensorHolderParams,
    _build_base,
    _build_pedestal,
    _build_side_wall,
    build_finger_sensor_holder_parts,
    parameters_for_prototype_tuning,
    validate_solids_watertight,
)


def test_build_produces_two_watertight_solids() -> None:
    parts = build_finger_sensor_holder_parts()
    errors = validate_solids_watertight(
        [("holder", parts.holder), ("retention_plate", parts.retention_plate)]
    )
    assert errors == []
    assert parts.holder.isValid()
    assert parts.retention_plate.isValid()


def test_assembly_has_holder_and_retention_plate() -> None:
    parts = build_finger_sensor_holder_parts()
    assy = parts.to_assembly()
    assert assy.name == "Finger Sensor Holder"
    assert len(assy.children) == 2


def test_params_from_config_overlay(tmp_path, argv_guard) -> None:
    overlay = tmp_path / "part.yaml"
    overlay.write_text("part_type: finger_sensor_holder\n")
    sys.argv = ["test", str(overlay)]
    cfg = Config(args=parse_render_args())
    params = FingerSensorHolderParams.from_config(cfg)
    assert params.holder_width == 30.00
    assert params.sensor_pocket_diameter == 16.20


def test_side_walls_align_with_base_edges() -> None:
    p = FingerSensorHolderParams()
    base = _build_base(p)
    left = _build_side_wall(p, left=True)
    right = _build_side_wall(p, left=False)
    bb_base = base.BoundingBox()
    bb_left = left.BoundingBox()
    bb_right = right.BoundingBox()
    tol = 1e-3
    assert abs(bb_left.xmin - bb_base.xmin) < tol
    assert abs(bb_left.xmax - p.wall_thickness) < tol
    assert abs(bb_right.xmax - bb_base.xmax) < tol
    assert abs(bb_right.xmin - (p.holder_width - p.wall_thickness)) < tol
    assert abs(bb_left.ymin - bb_base.ymin) < tol
    assert abs(bb_left.ymax - bb_base.ymax) < tol
    assert abs(bb_left.zmin - bb_base.zmin) < tol


def test_pedestal_is_centered_on_base() -> None:
    p = FingerSensorHolderParams()
    ped = _build_pedestal(p)
    bb = ped.BoundingBox()
    tol = 1e-3
    assert abs(bb.xmin - p.pedestal_left_x) < tol
    assert abs(bb.xmax - p.pedestal_right_x) < tol
    assert abs(0.5 * (bb.xmin + bb.xmax) - p.lateral_center_x) < tol


def test_holder_encloses_sensor_pocket_region() -> None:
    parts = build_finger_sensor_holder_parts()
    bb = parts.holder.BoundingBox()
    p = FingerSensorHolderParams()
    assert bb.xmin <= p.pedestal_left_x
    assert bb.xmax >= p.pedestal_right_x
    assert bb.ymin <= 0.0
    assert bb.ymax >= p.holder_length - 1e-3
    assert bb.zmax >= p.base_thickness + p.wall_full_height - 2.0


def test_prototype_tuning_list_includes_sensor_pocket() -> None:
    names = parameters_for_prototype_tuning()
    assert "sensor_pocket_diameter" in names
    assert "finger_trough_depth" in names


def test_invalid_pedestal_length_raises() -> None:
    with pytest.raises(ValueError, match="pedestal_length"):
        build_finger_sensor_holder_parts(
            params=FingerSensorHolderParams(pedestal_length=0.0)
        )
