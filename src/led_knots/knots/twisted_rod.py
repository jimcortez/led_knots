"""
Twisted rod knot creation using CadQuery.

Creates a straight vertical pipe with a 90-degree twist by sweeping a 
cross-section along a path with an auxiliary spine that controls the rotation.
The end face is rotated 90 degrees around the z-axis from the first face.
"""

import math
from cadquery.func import spline, sweep

from led_knots.core import get_config, render_part
from led_knots.core import create_led_circle_face


def create_helix_points(height, radius, total_rotation_deg, num_points=50):
    """
    Create points along a helix for the auxiliary spine.
    
    The helix spirals around the z-axis while moving from z=0 to z=height.
    The total angular sweep controls the twist of the swept shape.
    
    Args:
        height: Height of the helix (mm)
        radius: Radius of the helix (mm)
        total_rotation_deg: Total angular rotation of the helix (degrees)
        num_points: Number of points to generate
    
    Returns:
        List of (x, y, z) tuples representing helix points
    """
    points = []
    total_rotation_rad = math.radians(total_rotation_deg)
    
    for i in range(num_points):
        t = i / (num_points - 1)  # Parameter from 0 to 1
        
        # Angular position (starts at 0, ends at total_rotation)
        theta = t * total_rotation_rad
        
        # Helix position
        x = radius * math.cos(theta)
        y = radius * math.sin(theta)
        z = t * height
        
        points.append((x, y, z))
    
    return points


# Load configuration
config = get_config(
    name="Twisted Rod Knot",
    description="Create and render a twisted rod knot (90-degree rotation)"
)

# Create the twisted rod
height = config.output_bounds.height
total_rotation = 90.0  # Total twist in degrees
aux_radius = 10.0  # Radius of the auxiliary helix

# Create the main sweep path (straight line along z-axis)
path = spline([(0, 0, 0), (0, 0, height)], tgts=[(0, 0, 1), (0, 0, 1)])

# Create the auxiliary spine (helix) that controls the twist
# The helix spirals around the main path, causing the cross-section to rotate
helix_points = create_helix_points(
    height=height,
    radius=aux_radius,
    total_rotation_deg=total_rotation,
    num_points=50
)
aux_spine = spline(helix_points)

# Create the cross-section face
faces = create_led_circle_face(
    **config.tube_settings.to_led_circle_face_kwargs(orient_to_path=path)
)

# Sweep the face along the path with the auxiliary spine controlling rotation
result = sweep(faces, path, aux=aux_spine)

# Render the part
render_part(result, config)
