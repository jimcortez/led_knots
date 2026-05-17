"""
Registration geometry helpers for segmented prints.
"""

from __future__ import annotations

from typing import Sequence, Tuple

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


def _frame_location(origin_xyz: Tuple[float, float, float], z_dir: np.ndarray, ref_up: np.ndarray) -> cq.Location:
    z = _unit(z_dir)
    x = ref_up - np.dot(ref_up, z) * z
    if float(np.linalg.norm(x)) < 1e-9:
        fallback = np.array([1.0, 0.0, 0.0], dtype=float)
        x = fallback - np.dot(fallback, z) * z
    x = _unit(x)
    plane = cq.Plane(
        origin=cq.Vector(float(origin_xyz[0]), float(origin_xyz[1]), float(origin_xyz[2])),
        xDir=cq.Vector(float(x[0]), float(x[1]), float(x[2])),
        normal=cq.Vector(float(z[0]), float(z[1]), float(z[2])),
    )
    return cq.Location(plane)


def _make_twin_pin_features(joint_cfg, male: bool):
    r = max(0.05, 0.5 * float(joint_cfg.pin_diameter_mm))
    clearance = float(joint_cfg.clearance_mm)
    rr = r if male else (r + 0.5 * clearance)
    depth = float(joint_cfg.pin_depth_mm) if male else (float(joint_cfg.pin_depth_mm) + clearance)
    base_x = float(joint_cfg.pin_radial_offset_mm)
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


def _make_dovetail_feature(joint_cfg, male: bool):
    clear = float(joint_cfg.clearance_mm)
    neck = float(joint_cfg.neck_width_mm)
    base = float(joint_cfg.base_width_mm)
    depth = float(joint_cfg.depth_mm)
    radial = float(joint_cfg.pin_radial_offset_mm)

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
    part_idx: int,
    part_count: int,
    start_point: Sequence[float],
    end_point: Sequence[float],
    start_tangent: Sequence[float],
    end_tangent: Sequence[float],
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
    ref_up = np.array([0.0, 0.0, 1.0], dtype=float)
    jc = mp.joint

    # Start boundary (female) for all but first piece.
    if part_idx > 0:
        loc_start = _frame_location(tuple(start_point), _unit(np.array(start_tangent, dtype=float)), ref_up)
        female = (
            _make_twin_pin_features(jc, male=False)
            if jc.style == "twin_pin"
            else _make_dovetail_feature(jc, male=False)
        ).moved(loc_start)
        shape = shape.cut(female)

    # End boundary (male) for all but last piece.
    if part_idx < part_count - 1:
        loc_end = _frame_location(tuple(end_point), _unit(np.array(end_tangent, dtype=float)), ref_up)
        male = (
            _make_twin_pin_features(jc, male=True)
            if jc.style == "twin_pin"
            else _make_dovetail_feature(jc, male=True)
        ).moved(loc_end)
        shape = shape.fuse(male)

    return shape

