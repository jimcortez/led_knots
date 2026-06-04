"""
SLA / resin print optimization stage.

Public entry point: ``optimize_part(part, opt_settings, *, name=None)``.

For PR 1, this only implements orientation search (Tweaker-3). Per-segment
integration with ``max_print_bounds`` and the analyzer suite (overhangs,
islands, cavities) land in follow-up commits.
"""

from __future__ import annotations

import logging
import math
import os
import tempfile
from pathlib import Path
from typing import Tuple, Union

import cadquery as cq
import numpy as np
import trimesh

from .analysis import detect_islands, detect_overhangs, detect_trapped_cavities
from .face_tagging import FaceTagResult, tag_connector_faces
from .orient import (
    best_rotation_by_overhang,
    connector_verticality_bonus,
    find_best_orientations,
    rescore_candidates_with_connector_bonus,
)
from .report import OptimizationReport, OrientationCandidate, format_console
from .settings import PrintOptimizationSettings

logger = logging.getLogger(__name__)

__all__ = [
    "optimize_part",
    "best_orientation_index",
    "OptimizationReport",
    "OrientationCandidate",
    "PrintOptimizationSettings",
    "format_console",
]


_PartT = Union[cq.Workplane, cq.Solid, cq.Compound, cq.Assembly]


def _to_trimesh(part: _PartT) -> trimesh.Trimesh:
    """Tessellate a CadQuery part to a trimesh ``Trimesh`` via temp STL.

    Mirrors ``_solid_to_glb_bytes`` in ``led_knots.core.render_pipeline`` but
    skips GLB and returns the mesh directly. Uses a coarse tessellation
    (the optimizer only needs face normals, not viewing-quality smoothness).
    """
    if isinstance(part, cq.Assembly):
        solid = part.toCompound()
    elif hasattr(part, "val"):
        solid = part.val()
    else:
        solid = part

    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tf:
        tmp = tf.name
    try:
        cq.exporters.export(
            solid,
            tmp,
            tolerance=0.05,
            angularTolerance=0.3,
            opt={"ascii": False},
        )
        loaded = trimesh.load(tmp)
        if isinstance(loaded, trimesh.Scene):
            mesh = loaded.dump(concatenate=True)
        else:
            mesh = loaded
        return mesh
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _apply_rotation(part: _PartT, candidate: OrientationCandidate) -> _PartT:
    """Rotate a CadQuery part in place using the candidate's axis-angle.

    PR 1 handles the non-assembly case (single Solid / Compound). For
    assemblies, this stage is skipped earlier (segmentation flow lands in
    PR 2).
    """
    if candidate.angle_deg == 0.0:
        return part
    if isinstance(part, cq.Assembly):
        # Defensive: segmentation flow is meant to skip this in PR 1.
        raise NotImplementedError(
            "optimize_part: assembly rotation lands in the per-segment "
            "integration commit; should not reach here in PR 1."
        )
    solid = part.val() if hasattr(part, "val") else part
    rotated = solid.rotate(
        (0.0, 0.0, 0.0),
        (candidate.axis[0], candidate.axis[1], candidate.axis[2]),
        candidate.angle_deg,
    )
    return rotated


def best_orientation_index(
    part: _PartT,
    rotation_matrices,
    *,
    overhang_threshold_deg: float = 35.0,
    path=None,
    tube_settings=None,
    connector_bonus_weight: float = 0.0,
) -> int:
    """
    Pick the rotation that minimises SLA support need when applied to ``part``.

    Base score is overhang area (lower = better). When ``path`` and
    ``tube_settings`` are supplied and ``connector_bonus_weight > 0``,
    faces are tagged for connector-flank role and the score is shaved by
    ``(1 - weight * connector_verticality)`` — same multiplicative form
    as ``rescore_candidates_with_connector_bonus`` so scores remain
    comparable across the two code paths.

    Returns the winning index into ``rotation_matrices`` (0 if the list is
    empty).
    """
    if not rotation_matrices:
        return 0
    mesh = _to_trimesh(part)

    connector_mask = None
    if (
        path is not None
        and tube_settings is not None
        and connector_bonus_weight > 0.0
    ):
        try:
            tags = tag_connector_faces(mesh, path, tube_settings)
            if tags.n_connector_faces > 0:
                connector_mask = tags.connector_mask
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("best_orientation_index: face tagging failed (%r)", exc)

    if connector_mask is None:
        idx, _ = best_rotation_by_overhang(
            mesh, rotation_matrices, overhang_threshold_deg=overhang_threshold_deg
        )
        return idx

    # Combined score: overhang area * (1 - w * connector_verticality)
    from .orient import score_orientation_overhang

    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    weight = float(connector_bonus_weight)
    best_idx = 0
    best_score = math.inf
    for i, mat in enumerate(rotation_matrices):
        overhang = score_orientation_overhang(
            normals, areas, mat, overhang_threshold_deg=overhang_threshold_deg
        )
        bonus = connector_verticality_bonus(normals, areas, connector_mask, mat)
        adjusted = overhang * (1.0 - weight * bonus)
        if adjusted < best_score:
            best_score = adjusted
            best_idx = i
    return best_idx


