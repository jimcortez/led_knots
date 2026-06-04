"""
Academic-grounded braided tube sleeve along an arbitrary centerline path.

A rewrite of basic_rope.py that reformulates the geometry in the notation of
He et al. 2020 (https://journals.sagepub.com/doi/10.1177/1558925020939726,
Eqs. 13, 17, 18) and adds three improvements drawn from the wider braid-
modeling literature:

1. Float length F (Kyosev 2014/2018) -- supports n*n braids (1*1 diamond,
   2*2 regular, ...), not just 1*1.
2. Lenticular elliptical strand cross-section (Kyosev), optionally tilted
   to the local helix angle so strands lie naturally along the braid
   direction. Replaces basic_rope.py's circular profile.
3. A derived contact bound for the radial weave amplitude (Kyosev 2018
   Ch. 4 interlace geometry) instead of basic_rope.py's `1.2 * p` heuristic.

What is intentionally NOT modeled (would require an FE solver):
    strand self-adjustment under contact / friction (Vu, Durville,
    Davies 2015). Strands here are placed by phase relationships and may
    interpenetrate at extreme tilt or near-zero amplitude_factor.

References
----------
He, Sheng, He, Zhou, Yuan, Ning, Ning (2020). "Mathematical and
    geometrical modeling of braided ropes bent over a sheave."
    J. Eng. Fibers Fabrics 15. DOI: 10.1177/1558925020939726
Kyosev, Y. (2014/2015/2018). Braiding Technology for Textiles
    (Woodhead Publishing) -- generalized braid topology, float length,
    contact relations.
Ning, Potluri, Yu, et al. (2017). "Geometrical modeling of tubular
    braided structures using generalized rose curve." Textile Res. J.
"""

import argparse
import math
import signal
from contextlib import contextmanager
from dataclasses import dataclass, field
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


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

