"""Utilities for scaling and transforming pyknot-generated point data."""

from __future__ import annotations

from typing import Tuple, Union

import numpy as np


def scale_pyknot_points(
    points: np.ndarray,
    width: float,
    height: float,
    length: float,
    padding: Union[float, Tuple[float, float, float]] = 0.0,
    preserve_aspect_ratio: bool = True,
) -> list[tuple[float, float, float]]:
    """
    Scale pyknot points to fit within a bounding box while preserving aspect ratio.

    Calculates the bounding box of the input points and scales them uniformly
    to fit within the specified width, height, and length constraints,
    optionally applying padding on each dimension before scaling.

    Args:
        points: numpy array of shape (n, 3) containing (x, y, z) coordinates
        width: Target width for the x dimension (mm)
        height: Target height for the y dimension (mm)
        length: Target length for the z dimension (mm)
        padding: Optional padding to subtract from (width, height, length).
                 If a single float, the same padding is applied to all three
                 dimensions. If a tuple of three numbers, interpreted as
                 (width_padding, height_padding, length_padding).
        preserve_aspect_ratio: When True (default), uses a uniform scale factor
            so the knot preserves its proportions. When False, scales each axis
            independently to fill the (padded) bounding box.

    Returns:
        List of scaled (x, y, z) coordinate tuples in the positive octant.
    """
    min_x, max_x = points[:, 0].min(), points[:, 0].max()
    min_y, max_y = points[:, 1].min(), points[:, 1].max()
    min_z, max_z = points[:, 2].min(), points[:, 2].max()

    span_x = max_x - min_x
    span_y = max_y - min_y
    span_z = max_z - min_z

    if isinstance(padding, (tuple, list)) and len(padding) == 3:
        pad_w, pad_h, pad_l = padding
    else:
        pad_w = pad_h = pad_l = float(padding)

    effective_width = width - pad_w
    effective_height = height - pad_h
    effective_length = length - pad_l

    scale_x = effective_width / span_x if span_x > 0 else 1.0
    scale_y = effective_height / span_y if span_y > 0 else 1.0
    scale_z = effective_length / span_z if span_z > 0 else 1.0

    if preserve_aspect_ratio:
        scale_factor = min(scale_x, scale_y, scale_z)
        scaled = points * scale_factor
    else:
        scales = np.array([scale_x, scale_y, scale_z], dtype=float)
        scaled = points * scales

    min_scaled = scaled.min(axis=0)
    translated = scaled - min_scaled

    return [(float(p[0]), float(p[1]), float(p[2])) for p in translated]
