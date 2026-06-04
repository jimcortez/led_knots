"""
Tweaker-3 wrapper that returns the top-N build orientations for a mesh.

Tweaker-3 itself is vendored at ``led_knots.optimize._tweaker``; this module
adapts its result shape to the project's ``OrientationCandidate`` dataclass
and silences its built-in verbose printing.
"""

from __future__ import annotations

import logging
import math
from typing import List, Sequence, Tuple

import numpy as np
import trimesh

from ._tweaker import Tweak
from .report import OrientationCandidate

logger = logging.getLogger(__name__)


def score_orientation_overhang(
    face_normals: np.ndarray,
    face_areas: np.ndarray,
    rotation_matrix: np.ndarray,
    *,
    overhang_threshold_deg: float = 35.0,
) -> float:
    """Cheap SLA score for a rotation: total downward-facing face area.

    Returns the sum (in mm²) of face areas whose post-rotation normals lie
    within ``overhang_threshold_deg`` of straight-down — i.e. the faces
    that would need supports if the model were oriented this way.

    The mesh itself is *not* rotated; we transform the world-down vector
    by ``rotation_matrix.T`` instead, so this is O(F) per rotation candidate
    rather than O(F) vertex transforms per candidate.

    Args:
        face_normals: (F, 3) unit normals in the original mesh frame.
        face_areas: (F,) area in mm² per face.
        rotation_matrix: 3x3 rotation that would be applied to the mesh.
        overhang_threshold_deg: faces within this angle of straight-down
            count as overhangs. SLA: ~35°; FDM: ~45°.

    Returns:
        Total overhang area in mm² (lower is better).
    """
    down_world = np.array([0.0, 0.0, -1.0], dtype=np.float64)
    down_local = rotation_matrix.T @ down_world  # equivalent post-rotation "down"
    threshold = math.cos(math.radians(overhang_threshold_deg))
    # n · down_local > cos(threshold) means the face faces downward (toward
    # the build plate) within the overhang threshold.
    dot = face_normals @ down_local
    overhang_mask = dot > threshold
    return float(face_areas[overhang_mask].sum())


def best_rotation_by_overhang(
    mesh: trimesh.Trimesh,
    rotation_matrices: Sequence[np.ndarray],
    *,
    overhang_threshold_deg: float = 35.0,
) -> Tuple[int, float]:
    """Pick the rotation with the smallest overhang area for ``mesh``.

    Returns ``(winning_index, score)``. The index points into
    ``rotation_matrices``. Ties broken by lowest index, which preserves any
    upstream ordering (e.g. dim-score from segmentation).
    """
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    best_idx = 0
    best_score = math.inf
    for idx, mat in enumerate(rotation_matrices):
        score = score_orientation_overhang(
            normals, areas, mat, overhang_threshold_deg=overhang_threshold_deg
        )
        if score < best_score:
            best_score = score
            best_idx = idx
    return best_idx, best_score


def connector_verticality_bonus(
    face_normals: np.ndarray,
    face_areas: np.ndarray,
    connector_mask: np.ndarray,
    rotation_matrix: np.ndarray,
) -> float:
    """Area-weighted fraction of connector faces that become vertical after rotation.

    A connector "flank" face stands vertically (lining up with the build
    axis, so the strip acts as a natural support column) when its rotated
    normal lies in the horizontal plane — i.e. ``|n'_z|`` is small.

    Returns a value in ``[0, 1]``: 1 means every tagged connector face is
    perfectly vertical post-rotation; 0 means every one is horizontal
    (lying flat). 0 if no faces are tagged.
    """
    if connector_mask is None or not connector_mask.any():
        return 0.0
    # Pull rotation through to local frame: world-Z in the un-rotated
    # mesh frame is `R.T @ [0,0,1]`, which is the last column of R.T,
    # i.e. the last *row* of R.
    z_local = rotation_matrix[2, :]
    n = face_normals[connector_mask]
    a = face_areas[connector_mask]
    vert_per_face = 1.0 - np.abs(n @ z_local)  # 1 = vertical flank, 0 = horizontal
    total = float(a.sum())
    if total <= 0:
        return 0.0
    return float((vert_per_face * a).sum() / total)