@dataclass
class BraidParams:
    """
    Braid parameters following He et al. 2020 notation (paper symbols in
    parentheses). All lengths in mm, all angles in degrees.

    User-facing fields: num_strands_per_dir, outer_radius, float_length,
    helix_angle_deg, pack_factor, strand_aspect_ratio, tilt_to_helix_angle,
    weave_amplitude_factor, samples_per_period, strand_start, strand_end_offset.
    The remaining fields are derived in __post_init__ and named per the
    paper for traceability.
    """

    # User-facing
    num_strands_per_dir: int = 75          # = (total strands) / 2
    outer_radius: float = 14.0             # finished rope outer radius
    float_length: int = 1                  # F: 1=1*1 diamond; 2=2*2 regular; n*n
    helix_angle_deg: float = 30.0          # beta_s in He et al. Table 1
    pack_factor: float = 0.7               # k, 0..1 circumferential tightness
    strand_aspect_ratio: float = 1.6       # a / b (major / minor); 1.0 = circle
    tilt_to_helix_angle: bool = True       # rotate ellipse to braid direction
    weave_amplitude_factor: float = 1.05   # A as multiple of Kyosev A_min
    samples_per_period: int = 20           # loft samples per weave period
    strand_start: float = 2.0              # trim from path start
    strand_end_offset: float = 2.0         # trim from path end

    # Derived (filled by __post_init__)
    Rr: float = field(init=False)              # helix radius (paper symbol)
    p: float = field(init=False)               # strand minor semi-axis (radial)
    a: float = field(init=False)               # strand major semi-axis (circumf.)
    radial_extent: float = field(init=False)   # one-sided radial half-thickness
    A_min: float = field(init=False)           # Kyosev contact bound for amplitude
    A: float = field(init=False)               # weave amplitude actually used
    N: float = field(init=False)               # weave frequency per turn (paper)
    pitch: float = field(init=False)           # axial pitch of one strand revolution
    core_radius: float = field(init=False)     # inner core tube radius
    tilt_angle_rad: float = field(init=False)  # ellipse tilt around tangent

    def __post_init__(self):
        if self.float_length < 1:
            raise ValueError("float_length must be >= 1")
        if self.num_strands_per_dir % self.float_length != 0:
            raise ValueError(
                f"num_strands_per_dir ({self.num_strands_per_dir}) must be "
                f"divisible by float_length ({self.float_length}) so the "
                f"n*n weave pattern closes around the cylinder."
            )

        N = self.num_strands_per_dir
        F = self.float_length
        aspect = self.strand_aspect_ratio
        k = self.pack_factor

        # Ellipse tilt around the strand tangent. When tilt_to_helix_angle=True,
        # rotate so the major axis lies along the braid direction (helix-aligned)
        # rather than purely circumferential. tilt=0 leaves the major axis in
        # the cross-tangent in-surface direction.
        if self.tilt_to_helix_angle:
            self.tilt_angle_rad = math.radians(90.0 - self.helix_angle_deg)
        else:
            self.tilt_angle_rad = 0.0

        # eta := (radial half-thickness of one strand at the chosen tilt) / p.
        # For an ellipse (a circumferential, p radial) rotated by gamma around
        # the tangent (a rotation in the cross-section plane that mixes radial
        # and circumferential axes), the radial extent is
        #     sqrt((a*sin gamma)^2 + (p*cos gamma)^2).
        # eta = 1 when not tilted; > 1 when tilted with aspect > 1.
        gamma = self.tilt_angle_rad
        eta = math.sqrt((aspect * math.sin(gamma)) ** 2 + math.cos(gamma) ** 2)

        # Circumferential packing constraint: 2N strand centres (CW + CCW
        # interleaved) at arc spacing pi * Rr / N must accommodate strand
        # half-width a with packing factor k:
        #     2 * a <= k * (2 * pi * Rr / (2 * N)) = k * pi * Rr / N
        # so a = (k * pi * Rr) / (2 * N) gives the tightest legal packing.
        # We choose a at exactly that bound, then derive p = a / aspect.
        #
        # Outer surface of one strand at a crossing = Rr + A + radial_extent.
        # With A = weave_amplitude_factor * A_min = factor * eta * p:
        #     R_outer = Rr + (factor + 1) * eta * p
        #             = Rr * (1 + (factor + 1) * eta * k * pi / (2 * N * aspect))
        # Invert for Rr:
        denom = 1.0 + (self.weave_amplitude_factor + 1.0) * eta * k * math.pi / (
            2.0 * N * aspect
        )
        self.Rr = self.outer_radius / denom

        # Now derive strand axes from Rr.
        self.a = k * math.pi * self.Rr / (2.0 * N)
        self.p = self.a / aspect
        self.radial_extent = eta * self.p

        # Kyosev contact bound: at a CW/CCW crossing the two strand centres
        # are at radii Rr+A and Rr-A. For no interpenetration, the radial
        # gap (= 2A) must exceed twice the radial half-thickness, so
        # A_min = radial_extent.
        self.A_min = self.radial_extent
        self.A = self.weave_amplitude_factor * self.A_min

        # Weave frequency. basic_rope.py uses N (one over/under per strand pair);
        # Kyosev's n*n braid floats over F strand pairs, so the angular weave
        # frequency per rope turn becomes N/F.
        self.N = N / F

        # Pitch: helix advances one full turn over an axial length of
        # 2 * pi * Rr / tan(beta_s) (He et al., Sec 2).
        self.pitch = 2.0 * math.pi * self.Rr / math.tan(
            math.radians(self.helix_angle_deg)
        )

        # Core tube radius: sit safely inside the inner extreme of the weave.
        self.core_radius = self.Rr - self.A - 0.4 * self.radial_extent
        if self.core_radius <= 0:
            raise ValueError(
                "Derived core_radius <= 0; reduce weave_amplitude_factor, "
                "reduce strand_aspect_ratio, or increase num_strands_per_dir."
            )

    # Convenience views for logging
    def summary(self) -> str:
        total_strands = 2 * self.num_strands_per_dir
        return (
            f"Braid params (He et al. notation, Kyosev cross-section):\n"
            f"  total strands = {total_strands} (F={self.float_length} -> "
            f"{self.float_length}x{self.float_length} braid)\n"
            f"  Rr (helix R) = {self.Rr:.3f}, outer_R = {self.outer_radius:.3f}\n"
            f"  a (major) = {self.a:.3f}, p (minor) = {self.p:.3f}, "
            f"aspect = {self.strand_aspect_ratio:.2f}\n"
            f"  ellipse tilt = {math.degrees(self.tilt_angle_rad):.1f} deg, "
            f"radial_extent = {self.radial_extent:.3f}\n"
            f"  A_min (Kyosev) = {self.A_min:.3f}, A used = {self.A:.3f} "
            f"(factor {self.weave_amplitude_factor:.2f})\n"
            f"  N (weave/turn) = {self.N:.2f}, pitch = {self.pitch:.2f}, "
            f"beta_s = {self.helix_angle_deg:.1f} deg\n"
            f"  core_radius = {self.core_radius:.3f}"
        )


