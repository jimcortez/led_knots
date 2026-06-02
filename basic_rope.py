"""
Braided tube sleeve along an arbitrary centerline path.

Continuous helical strand lofts (tube_rope-style) with basket-inspired radial
weave modulation (basketr cosine bulge / rope_sim oscillation).
"""

import argparse
import math
from pathlib import Path

from cadquery import Vector, Wire, Plane, Compound, Edge
from cadquery.func import spline
from cadquery.occ_impl.shapes import Solid
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.GCPnts import GCPnts_UniformAbscissa

# Core / sleeve dimensions (mm)
BASE_OUTER_SIZE = 14.5
VALLEY_DEPTH = 3.0
CORE_RADIUS = BASE_OUTER_SIZE - VALLEY_DEPTH
STRAND_PROFILE_RADIUS = 2.5
STRAND_SURFACE_RADIUS = CORE_RADIUS + STRAND_PROFILE_RADIUS

# Braid parameters
NUM_STRANDS_PER_DIR = 6
NUM_RODS = 12  # circumferential weave frequency (basket number_of_rods)
PITCH = 20.0  # mm arc length per full 360° helix turn
LOFT_SAMPLES = 300
STRAND_START = 2.0
STRAND_END_OFFSET = 2.0

# Basket-style weave depth on helix radius
WEAVE_BULGE = 1.5
WEAVE_PHASE_CW = 0.0
WEAVE_PHASE_CCW = math.pi


def _norm(v):
    d = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    return (v[0] / d, v[1] / d, v[2] / d) if d > 1e-10 else v


def _vec(v):
    if isinstance(v, Vector):
        return (v.x, v.y, v.z)
    return v


def _lerp_vec(a, b, u):
    return (
        a[0] + u * (b[0] - a[0]),
        a[1] + u * (b[1] - a[1]),
        a[2] + u * (b[2] - a[2]),
    )


def point_bulged_circle(radius, angle, bulge, num_rods):
    """Basketr point_bulged_circle: r - bulge*cos(angle * num_rods / 2)."""
    r_eff = radius - bulge * math.cos(angle * num_rods / 2.0)
    return (r_eff * math.cos(angle), r_eff * math.sin(angle))


def effective_strand_radius(base_radius, theta, bulge, num_rods, weave_phase):
    """Radial offset for over/under: basket cosine in helix angle."""
    return base_radius + bulge * math.cos(num_rods / 2.0 * theta + weave_phase)


def get_samples(path, num_sections):
    """Sample path at uniform arc length with parallel-transported xDir."""
    path_length = path.Length()
    edges = path.Edges()

    if len(edges) == 1 and num_sections >= 2:
        edge = edges[0]
        adaptor = BRepAdaptor_Curve(edge.wrapped)
        u1, u2 = adaptor.FirstParameter(), adaptor.LastParameter()
        dist = GCPnts_UniformAbscissa(adaptor, num_sections, u1, u2)
        if not dist.IsDone():
            t_values = [i / (num_sections - 1) for i in range(num_sections)]
        else:
            t_values = []
            for i in range(1, dist.NbPoints() + 1):
                t_ocp = dist.Parameter(i)
                t_cq = (t_ocp - u1) / (u2 - u1) if u2 > u1 else 0.0
                t_values.append(t_cq)
    else:
        t_values = [i / (num_sections - 1) for i in range(num_sections)]

    samples = []
    prev_local_x = None
    for i, t in enumerate(t_values):
        s = i * path_length / (num_sections - 1) if num_sections > 1 else path_length
        pt = path.positionAt(t)
        tg = path.tangentAt(t)
        tangent = _norm((tg.x, tg.y, tg.z))
        if i == 0:
            ref = (0, 0, 1) if abs(tangent[2]) < 0.9 else (1, 0, 0)
            cx = tangent[1] * ref[2] - tangent[2] * ref[1]
            cy = tangent[2] * ref[0] - tangent[0] * ref[2]
            cz = tangent[0] * ref[1] - tangent[1] * ref[0]
            prev_local_x = _norm((cx, cy, cz))
        else:
            dot = (
                prev_local_x[0] * tangent[0]
                + prev_local_x[1] * tangent[1]
                + prev_local_x[2] * tangent[2]
            )
            px = prev_local_x[0] - dot * tangent[0]
            py = prev_local_x[1] - dot * tangent[1]
            pz = prev_local_x[2] - dot * tangent[2]
            pm = (px * px + py * py + pz * pz) ** 0.5
            if pm > 1e-6:
                prev_local_x = (px / pm, py / pm, pz / pm)
        x_dir = Vector(prev_local_x[0], prev_local_x[1], prev_local_x[2])
        samples.append({
            "t": t,
            "point": pt,
            "tangent": tg,
            "x_dir": x_dir,
            "arc_length": s,
        })
    return samples