def _compute_rotated_extents(mesh: trimesh.Trimesh, R: np.ndarray) -> tuple:
    """Return ``(extents_x, extents_y, extents_z)`` of the AABB after applying R.

    Cheaper than ``apply_transform`` + ``.bounding_box`` (which copies the
    full mesh): rotate vertices once and read min/max.
    """
    rotated_v = mesh.vertices @ R.T  # equivalent to (R @ v.T).T
    mn = rotated_v.min(axis=0)
    mx = rotated_v.max(axis=0)
    ext = mx - mn
    return (float(ext[0]), float(ext[1]), float(ext[2]))


def _filter_candidates_by_bed(
    mesh: trimesh.Trimesh,
    candidates: List[OrientationCandidate],
    output_bounds,
    bed_clearance_mm: float = 2.0,
) -> List[OrientationCandidate]:
    """Tag each candidate with its rotated extents and drop ones that don't fit.

    Returns the surviving candidates with ``rotated_extents_mm`` and
    ``fits_bed`` populated. The caller can also keep dropped candidates
    if every candidate fails — see ``optimize_part`` for that fallback.
    """
    if output_bounds is None:
        return candidates
    bed = sorted(
        [
            float(getattr(output_bounds, "width", math.inf)) - 2.0 * bed_clearance_mm,
            float(getattr(output_bounds, "length", math.inf)) - 2.0 * bed_clearance_mm,
            float(getattr(output_bounds, "height", math.inf)) - 2.0 * bed_clearance_mm,
        ],
        reverse=True,
    )

    out: List[OrientationCandidate] = []
    for cand in candidates:
        ext = _compute_rotated_extents(mesh, cand.matrix)
        sorted_ext = sorted(ext, reverse=True)
        fits = (
            sorted_ext[0] <= bed[0]
            and sorted_ext[1] <= bed[1]
            and sorted_ext[2] <= bed[2]
        )
        # OrientationCandidate is frozen — rebuild with the new fields.
        out.append(
            OrientationCandidate(
                rank=cand.rank,
                matrix=cand.matrix,
                axis=cand.axis,
                angle_deg=cand.angle_deg,
                unprintability=cand.unprintability,
                bottom_area_mm2=cand.bottom_area_mm2,
                overhang_area_mm2=cand.overhang_area_mm2,
                contour_length_mm=cand.contour_length_mm,
                connector_bonus=cand.connector_bonus,
                rotated_extents_mm=ext,
                fits_bed=bool(fits),
            )
        )
    return out


