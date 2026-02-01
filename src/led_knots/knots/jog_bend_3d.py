"""
Jog bend 3D knot creation using CadQuery.

Creates a jog bend 3D knot by sweeping an LED circle cross-section
along a 3D jog bend path. The path construction is the focus here;
the cross-section geometry is handled by the led_circle module.

The LED strip cross-section is ribbon-like (wider than tall):
- Flexible axis: Can bend around Y (short dimension)
- Rigid axis: Cannot bend sharply around X (wide dimension)
- Twist axis: Can twist around Z (along the path tangent)

Uses build_ribbon_aux_spine(path, config) to constrain twist from config
(min_90_degree_twist_distance) and align bends with the flexible axis.
"""

import logging
from cadquery.func import spline, sweep

from led_knots.core import (
    get_config,
    render_part,
    build_ribbon_aux_spine,
    create_led_circle_face,
)

logger = logging.getLogger(__name__)


def main():
    """Generate and render the jog bend 3D knot."""
    logging.basicConfig(level=logging.DEBUG)
    config = get_config(name="Jog Bend 3D Knot", description="Create and render a jog bend 3D knot")

    # Use output bounds from config (path must fit; twist must fit min_90_degree_twist_distance or error is raised)
    width = config.output_bounds.width
    height = config.output_bounds.height
    spine_offset_radius = 5.0

    # Create the sweep path from config bounds
    path = spline(
        [
            (0, 0, 0),
            (width / 2, width / 2, height / 2),
            (width, width, height),
        ],
        tgts=[
            (0, 0, 1),
            (0, 1, 0),
            (0, 0, 1),
        ],
    )

    # Raises ValueError if twist cannot be achieved within min_90_degree_twist_distance
    aux_spine, initial_rotation = build_ribbon_aux_spine(
        path,
        config,
        num_samples=40,
        spine_offset_radius=spine_offset_radius,
    )

    faces = create_led_circle_face(
        **config.tube_settings.to_led_circle_face_kwargs(
            orient_to_path=path,
            rotation_z=initial_rotation,
        )
    )

    result = sweep(faces, path, aux=aux_spine)
    render_part(
        result,
        config,
        path=path,
        aux=aux_spine,
        face_kwargs={"rotation_z": initial_rotation},
    )


if __name__ == "__main__":
    main()
