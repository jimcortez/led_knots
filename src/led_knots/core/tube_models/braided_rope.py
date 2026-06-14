"""
Academic-grounded braided tube sleeve along an arbitrary centerline path.

Ported into the package from the POC at the repo root. Geometry is unchanged:
He et al. 2020 braiding-curve formulation (Eqs. 17, 18) with Kyosev's
lenticular cross-section and the float-length / contact-bound generalisations.

The POC's local copies of `get_samples` and `frame_at_arc_length` are replaced
by the shared `path_frames` helpers so this model uses the same parallel-
transported frames as every other tube model.
"""

from __future__ import annotations

import logging
import math
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import cadquery as cq
from cadquery import Location, Plane, Vector, Wire
from cadquery.func import circle, clean, face, fuse, intersect, sweep
from cadquery.occ_impl.shapes import Compound, Solid
from tqdm.auto import tqdm

from ..path_frames import PathFrame, frame_at_arc_length, sample_path_frames
from .swept_face import SweptFaceModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

@dataclass
class BraidParams:
    """
    Braid parameters following He et al. 2020 notation (paper symbols in
    parentheses). All lengths in mm, all angles in degrees.
    """

    num_strands_per_dir: int = 25
    outer_radius: float = 14.0
    float_length: int = 1
    helix_angle_deg: float = 30.0
    pack_factor: float = 0.7
    strand_aspect_ratio: float = 1.6
    tilt_to_helix_angle: bool = True
    weave_amplitude_factor: float = 1.05
    samples_per_period: int = 20
    strand_start: float = 2.0
    strand_end_offset: float = 2.0
    radial_offset: float = 0.0

    Rr: float = field(init=False)
    p: float = field(init=False)
    a: float = field(init=False)
    radial_extent: float = field(init=False)
    A_min: float = field(init=False)
    A: float = field(init=False)
    N: float = field(init=False)
    pitch: float = field(init=False)
    core_radius: float = field(init=False)
    tilt_angle_rad: float = field(init=False)

    def __post_init__(self) -> None:
        if self.float_length < 1:
            raise ValueError("float_length must be >= 1")
        if self.num_strands_per_dir % self.float_length != 0:
            raise ValueError(
                f"num_strands_per_dir ({self.num_strands_per_dir}) must be "
                f"divisible by float_length ({self.float_length}) so the "
                f"n*n weave pattern closes around the cylinder."
            )

        N = self.num_strands_per_dir
        aspect = self.strand_aspect_ratio
        k = self.pack_factor

        if self.tilt_to_helix_angle:
            self.tilt_angle_rad = math.radians(90.0 - self.helix_angle_deg)
        else:
            self.tilt_angle_rad = 0.0

        gamma = self.tilt_angle_rad
        eta = math.sqrt(
            (aspect * math.sin(gamma)) ** 2 + math.cos(gamma) ** 2
        )

        denom = 1.0 + (self.weave_amplitude_factor + 1.0) * eta * k * math.pi / (
            2.0 * N * aspect
        )
        self.Rr = self.outer_radius / denom
        self.a = k * math.pi * self.Rr / (2.0 * N)
        self.p = self.a / aspect
        self.radial_extent = eta * self.p
        self.A_min = self.radial_extent
        self.A = self.weave_amplitude_factor * self.A_min
        self.N = N / self.float_length
        self.pitch = 2.0 * math.pi * self.Rr / math.tan(
            math.radians(self.helix_angle_deg)
        )
        self.core_radius = self.Rr - self.A - 0.4 * self.radial_extent
        if self.core_radius <= 0:
            raise ValueError(
                "Derived core_radius <= 0; reduce weave_amplitude_factor, "
                "reduce strand_aspect_ratio, or increase num_strands_per_dir."
            )

    def summary(self) -> str:
        total_strands = 2 * self.num_strands_per_dir
        offset_part = (
            f", radial_offset={self.radial_offset:.3f}"
            if abs(self.radial_offset) > 1e-6
            else ""
        )
        return (
            f"Braid params: total strands = {total_strands} "
            f"(F={self.float_length}), Rr={self.Rr:.3f}, "
            f"outer_R={self.outer_radius:.3f}, a={self.a:.3f}, p={self.p:.3f}, "
            f"A={self.A:.3f}, pitch={self.pitch:.2f}, "
            f"core_radius={self.core_radius:.3f}{offset_part}"
        )


# ---------------------------------------------------------------------------
# Geometry helpers (PathFrame-based)
# ---------------------------------------------------------------------------

