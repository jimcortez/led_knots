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
    _sample_strand_centerline,
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
    samples = _sample_strand_centerline(frames, _PATH_LENGTH, params, loft_samples)
    return _build_braid_strand(samples, params, phase, direction)


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


def test_braid_strand_curved_path_high_twist_phases() -> None:
    """High-twist strands on a curved path must pass the volume guard.

    Regression: uncapped shell sewing with the default 32-section chunk size
    collapsed some strands on the quarter-turn path (volume ~1 mm^3 vs ~18 mm^3
    expected). Smaller chunk fallbacks must recover without changing geometry.
    """
    config = SimpleNamespace(
        tube_settings=_tube_settings(
            face_type="braided_rope_tube",
            braided_rope={
                "num_strands_per_dir": 75,
                "pack_factor": 0.7,
            },
        )
    )
    params = _params_from_config(config, base_face_type="led_circle_tube")
    path = spline(
        [(0, 0, 0), (0, 100, 100)],
        tgts=[(0, 0, 1), (0, 1, 0)],
    )
    path_length = path.Length()
    frames = sample_path_frames(path, max(120, min(400, int(path_length))))
    loft_samples = max(
        240,
        min(
            1500,
            math.ceil(
                params.samples_per_period * params.N * path_length / params.pitch
            ),
        ),
    )
    samples = _sample_strand_centerline(frames, path_length, params, loft_samples)
    # i=30 and i=32 failed with chunk=32 only on the quarter-turn geometry.
    for i in (30, 32):
        phase = i * (2.0 * math.pi / params.num_strands_per_dir)
        strand = _build_braid_strand(samples, params, phase, -1)
        assert strand.Volume() > 1.0
        assert len(strand.Solids()) == 1


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


# ---------------------------------------------------------------------------
# Streaming assembly (bounded-memory build)
# ---------------------------------------------------------------------------

def test_assemble_brep_streaming_single_solid_and_volume() -> None:
    """Batched streaming fuse yields one solid with the same volume as a one-shot fuse."""
    import cadquery as cq
    from cadquery.occ_impl.shapes import Compound

    from led_knots.core.fuse_utils import fuse_part_solids
    from led_knots.core.tube_models.braided_rope import _assemble_brep

    core = cq.Workplane("XY").box(12, 2, 2).val()
    strands = [cq.Workplane("XY").move(x, 0).box(2, 2, 2).val() for x in (-4, -2, 0, 2, 4)]

    streamed = _assemble_brep(
        core,
        iter(strands),
        total_strands=len(strands),
        clip_solid=None,
        batch_size=2,
        name="stream",
    )
    assert len(streamed.Solids()) == 1

    ref = fuse_part_solids(Compound.makeCompound([core, *strands]), name="ref")
    assert streamed.Volume() == pytest.approx(ref.Volume(), rel=1e-3)


def test_assemble_brep_counts_mismatch_raises() -> None:
    import cadquery as cq

    from led_knots.core.tube_models.braided_rope import _assemble_brep

    core = cq.Workplane("XY").box(12, 2, 2).val()
    strands = [cq.Workplane("XY").move(x, 0).box(2, 2, 2).val() for x in (-2, 0, 2)]
    with pytest.raises(RuntimeError, match="expected 5 braid strands, built 3"):
        _assemble_brep(
            core,
            iter(strands),
            total_strands=5,
            clip_solid=None,
            batch_size=2,
            name="bad",
        )


# ---------------------------------------------------------------------------
# Mesh fuse path: pipeline guards
# ---------------------------------------------------------------------------