def frame_at_arc_length(samples, s):
    """
    Interpolate origin along path; keep x_dir from nearest upstream sample
    (parallel-transported on discrete samples) to avoid bad twists on curves.
    """
    if s <= samples[0]["arc_length"]:
        return samples[0]
    if s >= samples[-1]["arc_length"]:
        return samples[-1]
    for i in range(len(samples) - 1):
        s0 = samples[i]["arc_length"]
        s1 = samples[i + 1]["arc_length"]
        if s0 <= s <= s1:
            if abs(s1 - s0) < 1e-9:
                return samples[i]
            u = (s - s0) / (s1 - s0)
            p0 = _vec(samples[i]["point"])
            p1 = _vec(samples[i + 1]["point"])
            pt = _lerp_vec(p0, p1, u)
            # Use discrete frame from lower sample (stable on curved paths)
            ref = samples[i]
            return {
                "point": Vector(*pt),
                "tangent": ref["tangent"],
                "x_dir": ref["x_dir"],
                "arc_length": s,
            }
    return samples[-1]


def _frame_axes(frame):
    """Return unit tangent, x_dir, y_dir from a path frame sample."""
    tangent = _norm(_vec(frame["tangent"]))
    x_dir = _norm(_vec(frame["x_dir"]))
    tx, ty, tz = tangent
    xx, xy, xz = x_dir
    yx = ty * xz - tz * xy
    yy = tz * xx - tx * xz
    yz = tx * xy - ty * xx
    y_dir = _norm((yx, yy, yz))
    return tangent, x_dir, y_dir


def helix_point(s, frame, radius, pitch, phase, direction):
    """World-space point on helical strand at arc length s."""
    tangent, x_dir, y_dir = _frame_axes(frame)
    theta = direction * (s / pitch) * 2 * math.pi + phase
    ox, oy, oz = _vec(frame["point"])
    radial = (
        radius * math.cos(theta) * x_dir[0] + radius * math.sin(theta) * y_dir[0],
        radius * math.cos(theta) * x_dir[1] + radius * math.sin(theta) * y_dir[1],
        radius * math.cos(theta) * x_dir[2] + radius * math.sin(theta) * y_dir[2],
    )
    return (
        ox + radial[0],
        oy + radial[1],
        oz + radial[2],
    )


def build_helix_strand_on_path(
    path_samples,
    path_length,
    strand_radius,
    pitch,
    phase,
    direction,
    weave_phase,
    use_weave=True,
    weave_bulge=WEAVE_BULGE,
):
    """
    Continuous helical strand loft following path_samples frames.
    Optional basket cosine radial weave on strand radius.
    """
    s_start = STRAND_START
    s_end = path_length - STRAND_END_OFFSET
    strand_length = s_end - s_start
    if strand_length <= 0:
        raise ValueError("path too short for strand loft")

    pts = []
    tangents = []
    outwards = []

    for i in range(LOFT_SAMPLES):
        t = i / (LOFT_SAMPLES - 1)
        s = s_start + t * strand_length
        frame = frame_at_arc_length(path_samples, s)
        theta = direction * (s / pitch) * 2 * math.pi + phase
        if use_weave:
            r = effective_strand_radius(
                strand_radius,
                theta,
                weave_bulge,
                NUM_RODS,
                weave_phase,
            )
        else:
            r = strand_radius
        pts.append(helix_point(s, frame, r, pitch, phase, direction))

    for i in range(LOFT_SAMPLES):
        if i == 0:
            tang = _norm((pts[1][0] - pts[0][0], pts[1][1] - pts[0][1], pts[1][2] - pts[0][2]))
        elif i == LOFT_SAMPLES - 1:
            tang = _norm((pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1], pts[i][2] - pts[i - 1][2]))
        else:
            tang = _norm((
                pts[i + 1][0] - pts[i - 1][0],
                pts[i + 1][1] - pts[i - 1][1],
                pts[i + 1][2] - pts[i - 1][2],
            ))
        tangents.append(tang)

        frame = frame_at_arc_length(path_samples, s_start + i / (LOFT_SAMPLES - 1) * strand_length)
        center = _vec(frame["point"])
        outward = _norm((
            pts[i][0] - center[0],
            pts[i][1] - center[1],
            pts[i][2] - center[2],
        ))
        outwards.append(outward)

    # Parallel-transport profile x_dir along strand tangent
    t0 = tangents[0]
    n0 = outwards[0]
    dot = t0[0] * n0[0] + t0[1] * n0[1] + t0[2] * n0[2]
    x_raw = (t0[0] - dot * n0[0], t0[1] - dot * n0[1], t0[2] - dot * n0[2])
    x_dirs = [_norm(x_raw)]

    for i in range(1, LOFT_SAMPLES):
        tang = tangents[i]
        prev_x = x_dirs[-1]
        dot = prev_x[0] * tang[0] + prev_x[1] * tang[1] + prev_x[2] * tang[2]
        proj = (
            prev_x[0] - dot * tang[0],
            prev_x[1] - dot * tang[1],
            prev_x[2] - dot * tang[2],
        )
        x_dirs.append(_norm(proj))

    wires = []
    for i in range(LOFT_SAMPLES):
        pt = Vector(*pts[i])
        x_dir = Vector(*x_dirs[i])
        outward = Vector(*outwards[i])
        pl = Plane(origin=pt, xDir=x_dir, normal=outward)
        wires.append(Wire.makeCircle(STRAND_PROFILE_RADIUS, pl.origin, pl.zDir))

    try:
        return Solid.makeLoft(wires, ruled=False)
    except Exception:
        try:
            return Solid.makeLoft(wires, ruled=True)
        except Exception:
            pass

    # Fallback for curved paths where multi-section loft fails
    path_pts = [Vector(*p) for p in pts]
    path_edge = Edge.makeSpline(path_pts)
    path_wire = Wire.assembleEdges([path_edge])
    pl0 = Plane(
        origin=Vector(*pts[0]),
        xDir=Vector(*x_dirs[0]),
        normal=Vector(*outwards[0]),
    )
    profile = Wire.makeCircle(STRAND_PROFILE_RADIUS, pl0.origin, pl0.zDir)
    return Solid.sweep(profile, [], path_wire, makeSolid=True, isFrenet=True)


