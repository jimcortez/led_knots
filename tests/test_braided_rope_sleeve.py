"""Braid sleeve placement relative to swept base tubes."""

from __future__ import annotations

from types import SimpleNamespace

from led_knots.core.tube_models.braided_rope import (
    _params_from_config,
    _strand_envelope_radius,
)


def _tube_settings(*, face_type: str, outer_diameter: float = 30.0):
    return SimpleNamespace(
        face_type=face_type,
        outer_radius=outer_diameter / 2.0,
        braided_rope={
            "num_strands_per_dir": 25,
            "float_length": 1,
            "helix_angle_deg": 30.0,
            "strand_aspect_ratio": 1.6,
            "tilt_to_helix_angle": True,
            "weave_amplitude_factor": 1.05,
            "pack_factor": 0.7,
        },
    )


def test_sleeve_sits_outside_led_circle_tube_base() -> None:
    config = SimpleNamespace(tube_settings=_tube_settings(face_type="braided_rope_tube"))
    params = _params_from_config(config, base_face_type="led_circle_tube")
    tube_r = config.tube_settings.outer_radius
    assert _strand_envelope_radius(params) > tube_r + 0.1


def test_braid_core_keeps_envelope_at_tube_od() -> None:
    config = SimpleNamespace(tube_settings=_tube_settings(face_type="braided_rope"))
    params = _params_from_config(config, base_face_type="braid_core")
    tube_r = config.tube_settings.outer_radius
    assert abs(_strand_envelope_radius(params) - tube_r) < 0.05
