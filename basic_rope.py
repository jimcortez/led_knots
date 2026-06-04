"""
Braided tube sleeve along an arbitrary centerline path.

Continuous helical strand lofts (tube_rope-style) with basket-inspired radial
weave modulation (basketr cosine bulge / rope_sim oscillation).
"""

import argparse
import math
import signal
from contextlib import contextmanager
from pathlib import Path

from cadquery import Vector, Wire, Plane, Compound, Edge
from cadquery.func import spline
from cadquery.occ_impl.shapes import Solid
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.GCPnts import GCPnts_UniformAbscissa


@contextmanager
def _time_limit(seconds):
    """Raise TimeoutError if the wrapped block runs past `seconds` (Unix only)."""
    def _handler(signum, frame):
        raise TimeoutError(f"exceeded {seconds}s")
    prev = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, prev)

# Braid geometry (mm)
#
# Tubular 1-over-1 braid: NUM_STRANDS_PER_DIR strands spiral CW and the same
# count spiral CCW. At every CW/CCW crossing one strand is above the base
# helix radius and the other below, so the over/under genuinely interlaces.
#
# Only NUM_STRANDS_PER_DIR and OUTER_RADIUS are intended as user-tuned inputs.
# Everything below is derived so scaling means changing N at the top.
#
# Strand fit on the cylinder: 2N strand centers (CW + CCW interleaved) at
# angular spacing π/N. For circular profiles of radius p to fit at arc spacing
# π·R/N with packing factor k_pack:
#     p = k_pack · π·R / (2N)
# Over/under separation needs WEAVE_AMPLITUDE > p so surfaces don't merge:
#     δ = 1.2·p
# Outer surface of any strand = R + δ + p = R · (1 + 1.1·π·k_pack/N).
NUM_STRANDS_PER_DIR = 25         # 50 total strands; change this to scale
OUTER_RADIUS = 14.0              # fixed outer rope radius (mm)
_K_PACK = 0.7                    # 0..1 packing tightness; <1 leaves over/under headroom
# Helix angle controls pitch (pitch = 2π·R / tan(α)). Shallower angles widen
# the pitch, which is essential at high N: the radial-wiggle curvature radius
# (≈ pitch² / (4π²·N²·δ)) must exceed STRAND_PROFILE_RADIUS or OCC's loft
# and sweep both self-intersect. 30° empirically gives ~1.4× margin at N=25
# with k_pack=0.7 — loft handles ~75% of strands; sweep mops up the rest.
_HELIX_ANGLE_DEG = 30.0

HELIX_RADIUS = OUTER_RADIUS / (1.0 + 1.1 * math.pi * _K_PACK / NUM_STRANDS_PER_DIR)
STRAND_PROFILE_RADIUS = _K_PACK * math.pi * HELIX_RADIUS / (2.0 * NUM_STRANDS_PER_DIR)
WEAVE_AMPLITUDE = 1.2 * STRAND_PROFILE_RADIUS
PITCH = 2.0 * math.pi * HELIX_RADIUS / math.tan(math.radians(_HELIX_ANGLE_DEG))
CORE_RADIUS = HELIX_RADIUS - WEAVE_AMPLITUDE + 0.6 * STRAND_PROFILE_RADIUS

STRAND_START = 2.0
STRAND_END_OFFSET = 2.0
# loft_samples is computed per-build inside build_braided_rope (depends on path length).


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


