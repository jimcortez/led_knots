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
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, NamedTuple, Optional, Tuple

import cadquery as cq
from cadquery import Location, Plane, Vector, Wire
from cadquery.func import circle, clean, face, intersect, loft, solid, sweep
from cadquery.occ_impl.shapes import Solid
from tqdm.auto import tqdm

from ..fuse_utils import _assert_single_solid, _fuse_solids_map_reduce, _release
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


class _StrandSample(NamedTuple):
    """Precomputed centerline data at one arc-length sample, shared by all strands.

    ``center``/``x_dir``/``y_dir`` are the parallel-transported frame origin and
    unit basis (already normalized) at arc length ``s``. They depend only on the
    path shape, so every strand reuses the same samples; only the phase/direction
    weave term in ``_braiding_curve_point`` differs per strand.
    """

    s: float
    center: Tuple[float, float, float]
    x_dir: Tuple[float, float, float]
    y_dir: Tuple[float, float, float]


def _braiding_curve_point(sample: _StrandSample, params: BraidParams, phase: float, direction: int):
    """Point on a single braiding curve at the sample's arc length (He et al. Eq. 17/18)."""
    s = sample.s
    x_dir = sample.x_dir
    y_dir = sample.y_dir
    theta_s = direction * (s / params.pitch) * 2.0 * math.pi + phase
    omega_s = 2.0 * math.pi * params.N / params.pitch
    r_mod = (
        params.Rr
        + params.radial_offset
        + direction * params.A * math.sin(omega_s * s)
    )
    cos_t, sin_t = math.cos(theta_s), math.sin(theta_s)
    ox, oy, oz = sample.center
    return (
        ox + r_mod * (cos_t * x_dir[0] + sin_t * y_dir[0]),
        oy + r_mod * (cos_t * x_dir[1] + sin_t * y_dir[1]),
        oz + r_mod * (cos_t * x_dir[2] + sin_t * y_dir[2]),
    )


def _sample_strand_centerline(
    frames: List[PathFrame],
    path_length: float,
    params: BraidParams,
    loft_samples: int,
) -> List[_StrandSample]:
    """Sample the centerline frames once on the shared arc-length grid.

    The grid (``s_start`` .. ``s_end`` over ``loft_samples`` steps) and the frame
    at each ``s`` are identical for every strand, so this work is hoisted out of
    the per-strand loop. Valid for any path shape (rod, helix, trefoil); curvature
    is already encoded in ``frames``.
    """
    if loft_samples < 2:
        raise ValueError("need at least 2 centerline samples for strand loft")
    s_start = params.strand_start
    s_end = path_length - params.strand_end_offset
    strand_length = s_end - s_start
    if strand_length <= 0:
        raise ValueError("path too short for strand loft")

    samples: List[_StrandSample] = []
    for i in range(loft_samples):
        s = s_start + (i / (loft_samples - 1)) * strand_length
        f = frame_at_arc_length(frames, s)
        _, x_dir, y_dir = _frame_axes(f)
        samples.append(
            _StrandSample(
                s=s,
                center=(f.point.x, f.point.y, f.point.z),
                x_dir=x_dir,
                y_dir=y_dir,
            )
        )
    return samples


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


# Max sections per uncapped loft chunk. A single ThruSections over the full
# wire sequence collapsed CCW strands on straight paths; chunking fixes that.
# On high-twist curved paths, large chunks can still collapse when the chunk
# shells are sewn -- fall back to smaller chunk sizes (see _LOFT_CHUNK_FALLBACKS).
_LOFT_CHUNK_SECTIONS = 32
_LOFT_CHUNK_FALLBACKS = (16, 8, 4, 2)


def _sew_strand_solid_from_wires(wires: List[Wire], chunk_sections: int):
    """Loft uncapped chunk shells plus end caps into one strand solid."""
    n = len(wires)
    chunk_faces: List[Any] = []
    i = 0
    while i < n - 1:
        j = min(i + chunk_sections, n - 1)
        chunk_faces.extend(loft(wires[i : j + 1], cap=False, ruled=False).Faces())
        i = j
    merged = solid([*chunk_faces, face(wires[0]), face(wires[-1])])
    return clean(merged)




