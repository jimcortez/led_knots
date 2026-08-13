"""Shared scaffold for turning pyknotid point data into a swept knot part.

Every pyknotid-derived knot module does the same four things: scale the raw
points into the configured build volume, open the loop into a spline, solve a
twist schedule against an offset aux spine, and hand both to draw_part. This
collapses that into one call so a knot module is just its path source.
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence, Tuple

import numpy as np
from cadquery.func import spline

from .config import Config
from .path_utils import build_ribbon_aux_spine
from .pyknot_utils import scale_pyknot_points
from .utils import draw_part

logger = logging.getLogger(__name__)


def resolve_lowest_z_gap(
    knot_points,
    config: Config,
    *,
    aux: bool = True,
    num_samples: int = 150,
    spine_offset_radius: float = 5.0,
):
    """
    Pass-1 orientation probe for ``tube_gap.placement: lowest_z``.

    Builds the tube once with the manual (provisional) ``center_fraction``,
    runs the orientation search on it, and derives the ``center_fraction``
    that puts the gap at the lowest point of the oriented knot — so the gap
    doubles as a resin drain/vent at the bottom of the print. The chosen
    orientation is returned so the final build can pin it (re-searching on
    the re-seamed part could flip to a different candidate and invalidate
    the derived fraction).

    Returns ``(center_fraction, orientation_candidate)``, or ``(None, None)``
    when placement resolution is unavailable or fails — the caller then falls
    back to the manual ``center_fraction``. This function must never fail the
    build. Note: ``build_ribbon_aux_spine`` runs on the provisionally-seamed
    path here and again on the re-seamed final path; a twist-solver failure
    on the final path surfaces from the main flow with its usual message.
    """
    from led_knots.optimize import select_orientation

    from .tube_gap import (
        _closed_loop_arclengths,
        _point_at_arc_length,
        lowest_z_center_fraction,
        open_loop_with_gap,
    )
    from .utils import build_tube_from_path, ensure_render_stats, resolve_bed_bounds

    tg = config.tube_gap
    po = getattr(config, "print_optimization", None)

    fallback_reason = None
    if (
        po is None
        or not po.enabled
        or not po.orientation.enabled
        or not po.orientation.auto_apply
    ):
        fallback_reason = (
            "requires print optimization with orientation.auto_apply "
            "(pass --auto-orient)"
        )
    elif config.max_print_bounds.enabled:
        fallback_reason = (
            "segmented builds are unsupported — per-segment rotations have "
            "no single global bottom"
        )

    stats = ensure_render_stats(config)
    stats.add_stat("tube_gap.placement", tg.placement, "Gap placement mode")
    if fallback_reason:
        logger.warning(
            "tube_gap.placement=lowest_z: falling back to manual "
            "center_fraction — %s",
            fallback_reason,
        )
        stats.add_stat(
            "tube_gap.placement_fallback",
            fallback_reason,
            "Why lowest_z placement fell back to manual center_fraction",
        )
        return None, None

    try:
        with stats.record_stage("draw_knot_points.gap_orientation_pass"):
            pts1 = open_loop_with_gap(
                knot_points, tg.gap_length_mm, center_fraction=tg.center_fraction
            )
            path1 = spline(pts1)
            aux_spine = None
            rotation_z = 0.0
            if aux:
                aux_spine, rotation_z = build_ribbon_aux_spine(
                    path1,
                    config,
                    num_samples=num_samples,
                    spine_offset_radius=spine_offset_radius,
                )
            tube1 = build_tube_from_path(
                path1, config, aux=aux_spine, face_kwargs={"rotation_z": rotation_z}
            )
            bed_bounds, bed_clearance = resolve_bed_bounds(config)
            _mesh, candidates, _tags, note = select_orientation(
                tube1,
                po,
                name=(config.name or "part") + " (gap placement pass)",
                path=path1,
                tube_settings=config.tube_settings,
                output_bounds=bed_bounds,
                bed_clearance_mm=bed_clearance,
            )
            if not candidates:
                raise RuntimeError(
                    "orientation search returned no candidates"
                    + (f" ({note})" if note else "")
                )
            best = candidates[0]
            cf = float(lowest_z_center_fraction(knot_points, best.matrix))
    except Exception as exc:
        logger.warning(
            "tube_gap.placement=lowest_z: pre-pass failed (%r); falling back "
            "to manual center_fraction",
            exc,
        )
        stats.add_stat(
            "tube_gap.placement_fallback",
            repr(exc),
            "Why lowest_z placement fell back to manual center_fraction",
        )
        return None, None

    # Record where the gap center lands relative to the oriented path's low
    # point so "the gap is at the bottom" is checkable from the stats export.
    pts, ring, cum, total = _closed_loop_arclengths(knot_points)
    rot = np.asarray(best.matrix, dtype=float)
    rotated_z = (pts @ rot.T)[:, 2]
    center_s = ((0.5 + cf) * total) % total
    gap_mid_z = float((_point_at_arc_length(ring, cum, center_s) @ rot.T)[2])
    stats.add_stat(
        "tube_gap.resolved_center_fraction",
        cf,
        "center_fraction derived by lowest_z placement",
    )
    stats.add_stat(
        "tube_gap.oriented_min_z_mm",
        float(rotated_z.min()),
        "Min Z of the knot path after the applied orientation",
    )
    stats.add_stat(
        "tube_gap.oriented_gap_mid_z_mm",
        gap_mid_z,
        "Z of the gap center after the applied orientation",
    )
    logger.info(
        "tube_gap: lowest_z placement resolved center_fraction=%.4f "
        "(gap center Z %.2f mm, path min Z %.2f mm after orientation)",
        cf,
        gap_mid_z,
        float(rotated_z.min()),
    )
    return cf, best


def draw_knot_points(
    points: np.ndarray,
    config: Config,
    *,
    drop_last: int = 0,
    bounds: Optional[Tuple[float, float, float]] = None,
    preserve_aspect_ratio: bool = True,
    aux: bool = True,
    num_samples: int = 150,
    spine_offset_radius: float = 5.0,
) -> None:
    """
    Scale pyknotid points into the build volume, open the loop, and draw it.

    Args:
        points: Raw closed-loop points from pyknotid, shape (n, 3), in
            pyknotid's own units. The closing point must not be repeated.
        config: Render config; supplies output_bounds and tube_settings.
        drop_last: Trailing points to discard, which is what cuts the physical
            gap in the otherwise closed loop. 1 leaves a hairline seam; the
            ring uses 10 for a visible break.
        bounds: (width, height, length) to scale into, overriding
            config.output_bounds. Only needed by planar knots that want a
            different axis mapping than the default one.
        preserve_aspect_ratio: Passed to scale_pyknot_points. False stretches
            each axis independently to fill the box.
        aux: Build a twist-constrained aux spine (build_ribbon_aux_spine). Set
            False for paths with no meaningful curvature, or planar paths that
            need no twist schedule.
        num_samples: Samples along the path for the twist solver.
        spine_offset_radius: Radial offset of the aux spine, in mm.

    Raises:
        ValueError: From build_ribbon_aux_spine when the path bends faster
            than min_90_degree_twist_distance allows. The fix is a larger
            output_bounds in that knot's config, not a change here.
    """
    if bounds is None:
        bounds = (
            config.output_bounds.width,
            config.output_bounds.height,
            config.output_bounds.length,
        )
    width, height, length = bounds

    knot_points = scale_pyknot_points(
        points,
        width=width,
        height=height,
        length=length,
        padding=config.tube_settings.outer_radius,
        preserve_aspect_ratio=preserve_aspect_ratio,
    )

    # For an intact closed loop, the gap is applied at the point level: the
    # loop is rolled and trimmed so the sweep is open with the gap at its
    # ends. A boolean cut on the closed sweep would corrupt its coincident
    # seam caps. With drop_last the path is already open, so draw_part's
    # boolean cut handles the gap instead.
    tube_gap_handled = False
    pinned_orientation = None
    tg = getattr(config, "tube_gap", None)
    if tg is not None and tg.enabled and tg.gap_length_mm > 0 and not drop_last:
        from .tube_gap import open_loop_with_gap

        center_fraction = tg.center_fraction
        if getattr(tg, "placement", "manual") == "lowest_z":
            resolved_cf, pinned_orientation = resolve_lowest_z_gap(
                knot_points,
                config,
                aux=aux,
                num_samples=num_samples,
                spine_offset_radius=spine_offset_radius,
            )
            if resolved_cf is not None:
                center_fraction = resolved_cf
        knot_points = open_loop_with_gap(
            knot_points, tg.gap_length_mm, center_fraction=center_fraction
        )
        tube_gap_handled = True

    path = spline(knot_points[:-drop_last] if drop_last else knot_points)

    if not aux:
        draw_part(
            path,
            config,
            tube_gap_handled=tube_gap_handled,
            pinned_orientation=pinned_orientation,
            rotation_z=0.0,
        )
        return

    aux_spine, initial_rotation = build_ribbon_aux_spine(
        path,
        config,
        num_samples=num_samples,
        spine_offset_radius=spine_offset_radius,
    )

    draw_part(
        path,
        config,
        aux=aux_spine,
        tube_gap_handled=tube_gap_handled,
        pinned_orientation=pinned_orientation,
        rotation_z=initial_rotation,
    )


__all__ = ["draw_knot_points", "resolve_lowest_z_gap"]
