"""
SLA / resin print optimization stage.

Public entry point: ``optimize_part(part, opt_settings, *, name=None)``.

For PR 1, this only implements orientation search (Tweaker-3). Per-segment
integration with ``max_print_bounds`` and the analyzer suite (overhangs,
islands, cavities) land in follow-up commits.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Tuple, Union

import cadquery as cq
import trimesh

from .orient import find_best_orientations
from .report import OptimizationReport, OrientationCandidate, format_console
from .settings import PrintOptimizationSettings

logger = logging.getLogger(__name__)

__all__ = [
    "optimize_part",
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


def optimize_part(
    part: _PartT,
    opt_settings: PrintOptimizationSettings,
    *,
    name: str = "part",
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
    report.orientation_candidates = candidates

    if not candidates:
        report.note = "Tweaker-3 returned no orientation candidates"
        return part, report

    if opt_settings.orientation.auto_apply:
        best = candidates[0]
        try:
            part = _apply_rotation(part, best)
            report.applied_candidate = best
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("optimize_part: rotation apply failed (%r); skipping.", exc)
            report.note = f"rotation apply failed: {exc!r}"

    return part, report
