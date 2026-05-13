"""
Tube Rope Generator using CadQuery.

Creates a cylindrical core with a tight tubular braid sleeve.
The braid is formed by lofting continuous helical strands — each strand
is a thin, flat ribbon that wraps around the core in a helix path.
Two opposing helical sets (CW and CCW) create a diamond/herringbone pattern
that reads as interlaced braid under tension.

Key design insight:
- Each strand is a dedicated lofted solid with ~200 cross-sections along a helix
- The cross-sections are thin rectangles (flat ribbons) placed with a stable
  parallel-transported frame to avoid twist/flip artifacts
- CW and CCW sets offset by half a phase to create clean diamonds at crossings
"""

import math
from cadquery import Vector, Wire, Plane, Location, Workplane, Compound
from cadquery.occ_impl.shapes import Solid
from cadquery.func import face, loft

# Core Dimensions
CORE_RADIUS = 12.0
TUBE_LENGTH = 100.0

# Braid Parameters
NUM_STRANDS_PER_DIR = 5     # Strands in each direction
PITCH = 50.0                 # mm per full 360° wrap of a strand
STRAND_PROFILE_RADIUS = 4.0  # Radius of the individual strand "string"
STRAND_RADIUS = CORE_RADIUS + STRAND_PROFILE_RADIUS

LOFT_SAMPLES = 300           # Samples per strand (higher = smoother)
STRAND_START = 2.0           # mm from start to avoid end-cap warping
STRAND_END_OFFSET = 2.0      # mm from end to avoid end-cap warping


def _norm(v):
    d = math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)
    return (v[0]/d, v[1]/d, v[2]/d) if d > 1e-10 else v


def _cross(a, b):
    return (
        a[1]*b[2] - a[2]*b[1],
        a[2]*b[0] - a[0]*b[2],
        a[0]*b[1] - a[1]*b[0],
    )


def build_helix_strand(length, radius, pitch, phase, direction):
    """
    Build a single continuous helical strand using loft.
    The cross-section is a thin flat rectangle (ribbon).
    Parallel-transport ensures the frame doesn't flip.
    """
    z_start = STRAND_START
    z_end = length - STRAND_END_OFFSET
    strand_length = z_end - z_start

    # 1. Compute helix sample points and stable parallel-transported frames
    pts = []
    tangents = []
    for i in range(LOFT_SAMPLES):
        t = i / (LOFT_SAMPLES - 1)
        z = z_start + t * strand_length
        angle = direction * (z / pitch) * 2 * math.pi + phase

        r = radius
        x = r * math.cos(angle)
        y = r * math.sin(angle)
        pts.append((x, y, z))

        # Analytic tangent of the helix
        dtheta = direction * 2 * math.pi / pitch
        dx = -r * math.sin(angle) * dtheta
        dy =  r * math.cos(angle) * dtheta
        dz = 1.0
        tangents.append(_norm((dx, dy, dz)))

    # Parallel transport the x_dir (lies on cylinder surface, circumferential)
    # Seed: the circumferential direction at the start
    t0 = tangents[0]
    # Outward radial at start
    n0 = _norm((pts[0][0], pts[0][1], 0))
    # Circumferential: tangent projected onto the plane perpendicular to the radial outward
    # Actually, the strand is WIDE in the circumferential direction.
    # We want the strand to lie flat on the cylinder surface.
    # Normal to the surface = outward radial (n0).
    # Width direction (x_dir) = helix tangent component on the surface tangent plane
    #   = remove the outward component from the helix tangent, then normalize

    dot = t0[0]*n0[0] + t0[1]*n0[1] + t0[2]*n0[2]
    x_raw = (t0[0] - dot*n0[0], t0[1] - dot*n0[1], t0[2] - dot*n0[2])
    x_dirs = [_norm(x_raw)]

    for i in range(1, LOFT_SAMPLES):
        tang = tangents[i]
        # Project previous x_dir perpendicular to current tangent (parallel transport)
        prev_x = x_dirs[-1]
        dot = prev_x[0]*tang[0] + prev_x[1]*tang[1] + prev_x[2]*tang[2]
        proj = (prev_x[0] - dot*tang[0],
                prev_x[1] - dot*tang[1],
                prev_x[2] - dot*tang[2])
        x_dirs.append(_norm(proj))

    # 2. Build cross-section wires and loft
    wires = []

    for i in range(LOFT_SAMPLES):
        pt = Vector(*pts[i])
        tang = Vector(*tangents[i])
        x_dir = Vector(*x_dirs[i])
        # normal to surface (outward radial)
        n_raw = _norm((pts[i][0], pts[i][1], 0))
        outward = Vector(*n_raw)

        pl = Plane(origin=pt, xDir=x_dir, normal=outward)
        # Circular cross-section: radius = STRAND_PROFILE_RADIUS
        wire = Wire.makeCircle(STRAND_PROFILE_RADIUS, pl.origin, pl.zDir)
        wires.append(wire)

    return Solid.makeLoft(wires, ruled=False)


def main():
    print("Generating inner cylindrical core...")
    core_wires = []
    for i in range(10):
        z = i / 9 * TUBE_LENGTH
        pl = Plane(origin=Vector(0, 0, z), xDir=Vector(1, 0, 0), normal=Vector(0, 0, 1))
        core_wires.append(Wire.makeCircle(CORE_RADIUS, pl.origin, pl.zDir))
    core_tube = Solid.makeLoft(core_wires, ruled=True)

    print("Building helical strands...")
    strands = []
    for direction, label in [(-1, "CW"), (1, "CCW")]:
        print(f"  -> {label} strands...")
        for i in range(NUM_STRANDS_PER_DIR):
            phase = i * (2 * math.pi / NUM_STRANDS_PER_DIR)
            # Offset the CCW strands by half a diamond pitch to create proper interlace
            if direction == 1:
                phase += math.pi / NUM_STRANDS_PER_DIR
            strand = build_helix_strand(TUBE_LENGTH, STRAND_RADIUS, PITCH, phase, direction)
            strands.append(strand)
            print(f"     strand {i+1}/{NUM_STRANDS_PER_DIR} done")

    print(f"Total strands: {len(strands)}")

    print("Assembling compound...")
    result = Compound.makeCompound([core_tube] + strands)

    try:
        from yacv_server import yacv, show
        show(result, names='tube_rope')
    except ImportError:
        print("yacv_server not available.")


if __name__ == '__main__':
    main()