@dataclass
class _StrandTimings:
    """Cumulative per-stage wall-clock time across all strand builds.

    Used only for diagnostics: it locates the real OCC bottleneck (loft vs fuse
    vs clean) so optimization effort is spent where it matters.
    """

    wires: float = 0.0
    loft: float = 0.0
    sew: float = 0.0
    clean: float = 0.0
    volume: float = 0.0
    n_strands: int = 0

    def summary(self) -> str:
        total = self.wires + self.loft + self.sew + self.clean + self.volume
        return (
            f"strand build timing over {self.n_strands} strand(s): "
            f"wires={self.wires:.1f}s loft={self.loft:.1f}s sew={self.sew:.1f}s "
            f"clean={self.clean:.1f}s volume={self.volume:.1f}s "
            f"(timed total={total:.1f}s)"
        )


def _build_braid_strand(
    samples: List[_StrandSample],
    params: BraidParams,
    phase: float,
    direction: int,
    timings: Optional[_StrandTimings] = None,
):
    """Lofted lenticular strand along the path following the braiding curve.

    ``samples`` are the shared centerline samples from ``_sample_strand_centerline``;
    only the phase/direction weave term differs per strand.
    """
    loft_samples = len(samples)
    if loft_samples < 2:
        raise ValueError("need at least 2 centerline samples for strand loft")

    pts = [
        _braiding_curve_point(samples[i], params, phase, direction)
        for i in range(loft_samples)
    ]

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
        center = samples[i].center
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

    t_mark = time.perf_counter()
    wires = [
        _lenticular_wire(pts[i], tangents[i], x_dirs[i], params, direction)
        for i in range(loft_samples)
    ]
    if timings is not None:
        timings.wires += time.perf_counter() - t_mark

    centerline_length = sum(
        math.dist(pts[i], pts[i - 1]) for i in range(1, loft_samples)
    )
    expected_volume = math.pi * params.p * params.a * centerline_length

    # Build the strand solid without boolean fusion. ThruSections stays chunked
    # because long high-twist sequences destabilize it (a single loft over all
    # sections collapsed CCW strands to ~73% of their analytic volume). Each
    # chunk is lofted as an *uncapped* shell; adjacent chunks share an identical
    # boundary wire, so their lateral faces -- plus one planar cap at each end --
    # sew into a single closed shell that ShapeFix turns into a solid.
    #
    # On high-twist curved paths, large chunk sizes can still collapse when sewn.
    # Try progressively smaller chunks until the analytic volume guard passes;
    # if every size fails, raise with the full attempt log (no silent fallback).
    chunk_sizes = (_LOFT_CHUNK_SECTIONS, *_LOFT_CHUNK_FALLBACKS)
    attempts: List[str] = []
    solid_out = None
    for chunk_sections in chunk_sizes:
        t_mark = time.perf_counter()
        merged = _sew_strand_solid_from_wires(wires, chunk_sections)
        if timings is not None:
            timings.sew += time.perf_counter() - t_mark

        merged_solids = merged.Solids()
        if len(merged_solids) != 1:
            attempts.append(
                f"chunk={chunk_sections}: sewed into {len(merged_solids)} solids"
            )
            continue

        t_mark = time.perf_counter()
        volume = merged_solids[0].Volume()
        if timings is not None:
            timings.volume += time.perf_counter() - t_mark

        if 0.85 * expected_volume <= volume <= 1.15 * expected_volume:
            solid_out = merged_solids[0]
            break
        attempts.append(
            f"chunk={chunk_sections}: volume {volume:.1f} mm^3 "
            f"(expected {expected_volume:.1f} mm^3)"
        )

    if timings is not None and solid_out is not None:
        timings.n_strands += 1

    if solid_out is None:
        raise RuntimeError(
            f"braid strand loft failed volume guard at all chunk sizes "
            f"(direction={direction}, phase={phase:.3f}): "
            + "; ".join(attempts)
        )
    return solid_out


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
) -> Tuple[Solid, Solid]:
    """
    Path-aligned outer and inner clip solids: (tube_r - valley_embed_depth) <= r <= max_radius.

    Returns separate lofts so per-strand clip is ``intersect(outer).cut(inner)``. A
    single pre-cut annulus solid can make OCCT return empty on curved paths.
    """
    raw = getattr(config.tube_settings, "braided_rope", None) or {}
    depth = float(raw.get("valley_embed_depth", _DEFAULT_VALLEY_EMBED_DEPTH))
    tube_r = float(config.tube_settings.outer_radius)
    inner_r = max(tube_r - depth, 0.0)
    outer_profile = face(circle(max_radius))
    inner_profile = face(circle(inner_r))
    outer_oriented = _orient_profile_face(outer_profile, path, rotation_z=rotation_z)
    inner_oriented = _orient_profile_face(inner_profile, path, rotation_z=rotation_z)
    return sweep(outer_oriented, path, aux=aux), sweep(inner_oriented, path, aux=aux)


