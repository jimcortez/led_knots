"""
Realistic Rope Generator using CadQuery.

Principles from the guide:
1. Macro Form: Single continuous centerline curve.
2. Meso Structure: 3-strand helical logic with dynamic twist (higher twist in straight tension sections).
3. Negative Space/Strand Geometry: Valleys between strands, flattened dominant light-facing planes, asymmetric transitions.
4. Micro Surface: Low spatial frequency micro-faceting instead of high-frequency noise.
"""

import math
from cadquery import Vector, Wire, Plane, Location, Workplane
from cadquery.func import face, spline, loft
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.GCPnts import GCPnts_UniformAbscissa

BASE_OUTER_SIZE = 14.5  # mm (outer radius)
NUM_STRANDS = 3
VALLEY_DEPTH = 3.0  # mm (depth of valleys between strands)
POINTS_PER_STRAND = 6  # Low count intentionally creates micro-faceting

# Twist parameters
BASE_TWIST_RATE = 0.5  # radians per mm of arc length
TENSION_TWIST_MUL = 1.0  # Multiplier for twist in straight sections (tension)


def create_rope_profile(outer_size, num_strands=3, points_per_strand=6, valley_depth=2.0):
    """
    Creates a cross-section face for the rope.
    Uses a small number of points to create micro-faceting.
    Shapes the strands to have a flattened outer face and soft valleys.
    """
    pts = []
    total_points = num_strands * points_per_strand
    for i in range(total_points):
        # Base angle
        angle = 2 * math.pi * i / total_points
        
        # Asymmetry: slight shift to make one side of the strand steeper than the other
        skewed_angle = angle + 0.15 * math.sin(num_strands * angle)
        
        # Shape function for the lobes
        # t goes from 0 (valley) to 1 (peak)
        t = (math.cos(num_strands * skewed_angle) + 1.0) / 2.0
        
        # Flatten the peaks: raise to a power < 1 broadens the peaks and sharpens valleys slightly
        # We want soft valleys, so we don't go too extreme.
        shape = math.pow(t, 0.6)
        
        # Radius
        r = outer_size - valley_depth * (1.0 - shape)
        
        pts.append(Vector(r * math.cos(angle), r * math.sin(angle), 0))
        
    wire = Wire.makePolygon(pts + [pts[0]])
    return face(wire)


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
    else:
        # Fallback (omitted for brevity, spline will use Above branch)
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


def create_strand_segment(length, width, depth):
    """
    Creates a single curved strand segment that will be instanced to form the braid.
    """
    return (
        Workplane("XY")
        # A simple ellipse or rounded rectangle for the strand profile
        .ellipse(length/2, width/2)
        .extrude(depth)
        # Shift coordinate system so the base is at Z=0 and centered
        .translate((0, 0, -depth/2))
        .val()
    )

def main():
    print("Generating centerline path...")
    # A straight path along the Y axis
    path = spline(
        [(0, 0, 0), (0, 100, 0)],
        tgts=[(0, 1, 0), (0, 1, 0)],
    )
    
    path_length = path.Length()
    
    # Generate an underlying base tube
    print("Generating base tube...")
    from cadquery.occ_impl.shapes import Solid
    tube_samples = get_samples(path, 100)
    tube_wires = []
    for s in tube_samples:
        pl = Plane(origin=s["point"], xDir=s["x_dir"], normal=s["tangent"])
        wire = Wire.makeCircle(BASE_OUTER_SIZE - VALLEY_DEPTH, pl.origin, pl.zDir)
        tube_wires.append(wire)
    tube = Solid.makeLoft(tube_wires, ruled=True)

    print("Creating master strand segment...")
    STRAND_LENGTH = 8.0
    STRAND_WIDTH = 3.0
    STRAND_DEPTH = VALLEY_DEPTH * 1.5
    master_strand = create_strand_segment(STRAND_LENGTH, STRAND_WIDTH, STRAND_DEPTH)
    
    print("Instantiating braid texture...")
    placed_strands = []
    
    # We will wrap overlapping chevron patterns around the cylinder
    NUM_BRAIDS = 12  # How many braids around the circumference
    PITCH = 6.0      # Vertical distance between crosses
    
    s_curr = 0.0
    while s_curr <= path_length:
        pt, z_dir, x_dir, y_dir = None, None, None, None
        
        # Manually find the frame
        for i in range(len(tube_samples)-1):
            if tube_samples[i]["arc_length"] <= s_curr <= tube_samples[i+1]["arc_length"]:
                t_samp = tube_samples[i]
                pt = t_samp["point"]
                z_dir = t_samp["tangent"]
                x_dir = t_samp["x_dir"]
                z_dir_vec = Vector(_norm((z_dir.x, z_dir.y, z_dir.z)))
                x_dir_vec = Vector(_norm((x_dir.x, x_dir.y, x_dir.z)))
                y_dir = z_dir_vec.cross(x_dir_vec).normalized()
                break
        
        if pt is None:
            break
            
        angle_step = 2 * math.pi / NUM_BRAIDS
        
        for i in range(NUM_BRAIDS):
            angle = i * angle_step
            outward_normal = (x_dir * math.cos(angle)) + (y_dir * math.sin(angle))
            surface_pt = pt + (outward_normal * (BASE_OUTER_SIZE - VALLEY_DEPTH/2))
            
            # Left-leaning strand
            loc_l = Location(Plane(origin=surface_pt, xDir=z_dir, normal=outward_normal).rotated((0, 0, 35)))
            placed_strands.append(master_strand.moved(loc_l))
            
            # Right-leaning strand (shifted vertically by half a pitch)
            surface_pt_r = surface_pt + (z_dir * (PITCH/2))
            loc_r = Location(Plane(origin=surface_pt_r, xDir=z_dir, normal=outward_normal).rotated((0, 0, -35)))
            placed_strands.append(master_strand.moved(loc_r))
            
        s_curr += PITCH

    print(f"Placed {len(placed_strands)} strand segments!")
    
    from cadquery import Compound
    print("Grouping into final Compound...")
    result = Compound.makeCompound([tube] + placed_strands)
    
    try:
        from yacv_server import show
        show(result, names='braided_rope')
        print("Exported braided_rope to yacv_server!")
        import time
        print("Waiting 60s for frontend requests...")
        time.sleep(60)
    except ImportError:
        print("yacv_server not found.")


if __name__ == '__main__':
    main()
