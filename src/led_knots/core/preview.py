"""
Render STL meshes to preview images using numpy-stl and matplotlib.
"""

import logging
from pathlib import Path
from typing import Any

import numpy as np
from stl import mesh as stl_mesh
from mpl_toolkits import mplot3d
from matplotlib import pyplot
from matplotlib.colors import LightSource

logger = logging.getLogger(__name__)

# Shading range so faces away from light are visible but clearly darker (not black)
_SHADE_MIN = 0.35
_SHADE_MAX = 0.95


def render_stl_to_image(
    stl_path: Path,
    image_path: Path,
    preview_config: Any,
) -> None:
    """
    Render an STL file to an image using numpy-stl and matplotlib.

    Axis and grid are hidden so only the model is visible on a white background.
    """
    image_path = Path(image_path)
    image_path.parent.mkdir(parents=True, exist_ok=True)

    mesh = stl_mesh.Mesh.from_file(str(stl_path))

    fig_width_inches = preview_config.image_width / preview_config.dpi
    fig_height_inches = preview_config.image_height / preview_config.dpi
    figure = pyplot.figure(figsize=(fig_width_inches, fig_height_inches), facecolor='white')
    axes = figure.add_subplot(projection='3d')
    axes.set_facecolor('white')

    # Lambert shading from face normals so depth is visible
    normals = np.array(mesh.normals, dtype=np.float64)
    ls = LightSource(
        azdeg=preview_config.light_azimuth,
        altdeg=preview_config.light_elevation,
    )
    shade = ls.shade_normals(normals, fraction=1.0)
    shade_min, shade_max = shade.min(), shade.max()
    span = (shade_max - shade_min) or 1.0
    shade_normalized = (shade - shade_min) / span
    intensity = _SHADE_MIN + (_SHADE_MAX - _SHADE_MIN) * shade_normalized
    r, g, b = preview_config._color_rgb
    opacity = preview_config.opacity
    base_rgb = np.array([r, g, b])
    facecolors_rgb = np.outer(intensity, base_rgb)

    collection = mplot3d.art3d.Poly3DCollection(
        mesh.vectors,
        edgecolors=None,
        linewidths=0,
    )
    collection.set_alpha(opacity)
    collection.set_facecolor(facecolors_rgb)
    axes.add_collection3d(collection)

    axes.set_axis_off()
    points = mesh.points
    x_min, x_max = points[:, 0].min(), points[:, 0].max()
    y_min, y_max = points[:, 1].min(), points[:, 1].max()
    z_min, z_max = points[:, 2].min(), points[:, 2].max()
    margin = 0.05
    pad_x = (x_max - x_min) * margin if x_max > x_min else 0.5
    pad_y = (y_max - y_min) * margin if y_max > y_min else 0.5
    pad_z = (z_max - z_min) * margin if z_max > z_min else 0.5
    axes.set_xlim(x_min - pad_x, x_max + pad_x)
    axes.set_ylim(y_min - pad_y, y_max + pad_y)
    axes.set_zlim(z_min - pad_z, z_max + pad_z)
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
    pyplot.savefig(str(image_path), format=fmt, dpi=preview_config.dpi, bbox_inches='tight')
    pyplot.close(figure)
    logger.info("Preview image saved to %s", image_path)