_EMBED_CLIP_OUTER_MARGIN = 0.05  # mm above tube OD for tessellation/boolean tolerance

_EmbedClipShell = Tuple[Solid, Solid]


def _embed_clip_inner_radius(config: Any) -> float:
    raw = getattr(config.tube_settings, "braided_rope", None) or {}
    depth = float(raw.get("valley_embed_depth", _DEFAULT_VALLEY_EMBED_DEPTH))
    tube_r = float(config.tube_settings.outer_radius)
    return max(tube_r - depth, 0.0)


def _build_frame_aligned_embed_clip_shell(
    frames: List[PathFrame],
    config: Any,
    *,
    outer_r: float,
) -> _EmbedClipShell:
    """Loft outer and inner clip shells on parallel-transported path frames.

    Swept-circle embed shells use the path start tangent only; on curved knots
    (quarter_turn) that frame diverges from the braid's PT frames and strands
    poke through the outer clip on the convex side. Lofting on the same
    ``frames`` grid as the strands keeps the OD clip aligned with the weave.
    """
    inner_r = _embed_clip_inner_radius(config)
    outer_wires: List[Wire] = []
    inner_wires: List[Wire] = []
    for f in frames:
        pl = Plane(origin=f.point, xDir=f.x_dir, normal=f.tangent)
        outer_wires.append(Wire.makeCircle(outer_r, pl.origin, pl.zDir))
        inner_wires.append(Wire.makeCircle(inner_r, pl.origin, pl.zDir))
    return Solid.makeLoft(outer_wires, ruled=True), Solid.makeLoft(inner_wires, ruled=True)


def _embed_clip_outer_radius(config: Any, params: BraidParams) -> float:
    """Outer clip at the modeled strand peak (not envelope + tube_r)."""
    return _strand_envelope_radius(params) + _EMBED_CLIP_OUTER_MARGIN


def _max_centerline_radial_extent(
    samples: List["_StrandSample"],
    params: BraidParams,
    phase: float,
    direction: int,
) -> float:
    """Peak path-axis distance of a strand cross-section from centerline samples."""
    max_r = 0.0
    for sample in samples:
        px, py, pz = _braiding_curve_point(sample, params, phase, direction)
        cx, cy, cz = sample.center
        dx, dy, dz = px - cx, py - cy, pz - cz
        u = (
            dx * sample.x_dir[0]
            + dy * sample.x_dir[1]
            + dz * sample.x_dir[2]
        )
        v = (
            dx * sample.y_dir[0]
            + dy * sample.y_dir[1]
            + dz * sample.y_dir[2]
        )
        max_r = max(max_r, math.hypot(u, v) + max(params.p, params.a))
    return max_r


def _probe_clip_outer_radius(
    strand_samples: List["_StrandSample"],
    params: BraidParams,
    config: Any,
) -> float:
    """Path-aware outer embed radius so every strand phase intersects the shell.

    On curved knots lofted strand solids extend past the centerline envelope;
    probe every phase on the shared sample grid and add weave + cross-section
    slack so the outer loft fully contains the solids before the inner cut.
    """
    outer_r = _embed_clip_outer_radius(config, params)
    for direction in (-1, 1):
        for i in range(params.num_strands_per_dir):
            phase = i * (2.0 * math.pi / params.num_strands_per_dir)
            if direction == 1:
                phase += math.pi / params.num_strands_per_dir
            outer_r = max(
                outer_r,
                _max_centerline_radial_extent(
                    strand_samples, params, phase, direction
                ),
            )
    return (
        outer_r
        + 2.0 * params.A
        + params.p
        + max(params.p, params.a)
        + _EMBED_CLIP_OUTER_MARGIN
    )


