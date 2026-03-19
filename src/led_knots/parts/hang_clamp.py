from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Tuple

import cadquery as cq
import numpy as np
from cadquery.func import *  # match project functional API style

from led_knots.core import get_config, render_part

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TubeClampParts:
    half_with_hole: cq.Solid
    half_plain: cq.Solid

    def to_assembly(self, name: str = "Hang Clamp") -> cq.Assembly:
        """
        Return a CadQuery Assembly of the assembled clamp halves.

        Parts are placed in their native positions (no separation), so the assembly
        shows the clamp connected as it would be when glued.
        """
        assy = cq.Assembly(name=name)
        assy = assy.add(self.half_with_hole, name="clamp_half_a")
        assy = assy.add(self.half_plain, name="clamp_half_b")
        return assy


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n < 1e-9:
        return np.array([0.0, 0.0, 1.0], dtype=float)
    return v / n


def location_from_point_tangent(
    point_xyz: Tuple[float, float, float],
    tangent_xyz: Tuple[float, float, float],
) -> cq.Location:
    """
    Build a CadQuery Location such that local +Z aligns to the tangent.

    Used when placing the clamp along a knot path later.
    """
    p = cq.Vector(*[float(x) for x in point_xyz])
    t = _unit(np.array(tangent_xyz, dtype=float))
    normal = cq.Vector(float(t[0]), float(t[1]), float(t[2]))

    world_x = np.array([1.0, 0.0, 0.0], dtype=float)
    if abs(float(np.dot(world_x, t))) > 0.9:
        world_x = np.array([0.0, 1.0, 0.0], dtype=float)
    x_dir = _unit(np.cross(world_x, t))
    xDir = cq.Vector(float(x_dir[0]), float(x_dir[1]), float(x_dir[2]))

    pl = cq.Plane(origin=p, normal=normal, xDir=xDir)
    return cq.Location(pl)


