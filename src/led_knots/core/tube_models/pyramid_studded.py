"""
Pyramid-studded tube: a smooth base sweep with discrete 4-sided pyramidal
solids placed on the outer surface.

The base tube is built by reusing a `SweptFaceModel` (any registered smooth
face type — typically `solid_circle` or `led_circle`). On top, pyramid sites
are laid out in axial rows along the centerline path, each row carrying a
configurable number of pyramids around the perimeter. Each pyramid is a real
4-sided 3D solid (square base, apex pointing radially outward), constructed
by stitching its five faces into a closed Shell.

The base tube and all pyramid solids are returned as a single `Compound`. No
boolean union is performed — STL / GLB tessellation merges the geometry for
rendering and slicing, and a true union can be opted into later.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

import cadquery as cq
from cadquery import Vector
from cadquery.occ_impl.shapes import Compound, Face, Shell, Solid, Wire

from ..path_frames import PathFrame, frame_at_arc_length, sample_path_frames
from .swept_face import SweptFaceModel

logger = logging.getLogger(__name__)


_DEFAULTS: Dict[str, Any] = {
    "base_face_type": "solid_circle",
    "base_size": 2.0,
    "height": 2.5,
    "axial_pitch": 4.0,
    "axial_margin": 4.0,
    "circumferential_count": 12,
    "stagger_rows": True,
    "embed_depth": 0.3,
    "path_frame_samples": 200,
}


def _settings(config: Any) -> Dict[str, Any]:
    raw = getattr(config.tube_settings, "pyramid_studded", None) or {}
    out = dict(_DEFAULTS)
    out.update({k: v for k, v in raw.items() if v is not None})
    return out


def _vadd(a: Vector, b: Vector) -> Vector:
    return Vector(a.x + b.x, a.y + b.y, a.z + b.z)


def _vscale(v: Vector, s: float) -> Vector:
    return Vector(v.x * s, v.y * s, v.z * s)


def _make_pyramid_solid(
    base_corners: List[Vector],
    apex: Vector,
) -> Solid:
    """Build a 4-sided pyramid Solid from its 4 base corners and apex Vector."""
    if len(base_corners) != 4:
        raise ValueError("pyramid base must have 4 corners")

    base_wire = Wire.makePolygon([*base_corners, base_corners[0]])
    base_face = Face.makeFromWires(base_wire)

    side_faces: List[Face] = []
    for i in range(4):
        a = base_corners[i]
        b = base_corners[(i + 1) % 4]
        tri = Wire.makePolygon([a, b, apex, a])
        side_faces.append(Face.makeFromWires(tri))

    shell = Shell.makeShell([base_face, *side_faces])
    return Solid.makeSolid(shell)


def _pyramid_at(
    frame: PathFrame,
    theta: float,
    *,
    outer_radius: float,
    base_size: float,
    height: float,
    embed_depth: float,
) -> Solid:
    """
    Build one pyramid at angular position `theta` on the tube's outer surface
    at the given path frame.
    """
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    x_dir = frame.x_dir
    y_dir = frame.y_dir
    tangent = frame.tangent
    origin = frame.point

    outer_normal = Vector(
        cos_t * x_dir.x + sin_t * y_dir.x,
        cos_t * x_dir.y + sin_t * y_dir.y,
        cos_t * x_dir.z + sin_t * y_dir.z,
    )
    circumferential = Vector(
        -sin_t * x_dir.x + cos_t * y_dir.x,
        -sin_t * x_dir.y + cos_t * y_dir.y,
        -sin_t * x_dir.z + cos_t * y_dir.z,
    )

    base_center = _vadd(origin, _vscale(outer_normal, outer_radius - embed_depth))
    apex = _vadd(origin, _vscale(outer_normal, outer_radius + height))

    half = 0.5 * base_size
    base_corners = [
        _vadd(_vadd(base_center, _vscale(tangent, +half)), _vscale(circumferential, +half)),
        _vadd(_vadd(base_center, _vscale(tangent, -half)), _vscale(circumferential, +half)),
        _vadd(_vadd(base_center, _vscale(tangent, -half)), _vscale(circumferential, -half)),
        _vadd(_vadd(base_center, _vscale(tangent, +half)), _vscale(circumferential, -half)),
    ]

    return _make_pyramid_solid(base_corners, apex)


def _row_arc_lengths(path_length: float, *, axial_pitch: float, axial_margin: float) -> List[float]:
    """Arc-length positions where pyramid rows are placed."""
    usable_start = max(0.0, axial_margin)
    usable_end = max(usable_start, path_length - axial_margin)
    if usable_end - usable_start < axial_pitch * 0.5:
        return []
    n_rows = max(1, int(math.floor((usable_end - usable_start) / axial_pitch)) + 1)
    spacing = (usable_end - usable_start) / max(1, n_rows - 1) if n_rows > 1 else 0.0
    return [usable_start + i * spacing for i in range(n_rows)]


class PyramidStuddedModel:
    """Base swept tube + discrete 4-sided 3D pyramidal studs on the outer surface."""

    def build(
        self,
        *,
        path,
        aux,
        config: Any,
        face_kwargs: Optional[Dict[str, Any]] = None,
    ):
        settings = _settings(config)
        base_face_type = settings["base_face_type"]
        if base_face_type == "pyramid_studded":
            raise ValueError("pyramid_studded.base_face_type cannot be 'pyramid_studded'")

        swept_model = SweptFaceModel(base_face_type)
        base_tube = swept_model.build(
            path=path, aux=aux, config=config, face_kwargs=face_kwargs
        )

        outer_radius = float(config.tube_settings.outer_radius)
        base_size = float(settings["base_size"])
        height = float(settings["height"])
        axial_pitch = float(settings["axial_pitch"])
        axial_margin = float(settings["axial_margin"])
        circ_count = int(settings["circumferential_count"])
        stagger = bool(settings["stagger_rows"])
        embed_depth = float(settings["embed_depth"])
        frame_samples = int(settings["path_frame_samples"])

        if base_size <= 0 or height <= 0 or axial_pitch <= 0 or circ_count <= 0:
            raise ValueError(
                "pyramid_studded requires positive base_size, height, axial_pitch, "
                f"circumferential_count (got {base_size=}, {height=}, {axial_pitch=}, "
                f"{circ_count=})"
            )
        if embed_depth >= outer_radius:
            raise ValueError(
                f"embed_depth ({embed_depth}) must be < outer_radius ({outer_radius})"
            )

        frames = sample_path_frames(path, frame_samples)
        path_length = frames[-1].arc_length if frames else 0.0
        row_positions = _row_arc_lengths(
            path_length, axial_pitch=axial_pitch, axial_margin=axial_margin
        )

        if not row_positions:
            logger.warning(
                "pyramid_studded: path too short for any pyramid rows "
                "(length=%.2f mm, axial_pitch=%.2f mm)",
                path_length, axial_pitch,
            )
            return base_tube

        d_theta = 2.0 * math.pi / circ_count
        pyramids: List[Solid] = []
        for row_idx, s in enumerate(row_positions):
            frame = frame_at_arc_length(frames, s)
            phase = 0.5 * d_theta if (stagger and row_idx % 2 == 1) else 0.0
            for k in range(circ_count):
                theta = phase + k * d_theta
                pyramids.append(
                    _pyramid_at(
                        frame,
                        theta,
                        outer_radius=outer_radius,
                        base_size=base_size,
                        height=height,
                        embed_depth=embed_depth,
                    )
                )

        logger.info(
            "pyramid_studded: %d rows × %d per row = %d pyramids on a %.1f mm path",
            len(row_positions), circ_count, len(pyramids), path_length,
        )
        return Compound.makeCompound([base_tube, *pyramids])
