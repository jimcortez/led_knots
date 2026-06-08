"""Tests for pyknot point scaling utilities."""

import numpy as np

from led_knots.core.pyknot_utils import scale_pyknot_points


def test_scale_pyknot_points_reserves_padding_on_both_sides():
    """Path span plus tube radius on each side should fit within output bounds."""
    # Unit cube centered at origin; scale into a 100 mm box with 10 mm per-side padding.
    points = np.array(
        [
            [-0.5, -0.5, -0.5],
            [0.5, 0.5, 0.5],
        ],
        dtype=float,
    )
    padding = 10.0

    scaled = scale_pyknot_points(
        points,
        width=100.0,
        height=100.0,
        length=100.0,
        padding=padding,
        preserve_aspect_ratio=False,
    )
    arr = np.array(scaled)
    span = arr.max(axis=0) - arr.min(axis=0)

    assert np.allclose(span, 80.0)
    assert np.allclose(arr.min(axis=0), 0.0)
    assert np.allclose(arr.max(axis=0), 80.0)
    assert np.allclose(span + 2 * padding, 100.0)
