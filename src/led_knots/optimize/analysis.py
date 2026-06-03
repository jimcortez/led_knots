"""
Mesh analyzers for SLA print problems.

All analyzers operate on a single ``trimesh.Trimesh`` in the orientation it
would be printed (build axis = +Z). They return small dataclasses naming
problem regions; the consumer is the report layer, which formats them for
the console and (eventually) the annotated PNG.

Analyzers must NOT mutate the input mesh.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
import trimesh

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Overhangs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OverhangCluster:
    """A connected region of overhanging faces."""

    face_indices: np.ndarray  # (N,) integer indices into mesh.faces
    area_mm2: float
    centroid: Tuple[float, float, float]


@dataclass(frozen=True)
class OverhangResult:
    """Result of ``detect_overhangs`` on a mesh."""

    threshold_deg: float
    total_overhang_area_mm2: float
    face_mask: np.ndarray  # (F,) bool — True if face is an overhang
    clusters: List[OverhangCluster] = field(default_factory=list)


def detect_overhangs(
    mesh: trimesh.Trimesh,
    *,
    threshold_deg: float = 35.0,
    bottom_layer_height_mm: float = 0.2,
    min_cluster_area_mm2: float = 0.5,
) -> OverhangResult:
    """Flag faces whose normals make an angle with straight-down below
    ``threshold_deg``. Faces in the bottom build layer (``z <= z_min +
    bottom_layer_height_mm``) are excluded — they rest on the build plate.

    Faces are grouped into connected clusters via face adjacency; clusters
    below ``min_cluster_area_mm2`` are dropped (typically tessellation noise).

    Returns an ``OverhangResult`` carrying the per-face mask, cluster list,
    and total overhang area in mm².
    """
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    centroids = np.asarray(mesh.triangles_center, dtype=np.float64)

    threshold = math.cos(math.radians(threshold_deg))
    overhang_mask = normals[:, 2] < -threshold  # n_z < -cos(threshold) → faces down

    # Exclude the bottom layer (resting on the build plate).
    z_min = float(mesh.vertices[:, 2].min())
    face_z_max = np.max(mesh.vertices[mesh.faces][:, :, 2], axis=1)
    bottom_mask = face_z_max <= (z_min + bottom_layer_height_mm)
    overhang_mask = overhang_mask & ~bottom_mask

    overhang_idx = np.where(overhang_mask)[0]
    total_area = float(areas[overhang_mask].sum())

    clusters: List[OverhangCluster] = []
    if overhang_idx.size > 0:
        # Build adjacency restricted to overhang faces.
        # trimesh.face_adjacency is (E, 2) pairs of touching faces; keep
        # pairs where both faces are in the overhang set.
        adjacency = np.asarray(mesh.face_adjacency, dtype=np.int64)
        in_set = overhang_mask[adjacency[:, 0]] & overhang_mask[adjacency[:, 1]]
        edges = adjacency[in_set]
        components = trimesh.graph.connected_components(
            edges, nodes=overhang_idx
        )
        for comp in components:
            comp_idx = np.asarray(comp, dtype=np.int64)
            area = float(areas[comp_idx].sum())
            if area < min_cluster_area_mm2:
                continue
            c = centroids[comp_idx].mean(axis=0)
            clusters.append(
                OverhangCluster(
                    face_indices=comp_idx,
                    area_mm2=area,
                    centroid=(float(c[0]), float(c[1]), float(c[2])),
                )
            )
        clusters.sort(key=lambda x: x.area_mm2, reverse=True)

    return OverhangResult(
        threshold_deg=threshold_deg,
        total_overhang_area_mm2=total_area,
        face_mask=overhang_mask,
        clusters=clusters,
    )


# ---------------------------------------------------------------------------
# Islands (disconnected components)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Island:
    """A topologically disconnected component of the mesh."""

    face_indices: np.ndarray
    area_mm2: float
    volume_mm3: float
    bounds: Tuple[Tuple[float, float, float], Tuple[float, float, float]]


@dataclass(frozen=True)
class IslandResult:
    components: List[Island] = field(default_factory=list)

    @property
    def is_single_body(self) -> bool:
        return len(self.components) <= 1


def detect_islands(
    mesh: trimesh.Trimesh,
    *,
    min_area_mm2: float = 0.5,
) -> IslandResult:
    """Split ``mesh`` into topologically disconnected bodies.

    Returns an ``IslandResult``. Useful as a *whole-mesh* check: anything
    beyond one body means a piece is unanchored. (Per-layer island
    detection — the more common SLA failure — needs a slicer pass and is
    deferred to a future commit.)
    """
    submeshes = mesh.split(only_watertight=False)
    components: List[Island] = []
    for sub in submeshes:
        if sub.area < min_area_mm2:
            continue
        mn, mx = sub.bounds
        components.append(
            Island(
                face_indices=np.arange(len(sub.faces)),  # local to submesh
                area_mm2=float(sub.area),
                volume_mm3=float(sub.volume) if sub.is_volume else 0.0,
                bounds=(
                    (float(mn[0]), float(mn[1]), float(mn[2])),
                    (float(mx[0]), float(mx[1]), float(mx[2])),
                ),
            )
        )
    components.sort(key=lambda x: x.area_mm2, reverse=True)
    return IslandResult(components=components)


# ---------------------------------------------------------------------------
# Trapped cavities (optional; needs manifold3d for the boolean backend)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Cavity:
    """A pocket of empty space enclosed by the mesh."""

    volume_mm3: float
    centroid: Tuple[float, float, float]
    bounds: Tuple[Tuple[float, float, float], Tuple[float, float, float]]
    open_to_bbox_face: bool  # True if cavity touches a bbox face (likely an open end)


@dataclass(frozen=True)
class CavityResult:
    available: bool
    note: Optional[str] = None
    cavities: List[Cavity] = field(default_factory=list)

    @property
    def trapped_cavities(self) -> List[Cavity]:
        return [c for c in self.cavities if not c.open_to_bbox_face]


def _manifold_available() -> bool:
    try:
        import manifold3d  # noqa: F401
        return True
    except ImportError:
        return False


def detect_trapped_cavities(
    mesh: trimesh.Trimesh,
    *,
    min_volume_mm3: float = 100.0,
    ignore_open_cavities: bool = True,
    bbox_open_tolerance_mm: float = 0.5,
) -> CavityResult:
    """Detect internal pockets via ``convex_hull - mesh``.

    Needs ``manifold3d`` for the boolean engine. If it isn't installed,
    returns a ``CavityResult(available=False, note=...)`` so the caller
    can show a one-line "install manifold3d to enable" message without
    failing the run.

    Each cavity is tagged with ``open_to_bbox_face=True`` when its bounding
    box touches a face of the *mesh's* bounding box within
    ``bbox_open_tolerance_mm``. That is a coarse heuristic for "this is the
    open end of a hollow tube, not a sealed pocket". When
    ``ignore_open_cavities=True``, those are excluded from
    ``trapped_cavities`` accessors but still present in ``cavities``.
    """
    if not _manifold_available():
        return CavityResult(
            available=False,
            note="cavity detection requires `pip install manifold3d` (boolean engine).",
        )

    try:
        hull = mesh.convex_hull
        diff = trimesh.boolean.difference([hull, mesh], engine="manifold")
    except Exception as exc:  # pragma: no cover - defensive
        return CavityResult(
            available=False,
            note=f"boolean difference failed: {exc!r}",
        )

    if diff is None or diff.is_empty:
        return CavityResult(available=True, cavities=[])

    if not isinstance(diff, trimesh.Trimesh):
        # Older trimesh returns a list-like in some cases.
        merged = trimesh.util.concatenate(list(diff))
        diff = merged

    mesh_bounds = mesh.bounds  # (2, 3)
    cavities: List[Cavity] = []
    for piece in diff.split(only_watertight=False):
        vol = float(piece.volume) if piece.is_volume else 0.0
        if vol < min_volume_mm3:
            continue
        mn, mx = piece.bounds
        touches_min = np.any(np.abs(mn - mesh_bounds[0]) < bbox_open_tolerance_mm)
        touches_max = np.any(np.abs(mx - mesh_bounds[1]) < bbox_open_tolerance_mm)
        open_to_bbox = bool(touches_min or touches_max)
        c = piece.centroid
        cavities.append(
            Cavity(
                volume_mm3=vol,
                centroid=(float(c[0]), float(c[1]), float(c[2])),
                bounds=(
                    (float(mn[0]), float(mn[1]), float(mn[2])),
                    (float(mx[0]), float(mx[1]), float(mx[2])),
                ),
                open_to_bbox_face=open_to_bbox,
            )
        )
    cavities.sort(key=lambda x: x.volume_mm3, reverse=True)
    note = None
    if ignore_open_cavities and any(c.open_to_bbox_face for c in cavities):
        open_n = sum(1 for c in cavities if c.open_to_bbox_face)
        note = (
            f"{open_n} cavity(ies) touch the bounding box — likely open tube ends; "
            f"not reported as trapped"
        )
    return CavityResult(available=True, cavities=cavities, note=note)