def _path_has_curvature(
    frames: List[PathFrame],
    path_length: float,
    *,
    min_bend_deg: float = 5.0,
) -> bool:
    """True when the path bends enough that frame-loft inner cuts are unsafe.

    Dense frame sampling keeps consecutive tangents nearly parallel even on a
  90° bend; use endpoint tangents and arc/chord stretch instead.
    """
    if len(frames) < 2:
        return False
    cos_limit = math.cos(math.radians(min_bend_deg))
    if frames[0].tangent.dot(frames[-1].tangent) < cos_limit:
        return True
    chord = frames[0].point.sub(frames[-1].point).Length
    return chord > 1e-3 and path_length / chord > 1.02


def _od_trim_cap_radius(params: BraidParams) -> float:
    """Trim convex-side loft bulge without cutting nominal strand bodies."""
    return (
        _strand_envelope_radius(params)
        + 3.0 * params.A
        + params.p
        + _EMBED_CLIP_OUTER_MARGIN
    )


def _build_frame_aligned_od_trim_cap(
    frames: List[PathFrame],
    params: BraidParams,
) -> Solid:
    """Solid cylinder at the modeled envelope plus bend slack (frame-aligned loft)."""
    cap_r = _od_trim_cap_radius(params)
    wires: List[Wire] = []
    for f in frames:
        pl = Plane(origin=f.point, xDir=f.x_dir, normal=f.tangent)
        wires.append(Wire.makeCircle(cap_r, pl.origin, pl.zDir))
    return Solid.makeLoft(wires, ruled=True)


def _build_embed_clip_solid(
    path,
    aux,
    config: Any,
    params: BraidParams,
    *,
    frames: Optional[List[PathFrame]] = None,
    strand_samples: Optional[List["_StrandSample"]] = None,
    rotation_z: float = 90.0,
) -> _EmbedClipShell:
    """Build the embed-clip (outer, inner) shells reused for every strand."""
    if strand_samples is not None:
        outer_r = _probe_clip_outer_radius(strand_samples, params, config)
    else:
        outer_r = _embed_clip_outer_radius(config, params)
    if frames is not None:
        return _build_frame_aligned_embed_clip_shell(frames, config, outer_r=outer_r)
    return _swept_embed_clip_shell(
        path, aux, config, max_radius=outer_r, rotation_z=rotation_z
    )


def _clip_one_strand(
    strand: Solid,
    clip_shell: _EmbedClipShell,
    *,
    od_trim=None,
    apply_inner_cut: bool = True,
) -> Solid:
    """Clip one strand to the embed annulus, failing loudly on empty results."""
    outer, inner = clip_shell
    try:
        result = intersect(strand, outer)
        if od_trim is not None:
            result = intersect(result, od_trim)
        if apply_inner_cut:
            result = result.cut(inner)
    except Exception as exc:
        raise RuntimeError("strand embed clip failed") from exc
    if result.Volume() <= 1e-3:
        raise RuntimeError("strand has no volume above embed shell after clip")
    if od_trim is not None and result.Volume() > strand.Volume() * 1.05:
        raise RuntimeError("strand OD trim produced invalid geometry")
    return result


def _clip_strands_to_embed_shell(
    strands: List[Solid],
    path,
    aux,
    config: Any,
    params: BraidParams,
    *,
    rotation_z: float = 90.0,
    od_trim=None,
) -> List[Solid]:
    """Drop strand material below the embed shell so the base tube OD stays round."""
    if not strands:
        return strands
    path_length = path.Length()
    num_frames = max(120, min(400, int(path_length / 1.0)))
    frames = sample_path_frames(path, num_frames)
    clip_solid = _build_embed_clip_solid(
        path, aux, config, params, frames=frames, rotation_z=rotation_z
    )
    clipped: List[Solid] = []
    bar = tqdm(
        total=len(strands),
        desc="Clipping strands to embed shell",
        unit="strand",
        disable=not sys.stderr.isatty(),
    )
    try:
        for strand in strands:
            clipped.append(_clip_one_strand(strand, clip_solid, od_trim=od_trim))
            bar.update(1)
    finally:
        bar.close()
    return clipped


# ---------------------------------------------------------------------------
# Streaming assembly (bounded memory)
# ---------------------------------------------------------------------------