def test_braid_mesh_fuse_selected_flag() -> None:
    from led_knots.core.utils import _braid_mesh_fuse_selected

    def mk(face_type, fuse_method):
        rope = {"fuse_method": fuse_method} if fuse_method is not None else None
        return SimpleNamespace(
            tube_settings=SimpleNamespace(face_type=face_type, braided_rope=rope)
        )

    assert _braid_mesh_fuse_selected(mk("braided_rope_tube", "mesh"))
    assert _braid_mesh_fuse_selected(mk("braided_rope", "mesh"))
    assert not _braid_mesh_fuse_selected(mk("braided_rope_tube", "brep"))
    assert not _braid_mesh_fuse_selected(mk("braided_rope_tube", None))
    assert not _braid_mesh_fuse_selected(mk("solid_circle", None))


def test_partartifacts_mesh_exports_and_rejects_step(tmp_path) -> None:
    import trimesh

    from led_knots.core.render_pipeline import PartArtifacts
    from led_knots.core.render_planner import ExportJob

    mesh = trimesh.creation.box(extents=(2.0, 2.0, 2.0))
    cfg = SimpleNamespace(
        rendering=SimpleNamespace(tolerance=0.1, angular_tolerance=0.1),
        render_stats=None,
    )
    ctx = PartArtifacts(mesh, cfg)
    assert ctx.is_mesh

    stl = tmp_path / "m.stl"
    ctx.ensure_stl_at(stl, stl_ascii=False)
    assert stl.exists() and stl.stat().st_size > 0

    glb = ctx.ensure_glb_bytes()
    assert isinstance(glb, (bytes, bytearray)) and len(glb) > 0

    step_job = ExportJob(
        format="step",
        enabled=True,
        filename_template="{name}.step",
        resolved_path=tmp_path / "m.step",
        settings={},
    )
    with pytest.raises(RuntimeError, match="STEP export requires a B-rep solid"):
        ctx.execute_job(step_job)


# ---------------------------------------------------------------------------
# Full build (slow): both fuse methods produce equivalent geometry
# ---------------------------------------------------------------------------

def _debug_build_config(fuse_method: str, n: int):
    import sys

    from led_knots.core.config import Config

    old_argv = sys.argv
    sys.argv = ["render-knot", "knot_configs/test_short_rod_led_tube_braided_debug.yaml"]
    try:
        cfg = Config()
    finally:
        sys.argv = old_argv
    cfg.tube_settings.braided_rope["fuse_method"] = fuse_method
    cfg.tube_settings.braided_rope["num_strands_per_dir"] = n
    return cfg


def _build_with_model(cfg):
    from led_knots.core.tube_models import get_tube_model

    model = get_tube_model(cfg.tube_settings.face_type)
    path = spline([(0, 0, 0), (0, 0, cfg.output_bounds.height)])
    return model.build(path=path, aux=None, config=cfg, face_kwargs={})


@pytest.mark.slow
def test_build_brep_returns_single_solid() -> None:
    cfg = _debug_build_config("brep", n=4)
    result = _build_with_model(cfg)
    solids = result.Solids() if hasattr(result, "Solids") else [result]
    assert len(solids) == 1


@pytest.mark.slow
def test_build_mesh_watertight_and_matches_brep_volume() -> None:
    import trimesh

    brep = _build_with_model(_debug_build_config("brep", n=4))
    mesh = _build_with_model(_debug_build_config("mesh", n=4))
    assert isinstance(mesh, trimesh.Trimesh)
    assert mesh.is_watertight
    from led_knots.core.tube_models.braided_rope import _mesh_volume_bodies

    assert _mesh_volume_bodies(mesh) == 1
    assert mesh.volume == pytest.approx(brep.Volume(), rel=0.05)


# ---------------------------------------------------------------------------
# Curved-path mesh memory (map-reduce + face budget)
# ---------------------------------------------------------------------------

