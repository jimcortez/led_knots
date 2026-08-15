from __future__ import annotations

import logging
import math
import os
import tempfile
from dataclasses import dataclass
from typing import Iterable, List, Tuple

import cadquery as cq
import trimesh
from cadquery.func import *  # match project functional API style

from led_knots.core import render_part
from led_knots.core.config import Config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FingerSensorHolderParams:
    """Parametric dimensions for the finger pulse-sensor holder (millimetres)."""

    # --- Supplied main dimensions ---
    holder_width: float = 30.00
    holder_length: float = 67.00
    base_thickness: float = 4.48

    wall_thickness: float = 2.29
    # Wall heights are total heights from the print bed (base included).
    wall_full_height: float = 20.70
    rear_wall_low_height: float = 8.45
    rear_transition_length: float = 23.57
    front_transition_length: float = 4.90

    hinge_axis_from_rear: float = 22.70
    hinge_axis_height_above_base: float = 12
    hinge_rod_diameter: float = 3.17
    hinge_outer_diameter: float = 5.02

    pedestal_front_offset: float = 9.50
    pedestal_width: float = 17.00
    pedestal_front_height: float = 10.00

    sensor_pcb_diameter: float = 15.80
    sensor_max_thickness: float = 3.60

    sensor_pocket_diameter: float = 17.20
    sensor_pocket_depth: float = 3.70
    sensor_exposed_opening_diameter: float = 15.00

    cable_channel_width: float = 4.50
    cable_channel_depth: float = 2.50

    general_fillet_radius: float = 1.00

    # --- Assumption parameters (prototype validation recommended) ---
    front_transition_radius: float = 2.00
    rear_transition_radius: float = 2.50
    pedestal_length: float = 32.00
    pedestal_rear_height_above_base: float = 6.00

    # Wider than the pedestal so the trough cuts away its side walls entirely.
    finger_trough_width: float = 19.00
    finger_trough_depth: float = 3.50
    finger_trough_length: float = 28.00
    finger_stop_radius: float = 8.00
    finger_trough_front_blend_length: float = 5.00

    sensor_center_y: float = 33.50
    sensor_face_raise_mm: float = 0.25

    hinge_rod_clearance_mm: float = 0.15
    retention_plate_clearance_mm: float = 0.25
    retention_plate_thickness_mm: float = 1.50
    retention_tab_count: int = 3
    retention_tab_width_mm: float = 2.00
    retention_tab_depth_mm: float = 0.80

    cable_exit_y: float = 62.00
    strain_relief_pocket_diameter: float = 6.00
    strain_relief_pocket_depth: float = 1.50

    @classmethod
    def from_config(cls, config: Config) -> FingerSensorHolderParams:
        data = getattr(config, "finger_sensor_holder", None)
        if data is None:
            return cls()
        kwargs = {}
        for field_name in cls.__dataclass_fields__:
            if hasattr(data, field_name):
                kwargs[field_name] = getattr(data, field_name)
        return cls(**kwargs)

    @property
    def pedestal_left_x(self) -> float:
        return 0.5 * (self.holder_width - self.pedestal_width)

    @property
    def pedestal_right_x(self) -> float:
        return self.pedestal_left_x + self.pedestal_width

    @property
    def hinge_axis_y(self) -> float:
        return self.holder_length - self.hinge_axis_from_rear

    @property
    def hinge_axis_z(self) -> float:
        return self.base_thickness + self.hinge_axis_height_above_base

    @property
    def rear_full_height_y(self) -> float:
        return self.holder_length - self.rear_transition_length

    @property
    def lateral_center_x(self) -> float:
        return 0.5 * self.holder_width


@dataclass(frozen=True)
class FingerSensorHolderParts:
    holder: cq.Solid
    retention_plate: cq.Solid

    def to_assembly(self, name: str = "Finger Sensor Holder") -> cq.Assembly:
        assy = cq.Assembly(name=name)
        assy = assy.add(self.holder, name="holder")
        assy = assy.add(self.retention_plate, name="retention_plate")
        return assy


