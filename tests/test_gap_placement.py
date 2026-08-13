"""Tests for tube_gap.placement=lowest_z: point-space math, config plumbing,
pinned orientation, drain-hole guards, and the knot_build pre-pass."""

from __future__ import annotations

import math

import cadquery as cq
import numpy as np
import pytest
from cadquery.func import spline

from led_knots.core.cache_utils import config_settings_hash
from led_knots.core.knot_build import resolve_lowest_z_gap
from led_knots.core.tube_gap import lowest_z_center_fraction, open_loop_with_gap
from led_knots.core.utils import build_tube_from_path
from led_knots.optimize import optimize_part, select_orientation
from led_knots.optimize.report import OrientationCandidate
from led_knots.optimize.settings import PrintOptimizationSettings

from .conftest import load_test_config


def _circle_points(radius: float, n: int, plane: str = "xy", repeat_closing: bool = False):
    angles = np.linspace(0.0, 2.0 * math.pi, n, endpoint=False)
    if plane == "xy":
        pts = [(radius * math.cos(a), radius * math.sin(a), 0.0) for a in angles]
    else:  # xz
        pts = [(radius * math.cos(a), 0.0, radius * math.sin(a)) for a in angles]
    if repeat_closing:
        pts.append(pts[0])
    return pts


def _rot_x(deg: float) -> np.ndarray:
    r = math.radians(deg)
    return np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, math.cos(r), -math.sin(r)],
            [0.0, math.sin(r), math.cos(r)],
        ]
    )


# ---------------------------------------------------------------------------
# lowest_z_center_fraction: pure point-space math
# ---------------------------------------------------------------------------


def test_lowest_z_identity_rotation_targets_min_z_vertex() -> None:
    radius = 40.0
    pts = _circle_points(radius, 72, plane="xz")
    cf = lowest_z_center_fraction(pts, np.eye(3))

    # Gap centered on the lowest vertex: open the loop there and check the
    # midpoint between the gap edges sits near the circle's bottom.
    opened = np.asarray(open_loop_with_gap(pts, 20.0, cf))
    gap_mid = 0.5 * (opened[0] + opened[-1])
    # Chord midpoint between the gap edges sits at R·cos(gap/2R) from center.
    chord_r = radius * math.cos(0.5 * 20.0 / radius)
    assert gap_mid[2] == pytest.approx(-chord_r, abs=0.5)
    assert gap_mid[0] == pytest.approx(0.0, abs=0.5)


def test_lowest_z_known_rotation_maps_back_to_expected_vertex() -> None:
    # XY-plane circle rotated 90° about X: rotated Z equals the original Y
    # ((x, y, 0) @ R.T = (x, 0, y)), so the lowest post-rotation vertex is
    # the one at (0, -R, 0).
    radius = 40.0
    pts = _circle_points(radius, 72, plane="xy")
    cf = lowest_z_center_fraction(pts, _rot_x(90.0))

    opened = np.asarray(open_loop_with_gap(pts, 20.0, cf))
    gap_mid = 0.5 * (opened[0] + opened[-1])
    chord_r = radius * math.cos(0.5 * 20.0 / radius)
    assert gap_mid[1] == pytest.approx(-chord_r, abs=0.5)
    assert gap_mid[0] == pytest.approx(0.0, abs=0.5)


def test_lowest_z_wraps_seam_when_min_is_at_start() -> None:
    # XZ circle starts at (R, 0, 0); rotate 90° about Y-equivalent by using a
    # rotation that sends the start vertex to the bottom: rotated Z of vertex
    # i is -cos(angle_i) under this matrix, minimized at angle 0 (the seam).
    radius = 40.0
    pts = _circle_points(radius, 72, plane="xz")
    R = np.array([[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]])
    assert float((np.asarray(pts) @ R.T)[:, 2].min()) == pytest.approx(-radius)

    cf = lowest_z_center_fraction(pts, R)
    assert cf == pytest.approx(-0.5, abs=1e-6)

    opened = np.asarray(open_loop_with_gap(pts, 20.0, cf))
    gap_mid_rotated = (0.5 * (opened[0] + opened[-1])) @ R.T
    chord_r = radius * math.cos(0.5 * 20.0 / radius)
    assert gap_mid_rotated[2] == pytest.approx(-chord_r, abs=0.5)


