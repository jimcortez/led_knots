"""Braid sleeve placement relative to swept base tubes."""

from __future__ import annotations

from types import SimpleNamespace

from led_knots.core.tube_models.braided_rope import (
    _params_from_config,
    _strand_envelope_radius,
    _strand_valley_radius,
)


def _tube_settings(
    *,
    face_type: str,
    outer_diameter: float = 30.0,
    wall_thickness: float = 4.0,
    braided_rope: dict | None = None,
):
    br = {
        "num_strands_per_dir": 25,
        "float_length": 1,
        "helix_angle_deg": 30.0,
        "strand_aspect_ratio": 1.6,
        "tilt_to_helix_angle": True,
        "weave_amplitude_factor": 1.05,
        "pack_factor": 0.7,
    }
    if braided_rope is not None:
        br.update(braided_rope)
    return SimpleNamespace(
        face_type=face_type,
        outer_radius=outer_diameter / 2.0,
        wall_thickness=wall_thickness,
        braided_rope=br,
    )


def test_sleeve_valley_embed_depth_default() -> None:
    config = SimpleNamespace(
        tube_settings=_tube_settings(face_type="braided_rope_tube")
    )
    params = _params_from_config(config, base_face_type="led_circle_tube")
    tube_r = config.tube_settings.outer_radius
    assert abs(_strand_valley_radius(params) - (tube_r - 0.5)) < 0.05


def test_sleeve_valley_embed_depth_override() -> None:
    tube_r = 15.0
    for depth in (0.0, 1.0):
        config = SimpleNamespace(
            tube_settings=_tube_settings(
                face_type="braided_rope_tube",
                braided_rope={"valley_embed_depth": depth},
            )
        )
        params = _params_from_config(config, base_face_type="led_circle_tube")
        assert abs(_strand_valley_radius(params) - (tube_r - depth)) < 0.05


def test_sleeve_auto_scales_outer_radius_for_tube() -> None:
    """Swept-base braids stay near the tube OD (no runaway outer_radius)."""
    config = SimpleNamespace(
        tube_settings=_tube_settings(
            face_type="braided_rope_tube",
            braided_rope={"num_strands_per_dir": 20, "braid_tightness": 1.0},
        )
    )
    params = _params_from_config(config, base_face_type="led_circle_tube")
    tube_r = config.tube_settings.outer_radius
    assert params.outer_radius < tube_r + 3.0
    assert abs(_strand_valley_radius(params) - (tube_r - 0.5)) < 0.05
    assert params.pack_factor > 0.7


def test_sleeve_braid_tightness_boosts_pack_factor() -> None:
    loose = _params_from_config(
        SimpleNamespace(
            tube_settings=_tube_settings(
                face_type="braided_rope_tube",
                braided_rope={"braid_tightness": 0.0},
            )
        ),
        base_face_type="led_circle_tube",
    )
    tight = _params_from_config(
        SimpleNamespace(
            tube_settings=_tube_settings(
                face_type="braided_rope_tube",
                braided_rope={"braid_tightness": 1.0},
            )
        ),
        base_face_type="led_circle_tube",
    )
    assert tight.pack_factor > loose.pack_factor
    tube_r = 15.0
    assert tight.outer_radius < tube_r + 3.0


def test_braid_core_keeps_envelope_at_tube_od() -> None:
    config = SimpleNamespace(tube_settings=_tube_settings(face_type="braided_rope"))
    params = _params_from_config(config, base_face_type="braid_core")
    tube_r = config.tube_settings.outer_radius
    assert abs(_strand_envelope_radius(params) - tube_r) < 0.05


def test_braid_core_ignores_valley_embed_depth() -> None:
    config = SimpleNamespace(
        tube_settings=_tube_settings(
            face_type="braided_rope",
            braided_rope={"valley_embed_depth": 2.0},
        )
    )
    params = _params_from_config(config, base_face_type="braid_core")
    tube_r = config.tube_settings.outer_radius
    assert abs(_strand_envelope_radius(params) - tube_r) < 0.05
    assert abs(params.radial_offset) < 1e-6