def rescore_candidates_with_connector_bonus(
    candidates: List[OrientationCandidate],
    mesh: trimesh.Trimesh,
    connector_mask: np.ndarray,
    *,
    bonus_weight: float,
) -> List[OrientationCandidate]:
    """Re-rank Tweaker-3 candidates by ``unprintability * (1 - w * bonus)``.

    The bonus is the area-weighted connector verticality (0..1). With
    ``bonus_weight=0.7`` a fully-vertical-connectors orientation cuts the
    effective unprintability by 70%, which is usually enough to flip
    Tweaker's volume-minimising default to the orientation that uses the
    connectors as natural supports.

    Returns a new list, sorted by the rescored value ascending. ``rank``
    is renumbered to match the new ordering; other fields are preserved.
    """
    if not candidates or connector_mask is None or not connector_mask.any():
        return candidates

    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    weight = float(bonus_weight)

    scored: List[Tuple[float, float, OrientationCandidate]] = []
    for cand in candidates:
        bonus = connector_verticality_bonus(normals, areas, connector_mask, cand.matrix)
        adjusted = cand.unprintability * (1.0 - weight * bonus)
        scored.append((adjusted, bonus, cand))
    scored.sort(key=lambda x: x[0])

    return [
        OrientationCandidate(
            rank=i + 1,
            matrix=cand.matrix,
            axis=cand.axis,
            angle_deg=cand.angle_deg,
            unprintability=cand.unprintability,
            bottom_area_mm2=cand.bottom_area_mm2,
            overhang_area_mm2=cand.overhang_area_mm2,
            contour_length_mm=cand.contour_length_mm,
            connector_bonus=bonus,
        )
        for i, (_, bonus, cand) in enumerate(scored)
    ]


def _axis_angle_from_matrix(matrix: np.ndarray) -> tuple:
    """
    Decompose a 3x3 rotation matrix into (axis, angle_rad).

    Tweaker-3 already provides the axis+angle directly, but for the
    near-identity case (``alignment ≈ [0,0,1]``) its ``euler`` helper
    returns ``angle=0`` with an arbitrary axis; we keep its values intact
    and only use this helper as a sanity fallback if needed.
    """
    cos_a = (np.trace(matrix) - 1.0) / 2.0
    cos_a = max(-1.0, min(1.0, cos_a))
    angle = math.acos(cos_a)
    if angle < 1e-9:
        return (1.0, 0.0, 0.0), 0.0
    if math.isclose(angle, math.pi, abs_tol=1e-6):
        # Pick the largest diagonal element to extract axis stably.
        diag = np.array([matrix[0, 0], matrix[1, 1], matrix[2, 2]])
        i = int(np.argmax(diag))
        v = np.zeros(3)
        v[i] = math.sqrt(max(0.0, (matrix[i, i] + 1.0) / 2.0))
        for j in range(3):
            if j == i:
                continue
            v[j] = matrix[i, j] / (2.0 * v[i]) if v[i] != 0 else 0.0
        n = float(np.linalg.norm(v))
        if n > 0:
            v = v / n
        return (float(v[0]), float(v[1]), float(v[2])), float(angle)
    axis = np.array([
        matrix[2, 1] - matrix[1, 2],
        matrix[0, 2] - matrix[2, 0],
        matrix[1, 0] - matrix[0, 1],
    ]) / (2.0 * math.sin(angle))
    return (float(axis[0]), float(axis[1]), float(axis[2])), float(angle)


def find_best_orientations(
    mesh: trimesh.Trimesh,
    *,
    top_n: int = 5,
    min_volume: bool = True,
) -> List[OrientationCandidate]:
    """
    Run Tweaker-3 on ``mesh`` and return up to ``top_n`` ranked candidates.

    ``min_volume=True`` uses the upstream parameter set tuned to minimise
    support material volume, which matches the SLA use case.

    Returns an empty list if Tweaker-3 produced no usable orientation
    (e.g. degenerate mesh with no faces).
    """
    if len(mesh.faces) == 0:
        return []

    # Tweaker-3's `preprocess` expects content shaped (n_faces*3, 3) —
    # a flat sequence of vertices, three consecutive rows per face — and
    # internally reshapes to (n_faces, 3, 3). trimesh exposes
    # `mesh.triangles` already in (n_faces, 3, 3); flatten before passing.
    triangles = np.asarray(mesh.triangles, dtype=np.float64).reshape(-1, 3)
    tweak = Tweak(
        triangles,
        extended_mode=True,
        verbose=False,
        show_progress=False,
        min_volume=min_volume,
    )

    if not hasattr(tweak, "all_orientations"):
        return []

    all_results = np.asarray(tweak.all_orientations)
    n = min(int(top_n), all_results.shape[0])
    candidates: List[OrientationCandidate] = []
    for rank_idx in range(n):
        row = all_results[rank_idx]
        alignment = np.array([row[0], row[1], row[2]], dtype=np.float64)
        _, angle_rad, matrix = tweak.euler(alignment.tolist())
        matrix = np.asarray(matrix, dtype=np.float64)

        if angle_rad < 1e-9:
            axis = (1.0, 0.0, 0.0)
            angle_deg = 0.0
        else:
            axis_calc, angle_calc = _axis_angle_from_matrix(matrix)
            axis = axis_calc
            angle_deg = math.degrees(angle_calc)

        candidates.append(
            OrientationCandidate(
                rank=rank_idx + 1,
                matrix=matrix,
                axis=axis,
                angle_deg=angle_deg,
                unprintability=float(row[6]),
                bottom_area_mm2=float(row[3]),
                overhang_area_mm2=float(row[4]),
                contour_length_mm=float(row[5]),
            )
        )
    return candidates