_DEFAULT_FUSE_METHOD = "brep"
_DEFAULT_FUSE_BATCH_SIZE = 12
_DEFAULT_MESH_BATCH_SIZE = 2
# Coarser than the final-export render tolerance on purpose: each strand B-rep
# is ~10^6 triangles at 0.001 mm, so meshing 150 strands that finely OOMs.
# ~0.05 mm is print-appropriate (SLA layer heights are ~0.05 mm) and ~36x
# lighter per strand.
_DEFAULT_MESH_TOLERANCE = 0.05
_DEFAULT_MESH_ANGULAR_TOLERANCE = 0.3
_DEFAULT_MESH_TOLERANCE_MAX = 0.3
_DEFAULT_MESH_MAX_STRAND_FACES = 80_000
_MESH_LOFT_SAMPLES_CAP = 500
_MESH_MAX_CHUNKS_FACTOR = 2


def _make_rss_logger(label: str) -> Optional[Callable[[str], None]]:
    """Return a stage-boundary RSS logger, or ``None`` if psutil is unavailable.

    Memory pressure is the whole point of the streaming build, so log resident
    set size at stage boundaries to produce evidence instead of guesses. psutil
    is optional: absence degrades to no instrumentation, never to a crash.
    """
    try:
        import psutil
    except Exception:
        return None
    proc = psutil.Process()

    def _log(stage: str) -> None:
        rss_gb = proc.memory_info().rss / (1024.0 ** 3)
        logger.info("%s: RSS=%.2f GB (%s)", label, rss_gb, stage)

    return _log


def _iter_braid_strands(
    strand_samples: List["_StrandSample"],
    params: BraidParams,
    timings: "_StrandTimings",
) -> Iterator[Solid]:
    """Yield each of the ``2N`` braid strand solids in build order, lazily.

    Lazy generation is what keeps memory bounded: the caller fuses (or meshes)
    each strand and drops it before the next is built, so the full set of
    strands is never resident at once.
    """
    for direction in (-1, 1):
        for i in range(params.num_strands_per_dir):
            phase = i * (2.0 * math.pi / params.num_strands_per_dir)
            if direction == 1:
                phase += math.pi / params.num_strands_per_dir
            yield _build_braid_strand(strand_samples, params, phase, direction, timings)


def _flush_brep_batch(accumulator, pending: List[Solid], *, name: str):
    """Fuse a batch of pending strands into the running accumulator and release them."""
    if not pending:
        return accumulator
    merged = _fuse_solids_map_reduce(
        [accumulator, *pending], name=name, show_progress=False
    )
    pending.clear()
    _release()
    return merged


def _assemble_brep(
    core,
    strands: Iterator[Solid],
    *,
    total_strands: int,
    clip_solid,
    od_trim=None,
    apply_inner_cut: bool = True,
    batch_size: int,
    name: str,
    rss: Optional[Callable[[str], None]] = None,
) -> Solid:
    """Stream build -> per-strand clip -> batched fuse into one accumulator solid.

    Peak memory is bounded by ``accumulator + batch_size`` strands rather than
    all ``2N`` strands plus map-reduce intermediates, which is what previously
    drove the process into an OOM kill during the final fuse.
    """
    accumulator = core
    pending: List[Solid] = []
    built = 0
    bar = tqdm(
        total=total_strands,
        desc=f"Building + fusing braid strands for {name}",
        unit="strand",
        disable=not sys.stderr.isatty(),
    )
    try:
        for strand in strands:
            if clip_solid is not None:
                strand = _clip_one_strand(
                    strand, clip_solid, od_trim=od_trim, apply_inner_cut=apply_inner_cut
                )
            pending.append(strand)
            built += 1
            bar.update(1)
            if len(pending) >= batch_size:
                accumulator = _flush_brep_batch(accumulator, pending, name=name)
                if rss is not None:
                    rss(f"fused {built}/{total_strands}")
        accumulator = _flush_brep_batch(accumulator, pending, name=name)
    finally:
        bar.close()
    if built != total_strands:
        raise RuntimeError(
            f"expected {total_strands} braid strands, built {built}"
        )
    _assert_single_solid(accumulator, name=name)
    return accumulator


def _shape_to_trimesh(shape, *, tolerance: float, angular_tolerance: float):
    """Tessellate a CadQuery shape directly to a ``trimesh.Trimesh`` (no temp file)."""
    import trimesh

    s = shape.val() if hasattr(shape, "val") else shape
    verts, tris = s.tessellate(tolerance, angular_tolerance)
    return trimesh.Trimesh(
        vertices=[(v.x, v.y, v.z) for v in verts],
        faces=tris,
    )


