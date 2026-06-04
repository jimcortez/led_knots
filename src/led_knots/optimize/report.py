"""
Report dataclass + console formatter for the print-optimization stage.

For PR 1 the report holds orientation candidates only; analyzers (overhangs,
islands, cavities) land in a follow-up commit and will populate the empty
fields here.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Tuple

import numpy as np

from .analysis import CavityResult, IslandResult, OverhangResult
from .face_tagging import FaceTagResult

logger = logging.getLogger(__name__)


# Default annotation palette (RGBA uint8) — used by build_face_color_array
# and by callers that want consistent colors across PNG / viewer layers.
COLOR_DEFAULT = (180, 180, 180, 255)
COLOR_OVERHANG = (255, 60, 60, 255)
COLOR_ISLAND_EXTRA = (255, 200, 0, 255)
COLOR_CONNECTOR = (60, 200, 100, 255)


@dataclass(frozen=True)
class OrientationCandidate:
    """One result from the Tweaker-3 orientation search.

    ``matrix`` is the 3x3 rotation that maps the original mesh into the
    build orientation (i.e. ``rotated_vertices = vertices @ matrix.T``).
    ``axis`` and ``angle_deg`` are the equivalent axis-angle representation
    suitable for CadQuery's ``rotate((0,0,0), axis, angle_deg)``.

    ``connector_bonus`` is in ``[0, 1]`` — area-weighted fraction of
    tagged connector faces that become vertical after the rotation. 0 if
    face tagging didn't run or no connectors were found.
    """

    rank: int
    matrix: np.ndarray
    axis: Tuple[float, float, float]
    angle_deg: float
    unprintability: float
    bottom_area_mm2: float
    overhang_area_mm2: float
    contour_length_mm: float
    connector_bonus: float = 0.0


@dataclass
class OptimizationReport:
    """Collected findings + chosen action for one part."""

    orientation_candidates: List[OrientationCandidate] = field(default_factory=list)
    applied_candidate: Optional[OrientationCandidate] = None
    overhangs: Optional[OverhangResult] = None
    islands: Optional[IslandResult] = None
    cavities: Optional[CavityResult] = None
    connector_tags: Optional[FaceTagResult] = None
    # Tessellated mesh used by the analyzers (in the orientation the part
    # will be exported in). Stashed so callers can render annotated PNGs
    # without re-tessellating. Not part of the printed report.
    mesh: Any = None
    note: Optional[str] = None


def _axis_angle_str(axis: Tuple[float, float, float], angle_deg: float) -> str:
    return f"axis=({axis[0]:+.3f}, {axis[1]:+.3f}, {axis[2]:+.3f}), angle={angle_deg:6.2f}°"


def format_console(report: OptimizationReport, *, part_name: str = "part") -> str:
    """One-shot text summary of a report. Multi-line, no trailing newline."""
    lines: List[str] = []
    lines.append(f"[optimize] {part_name}: {len(report.orientation_candidates)} orientation candidate(s)")
    if report.note:
        lines.append(f"[optimize] note: {report.note}")
    if report.overhangs is not None:
        oh = report.overhangs
        lines.append(
            f"[optimize] overhangs (>{oh.threshold_deg:.0f}° from build axis): "
            f"{oh.total_overhang_area_mm2:.1f} mm² in {len(oh.clusters)} cluster(s)"
        )
        for i, c in enumerate(oh.clusters[:3]):
            lines.append(
                f"[optimize]   #{i+1}: {c.area_mm2:.1f} mm² @ ({c.centroid[0]:+.1f}, "
                f"{c.centroid[1]:+.1f}, {c.centroid[2]:+.1f}) mm"
            )
        if len(oh.clusters) > 3:
            lines.append(f"[optimize]   ... +{len(oh.clusters) - 3} smaller cluster(s)")
    if report.islands is not None:
        isl = report.islands
        if not isl.is_single_body:
            lines.append(
                f"[optimize] islands: {len(isl.components)} disconnected bodies "
                f"(areas: {', '.join(f'{c.area_mm2:.0f}' for c in isl.components[:5])}"
                f"{' ...' if len(isl.components) > 5 else ''} mm²)"
            )
    if report.cavities is not None:
        cv = report.cavities
        if not cv.available:
            lines.append(f"[optimize] cavities: {cv.note}")
        else:
            trapped = cv.trapped_cavities
            lines.append(
                f"[optimize] cavities: {len(trapped)} trapped, "
                f"{len(cv.cavities) - len(trapped)} open"
            )
            if cv.note:
                lines.append(f"[optimize]   note: {cv.note}")
            for i, c in enumerate(trapped[:3]):
                lines.append(
                    f"[optimize]   trapped #{i+1}: {c.volume_mm3:.0f} mm³ @ "
                    f"({c.centroid[0]:+.1f}, {c.centroid[1]:+.1f}, {c.centroid[2]:+.1f}) mm"
                )
    for cand in report.orientation_candidates:
        marker = " *" if (report.applied_candidate is not None and cand.rank == report.applied_candidate.rank) else "  "
        bonus_str = (
            f"  conn={cand.connector_bonus:.2f}"
            if cand.connector_bonus > 0.0
            else ""
        )
        lines.append(
            f"[optimize] {marker}rank={cand.rank} "
            f"unprintability={cand.unprintability:8.3f}  "
            f"bottom={cand.bottom_area_mm2:7.1f} mm²  "
            f"overhang={cand.overhang_area_mm2:7.1f} mm²"
            f"{bonus_str}  "
            f"{_axis_angle_str(cand.axis, cand.angle_deg)}"
        )
    if report.applied_candidate is None and report.orientation_candidates:
        lines.append(
            "[optimize] no rotation applied (auto_apply=false). "
            "Pass --auto-orient to apply rank=1 to the exported geometry."
        )
    elif report.applied_candidate is not None:
        ac = report.applied_candidate
        lines.append(
            f"[optimize] applied rank={ac.rank} "
            f"({_axis_angle_str(ac.axis, ac.angle_deg)})"
        )
    return "\n".join(lines)


def build_face_color_array(
    n_faces: int,
    overhangs: Optional[OverhangResult] = None,
    connector_tags: Optional[FaceTagResult] = None,
) -> np.ndarray:
    """Compose a (F, 4) uint8 RGBA face-color array from analyzer results.

    Default color goes to every face. Connector faces are painted green
    first; overhang faces overlay red on top, so an overhanging connector
    shows as red (the higher-priority finding) — they need supports
    regardless of structural role.
    """
    colors = np.tile(np.asarray(COLOR_DEFAULT, dtype=np.uint8), (n_faces, 1))
    if connector_tags is not None and connector_tags.connector_mask.shape[0] == n_faces:
        colors[connector_tags.connector_mask] = np.asarray(COLOR_CONNECTOR, dtype=np.uint8)
    if overhangs is not None and overhangs.face_mask.shape[0] == n_faces:
        colors[overhangs.face_mask] = np.asarray(COLOR_OVERHANG, dtype=np.uint8)
    return colors


def write_annotated_pngs(
    report: "OptimizationReport",
    mesh,
    out_dir: Path,
    *,
    part_name: str,
    preview_settings: Any,
) -> List[Path]:
    """Write annotated PNGs for the report into ``out_dir``.

    Writes ``{part_name}_overhangs_top.png`` and
    ``{part_name}_overhangs_bottom.png``. Most SLA overhangs are on the
    underside of the part — many are invisible from a top view alone —
    so a bottom view is essential for visual inspection.
    """
    # Local import to avoid a hard dep on pyrender when callers don't use
    # the annotated PNG path.
    from led_knots.core.preview import render_annotated_mesh_to_image

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []

    if report.overhangs is None and report.connector_tags is None:
        return written

    face_colors = build_face_color_array(
        len(mesh.faces),
        overhangs=report.overhangs,
        connector_tags=report.connector_tags,
    )
    base_elevation = float(getattr(preview_settings, "elevation", 30.0))

    for label, elevation in (
        ("top", abs(base_elevation)),
        ("bottom", -abs(base_elevation)),
    ):
        # Shallow per-view settings override without mutating shared config.
        view_settings = _ViewSettings(preview_settings, elevation=elevation)
        out_path = out_dir / f"{part_name}_overhangs_{label}.png"
        try:
            render_annotated_mesh_to_image(
                mesh, out_path, view_settings, face_colors=face_colors
            )
            written.append(out_path)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("annotated PNG render failed for %s view: %r", label, exc)
    return written


class _ViewSettings:
    """Read-only proxy over preview_settings that overrides ``elevation``."""

    def __init__(self, base: Any, *, elevation: float):
        self._base = base
        self._elevation = float(elevation)

    @property
    def elevation(self) -> float:
        return self._elevation

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)
