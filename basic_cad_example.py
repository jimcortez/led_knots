"""
Minimal CadQuery example: LED circle with pyramid bands via multisection sweep.

Triangle height at each slice = f(arc_length, PYRAMID_DEPTH). The pyramid pattern
is defined by distance along the curve; more slices = higher resolution.

Uses cadquery + OCP (GCPnts_UniformAbscissa) for uniform arc-length sampling.
"""

import math
from cadquery import Vector, Wire
from cadquery.func import *
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.GCPnts import GCPnts_UniformAbscissa

TRIANGLE_WIDTH = 2.0  # mm (base along circle)
PYRAMID_DEPTH = 2.0  # mm (peak triangle height at pyramid crests)
RIDGE_WIDTH = 2.0  # mm (pyramid base along path)
RIDGE_SPACING = 1.0  # mm (gap between pyramids)
BASE_OUTER_SIZE = 14.5  # mm (outer radius of the circle)
MIN_TRIANGLE_HEIGHT = 0.01  # avoid 0 for consistent face count (sweep requirement)


def create_solid_circle_face(outer_size=14.5, triangle_height=0.0, num_triangles=None):
    """
    Solid circle: outer ring with triangles computed mathematically as a single polygon.
    Avoids expensive 2D boolean operations (fuse/clean), giving massive speedup.
    """
    if not num_triangles or triangle_height <= 0:
        return face(circle(outer_size))

    pts = []
    half_angle = (TRIANGLE_WIDTH / 2) / outer_size
    angle_step = 2 * math.pi / num_triangles

    for i in range(num_triangles):
        angle_center = i * angle_step
        angle_start = angle_center - half_angle
        angle_end = angle_center + half_angle

        # 1. Base corner (start of triangle)
        pts.append(Vector(outer_size * math.cos(angle_start), outer_size * math.sin(angle_start), 0))
        
        # 2. Apex (peak of triangle)
        r_apex = outer_size + max(triangle_height, MIN_TRIANGLE_HEIGHT)
        pts.append(Vector(r_apex * math.cos(angle_center), r_apex * math.sin(angle_center), 0))
        
        # 3. Base corner (end of triangle)
        # (The Wire.makePolygon will automatically draw a straight chord to the next triangle's start)
        pts.append(Vector(outer_size * math.cos(angle_end), outer_size * math.sin(angle_end), 0))

    # Close the loop and convert to a face
    wire = Wire.makePolygon(pts + [pts[0]])
    return face(wire)


def pyramid_ridge_height(s, path_length, ridge_width, ridge_spacing, ridge_depth):
    """Triangle height at arc length s. Triangular wave: 0 -> peak (ridge_depth) -> 0."""
    pitch = ridge_width + ridge_spacing
    if pitch <= 0:
        return ridge_depth
    pos_in_pitch = (s % pitch) / pitch
    if pos_in_pitch <= 0.5:
        return 2 * pos_in_pitch * ridge_depth
    return 2 * (1 - pos_in_pitch) * ridge_depth


def _norm(v):
    """Normalize vector (x, y, z)."""
    d = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) ** 0.5
    return (v[0] / d, v[1] / d, v[2] / d) if d > 1e-10 else v