def weave_radius(base_radius, s, pitch, amplitude, num_strands_per_dir, direction):
    """
    1-over-1 tubular braid radial modulation.

    All strands of the same direction share the same r(s); CW and CCW are
    180° out of phase so at each CW/CCW crossing one is at +amplitude and
    the other at -amplitude. Period = pitch / num_strands_per_dir, which
    equals 2× the crossing interval of a strand against the opposite set.
    """
    if amplitude <= 0:
        return base_radius
    omega = 2.0 * math.pi * num_strands_per_dir / pitch
    return base_radius + direction * amplitude * math.sin(omega * s)


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
    loft_samples,
    use_weave=True,
    weave_amplitude=WEAVE_AMPLITUDE,
    num_strands_per_dir=NUM_STRANDS_PER_DIR,
):
    """
    Continuous helical strand loft following path_samples frames.

    With use_weave=True the strand's helix radius oscillates per
    weave_radius() so CW and CCW strands interlace at their crossings.

    Returns (solid, used_sweep_fallback). used_sweep_fallback is True if the
    multi-section loft failed and we fell back to a single-profile sweep.
    """
    s_start = STRAND_START
    s_end = path_length - STRAND_END_OFFSET
    strand_length = s_end - s_start
    if strand_length <= 0:
        raise ValueError("path too short for strand loft")

    pts = []
    tangents = []
    outwards = []

    for i in range(loft_samples):
        t = i / (loft_samples - 1)
        s = s_start + t * strand_length
        frame = frame_at_arc_length(path_samples, s)
        if use_weave:
            r = weave_radius(
                strand_radius,
                s,
                pitch,
                weave_amplitude,
                num_strands_per_dir,
                direction,
            )
        else:
            r = strand_radius
        pts.append(helix_point(s, frame, r, pitch, phase, direction))

    for i in range(loft_samples):
        if i == 0:
            tang = _norm((pts[1][0] - pts[0][0], pts[1][1] - pts[0][1], pts[1][2] - pts[0][2]))
        elif i == loft_samples - 1:
            tang = _norm((pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1], pts[i][2] - pts[i - 1][2]))
        else:
            tang = _norm((
                pts[i + 1][0] - pts[i - 1][0],
                pts[i + 1][1] - pts[i - 1][1],
                pts[i + 1][2] - pts[i - 1][2],
            ))
        tangents.append(tang)

        frame = frame_at_arc_length(path_samples, s_start + i / (loft_samples - 1) * strand_length)
        center = _vec(frame["point"])
        outward = _norm((
            pts[i][0] - center[0],
            pts[i][1] - center[1],
            pts[i][2] - center[2],
        ))
        outwards.append(outward)

    # Seed x_dir perpendicular to the strand tangent (outward projected onto
    # the cross-section plane). Then parallel-transport along the tangents.
    t0 = tangents[0]
    n0 = outwards[0]
    dot = t0[0] * n0[0] + t0[1] * n0[1] + t0[2] * n0[2]
    x_raw = (n0[0] - dot * t0[0], n0[1] - dot * t0[1], n0[2] - dot * t0[2])
    x_dirs = [_norm(x_raw)]

    for i in range(1, loft_samples):
        tang = tangents[i]
        prev_x = x_dirs[-1]
        dot = prev_x[0] * tang[0] + prev_x[1] * tang[1] + prev_x[2] * tang[2]
        proj = (
            prev_x[0] - dot * tang[0],
            prev_x[1] - dot * tang[1],
            prev_x[2] - dot * tang[2],
        )
        x_dirs.append(_norm(proj))

    # Cross-section plane is perpendicular to the strand's own tangent so the
    # circular profile sweeps a true cord, not a radially-flat ribbon.
    wires = []
    for i in range(loft_samples):
        pt = Vector(*pts[i])
        x_dir = Vector(*x_dirs[i])
        tangent = Vector(*tangents[i])
        pl = Plane(origin=pt, xDir=x_dir, normal=tangent)
        wires.append(Wire.makeCircle(STRAND_PROFILE_RADIUS, pl.origin, pl.zDir))

    try:
        return Solid.makeLoft(wires, ruled=False), "loft"
    except Exception:
        try:
            return Solid.makeLoft(wires, ruled=True), "loft-ruled"
        except Exception:
            pass

    # Sweep fallback for strands the loft can't handle. Wrap in a timeout —
    # at thin-strand / curved-path geometries OCC's MakePipeShell sometimes
    # spins for minutes before giving up. 30s is generous for one strand.
    try:
        with _time_limit(30):
            path_pts = [Vector(*p) for p in pts]
            path_edge = Edge.makeSpline(path_pts)
            path_wire = Wire.assembleEdges([path_edge])
            pl0 = Plane(
                origin=Vector(*pts[0]),
                xDir=Vector(*x_dirs[0]),
                normal=Vector(*tangents[0]),
            )
            profile = Wire.makeCircle(STRAND_PROFILE_RADIUS, pl0.origin, pl0.zDir)
            return Solid.sweep(profile, [], path_wire, makeSolid=True, isFrenet=True), "sweep"
    except (TimeoutError, Exception):
        return None, "failed"


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

    total_strands = 2 * NUM_STRANDS_PER_DIR
    strand_dia = 2.0 * STRAND_PROFILE_RADIUS
    samples_per_period = 20
    loft_samples = max(
        240,
        min(1500, math.ceil(samples_per_period * NUM_STRANDS_PER_DIR * path_length / PITCH)),
    )
    print(
        f"Braid: {total_strands} strands, strand_dia={strand_dia:.2f}mm, "
        f"outer_dia={2 * OUTER_RADIUS:.1f}mm, pitch={PITCH:.1f}mm, "
        f"loft_samples={loft_samples}"
    )
    if strand_dia < 1.2:
        print(f"  note: strand_dia < 1.2mm FDM floor; SLA/visualization only")

    print("Generating core tube...")
    core = build_core_tube(path, path_samples)

    print(f"Building {total_strands} helical braid strands...")
    strands = []
    method_counts = {"loft": 0, "loft-ruled": 0, "sweep": 0, "failed": 0}
    built = 0
    for direction, label in [(-1, "CW"), (1, "CCW")]:
        for i in range(NUM_STRANDS_PER_DIR):
            phase = i * (2 * math.pi / NUM_STRANDS_PER_DIR)
            if direction == 1:
                phase += math.pi / NUM_STRANDS_PER_DIR
            strand, method = build_helix_strand_on_path(
                path_samples,
                path_length,
                HELIX_RADIUS,
                PITCH,
                phase,
                direction,
                loft_samples,
                use_weave=use_weave,
                weave_amplitude=WEAVE_AMPLITUDE,
                num_strands_per_dir=NUM_STRANDS_PER_DIR,
            )
            method_counts[method] += 1
            if strand is not None:
                strands.append(strand)
            built += 1
            print(f"\r  strands: {built}/{total_strands}", end="", flush=True)
    print()  # newline after the progress carriage-return

    print(
        f"  built via: loft={method_counts['loft']}, "
        f"loft-ruled={method_counts['loft-ruled']}, "
        f"sweep={method_counts['sweep']}, "
        f"failed/skipped={method_counts['failed']} (of {total_strands})"
    )
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