def _norm3(v):
    d = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    return (v[0] / d, v[1] / d, v[2] / d) if d > 1e-10 else v


def _frame_axes(frame: PathFrame):
    """Return unit tangent/x/y tuples from a `PathFrame`."""
    t = (frame.tangent.x, frame.tangent.y, frame.tangent.z)
    x = (frame.x_dir.x, frame.x_dir.y, frame.x_dir.z)
    y = (frame.y_dir.x, frame.y_dir.y, frame.y_dir.z)
    return _norm3(t), _norm3(x), _norm3(y)


def _braiding_curve_point(s: float, frame: PathFrame, params: BraidParams, phase: float, direction: int):
    """Point on a single braiding curve at arc length s along the path (He et al. Eq. 17/18)."""
    _, x_dir, y_dir = _frame_axes(frame)
    theta_s = direction * (s / params.pitch) * 2.0 * math.pi + phase
    omega_s = 2.0 * math.pi * params.N / params.pitch
    r_mod = (
        params.Rr
        + params.radial_offset
        + direction * params.A * math.sin(omega_s * s)
    )
    cos_t, sin_t = math.cos(theta_s), math.sin(theta_s)
    ox, oy, oz = frame.point.x, frame.point.y, frame.point.z
    return (
        ox + r_mod * (cos_t * x_dir[0] + sin_t * y_dir[0]),
        oy + r_mod * (cos_t * x_dir[1] + sin_t * y_dir[1]),
        oz + r_mod * (cos_t * x_dir[2] + sin_t * y_dir[2]),
    )


def _lenticular_wire(center, tangent, x_in_plane, params: BraidParams, direction: int) -> Wire:
    """Lenticular (elliptical) cross-section wire perpendicular to the strand tangent."""
    t = _norm3(tangent)
    n_radial = _norm3(x_in_plane)

    cx = t[1] * n_radial[2] - t[2] * n_radial[1]
    cy = t[2] * n_radial[0] - t[0] * n_radial[2]
    cz = t[0] * n_radial[1] - t[1] * n_radial[0]
    cross_in_plane = _norm3((cx, cy, cz))

    gamma = direction * params.tilt_angle_rad
    cos_g, sin_g = math.cos(gamma), math.sin(gamma)
    e_x = (
        cos_g * n_radial[0] + sin_g * cross_in_plane[0],
        cos_g * n_radial[1] + sin_g * cross_in_plane[1],
        cos_g * n_radial[2] + sin_g * cross_in_plane[2],
    )

    pl = Plane(origin=Vector(*center), xDir=Vector(*e_x), normal=Vector(*t))
    return Wire.makeEllipse(params.p, params.a, pl.origin, pl.zDir, pl.xDir)


# Max sections per loft call; longer sequences destabilize OCC ThruSections.
_LOFT_CHUNK_SECTIONS = 32


