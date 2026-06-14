"""Swept tube profiles must be concentric with the path centerline.

Regression for a 0.5 mm profile-center offset baked into the face factories:
the swept tube rode 0.5 mm off the path while path-frame-based decorations
(braid strands, pyramid studs) orbit the true path center, so embed depths
varied azimuthally from 0 to twice the configured value.
"""

from __future__ import annotations

from types import SimpleNamespace

from cadquery.func import spline, sweep

from led_knots.core.led_circle import (
    create_led_circle_face,
    create_led_circle_tube_face,
    create_solid_circle_face,
    create_square_face,
)
from led_knots.core.tube_models.braided_rope import (
    _params_from_config,
    _strand_envelope_radius,
    _swept_embed_clip_shell,
)

_TOL = 1e-3


def _bbox_center_xy(shape) -> tuple:
    bb = shape.BoundingBox()
    return ((bb.xmin + bb.xmax) / 2.0, (bb.ymin + bb.ymax) / 2.0)


def _assert_centered(shape, label: str) -> None:
    cx, cy = _bbox_center_xy(shape)
    assert abs(cx) < _TOL and abs(cy) < _TOL, (
        f"{label} profile center is ({cx:.4f}, {cy:.4f}), expected the origin"
    )


def test_face_profiles_centered_on_origin() -> None:
    _assert_centered(
        create_led_circle_face(outer_radius=15.0, wall_thickness=4.0),
        "led_circle",
    )
    _assert_centered(
        create_led_circle_tube_face(
            outer_radius=15.0,
            wall_thickness=4.0,
            inner_tube_diameter=8.0,
            inner_tube_wall_thickness=0.5,
        ),
        "led_circle_tube",
    )
    _assert_centered(
        create_solid_circle_face(outer_radius=15.0, wall_thickness=4.0),
        "solid_circle",
    )
    _assert_centered(
        create_square_face(outer_radius=15.0, wall_thickness=4.0),
        "square",
    )


def test_swept_tube_concentric_with_path() -> None:
    path = spline([(0, 0, 0), (0, 0, 50)])
    profile = create_led_circle_tube_face(
        outer_radius=15.0,
        wall_thickness=4.0,
        inner_tube_diameter=8.0,
        inner_tube_wall_thickness=0.5,
        orient_to_path=path,
    )
    tube = sweep(profile, path)
    _assert_centered(tube, "swept led_circle_tube")


def test_embed_clip_shell_concentric_with_path() -> None:
    config = SimpleNamespace(
        tube_settings=SimpleNamespace(
            face_type="braided_rope_tube",
            outer_radius=15.0,
            wall_thickness=4.0,
            braided_rope={"num_strands_per_dir": 20},
        )
    )
    params = _params_from_config(config, base_face_type="led_circle_tube")
    path = spline([(0, 0, 0), (0, 0, 50)])
    max_r = _strand_envelope_radius(params) + 15.0
    shell = _swept_embed_clip_shell(path, None, config, max_radius=max_r)
    _assert_centered(shell, "embed clip shell")