def _tessellate_strand_mesh(
    shape,
    *,
    tolerance: float,
    angular_tolerance: float,
    refine_tolerance: Optional[float] = None,
):
    """Tessellate a strand solid; retry finer when coarse clip meshes are non-volumetric."""
    mesh = _shape_to_trimesh(
        shape, tolerance=tolerance, angular_tolerance=angular_tolerance
    )
    if (
        refine_tolerance is not None
        and refine_tolerance < tolerance - 1e-9
        and not mesh.is_volume
    ):
        mesh = _shape_to_trimesh(
            shape, tolerance=refine_tolerance, angular_tolerance=angular_tolerance
        )
    if not mesh.is_volume:
        raise RuntimeError("clipped strand did not tessellate to a volume mesh")
    return mesh


def _mesh_tolerance_ladder(
    tolerance: float,
    tolerance_max: float,
    angular_tolerance: float,
) -> List[Tuple[float, float]]:
    """Increasing (linear_tol, angular_tol) pairs from config min to max."""
    if tolerance_max < tolerance:
        raise ValueError(
            f"mesh_tolerance_max ({tolerance_max}) must be >= mesh_tolerance ({tolerance})"
        )
    ang_max = max(
        angular_tolerance,
        angular_tolerance * (tolerance_max / max(tolerance, 1e-9)),
    )
    ladder: List[Tuple[float, float]] = []
    t = tolerance
    while True:
        span = tolerance_max - tolerance
        frac = (t - tolerance) / span if span > 1e-12 else 1.0
        ang = angular_tolerance + frac * (ang_max - angular_tolerance)
        ladder.append((t, ang))
        if t >= tolerance_max - 1e-12:
            break
        t = min(t * 1.5, tolerance_max)
    if ladder[-1][0] < tolerance_max - 1e-12:
        ladder.append((tolerance_max, ang_max))
    return ladder


def _reference_strand_face_count(
    strand: Solid, *, tolerance: float, angular_tolerance: float
) -> int:
    s = strand.val() if hasattr(strand, "val") else strand
    _, tris = s.tessellate(tolerance, angular_tolerance)
    return len(tris)


def _pick_mesh_tolerances(
    reference_builder: Callable[[], Solid],
    *,
    tolerance: float,
    angular_tolerance: float,
    tolerance_max: float,
    max_strand_faces: int,
    name: str,
) -> Tuple[float, float, int]:
    """Pick the finest mesh tolerance that keeps a reference strand under the face budget.

  Curved paths (e.g. quarter_turn) tessellate far denser than straight rods at
  the same linear tolerance; probing a reference strand before the full build
  avoids OOM from hundreds of thousands of faces per strand.
    """
    ladder = _mesh_tolerance_ladder(tolerance, tolerance_max, angular_tolerance)
    ang_at_max = ladder[-1][1]
    for tol, ang in ladder:
        ref = reference_builder()
        faces = _reference_strand_face_count(ref, tolerance=tol, angular_tolerance=ang)
        del ref
        _release()
        if faces <= max_strand_faces:
            logger.info(
                "mesh tessellation: using tol=%.4f (config %.4f) — reference "
                "strand faces=%d (budget %d)",
                tol,
                tolerance,
                faces,
                max_strand_faces,
            )
            return tol, ang, faces

    ref = reference_builder()
    faces = _reference_strand_face_count(
        ref, tolerance=tolerance_max, angular_tolerance=ang_at_max
    )
    del ref
    raise RuntimeError(
        f"{name}: reference strand tessellates to {faces} faces even at "
        f"mesh_tolerance_max={tolerance_max} (budget {max_strand_faces}). "
        "Increase mesh_max_strand_faces or mesh_tolerance_max, or reduce "
        "num_strands_per_dir."
    )


def _mesh_union(meshes: List[Any], *, name: str):
    """Union watertight meshes via manifold; single mesh passes through."""
    import trimesh

    if len(meshes) == 1:
        return meshes[0]
    return trimesh.boolean.union(meshes, engine="manifold")