def test_center_fraction_inversion_round_trip() -> None:
    pts = _circle_points(40.0, 72)
    arr = np.asarray(pts)
    ring = np.vstack([arr, arr[0]])
    seg = np.linalg.norm(np.diff(ring, axis=0), axis=1)
    cum = np.concatenate(([0.0], np.cumsum(seg)))
    total = float(cum[-1])

    for cf in np.linspace(-0.5, 0.49, 20):
        center_s = ((0.5 + cf) * total) % total
        recovered = (center_s % total) / total - 0.5
        # -0.5 and +0.5 are the same loop position.
        delta = abs(recovered - cf) % 1.0
        assert min(delta, 1.0 - delta) == pytest.approx(0.0, abs=1e-9)


def test_lowest_z_handles_repeated_closing_point() -> None:
    pts = _circle_points(40.0, 72, plane="xz")
    pts_closed = _circle_points(40.0, 72, plane="xz", repeat_closing=True)
    R = _rot_x(30.0)
    assert lowest_z_center_fraction(pts, R) == pytest.approx(
        lowest_z_center_fraction(pts_closed, R)
    )


def test_lowest_z_rejects_bad_rotation_shape() -> None:
    with pytest.raises(ValueError, match="3x3"):
        lowest_z_center_fraction(_circle_points(40.0, 8), np.eye(4))


# ---------------------------------------------------------------------------
# Config + cache key
# ---------------------------------------------------------------------------


def test_tube_gap_placement_validation(tmp_path) -> None:
    default = load_test_config(tmp_path, "knot_type: rod\n")
    assert default.tube_gap.placement == "manual"

    lowest = load_test_config(
        tmp_path,
        """
knot_type: rod
tube_gap:
  enabled: true
  gap_length_mm: 25.0
  placement: lowest_z
""",
    )
    assert lowest.tube_gap.placement == "lowest_z"

    with pytest.raises(ValueError, match="placement"):
        load_test_config(
            tmp_path,
            """
knot_type: rod
tube_gap:
  placement: sideways
""",
        )


def test_config_settings_hash_changes_with_placement(tmp_path) -> None:
    manual = """
knot_type: rod
tube_gap:
  enabled: true
  gap_length_mm: 25.0
  placement: manual
"""
    lowest = """
knot_type: rod
tube_gap:
  enabled: true
  gap_length_mm: 25.0
  placement: lowest_z
"""
    h_manual = config_settings_hash(load_test_config(tmp_path, manual))
    h_lowest = config_settings_hash(load_test_config(tmp_path, lowest))
    assert h_manual != h_lowest


# ---------------------------------------------------------------------------
# optimize_part: pinned candidate + drain-hole guards
# ---------------------------------------------------------------------------


def _pinned_90_about_x() -> OrientationCandidate:
    return OrientationCandidate(
        rank=1,
        matrix=_rot_x(90.0),
        axis=(1.0, 0.0, 0.0),
        angle_deg=90.0,
        unprintability=0.0,
        bottom_area_mm2=0.0,
        overhang_area_mm2=0.0,
        contour_length_mm=0.0,
    )


def _opt_settings(auto_apply: bool = True, drain: bool = False) -> PrintOptimizationSettings:
    return PrintOptimizationSettings(
        {
            "enabled": True,
            "orientation": {"enabled": True, "auto_apply": auto_apply},
            "drain_holes": {"enabled": drain},
        }
    )


