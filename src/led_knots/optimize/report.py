"""
Report dataclass + console formatter for the print-optimization stage.

For PR 1 the report holds orientation candidates only; analyzers (overhangs,
islands, cavities) land in a follow-up commit and will populate the empty
fields here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np


@dataclass(frozen=True)
class OrientationCandidate:
    """One result from the Tweaker-3 orientation search.

    ``matrix`` is the 3x3 rotation that maps the original mesh into the
    build orientation (i.e. ``rotated_vertices = vertices @ matrix.T``).
    ``axis`` and ``angle_deg`` are the equivalent axis-angle representation
    suitable for CadQuery's ``rotate((0,0,0), axis, angle_deg)``.
    """

    rank: int
    matrix: np.ndarray
    axis: Tuple[float, float, float]
    angle_deg: float
    unprintability: float
    bottom_area_mm2: float
    overhang_area_mm2: float
    contour_length_mm: float


@dataclass
class OptimizationReport:
    """Collected findings + chosen action for one part."""

    orientation_candidates: List[OrientationCandidate] = field(default_factory=list)
    applied_candidate: Optional[OrientationCandidate] = None
    note: Optional[str] = None


def _axis_angle_str(axis: Tuple[float, float, float], angle_deg: float) -> str:
    return f"axis=({axis[0]:+.3f}, {axis[1]:+.3f}, {axis[2]:+.3f}), angle={angle_deg:6.2f}°"


def format_console(report: OptimizationReport, *, part_name: str = "part") -> str:
    """One-shot text summary of a report. Multi-line, no trailing newline."""
    lines: List[str] = []
    lines.append(f"[optimize] {part_name}: {len(report.orientation_candidates)} orientation candidate(s)")
    if report.note:
        lines.append(f"[optimize] note: {report.note}")
    for cand in report.orientation_candidates:
        marker = " *" if (report.applied_candidate is not None and cand.rank == report.applied_candidate.rank) else "  "
        lines.append(
            f"[optimize] {marker}rank={cand.rank} "
            f"unprintability={cand.unprintability:8.3f}  "
            f"bottom={cand.bottom_area_mm2:7.1f} mm²  "
            f"overhang={cand.overhang_area_mm2:7.1f} mm²  "
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
