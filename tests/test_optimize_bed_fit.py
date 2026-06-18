"""Bed-fit gate for print orientation."""

from __future__ import annotations

import numpy as np
import pytest
import trimesh

from led_knots.optimize import _filter_candidates_by_bed
from led_knots.optimize.report import OrientationCandidate


class _Bounds:
    def __init__(self, width: float, length: float, height: float):
        self.width = width
        self.length = length
        self.height = height


def _candidate(matrix: np.ndarray) -> OrientationCandidate:
    return OrientationCandidate(
        rank=1,
        matrix=matrix,
        axis=(0.0, 0.0, 1.0),
        angle_deg=0.0,
        unprintability=1.0,
        bottom_area_mm2=0.0,
        overhang_area_mm2=0.0,
        contour_length_mm=0.0,
    )


def test_bed_fit_allows_output_bounds_sized_part_with_zero_clearance() -> None:
    """Parts scaled to output_bounds should pass when clearance is 0."""
    mesh = trimesh.creation.box(extents=(200.05, 191.3, 89.9))
    bed = _Bounds(width=200.0, length=110.0, height=200.0)
    out = _filter_candidates_by_bed(mesh, [_candidate(np.eye(3))], bed, bed_clearance_mm=0.0)
    assert len(out) == 1
    assert out[0].fits_bed is True


def test_bed_fit_rejects_when_clearance_shrinks_bed_past_part() -> None:
    """Applying printer clearance on top of output_bounds sizing is too strict."""
    mesh = trimesh.creation.box(extents=(200.05, 191.3, 89.9))
    bed = _Bounds(width=200.0, length=110.0, height=200.0)
    out = _filter_candidates_by_bed(mesh, [_candidate(np.eye(3))], bed, bed_clearance_mm=2.0)
    assert len(out) == 1
    assert out[0].fits_bed is False


def test_bed_fit_sorted_assignment_uses_smallest_bed_axis() -> None:
    """The 89.9 mm extent must map to the 110 mm bed axis, not 200 mm."""
    mesh = trimesh.creation.box(extents=(200.0, 191.0, 89.9))
    bed = _Bounds(width=200.0, length=110.0, height=200.0)
    out = _filter_candidates_by_bed(mesh, [_candidate(np.eye(3))], bed, bed_clearance_mm=0.0)
    assert out[0].fits_bed is True
