"""
Unit tests for ``led_knots.optimize.drain_holes``.
"""

from __future__ import annotations

import math
import os
import tempfile

import cadquery as cq
import numpy as np
import pytest
import trimesh

from led_knots.optimize.analysis import Cavity
from led_knots.optimize.drain_holes import drill_drain_holes
from led_knots.optimize.settings import DrainHoleSettings


def _to_trimesh(solid) -> trimesh.Trimesh:
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
        tmp = f.name
    try:
        cq.exporters.export(
            solid, tmp, tolerance=0.05, angularTolerance=0.3, opt={"ascii": False}
        )
        return trimesh.load(tmp)
    finally:
        os.unlink(tmp)


def _sealed_cavity_solid() -> cq.Solid:
    """40-cube minus inner 20-cube — fully enclosed cavity."""
    outer = cq.Solid.makeBox(40, 40, 40, cq.Vector(-20, -20, -20))
    inner = cq.Solid.makeBox(20, 20, 20, cq.Vector(-10, -10, -10))
    return outer.cut(inner)


def test_disabled_returns_part_unchanged() -> None:
    solid = _sealed_cavity_solid()
    cav = Cavity(
        volume_mm3=8000.0,
        centroid=(0.0, 0.0, 0.0),
        bounds=((-10, -10, -10), (10, 10, 10)),
        is_trapped=True,
    )
    settings = DrainHoleSettings({"enabled": False})
    out, drilled = drill_drain_holes(solid, [cav], settings)
    assert drilled == []
    # Same object reference (no boolean cut performed)
    assert out is solid


def test_drill_through_sealed_cavity() -> None:
    """Drilling through a sealed cavity should reduce the solid's volume
    by approximately one cylinder's worth of material (top wall + bottom
    wall, since the cylinder also passes through the cavity which has
    no material to remove)."""
    solid = _sealed_cavity_solid()
    cav = Cavity(
        volume_mm3=8000.0,
        centroid=(0.0, 0.0, 0.0),
        bounds=((-10, -10, -10), (10, 10, 10)),
        is_trapped=True,
    )
    diameter = 2.0
    settings = DrainHoleSettings(
        {"enabled": True, "diameter_mm": diameter, "min_cavity_volume_mm3": 100.0, "margin_mm": 5.0}
    )
    out, drilled = drill_drain_holes(solid, [cav], settings)
    assert len(drilled) == 1
    expected_removed = math.pi * (diameter / 2.0) ** 2 * 20.0  # 10mm top wall + 10mm bottom
    assert (solid.Volume() - out.Volume()) == pytest.approx(expected_removed, rel=0.05)


def test_skip_below_min_volume() -> None:
    """Cavities below ``min_cavity_volume_mm3`` are not drilled."""
    solid = _sealed_cavity_solid()
    cav_small = Cavity(
        volume_mm3=50.0,
        centroid=(0.0, 0.0, 0.0),
        bounds=((-10, -10, -10), (10, 10, 10)),
        is_trapped=True,
    )
    settings = DrainHoleSettings(
        {"enabled": True, "diameter_mm": 2.0, "min_cavity_volume_mm3": 100.0}
    )
    out, drilled = drill_drain_holes(solid, [cav_small], settings)
    assert drilled == []


def test_drilled_mesh_remains_watertight() -> None:
    """A clean CadQuery boolean cut should preserve watertightness —
    important so the resulting STL slices correctly."""
    solid = _sealed_cavity_solid()
    cav = Cavity(
        volume_mm3=8000.0,
        centroid=(0.0, 0.0, 0.0),
        bounds=((-10, -10, -10), (10, 10, 10)),
        is_trapped=True,
    )
    settings = DrainHoleSettings({"enabled": True, "diameter_mm": 2.0, "margin_mm": 5.0})
    out, _ = drill_drain_holes(solid, [cav], settings)
    mesh = _to_trimesh(out)
    assert mesh.is_watertight, "drilled mesh lost watertightness"


def test_drill_creates_tunnel() -> None:
    """The drilled tunnel should be open all the way through. Verified
    by checking the cavity centroid is reachable from outside via a
    short downward ray (origin just above the part, axis straight down):
    the ray should NOT hit any geometry until it exits the part —
    because the tunnel is now a clear passage to the cavity.

    Pre-drill, the same ray would hit the outer top wall."""
    solid = _sealed_cavity_solid()
    cav = Cavity(
        volume_mm3=8000.0,
        centroid=(0.0, 0.0, 0.0),
        bounds=((-10, -10, -10), (10, 10, 10)),
        is_trapped=True,
    )
    settings = DrainHoleSettings({"enabled": True, "diameter_mm": 4.0, "margin_mm": 5.0})
    out, _ = drill_drain_holes(solid, [cav], settings)
    mesh = _to_trimesh(out)
    # Centerline ray — passes straight down the tunnel. Hits 0 surfaces.
    origin_inside = np.array([[0.0, 0.0, 30.0]])
    direction = np.array([[0.0, 0.0, -1.0]])
    locs_inside, _, _ = mesh.ray.intersects_location(origin_inside, direction)
    # Off-tunnel ray — clearly outside the 2-mm radius tunnel. Hits 4 walls.
    origin_outside = np.array([[5.0, 0.0, 30.0]])
    locs_outside, _, _ = mesh.ray.intersects_location(origin_outside, direction)
    assert len(locs_inside) == 0, (
        f"centerline ray through the tunnel should hit nothing, got {len(locs_inside)}"
    )
    assert len(locs_outside) >= 4, (
        f"off-tunnel ray should hit ≥4 walls (outer top, cavity top, cavity bottom, "
        f"outer bottom), got {len(locs_outside)}"
    )
