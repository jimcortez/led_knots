"""Tests for segmented-print joint framing."""

from __future__ import annotations

import numpy as np
import pytest
from cadquery.func import spline
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.gp import gp_Pnt
from OCP.TopAbs import TopAbs_IN, TopAbs_ON

from led_knots.core.print_joint import (
    _joint_frame_at_point,
    _pin_radial_offset_mm,
    joint_radial_direction,
)
from led_knots.core.print_segmentation import build_segmented_tube_assembly, plan_segments, sample_wire_points
from led_knots.core.utils import build_tube_from_path


class _Joint:
    enabled = True
    style = "twin_pin"
    clearance_mm = 0.2
    pin_diameter_mm = 3.0
    pin_depth_mm = 4.0
    pin_radial_offset_mm = 17.0
    pin_spacing_mm = 7.0
    lap_overlap_mm = 4.0
    lap_step_height_mm = 3.0
    base_width_mm = 5.0


class _MaxPrintBounds:
    enabled = True
    width = 200.0
    length = 110.0
    height = 200.0
    clearance_mm = 2.0
    max_segments = 32
    path_samples = 51
    layout = "path"
    layout_gap_mm = 0.0
    joint = _Joint()


class _TubeSettings:
    outer_radius = 15.0
    face_type = "led_circle_tube"

    def to_led_circle_tube_face_kwargs(self, **kwargs):
        return dict(
            outer_radius=15.0,
            wall_thickness=4.0,
            inner_tube_diameter=10.0,
            inner_tube_wall_thickness=0.5,
            connector_width=0.5,
            **kwargs,
        )


class _SegmentConfig:
    max_print_bounds = _MaxPrintBounds()
    tube_settings = _TubeSettings()
    name = "rod"


def _solid_contains(shape, xyz) -> bool:
    classifier = BRepClass3d_SolidClassifier(shape.wrapped, gp_Pnt(*xyz), 1e-3)
    return classifier.State() in (TopAbs_IN, TopAbs_ON)


def test_joint_frame_matches_sweep_not_fixed_world_x() -> None:
    wire = spline([(0.0, 0.0, 0.0), (0.0, 0.0, 200.0)])
    _, tangent, x_dir = _joint_frame_at_point(wire, (0.0, 0.0, 100.0), num_samples=21)

    assert tangent[2] == pytest.approx(1.0, abs=1e-3)
    assert x_dir[1] == pytest.approx(1.0, abs=1e-3)
    assert x_dir[0] == pytest.approx(0.0, abs=1e-3)

    legacy_radial = joint_radial_direction(tangent)
    assert legacy_radial[0] == pytest.approx(1.0, abs=1e-3)
    assert abs(float(np.dot(legacy_radial, x_dir))) < 0.1


def test_segmented_twin_pins_align_with_tube_wall() -> None:
    height = 350.0
    path = spline([(0.0, 0.0, 0.0), (0.0, 0.0, height)])
    cfg = _SegmentConfig()
    pts, _ = sample_wire_points(path, n_samples=cfg.max_print_bounds.path_samples)
    plans = plan_segments(pts, cfg)
    assy = build_segmented_tube_assembly(path, cfg, build_tube_from_path)

    cut_idx = plans[0].end_idx
    cut_pt = pts[cut_idx]
    wire = spline(pts[: cut_idx + 1])
    _, tangent, x_dir = _joint_frame_at_point(wire, cut_pt, num_samples=cut_idx + 1)
    y_dir = np.cross(tangent, x_dir)

    base_x = _pin_radial_offset_mm(cfg.max_print_bounds.joint, cfg.tube_settings.outer_radius)
    spacing = float(cfg.max_print_bounds.joint.pin_spacing_mm)
    pin_centers = [
        np.asarray(cut_pt, dtype=float) + base_x * x_dir + 0.5 * spacing * y_dir,
        np.asarray(cut_pt, dtype=float) + base_x * x_dir - 0.2 * spacing * y_dir,
    ]

    male_shape = assy.children[0].shapes[0]
    for center in pin_centers:
        assert _solid_contains(male_shape, center), f"expected male pin near {center}"
