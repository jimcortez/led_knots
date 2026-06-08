"""
Unit tests for ``led_knots.optimize.face_tagging``.

Builds a short vertical rod with the led_circle_tube cross-section via the
project's own pipeline and checks that connector-flank faces are tagged with
the expected direction signature.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SHORT_ROD_CONFIG = _PROJECT_ROOT / "knot_configs" / "test_short_rod_led_tube.yaml"


@pytest.fixture(scope="module")
def rod_mesh_and_path():
    """Build a short vertical rod using knot_configs/test_short_rod_led_tube.yaml."""
    from cadquery.func import spline

    from led_knots.core.config import Config
    from led_knots.core.utils import build_tube_from_path, parse_render_args
    from led_knots.optimize import _to_trimesh

    sys.argv = ["test", str(_SHORT_ROD_CONFIG)]
    config = Config(args=parse_render_args())

    path = spline([(0, 0, 0), (0, 0, config.output_bounds.height)])
    solid = build_tube_from_path(path, config, aux=None, face_kwargs={"rotation_z": 0.0})
    mesh = _to_trimesh(solid)
    return mesh, path, config.tube_settings


def test_tagger_tags_some_connectors(rod_mesh_and_path):
    from led_knots.optimize.face_tagging import tag_connector_faces

    mesh, path, ts = rod_mesh_and_path
    tags = tag_connector_faces(mesh, path, ts)
    assert tags.n_connector_faces > 0, f"no connectors tagged on led_circle_tube rod; note: {tags.note!r}"
    tagged_area = float(mesh.area_faces[tags.connector_mask].sum())
    fraction = tagged_area / float(mesh.area)
    assert 0.01 < fraction < 0.25, (
        f"tagged fraction {fraction:.3f} outside expected band [0.01, 0.25]"
    )


def test_tagger_returns_empty_for_solid_circle(rod_mesh_and_path):
    """solid_circle has no connectors — the tagger must return an empty
    mask + an explanatory note instead of erroring."""
    from led_knots.optimize.face_tagging import tag_connector_faces

    class FakeTubeSettings:
        face_type = "solid_circle"
        outer_radius = 15.0
        wall_thickness = 1.0
        inner_tube_diameter = None
        inner_tube_wall_thickness = None
        rect_inner_y = 0.0
        oval_wall_thickness = 0.0

    mesh, path, _ = rod_mesh_and_path
    tags = tag_connector_faces(mesh, path, FakeTubeSettings())
    assert tags.n_connector_faces == 0
    assert tags.note != ""


def test_tagger_normal_signature_is_horizontal_for_flat_rotation_z_zero(rod_mesh_and_path):
    """For rotation_z=0 on a vertical rod the connector flank normals must
    lie in the horizontal plane (mean |n_z| ≈ 0)."""
    from led_knots.optimize.face_tagging import tag_connector_faces

    mesh, path, ts = rod_mesh_and_path
    tags = tag_connector_faces(mesh, path, ts)
    if tags.n_connector_faces == 0:
        pytest.skip("no connector faces tagged; tested in test_tagger_tags_some_connectors")
    n = mesh.face_normals[tags.connector_mask]
    a = mesh.area_faces[tags.connector_mask]
    mean_abs_nz = float(np.average(np.abs(n[:, 2]), weights=a))
    assert mean_abs_nz < 0.3, (
        f"expected horizontal connector flank normals (|n_z| small), got {mean_abs_nz:.3f}"
    )