def optimize_part(
    part: _PartT,
    opt_settings: PrintOptimizationSettings,
    *,
    name: str = "part",
    path=None,
    tube_settings=None,
    output_bounds=None,
    bed_clearance_mm: float = 2.0,
) -> Tuple[_PartT, OptimizationReport]:
    """
    Analyze a built part for SLA-print problems and (optionally) re-orient it.

    Returns ``(maybe_rotated_part, report)``. The caller is responsible for
    logging or otherwise consuming the report — this function does not print.

    Assemblies and parts produced by the segmented-build flow are out of
    scope for PR 1 and return a no-op report with a ``note``.
    """
    report = OptimizationReport()

    if isinstance(part, cq.Assembly):
        report.note = (
            "skipped: assembly inputs (segmented prints) land in a follow-up commit"
        )
        return part, report

    if not opt_settings.orientation.enabled:
        report.note = "orientation disabled in config"
        return part, report

    try:
        mesh = _to_trimesh(part)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("optimize_part: tessellation failed (%r); skipping.", exc)
        report.note = f"tessellation failed: {exc!r}"
        return part, report

    candidates = find_best_orientations(
        mesh,
        top_n=opt_settings.orientation.top_n_candidates,
        min_volume=True,
    )

    # Connector-aware rescoring (PR4). Skipped when path/tube_settings
    # aren't supplied (e.g. non-knot callers) or when the face type has
    # no connectors. The bonus shaves Tweaker-3's volume-minimising score
    # so orientations that stand the connector strips vertically (acting
    # as natural support columns) are preferred.
    connector_tags = None
    if (
        path is not None
        and tube_settings is not None
        and opt_settings.orientation.connector_bonus_weight > 0.0
    ):
        try:
            connector_tags = tag_connector_faces(mesh, path, tube_settings)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("optimize_part: face tagging failed (%r)", exc)
            connector_tags = None
        if connector_tags is not None and connector_tags.n_connector_faces > 0:
            candidates = rescore_candidates_with_connector_bonus(
                candidates,
                mesh,
                connector_tags.connector_mask,
                bonus_weight=opt_settings.orientation.connector_bonus_weight,
            )
        report.connector_tags = connector_tags

    # Bed-fit gate (SF2): drop candidates whose rotated AABB exceeds the
    # build volume. Annotates the survivors with ``rotated_extents_mm``.
    # If every candidate fails (e.g. part is too big for the bed in any
    # orientation), retain the original list with a clear note rather
    # than silently emitting an empty result.
    notes: List[str] = []
    if output_bounds is not None and candidates:
        annotated = _filter_candidates_by_bed(
            mesh, candidates, output_bounds, bed_clearance_mm=bed_clearance_mm
        )
        survivors = [c for c in annotated if c.fits_bed]
        if survivors:
            # Re-rank survivors 1..N (preserves the relative order from
            # rescoring; this is just renumbering).
            candidates = [
                OrientationCandidate(
                    rank=i + 1,
                    matrix=c.matrix,
                    axis=c.axis,
                    angle_deg=c.angle_deg,
                    unprintability=c.unprintability,
                    bottom_area_mm2=c.bottom_area_mm2,
                    overhang_area_mm2=c.overhang_area_mm2,
                    contour_length_mm=c.contour_length_mm,
                    connector_bonus=c.connector_bonus,
                    rotated_extents_mm=c.rotated_extents_mm,
                    fits_bed=c.fits_bed,
                )
                for i, c in enumerate(survivors)
            ]
            dropped = len(annotated) - len(survivors)
            if dropped > 0:
                notes.append(
                    f"{dropped} of {len(annotated)} candidate(s) dropped — rotated AABB exceeds output_bounds (clearance {bed_clearance_mm}mm)"
                )
        else:
            candidates = annotated  # keep extents for reporting
            notes.append(
                "no candidate fits output_bounds; reporting all anyway"
            )

    # Diagnostic warnings (NH1): when no candidate has any flat bed
    # contact, the optimizer is essentially picking the least-bad among
    # equally unsupportable poses. Surface this so the user knows
    # supports are unavoidable, regardless of orientation.
    if candidates and all(c.bottom_area_mm2 <= 1.0 for c in candidates):
        notes.append(
            "all candidates have <=1 mm² bed contact — no defensible flat side; "
            "supports will be needed regardless of orientation"
        )

    if notes:
        report.note = "; ".join(notes)

    report.orientation_candidates = candidates

    if not candidates:
        report.note = (report.note or "") + " | Tweaker-3 returned no orientation candidates"
        return part, report

    if opt_settings.orientation.auto_apply:
        best = candidates[0]
        try:
            part = _apply_rotation(part, best)
            report.applied_candidate = best
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("optimize_part: rotation apply failed (%r); skipping.", exc)
            report.note = f"rotation apply failed: {exc!r}"

    # Use the same trimesh for the analyzers as for tagging so face
    # indices stay valid. When the orientation was applied, rotate the
    # mesh's vertices in-place (preserves face indices, unlike
    # re-tessellating from the rotated CadQuery part).
    if opt_settings.orientation.auto_apply and report.applied_candidate is not None:
        rotated_mesh = mesh.copy()
        T = np.eye(4)
        T[:3, :3] = report.applied_candidate.matrix
        rotated_mesh.apply_transform(T)
        analysis_mesh = rotated_mesh
    else:
        analysis_mesh = mesh

    try:
        report.overhangs = detect_overhangs(
            analysis_mesh, threshold_deg=opt_settings.overhang_threshold_deg
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("optimize_part: overhang analyzer failed (%r)", exc)
    try:
        report.islands = detect_islands(analysis_mesh)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("optimize_part: island analyzer failed (%r)", exc)
    try:
        report.cavities = detect_trapped_cavities(analysis_mesh)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("optimize_part: cavity analyzer failed (%r)", exc)

    report.mesh = analysis_mesh
    return part, report
