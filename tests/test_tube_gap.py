"""Tests for the tube_gap boolean-subtraction feature."""

from __future__ import annotations

import math

import numpy as np
import pytest
from cadquery.func import spline
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.gp import gp_Pnt
from OCP.TopAbs import TopAbs_IN, TopAbs_ON

from led_knots.core.cache_utils import config_settings_hash
from led_knots.core.print_segmentation import build_segmented_tube_assembly
from led_knots.core.tube_gap import (
    apply_tube_gap,
    build_gap_cutter,
    compute_gap_placement,
    gap_cutter_radius,
    open_loop_with_gap,
)
from led_knots.core.utils import build_tube_from_path

from .conftest import load_test_config


class _TubeGap:
    enabled = True
    gap_length_mm = 20.0
    center_fraction = 0.0
    cutter_radius_mm = None


class _TubeSettings:
    outer_radius = 5.0
    face_type = "solid_circle"

    def to_led_circle_face_kwargs(self, **kwargs):
        return dict(outer_radius=5.0, wall_thickness=0.0, **kwargs)


class _GapConfig:
    tube_gap = _TubeGap()
    tube_settings = _TubeSettings()
    render_stats = None
    name = "gap-test"


def _solid_contains(shape, xyz) -> bool:
    classifier = BRepClass3d_SolidClassifier(shape.wrapped, gp_Pnt(*xyz), 1e-3)
    return classifier.State() in (TopAbs_IN, TopAbs_ON)


def _straight_path(length: float = 100.0):
    return spline([(0.0, 0.0, 0.0), (0.0, 0.0, length)])


def test_placement_centered_on_straight_path() -> None:
    placement = compute_gap_placement(_straight_path(100.0), 20.0, 0.0)

    assert placement.total_length_mm == pytest.approx(100.0, abs=0.01)
    assert placement.gap_length_mm == pytest.approx(20.0)
    assert placement.s0 == pytest.approx(40.0, abs=0.01)
    assert placement.s1 == pytest.approx(60.0, abs=0.01)
    assert placement.mid_point == pytest.approx((0.0, 0.0, 50.0), abs=0.01)
    assert placement.tangent == pytest.approx((0.0, 0.0, 1.0), abs=1e-3)


def test_placement_clamps_center_but_preserves_gap_length() -> None:
    # center_fraction=0.5 targets the path end; the center must shift inward
    # so the full 20 mm gap still fits.
    placement = compute_gap_placement(_straight_path(100.0), 20.0, 0.5)

    assert placement.gap_length_mm == pytest.approx(20.0)
    assert placement.s1 == pytest.approx(100.0, abs=0.01)
    assert placement.s0 == pytest.approx(80.0, abs=0.01)


def test_placement_clamps_oversized_gap() -> None:
    placement = compute_gap_placement(_straight_path(100.0), 500.0, 0.0)
    assert placement.gap_length_mm == pytest.approx(80.0, abs=0.01)


def test_straight_tube_cut_splits_and_removes_expected_volume() -> None:
    cfg = _GapConfig()
    path = _straight_path(100.0)
    tube = build_tube_from_path(path, cfg)

    result = apply_tube_gap(tube, path, cfg)

    solids = result.Solids()
    assert len(solids) == 2
    expected_volume = math.pi * 5.0**2 * 80.0
    total_volume = sum(s.Volume() for s in solids)
    assert total_volume == pytest.approx(expected_volume, rel=0.02)
    assert not _solid_contains(result, (0.0, 0.0, 50.0))
    assert _solid_contains(result, (0.0, 0.0, 39.0))
    assert _solid_contains(result, (0.0, 0.0, 61.0))


def test_curved_path_gap_measured_along_arc() -> None:
    # Quarter-plus arc of radius 60: a chord-aligned cutter would remove the
    # wrong span; the swept cutter must produce the gap in arc length.
    radius = 60.0
    angles = np.linspace(0.0, 0.6 * math.pi, 41)
    pts = [(radius * math.cos(a), radius * math.sin(a), 0.0) for a in angles]
    path = spline(pts)
    cfg = _GapConfig()
    tube = build_tube_from_path(path, cfg)

    result = apply_tube_gap(tube, path, cfg)
    placement = compute_gap_placement(path, 20.0, 0.0)

    eps = 1.5
    for s in np.linspace(0.0, placement.total_length_mm, 121):
        a = s / radius
        pt = (radius * math.cos(a), radius * math.sin(a), 0.0)
        if placement.s0 + eps < s < placement.s1 - eps:
            assert not _solid_contains(result, pt), f"expected gap at arc length {s:.1f}"
        elif s < placement.s0 - eps or s > placement.s1 + eps:
            assert _solid_contains(result, pt), f"expected tube at arc length {s:.1f}"


def test_cutter_radius_auto_and_override() -> None:
    cfg = _GapConfig()
    assert gap_cutter_radius(cfg) == pytest.approx(7.5)

    class _Override(_TubeGap):
        cutter_radius_mm = 12.0

    class _Cfg(_GapConfig):
        tube_gap = _Override()

    assert gap_cutter_radius(_Cfg()) == pytest.approx(12.0)


def test_apply_tube_gap_noop_when_disabled() -> None:
    class _Disabled(_TubeGap):
        enabled = False

    class _Cfg(_GapConfig):
        tube_gap = _Disabled()

    path = _straight_path(100.0)
    tube = build_tube_from_path(path, _Cfg())
    assert apply_tube_gap(tube, path, _Cfg()) is tube


def _circle_points(radius: float, n: int, repeat_closing: bool = False):
    angles = np.linspace(0.0, 2.0 * math.pi, n, endpoint=False)
    pts = [(radius * math.cos(a), radius * math.sin(a), 0.0) for a in angles]
    if repeat_closing:
        pts.append(pts[0])
    return pts


