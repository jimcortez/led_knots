"""Utilities for building, scaling and transforming pyknot point data."""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Sequence, Tuple, Union

import numpy as np

if TYPE_CHECKING:
    from pyknotid.representations.representation import Representation
    from pyknotid.spacecurves import Knot


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
        padding: Per-side clearance (mm) reserved for the swept tube profile.
                 Subtracted from both sides of each axis before scaling, so the
                 path centerline fits in (width - 2*pad_w) x (height - 2*pad_h)
                 x (length - 2*pad_l). If a single float, the same padding is
                 applied on every side of all three dimensions. If a tuple of
                 three numbers, interpreted as (width_padding, height_padding,
                 length_padding) per side.
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

    effective_width = width - 2 * pad_w
    effective_height = height - 2 * pad_h
    effective_length = length - 2 * pad_l

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


def dt_code_for(name: str) -> List[int]:
    """
    Look up the Dowker-Thistlethwaite code of a named knot.

    Reads pyknotid's bundled catalogue, so names are Rolfsen / Knot Atlas
    identifiers such as '9_35' or '10_1'. Preferred over pasting DT codes by
    hand, since the catalogue's codes are already in the sign convention
    pyknotid's DT parser expects.

    Args:
        name: Rolfsen identifier, e.g. '10_1'.

    Returns:
        The DT code as a list of ints.

    Raises:
        ValueError: If no catalogue entry matches, or the entry has no DT code.
    """
    from pyknotid.catalogue import get_knot

    entry = get_knot(name)
    if entry is None:
        raise ValueError(f"No catalogue entry named {name!r}")
    if entry.dt_code is None:
        raise ValueError(f"Catalogue entry {name!r} has no DT code")
    return [int(n) for n in entry.dt_code.split()]


def dowker_to_representation(dt_code: Sequence[int]) -> "Representation":
    """
    Build a pyknotid Representation from a DT code.

    Crossing signs are chosen by pyknotid's orientation solver, so the
    chirality of the result is arbitrary but self-consistent. A DT code does
    not determine handedness on its own.

    Args:
        dt_code: DT code as a sequence of ints.

    Returns:
        A pyknotid Representation of the knot.
    """
    from pyknotid.representations.dtnotation import DTNotation

    # DTNotation reads a bare list as one component per entry, which then fails
    # its own link check, so hand it the space-separated string form instead.
    notation = DTNotation(" ".join(str(n) for n in dt_code))
    return notation.representation()


def resample_closed_points(points: np.ndarray, num_points: int) -> np.ndarray:
    """
    Arc-length resample a closed polyline through its own vertices.

    Linear interpolation is deliberate. A cubic spline through the same
    vertices (scipy splprep, or pyknotid's Knot.interpolate) overshoots at
    right-angle corners badly enough to push strands through each other and
    silently change the knot type.

    Args:
        points: Array of shape (n, 3). Treated as a closed loop; the point
            closing the loop must NOT already be repeated at the end.
        num_points: Number of points in the resampled loop.

    Returns:
        Array of shape (num_points, 3), evenly spaced by arc length, with the
        closing point again left off the end.
    """
    closed = np.vstack([points, points[:1]])
    segments = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    u = np.concatenate([[0.0], np.cumsum(segments)])
    u /= u[-1]
    t = np.linspace(0.0, 1.0, num_points, endpoint=False)
    return np.column_stack([np.interp(t, u, closed[:, i]) for i in range(3)])