def build_core_tube(path, path_samples):
    """Smooth core loft along path."""
    wires = []
    for s in path_samples:
        pl = Plane(origin=s["point"], xDir=s["x_dir"], normal=s["tangent"])
        wires.append(Wire.makeCircle(CORE_RADIUS, pl.origin, pl.zDir))
    return Solid.makeLoft(wires, ruled=True)


def build_braided_rope(path=None, curved=False, use_weave=True):
    """Build core + CW/CCW helical braid sleeve compound."""
    if path is None:
        if curved:
            # Gentle curve (tight bends can break OCC loft on some strand phases)
            path = spline(
                [(0, 0, 0), (0, 50, 2), (0, 100, 0)],
                tgts=[(0, 1, 0), (0, 1, 0), (0, 1, 0)],
            )
        else:
            path = spline(
                [(0, 0, 0), (0, 100, 0)],
                tgts=[(0, 1, 0), (0, 1, 0)],
            )

    path_length = path.Length()
    path_samples = get_samples(path, 200 if curved else 100)
    strand_weave = use_weave
    pitch = PITCH
    weave_bulge = WEAVE_BULGE

    print("Generating core tube...")
    core = build_core_tube(path, path_samples)

    print("Building helical braid strands...")
    strands = []
    for direction, label, weave_phase in [
        (-1, "CW", WEAVE_PHASE_CW),
        (1, "CCW", WEAVE_PHASE_CCW),
    ]:
        print(f"  -> {label} strands...")
        for i in range(NUM_STRANDS_PER_DIR):
            phase = i * (2 * math.pi / NUM_STRANDS_PER_DIR)
            if direction == 1:
                phase += math.pi / NUM_STRANDS_PER_DIR
            strand = build_helix_strand_on_path(
                path_samples,
                path_length,
                STRAND_SURFACE_RADIUS,
                pitch,
                phase,
                direction,
                weave_phase,
                use_weave=strand_weave,
                weave_bulge=weave_bulge,
            )
            strands.append(strand)
            print(f"     strand {i + 1}/{NUM_STRANDS_PER_DIR} done")

    print(f"Total strands: {len(strands)}")
    return Compound.makeCompound([core] + strands)


def main():
    parser = argparse.ArgumentParser(description="Braided rope sleeve along a path")
    parser.add_argument("--preview", type=str, help="Export PNG preview to this path")
    parser.add_argument(
        "--curved",
        action="store_true",
        help="Use gentle S-curve path instead of straight",
    )
    args = parser.parse_args()

    result = build_braided_rope(curved=args.curved)

    if args.preview:
        from cadquery import exporters
        import tempfile
        from led_knots.core.preview import render_stl_to_image

        class MockPreviewConfig:
            image_width = 800
            image_height = 800
            elevation = 30
            azimuth = 45
            roll = 0
            light_azimuth = 30
            light_elevation = 60
            opacity = 1.0
            _color_rgb = (0.7, 0.7, 0.7)
            _background_rgb = (0.1, 0.1, 0.1)

        out = Path(args.preview)
        out.parent.mkdir(parents=True, exist_ok=True)
        print(f"Exporting preview to {out}...")
        with tempfile.NamedTemporaryFile(suffix=".stl") as tf:
            exporters.export(result, tf.name)
            render_stl_to_image(Path(tf.name), out, MockPreviewConfig())
        print("Done.")
    else:
        try:
            from cadquery_web_viewer import show
            show(result, names="braided_rope", server_type="remote")
            print("Displayed braided_rope in cadquery-web-viewer.")
        except ImportError:
            print("cadquery-web-viewer not found. Use --preview to export PNG.")


if __name__ == "__main__":
    main()