def _mesh_map_reduce_one_round(chunks: List[Any], *, name: str) -> List[Any]:
    """Pair adjacent chunk meshes and union each pair (one map-reduce round)."""
    if len(chunks) <= 1:
        return list(chunks)
    nxt: List[Any] = []
    i = 0
    while i < len(chunks):
        if i + 1 < len(chunks):
            nxt.append(_mesh_union([chunks[i], chunks[i + 1]], name=name))
            i += 2
        else:
            nxt.append(chunks[i])
            i += 1
    _release()
    return nxt


def _mesh_map_reduce_final(chunks: List[Any], *, name: str):
    """Reduce chunk meshes to a single body via repeated map-reduce rounds."""
    current = list(chunks)
    while len(current) > 1:
        current = _mesh_map_reduce_one_round(current, name=name)
    if not current:
        raise RuntimeError(f"{name}: mesh map-reduce produced no chunks")
    return current[0]


def _mesh_volume_bodies(mesh) -> int:
    """Count connected watertight solids with positive volume (ignores sheet debris)."""
    return sum(1 for p in mesh.split() if p.is_volume and p.volume > 1e-3)


def _assert_single_volume_body(mesh, *, name: str) -> None:
    """Raise unless the mesh is one printable solid (single volume component)."""
    vol_parts = [p for p in mesh.split() if p.is_volume and p.volume > 1e-3]
    n_vol = len(vol_parts)
    if n_vol != 1:
        raise RuntimeError(
            f"{name}: mesh union produced {n_vol} volume bodies "
            f"({mesh.body_count} graph components); strands do not form one solid"
        )


def _assemble_mesh(
    core,
    strands: Iterator[Solid],
    *,
    total_strands: int,
    clip_solid,
    od_trim=None,
    apply_inner_cut: bool = True,
    refine_tolerance: Optional[float] = None,
    tolerance: float,
    angular_tolerance: float,
    batch_size: int,
    name: str,
    rss: Optional[Callable[[str], None]] = None,
):
    """Stream tessellate -> per-strand mesh clip -> batched union into the core mesh.

    Each batch of strand meshes is unioned into the core tube mesh immediately.
    Strands only meet the rest of the braid through the core, so folding batches
    into the core (rather than map-reducing strand-only chunks) is required for
    a single connected body. Peak memory is bounded by ``core + batch_size``
    strand meshes at the chosen tessellation tolerance.
    """
    import trimesh

    accumulator = _shape_to_trimesh(
        core, tolerance=tolerance, angular_tolerance=angular_tolerance
    )

    pending: List[Any] = []
    built = 0

    def _flush_pending() -> None:
        nonlocal accumulator, pending
        if not pending:
            return
        batch = _mesh_union(pending, name=name) if len(pending) > 1 else pending[0]
        pending = []
        _release()
        accumulator = _mesh_union([accumulator, batch], name=name)
        _release()

    bar = tqdm(
        total=total_strands,
        desc=f"Meshing + unioning braid strands for {name}",
        unit="strand",
        disable=not sys.stderr.isatty(),
    )
    try:
        for strand in strands:
            if clip_solid is not None:
                strand = _clip_one_strand(
                    strand, clip_solid, od_trim=od_trim, apply_inner_cut=apply_inner_cut
                )
            strand_mesh = _tessellate_strand_mesh(
                strand,
                tolerance=tolerance,
                angular_tolerance=angular_tolerance,
                refine_tolerance=refine_tolerance,
            )
            del strand
            _release()
            pending.append(strand_mesh)
            built += 1
            bar.update(1)
            if len(pending) >= batch_size:
                _flush_pending()
                if rss is not None:
                    rss(f"unioned {built}/{total_strands}")
        _flush_pending()
    finally:
        bar.close()
    if built != total_strands:
        raise RuntimeError(
            f"expected {total_strands} braid strands, built {built}"
        )

    result = accumulator
    if not result.is_watertight:
        raise RuntimeError(f"{name}: mesh union is not watertight")
    _assert_single_volume_body(result, name=name)
    return result