def _corner_box(x0: float, y0: float, z0: float, dx: float, dy: float, dz: float) -> cq.Solid:
    if dx <= 0 or dy <= 0 or dz <= 0:
        raise ValueError("Box extents must be positive.")
    return box(dx, dy, dz).moved(Location((x0 + 0.5 * dx, y0 + 0.5 * dy, z0)))


def _wall_top_z(y: float, p: FingerSensorHolderParams) -> float:
    """Return absolute Z of the exterior wall top at longitudinal coordinate Y."""
    bz = p.base_thickness
    # Wall heights are totals from Z=0, so the base thickness is part of the
    # wall height rather than added beneath it.
    full_z = p.wall_full_height
    rear_z = p.rear_wall_low_height
    y_ff = p.front_transition_length
    y_rf = p.rear_full_height_y
    r_f = p.front_transition_radius
    r_r = p.rear_transition_radius

    if y <= 0.0:
        return bz
    if y < y_ff - r_f:
        t = y / max(y_ff - r_f, 1e-9)
        return bz + t * (full_z - r_f - bz)
    if y < y_ff:
        ang = math.pi - ((y - (y_ff - r_f)) / max(r_f, 1e-9)) * (0.5 * math.pi)
        cy = y_ff - r_f
        cz = full_z - r_f
        return cz + r_f * math.sin(ang)
    if y <= y_rf:
        return full_z
    if y < y_rf + r_r:
        ang = 0.5 * math.pi - ((y - y_rf) / max(r_r, 1e-9)) * (0.5 * math.pi)
        cy = y_rf + r_r
        cz = full_z - r_r
        return cz + r_r * math.sin(ang)
    if y < p.holder_length:
        t = (y - (y_rf + r_r)) / max(p.holder_length - (y_rf + r_r), 1e-9)
        z_start = full_z - r_r
        return z_start + t * (rear_z - z_start)
    return rear_z


def _wall_profile_points(p: FingerSensorHolderParams, samples: int = 80) -> List[Tuple[float, float]]:
    """Closed YZ profile for one side wall (Y forward, Z up).

    The profile spans the full base thickness at the holder edge so the wall
    column is flush with the base exterior in X and Y.
    """
    ys = [p.holder_length * i / samples for i in range(samples + 1)]
    top = [(y, _wall_top_z(y, p)) for y in ys]
    bottom = [(p.holder_length, 0.0), (0.0, 0.0)]
    return top + bottom


def _build_side_wall(p: FingerSensorHolderParams, *, left: bool) -> cq.Solid:
    pts = _wall_profile_points(p)
    x0 = 0.0 if left else p.holder_width - p.wall_thickness
    wp = cq.Workplane("YZ").workplane(offset=x0)
    wall = wp.polyline(pts).close().extrude(p.wall_thickness)
    return wall.val()


def _build_base(p: FingerSensorHolderParams) -> cq.Solid:
    return _corner_box(0.0, 0.0, 0.0, p.holder_width, p.holder_length, p.base_thickness)


def _build_pedestal(p: FingerSensorHolderParams) -> cq.Solid:
    y0 = p.pedestal_front_offset
    dy = p.pedestal_length
    dz_front = p.pedestal_front_height
    dz_rear = p.pedestal_rear_height_above_base
    if dy <= 0:
        raise ValueError("pedestal_length must be positive.")

    # Loft a tapered pedestal block between front and rear heights.
    # rect() is centered on the plane origin, so X/Z origins are the profile
    # centroids — not the lower-left corner of the pedestal footprint.
    y_front = y0
    y_rear = y0 + dy
    cx = p.lateral_center_x
    bz = p.base_thickness

    pl_front = Plane(
        origin=(cx, y_front, bz + 0.5 * dz_front),
        normal=(0, 1, 0),
        xDir=(1, 0, 0),
    )
    pl_rear = Plane(
        origin=(cx, y_rear, bz + 0.5 * dz_rear),
        normal=(0, 1, 0),
        xDir=(1, 0, 0),
    )
    rect_front = wire(rect(p.pedestal_width, dz_front).moved(Location(pl_front)))
    rect_rear = wire(rect(p.pedestal_width, dz_rear).moved(Location(pl_rear)))
    return loft([face(rect_front), face(rect_rear)])