def relax_knot_points(
    points: np.ndarray,
    steps: int = 400,
    num_points: int = 240,
    thickness: float = 1.2,
    stiffness: float = 0.25,
) -> np.ndarray:
    """
    Relax a closed curve toward a rounder conformation of the same knot.

    pyknotid lays a knot out on a rectilinear grid, which is topologically
    correct but looks nothing like the drawings on the Knot Atlas. This runs a
    curve-shortening flow (Laplacian smoothing) against a short-range
    self-repulsion holding non-adjacent strands apart, which is enough to pull
    the grid layout into a recognisable shape.

    Cosmetic only: this is not an ideal-knot solver, and nothing here proves
    the knot type is preserved. Verify with Knot.identify() if you move off the
    defaults, since a strand pushed through another gives a different knot with
    no error raised.

    Args:
        points: Array of shape (n, 3) describing a closed loop.
        steps: Relaxation iterations. Cost is O(steps * num_points^2); 400
            steps at 240 points takes a few seconds.
        num_points: Points to resample to before relaxing.
        thickness: Self-repulsion radius, in units of mean segment length.
            The parameter that matters. Near 1 the curve settles into a flat,
            diagram-like conformation; much above ~2.5 it inflates into a
            genuinely three-dimensional tangle that reads as messier, not
            cleaner, from a fixed viewpoint.
        stiffness: Per-step weight of the smoothing term.

    Returns:
        Array of shape (num_points, 3), at roughly the input's scale.
    """
    p = resample_closed_points(points, num_points)
    segment = np.mean(
        np.linalg.norm(np.diff(np.vstack([p, p[:1]]), axis=0), axis=1)
    )
    p = p / segment

    index = np.arange(num_points)
    separation = np.abs(index[:, None] - index[None, :])
    separation = np.minimum(separation, num_points - separation)
    non_adjacent = separation > 3

    for _ in range(steps):
        laplacian = 0.5 * (np.roll(p, 1, axis=0) + np.roll(p, -1, axis=0)) - p
        p = p + stiffness * laplacian

        offsets = p[:, None, :] - p[None, :, :]
        distances = np.linalg.norm(offsets, axis=2)
        overlapping = non_adjacent & (distances < thickness) & (distances > 1e-9)
        if overlapping.any():
            units = np.zeros_like(offsets)
            positive = distances > 1e-9
            units[positive] = offsets[positive] / distances[positive][:, None]
            weights = np.where(
                overlapping, (thickness - distances) / thickness, 0.0
            )
            p = p + 0.5 * np.einsum("ij,ijk->ik", weights, units)

        p = resample_closed_points(p, num_points)

    return p * segment


def dowker_to_knot(
    dt_code: Sequence[int],
    num_points: int = 300,
    z_stretch: float = 5.0,
    smooth_passes: int = 2,
    window_len: int = 9,
    relax_steps: int = 0,
    verbose: bool = False,
) -> "Knot":
    """
    Build a plottable pyknotid Knot space curve from a DT code.

    pyknotid's Representation.space_curve() returns an *open* rectilinear
    polyline of ~100 vertices whose z span is an order of magnitude smaller
    than x/y. Plotted raw that reads as corrupt: there is a visible gap at the
    unclosed end, and uniform scaling flattens every crossing into near
    coplanarity. This wraps it into something drawable:

    - z is stretched so crossings are visible in 3D. Uniform per-axis scaling,
      so over/under ordering is preserved.
    - the polyline is closed and arc-length resampled to num_points.
    - moving-average passes round off the right angles.
    - optionally, relax_knot_points pulls the layout into an atlas-like shape.

    Note that Representation.space_curve() silently ignores every keyword it is
    given, num_points included, so the resampling here is what actually
    controls the point count.

    Args:
        dt_code: DT code as a sequence of ints. See dt_code_for() to look one
            up by name.
        num_points: Points in the returned curve.
        z_stretch: Factor applied to z before resampling.
        smooth_passes: Moving-average smoothing passes.
        window_len: Window length for each smoothing pass.
        relax_steps: If nonzero, relaxation iterations to run. 400 is a good
            starting value and costs a few seconds.
        verbose: Passed to the Knot constructor.

    Returns:
        A pyknotid Knot whose points form a closed loop, with the closing point
        left off the end.
    """
    representation = dowker_to_representation(dt_code)
    points = representation.space_curve().points.copy()

    z_span = float(points[:, 2].max() - points[:, 2].min())
    if z_stretch != 1.0 and z_span > 0.0:
        points[:, 2] *= z_stretch

    if relax_steps:
        points = relax_knot_points(
            points, steps=relax_steps, num_points=num_points
        )

    from pyknotid.spacecurves import Knot

    knot = Knot(resample_closed_points(points, num_points), verbose=verbose)
    for _ in range(smooth_passes):
        knot.smooth(1, periodic=True, window_len=window_len)
    return knot


def knot_from_name(name: str, **kwargs) -> "Knot":
    """
    Build a plottable pyknotid Knot from a Rolfsen / Knot Atlas name.

    Convenience wrapper over dt_code_for() and dowker_to_knot().

    Args:
        name: Rolfsen identifier, e.g. '10_1'.
        **kwargs: Passed through to dowker_to_knot().

    Returns:
        A pyknotid Knot space curve.
    """
    return dowker_to_knot(dt_code_for(name), **kwargs)
