"""
Unit tests for ``led_knots.optimize.orient``: scoring functions and the
Tweaker-3 wrapper.

Run with ``uv run pytest tests/test_optimize_orient.py`` from the repo
root, or via ``uv run pytest tests/`` for the full suite.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
import trimesh

from led_knots.optimize.orient import (
    best_rotation_by_overhang,
    connector_verticality_bonus,
    find_best_orientations,
    rescore_candidates_with_connector_bonus,
    score_orientation_overhang,
)
from led_knots.optimize.report import OrientationCandidate


# ---------------------------------------------------------------------------
# score_orientation_overhang
# ---------------------------------------------------------------------------


def test_overhang_score_zero_for_box_identity() -> None:
    """A solid box at identity has only a single bottom face overhang —
    which the tagger excludes via the bottom-layer rule, but the bare
    score function doesn't apply that rule. So identity rotation gives
    1 face × area as overhang. Verify ordering rather than absolute."""
    box = trimesh.creation.box(extents=(20, 20, 20))
    s = score_orientation_overhang(
        box.face_normals, box.area_faces, np.eye(3), overhang_threshold_deg=35
    )
    # 1 bottom face of 20×20 = 400 mm²
    assert s == pytest.approx(400.0)


def test_overhang_score_invariant_under_180_about_z() -> None:
    """Rotating about Z keeps the bottom face on the bottom — overhang
    should match identity to floating-point precision."""
    box = trimesh.creation.box(extents=(20, 20, 20))
    Rz = np.array(
        [[-1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64
    )
    s_id = score_orientation_overhang(box.face_normals, box.area_faces, np.eye(3))
    s_rz = score_orientation_overhang(box.face_normals, box.area_faces, Rz)
    assert s_id == pytest.approx(s_rz)


def test_overhang_score_picks_thinnest_axis_for_l_shape() -> None:
    """An L-shape (concatenated boxes) has the smallest overhang area
    when laid on its tallest dimension's side — the orientation
    minimising downward face area changes with the rotation."""
    base = trimesh.creation.box(extents=(40, 20, 5))
    column = trimesh.creation.box(extents=(10, 20, 30))
    column.apply_translation([15, 0, 17.5])
    L = trimesh.util.concatenate([base, column])

    Rx90 = np.array(
        [[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]], dtype=np.float64
    )

    s_id = score_orientation_overhang(L.face_normals, L.area_faces, np.eye(3))
    s_rx = score_orientation_overhang(L.face_normals, L.area_faces, Rx90)
    # Identity has both the base bottom AND the column bottom as overhangs.
    # Rx90 stands the L on its end — fewer downward faces.
    assert s_rx < s_id


# ---------------------------------------------------------------------------
# best_rotation_by_overhang
# ---------------------------------------------------------------------------


def test_best_rotation_picks_index_zero_on_tie() -> None:
    """Tied scores should keep the first index — preserves upstream
    (e.g. dim-score) ordering for the segmented-print path."""
    box = trimesh.creation.box(extents=(20, 20, 20))
    Rz = np.array(
        [[-1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64
    )
    idx, _ = best_rotation_by_overhang(box, [np.eye(3), Rz])
    assert idx == 0


def test_best_rotation_handles_empty_list() -> None:
    box = trimesh.creation.box(extents=(20, 20, 20))
    # Tweaker-3 + this scorer share an interface — empty rotation list
    # should not crash. score_orientation_overhang is the underlying call.
    # best_rotation_by_overhang loops over rotations; empty → best_idx=0.
    idx, _ = best_rotation_by_overhang(box, [])
    assert idx == 0


# ---------------------------------------------------------------------------
# connector_verticality_bonus
# ---------------------------------------------------------------------------


def _make_connector_test_mesh():
    """A box whose two opposite vertical faces are 'connector flanks'.

    Vertical-x faces have normals ±X; under identity they're already
    horizontal (the FACE is vertical; the NORMAL is horizontal).
    """
    box = trimesh.creation.box(extents=(10, 10, 10))
    # Box face normals (per trimesh convention): faces 0..11 are 6 sides × 2 tris.
    # Mark faces with |n_x| ≈ 1 as 'connectors'.
    mask = np.abs(box.face_normals[:, 0]) > 0.99
    return box, mask


def test_connector_bonus_identity_already_vertical() -> None:
    """Vertical faces (normals ±X) under identity rotation are already
    vertical — bonus should be 1.0."""
    box, mask = _make_connector_test_mesh()
    bonus = connector_verticality_bonus(box.face_normals, box.area_faces, mask, np.eye(3))
    assert bonus == pytest.approx(1.0, abs=1e-9)


def test_connector_bonus_rotated_to_horizontal() -> None:
    """Ry(90°) maps ±X normals to ±Z normals — the faces become
    horizontal (lying flat). Bonus should drop to 0.0."""
    box, mask = _make_connector_test_mesh()
    Ry90 = np.array(
        [[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]], dtype=np.float64
    )
    bonus = connector_verticality_bonus(box.face_normals, box.area_faces, mask, Ry90)
    assert bonus == pytest.approx(0.0, abs=1e-9)


def test_connector_bonus_returns_zero_when_no_mask() -> None:
    box = trimesh.creation.box(extents=(10, 10, 10))
    empty = np.zeros(len(box.faces), dtype=bool)
    bonus = connector_verticality_bonus(box.face_normals, box.area_faces, empty, np.eye(3))
    assert bonus == 0.0


def test_connector_bonus_45_degrees() -> None:
    """A 45° rotation of vertical-X faces about Y leaves their normals
    at 45° to vertical — ``vert = 1 - |cos 45°| ≈ 0.293``."""
    box, mask = _make_connector_test_mesh()
    c = math.cos(math.radians(45))
    s = math.sin(math.radians(45))
    Ry45 = np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]], dtype=np.float64)
    bonus = connector_verticality_bonus(box.face_normals, box.area_faces, mask, Ry45)
    assert bonus == pytest.approx(1.0 - c, abs=1e-6)


# ---------------------------------------------------------------------------
# rescore_candidates_with_connector_bonus
# ---------------------------------------------------------------------------


def _candidate(rank, unprintability, matrix=None):
    return OrientationCandidate(
        rank=rank,
        matrix=matrix if matrix is not None else np.eye(3),
        axis=(1.0, 0.0, 0.0),
        angle_deg=0.0,
        unprintability=unprintability,
        bottom_area_mm2=0.0,
        overhang_area_mm2=0.0,
        contour_length_mm=0.0,
    )


def test_rescore_passthrough_when_mask_empty() -> None:
    box = trimesh.creation.box(extents=(10, 10, 10))
    candidates = [_candidate(1, 100.0), _candidate(2, 200.0)]
    out = rescore_candidates_with_connector_bonus(
        candidates, box, np.zeros(len(box.faces), dtype=bool), bonus_weight=0.7
    )
    assert [c.unprintability for c in out] == [100.0, 200.0]


def test_rescore_promotes_high_bonus_candidate() -> None:
    """A 200-unprintability candidate with bonus=1 (adjusted=60) should
    outrank a 100-unprintability candidate with bonus=0 (adjusted=100)."""
    box, mask = _make_connector_test_mesh()
    Ry90 = np.array(
        [[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]], dtype=np.float64
    )
    # Candidate A: identity, faces vertical → bonus=1 → adjusted = 200 * 0.3 = 60
    # Candidate B: Ry90, faces horizontal → bonus=0 → adjusted = 100 * 1.0 = 100
    cand_a = _candidate(1, 200.0, matrix=np.eye(3))
    cand_b = _candidate(2, 100.0, matrix=Ry90)
    out = rescore_candidates_with_connector_bonus(
        [cand_a, cand_b], box, mask, bonus_weight=0.7
    )
    assert out[0].unprintability == pytest.approx(200.0)
    assert out[0].connector_bonus == pytest.approx(1.0, abs=1e-9)
    assert out[1].unprintability == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# find_best_orientations
# ---------------------------------------------------------------------------


def test_find_best_orientations_returns_consistent_axis() -> None:
    """The (axis, angle, matrix) produced by find_best_orientations must
    be self-consistent: applying ``rotate(axis, angle)`` should match
    multiplying by ``matrix``. This guards SF3."""
    box = trimesh.creation.box(extents=(40, 20, 5))
    candidates = find_best_orientations(box, top_n=3)
    assert len(candidates) > 0
    for c in candidates:
        # Build the rotation matrix from (axis, angle) using Rodrigues.
        axis = np.asarray(c.axis, dtype=np.float64)
        n = np.linalg.norm(axis)
        if n < 1e-9:
            # Identity rotation — matrix should be ~I.
            assert np.allclose(c.matrix, np.eye(3), atol=1e-9)
            continue
        axis = axis / n
        a = math.radians(c.angle_deg)
        K = np.array(
            [
                [0.0, -axis[2], axis[1]],
                [axis[2], 0.0, -axis[0]],
                [-axis[1], axis[0], 0.0],
            ]
        )
        rodrigues = np.eye(3) + math.sin(a) * K + (1.0 - math.cos(a)) * (K @ K)
        # Tolerate a generous epsilon — Tweaker computes via a slightly
        # different formulation, so element-wise match isn't exact.
        assert np.allclose(c.matrix, rodrigues, atol=1e-6), (
            f"matrix vs (axis,angle) mismatch for rank={c.rank}: "
            f"axis={axis}, angle={c.angle_deg}, matrix-rodrigues={c.matrix - rodrigues}"
        )


def test_find_best_orientations_empty_mesh() -> None:
    empty = trimesh.Trimesh()
    out = find_best_orientations(empty, top_n=3)
    assert out == []
