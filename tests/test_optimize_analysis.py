"""
Unit tests for ``led_knots.optimize.analysis``: overhang / island / cavity
detectors.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
import trimesh

from led_knots.optimize.analysis import (
    detect_islands,
    detect_overhangs,
    detect_trapped_cavities,
)


# ---------------------------------------------------------------------------
# detect_overhangs
# ---------------------------------------------------------------------------


def test_overhangs_box_no_overhangs_after_bottom_layer_filter() -> None:
    """A box's only downward face is at z_min; the bottom-layer filter
    excludes it. No overhangs should be reported."""
    box = trimesh.creation.box(extents=(10, 10, 10))
    res = detect_overhangs(box, threshold_deg=35, bottom_layer_height_mm=0.5)
    assert res.total_overhang_area_mm2 == pytest.approx(0.0)
    assert len(res.clusters) == 0


def test_overhangs_t_shape_finds_underside() -> None:
    """A T-shape: top arm has an underside that's a 90° overhang."""
    top = trimesh.creation.box(extents=(40, 10, 4)).apply_translation([0, 0, 12])
    stem = trimesh.creation.box(extents=(8, 10, 12)).apply_translation([0, 0, 4])
    t_shape = trimesh.util.concatenate([top, stem])
    res = detect_overhangs(t_shape, threshold_deg=35)
    # Underside of the top arm is 40×10 = 400 mm². The center 8×10 chunk
    # overlaps with the stem top, but as concatenated meshes (no boolean
    # union) the entire underside is still flagged. So expect ~400.
    assert res.total_overhang_area_mm2 == pytest.approx(400.0, rel=0.01)
    assert len(res.clusters) >= 1


def test_overhangs_threshold_changes_count() -> None:
    """A 60° tilted face should be flagged at threshold 70° but not 30°."""
    # Plate tilted 60° from horizontal — normal is 30° from vertical.
    plate = trimesh.creation.box(extents=(20, 20, 1))
    angle = math.radians(60)
    R = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, math.cos(angle), -math.sin(angle)],
            [0.0, math.sin(angle), math.cos(angle)],
        ]
    )
    plate.apply_transform(np.vstack([np.hstack([R, [[0], [0], [0]]]), [0, 0, 0, 1]]))
    plate.apply_translation([0, 0, 50])  # away from build plate
    res_lo = detect_overhangs(plate, threshold_deg=20)
    res_hi = detect_overhangs(plate, threshold_deg=70)
    assert res_hi.total_overhang_area_mm2 > res_lo.total_overhang_area_mm2


def test_overhangs_face_mask_size_matches_mesh() -> None:
    """face_mask shape must match mesh.faces — required for downstream
    annotated PNG colorization."""
    box = trimesh.creation.box(extents=(10, 10, 10))
    res = detect_overhangs(box)
    assert res.face_mask.shape == (len(box.faces),)
    assert res.face_mask.dtype == np.bool_


# ---------------------------------------------------------------------------
# detect_islands
# ---------------------------------------------------------------------------


def test_islands_single_box() -> None:
    box = trimesh.creation.box(extents=(10, 10, 10))
    res = detect_islands(box)
    assert res.is_single_body
    assert len(res.components) == 1


def test_islands_two_boxes() -> None:
    a = trimesh.creation.box(extents=(10, 10, 10))
    b = trimesh.creation.box(extents=(10, 10, 10)).apply_translation([20, 0, 0])
    pair = trimesh.util.concatenate([a, b])
    res = detect_islands(pair, min_area_mm2=1.0)
    assert not res.is_single_body
    assert len(res.components) == 2


