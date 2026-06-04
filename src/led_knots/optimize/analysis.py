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
    min_area_mm2: Optional[float] = None,
    min_area_fraction: float = 0.001,
) -> IslandResult:
    """Split ``mesh`` into topologically disconnected bodies.

    Returns an ``IslandResult``. Useful as a *whole-mesh* check: anything
    beyond one body means a piece is unanchored. (Per-layer island
    detection — the more common SLA failure — needs a slicer pass and is
    deferred to a future commit.)

    The default minimum-area floor scales with the mesh's total surface
    area (``min_area_fraction`` of total, default 0.1%) so tessellation
    fragments and tiny disconnected slivers — e.g. sine_wave's 325
    pseudo-islands — don't drown the report. Pass an explicit
    ``min_area_mm2`` to override.
    """
    if min_area_mm2 is None:
        min_area_mm2 = max(0.5, float(mesh.area) * float(min_area_fraction))
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
    is_trapped: bool  # ray-casting test: True if all 26 rays from centroid hit the mesh


@dataclass(frozen=True)
class CavityResult:
    available: bool
    note: Optional[str] = None
    cavities: List[Cavity] = field(default_factory=list)

    @property
    def trapped_cavities(self) -> List[Cavity]:
        return [c for c in self.cavities if c.is_trapped]


def _manifold_available() -> bool:
    try:
        import manifold3d  # noqa: F401
        return True
    except ImportError:
        return False


def _unit_sphere_directions_26() -> np.ndarray:
    """26 unit vectors covering the cube's faces, edges, and corners.

    Combined: 6 axis-aligned + 12 edge-diagonals + 8 corners = 26 rays.
    Coverage is dense enough that any directional escape path through
    a non-convex cavity opening will hit at least one ray's null-result.
    """
    s2 = 1.0 / math.sqrt(2.0)
    s3 = 1.0 / math.sqrt(3.0)
    dirs: List[Tuple[float, float, float]] = []
    for sign in (-1.0, 1.0):
        dirs += [(sign, 0.0, 0.0), (0.0, sign, 0.0), (0.0, 0.0, sign)]
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            dirs.append((sx * s2, sy * s2, 0.0))
            dirs.append((sx * s2, 0.0, sy * s2))
            dirs.append((0.0, sx * s2, sy * s2))
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            for sz in (-1.0, 1.0):
                dirs.append((sx * s3, sy * s3, sz * s3))
    return np.asarray(dirs, dtype=np.float64)


def _is_cavity_trapped(mesh: trimesh.Trimesh, point: np.ndarray) -> bool:
    """Ray-cast from ``point`` in 26 directions; return True if every ray hits.

    For a watertight, manifold mesh: a point in a *sealed* cavity has the
    mesh between it and infinity in every direction (every ray hits). A
    point in an *open* cavity has at least one direction where rays exit
    without intersecting the mesh.

    We use ``mesh.ray.intersects_id`` (returns one entry per ray hit) and
    count hits per ray. A ray with zero hits means an escape route.
    """
    dirs = _unit_sphere_directions_26()
    n = len(dirs)
    origins = np.tile(point, (n, 1))
    try:
        # intersects_id returns (index_tri, index_ray) of hits.
        _, ray_idx = mesh.ray.intersects_id(
            origins, dirs, multiple_hits=False, return_locations=False
        )
    except Exception:  # pragma: no cover - defensive
        return False
    hit_rays = set(int(i) for i in ray_idx)
    return len(hit_rays) == n


def detect_trapped_cavities(
    mesh: trimesh.Trimesh,
    *,
    min_volume_mm3: float = 100.0,
) -> CavityResult:
    """Detect internal pockets via ``convex_hull - mesh`` + ray-cast trap test.

    The convex-hull difference is only the *first* filter — for non-convex
    meshes (every knot in this codebase) it also includes huge external
    concavities that aren't real cavities. The 26-ray trap test on each
    candidate's centroid is the actual decision: a centroid surrounded by
    the mesh on all sides is a trapped cavity; anything with an escape
    direction is not.

    Needs ``manifold3d`` for the boolean engine. If it isn't installed,
    returns a ``CavityResult(available=False, note=...)`` so the caller
    can show a one-line "install manifold3d to enable" message without
    failing the run.
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
        merged = trimesh.util.concatenate(list(diff))
        diff = merged

    cavities: List[Cavity] = []
    for piece in diff.split(only_watertight=False):
        vol = float(piece.volume) if piece.is_volume else 0.0
        if vol < min_volume_mm3:
            continue
        mn, mx = piece.bounds
        c = piece.centroid
        is_trapped = _is_cavity_trapped(mesh, np.asarray(c, dtype=np.float64))
        cavities.append(
            Cavity(
                volume_mm3=vol,
                centroid=(float(c[0]), float(c[1]), float(c[2])),
                bounds=(
                    (float(mn[0]), float(mn[1]), float(mn[2])),
                    (float(mx[0]), float(mx[1]), float(mx[2])),
                ),
                is_trapped=is_trapped,
            )
        )
    cavities.sort(key=lambda x: x.volume_mm3, reverse=True)
    open_n = sum(1 for c in cavities if not c.is_trapped)
    note = None
    if open_n > 0:
        note = (
            f"{open_n} candidate(s) had an escape route by ray-cast and were "
            f"classified as open (not trapped)"
        )
    return CavityResult(available=True, cavities=cavities, note=note)