def _hinge_hole_cutter(p: FingerSensorHolderParams) -> cq.Solid:
    hole_r = 0.5 * p.hinge_rod_diameter + p.hinge_rod_clearance_mm
    axis_len = p.holder_width + 4.0
    # Start the cutter 2mm outboard of the left face so it drills through
    # both walls and barrels across the full holder width.
    pl = Plane(
        origin=(-2.0, p.hinge_axis_y, p.hinge_axis_z),
        normal=(1, 0, 0),
        xDir=(0, 1, 0),
    )
    hole_face = face(wire(circle(hole_r).moved(Location(pl))))
    return extrude(hole_face, (axis_len, 0, 0))


def _hinge_barrel(p: FingerSensorHolderParams, *, left: bool) -> cq.Solid:
    outer_r = 0.5 * p.hinge_outer_diameter
    inner_r = 0.5 * p.hinge_rod_diameter + p.hinge_rod_clearance_mm
    depth = p.wall_thickness
    # Start the ring face on the wall's exterior face and extrude inward
    # exactly one wall thickness so the barrel is flush with both the outer
    # and inner wall faces.
    x_outer = 0.0 if left else p.holder_width
    pl = Plane(
        origin=(x_outer, p.hinge_axis_y, p.hinge_axis_z),
        normal=(1, 0, 0),
        xDir=(0, 1, 0),
    )
    ring_face = face(
        wire(circle(outer_r).moved(Location(pl))),
        wire(circle(inner_r).moved(Location(pl))),
    )
    direction = (depth, 0, 0) if left else (-depth, 0, 0)
    return extrude(ring_face, direction)


def _finger_trough_cutter(p: FingerSensorHolderParams) -> cq.Solid:
    """Ramped finger channel: bottom starts at the base floor at the pedestal
    front face and slopes up so the fingertip lands on the sensor face."""
    cx = p.lateral_center_x
    depth = p.finger_trough_depth

    y_start = p.pedestal_front_offset
    y_end = y_start + p.finger_trough_front_blend_length + p.finger_trough_length
    z_bot_start = p.base_thickness
    # The sensor pocket assumes the trough surface sits trough_depth below the
    # pedestal front height at the sensor — the ramp must hit that exactly.
    z_bot_sensor = p.base_thickness + p.pedestal_front_height - depth
    slope = (z_bot_sensor - z_bot_start) / max(p.sensor_center_y - y_start, 1e-9)

    # Small lead-in ahead of the pedestal face for a clean boolean and a
    # smooth entry off the floor.
    lead = 0.8
    y0 = y_start - lead
    z0 = z_bot_start - lead * slope
    direction = (0.0, y_end - y0, (y_end - y0) * slope)

    # Elliptical channel bottom, extruded along the ramp direction.
    pl = Plane(origin=(cx, y0, z0 + 0.5 * depth), normal=(0, 1, 0), xDir=(1, 0, 0))
    ell_face = face(wire(ellipse(0.5 * p.finger_trough_width, 0.5 * depth).moved(Location(pl))))
    tool = extrude(ell_face, direction)

    # Open the channel to the sky so it cuts a trough, not a tunnel.
    clear_h = p.wall_full_height
    pl_rect = Plane(
        origin=(cx, y0, z0 + 0.5 * depth + 0.5 * clear_h),
        normal=(0, 1, 0),
        xDir=(1, 0, 0),
    )
    rect_face = face(wire(rect(p.finger_trough_width, clear_h).moved(Location(pl_rect))))
    tool = fuse(tool, extrude(rect_face, direction))

    # Trim the tool to just above the base floor: the flat ellipse would
    # otherwise graze the base top plane at the entry, leaving a paper-thin
    # groove that tessellates non-watertight at export tolerance.
    floor_eps = 0.1
    trim = _corner_box(
        cx - p.finger_trough_width,
        y0 - 1.0,
        z0 - 1.0,
        2.0 * p.finger_trough_width,
        (y_end - y0) + 2.0,
        (p.base_thickness + floor_eps) - (z0 - 1.0),
    )
    tool = cut(tool, trim)

    # Rounded finger stop scoop at the rear end of the ramp.
    stop_y = y_end - p.finger_stop_radius
    stop_z = z0 + (stop_y - y0) * slope + depth
    stop_pl = Plane(origin=(cx, stop_y, stop_z), normal=(0, 1, 0), xDir=(1, 0, 0))
    stop = extrude(face(wire(circle(p.finger_stop_radius).moved(Location(stop_pl)))), (0, p.finger_stop_radius, 0))
    return fuse(tool, stop)


