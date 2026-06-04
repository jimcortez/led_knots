"""
Unit tests for ``led_knots.optimize.face_tagging``.

Builds a synthetic swept LED-tube via the project's own pipeline and
checks that connector-flank faces are tagged with the expected
direction signature.
"""

from __future__ import annotations

import math

import numpy as np
import pytest


@pytest.fixture(scope="module")
def ring_mesh_and_path():
    """Build a small flat ring with led_circle_tube cross-section.

    Uses the project's actual sweep path and tessellation so the fixture
    catches any drift between the real flow and the tagger heuristic.
    """
    import sys
    sys.argv = ["test"]  # parse_args runs with no flags
    from cadquery.func import spline
    from pyknotid.spacecurves import Knot
    from led_knots.core import scale_pyknot_points
    from led_knots.core.config import Config
    from led_knots.core.utils import build_tube_from_path
    from led_knots.optimize import _to_trimesh

    config = Config(name="Ring (test)")
    n = 100
    data = np.zeros((n, 3), dtype=np.float64)
    ts = np.linspace(0, 2 * np.pi, n)
    data[:, 0] = 3 * np.sin(ts)
    data[:, 1] = 3 * np.cos(ts)
    points = scale_pyknot_points(
        Knot(data).points,
        width=config.output_bounds.width,
        height=config.output_bounds.width,
        length=config.output_bounds.height,
        padding=config.tube_settings.outer_radius,
        preserve_aspect_ratio=False,
    )
    path = spline(points[:-10])
    # Use the user's manual workaround (rotation_z=0 → connectors vertical)
    solid = build_tube_from_path(path, config, aux=None, face_kwargs={"rotation_z": 0.0})
    mesh = _to_trimesh(solid)
    return mesh, path, config.tube_settings


def test_tagger_tags_some_connectors(ring_mesh_and_path):
    from led_knots.optimize.face_tagging import tag_connector_faces

    mesh, path, ts = ring_mesh_and_path
    tags = tag_connector_faces(mesh, path, ts)
    assert tags.n_connector_faces > 0, f"no connectors tagged on a led_circle_tube ring; note: {tags.note!r}"
    # Sanity: tagged area should be a non-trivial fraction (>1%) of the
    # full mesh area but not most of it (<25%).
    tagged_area = float(mesh.area_faces[tags.connector_mask].sum())
    fraction = tagged_area / float(mesh.area)
    assert 0.01 < fraction < 0.25, (
        f"tagged fraction {fraction:.3f} outside expected band [0.01, 0.25]"
    )


def test_tagger_returns_empty_for_solid_circle(ring_mesh_and_path):
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

    mesh, path, _ = ring_mesh_and_path
    tags = tag_connector_faces(mesh, path, FakeTubeSettings())
    assert tags.n_connector_faces == 0
    assert tags.note != ""


def test_tagger_normal_signature_is_horizontal_for_flat_rotation_z_zero(ring_mesh_and_path):
    """For rotation_z=0 (the ring.py setting) the connector flank
    normals must be in the horizontal plane (mean |n_z| ≈ 0). This
    locks down the geometric invariant the bonus relies on."""
    from led_knots.optimize.face_tagging import tag_connector_faces

    mesh, path, ts = ring_mesh_and_path
    tags = tag_connector_faces(mesh, path, ts)
    if tags.n_connector_faces == 0:
        pytest.skip("no connector faces tagged; tested in test_tagger_tags_some_connectors")
    n = mesh.face_normals[tags.connector_mask]
    a = mesh.area_faces[tags.connector_mask]
    mean_abs_nz = float(np.average(np.abs(n[:, 2]), weights=a))
    # For a flat ring with rotation_z=0, the connectors are along Y of
    # cross-section, which after sweep maps to ~world Z. Their flanks
    # face ±X of cross-section (horizontal). So mean |n_z| should be
    # small (<0.3 leaves headroom for tessellation jitter).
    assert mean_abs_nz < 0.3, (
        f"expected horizontal connector flank normals (|n_z| small), got {mean_abs_nz:.3f}"
    )
