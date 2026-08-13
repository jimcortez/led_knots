"""
Tube gap: boolean subtraction of an arc-length span from a swept tube.

The gap is cut by sweeping an oversized disc along the sub-path between arc
lengths ``s0..s1``, then subtracting that cutter from the finished tube. The
cut faces are therefore normal to the path tangent and the gap length is
exact when measured along the path, even on curved knots.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Tuple

import numpy as np
import cadquery as cq
from cadquery.func import spline, sweep

logger = logging.getLogger(__name__)

# Auto cutter radius = this factor × tube outer_radius. 1.5 clears every
# registered face type (the square face's half-diagonal is ~1.41 × r).
_AUTO_CUTTER_RADIUS_FACTOR = 1.5

# Fraction of total path length the gap is clamped to, so a misconfigured
# gap can never consume the whole part.
_MAX_GAP_FRACTION = 0.8


@dataclass(frozen=True)
class TubeGapPlacement:
    """Where the gap lands on the path, in arc-length terms."""

    gap_length_mm: float  # effective length after clamping
    s0: float  # arc length of gap start (mm)
    s1: float  # arc length of gap end (mm)
    total_length_mm: float
    start_point: Tuple[float, float, float]
    end_point: Tuple[float, float, float]
    mid_point: Tuple[float, float, float]  # on-path point at (s0 + s1) / 2
    tangent: Tuple[float, float, float]  # unit tangent at mid_point


def _sample_path(path, n_samples: int) -> Tuple[np.ndarray, np.ndarray]:
    """Sample the path uniformly in parameter; return (points, cumulative arc lengths)."""
    n = max(8, int(n_samples))
    pts = np.empty((n, 3), dtype=float)
    for i, t in enumerate(np.linspace(0.0, 1.0, n)):
        p = path.positionAt(float(t))
        pts[i] = (float(p.x), float(p.y), float(p.z))
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate(([0.0], np.cumsum(seg)))
    return pts, cum


def _point_at_arc_length(pts: np.ndarray, cum: np.ndarray, s: float) -> np.ndarray:
    """Linearly interpolate the sampled polyline at arc length ``s``."""
    s = float(np.clip(s, 0.0, cum[-1]))
    i = int(np.searchsorted(cum, s, side="right") - 1)
    i = min(max(i, 0), len(cum) - 2)
    seg_len = cum[i + 1] - cum[i]
    frac = 0.0 if seg_len <= 1e-12 else (s - cum[i]) / seg_len
    return pts[i] + frac * (pts[i + 1] - pts[i])


def compute_gap_placement(
    path,
    gap_length_mm: float,
    center_fraction: float = 0.0,
    *,
    n_samples: int = 1001,
) -> TubeGapPlacement:
    """
    Resolve the gap's arc-length span ``[s0, s1]`` on ``path``.

    ``center_fraction`` in [-0.5, 0.5] places the gap center along the path
    (0.0 = midpoint). The center is shifted inward as needed so the full gap
    always fits, preserving the requested length; the length itself is only
    clamped when it exceeds 80% of the path.
    """
    if gap_length_mm <= 0:
        raise ValueError("gap_length_mm must be > 0 (got %s)" % gap_length_mm)

    pts, cum = _sample_path(path, n_samples)
    total = float(cum[-1])
    if total <= 1e-6:
        raise ValueError("tube_gap: path is degenerate (zero length)")

    gap_len = float(gap_length_mm)
    if gap_len > _MAX_GAP_FRACTION * total:
        gap_len = _MAX_GAP_FRACTION * total
        logger.warning(
            "tube_gap: gap_length_mm=%.1f exceeds %.0f%% of the %.1f mm path; "
            "clamped to %.1f mm",
            gap_length_mm,
            _MAX_GAP_FRACTION * 100,
            total,
            gap_len,
        )

    cf = float(np.clip(center_fraction, -0.5, 0.5))
    center_s = float(np.clip((0.5 + cf) * total, 0.5 * gap_len, total - 0.5 * gap_len))
    s0 = center_s - 0.5 * gap_len
    s1 = center_s + 0.5 * gap_len

    start = _point_at_arc_length(pts, cum, s0)
    end = _point_at_arc_length(pts, cum, s1)
    mid = _point_at_arc_length(pts, cum, center_s)
    # Central-difference tangent at the gap midpoint.
    ds = max(1e-3, min(1.0, 0.01 * gap_len))
    ahead = _point_at_arc_length(pts, cum, center_s + ds)
    behind = _point_at_arc_length(pts, cum, center_s - ds)
    tan = ahead - behind
    mag = float(np.linalg.norm(tan))
    tan = tan / mag if mag > 1e-12 else np.array([0.0, 0.0, 1.0])

    return TubeGapPlacement(
        gap_length_mm=gap_len,
        s0=s0,
        s1=s1,
        total_length_mm=total,
        start_point=tuple(map(float, start)),
        end_point=tuple(map(float, end)),
        mid_point=tuple(map(float, mid)),
        tangent=tuple(map(float, tan)),
    )


def _closed_loop_arclengths(points) -> Tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """
    Normalize a closed point loop for arc-length math: drop a repeated
    closing point, then return ``(pts, ring, cum, total)`` where ``ring``
    appends ``pts[0]`` to close the loop, ``cum[i]`` is the arc position of
    ``ring[i]``, and ``total`` is the full loop length.
    """
    pts = np.asarray([(float(x), float(y), float(z)) for (x, y, z) in points], dtype=float)
    if len(pts) >= 2 and float(np.linalg.norm(pts[0] - pts[-1])) < 1e-6:
        pts = pts[:-1]
    if len(pts) < 4:
        raise ValueError("closed loop needs at least 4 distinct points")
    ring = np.vstack([pts, pts[0]])
    seg = np.linalg.norm(np.diff(ring, axis=0), axis=1)
    cum = np.concatenate(([0.0], np.cumsum(seg)))
    total = float(cum[-1])
    if total <= 1e-6:
        raise ValueError("closed loop is degenerate (zero length)")
    return pts, ring, cum, total


def lowest_z_center_fraction(points, rotation_matrix) -> float:
    """
    Return the ``center_fraction`` in [-0.5, 0.5) that centers the gap on the
    loop point with the lowest Z after applying ``rotation_matrix``.

    ``points`` is a closed loop (a repeated closing point is tolerated, as in
    ``open_loop_with_gap``). ``rotation_matrix`` is the 3x3 orientation matrix
    with the ``rotated = pts @ matrix.T`` convention used by
    ``OrientationCandidate.matrix``. Segments are straight, so the loop's
    minimum Z is always attained at a vertex.
    """
    pts, _ring, cum, total = _closed_loop_arclengths(points)
    R = np.asarray(rotation_matrix, dtype=float)
    if R.shape != (3, 3):
        raise ValueError("rotation_matrix must be 3x3 (got %s)" % (R.shape,))
    rotated_z = (pts @ R.T)[:, 2]
    s_star = float(cum[int(np.argmin(rotated_z))])
    return (s_star % total) / total - 0.5


def open_loop_with_gap(
    points,
    gap_length_mm: float,
    center_fraction: float = 0.0,
) -> List[Tuple[float, float, float]]:
    """
    Open a closed point loop by removing the gap's arc, rolling the sequence
    so the trimmed span becomes the (new) seam.

    This is the gap strategy for closed knots: sweeping the returned open
    polyline yields a tube whose end caps are the gap faces. A boolean cut
    is deliberately avoided because a closed sweep has coincident start/end
    caps, and OCC booleans corrupt self-touching solids.

    ``points`` must trace a closed loop (the closing point may or may not be
    repeated; a repeated one is dropped). ``center_fraction`` in [-0.5, 0.5]
    places the gap center along the loop's arc length measured from the
    original first point; the gap wraps around the loop seam if needed.

    Returns the new open point list, ordered from the gap's far edge around
    the loop to its near edge, with exact interpolated endpoints.
    """
    if gap_length_mm <= 0:
        raise ValueError("gap_length_mm must be > 0 (got %s)" % gap_length_mm)

    pts, ring, cum, total = _closed_loop_arclengths(points)
    n = len(pts)

    gap_len = float(gap_length_mm)
    if gap_len > _MAX_GAP_FRACTION * total:
        gap_len = _MAX_GAP_FRACTION * total
        logger.warning(
            "tube_gap: gap_length_mm=%.1f exceeds %.0f%% of the %.1f mm loop; "
            "clamped to %.1f mm",
            gap_length_mm,
            _MAX_GAP_FRACTION * 100,
            total,
            gap_len,
        )

    cf = float(np.clip(center_fraction, -0.5, 0.5))
    center_s = ((0.5 + cf) * total) % total
    s0 = (center_s - 0.5 * gap_len) % total  # gap start (kept side ends here)
    s1 = (center_s + 0.5 * gap_len) % total  # gap end (kept side starts here)

    def interp(s: float) -> np.ndarray:
        return _point_at_arc_length(ring, cum, s % total)

    # Walk the kept arc from s1 forward (wrapping) to s0.
    kept_len = (s0 - s1) % total
    order = sorted(range(n), key=lambda k: (float(cum[k]) - s1) % total)
    new_pts: List[Tuple[float, float, float]] = [tuple(map(float, interp(s1)))]
    for k in order:
        offset = (float(cum[k]) - s1) % total
        if 1e-9 < offset < kept_len - 1e-9:
            new_pts.append((float(pts[k][0]), float(pts[k][1]), float(pts[k][2])))
    new_pts.append(tuple(map(float, interp(s0))))

    # Drop near-duplicate neighbors (interpolated ends can coincide with samples).
    deduped: List[Tuple[float, float, float]] = [new_pts[0]]
    for p in new_pts[1:]:
        if np.linalg.norm(np.asarray(p) - np.asarray(deduped[-1])) > 1e-6:
            deduped.append(p)

    logger.info(
        "tube_gap: opened closed loop with %.1f mm gap centered at arc "
        "length %.1f mm of %.1f mm",
        gap_len,
        center_s,
        total,
    )
    return deduped


def gap_cutter_radius(config) -> float:
    """Cutter disc radius: explicit override, else 1.5 × tube outer_radius."""
    override = getattr(config.tube_gap, "cutter_radius_mm", None)
    if override:
        return float(override)
    return _AUTO_CUTTER_RADIUS_FACTOR * float(config.tube_settings.outer_radius)


def build_gap_cutter(path, placement: TubeGapPlacement, radius_mm: float):
    """
    Build the cutter solid: a disc of ``radius_mm`` swept along the sub-path
    spanning ``[placement.s0, placement.s1]``.
    """
    from .led_circle import create_solid_circle_face

    pts, cum = _sample_path(path, 1001)
    # ~1 point per 2 mm of gap, bounded so the spline stays cheap and stable.
    n_cutter = int(np.clip(round(placement.gap_length_mm / 2.0), 8, 64))
    s_values = np.linspace(placement.s0, placement.s1, n_cutter)
    cutter_pts: List[Tuple[float, float, float]] = [
        tuple(map(float, _point_at_arc_length(pts, cum, s))) for s in s_values
    ]

    sub_wire = spline(cutter_pts)
    disc = create_solid_circle_face(
        outer_radius=float(radius_mm),
        wall_thickness=0.0,
        orient_to_path=sub_wire,
        rotation_z=0.0,
    )
    try:
        return sweep(disc, sub_wire)
    except Exception as exc:
        raise RuntimeError(
            "tube_gap: cutter sweep failed (radius %.1f mm along %.1f mm of path). "
            "The path likely bends tighter than the cutter radius here; try a "
            "smaller tube_gap.cutter_radius_mm or a different center_fraction."
            % (radius_mm, placement.gap_length_mm)
        ) from exc


def apply_tube_gap(result, path, config):
    """
    Subtract the configured gap from ``result`` (the finished tube geometry).

    No-op when ``config.tube_gap`` is absent or disabled. ``result`` may be a
    Workplane, Solid, or Compound; returns the cut Shape (typically a
    two-solid Compound for an open path).
    """
    tg = getattr(config, "tube_gap", None)
    if tg is None or not tg.enabled or tg.gap_length_mm <= 0:
        return result

    # A closed sweep has coincident start/end caps; OCC booleans corrupt
    # self-touching solids (webbed faces, open shells). Closed knots must
    # open the loop at the point level instead (open_loop_with_gap, applied
    # by draw_knot_points), which never reaches this code.
    start = path.positionAt(0.0)
    end = path.positionAt(1.0)
    if start.sub(end).Length < 1e-3:
        raise RuntimeError(
            "tube_gap: sweep path is a closed loop; a boolean cut would "
            "corrupt the coincident seam. Apply the gap at the point level "
            "with open_loop_with_gap before splining (draw_knot_points does "
            "this automatically for closed knots)."
        )

    shape = result.val() if hasattr(result, "val") else result
    placement = compute_gap_placement(
        path, tg.gap_length_mm, center_fraction=tg.center_fraction
    )
    radius = gap_cutter_radius(config)
    cutter = build_gap_cutter(path, placement, radius)
    try:
        cut = shape.cut(cutter)
    except Exception as exc:
        raise RuntimeError(
            "tube_gap: boolean subtraction failed; try adjusting "
            "tube_gap.cutter_radius_mm or center_fraction."
        ) from exc

    logger.info(
        "tube_gap: cut %.1f mm gap at arc length %.1f–%.1f mm of %.1f mm "
        "(cutter radius %.1f mm)",
        placement.gap_length_mm,
        placement.s0,
        placement.s1,
        placement.total_length_mm,
        radius,
    )
    stats = getattr(config, "render_stats", None)
    if stats is not None:
        stats.add_stat("tube_gap.gap_length_mm", placement.gap_length_mm, "Effective gap length")
        stats.add_stat("tube_gap.s0_mm", placement.s0, "Gap start arc length")
        stats.add_stat("tube_gap.s1_mm", placement.s1, "Gap end arc length")
        stats.add_stat("tube_gap.mid_point", placement.mid_point, "Gap midpoint (path coords)")
    return cut


__all__ = [
    "TubeGapPlacement",
    "compute_gap_placement",
    "gap_cutter_radius",
    "build_gap_cutter",
    "apply_tube_gap",
    "open_loop_with_gap",
    "lowest_z_center_fraction",
]
