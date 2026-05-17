"""
Minimal CadQuery example: LED circle with pyramid bands via instancing.

Creates a smooth tube and instances individual 3D pyramids over its surface 
instead of doing a dense multi-section loft. Drastically improves speed and
reduces the rendering load.
"""

import math
from cadquery import Vector, Wire, Compound, Plane, Location, Workplane
from cadquery.func import circle, face, spline, loft
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.GCPnts import GCPnts_UniformAbscissa

TRIANGLE_WIDTH = 2.0  # mm (base along circle)
PYRAMID_DEPTH = 2.0  # mm (peak triangle height)
RIDGE_WIDTH = 2.0  # mm (pyramid base along path)
RIDGE_SPACING = 1.0  # mm (gap between pyramids)
BASE_OUTER_SIZE = 14.5  # mm (outer radius of the circle)

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
            "t": t,
            "point": pt,
            "tangent": tg,
            "x_dir": x_dir,
            "arc_length": s,
        })
    return samples

def create_master_pyramid(length_along_path, width_along_circ, depth):
    """
    Creates a single true 4-sided pyramid.
    Base size is `length_along_path` by `width_along_circ`.
    Height is `depth`.
    Orientation: Points directly UP (+Z).
    """
    return (
        Workplane("XY")
        .rect(length_along_path, width_along_circ)
        .workplane(offset=depth)
        .rect(0.001, 0.001)
        .loft(ruled=True)
        .val()
    )

def get_frame(target_s, all_samples, path):
    """Interpolate to find exact coordinate and twist-free frame at specific arc length s."""
    if target_s <= all_samples[0]["arc_length"]:
        t = all_samples[0]["t"]
        x_dir = all_samples[0]["x_dir"]
    elif target_s >= all_samples[-1]["arc_length"]:
        t = all_samples[-1]["t"]
        x_dir = all_samples[-1]["x_dir"]
    else:
        # Interpolate between closest samples
        for i in range(len(all_samples)-1):
            s1 = all_samples[i]["arc_length"]
            s2 = all_samples[i+1]["arc_length"]
            if s1 <= target_s <= s2:
                f = (target_s - s1) / (s2 - s1) if s2 > s1 else 0
                t = all_samples[i]["t"] + f * (all_samples[i+1]["t"] - all_samples[i]["t"])
                
                xd1, xd2 = all_samples[i]["x_dir"], all_samples[i+1]["x_dir"]
                x_dir = Vector(
                    xd1.x + f*(xd2.x - xd1.x),
                    xd1.y + f*(xd2.y - xd1.y),
                    xd1.z + f*(xd2.z - xd1.z)
                )
                break
                
    pt = path.positionAt(t)
    tg = path.tangentAt(t)
    
    tangent = Vector(_norm((tg.x, tg.y, tg.z)))
    x_dir = Vector(_norm((x_dir.x, x_dir.y, x_dir.z)))
    
    # Re-orthogonalize x_dir against the precise tangent just in case interpolation drifted it slightly
    dot = x_dir.dot(tangent)
    x_dir = (x_dir - tangent * dot).normalized()
    
    return pt, tangent, x_dir

def main():
    path = spline(
        [(0, 0, 0), (0, 100, 100)],
        tgts=[(0, 0, 1), (0, 1, 0)],
    )
    path_length = path.Length()
    
    num_triangles = max(1, int(2 * math.pi * BASE_OUTER_SIZE / TRIANGLE_WIDTH))
    
    print("Generating tube samples...")
    # Generate an underlying smooth tube. We don't need 1000 slices just to draw a bendy tube.
    tube_slices = 100
    tube_samples = get_samples(path, tube_slices)
    
    print("Lofting base tube...")
    from cadquery.occ_impl.shapes import Solid
    tube_wires = []
    for s in tube_samples:
        # Create a circle directly in 3D space avoiding CQ multimethod stack
        pl = Plane(origin=s["point"], xDir=s["x_dir"], normal=s["tangent"])
        wire = Wire.makeCircle(BASE_OUTER_SIZE, pl.origin, pl.zDir)
        tube_wires.append(wire)
    tube = Solid.makeLoft(tube_wires, ruled=True)

    
    print("Creating master pyramid...")
    master_pyramid = create_master_pyramid(RIDGE_WIDTH, TRIANGLE_WIDTH, PYRAMID_DEPTH)
    
    print("Instantiating pyramids along surface...")
    placed_pyramids = []
    pitch = RIDGE_WIDTH + RIDGE_SPACING
    
    # The center of the first row of pyramids
    s_curr = RIDGE_WIDTH / 2.0
    
    while s_curr <= path_length:
        pt, z_dir, x_dir = get_frame(s_curr, tube_samples, path)
        y_dir = z_dir.cross(x_dir).normalized() # Binormal
        
        angle_step = 2 * math.pi / num_triangles
        for i in range(num_triangles):
            angle = i * angle_step
            
            # Normal vector wrapping around the circumference
            outward_normal = (x_dir * math.cos(angle)) + (y_dir * math.sin(angle))
            
            # Place instance on the surface bounds
            surface_pt = pt + (outward_normal * BASE_OUTER_SIZE)
            
            # The master pyramid z-axis is pointing UP. We want it pointing OUT of the tube.
            # Its x-axis goes along the length, so it aligns with path tangent (z_dir).
            loc = Location(Plane(origin=surface_pt, xDir=z_dir, normal=outward_normal))
            placed_pyramids.append(master_pyramid.moved(loc))
            
        s_curr += pitch
    
    print(f"Placed {len(placed_pyramids)} discrete pyramid instances!")
    
    print("Grouping into final Compound...")
    result = Compound.makeCompound([tube] + placed_pyramids)
    
    # from cadquery.exporters import export; export(result, "pyramids_instanced.stl")
    
    try:
        from cadquery_web_viewer import show
        show(result, names='test_instanced')
        print("Displayed in cadquery-web-viewer.")
    except ImportError:
        print("cadquery-web-viewer not found. Skipping display.")

if __name__ == "__main__":
    main()
