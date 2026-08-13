"""
Registration and lap-joint geometry helpers for segmented prints.
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

import cadquery as cq
import numpy as np


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n < 1e-9:
        return np.array([0.0, 0.0, 1.0], dtype=float)
    return v / n


def _shape_from_any(obj):
    if hasattr(obj, "val"):
        return obj.val()
    return obj


def joint_tangent_at_cut(
    sampled_points: Sequence[Tuple[float, float, float]],
    cut_idx: int,
) -> np.ndarray:
    """Unit tangent along the path at an internal segment boundary (cut index)."""
    n = len(sampled_points)
    if n < 2:
        return np.array([0.0, 0.0, 1.0], dtype=float)
    i = int(cut_idx)
    if i <= 0:
        p0, p1 = sampled_points[0], sampled_points[1]
    elif i >= n - 1:
        p0, p1 = sampled_points[n - 2], sampled_points[n - 1]
    else:
        p0, p1 = sampled_points[i - 1], sampled_points[i + 1]
    return _unit(np.asarray(p1, dtype=float) - np.asarray(p0, dtype=float))


def joint_radial_direction(
    tangent: Sequence[float],
    ref_up: Sequence[float] = (0.0, 0.0, 1.0),
) -> np.ndarray:
    """Unit +X of the joint cut frame: perpendicular to path tangent (registration radial axis)."""
    z = _unit(np.asarray(tangent, dtype=float))
    up = np.asarray(ref_up, dtype=float)
    x = up - np.dot(up, z) * z
    if float(np.linalg.norm(x)) < 1e-9:
        fallback = np.array([1.0, 0.0, 0.0], dtype=float)
        x = fallback - np.dot(fallback, z) * z
    return _unit(x)


def _joint_frame_at_point(
    wire,
    point_xyz: Sequence[float],
    *,
    num_samples: int,
) -> Tuple[Tuple[float, float, float], np.ndarray, np.ndarray]:
    """Parallel-transported (origin, tangent, x_dir) on ``wire`` nearest to ``point_xyz``."""
    from .path_frames import sample_path_frames

    if num_samples < 2:
        raise ValueError("num_samples must be >= 2 for joint framing")
    frames = sample_path_frames(wire, num_samples)
    tx, ty, tz = float(point_xyz[0]), float(point_xyz[1]), float(point_xyz[2])
    best = min(
        frames,
        key=lambda f: (f.point.x - tx) ** 2 + (f.point.y - ty) ** 2 + (f.point.z - tz) ** 2,
    )
    origin = (float(best.point.x), float(best.point.y), float(best.point.z))
    tangent = _unit(np.array([best.tangent.x, best.tangent.y, best.tangent.z], dtype=float))
    x_dir = _unit(np.array([best.x_dir.x, best.x_dir.y, best.x_dir.z], dtype=float))
    return origin, tangent, x_dir


def _frame_location(
    origin_xyz: Tuple[float, float, float],
    z_dir: np.ndarray,
    x_dir: np.ndarray,
) -> cq.Location:
    z = _unit(z_dir)
    x = _unit(x_dir)
    x = x - np.dot(x, z) * z
    n = float(np.linalg.norm(x))
    if n < 1e-9:
        x = joint_radial_direction(z)
    else:
        x = x / n
    plane = cq.Plane(
        origin=cq.Vector(float(origin_xyz[0]), float(origin_xyz[1]), float(origin_xyz[2])),
        xDir=cq.Vector(float(x[0]), float(x[1]), float(x[2])),
        normal=cq.Vector(float(z[0]), float(z[1]), float(z[2])),
    )
    return cq.Location(plane)


def lap_overlap_mm(joint_cfg) -> float:
    """Axial lap length at internal cuts; defaults to pin depth when unset/zero."""
    lap = float(getattr(joint_cfg, "lap_overlap_mm", 0.0))
    if lap > 0:
        return lap
    if bool(getattr(joint_cfg, "enabled", False)):
        return float(joint_cfg.pin_depth_mm)
    return 0.0


def extend_segment_points_for_lap(
    seg_pts: Sequence[Tuple[float, float, float]],
    *,
    sampled_points: Sequence[Tuple[float, float, float]],
    start_idx: int,
    end_idx: int,
    part_idx: int,
    part_count: int,
    lap_mm: float,
) -> List[Tuple[float, float, float]]:
    """
    Extend the segment polyline past internal cuts so adjacent prints overlap axially.

    Each neighbor extends ``lap_mm`` into the shared boundary so glued joints are not
    flush butt faces.
    """
    if lap_mm <= 0 or part_count < 2:
        return list(seg_pts)
    pts: List[Tuple[float, float, float]] = list(seg_pts)
    if part_idx > 0:
        p0 = np.array(sampled_points[start_idx], dtype=float)
        p1 = np.array(sampled_points[min(start_idx + 1, len(sampled_points) - 1)], dtype=float)
        tan = _unit(p1 - p0)
        pts.insert(0, tuple(p0 - tan * lap_mm))
    if part_idx < part_count - 1:
        p_end = np.array(sampled_points[end_idx], dtype=float)
        p_prev = np.array(sampled_points[max(end_idx - 1, 0)], dtype=float)
        tan = _unit(p_end - p_prev)
        pts.append(tuple(p_end + tan * lap_mm))
    return pts


def _pin_radial_offset_mm(joint_cfg, outer_radius: float) -> float:
    """Keep pins on the tube wall instead of floating outside the OD."""
    r_pin = 0.5 * float(joint_cfg.pin_diameter_mm)
    target = float(joint_cfg.pin_radial_offset_mm)
    embed = float(outer_radius) - r_pin - 0.25
    if target > embed:
        return max(r_pin + 0.5, embed)
    return target


def _make_lap_rabbet_feature(joint_cfg, outer_radius: float, *, male: bool):
    """Stepped rabbet on the outer wall at a segment cut (local +Z = along path tangent)."""
    lap_depth = lap_overlap_mm(joint_cfg)
    if lap_depth <= 0:
        return None
    clear = float(joint_cfg.clearance_mm)
    step_h = min(float(joint_cfg.lap_step_height_mm), max(0.5, float(outer_radius) * 0.45))
    inner_r = max(0.5, float(outer_radius) - step_h)
    if male:
        outer_r = float(outer_radius)
        z0, z1 = 0.0, lap_depth
    else:
        outer_r = float(outer_radius) + clear
        inner_r = max(0.3, inner_r - clear)
        z0, z1 = -clear, lap_depth + clear
    return (
        cq.Workplane("XY")
        .circle(outer_r)
        .circle(inner_r)
        .extrude(z1 - z0)
        .translate((0.0, 0.0, z0))
        .val()
    )


def apply_lap_joint_features(
    part_obj,
    *,
    wire_seg,
    frame_samples: int,
    part_idx: int,
    part_count: int,
    start_point: Sequence[float],
    end_point: Sequence[float],
    config,
):
    """Add outer-wall rabbets at internal segment boundaries (complements axial overlap)."""
    mp = config.max_print_bounds
    if not mp.enabled or not mp.joint.enabled:
        return part_obj
    lap_depth = lap_overlap_mm(mp.joint)
    if lap_depth <= 0:
        return part_obj

    shape = _shape_from_any(part_obj)
    outer_r = float(config.tube_settings.outer_radius)

    if part_idx > 0:
        origin, tan, x_dir = _joint_frame_at_point(
            wire_seg, start_point, num_samples=frame_samples
        )
        loc_start = _frame_location(origin, tan, x_dir)
        female = _make_lap_rabbet_feature(mp.joint, outer_r, male=False)
        if female is not None:
            shape = shape.cut(female.moved(loc_start))

    if part_idx < part_count - 1:
        origin, tan, x_dir = _joint_frame_at_point(
            wire_seg, end_point, num_samples=frame_samples
        )
        loc_end = _frame_location(origin, tan, x_dir)
        male = _make_lap_rabbet_feature(mp.joint, outer_r, male=True)
        if male is not None:
            shape = shape.fuse(male.moved(loc_end))

    return shape


def _make_twin_pin_features(joint_cfg, male: bool, *, outer_radius: float):
    r = max(0.05, 0.5 * float(joint_cfg.pin_diameter_mm))
    clearance = float(joint_cfg.clearance_mm)
    rr = r if male else (r + 0.5 * clearance)
    depth = float(joint_cfg.pin_depth_mm) if male else (float(joint_cfg.pin_depth_mm) + clearance)
    base_x = _pin_radial_offset_mm(joint_cfg, outer_radius)
    spacing = float(joint_cfg.pin_spacing_mm)

    # Asymmetric twin-pin layout prevents 180-degree flip mistakes.
    centers = [
        (base_x, 0.5 * spacing),
        (base_x, -0.20 * spacing),
    ]
    wp = cq.Workplane("XY")
    for cx, cy in centers:
        wp = wp.center(cx, cy).circle(rr).center(-cx, -cy)
    return wp.extrude(depth).val()


def _make_dovetail_feature(joint_cfg, male: bool, *, outer_radius: float):
    clear = float(joint_cfg.clearance_mm)
    neck = float(joint_cfg.neck_width_mm)
    base = float(joint_cfg.base_width_mm)
    depth = float(joint_cfg.depth_mm)
    radial = _pin_radial_offset_mm(joint_cfg, outer_radius)

    if male:
        neck_eff = neck
        base_eff = base
        depth_eff = depth
    else:
        neck_eff = neck + clear
        base_eff = base + clear
        depth_eff = depth + clear

    hw_neck = 0.5 * neck_eff
    hw_base = 0.5 * base_eff
    poly = [
        (radial - hw_base, 0.0),
        (radial + hw_base, 0.0),
        (radial + hw_neck, depth_eff),
        (radial - hw_neck, depth_eff),
    ]
    return cq.Workplane("XY").polyline(poly).close().extrude(depth_eff).val()


def apply_registration_features(
    part_obj,
    *,
    wire_seg,
    frame_samples: int,
    part_idx: int,
    part_count: int,
    start_point: Sequence[float],
    end_point: Sequence[float],
    config,
):
    """
    Add/cut registration features on segment boundaries.

    Convention:
    - Internal start boundary gets female socket.
    - Internal end boundary gets male key/pin.
    """
    mp = config.max_print_bounds
    if not mp.enabled or not mp.joint.enabled:
        return part_obj

    shape = _shape_from_any(part_obj)
    jc = mp.joint
    outer_r = float(config.tube_settings.outer_radius)

    # Start boundary (female) for all but first piece.
    if part_idx > 0:
        origin, tan, x_dir = _joint_frame_at_point(
            wire_seg, start_point, num_samples=frame_samples
        )
        loc_start = _frame_location(origin, tan, x_dir)
        female = (
            _make_twin_pin_features(jc, male=False, outer_radius=outer_r)
            if jc.style == "twin_pin"
            else _make_dovetail_feature(jc, male=False, outer_radius=outer_r)
        ).moved(loc_start)
        shape = shape.cut(female)

    # End boundary (male) for all but last piece.
    if part_idx < part_count - 1:
        origin, tan, x_dir = _joint_frame_at_point(
            wire_seg, end_point, num_samples=frame_samples
        )
        loc_end = _frame_location(origin, tan, x_dir)
        male = (
            _make_twin_pin_features(jc, male=True, outer_radius=outer_r)
            if jc.style == "twin_pin"
            else _make_dovetail_feature(jc, male=True, outer_radius=outer_r)
        ).moved(loc_end)
        shape = shape.fuse(male)

    return shape