class BraidedRopeModel:
    """Braided sleeve: smooth core + 2N interlacing helical strands.

    Strands are built lazily and folded one at a time into a running result so
    memory stays bounded for high strand counts. ``fuse_method`` selects the
    output: ``brep`` (default) returns a single fused ``Solid`` and preserves the
    STEP / SLA-optimize pipeline; ``mesh`` returns a watertight ``trimesh.Trimesh``
    via fast manifold unions (no STEP / optimize).
    """

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

        raw = getattr(config.tube_settings, "braided_rope", None) or {}
        fuse_method = str(raw.get("fuse_method", _DEFAULT_FUSE_METHOD)).lower()
        if fuse_method not in ("brep", "mesh"):
            raise ValueError(
                f"braided_rope.fuse_method must be 'brep' or 'mesh' "
                f"(got {fuse_method!r})"
            )
        batch_size = int(raw.get("fuse_batch_size", _DEFAULT_FUSE_BATCH_SIZE))
        if batch_size < 1:
            raise ValueError("braided_rope.fuse_batch_size must be >= 1")
        mesh_batch_size = int(raw.get("mesh_batch_size", _DEFAULT_MESH_BATCH_SIZE))
        if mesh_batch_size < 1:
            raise ValueError("braided_rope.mesh_batch_size must be >= 1")

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
        if fuse_method == "mesh":
            loft_samples = min(loft_samples, _MESH_LOFT_SAMPLES_CAP)

        log_batch = mesh_batch_size if fuse_method == "mesh" else batch_size
        logger.info(
            "BraidedRopeModel: %s; base_face_type=%s; path_length=%.1f mm, "
            "loft_samples=%d, fuse_method=%s, batch_size=%d",
            params.summary(),
            base_face_type,
            path_length,
            loft_samples,
            fuse_method,
            log_batch,
        )

        rss = _make_rss_logger("BraidedRopeModel")

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
        if rss is not None:
            rss("core built")

        # Centerline samples (frame at each arc-length step) are identical for
        # every strand, so sample them once instead of per strand.
        strand_samples = _sample_strand_centerline(
            frames, path_length, params, loft_samples
        )

        total_strands = 2 * params.num_strands_per_dir
        timings = _StrandTimings()

        clip_solid = None
        refine_tolerance = None
        apply_inner_clip = True
        if base_face_type in _SWEPT_BASE_FACE_TYPES:
            rotation_z = float((face_kwargs or {}).get("rotation_z", 90.0))
            curved = _path_has_curvature(frames, path_length)
            apply_inner_clip = not curved
            clip_solid = _build_embed_clip_solid(
                path,
                aux,
                config,
                params,
                frames=frames,
                strand_samples=strand_samples,
                rotation_z=rotation_z,
            )
            if curved and fuse_method == "mesh":
                refine_tolerance = float(
                    raw.get("mesh_tolerance", _DEFAULT_MESH_TOLERANCE)
                )

        strands = _iter_braid_strands(strand_samples, params, timings)
        name = config.name or "braid"

        if fuse_method == "mesh":
            tol_cfg = float(raw.get("mesh_tolerance", _DEFAULT_MESH_TOLERANCE))
            ang_cfg = float(
                raw.get("mesh_angular_tolerance", _DEFAULT_MESH_ANGULAR_TOLERANCE)
            )
            tol_max = float(raw.get("mesh_tolerance_max", _DEFAULT_MESH_TOLERANCE_MAX))
            max_faces = int(raw.get("mesh_max_strand_faces", _DEFAULT_MESH_MAX_STRAND_FACES))

            def _reference_strand() -> Solid:
                return _build_braid_strand(strand_samples, params, 0.0, -1, timings)

            tol, ang, _ = _pick_mesh_tolerances(
                _reference_strand,
                tolerance=tol_cfg,
                angular_tolerance=ang_cfg,
                tolerance_max=tol_max,
                max_strand_faces=max_faces,
                name=name,
            )
            result = _assemble_mesh(
                core,
                strands,
                total_strands=total_strands,
                clip_solid=clip_solid,
                apply_inner_cut=apply_inner_clip,
                refine_tolerance=refine_tolerance,
                tolerance=tol,
                angular_tolerance=ang,
                batch_size=mesh_batch_size,
                name=name,
                rss=rss,
            )
        else:
            result = _assemble_brep(
                core,
                strands,
                total_strands=total_strands,
                clip_solid=clip_solid,
                apply_inner_cut=apply_inner_clip,
                batch_size=batch_size,
                name=name,
                rss=rss,
            )

        logger.info("BraidedRopeModel: built %d/%d strands", total_strands, total_strands)
        logger.info("BraidedRopeModel: %s", timings.summary())
        if rss is not None:
            rss("assembly complete")
        return result
