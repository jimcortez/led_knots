"""
Mathematically Defined Braided Rope Simulation using CadQuery.

Generates a braided tube by utilizing parametric equations that incorporate
radial oscillation (representing the weave) and the Frenet-Serret frame.
"""

import argparse
import math
from pathlib import Path
from cadquery import Vector, Wire, Plane, Edge, Face, Solid, Compound

# Core Dimensions
CORE_RADIUS = 12.0
TUBE_LENGTH = 100.0

# Braid Parameters
NUM_STRANDS_PER_DIR = 100    # Strands in each direction (200 total)
PITCH = 80.0                 # mm per full 360° wrap around the cylinder
STRAND_PROFILE_RADIUS = 0.25 # Radius of the individual strand cross-section
BASE_STRAND_RADIUS = CORE_RADIUS + STRAND_PROFILE_RADIUS

# Weave Oscillation Parameters
# The amplitude defines how far the strand weaves over and under the base radius.
# For dense braids, this can cause self-intersection in the sweep if too aggressive.
WEAVE_AMPLITUDE = STRAND_PROFILE_RADIUS * 0.95
# In a dense braid, weaving over *every* intersecting strand makes the path too jagged.
# In real braids (like standard 1x1 or 2x2), we weave fewer times.
# Let's weave twice per pitch to create the macro pattern without failing the sweep.
WEAVE_FREQUENCY = 10

SPLINE_SAMPLES = 600         # Number of points to sample for the parametric spline (higher resolution for dense weave)

def build_braided_strand(length, base_radius, pitch, phase, direction):
    """
    Build a single braided strand using a mathematical spline and sweep.
    Incorporates a sinusoidal radial displacement to simulate weaving.
    """
    pts = []
    
    for i in range(SPLINE_SAMPLES):
        z = length * (i / (SPLINE_SAMPLES - 1))
        
        # Helical angle around the cylinder
        theta = direction * (z / pitch) * 2 * math.pi + phase
        
        # Radial oscillation: creates the over-and-under weave pattern.
        # It oscillates based on the z-progress and frequency
        # We offset the sine wave phase depending on the direction and strand phase
        # so that crossing CW and CCW strands naturally weave past each other.
        oscillating_radius = base_radius + WEAVE_AMPLITUDE * math.cos(WEAVE_FREQUENCY * (z / pitch) * 2 * math.pi)
        
        x = oscillating_radius * math.cos(theta)
        y = oscillating_radius * math.sin(theta)
        pts.append(Vector(x, y, z))
        
    # Create the 3D spline edge
    path_edge = Edge.makeSpline(pts)
    path_wire = Wire.assembleEdges([path_edge])
    
    # Calculate initial tangent analytically
    # Parameterization in t (where t = z)
    # r(t) = R + A * cos(k*t)
    # x(t) = r(t) * cos(w*t + phi)
    # y(t) = r(t) * sin(w*t + phi)
    # z(t) = t
    # To keep it simple, we take the derivative numerically for the starting plane
    pt_0 = pts[0]
    pt_1 = pts[1]
    
    start_tangent = (pt_1 - pt_0).normalized()
    
    # Construct exactly sweeping profile at t=0
    cross_section_plane = Plane(origin=pt_0, normal=start_tangent)
    
    profile_wire = Wire.makeCircle(STRAND_PROFILE_RADIUS, cross_section_plane.origin, cross_section_plane.zDir)
    profile_face = Face.makeFromWires(profile_wire)
    
    # In CadQuery's lowest-level OCC wrapper, Solid.sweep expects a profile (Wire or Face) and path (Wire)
    strand_solid = Solid.sweep(profile_wire, [], path_wire, makeSolid=True, isFrenet=True)
    return strand_solid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", type=str, help="Path to export preview image")
    args = parser.parse_args()

    print("Generating inner cylindrical core...")
    # Using generic z-directed cylinder as defined by extrude
    core_plane = Plane(origin=Vector(0, 0, 0), normal=Vector(0, 0, 1))
    core_wire = Wire.makeCircle(CORE_RADIUS, core_plane.origin, core_plane.zDir)
    core_face = Face.makeFromWires(core_wire)
    core_tube = Solid.extrudeLinear(
        core_face, 
        core_plane.zDir.normalized().multiply(TUBE_LENGTH)
    )

    print("Building mathematically braided strands...")
    strands = []
    
    for direction, label in [(-1, "CW"), (1, "CCW")]:
        print(f"  -> {label} strands...")
        for i in range(NUM_STRANDS_PER_DIR):
            phase = i * (2 * math.pi / NUM_STRANDS_PER_DIR)
            
            # The CCW strands are offset in phase. 
            # In braided structures, the weave frequency must match properly so 
            # strands don't collide at the same radius.
            offset_phase = phase
            if direction == 1:
                offset_phase += math.pi / NUM_STRANDS_PER_DIR
                
            strand = build_braided_strand(TUBE_LENGTH, BASE_STRAND_RADIUS, PITCH, offset_phase, direction)
            strands.append(strand)
            print(f"     strand {i+1}/{NUM_STRANDS_PER_DIR} generated")

    print(f"Total strands: {len(strands)}")

    print("Assembling compound model...")
    result = Compound.makeCompound([core_tube] + strands)

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

        print(f"Exporting model to preview {args.preview}...")
        with tempfile.NamedTemporaryFile(suffix=".stl") as tf:
            exporters.export(result, tf.name)
            render_stl_to_image(Path(tf.name), Path(args.preview), MockPreviewConfig())
        print("Done.")
    else:
        try:
            from yacv_server import show
            show(result, names='rope_sim')
            print("Model dispatched to yacv-server.")
        except ImportError:
            print("yacv_server not available. The model was built successfully.")


if __name__ == '__main__':
    main()
