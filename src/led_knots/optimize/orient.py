"""
Tweaker-3 wrapper that returns the top-N build orientations for a mesh.

Tweaker-3 itself is vendored at ``led_knots.optimize._tweaker``; this module
adapts its result shape to the project's ``OrientationCandidate`` dataclass
and silences its built-in verbose printing.
"""

from __future__ import annotations

import logging
import math
from typing import List

import numpy as np
import trimesh

from ._tweaker import Tweak
from .report import OrientationCandidate

logger = logging.getLogger(__name__)


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
