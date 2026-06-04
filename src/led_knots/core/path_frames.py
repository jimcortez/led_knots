"""
Parallel-transported frames along a centerline path.

A `PathFrame` is a complete local coordinate system at a single arc-length
position along a Wire: origin (`point`), unit `tangent`, and an in-cross-section
`(x_dir, y_dir)` basis that is parallel-transported from the start of the path
so the cross-section orientation does not flip on curves.

This module exists to be the single source of truth for path framing used by
every tube model — the simple swept-face models, the pyramid-studded model, and
the braided-rope model all consume the same frames.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from cadquery import Vector
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.GCPnts import GCPnts_UniformAbscissa


@dataclass(frozen=True)
class PathFrame:
    """Local frame at a sample along a centerline path."""

    t: float
    point: Vector
    tangent: Vector
    x_dir: Vector
    y_dir: Vector
    arc_length: float


def _norm3(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    d = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if d < 1e-10:
        return v
    return (v[0] / d, v[1] / d, v[2] / d)


def _cross(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _seed_x_dir(tangent: Tuple[float, float, float]) -> Tuple[float, float, float]:
    ref = (0.0, 0.0, 1.0) if abs(tangent[2]) < 0.9 else (1.0, 0.0, 0.0)
    return _norm3(_cross(tangent, ref))


def _t_values_uniform_arc(path, num_samples: int) -> List[float]:
    """t values at uniform arc length when path is a single edge; falls back to uniform t."""
    edges = path.Edges()
    if len(edges) != 1 or num_samples < 2:
        return [i / (num_samples - 1) for i in range(num_samples)] if num_samples > 1 else [1.0]
    edge = edges[0]
    adaptor = BRepAdaptor_Curve(edge.wrapped)
    u1, u2 = adaptor.FirstParameter(), adaptor.LastParameter()
    dist = GCPnts_UniformAbscissa(adaptor, num_samples, u1, u2)
    if not dist.IsDone():
        return [i / (num_samples - 1) for i in range(num_samples)]
    out: List[float] = []
    span = u2 - u1
    for i in range(1, dist.NbPoints() + 1):
        u = dist.Parameter(i)
        out.append((u - u1) / span if span > 0 else 0.0)
    return out


def sample_path_frames(
    path,
    num_samples: int,
    *,
    uniform_arc: bool = False,
) -> List[PathFrame]:
    """
    Sample `num_samples` frames along `path` with parallel-transported x/y basis.

    When `uniform_arc=True` the t values are chosen so sample points are evenly
    spaced in arc length (uses OCC's GCPnts_UniformAbscissa for single-edge wires).
    Otherwise t is sampled uniformly in [0, 1].

    Arc length is accumulated as chord distance between successive samples — the
    same approximation used elsewhere in the package.
    """
    if num_samples < 1:
        raise ValueError("num_samples must be >= 1")

    if uniform_arc:
        t_values = _t_values_uniform_arc(path, num_samples)
    else:
        t_values = (
            [i / (num_samples - 1) for i in range(num_samples)] if num_samples > 1 else [1.0]
        )

    frames: List[PathFrame] = []
    prev_x: Optional[Tuple[float, float, float]] = None
    prev_pt: Optional[Vector] = None
    cumulative = 0.0
    for i, t in enumerate(t_values):
        pt = path.positionAt(t)
        tg = path.tangentAt(t)
        tangent3 = _norm3((tg.x, tg.y, tg.z))

        if prev_x is None:
            x3 = _seed_x_dir(tangent3)
        else:
            dot = prev_x[0] * tangent3[0] + prev_x[1] * tangent3[1] + prev_x[2] * tangent3[2]
            proj = (
                prev_x[0] - dot * tangent3[0],
                prev_x[1] - dot * tangent3[1],
                prev_x[2] - dot * tangent3[2],
            )
            mag = math.sqrt(proj[0] ** 2 + proj[1] ** 2 + proj[2] ** 2)
            x3 = _norm3(proj) if mag > 1e-6 else _seed_x_dir(tangent3)
        prev_x = x3

        if prev_pt is not None:
            dx = pt.x - prev_pt.x
            dy = pt.y - prev_pt.y
            dz = pt.z - prev_pt.z
            cumulative += math.sqrt(dx * dx + dy * dy + dz * dz)
        prev_pt = pt

        y3 = _norm3(_cross(tangent3, x3))
        frames.append(
            PathFrame(
                t=t,
                point=pt,
                tangent=Vector(*tangent3),
                x_dir=Vector(*x3),
                y_dir=Vector(*y3),
                arc_length=cumulative,
            )
        )
    return frames


def frame_at_arc_length(frames: List[PathFrame], s: float) -> PathFrame:
    """
    Return a `PathFrame` at arc length `s` by linearly interpolating origin
    between bracketing samples; tangent/x_dir/y_dir are taken from the nearest
    upstream sample so they remain stable on curves (a discrete parallel-transport
    approximation, matching the POC scripts' behavior).
    """
    if not frames:
        raise ValueError("frames is empty")
    if s <= frames[0].arc_length:
        return frames[0]
    if s >= frames[-1].arc_length:
        return frames[-1]

    for i in range(len(frames) - 1):
        s0 = frames[i].arc_length
        s1 = frames[i + 1].arc_length
        if s0 <= s <= s1:
            if s1 - s0 < 1e-9:
                return frames[i]
            u = (s - s0) / (s1 - s0)
            p0 = frames[i].point
            p1 = frames[i + 1].point
            pt = Vector(
                p0.x + u * (p1.x - p0.x),
                p0.y + u * (p1.y - p0.y),
                p0.z + u * (p1.z - p0.z),
            )
            ref = frames[i]
            return PathFrame(
                t=ref.t,
                point=pt,
                tangent=ref.tangent,
                x_dir=ref.x_dir,
                y_dir=ref.y_dir,
                arc_length=s,
            )
    return frames[-1]


def frame_to_dict(frame: PathFrame) -> dict:
    """Compatibility view: dict shape used by older sample-list consumers."""
    return {
        "t": frame.t,
        "point": frame.point,
        "tangent": frame.tangent,
        "x_dir": frame.x_dir,
        "y_dir": frame.y_dir,
        "arc_length": frame.arc_length,
    }