def test_open_loop_with_gap_trims_expected_arc() -> None:
    radius = 40.0
    pts = open_loop_with_gap(_circle_points(radius, 72), 20.0, 0.0)

    arr = np.asarray(pts)
    total = float(np.linalg.norm(np.diff(arr, axis=0), axis=1).sum())
    circumference = 2.0 * math.pi * radius
    # Chord-length total of the trimmed polyline ≈ circumference − gap.
    assert total == pytest.approx(circumference - 20.0, rel=0.01)
    # The path is open: endpoints sit at the gap edges, ~20 mm apart in arc.
    end_gap_chord = 2.0 * radius * math.sin(0.5 * 20.0 / radius)
    assert float(np.linalg.norm(arr[0] - arr[-1])) == pytest.approx(end_gap_chord, rel=0.02)
    # Gap is centered opposite the loop start (center_fraction=0). The chord
    # midpoint between the gap edges sits at R·cos(gap/2R) inside the circle.
    gap_mid = 0.5 * (arr[0] + arr[-1])
    assert gap_mid[0] == pytest.approx(-radius * math.cos(0.5 * 20.0 / radius), abs=0.3)
    assert gap_mid[1] == pytest.approx(0.0, abs=0.3)


def test_open_loop_with_gap_handles_repeated_closing_point() -> None:
    a = open_loop_with_gap(_circle_points(40.0, 72), 20.0, 0.0)
    b = open_loop_with_gap(_circle_points(40.0, 72, repeat_closing=True), 20.0, 0.0)
    assert np.allclose(np.asarray(a), np.asarray(b))


def test_open_loop_with_gap_wraps_gap_across_seam() -> None:
    # center_fraction=±0.5 puts the gap across the original loop seam.
    radius = 40.0
    pts = open_loop_with_gap(_circle_points(radius, 72), 20.0, 0.5)
    arr = np.asarray(pts)
    gap_mid = 0.5 * (arr[0] + arr[-1])
    assert gap_mid[0] == pytest.approx(radius * math.cos(0.5 * 20.0 / radius), abs=0.3)
    assert gap_mid[1] == pytest.approx(0.0, abs=0.3)
    total = float(np.linalg.norm(np.diff(arr, axis=0), axis=1).sum())
    assert total == pytest.approx(2.0 * math.pi * radius - 20.0, rel=0.01)


def test_closed_loop_tube_via_point_gap_is_single_clean_solid() -> None:
    radius = 40.0
    cfg = _GapConfig()
    pts = open_loop_with_gap(_circle_points(radius, 72), 20.0, 0.0)
    path = spline(pts)
    tube = build_tube_from_path(path, cfg)
    shape = tube.val() if hasattr(tube, "val") else tube

    assert len(shape.Solids()) == 1
    # Gap region (opposite the start) is empty; rest of the ring has material.
    assert not _solid_contains(shape, (-radius, 0.0, 0.0))
    assert _solid_contains(shape, (radius, 0.0, 0.0))
    assert _solid_contains(shape, (0.0, radius, 0.0))
    assert _solid_contains(shape, (0.0, -radius, 0.0))


def test_apply_tube_gap_rejects_closed_path() -> None:
    cfg = _GapConfig()
    path = spline(_circle_points(40.0, 72, repeat_closing=True))
    with pytest.raises(RuntimeError, match="closed loop"):
        apply_tube_gap(None, path, cfg)


def test_segmented_assembly_gap_only_in_overlapping_segment() -> None:
    # Reuse the segmentation fake-config shape from test_print_joint.
    from .test_print_joint import _SegmentConfig

    class _Cfg(_SegmentConfig):
        tube_gap = _TubeGap()
        render_stats = None

    height = 350.0
    path = spline([(0.0, 0.0, 0.0), (0.0, 0.0, height)])
    assy = build_segmented_tube_assembly(path, _Cfg(), build_tube_from_path)

    placement = compute_gap_placement(path, 20.0, 0.0)
    mid_z = 0.5 * (placement.s0 + placement.s1)
    wall_x = 0.5 * (
        _Cfg.tube_settings.outer_radius
        + (_Cfg.tube_settings.outer_radius - 4.0)
    )

    gap_hit = False
    outside_hit = False
    for child in assy.children:
        shape = child.shapes[0]
        if _solid_contains(shape, (wall_x, 0.0, 10.0)) or _solid_contains(
            shape, (wall_x, 0.0, height - 10.0)
        ):
            outside_hit = True
        if _solid_contains(shape, (wall_x, 0.0, mid_z)):
            gap_hit = True
    assert outside_hit, "tube should survive outside the gap"
    assert not gap_hit, "no segment should contain material at the gap midpoint"


def test_config_settings_hash_changes_with_tube_gap(tmp_path) -> None:
    base = """
knot_type: rod
"""
    enabled = """
knot_type: rod
tube_gap:
  enabled: true
  gap_length_mm: 25.0
"""
    longer = """
knot_type: rod
tube_gap:
  enabled: true
  gap_length_mm: 40.0
"""
    h_base = config_settings_hash(load_test_config(tmp_path, base))
    h_enabled = config_settings_hash(load_test_config(tmp_path, enabled))
    h_longer = config_settings_hash(load_test_config(tmp_path, longer))

    assert h_base != h_enabled
    assert h_enabled != h_longer


def test_config_rejects_enabled_without_length(tmp_path) -> None:
    bad = """
knot_type: rod
tube_gap:
  enabled: true
  gap_length_mm: 0.0
"""
    with pytest.raises(ValueError, match="gap_length_mm"):
        load_test_config(tmp_path, bad)
