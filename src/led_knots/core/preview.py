"""
Render STL meshes to preview images using numpy-stl and matplotlib.
"""

import logging
from pathlib import Path
from typing import Any

from stl import mesh as stl_mesh
from mpl_toolkits import mplot3d
from matplotlib import pyplot

logger = logging.getLogger(__name__)


def render_stl_to_image(
    stl_path: Path,
    image_path: Path,
    preview_config: Any,
) -> None:
    """
    Render an STL file to an image using numpy-stl and matplotlib.

    Args:
        stl_path: Path to the STL file.
        image_path: Path to write the output image (format from extension).
        preview_config: PreviewSettings with image_width, image_height, dpi,
            elevation, azimuth, roll.
    """
    mesh = stl_mesh.Mesh.from_file(str(stl_path))

    fig_width_inches = preview_config.image_width / preview_config.dpi
    fig_height_inches = preview_config.image_height / preview_config.dpi
    figure = pyplot.figure(figsize=(fig_width_inches, fig_height_inches))
    axes = figure.add_subplot(projection='3d')

    axes.add_collection3d(
        mplot3d.art3d.Poly3DCollection(mesh.vectors)
    )

    scale = mesh.points.flatten()
    axes.auto_scale_xyz(scale, scale, scale)

    axes.view_init(
        elev=preview_config.elevation,
        azim=preview_config.azimuth,
        roll=preview_config.roll,
    )

    image_path = Path(image_path)
    image_path.parent.mkdir(parents=True, exist_ok=True)

    ext = image_path.suffix.lower()
    format_map = {'.jpg': 'jpg', '.jpeg': 'jpg', '.png': 'png'}
    fmt = format_map.get(ext, 'png')

    pyplot.savefig(
        str(image_path),
        format=fmt,
        dpi=preview_config.dpi,
        bbox_inches='tight',
    )
    pyplot.close(figure)
    logger.info("Preview image saved to %s", image_path)