def build_tube_clamp_parts(config) -> TubeClampParts:
    """
    Build a two-part circular hanging clamp using `config.tube_settings` and `config.clamp`.

    Local coordinates:
    - Clamp axis is +Z.
    - Split plane is Y=0 (halves are +Y and -Y).
    """
    tube_outer_radius_mm = float(config.tube_settings.outer_radius)
    c = config.clamp

    clearance_diameter_mm = float(c.clearance_diameter_mm)
    inner_radius = tube_outer_radius_mm + 0.5 * clearance_diameter_mm
    outer_radius = inner_radius + float(c.wall_thickness_mm)
    L = float(c.length_mm)

    # Base clamp ring (full) using functional API.
    ring_face = face(wire(circle(outer_radius)), wire(circle(inner_radius)))
    ring = extrude(ring_face, (0, 0, L)).moved(Location((0, 0, -L / 2.0)))

    # Split into halves using a large box as half-space.
    big = outer_radius * 4.0 + L
    # `box(w,l,h)` is centered in X/Y but starts at Z=0, so we move it down by h/2
    # to center it in Z. For a true half-space split at Y=0:
    # - positive cutter spans Y in [0, big]
    # - negative cutter spans Y in [-big, 0]
    cutter_pos = box(big, big, big).moved(Location((0, +big / 2.0, -big / 2.0)))
    cutter_neg = box(big, big, big).moved(Location((0, -big / 2.0, -big / 2.0)))
    # Base halves (pure clamshell split at Y=0).
    half_pos = intersect(ring, cutter_pos)  # nominally Y >= 0
    half_neg = intersect(ring, cutter_neg)  # nominally Y <= 0

    # Continuous stepped lap joint (rabbet) along the Y=0 seam.
    #
    # IMPORTANT: A real lap joint must cross the nominal split plane so you get overlap.
    # That means we intentionally extend the +Y half slightly into Y<0, and cut the
    # complementary volume out of the -Y half. This avoids the “flat seam” outcome
    # you get if everything is clipped strictly to Y>=0 / Y<=0.
    #
    # - half_pos gets a protruding step (male) occupying Y in [-lap_depth, 0]
    # - half_neg gets a matching recess (female) removed from Y in [-lap_depth, 0]
    lap_depth = float(max(0.0, c.lap_depth_mm))  # overlap depth across seam normal (Y)
    lap_step_h = float(max(0.1, getattr(c, "lap_step_height_mm", 1.5)))  # radial (X)
    lap_clear = float(max(0.0, c.lap_clearance_mm))

    # Clamp step height so we don't exceed wall thickness.
    lap_step_h = min(lap_step_h, max(0.2, outer_radius - inner_radius - 0.2))

    # Male step volumes: rails near the OUTER wall on BOTH seam edges (+X and -X).
    # Spans the full clamp length in Z, and occupies Y in [-lap_depth, 0].
    male_pos = box(lap_step_h, lap_depth, L).moved(
        Location((+outer_radius - lap_step_h / 2.0, -lap_depth / 2.0, -L / 2.0))
    )
    male_neg = box(lap_step_h, lap_depth, L).moved(
        Location((-outer_radius + lap_step_h / 2.0, -lap_depth / 2.0, -L / 2.0))
    )
    male = intersect(ring, fuse(male_pos, male_neg))
    half_pos = fuse(half_pos, male)

    # Female recess volume (bigger): remove from the -Y half (same Y band),
    # enlarged for clearance (and any adhesive gap is handled in groove).
    recess_x = lap_step_h + lap_clear
    recess_y = lap_depth + lap_clear
    recess_pos = box(recess_x, recess_y, L + 0.5).moved(
        Location((+outer_radius - recess_x / 2.0, -(lap_depth / 2.0) - (lap_clear / 2.0), -(L + 0.5) / 2.0))
    )
    recess_neg = box(recess_x, recess_y, L + 0.5).moved(
        Location((-outer_radius + recess_x / 2.0, -(lap_depth / 2.0) - (lap_clear / 2.0), -(L + 0.5) / 2.0))
    )
    recess = intersect(ring, fuse(recess_pos, recess_neg))
    half_neg = cut(half_neg, recess)

    # Seam registration (tongue-and-groove) + explicit adhesive gap.
    # Seam plane is Y=0, so the rail spans Z and sits near outer radius.
    adhesive_gap = float(getattr(c, "adhesive_gap_mm", 0.10))
    reg_h = float(getattr(c, "reg_lip_height_mm", 0.8))  # radial (X)
    reg_w = float(getattr(c, "reg_lip_width_mm", 1.2))   # across seam normal (Y)
    reg_clear = float(getattr(c, "reg_clearance_mm", 0.08))

    # Male tongue on +Y half (nested within the lap area).
    tongue_x = max(0.1, reg_h)
    tongue_y = max(0.1, reg_w)
    tongue_pos = box(tongue_x, tongue_y, L).moved(
        Location((+outer_radius - lap_step_h + tongue_x / 2.0, -tongue_y / 2.0, -L / 2.0))
    )
    tongue_neg = box(tongue_x, tongue_y, L).moved(
        Location((-outer_radius + lap_step_h - tongue_x / 2.0, -tongue_y / 2.0, -L / 2.0))
    )
    tongue = intersect(ring, fuse(tongue_pos, tongue_neg))
    half_pos = fuse(half_pos, tongue)

    # Female groove on -Y half (clearance + adhesive gap).
    groove_x = max(0.1, reg_h + adhesive_gap)
    groove_y = max(0.1, reg_w + reg_clear + 2.0 * adhesive_gap)
    groove_pos = box(groove_x, groove_y, L + 0.5).moved(
        Location((+outer_radius - lap_step_h + groove_x / 2.0, -groove_y / 2.0, -(L + 0.5) / 2.0))
    )
    groove_neg = box(groove_x, groove_y, L + 0.5).moved(
        Location((-outer_radius + lap_step_h - groove_x / 2.0, -groove_y / 2.0, -(L + 0.5) / 2.0))
    )
    groove = intersect(ring, fuse(groove_pos, groove_neg))
    half_neg = cut(half_neg, groove)

    # Optional relief pockets: small cutouts inside the groove to let glue escape.
    if bool(getattr(c, "relief_enabled", True)):
        relief_d = float(getattr(c, "relief_depth_mm", 0.3))
        relief_w = float(getattr(c, "relief_width_mm", 0.5))
        relief_d = max(0.1, min(relief_d, groove_x))
        relief_w = max(0.1, min(relief_w, groove_y))
        pocket_x = relief_d
        pocket_y = relief_w
        pocket_z = max(0.5, min(2.0, L * 0.25))
        for zc in (-L * 0.25, 0.0, L * 0.25):
            pocket_pos = box(pocket_x, pocket_y, pocket_z).moved(
                Location((+outer_radius - lap_step_h + pocket_x / 2.0, -groove_y / 2.0, zc - pocket_z / 2.0))
            )
            pocket_neg = box(pocket_x, pocket_y, pocket_z).moved(
                Location((-outer_radius + lap_step_h - pocket_x / 2.0, -groove_y / 2.0, zc - pocket_z / 2.0))
            )
            pocket = intersect(ring, fuse(pocket_pos, pocket_neg))
            half_neg = cut(half_neg, pocket)
    # (Previous end-rib lap joint removed; seam lap is now continuous.)

    # Wire hole + tapered ring on the +Y half.
    hole_r = 0.5 * float(c.wire_hole_diameter_mm)
    if hole_r > 0:
        hole_len = outer_radius + float(c.wire_ring_height_mm) + 2.0
        xz_plane = Plane(origin=(0, 0, 0), normal=(0, 1, 0), xDir=(1, 0, 0))
        hole_edge = circle(hole_r).moved(Location(xz_plane))
        hole_face = face(wire(hole_edge))
        hole_cyl = extrude(hole_face, (0, hole_len, 0))
        half_pos = cut(half_pos, hole_cyl)

        ring_h = float(c.wire_ring_height_mm)
        base_t = float(c.wire_ring_base_thickness_mm)
        top_t = float(c.wire_ring_top_thickness_mm)
        if ring_h > 1e-6 and base_t > 0 and top_t > 0:
            # Ensure the collar *intersects* the clamp body (not just tangent),
            # otherwise the fuse can result in a visually detached ring.
            collar_overlap = min(1.0, max(0.2, float(c.wall_thickness_mm) * 0.4))
            pl0 = Plane(
                origin=(0, outer_radius - collar_overlap, 0),
                normal=(0, 1, 0),
                xDir=(1, 0, 0),
            )
            pl1 = Plane(origin=(0, outer_radius + ring_h, 0), normal=(0, 1, 0), xDir=(1, 0, 0))
            outer0 = wire(circle(hole_r + base_t).moved(Location(pl0)))
            inner0 = wire(circle(hole_r).moved(Location(pl0)))
            outer1 = wire(circle(hole_r + top_t).moved(Location(pl1)))
            inner1 = wire(circle(hole_r).moved(Location(pl1)))
            f0 = face(outer0, inner0)
            f1 = face(outer1, inner1)
            collar = loft([f0, f1])
            half_pos = fuse(half_pos, collar)

    # Final cleanup: reduce residual edges/vertices from booleans.
    # This helps downstream exporting/slicing and makes the part easier to inspect.
    half_pos = clean(half_pos)
    half_neg = clean(half_neg)

    return TubeClampParts(half_with_hole=half_pos, half_plain=half_neg)


def main() -> None:
    config = get_config(name="Hang Clamp", description="Create and render a 2-part hang clamp")

    parts = build_tube_clamp_parts(config)
    
    assembled = parts.to_assembly()
    render_part(assembled, config)


if __name__ == "__main__":
    main()

