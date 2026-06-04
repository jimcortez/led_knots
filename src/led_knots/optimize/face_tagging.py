"""
Classify the faces of a swept LED-tube mesh by structural role.

The role we care about for SLA optimization is "connector flank" — the
two long flat sides of the radial strips that join the outer ring to the
inner tube/oval. When the part is oriented so those flanks are vertical
(i.e. the strip's long axis aligns with the build axis), the strip itself
becomes a natural support column and the inner tube hangs from the outer
ring without needing slicer-generated supports.

The classifier is purely geometric: for each face centroid it looks up
the nearest path sample, builds a local frame ``(T, R_hat, B_hat=T×R_hat)``
and reads off the dominant component of the face normal in that frame.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import trimesh

logger = logging.getLogger(__name__)


# Face types that the LED-circle cross-section geometry actually has
# connectors in. Other face types (solid_circle, square, …) return an
# empty connector mask.
_FACE_TYPES_WITH_CONNECTORS = frozenset({
    "led_circle",
    "led_circle_tube",
    "led_circle_diffusion_pyramids",
})


@dataclass(frozen=True)
class FaceTagResult:
    """Per-face role classification for a swept LED-tube mesh."""

    connector_mask: np.ndarray  # (F,) bool
    note: str = ""

    @property
    def n_connector_faces(self) -> int:
        return int(self.connector_mask.sum())


def _sample_path_frames(path, num_samples: int) -> tuple:
    """Return ``(points, tangents)`` as ``(N, 3)`` float arrays.

    Both are unit-tangent normalised. Reuses ``path.positionAt`` /
    ``path.tangentAt`` so the sampling matches the rest of the codebase.
    """
    n = max(int(num_samples), 8)
    ts = np.linspace(0.0, 1.0, n)
    points = np.empty((n, 3), dtype=np.float64)
    tangents = np.empty((n, 3), dtype=np.float64)
    for i, t in enumerate(ts):
        p = path.positionAt(float(t))
        tg = path.tangentAt(float(t))
        points[i] = (p.x, p.y, p.z)
        tangents[i] = (tg.x, tg.y, tg.z)
    norms = np.linalg.norm(tangents, axis=1, keepdims=True)
    safe = np.where(norms > 1e-12, norms, 1.0)
    tangents = tangents / safe
    return points, tangents


def tag_connector_faces(
    mesh: trimesh.Trimesh,
    path: Any,
    tube_settings: Any,
    *,
    num_path_samples: int = 200,
    azimuthal_alignment_threshold: float = 0.7,
    min_radial_clearance_mm: float = 0.05,
) -> FaceTagResult:
    """Mark faces whose normal points along the cross-section's azimuthal axis.

    The "azimuthal" direction at a path sample is ``T × R_hat`` where ``T``
    is the path tangent and ``R_hat`` is the outward radial from the path
    to the face centroid. Connector-flank faces — the long flat sides of
    the radial connector strips — have normals that align with that
    azimuthal direction.

    Faces are also constrained to lie radially between the inner feature
    (tube outer wall, or oval extent) and the outer ring's inner wall —
    physically where the connectors live. This second gate filters out
    fillets and end-cap remnants that happen to have an azimuthal normal.

    Args:
        mesh: tessellated swept tube in build orientation.
        path: cadquery Wire/Edge the tube was swept along.
        tube_settings: ``config.tube_settings`` — used for face-type and
            radial bounds.
        num_path_samples: sample density along the path. 200 covers most
            knots; bump for very long sweeps.
        azimuthal_alignment_threshold: cosine threshold for the
            ``|n · B_hat|`` test. 0.7 ≈ within 45° of pure azimuthal.
        min_radial_clearance_mm: shrink the inner/outer radial bounds by
            this much so faces sitting *on* the ring surfaces don't get
            misclassified as connectors.

    Returns:
        FaceTagResult with the connector mask (and a ``note`` if the face
        type has no connectors or the geometry doesn't admit a gap).
    """
    n_faces = len(mesh.faces)
    empty = np.zeros(n_faces, dtype=bool)

    face_type = getattr(tube_settings, "face_type", None)
    if face_type not in _FACE_TYPES_WITH_CONNECTORS:
        return FaceTagResult(
            connector_mask=empty,
            note=f"face type {face_type!r} has no connectors",
        )

    outer_radius = float(tube_settings.outer_radius)
    wall_thickness = float(tube_settings.wall_thickness)
    outer_ring_inner_r = outer_radius - wall_thickness

    if face_type == "led_circle_tube":
        if tube_settings.inner_tube_diameter is None or tube_settings.inner_tube_wall_thickness is None:
            return FaceTagResult(
                connector_mask=empty,
                note="led_circle_tube missing inner_tube_* settings",
            )
        inner_feature_r = (
            float(tube_settings.inner_tube_diameter) / 2.0
            + float(tube_settings.inner_tube_wall_thickness)
        )
    else:
        # led_circle / _diffusion_pyramids: the oval enclosing the LED
        # cavity has approximate radial extent = half the long inner side
        # plus the wall thickness. Conservative — captures the bulk of the
        # gap even when the actual oval is slightly larger.
        inner_feature_r = (
            float(tube_settings.rect_inner_y) / 2.0
            + float(tube_settings.oval_wall_thickness)
        )

    r_lo = inner_feature_r + float(min_radial_clearance_mm)
    r_hi = outer_ring_inner_r - float(min_radial_clearance_mm)
    if r_hi <= r_lo:
        return FaceTagResult(
            connector_mask=empty,
            note=(
                f"no radial gap for connectors: inner feature r≈{inner_feature_r:.2f} "
                f"vs ring inner r≈{outer_ring_inner_r:.2f}"
            ),
        )

    sample_points, sample_tangents = _sample_path_frames(path, num_path_samples)

    centroids = np.asarray(mesh.triangles_center, dtype=np.float64)
    normals = np.asarray(mesh.face_normals, dtype=np.float64)

    # Nearest path sample per face centroid. KDTree if scipy is available;
    # brute-force otherwise (the codebase doesn't pin scipy as a dep).
    try:
        from scipy.spatial import cKDTree

        tree = cKDTree(sample_points)
        _, nearest_idx = tree.query(centroids, k=1)
    except ImportError:  # pragma: no cover - exercised on stripped envs
        dists = np.linalg.norm(
            centroids[:, None, :] - sample_points[None, :, :], axis=2
        )
        nearest_idx = np.argmin(dists, axis=1)

    p_near = sample_points[nearest_idx]
    t_hat = sample_tangents[nearest_idx]

    delta = centroids - p_near
    along = np.einsum("ij,ij->i", delta, t_hat)
    perp = delta - along[:, None] * t_hat
    r_dist = np.linalg.norm(perp, axis=1)

    safe_perp = np.where(r_dist[:, None] > 1e-9, perp / np.where(r_dist[:, None] > 1e-9, r_dist[:, None], 1.0), 0.0)
    r_hat = safe_perp
    b_hat = np.cross(t_hat, r_hat)
    b_norms = np.linalg.norm(b_hat, axis=1, keepdims=True)
    b_hat = np.where(b_norms > 1e-9, b_hat / np.where(b_norms > 1e-9, b_norms, 1.0), 0.0)

    azimuthal_alignment = np.abs(np.einsum("ij,ij->i", normals, b_hat))
    in_radial_gap = (r_dist > r_lo) & (r_dist < r_hi)
    is_connector = in_radial_gap & (azimuthal_alignment > float(azimuthal_alignment_threshold))

    return FaceTagResult(connector_mask=is_connector, note="")
