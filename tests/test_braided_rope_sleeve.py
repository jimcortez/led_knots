"""Braid sleeve placement relative to swept base tubes."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest
from cadquery.func import box, intersect, spline

from led_knots.core.path_frames import sample_path_frames
from led_knots.core.tube_models.braided_rope import (
    _build_braid_strand,
    _clip_strands_to_embed_shell,
    _params_from_config,
    _strand_envelope_radius,
    _strand_valley_radius,
)

# Matches the production loft_samples formula in BraidedRopeModel.build for
# the 100 mm straight test path used below.
_PATH_LENGTH = 100.0


def _production_loft_samples(params) -> int:
    return max(
        240,
        min(
            1500,
            math.ceil(
                params.samples_per_period * params.N * _PATH_LENGTH / params.pitch
            ),
        ),
    )


def _build_test_strand(params, frames, direction: int, loft_samples: int):
    phase = 0.0 if direction == -1 else math.pi / params.num_strands_per_dir
    return _build_braid_strand(
        frames, _PATH_LENGTH, params, phase, direction, loft_samples
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


@pytest.fixture(scope="module")
def production_strands():
    """One CW and one CCW strand at production loft sampling (render config params)."""
    config = SimpleNamespace(
        tube_settings=_tube_settings(
            face_type="braided_rope_tube",
            braided_rope={
                "num_strands_per_dir": 20,
                "braid_tightness": 1.0,
                "pack_factor": 0.9,
                "weave_amplitude_factor": 1.0,
            },
        )
    )
    params = _params_from_config(config, base_face_type="led_circle_tube")
    path = spline([(0, 0, 0), (0, 0, _PATH_LENGTH)])
    frames = sample_path_frames(path, 120)
    loft_samples = _production_loft_samples(params)
    cw = _build_test_strand(params, frames, -1, loft_samples)
    ccw = _build_test_strand(params, frames, 1, loft_samples)
    return config, params, path, cw, ccw


def test_braid_strand_volumes_symmetric_both_directions(production_strands) -> None:
    """CW and CCW strands are mirror geometry and must have matching volume.

    Regression for the CCW loft collapse: lofting all sections in one OCC
    ThruSections call silently lost up to a quarter of the CCW strand volume.
    (`_build_braid_strand` itself raises if a loft deviates >15% from the
    analytic volume, so building the fixture already exercises that guard.)
    """
    _, _, _, cw, ccw = production_strands
    vol_cw, vol_ccw = cw.Volume(), ccw.Volume()
    assert vol_cw > 1.0 and vol_ccw > 1.0
    assert abs(vol_cw - vol_ccw) / max(vol_cw, vol_ccw) < 0.05, (
        f"CW/CCW strand volumes diverge: {vol_cw:.1f} vs {vol_ccw:.1f} mm^3"
    )


def test_braid_strand_cross_sections_uniform(production_strands) -> None:
    """Thin z-slab sections along each strand stay close to the nominal ellipse.

    Catches localized pinching/fold-over that volume totals can hide. Slab
    area exceeds the nominal ellipse area by 1/cos(inclination), so the band
    is wider than the ellipse tolerance alone.
    """
    _, params, _, cw, ccw = production_strands
    nominal = math.pi * params.p * params.a
    eps = 0.4
    means = []
    for label, strand in (("CW", cw), ("CCW", ccw)):
        bb = strand.BoundingBox()
        areas = []
        for i in range(6):
            frac = 0.2 + 0.6 * i / 5
            z = bb.zmin + frac * (bb.zmax - bb.zmin)
            slab = box(200, 200, eps).moved(z=z)
            areas.append(intersect(strand, slab).Volume() / eps)
        for frac_area in areas:
            ratio = frac_area / nominal
            assert 1.0 <= ratio <= 1.8, (
                f"{label} slab section area {frac_area:.2f} mm^2 outside band "
                f"[{nominal:.2f}, {1.8 * nominal:.2f}]"
            )
        means.append(sum(areas) / len(areas))
    assert abs(means[0] - means[1]) / max(means) < 0.10, (
        f"CW/CCW mean section areas diverge: {means[0]:.2f} vs {means[1]:.2f} mm^2"
    )


def test_braid_strands_survive_embed_clip(production_strands) -> None:
    """The embed-shell clip must keep nearly all strand material in one piece.

    With valley-targeted placement the clip floor sits exactly at the strand
    valley bottoms, so a correct clip removes almost nothing. Heavy loss or
    fragmentation indicates the clip shell is not concentric with the strands
    (the 0.5 mm profile-eccentricity bug produced sliced valleys and slivers).
    """
    config, params, path, cw, ccw = production_strands
    strands = [cw, ccw]
    clipped = _clip_strands_to_embed_shell(strands, path, None, config, params)
    assert len(clipped) == len(strands)
    for label, before, after in zip(("CW", "CCW"), strands, clipped):
        retention = after.Volume() / before.Volume()
        assert retention >= 0.85, (
            f"{label} strand lost {100 * (1 - retention):.1f}% of its volume to the embed clip"
        )
        assert len(after.Solids()) == 1, (
            f"{label} strand fragmented into {len(after.Solids())} pieces after clip"
        )