def test_optimize_part_pinned_candidate_skips_search_and_rotates() -> None:
    # Flat slab: 40 x 20 x 4. Pinned 90° about X swaps Y and Z extents.
    part = cq.Solid.makeBox(40, 20, 4, cq.Vector(-20, -10, -2))
    pinned = _pinned_90_about_x()

    rotated, report = optimize_part(part, _opt_settings(), pinned_candidate=pinned)

    assert report.applied_candidate is pinned
    assert report.orientation_candidates == [pinned]
    bb = rotated.BoundingBox()
    assert (bb.ymax - bb.ymin) == pytest.approx(4.0, abs=0.1)
    assert (bb.zmax - bb.zmin) == pytest.approx(20.0, abs=0.1)


def test_select_orientation_matches_optimize_part_top_pick() -> None:
    part = cq.Solid.makeBox(40, 20, 4, cq.Vector(-20, -10, -2))
    settings = _opt_settings(auto_apply=False)

    _mesh, candidates, _tags, _note = select_orientation(part, settings)
    _part, report = optimize_part(part, settings)

    assert candidates, "Tweaker returned no candidates for a plain box"
    assert np.allclose(
        report.orientation_candidates[0].matrix, candidates[0].matrix
    )


def test_vented_part_skips_drilling() -> None:
    part = cq.Solid.makeBox(40, 20, 4, cq.Vector(-20, -10, -2))

    _part, report = optimize_part(
        part, _opt_settings(drain=True), part_is_vented=True
    )

    assert not report.drilled_cavities
    assert "vented via tube_gap" in (report.note or "")


def test_closed_loop_path_skips_drilling() -> None:
    part = cq.Solid.makeBox(40, 20, 4, cq.Vector(-20, -10, -2))
    closed_path = spline(_circle_points(40.0, 36, repeat_closing=True))

    _part, report = optimize_part(
        part, _opt_settings(drain=True), path=closed_path
    )

    assert not report.drilled_cavities
    assert "closed loop" in (report.note or "")


# ---------------------------------------------------------------------------
# resolve_lowest_z_gap: the knot_build pre-pass
# ---------------------------------------------------------------------------

_PREPASS_YAML = """
knot_type: rod
tube_settings:
  face_type: solid_circle
  outer_radius: 5.0
tube_gap:
  enabled: true
  gap_length_mm: 20.0
  center_fraction: 0.0
  placement: lowest_z
print_optimization:
  enabled: true
  orientation:
    auto_apply: true
"""


def test_resolve_lowest_z_gap_places_gap_at_oriented_bottom(tmp_path) -> None:
    config = load_test_config(tmp_path, _PREPASS_YAML)
    # Tilted circle: no orientation leaves it flat in XY, so the derived
    # fraction is only correct if the pre-pass actually used the candidate.
    pts = np.asarray(_circle_points(60.0, 72, plane="xy")) @ _rot_x(30.0).T

    cf, candidate = resolve_lowest_z_gap([tuple(p) for p in pts], config, aux=False)

    assert cf is not None and candidate is not None
    rotated = pts @ np.asarray(candidate.matrix).T
    opened = np.asarray(open_loop_with_gap([tuple(p) for p in pts], 20.0, cf))
    gap_mid_rotated = (0.5 * (opened[0] + opened[-1])) @ np.asarray(candidate.matrix).T
    # Gap center within one segment of the oriented path's lowest point.
    assert gap_mid_rotated[2] <= float(rotated[:, 2].min()) + 6.0

    stats = {s.name: s.value for s in config.render_stats._stats}
    assert float(stats["tube_gap.resolved_center_fraction"]) == pytest.approx(cf)
    assert float(stats["tube_gap.oriented_gap_mid_z_mm"]) == pytest.approx(
        float(stats["tube_gap.oriented_min_z_mm"]), abs=6.0
    )


def test_resolve_lowest_z_gap_falls_back_without_auto_orient(tmp_path) -> None:
    yaml_body = _PREPASS_YAML.replace("auto_apply: true", "auto_apply: false")
    config = load_test_config(tmp_path, yaml_body)
    pts = _circle_points(60.0, 72, plane="xz")

    cf, candidate = resolve_lowest_z_gap(pts, config, aux=False)

    assert cf is None and candidate is None
    stats = {s.name: s.value for s in config.render_stats._stats}
    assert "tube_gap.placement_fallback" in stats