def _build_braid_strand(
    path_frames_seq: List[PathFrame],
    path_length: float,
    params: BraidParams,
    phase: float,
    direction: int,
    loft_samples: int,
):
    """Lofted lenticular strand along the path following the braiding curve."""
    s_start = params.strand_start
    s_end = path_length - params.strand_end_offset
    strand_length = s_end - s_start
    if strand_length <= 0:
        raise ValueError("path too short for strand loft")

    pts = []
    for i in range(loft_samples):
        t = i / (loft_samples - 1)
        s = s_start + t * strand_length
        f = frame_at_arc_length(path_frames_seq, s)
        pts.append(_braiding_curve_point(s, f, params, phase, direction))

    tangents = []
    for i in range(loft_samples):
        if i == 0:
            d = (pts[1][0] - pts[0][0], pts[1][1] - pts[0][1], pts[1][2] - pts[0][2])
        elif i == loft_samples - 1:
            d = (pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1], pts[i][2] - pts[i - 1][2])
        else:
            d = (
                pts[i + 1][0] - pts[i - 1][0],
                pts[i + 1][1] - pts[i - 1][1],
                pts[i + 1][2] - pts[i - 1][2],
            )
        tangents.append(_norm3(d))

    outwards = []
    for i in range(loft_samples):
        s = s_start + i / (loft_samples - 1) * strand_length
        f = frame_at_arc_length(path_frames_seq, s)
        center = (f.point.x, f.point.y, f.point.z)
        outwards.append(_norm3((
            pts[i][0] - center[0],
            pts[i][1] - center[1],
            pts[i][2] - center[2],
        )))

    t0 = tangents[0]
    n0 = outwards[0]
    dot0 = t0[0] * n0[0] + t0[1] * n0[1] + t0[2] * n0[2]
    x_raw = (n0[0] - dot0 * t0[0], n0[1] - dot0 * t0[1], n0[2] - dot0 * t0[2])
    x_dirs = [_norm3(x_raw)]
    for i in range(1, loft_samples):
        tang = tangents[i]
        prev_x = x_dirs[-1]
        d = prev_x[0] * tang[0] + prev_x[1] * tang[1] + prev_x[2] * tang[2]
        proj = (prev_x[0] - d * tang[0], prev_x[1] - d * tang[1], prev_x[2] - d * tang[2])
        x_dirs.append(_norm3(proj))

    wires = [
        _lenticular_wire(pts[i], tangents[i], x_dirs[i], params, direction)
        for i in range(loft_samples)
    ]

    # OCC ThruSections degrades on long high-twist section sequences: a single
    # loft over all sections collapsed CCW strands to ~73% of their analytic
    # volume (and to garbage at other sample counts), while bounded chunks are
    # exact for both directions. Loft chunks over shared boundary wires and
    # fuse them into one strand solid.
    chunk_solids = []
    i = 0
    while i < loft_samples - 1:
        j = min(i + _LOFT_CHUNK_SECTIONS, loft_samples - 1)
        chunk_solids.append(Solid.makeLoft(wires[i : j + 1], ruled=False))
        i = j
    merged = chunk_solids[0]
    for chunk in chunk_solids[1:]:
        merged = fuse(merged, chunk)
    merged = clean(merged)
    merged_solids = merged.Solids()
    if len(merged_solids) != 1:
        raise RuntimeError(
            f"braid strand chunks fused into {len(merged_solids)} solids, expected 1 "
            f"(direction={direction}, phase={phase:.3f})"
        )
    solid = merged_solids[0]

    # Guard against folded/collapsed lofts: the solid volume must be close to
    # ellipse area x centerline length. A bare positive-volume check passes
    # lofts that lost a quarter of their material to fold-over.
    centerline_length = sum(
        math.dist(pts[i], pts[i - 1]) for i in range(1, loft_samples)
    )
    expected_volume = math.pi * params.p * params.a * centerline_length
    volume = solid.Volume()
    if not (0.85 * expected_volume <= volume <= 1.15 * expected_volume):
        raise RuntimeError(
            f"braid strand loft volume {volume:.1f} mm^3 deviates from expected "
            f"{expected_volume:.1f} mm^3 (direction={direction}, phase={phase:.3f})"
        )
    return solid


def _build_core_tube(frames: List[PathFrame], params: BraidParams) -> Solid:
    """Smooth core loft along the path."""
    wires = []
    for f in frames:
        pl = Plane(origin=f.point, xDir=f.x_dir, normal=f.tangent)
        wires.append(Wire.makeCircle(params.core_radius, pl.origin, pl.zDir))
    return Solid.makeLoft(wires, ruled=True)


# ---------------------------------------------------------------------------
# Model entry point
# ---------------------------------------------------------------------------

_PARAM_KEYS = {
    "num_strands_per_dir",
    "outer_radius",
    "float_length",
    "helix_angle_deg",
    "pack_factor",
    "strand_aspect_ratio",
    "tilt_to_helix_angle",
    "weave_amplitude_factor",
    "samples_per_period",
    "strand_start",
    "strand_end_offset",
}

_SWEPT_BASE_FACE_TYPES = frozenset({
    "led_circle",
    "led_circle_tube",
    "solid_circle",
    "square",
})


def _base_face_type(config: Any) -> str:
    raw = getattr(config.tube_settings, "braided_rope", None) or {}
    return str(raw.get("base_face_type", "braid_core"))


def _strand_envelope_radius(params: BraidParams) -> float:
    """Outermost radial reach of the braided sleeve (centerline to strand peak)."""
    return params.Rr + params.radial_offset + params.A + params.radial_extent


def _strand_valley_radius(params: BraidParams) -> float:
    """Innermost radial reach of the braided sleeve (centerline to strand valley)."""
    return params.Rr + params.radial_offset - params.A - params.radial_extent


_DEFAULT_VALLEY_EMBED_DEPTH = 0.5
_DEFAULT_BRAID_TIGHTNESS = 0.0