def test_quarter_turn_strand_face_budget() -> None:
    """Curved quarter_turn strands auto-coarsen under mesh_max_strand_faces."""
    import sys

    from led_knots.core.config import Config
    from led_knots.core.path_frames import sample_path_frames
    from led_knots.core.tube_models.braided_rope import (
        _base_face_type,
        _build_braid_strand,
        _params_from_config,
        _pick_mesh_tolerances,
        _reference_strand_face_count,
        _sample_strand_centerline,
        _StrandTimings,
        _DEFAULT_MESH_MAX_STRAND_FACES,
        _DEFAULT_MESH_TOLERANCE,
        _DEFAULT_MESH_TOLERANCE_MAX,
        _DEFAULT_MESH_ANGULAR_TOLERANCE,
        _MESH_LOFT_SAMPLES_CAP,
    )

    sys.argv = ["render-knot", "knot_configs/quarter_turn_braided.yaml"]
    cfg = Config()
    path = spline(
        [(0, 0, 0), (0, cfg.output_bounds.height, cfg.output_bounds.height)],
        tgts=[(0, 0, 1), (0, 1, 0)],
    )
    base = _base_face_type(cfg)
    params = _params_from_config(cfg, base_face_type=base)
    plen = path.Length()
    loft = min(
        max(
            240,
            min(
                1500,
                math.ceil(params.samples_per_period * params.N * plen / params.pitch),
            ),
        ),
        _MESH_LOFT_SAMPLES_CAP,
    )
    frames = sample_path_frames(path, max(120, min(400, int(plen / 1.0))))
    samples = _sample_strand_centerline(frames, plen, params, loft)

    def _reference_strand():
        return _build_braid_strand(samples, params, 0.0, -1, _StrandTimings())

    tol, ang, faces = _pick_mesh_tolerances(
        _reference_strand,
        tolerance=_DEFAULT_MESH_TOLERANCE,
        angular_tolerance=_DEFAULT_MESH_ANGULAR_TOLERANCE,
        tolerance_max=_DEFAULT_MESH_TOLERANCE_MAX,
        max_strand_faces=_DEFAULT_MESH_MAX_STRAND_FACES,
        name="quarter_turn",
    )
    assert faces <= _DEFAULT_MESH_MAX_STRAND_FACES
    assert tol > _DEFAULT_MESH_TOLERANCE
    ref = _reference_strand()
    assert (
        _reference_strand_face_count(ref, tolerance=tol, angular_tolerance=ang)
        <= _DEFAULT_MESH_MAX_STRAND_FACES
    )


def test_mesh_map_reduce_watertight() -> None:
    """Map-reduce mesh union of overlapping boxes yields one watertight volume body."""
    import trimesh

    from led_knots.core.tube_models.braided_rope import (
        _assemble_mesh,
        _assert_single_volume_body,
        _mesh_map_reduce_final,
        _mesh_map_reduce_one_round,
    )

    boxes = [
        trimesh.creation.box(extents=(2.0, 2.0, 2.0)).apply_translation((x, 0, 0))
        for x in (0, 1, 2, 3)
    ]
    reduced = _mesh_map_reduce_final(boxes, name="boxes")
    assert reduced.is_watertight
    _assert_single_volume_body(reduced, name="boxes")

    # one round halves four chunks to two
    four = list(boxes)
    one_round = _mesh_map_reduce_one_round(four, name="boxes")
    assert len(one_round) == 2


def test_mesh_map_reduce_peak_chunks_bounded() -> None:
    """Chunk list high-water mark stays within 2 * mesh_batch_size during streaming."""
    import trimesh

    from led_knots.core.tube_models.braided_rope import (
        _MESH_MAX_CHUNKS_FACTOR,
        _mesh_map_reduce_one_round,
    )

    mesh_batch_size = 2
    max_chunks = max(2, _MESH_MAX_CHUNKS_FACTOR * mesh_batch_size)
    chunks = [trimesh.creation.box(extents=(2.0, 2.0, 2.0))]
    peak = len(chunks)
    for i in range(12):
        chunks.append(
            trimesh.creation.box(extents=(1.0, 1.0, 1.0)).apply_translation((i, 0, 0))
        )
        while len(chunks) > max_chunks:
            chunks = _mesh_map_reduce_one_round(chunks, name="bounded")
        peak = max(peak, len(chunks))
    assert peak <= max_chunks
    assert max_chunks == 4