# ---------------------------------------------------------------------------
# Path frames (parallel-transported; copied from basic_rope.py)
# ---------------------------------------------------------------------------

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
    """Interpolate origin along path; keep nearest upstream x_dir (stable)."""
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


# ---------------------------------------------------------------------------
# Braiding curve (He et al. Eqs. 17, 18 -- frame-relative form)
# ---------------------------------------------------------------------------

def braiding_curve_point(s, frame, params: BraidParams, phase, direction):
    """
    Point on a single braiding curve at arc length s along the path.

    He et al. 2020 Eq. 17 (CCW, direction=+1) and Eq. 18 (CW, direction=-1)
    rewritten in a path-local Frenet-Serret frame so the model generalizes
    from the paper's single bent-over-sheave case to an arbitrary centerline:

        theta_s    = direction * 2*pi*s/pitch + phase           # angular position
        r_mod(s)   = Rr + direction * A * sin(N * omega_s * s)  # over/under weave
        omega_s    = 2*pi / pitch                                # axial weave rate
        position(s) = origin(s) + r_mod(s) * (cos theta_s * x_dir
                                              + sin theta_s * y_dir)

    where origin(s), x_dir, y_dir come from the path frame at arc length s.

    The weave term uses `s` (NOT `theta_s`) inside the sin, and multiplies the
    amplitude by `direction`. This is what makes the braid actually interlace:
    at every CW/CCW crossing the two strands meet at the same theta_s, so to
    place them at opposite radii (one over, one under) the weave must depend
    only on s and on the strand's handedness -- not on its per-strand phase
    around the cylinder. (Putting `phase` inside the sin makes sin(N(...))
    differ from CW to CCW by a multiple of pi, which collapses both strands
    to the same radius at every crossing -- they merge instead of interlace.)

    He et al.'s Eqs. 17 (CCW) and 18 (CW) achieve the same opposite-radius
    behavior at crossings via the CW/CCW sin/cos swap and opposite directions
    of theta_s. Here we express it more directly with the direction multiplier
    on A -- the resulting world-space point is identical to basic_rope.py's
    helix_point(weave_radius(...)) composition at F=1, aspect=1.
    """
    tangent, x_dir, y_dir = _frame_axes(frame)
    theta_s = direction * (s / params.pitch) * 2.0 * math.pi + phase
    omega_s = 2.0 * math.pi * params.N / params.pitch
    r_mod = params.Rr + direction * params.A * math.sin(omega_s * s)
    cos_t, sin_t = math.cos(theta_s), math.sin(theta_s)
    ox, oy, oz = _vec(frame["point"])
    return (
        ox + r_mod * (cos_t * x_dir[0] + sin_t * y_dir[0]),
        oy + r_mod * (cos_t * x_dir[1] + sin_t * y_dir[1]),
        oz + r_mod * (cos_t * x_dir[2] + sin_t * y_dir[2]),
    )


# ---------------------------------------------------------------------------
# Lenticular cross-section wire
# ---------------------------------------------------------------------------