def _validate_valley_embed_depth(
    depth: float,
    *,
    tube_r: float,
    wall_thickness: Optional[float],
) -> None:
    if depth < 0:
        raise ValueError(f"valley_embed_depth ({depth}) must be >= 0")
    if depth >= tube_r:
        raise ValueError(
            f"valley_embed_depth ({depth}) must be < outer_radius ({tube_r})"
        )
    if wall_thickness is not None and depth > wall_thickness:
        raise ValueError(
            f"valley_embed_depth ({depth}) must be <= wall_thickness "
            f"({wall_thickness})"
        )


def _scale_outer_radius_for_tube(
    kwargs: Dict[str, Any],
    *,
    tube_r: float,
) -> None:
    """
    Size the braid envelope to the tube OD before applying valley embed.

    Strands sized at ``outer_radius=tube_r`` but shifted outward only via
    ``radial_offset`` orbit far from their cross-section, which deforms the
    swept base during boolean fuse.  Bump ``outer_radius`` until the natural
    envelope clears the tube, then apply a small offset for valley depth.
    """
    outer = float(kwargs["outer_radius"])
    for _ in range(8):
        probe = BraidParams(**{**kwargs, "outer_radius": outer})
        if _strand_envelope_radius(probe) > tube_r + 1e-3:
            kwargs["outer_radius"] = outer
            return
        outer = tube_r + probe.p + probe.radial_extent
    kwargs["outer_radius"] = outer


def _tube_arc_spacing(tube_r: float, num_strands_per_dir: int) -> float:
    """Circumferential arc between same-direction strand centerlines at ``tube_r``."""
    return math.pi * tube_r / num_strands_per_dir


def _apply_braid_tightness(kwargs: Dict[str, Any], *, tightness: float) -> None:
    """
    Scale ``pack_factor`` toward a tighter sleeve without changing ``outer_radius``.

    A full contact solve that also retargets ``outer_radius`` pulled strands off
    the tube surface and left almost nothing after the tube-OD clip.
    """
    if tightness <= 0:
        return
    base_pack = float(kwargs.get("pack_factor", 0.7))
    kwargs["pack_factor"] = min(base_pack * (1.0 + 0.6 * tightness), 1.15)


def _params_from_config(config: Any, *, base_face_type: str = "braid_core") -> BraidParams:
    raw = getattr(config.tube_settings, "braided_rope", None) or {}
    kwargs: Dict[str, Any] = {
        k: v for k, v in raw.items() if k in _PARAM_KEYS and v is not None
    }
    tube_r = float(config.tube_settings.outer_radius)
    user_set_outer = raw.get("outer_radius") is not None
    if "outer_radius" not in kwargs:
        kwargs["outer_radius"] = tube_r

    if base_face_type != "braid_core":
        valley_embed_depth = float(
            raw.get("valley_embed_depth", _DEFAULT_VALLEY_EMBED_DEPTH)
        )
        wall_thickness = getattr(config.tube_settings, "wall_thickness", None)
        _validate_valley_embed_depth(
            valley_embed_depth,
            tube_r=tube_r,
            wall_thickness=float(wall_thickness) if wall_thickness is not None else None,
        )
        tightness = float(raw.get("braid_tightness", _DEFAULT_BRAID_TIGHTNESS))
        _apply_braid_tightness(kwargs, tightness=tightness)
        if not user_set_outer:
            _scale_outer_radius_for_tube(kwargs, tube_r=tube_r)
        params = BraidParams(**kwargs)
        target_valley = tube_r - valley_embed_depth
        offset = target_valley - _strand_valley_radius(params)
        return BraidParams(**{**kwargs, "radial_offset": offset})

    return BraidParams(**kwargs)


def _orient_profile_face(profile, path, *, rotation_z: float = 90.0):
    """Match the placement of the swept-base profiles: origin-centered, rotated, on the path."""
    oriented = profile if rotation_z == 0 else profile.moved(rz=rotation_z)
    face_plane = Plane(origin=path.startPoint(), normal=path.tangentAt(0))
    return oriented.moved(Location(face_plane))


def _swept_embed_clip_shell(
    path,
    aux,
    config: Any,
    *,
    max_radius: float,
    rotation_z: float = 90.0,
):
    """
    Path-aligned volume: (tube_r - valley_embed_depth) <= r <= max_radius.

    Clips below the embed depth, not the tube OD, so strand bodies that
    intentionally reach into the wall are not discarded.
    """
    raw = getattr(config.tube_settings, "braided_rope", None) or {}
    depth = float(raw.get("valley_embed_depth", _DEFAULT_VALLEY_EMBED_DEPTH))
    tube_r = float(config.tube_settings.outer_radius)
    inner_r = max(tube_r - depth, 0.0)
    profile = face(circle(max_radius)) - face(circle(inner_r))
    oriented = _orient_profile_face(profile, path, rotation_z=rotation_z)
    return sweep(oriented, path, aux=aux)