def test_islands_default_floor_filters_tiny_fragments() -> None:
    """The default min_area_fraction=0.001 of mesh area should drop
    sliver-area pseudo-islands. Verify by adding a deliberately tiny
    triangle to a normal box."""
    big = trimesh.creation.box(extents=(50, 50, 50))
    sliver_v = np.array([[100.0, 100.0, 0.0], [100.001, 100.0, 0.0], [100.0, 100.001, 0.0]])
    sliver_f = np.array([[0, 1, 2]])
    sliver = trimesh.Trimesh(vertices=sliver_v, faces=sliver_f, process=False)
    combined = trimesh.util.concatenate([big, sliver])
    res = detect_islands(combined)  # default min_area_fraction
    # Sliver area = ~5e-7 mm², well below 0.1% of 15000 mm² total.
    assert res.is_single_body or all(c.area_mm2 > 1.0 for c in res.components)


def test_islands_explicit_min_area() -> None:
    """When the caller passes min_area_mm2 explicitly, it overrides the
    default fractional floor."""
    big = trimesh.creation.box(extents=(50, 50, 50))
    small = trimesh.creation.box(extents=(2, 2, 2))
    small.apply_translation([100, 0, 0])
    combined = trimesh.util.concatenate([big, small])
    res_strict = detect_islands(combined, min_area_mm2=100.0)
    res_lax = detect_islands(combined, min_area_mm2=1.0)
    assert len(res_lax.components) > len(res_strict.components)


# ---------------------------------------------------------------------------
# detect_trapped_cavities
# ---------------------------------------------------------------------------


def test_cavities_unavailable_without_manifold3d() -> None:
    """When manifold3d isn't installed, the detector returns
    available=False with a clear note rather than raising."""
    try:
        import manifold3d  # noqa: F401

        pytest.skip("manifold3d is installed; test only validates the not-available path")
    except ImportError:
        pass

    box = trimesh.creation.box(extents=(10, 10, 10))
    res = detect_trapped_cavities(box)
    assert res.available is False
    assert res.note is not None
    assert "manifold3d" in res.note.lower()
    assert len(res.cavities) == 0


def _require_manifold3d() -> None:
    try:
        import manifold3d  # noqa: F401
    except ImportError:
        pytest.skip("manifold3d not installed")


def test_cavities_detect_sealed_inner_box() -> None:
    """outer-cube minus inner-cube has a fully enclosed cavity. The
    26-ray trap test should report it as trapped."""
    _require_manifold3d()
    outer = trimesh.creation.box(extents=(40, 40, 40))
    inner = trimesh.creation.box(extents=(20, 20, 20))
    sealed = trimesh.boolean.difference([outer, inner], engine="manifold")
    res = detect_trapped_cavities(sealed)
    assert res.available is True
    assert len(res.cavities) == 1
    cav = res.cavities[0]
    assert cav.is_trapped is True
    assert cav.volume_mm3 == pytest.approx(8000.0, rel=0.05)


def test_cavities_open_top_cup_is_not_trapped() -> None:
    """A cup open on top has a cavity in the convex-hull diff, but it's
    not trapped — rays going upward escape."""
    _require_manifold3d()
    outer = trimesh.creation.box(extents=(20, 20, 20)).apply_translation([0, 0, 10])
    inner = trimesh.creation.box(extents=(16, 16, 16)).apply_translation([0, 0, 12])
    cup = trimesh.boolean.difference([outer, inner], engine="manifold")
    res = detect_trapped_cavities(cup)
    assert res.available is True
    # The cavity from convex-hull diff is the open top — must be open.
    assert all(not c.is_trapped for c in res.cavities)
    assert len(res.trapped_cavities) == 0


def test_cavities_l_shape_is_not_trapped() -> None:
    """An L-shape's convex hull encloses an exterior corner volume that
    appears in the diff but is NOT a real cavity (it's accessible from
    outside)."""
    _require_manifold3d()
    base = trimesh.creation.box(extents=(40, 40, 5))
    column = trimesh.creation.box(extents=(10, 40, 30)).apply_translation([15, 0, 17.5])
    L = trimesh.boolean.union([base, column], engine="manifold")
    res = detect_trapped_cavities(L)
    assert res.available is True
    assert all(not c.is_trapped for c in res.cavities), (
        "L-shape's convex-hull diff is exterior and should not be tagged as trapped"
    )
    assert len(res.trapped_cavities) == 0