def _lenticular_wire(center, tangent, x_in_plane, params: BraidParams, direction):
    """
    Build a lenticular (elliptical) cross-section wire perpendicular to the
    strand tangent.

    `x_in_plane` is a unit vector perpendicular to `tangent` -- the "outward
    radial" direction projected into the cross-section plane. We construct
    an orthonormal in-plane basis (e_radial, e_cross) and use cadquery's
    Plane with these as (xDir, normal) so makeEllipse aligns the major axis
    along e_cross (circumferential) and the minor along e_radial.

    When tilt_to_helix_angle=True we rotate the ellipse in its own plane by
    +/- (90 - beta_s) so the major axis lies along the local braid direction
    (which is the helix tangent direction tilted from circumferential by
    beta_s). Sign follows the strand handedness.
    """
    t = _norm(_vec(tangent))
    n_radial = _norm(_vec(x_in_plane))

    # cross_in_plane = tangent x n_radial -> right-handed in-plane axis
    cx = t[1] * n_radial[2] - t[2] * n_radial[1]
    cy = t[2] * n_radial[0] - t[0] * n_radial[2]
    cz = t[0] * n_radial[1] - t[1] * n_radial[0]
    cross_in_plane = _norm((cx, cy, cz))

    # Apply tilt: rotate (n_radial, cross_in_plane) in the cross-section plane
    # so the ellipse's "x" axis sits at angle gamma off the radial direction.
    # Direction sign: CW (-1) tilts one way, CCW (+1) the other, matching
    # how the strand actually leans along the braid direction.
    gamma = direction * params.tilt_angle_rad
    cos_g, sin_g = math.cos(gamma), math.sin(gamma)
    e_x = (
        cos_g * n_radial[0] + sin_g * cross_in_plane[0],
        cos_g * n_radial[1] + sin_g * cross_in_plane[1],
        cos_g * n_radial[2] + sin_g * cross_in_plane[2],
    )

    # cadquery Plane(origin, xDir, normal): the ellipse's makeEllipse takes
    # (x_radius, y_radius). We want the ellipse "fat" along cross_in_plane
    # (the major axis a) and "thin" along the radial-ish direction (minor p).
    # With xDir = e_x (the tilted radial-ish axis) and y in-plane = tangent x e_x,
    # we therefore pass x_radius = p, y_radius = a.
    pl = Plane(origin=Vector(*center), xDir=Vector(*e_x), normal=Vector(*t))
    return Wire.makeEllipse(
        params.p, params.a, pl.origin, pl.zDir, pl.xDir,
    )


# ---------------------------------------------------------------------------
# Per-strand loft (mirrors basic_rope.py's loft -> ruled -> sweep fallback)
# ---------------------------------------------------------------------------

def build_braid_strand(
    path_samples,
    path_length,
    params: BraidParams,
    phase,
    direction,
    loft_samples,
):
    """
    Lofted lenticular strand along the path following He et al.'s braiding
    curve. Returns (Solid|None, method_label).
    """
    s_start = params.strand_start
    s_end = path_length - params.strand_end_offset
    strand_length = s_end - s_start
    if strand_length <= 0:
        raise ValueError("path too short for strand loft")

    # 1. Sample braiding-curve points.
    pts = []
    for i in range(loft_samples):
        t = i / (loft_samples - 1)
        s = s_start + t * strand_length
        frame = frame_at_arc_length(path_samples, s)
        pts.append(braiding_curve_point(s, frame, params, phase, direction))

    # 2. Per-sample tangents (central differences) for cross-section planes.
    tangents = []
    for i in range(loft_samples):
        if i == 0:
            d = (pts[1][0] - pts[0][0], pts[1][1] - pts[0][1], pts[1][2] - pts[0][2])
        elif i == loft_samples - 1:
            d = (pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1], pts[i][2] - pts[i - 1][2])
        else:
            d = (
                pts[i + 1][0] - pts[i - 1][0],
                pts[i + 1][1] - pts[i - 1][1],
                pts[i + 1][2] - pts[i - 1][2],
            )
        tangents.append(_norm(d))

    # 3. Outward-from-axis directions, then parallel-transport an in-plane
    #    x basis along the strand so the ellipse orientation doesn't flip.
    outwards = []
    for i in range(loft_samples):
        frame = frame_at_arc_length(
            path_samples, s_start + i / (loft_samples - 1) * strand_length
        )
        center = _vec(frame["point"])
        outwards.append(_norm((
            pts[i][0] - center[0],
            pts[i][1] - center[1],
            pts[i][2] - center[2],
        )))

    t0 = tangents[0]
    n0 = outwards[0]
    dot0 = t0[0] * n0[0] + t0[1] * n0[1] + t0[2] * n0[2]
    x_raw = (n0[0] - dot0 * t0[0], n0[1] - dot0 * t0[1], n0[2] - dot0 * t0[2])
    x_dirs = [_norm(x_raw)]
    for i in range(1, loft_samples):
        tang = tangents[i]
        prev_x = x_dirs[-1]
        d = prev_x[0] * tang[0] + prev_x[1] * tang[1] + prev_x[2] * tang[2]
        proj = (prev_x[0] - d * tang[0], prev_x[1] - d * tang[1], prev_x[2] - d * tang[2])
        x_dirs.append(_norm(proj))

    # 4. Build cross-section wires (lenticular).
    wires = [
        _lenticular_wire(pts[i], tangents[i], x_dirs[i], params, direction)
        for i in range(loft_samples)
    ]

    # 5. Loft -> ruled-loft -> Frenet sweep fallback chain (basic_rope.py
    #    pattern; the lenticular profile is slightly more failure-prone in
    #    tight bends so the fallback path matters).
    try:
        return Solid.makeLoft(wires, ruled=False), "loft"
    except Exception:
        try:
            return Solid.makeLoft(wires, ruled=True), "loft-ruled"
        except Exception:
            pass

    try:
        with _time_limit(30):
            path_pts = [Vector(*p) for p in pts]
            path_edge = Edge.makeSpline(path_pts)
            path_wire = Wire.assembleEdges([path_edge])
            profile = _lenticular_wire(pts[0], tangents[0], x_dirs[0], params, direction)
            return Solid.sweep(profile, [], path_wire, makeSolid=True, isFrenet=True), "sweep"
    except (TimeoutError, Exception):
        return None, "failed"