def _clip_strands_to_embed_shell(
    strands: List[Solid],
    path,
    aux,
    config: Any,
    params: BraidParams,
    *,
    rotation_z: float = 90.0,
) -> List[Solid]:
    """Drop strand material below the embed shell so the base tube OD stays round."""
    if not strands:
        return strands
    max_r = _strand_envelope_radius(params) + float(config.tube_settings.outer_radius)
    clip_solid = _swept_embed_clip_shell(
        path, aux, config, max_radius=max_r, rotation_z=rotation_z
    )
    clipped: List[Solid] = []
    bar = tqdm(
        total=len(strands),
        desc="Clipping strands to embed shell",
        unit="strand",
        disable=not sys.stderr.isatty(),
    )
    for strand in strands:
        try:
            result = intersect(strand, clip_solid)
        except Exception as exc:
            bar.close()
            raise RuntimeError("strand embed clip failed") from exc
        if result.Volume() <= 1e-3:
            bar.close()
            raise RuntimeError("strand has no volume above embed shell after clip")
        clipped.append(result)
        bar.update(1)
    bar.close()
    return clipped


class BraidedRopeModel:
    """Braided sleeve: smooth core + 2N interlacing helical strands as a Compound."""

    def build(
        self,
        *,
        path,
        aux,
        config: Any,
        face_kwargs: Optional[Dict[str, Any]] = None,
    ):
        base_face_type = _base_face_type(config)
        params = _params_from_config(config, base_face_type=base_face_type)
        path_length = path.Length()
        if base_face_type in ("braided_rope", "braided_rope_tube"):
            raise ValueError(
                f"braided_rope.base_face_type cannot be {base_face_type!r}"
            )

        # Centerline frames: denser when the path is curved or long.
        num_frames = max(120, min(400, int(path_length / 1.0)))
        frames = sample_path_frames(path, num_frames)

        loft_samples = max(
            240,
            min(
                1500,
                math.ceil(
                    params.samples_per_period * params.N * path_length / params.pitch
                ),
            ),
        )

        logger.info(
            "BraidedRopeModel: %s; base_face_type=%s; path_length=%.1f mm, loft_samples=%d",
            params.summary(),
            base_face_type,
            path_length,
            loft_samples,
        )

        if base_face_type == "braid_core":
            core = _build_core_tube(frames, params)
        elif base_face_type in _SWEPT_BASE_FACE_TYPES:
            core = SweptFaceModel(base_face_type).build(
                path=path, aux=aux, config=config, face_kwargs=face_kwargs
            )
        else:
            raise ValueError(
                f"braided_rope.base_face_type must be 'braid_core' or one of "
                f"{sorted(_SWEPT_BASE_FACE_TYPES)!r} (got {base_face_type!r})"
            )

        total_strands = 2 * params.num_strands_per_dir
        strands: List[Solid] = []
        bar = tqdm(
            total=total_strands,
            desc="Building braid strands",
            unit="strand",
            disable=not sys.stderr.isatty(),
        )
        for direction in (-1, 1):
            for i in range(params.num_strands_per_dir):
                phase = i * (2.0 * math.pi / params.num_strands_per_dir)
                if direction == 1:
                    phase += math.pi / params.num_strands_per_dir
                strands.append(
                    _build_braid_strand(
                        frames, path_length, params, phase, direction, loft_samples
                    )
                )
                bar.update(1)
        bar.close()

        if len(strands) != total_strands:
            raise RuntimeError(
                f"expected {total_strands} braid strands, built {len(strands)}"
            )

        logger.info(
            "BraidedRopeModel: built %d/%d strands",
            len(strands),
            total_strands,
        )

        if base_face_type in _SWEPT_BASE_FACE_TYPES and strands:
            rotation_z = float((face_kwargs or {}).get("rotation_z", 90.0))
            logger.info(
                "BraidedRopeModel: clipping %d strands to embed shell",
                len(strands),
            )
            strands = _clip_strands_to_embed_shell(
                strands, path, aux, config, params, rotation_z=rotation_z
            )
            return Compound.makeCompound([core, *strands])

        return Compound.makeCompound([core, *strands])