def _sensor_pocket_floor_z(p: FingerSensorHolderParams) -> float:
    return (
        p.base_thickness
        + p.pedestal_front_height
        - p.finger_trough_depth
        - p.sensor_pocket_depth
        + p.sensor_face_raise_mm
    )


def _sensor_pocket_cutter(p: FingerSensorHolderParams) -> cq.Solid:
    cx = p.lateral_center_x
    cy = p.sensor_center_y
    floor_z = _sensor_pocket_floor_z(p)
    pocket_r = 0.5 * p.sensor_pocket_diameter
    pl = Plane(origin=(cx, cy, floor_z), normal=(0, 0, 1), xDir=(1, 0, 0))
    pocket = extrude(face(wire(circle(pocket_r).moved(Location(pl)))), (0, 0, p.sensor_pocket_depth + 2.0))
    # Top optical opening — leaves PCB perimeter lip.
    opening_r = 0.5 * p.sensor_exposed_opening_diameter
    top_z = floor_z + p.sensor_pocket_depth - p.sensor_max_thickness + p.sensor_face_raise_mm
    pl_open = Plane(origin=(cx, cy, top_z + 1.0), normal=(0, 0, 1), xDir=(1, 0, 0))
    opening = extrude(face(wire(circle(opening_r).moved(Location(pl_open)))), (0, 0, 4.0))
    return fuse(pocket, opening)


def _cable_channel_cutter(p: FingerSensorHolderParams) -> cq.Solid:
    cx = p.lateral_center_x
    pocket_r = 0.5 * p.sensor_pocket_diameter
    half_w = 0.5 * p.cable_channel_width
    if half_w >= pocket_r:
        raise ValueError("cable_channel_width must be narrower than the sensor pocket diameter.")
    # Start at the chord where the channel sides meet the pocket wall so the
    # PCB underside relief spans the entire pocket diameter (wires and solder
    # joints on the sensor back), not just the span behind the PCB rear edge.
    y_start = p.sensor_center_y - math.sqrt(pocket_r * pocket_r - half_w * half_w)
    y_end = p.cable_exit_y
    z_floor = p.base_thickness - p.cable_channel_depth
    length = max(y_end - y_start, 1.0)
    # Tall enough to open through the pocket floor along the pocket span;
    # behind the pedestal the extra height only cuts air above the base top.
    channel_top = _sensor_pocket_floor_z(p) + 0.5
    channel = _corner_box(
        cx - half_w,
        y_start,
        z_floor,
        p.cable_channel_width,
        length,
        channel_top - z_floor,
    )
    strain_r = 0.5 * p.strain_relief_pocket_diameter
    pl = Plane(
        origin=(cx, p.sensor_center_y + 0.5 * p.sensor_pcb_diameter + 2.0, p.base_thickness),
        normal=(0, 0, 1),
        xDir=(1, 0, 0),
    )
    strain = extrude(
        face(wire(circle(strain_r).moved(Location(pl)))),
        (0, 0, p.strain_relief_pocket_depth),
    )
    return fuse(channel, strain)


