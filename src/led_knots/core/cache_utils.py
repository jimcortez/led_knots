"""
Cache key utilities for preview STL paths.

Builds deterministic filename stems from part name, path geometry,
rotation/face kwargs, and config (output_bounds, tube_settings, path_settings).
"""

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, Optional

# Decimal places for path coordinates before hashing (avoids cache misses from float variants)
_PATH_HASH_DECIMALS = 5
# Dense sampling step for t in [0, 1] so we represent all points (e.g. 1001 points for step 0.001)
_PATH_HASH_T_STEP = 0.001
# Length of hash digest used in cache filename
_PATH_HASH_DIGEST_LEN = 16


def slugify(s: str) -> str:
    """Lowercase, replace non-alphanumeric with '-', strip leading/trailing '-'."""
    s = s.lower().strip()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-')


def _sample_path_points(path, t_step: float = _PATH_HASH_T_STEP) -> list:
    """Sample path at t in [0, 1] with given step. Round each coordinate to 5 decimal places."""
    points = []
    t = 0.0
    while t <= 1.0:
        pos = path.positionAt(min(t, 1.0))
        points.append(
            (
                round(float(pos.x), _PATH_HASH_DECIMALS),
                round(float(pos.y), _PATH_HASH_DECIMALS),
                round(float(pos.z), _PATH_HASH_DECIMALS),
            )
        )
        t += t_step
    return points


def path_hash(path, aux=None) -> str:
    """
    Hash the geometry of path (and aux if provided). Uses all points from dense sampling,
    with each coordinate rounded to 5 decimal places to avoid floating-point cache misses.
    """
    data = _sample_path_points(path)
    if aux is not None:
        data.extend(_sample_path_points(aux))
    # Deterministic serialization: tuple of tuples
    blob = tuple(tuple(p) for p in data)
    h = hashlib.sha256(str(blob).encode()).hexdigest()
    return h[:_PATH_HASH_DIGEST_LEN]


def rotation_params_string(face_kwargs: Dict[str, Any]) -> str:
    """Build a deterministic string from face_kwargs (excluding orient_to_path), then slugify."""
    excluded = {'orient_to_path'}
    parts = []
    for k in sorted(face_kwargs.keys()):
        if k in excluded:
            continue
        v = face_kwargs[k]
        parts.append(f"{k}={v}")
    return slugify(",".join(parts)) if parts else ""


def _round_for_hash(x: float) -> float:
    """Round float to same decimals as path hash for stable cache keys."""
    return round(x, _PATH_HASH_DECIMALS)


def config_settings_hash(config) -> str:
    """
    Hash output_bounds, tube_settings (active face), and path_settings so cache keys change
    when these settings change. Uses 5 decimal places for floats for stability.
    """
    ob = config.output_bounds
    out = {
        'output_bounds': {
            'width': _round_for_hash(ob.width),
            'length': _round_for_hash(ob.length),
            'height': _round_for_hash(ob.height),
        }
    }
    ts = config.tube_settings
    out['tube_settings'] = {
        'face_type': ts.face_type,
        'outer_radius': _round_for_hash(ts.outer_radius),
        'wall_thickness': _round_for_hash(ts.wall_thickness),
        'oval_wall_thickness': _round_for_hash(ts.oval_wall_thickness),
        'connector_width': _round_for_hash(ts.connector_width),
        'rect_inner_x': _round_for_hash(ts.rect_inner_x),
        'rect_inner_y': _round_for_hash(ts.rect_inner_y),
    }
    if ts.diffusion_ridges is not None:
        out['tube_settings']['diffusion_ridges'] = {
            k: _round_for_hash(v) for k, v in sorted(ts.diffusion_ridges.items())
        }
    else:
        out['tube_settings']['diffusion_ridges'] = None
    if ts.face_type == 'solid_circle_pyramid':
        out['tube_settings']['_pyramid_sampling_version'] = 1

    ps = config.path_settings
    out['path_settings'] = {
        'min_90_degree_twist_distance': _round_for_hash(ps.min_90_degree_twist_distance),
    }
    mp = config.max_print_bounds
    out["max_print_bounds"] = {
        "enabled": bool(mp.enabled),
        "width": _round_for_hash(mp.width),
        "length": _round_for_hash(mp.length),
        "height": _round_for_hash(mp.height),
        "clearance_mm": _round_for_hash(mp.clearance_mm),
        "max_segments": int(mp.max_segments),
        "layout": str(mp.layout),
        "layout_gap_mm": _round_for_hash(mp.layout_gap_mm),
        "path_samples": int(mp.path_samples),
        "joint": {
            "enabled": bool(mp.joint.enabled),
            "style": str(mp.joint.style),
            "clearance_mm": _round_for_hash(mp.joint.clearance_mm),
            "close_loop": bool(mp.joint.close_loop),
            "pin_diameter_mm": _round_for_hash(mp.joint.pin_diameter_mm),
            "pin_depth_mm": _round_for_hash(mp.joint.pin_depth_mm),
            "pin_radial_offset_mm": _round_for_hash(mp.joint.pin_radial_offset_mm),
            "pin_spacing_mm": _round_for_hash(mp.joint.pin_spacing_mm),
            "lap_overlap_mm": _round_for_hash(mp.joint.lap_overlap_mm),
            "lap_step_height_mm": _round_for_hash(mp.joint.lap_step_height_mm),
            "neck_width_mm": _round_for_hash(mp.joint.neck_width_mm),
            "base_width_mm": _round_for_hash(mp.joint.base_width_mm),
            "depth_mm": _round_for_hash(mp.joint.depth_mm),
            "flank_angle_deg": _round_for_hash(mp.joint.flank_angle_deg),
        },
    }
    blob = str(sorted(out.items()))
    return hashlib.sha256(blob.encode()).hexdigest()[:_PATH_HASH_DIGEST_LEN]


def cache_key_for_part(
    name: str,
    path,
    aux=None,
    face_kwargs: Optional[Dict[str, Any]] = None,
    config: Optional[Any] = None,
) -> str:
    """
    Build the cache filename stem: slug(name)-slug(rotation_params)-config_hash-path_hash.
    Includes output_bounds, tube_settings, and path_settings when config is provided.
    Used as the base for preview STL paths (e.g. preview_cache_dir / f"{stem}.stl").
    """
    name_slug = slugify(name or "knot")
    rot_slug = rotation_params_string(face_kwargs or {})
    config_hash = config_settings_hash(config) if config is not None else ""
    ph = path_hash(path, aux=aux)
    parts = [name_slug]
    if rot_slug:
        parts.append(rot_slug)
    if config_hash:
        parts.append(config_hash)
    parts.append(ph)
    return "-".join(p for p in parts if p)


def preview_stl_path_for_part(
    config: Any,
    path,
    aux=None,
    face_kwargs: Optional[Dict[str, Any]] = None,
) -> Optional[Path]:
    """
    Derive the preview STL file path for a part from config and path/aux/face_kwargs.

    Returns preview_cache_dir / f"{stem}.stl" using the same stem as cache_key_for_part.
    Used when --preview is set and the STL source is the preview cache (not --export .stl).
    """
    preview_cache_dir = config.preview_settings.preview_cache_dir
    stem = cache_key_for_part(
        config.name,
        path,
        aux=aux,
        face_kwargs=face_kwargs,
        config=config,
    )
    return Path(preview_cache_dir) / f"{stem}.stl"