# ---------------------------------------------------------------------------
# Core tube + top-level builder
# ---------------------------------------------------------------------------

def build_core_tube(path, path_samples, params: BraidParams):
    """Smooth core loft along path (same approach as basic_rope.py)."""
    wires = []
    for s in path_samples:
        pl = Plane(origin=s["point"], xDir=s["x_dir"], normal=s["tangent"])
        wires.append(Wire.makeCircle(params.core_radius, pl.origin, pl.zDir))
    return Solid.makeLoft(wires, ruled=True)


def build_braided_rope(path=None, curved=False, params: BraidParams = None):
    """Build core + CW/CCW braided sleeve compound along `path`."""
    if params is None:
        params = BraidParams()

    if path is None:
        if curved:
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

    total_strands = 2 * params.num_strands_per_dir

    # Loft density: at least `samples_per_period` per weave period along the
    # whole path. Period = pitch / N. Bracket between 240 and 1500 to keep
    # build times sane on long/curved paths.
    loft_samples = max(
        240,
        min(
            1500,
            math.ceil(
                params.samples_per_period * params.N * path_length / params.pitch
            ),
        ),
    )

    print(params.summary())
    print(f"  loft_samples = {loft_samples}, path_length = {path_length:.1f} mm")
    if 2.0 * params.p < 1.2:
        print(f"  note: strand minor diameter < 1.2 mm FDM floor; SLA/visualization only")

    print("Generating core tube...")
    core = build_core_tube(path, path_samples, params)

    print(f"Building {total_strands} helical braid strands...")
    strands = []
    method_counts = {"loft": 0, "loft-ruled": 0, "sweep": 0, "failed": 0}
    built = 0
    for direction, _label in [(-1, "CW"), (1, "CCW")]:
        for i in range(params.num_strands_per_dir):
            phase = i * (2.0 * math.pi / params.num_strands_per_dir)
            if direction == 1:
                phase += math.pi / params.num_strands_per_dir
            strand, method = build_braid_strand(
                path_samples,
                path_length,
                params,
                phase,
                direction,
                loft_samples,
            )
            method_counts[method] += 1
            if strand is not None:
                strands.append(strand)
            built += 1
            print(f"\r  strands: {built}/{total_strands}", end="", flush=True)
    print()

    print(
        f"  built via: loft={method_counts['loft']}, "
        f"loft-ruled={method_counts['loft-ruled']}, "
        f"sweep={method_counts['sweep']}, "
        f"failed/skipped={method_counts['failed']} (of {total_strands})"
    )
    return Compound.makeCompound([core] + strands)


# ---------------------------------------------------------------------------
# CLI (matches basic_rope.py exactly so the two can be diffed side by side)
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Academic-grounded braided rope sleeve along a path"
    )
    parser.add_argument("--preview", type=str, help="Export PNG preview to this path")
    parser.add_argument(
        "--curved",
        action="store_true",
        help="Use gentle S-curve path instead of straight",
    )
    parser.add_argument(
        "--float-length",
        type=int,
        default=1,
        help="F: 1 = 1x1 diamond braid (default); 2 = 2x2 regular braid; n*n",
    )
    parser.add_argument(
        "--aspect",
        type=float,
        default=1.6,
        help="Strand cross-section aspect ratio a/b; 1.0 = circle (default 1.6)",
    )
    parser.add_argument(
        "--no-tilt",
        action="store_true",
        help="Disable ellipse tilt to local helix angle",
    )
    args = parser.parse_args()

    params = BraidParams(
        float_length=args.float_length,
        strand_aspect_ratio=args.aspect,
        tilt_to_helix_angle=not args.no_tilt,
    )
    result = build_braided_rope(curved=args.curved, params=params)

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