def _retention_slot_cutters(p: FingerSensorHolderParams) -> cq.Solid:
    cx = p.lateral_center_x
    cy = p.sensor_center_y
    slot_r = 0.5 * p.sensor_pocket_diameter - p.retention_plate_clearance_mm - 0.4
    cutters: List[cq.Solid] = []
    for i in range(p.retention_tab_count):
        ang = 2.0 * math.pi * i / p.retention_tab_count
        sx = cx + slot_r * math.cos(ang)
        sy = cy + slot_r * math.sin(ang)
        slot = _corner_box(
            sx - 0.5 * p.retention_tab_width_mm,
            sy - 0.5 * p.retention_tab_width_mm,
            p.base_thickness,
            p.retention_tab_width_mm,
            p.retention_tab_width_mm,
            p.pedestal_front_height,
        )
        cutters.append(slot)
    out = cutters[0]
    for c in cutters[1:]:
        out = fuse(out, c)
    return out


def _fillet_base_exterior_edges(
    solid: cq.Solid, radius: float, p: FingerSensorHolderParams
) -> cq.Solid:
    """Fillet front/rear base edges between the side walls (not wall junctions)."""
    if radius <= 0:
        return solid
    wp = cq.Workplane("XY").add(solid)
    margin = 0.05
    wall_lo = p.wall_thickness + margin
    wall_hi = p.holder_width - p.wall_thickness - margin

    def _is_front_rear_free_edge(edge: cq.Edge) -> bool:
        c = edge.Center()
        on_front = abs(c.y) < margin
        on_rear = abs(c.y - p.holder_length) < margin
        between_walls = wall_lo < c.x < wall_hi
        on_base = c.z < p.base_thickness + margin
        return (on_front or on_rear) and between_walls and on_base

    edges = wp.edges("|Z").filter(_is_front_rear_free_edge)
    if len(edges.vals()) == 0:
        return solid
    try:
        return edges.fillet(radius).val()
    except Exception as exc:
        raise RuntimeError(
            f"Base exterior fillet failed at radius={radius} mm; "
            "reduce general_fillet_radius or adjust geometry."
        ) from exc


def build_retention_plate(p: FingerSensorHolderParams) -> cq.Solid:
    """Removable backing plate that retains the sensor PCB from below."""
    cx = p.lateral_center_x
    cy = p.sensor_center_y
    outer_r = 0.5 * p.sensor_pocket_diameter - p.retention_plate_clearance_mm
    inner_r = 0.5 * p.sensor_pcb_diameter - 1.5
    if inner_r <= 0 or outer_r <= inner_r:
        raise ValueError("Retention plate radii are inconsistent; adjust clearance parameters.")

    pl = Plane(origin=(cx, cy, 0.0), normal=(0, 0, 1), xDir=(1, 0, 0))
    ring_face = face(
        wire(circle(outer_r).moved(Location(pl))),
        wire(circle(inner_r).moved(Location(pl))),
    )
    plate = extrude(ring_face, (0, 0, p.retention_plate_thickness_mm))

    tabs: List[cq.Solid] = []
    tab_r = outer_r - 0.5 * p.retention_tab_width_mm
    for i in range(p.retention_tab_count):
        ang = 2.0 * math.pi * i / p.retention_tab_count
        tx = cx + tab_r * math.cos(ang)
        ty = cy + tab_r * math.sin(ang)
        tab = _corner_box(
            tx - 0.5 * p.retention_tab_width_mm,
            ty - 0.5 * p.retention_tab_width_mm,
            p.retention_plate_thickness_mm,
            p.retention_tab_width_mm,
            p.retention_tab_width_mm,
            p.retention_tab_depth_mm,
        )
        tabs.append(tab)
    fused = plate
    for tab in tabs:
        fused = fuse(fused, tab)
    # Park the plate beside the holder so both parts print side by side
    # instead of overlapping at the sensor position.
    print_gap = 5.0
    plate_center_x = p.holder_width + print_gap + outer_r
    fused = fused.moved(Location((plate_center_x - cx, 0.0, 0.0)))
    return clean(fused)