def get_samples(path, num_sections, dense=200):
    """Sample path at evenly spaced arc lengths. Uses GCPnts_UniformAbscissa for single-edge paths,
    parallel-transported xDir to prevent twist."""
    path_length = path.Length()
    edges = path.Edges()

    # Use OCP GCPnts_UniformAbscissa for single-edge paths (e.g. spline)
    if len(edges) == 1 and num_sections >= 2:
        edge = edges[0]
        adaptor = BRepAdaptor_Curve(edge.wrapped)
        u1, u2 = adaptor.FirstParameter(), adaptor.LastParameter()
        dist = GCPnts_UniformAbscissa(adaptor, num_sections, u1, u2)
        if not dist.IsDone():
            t_values = [i / (num_sections - 1) if num_sections > 1 else 1.0 for i in range(num_sections)]
        else:
            t_values = []
            for i in range(1, dist.NbPoints() + 1):
                t_ocp = dist.Parameter(i)
                t_cq = (t_ocp - u1) / (u2 - u1) if u2 > u1 else 0.0
                t_values.append(t_cq)
    elif len(edges) == 1 and num_sections == 1:
        t_values = [1.0]
    else:
        # Multi-edge Wire: fall back to dense sampling + interpolation
        dense_samples = []
        prev_pos = None
        cumulative = 0.0
        for i in range(dense):
            t = i / (dense - 1) if dense > 1 else 1.0
            pt = path.positionAt(t)
            if prev_pos is not None:
                dx, dy, dz = pt.x - prev_pos.x, pt.y - prev_pos.y, pt.z - prev_pos.z
                cumulative += (dx * dx + dy * dy + dz * dz) ** 0.5
            prev_pos = pt
            dense_samples.append({"t": t, "arc_length": cumulative})

        def t_for_s(s_target):
            if s_target <= 0:
                return 0.0
            if s_target >= path_length:
                return 1.0
            for j in range(len(dense_samples) - 1):
                s_lo, s_hi = dense_samples[j]["arc_length"], dense_samples[j + 1]["arc_length"]
                if s_lo <= s_target <= s_hi:
                    t_lo, t_hi = dense_samples[j]["t"], dense_samples[j + 1]["t"]
                    if s_hi - s_lo > 1e-10:
                        frac = (s_target - s_lo) / (s_hi - s_lo)
                        return t_lo + frac * (t_hi - t_lo)
                    return t_lo
            return 1.0

        t_values = [
            t_for_s(i * path_length / (num_sections - 1) if num_sections > 1 else path_length)
            for i in range(num_sections)
        ]

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
            dot = prev_local_x[0] * tangent[0] + prev_local_x[1] * tangent[1] + prev_local_x[2] * tangent[2]
            px = prev_local_x[0] - dot * tangent[0]
            py = prev_local_x[1] - dot * tangent[1]
            pz = prev_local_x[2] - dot * tangent[2]
            pm = (px * px + py * py + pz * pz) ** 0.5
            if pm > 1e-6:
                prev_local_x = (px / pm, py / pm, pz / pm)
        x_dir = Vector(prev_local_x[0], prev_local_x[1], prev_local_x[2])
        samples.append({
            "point": pt,
            "tangent": tg,
            "x_dir": x_dir,
            "arc_length": s,
        })
    return samples


path = spline(
    [(0, 0, 0), (0, 100, 100)],
    tgts=[(0, 0, 1), (0, 1, 0)],
)
path_length = path.Length()

num_triangles = max(1, int(2 * math.pi * BASE_OUTER_SIZE / TRIANGLE_WIDTH))
num_slices = 1000
samples = get_samples(path, num_slices)

faces = []
for sample in samples:
    s = sample["arc_length"]
    # Height from distance along curve; PYRAMID_DEPTH sets peak
    th = pyramid_ridge_height(s, path_length, RIDGE_WIDTH, RIDGE_SPACING, PYRAMID_DEPTH) if num_triangles else 0
    th = max(MIN_TRIANGLE_HEIGHT, th) if num_triangles else 0
    f = create_solid_circle_face(BASE_OUTER_SIZE, triangle_height=th, num_triangles=num_triangles)
    pl = Plane(origin=sample["point"], xDir=sample["x_dir"], normal=sample["tangent"])
    f = f.moved(Location(pl))
    faces.append(f)

print(f'generated {len(faces)} faces')

# CadQuery sweep doesn't expose OpenCASCADE's transition mode (Transformed vs RoundCorner).
# For straighter transitions: use loft(ruled=True) - ruled surfaces between sections.
# Trade-off: loft doesn't follow path; sweep follows path but uses smooth interpolation.
USE_RULED_LOFT = True  # True = straighter, False = sweep along path
if USE_RULED_LOFT:
    result = loft(faces, ruled=True)
else:
    result = sweep(faces, path)

# --- Export or show ---
# from cadquery.exporters import export; export(result, "pyramid_ridges.stl")
# from cadquery.vis import show; show(result)

from cadquery_web_viewer import show
show(result, names='test2')

