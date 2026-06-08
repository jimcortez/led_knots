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
import signal
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import cadquery as cq
from cadquery import Vector, Wire, Plane, Edge
from cadquery.occ_impl.shapes import Compound, Solid
from tqdm.auto import tqdm

from ..path_frames import PathFrame, frame_at_arc_length, sample_path_frames
from .swept_face import SweptFaceModel

logger = logging.getLogger(__name__)


@contextmanager
def _time_limit(seconds: int):
    """Raise TimeoutError if the wrapped block runs past `seconds` (Unix only)."""
    def _handler(signum, frame):
        raise TimeoutError(f"exceeded {seconds}s")
    prev = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, prev)


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
        return (
            f"Braid params: total strands = {total_strands} "
            f"(F={self.float_length}), Rr={self.Rr:.3f}, "
            f"outer_R={self.outer_radius:.3f}, a={self.a:.3f}, p={self.p:.3f}, "
            f"A={self.A:.3f}, pitch={self.pitch:.2f}, "
            f"core_radius={self.core_radius:.3f}"
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
    r_mod = params.Rr + direction * params.A * math.sin(omega_s * s)
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

    try:
        return Solid.makeLoft(wires, ruled=False), "loft"
    except Exception:
        try:
            return Solid.makeLoft(wires, ruled=True), "loft-ruled"
        except Exception:
            pass

    try:
        with _time_limit(30):
            path_pts = [Vector(*p) for p in pts]
            path_edge = Edge.makeSpline(path_pts)
            path_wire = Wire.assembleEdges([path_edge])
            profile = _lenticular_wire(pts[0], tangents[0], x_dirs[0], params, direction)
            return Solid.sweep(profile, [], path_wire, makeSolid=True, isFrenet=True), "sweep"
    except (TimeoutError, Exception):
        return None, "failed"


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
    return params.Rr + params.A + params.radial_extent


def _params_from_config(config: Any, *, base_face_type: str = "braid_core") -> BraidParams:
    raw = getattr(config.tube_settings, "braided_rope", None) or {}
    kwargs: Dict[str, Any] = {
        k: v for k, v in raw.items() if k in _PARAM_KEYS and v is not None
    }
    tube_r = float(config.tube_settings.outer_radius)
    if "outer_radius" not in kwargs:
        kwargs["outer_radius"] = tube_r

    if base_face_type != "braid_core":
        # Swept bases (led_circle_tube, solid_circle, …) already occupy the
        # tube OD.  Strands must sit outside that surface or a later fuse
        # absorbs them into the wall with no visible braid texture.
        outer = float(kwargs["outer_radius"])
        for _ in range(8):
            probe = BraidParams(**{**kwargs, "outer_radius": outer})
            if _strand_envelope_radius(probe) > tube_r + 1e-3:
                return probe
            outer = tube_r + probe.p + probe.radial_extent
        kwargs["outer_radius"] = outer

    return BraidParams(**kwargs)


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
        method_counts = {"loft": 0, "loft-ruled": 0, "sweep": 0, "failed": 0}
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
                strand, method = _build_braid_strand(
                    frames, path_length, params, phase, direction, loft_samples
                )
                method_counts[method] = method_counts.get(method, 0) + 1
                if strand is not None:
                    strands.append(strand)
                bar.update(1)
        bar.close()

        logger.info(
            "BraidedRopeModel: built %d/%d strands (loft=%d, loft-ruled=%d, sweep=%d, failed=%d)",
            len(strands), total_strands,
            method_counts["loft"], method_counts["loft-ruled"],
            method_counts["sweep"], method_counts["failed"],
        )

        return Compound.makeCompound([core, *strands])