def build_finger_sensor_holder_parts(
    params: FingerSensorHolderParams | None = None,
    *,
    config: Config | None = None,
) -> FingerSensorHolderParts:
    if params is None:
        if config is None:
            params = FingerSensorHolderParams()
        else:
            params = FingerSensorHolderParams.from_config(config)

    p = params
    base = _build_base(p)
    holder = fuse(base, _build_side_wall(p, left=True), _build_side_wall(p, left=False))
    holder = _fillet_base_exterior_edges(
        holder, min(p.general_fillet_radius, 0.8), p
    )
    holder = fuse(holder, _build_pedestal(p))
    holder = fuse(holder, _hinge_barrel(p, left=True), _hinge_barrel(p, left=False))
    holder = cut(holder, _hinge_hole_cutter(p))
    holder = cut(holder, _finger_trough_cutter(p))
    holder = cut(holder, _sensor_pocket_cutter(p))
    holder = cut(holder, _cable_channel_cutter(p))
    holder = cut(holder, _retention_slot_cutters(p))
    holder = clean(holder)

    plate = build_retention_plate(p)
    return FingerSensorHolderParts(holder=holder, retention_plate=plate)


def solid_to_trimesh(solid: cq.Solid, *, tolerance: float = 0.05) -> trimesh.Trimesh:
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
        tmp = f.name
    try:
        cq.exporters.export(
            solid, tmp, tolerance=tolerance, angularTolerance=0.3, opt={"ascii": False}
        )
        mesh = trimesh.load(tmp)
        if isinstance(mesh, trimesh.Scene):
            mesh = mesh.dump(concatenate=True)
        return mesh
    finally:
        os.unlink(tmp)


def validate_solids_watertight(
    solids: Iterable[Tuple[str, cq.Solid]],
    *,
    tolerance: float = 0.05,
) -> List[str]:
    """Return human-readable errors; empty list means all solids tessellate watertight."""
    errors: List[str] = []
    for name, solid in solids:
        if not solid.isValid():
            errors.append(f"{name}: CadQuery/OCC shape is invalid")
            continue
        mesh = solid_to_trimesh(solid, tolerance=tolerance)
        if not mesh.is_watertight:
            errors.append(f"{name}: tessellated mesh is not watertight")
        if mesh.volume <= 0:
            errors.append(f"{name}: non-positive volume ({mesh.volume:.4f} mm³)")
    return errors


def parameters_for_prototype_tuning() -> List[str]:
    """Parameters most likely to need adjustment after a first test print."""
    return [
        "finger_trough_width",
        "finger_trough_depth",
        "finger_trough_length",
        "finger_stop_radius",
        "sensor_pocket_diameter",
        "sensor_pocket_depth",
        "sensor_exposed_opening_diameter",
        "sensor_face_raise_mm",
        "cable_channel_width",
        "cable_channel_depth",
        "hinge_rod_clearance_mm",
        "retention_plate_clearance_mm",
        "retention_tab_depth_mm",
        "pedestal_length",
        "front_transition_radius",
        "rear_transition_radius",
    ]


def build(config: Config) -> None:
    parts = build_finger_sensor_holder_parts(config=config)
    errors = validate_solids_watertight(
        [("holder", parts.holder), ("retention_plate", parts.retention_plate)]
    )
    if errors:
        raise RuntimeError("Finger sensor holder geometry validation failed:\n  " + "\n  ".join(errors))
    logger.info(
        "Finger sensor holder validation OK (watertight). "
        "Tune after first print: %s",
        ", ".join(parameters_for_prototype_tuning()[:6]) + ", ...",
    )
    render_part(parts.to_assembly(), config)
