"""
Wire-driven segmentation for multi-part printing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple

import cadquery as cq
import numpy as np
from cadquery.func import spline

from .print_joint import apply_registration_features


@dataclass(frozen=True)
class SegmentPlan:
    start_idx: int
    end_idx: int
    euler_xyz_deg: Tuple[float, float, float]


def _euler_to_matrix(rx_deg: float, ry_deg: float, rz_deg: float) -> np.ndarray:
    rx = np.deg2rad(rx_deg)
    ry = np.deg2rad(ry_deg)
    rz = np.deg2rad(rz_deg)
    cx, sx = np.cos(rx), np.sin(rx)
    cy, sy = np.cos(ry), np.sin(ry)
    cz, sz = np.cos(rz), np.sin(rz)
    rx_m = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], dtype=float)
    ry_m = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=float)
    rz_m = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], dtype=float)
    return rz_m @ ry_m @ rx_m


def _rotation_candidates_24() -> List[Tuple[float, float, float]]:
    cands: List[Tuple[float, float, float]] = []
    seen = set()
    for rx in (0.0, 90.0, 180.0, 270.0):
        for ry in (0.0, 90.0, 180.0, 270.0):
            for rz in (0.0, 90.0, 180.0, 270.0):
                m = _euler_to_matrix(rx, ry, rz)
                key = tuple(np.round(m.reshape(-1), 6))
                if key in seen:
                    continue
                seen.add(key)
                cands.append((rx, ry, rz))
    return cands


def sample_wire_points(path, n_samples: int = 1001):
    n = max(8, int(n_samples))
    t_vals = np.linspace(0.0, 1.0, n)
    pts = []
    for t in t_vals:
        p = path.positionAt(float(t))
        pts.append((float(p.x), float(p.y), float(p.z)))
    return pts, [float(t) for t in t_vals]


def _joint_margin(config) -> float:
    mp = config.max_print_bounds
    if not mp.enabled or not mp.joint.enabled:
        return 0.0
    jc = mp.joint
    if jc.style == "twin_pin":
        return max(0.0, float(jc.pin_radial_offset_mm) + 0.5 * float(jc.pin_diameter_mm))
    return max(0.0, float(jc.pin_radial_offset_mm) + 0.5 * float(jc.base_width_mm))


def _best_rotation_for_segment(
    points: np.ndarray,
    printer_dims_sorted: Sequence[float],
    outer_radius: float,
    extra_margin: float,
    rotations: Sequence[Tuple[float, float, float]],
) -> Optional[Tuple[float, float, float]]:
    best = None
    best_score = None
    inflate = 2.0 * (float(outer_radius) + float(extra_margin))
    for euler in rotations:
        m = _euler_to_matrix(*euler)
        rot = points @ m.T
        ext = rot.max(axis=0) - rot.min(axis=0)
        ext = ext + inflate
        dims = sorted([float(ext[0]), float(ext[1]), float(ext[2])], reverse=True)
        if dims[0] <= printer_dims_sorted[0] and dims[1] <= printer_dims_sorted[1] and dims[2] <= printer_dims_sorted[2]:
            score = (dims[0], dims[1], dims[2], sum(dims))
            if best_score is None or score < best_score:
                best_score = score
                best = euler
    return best


def plan_segments(sampled_points: Sequence[Tuple[float, float, float]], config) -> List[SegmentPlan]:
    mp = config.max_print_bounds
    usable = [
        float(mp.width - 2.0 * mp.clearance_mm),
        float(mp.length - 2.0 * mp.clearance_mm),
        float(mp.height - 2.0 * mp.clearance_mm),
    ]
    printer_dims_sorted = sorted(usable, reverse=True)
    points = np.asarray(sampled_points, dtype=float)
    n = len(points)
    min_points = 4
    rotations = _rotation_candidates_24()
    extra_margin = _joint_margin(config)

    inf = 10**9
    dp = [inf] * n
    prev = [-1] * n
    rot_for = [None] * n
    dp[0] = 0

    for end_idx in range(min_points - 1, n):
        for start_idx in range(0, end_idx - min_points + 2):
            if start_idx > 0 and dp[start_idx] == inf:
                continue
            seg_pts = points[start_idx : end_idx + 1]
            euler = _best_rotation_for_segment(
                seg_pts,
                printer_dims_sorted,
                outer_radius=config.tube_settings.outer_radius,
                extra_margin=extra_margin,
                rotations=rotations,
            )
            if euler is None:
                continue
            cand = (dp[start_idx] + 1) if start_idx > 0 else 1
            if cand < dp[end_idx]:
                dp[end_idx] = cand
                prev[end_idx] = start_idx
                rot_for[end_idx] = euler

    if dp[-1] == inf:
        raise RuntimeError("Could not segment path to fit max_print_bounds. Increase bounds or reduce output size.")
    if dp[-1] > mp.max_segments:
        raise RuntimeError(
            f"Segmentation required {dp[-1]} segments but max_print_bounds.max_segments={mp.max_segments}."
        )

    plans: List[SegmentPlan] = []
    i = n - 1
    while i >= 0:
        s = prev[i]
        if s < 0 and i != 0:
            s = 0
        plans.append(SegmentPlan(start_idx=s, end_idx=i, euler_xyz_deg=rot_for[i]))
        if s == 0:
            break
        i = s
    plans.reverse()
    return plans


def _as_shape(obj):
    return obj.val() if hasattr(obj, "val") else obj


def _rotate_shape(shape, euler_xyz_deg: Tuple[float, float, float]):
    rx, ry, rz = euler_xyz_deg
    rotated = shape.rotate((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), float(rx))
    rotated = rotated.rotate((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), float(ry))
    rotated = rotated.rotate((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), float(rz))
    return rotated


def build_segmented_tube_assembly(
    path,
    config,
    build_segment_fn: Callable,
    *,
    aux=None,
    face_kwargs: Optional[dict] = None,
) -> cq.Assembly:
    face_kwargs = face_kwargs or {}
    sampled_points, t_vals = sample_wire_points(path, n_samples=config.max_print_bounds.path_samples)
    aux_sampled = None
    if aux is not None:
        aux_sampled = []
        for t in t_vals:
            p = aux.positionAt(float(t))
            aux_sampled.append((float(p.x), float(p.y), float(p.z)))

    plans = plan_segments(sampled_points, config)
    assy = cq.Assembly(name=f"{config.name or 'knot'} segmented")
    cursor_x = 0.0

    for idx, plan in enumerate(plans):
        seg_pts = sampled_points[plan.start_idx : plan.end_idx + 1]
        wire_seg = spline(seg_pts)
        aux_seg = None
        if aux_sampled is not None:
            aux_seg = spline(aux_sampled[plan.start_idx : plan.end_idx + 1])
        part_obj = build_segment_fn(wire_seg, config, aux=aux_seg, face_kwargs=face_kwargs)
        part_shape = _as_shape(part_obj)

        # Tangents from neighboring points in the sampled polyline.
        s = plan.start_idx
        e = plan.end_idx
        start_tan = np.array(sampled_points[min(s + 1, len(sampled_points) - 1)], dtype=float) - np.array(
            sampled_points[s], dtype=float
        )
        end_tan = np.array(sampled_points[e], dtype=float) - np.array(sampled_points[max(e - 1, 0)], dtype=float)
        part_shape = apply_registration_features(
            part_shape,
            part_idx=idx,
            part_count=len(plans),
            start_point=sampled_points[s],
            end_point=sampled_points[e],
            start_tangent=start_tan,
            end_tangent=end_tan,
            config=config,
        )

        rot_shape = _rotate_shape(part_shape, plan.euler_xyz_deg)
        bb = rot_shape.BoundingBox()
        x_off = cursor_x - bb.xmin
        y_off = -bb.ymin
        z_off = -bb.zmin
        placed = rot_shape.translate((x_off, y_off, z_off))
        assy = assy.add(placed, name=f"segment_{idx:02d}")
        cursor_x = x_off + bb.xlen + float(config.max_print_bounds.layout_gap_mm)

    return assy

