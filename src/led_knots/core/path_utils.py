"""
Path-related utilities for LED knot generation.

Provides path curvature sampling, twist angle computation, and auxiliary spine
construction for ribbon sweeps along arbitrary paths.
"""

import math
import numpy as np
from cadquery.func import spline


def _normalize(v: np.ndarray) -> np.ndarray:
    """Normalize a vector, returning zero vector if magnitude is too small."""
    mag = np.linalg.norm(v)
    if mag < 1e-10:
        return np.zeros_like(v)
    return v / mag


def sample_path_curvature(path, num_samples: int = 50) -> list:
    """
    Sample the path and compute curvature data at each point.

    Uses finite differences to compute the curvature vector at each sample point.
    The curvature direction points toward the center of curvature (the normal vector
    in the Frenet-Serret frame).

    Args:
        path: A CadQuery Wire object representing the sweep path
        num_samples: Number of sample points along the path (default: 50)

    Returns:
        List of dicts, each containing:
          - t: parameter value (0 to 1)
          - point: (x, y, z) position tuple
          - tangent: unit tangent vector as numpy array
          - curvature: curvature magnitude (1/radius of curvature)
          - curvature_direction: unit vector pointing toward center of curvature
    """
    samples = []

    # Small delta for finite difference computation
    dt = 1.0 / (num_samples - 1)
    epsilon = dt * 0.01  # Small perturbation for derivative estimation

    for i in range(num_samples):
        t = i / (num_samples - 1)

        # Get position at t
        point = path.positionAt(t)
        point_tuple = (point.x, point.y, point.z)

        # Get tangent at t (already provided by CadQuery)
        tangent_vec = path.tangentAt(t)
        tangent = _normalize(np.array([tangent_vec.x, tangent_vec.y, tangent_vec.z]))

        # Compute curvature using finite differences of the tangent
        # Curvature = |dT/ds| where s is arc length
        # We approximate dT/dt and divide by |dr/dt| to get dT/ds

        t_prev = max(0, t - epsilon)
        t_next = min(1, t + epsilon)

        # Get tangents at neighboring points
        tangent_prev_vec = path.tangentAt(t_prev)
        tangent_next_vec = path.tangentAt(t_next)
        tangent_prev = _normalize(np.array([tangent_prev_vec.x, tangent_prev_vec.y, tangent_prev_vec.z]))
        tangent_next = _normalize(np.array([tangent_next_vec.x, tangent_next_vec.y, tangent_next_vec.z]))

        # Get positions at neighboring points for arc length estimation
        pos_prev = path.positionAt(t_prev)
        pos_next = path.positionAt(t_next)
        pos_prev_arr = np.array([pos_prev.x, pos_prev.y, pos_prev.z])
        pos_next_arr = np.array([pos_next.x, pos_next.y, pos_next.z])

        # Estimate arc length between prev and next
        arc_length = np.linalg.norm(pos_next_arr - pos_prev_arr)

        # Compute dT/ds (rate of change of tangent with respect to arc length)
        if arc_length > 1e-10:
            dT_ds = (tangent_next - tangent_prev) / arc_length
        else:
            dT_ds = np.zeros(3)

        # Curvature magnitude is |dT/ds|
        curvature = np.linalg.norm(dT_ds)

        # Curvature direction (normal) is the normalized dT/ds
        curvature_direction = _normalize(dT_ds)

        samples.append({
            't': t,
            'point': point_tuple,
            'tangent': tangent,
            'curvature': curvature,
            'curvature_direction': curvature_direction,
        })

    return samples


def sample_path_for_profiles(path, num_samples: int = 50) -> list:
    """
    Sample the path for multisection sweep profile placement.

    Returns position, tangent, and arc length at each sample point for creating
    profiles that coincide with the path.

    Args:
        path: A CadQuery Wire or Edge representing the sweep path
        num_samples: Number of sample points along the path (default: 50)

    Returns:
        List of dicts, each containing:
          - t: parameter value (0 to 1)
          - point: CadQuery Vector (path.positionAt(t))
          - tangent: CadQuery Vector (path.tangentAt(t))
          - arc_length: cumulative arc length from start to this point (chord-length approx)
    """
    samples = []
    cumulative_arc = 0.0
    prev_pos = None

    for i in range(num_samples):
        t = i / (num_samples - 1) if num_samples > 1 else 1.0

        point = path.positionAt(t)
        tangent_vec = path.tangentAt(t)

        if prev_pos is not None:
            curr_arr = np.array([point.x, point.y, point.z])
            prev_arr = np.array([prev_pos.x, prev_pos.y, prev_pos.z])
            cumulative_arc += float(np.linalg.norm(curr_arr - prev_arr))
        prev_pos = point

        samples.append({
            't': t,
            'point': point,
            'tangent': tangent_vec,
            'arc_length': cumulative_arc,
        })

    return samples


def sample_path_for_pyramid_profiles(
    path,
    pitch: float,
    sections_per_pyramid: int = 5,
    dense_samples: int = 500,
) -> list:
    """
    Sample the path at pyramid-aligned positions for multisection sweep.

    Sections are placed so the pyramid pattern (ridge_width + ridge_spacing)
    repeats correctly. Total sections = sections_per_pyramid * num_pyramids,
    where num_pyramids = path_length / pitch.

    Args:
        path: CadQuery Wire or Edge representing the sweep path
        pitch: Length of one pyramid cycle in mm (ridge_width + ridge_spacing)
        sections_per_pyramid: Faces per pyramid to define the shape (e.g., 5 for valley-rise-peak-fall-valley)
        dense_samples: Samples for arc-length lookup (default: 500)

    Returns:
        List of dicts with t, point, tangent, arc_length (same format as sample_path_for_profiles)
    """
    if pitch <= 0:
        raise ValueError("pitch must be positive")
    if sections_per_pyramid < 2:
        raise ValueError("sections_per_pyramid must be >= 2")

    # Dense sample for arc-length to t mapping
    dense = sample_path_for_profiles(path, num_samples=dense_samples)
    path_length = dense[-1]['arc_length']

    # Step between sections within one pyramid
    step = pitch / (sections_per_pyramid - 1)
    # Arc positions: 0, step, 2*step, ... up to path_length
    s_values = []
    s = 0.0
    while s < path_length - 1e-6:  # small tolerance for float
        s_values.append(s)
        s += step
    s_values.append(path_length)

    def _t_for_arc_length(s_target: float) -> float:
        """Interpolate t from arc length using dense lookup."""
        if s_target <= 0:
            return 0.0
        if s_target >= path_length:
            return 1.0
        for i in range(len(dense) - 1):
            s_lo, s_hi = dense[i]['arc_length'], dense[i + 1]['arc_length']
            if s_lo <= s_target <= s_hi:
                t_lo, t_hi = dense[i]['t'], dense[i + 1]['t']
                if s_hi - s_lo > 1e-10:
                    frac = (s_target - s_lo) / (s_hi - s_lo)
                    return t_lo + frac * (t_hi - t_lo)
                return t_lo
        return 1.0

    samples = []
    for s_val in s_values:
        t = _t_for_arc_length(s_val)
        point = path.positionAt(t)
        tangent = path.tangentAt(t)
        samples.append({
            't': t,
            'point': point,
            'tangent': tangent,
            'arc_length': s_val,
        })

    return samples


def compute_optimal_twist_angles(
    curvature_data: list,
    initial_rotation: float = 0.0,
    flexible_tolerance: float = 0.01,
    rigid_tolerance: float = 0.002,
    max_twist_rate: float = 2.0,
    smoothing_window: int = 7,
) -> list:
    """
    Compute optimal twist angles at each sample point to keep bends within tolerance.

    The LED strip cross-section is ribbon-like:
    - Flexible axis (local Y): Can bend easily in this direction
    - Rigid axis (local X): Cannot bend sharply in this direction

    When path curvature exceeds the rigid tolerance, the face must twist so that
    the flexible axis aligns with the curvature direction.

    This implementation uses parallel transport to maintain a consistent local
    coordinate frame, and computes incremental twist adjustments to avoid
    oscillation.

    Args:
        curvature_data: List of dicts from sample_path_curvature()
        initial_rotation: Starting rotation angle in degrees (default: 0)
        flexible_tolerance: Max curvature (1/mm) allowed in flexible direction (default: 0.01)
        rigid_tolerance: Max curvature (1/mm) allowed in rigid direction (default: 0.002)
        max_twist_rate: Maximum twist rate in degrees per mm of path length (default: 2.0)
        smoothing_window: Window size for Gaussian smoothing of twist angles (default: 7)

    Returns:
        List of twist angles in degrees, one for each sample point
    """
    n = len(curvature_data)
    if n == 0:
        return []

    if n == 1:
        return [initial_rotation]

    # Use parallel transport to maintain a consistent reference frame
    # This prevents the oscillation caused by recomputing the frame at each point
    prev_local_x = None
    prev_local_y = None

    # First pass: compute desired twist adjustments using parallel transport
    desired_twists = np.zeros(n)

    for i, sample in enumerate(curvature_data):
        curvature = sample['curvature']
        curvature_dir = sample['curvature_direction']
        tangent = sample['tangent']

        # Build/update local coordinate frame using parallel transport
        if i == 0:
            # Initialize the local frame
            if abs(tangent[2]) < 0.9:
                ref = np.array([0, 0, 1])
            else:
                ref = np.array([1, 0, 0])
            prev_local_x = _normalize(np.cross(tangent, ref))
            prev_local_y = _normalize(np.cross(tangent, prev_local_x))
        else:
            # Parallel transport: project previous frame onto plane perpendicular to tangent
            prev_local_x_proj = prev_local_x - np.dot(prev_local_x, tangent) * tangent
            proj_mag = np.linalg.norm(prev_local_x_proj)
            if proj_mag > 1e-6:
                prev_local_x = prev_local_x_proj / proj_mag
            else:
                # Degeneracy: tangent nearly parallel to prev_local_x. Re-initialize frame
                # so curvature/twist logic uses a valid perpendicular direction.
                if abs(tangent[2]) < 0.9:
                    ref = np.array([0, 0, 1])
                else:
                    ref = np.array([1, 0, 0])
                prev_local_x = _normalize(np.cross(tangent, ref))
            prev_local_y = _normalize(np.cross(tangent, prev_local_x))

        # Skip twist computation if curvature is negligible
        if curvature < 1e-6:
            desired_twists[i] = 0.0
            continue

        # Project curvature direction onto the local XY plane
        curv_x = np.dot(curvature_dir, prev_local_x)
        curv_y = np.dot(curvature_dir, prev_local_y)

        # Calculate how much curvature is in the rigid direction at the current twist
        # The face is rotated by the accumulated twist, so we need to account for that
        current_twist_rad = math.radians(initial_rotation + sum(desired_twists[:i]))

        # Rotate the curvature components by the current twist
        cos_t = math.cos(current_twist_rad)
        sin_t = math.sin(current_twist_rad)
        rigid_component = abs(curvature * (curv_x * cos_t + curv_y * sin_t))

        if rigid_component > rigid_tolerance:
            # Need to twist to reduce rigid component
            # The curvature angle in the local frame
            curv_angle = math.atan2(curv_y, curv_x)

            # Target twist should align flexible axis (90° offset) with curvature
            # This is an incremental adjustment from the current accumulated twist
            target_total = math.degrees(curv_angle) - 90.0 - initial_rotation
            current_total = sum(desired_twists[:i])

            # Compute incremental twist needed
            delta = target_total - current_total

            # Normalize delta to [-180, 180]
            while delta > 180:
                delta -= 360
            while delta < -180:
                delta += 360

            desired_twists[i] = delta
        else:
            desired_twists[i] = 0.0

    # Second pass: compute cumulative twist with rate limiting
    cumulative_twist = np.zeros(n)
    cumulative_twist[0] = 0.0

    for i in range(1, n):
        # Get arc length for rate limiting
        prev_point = np.array(curvature_data[i - 1]['point'])
        curr_point = np.array(curvature_data[i]['point'])
        segment_length = max(np.linalg.norm(curr_point - prev_point), 0.1)

        # Target cumulative twist is the sum of all desired increments up to this point
        target = sum(desired_twists[:i + 1])

        # Limit the rate of change
        max_delta = max_twist_rate * segment_length
        delta = target - cumulative_twist[i - 1]

        # Clamp the change
        if abs(delta) > max_delta:
            delta = max_delta if delta > 0 else -max_delta

        cumulative_twist[i] = cumulative_twist[i - 1] + delta

    # Apply Gaussian smoothing for a gradual transition
    if smoothing_window > 1 and n > smoothing_window:
        kernel_size = smoothing_window
        sigma = kernel_size / 3.0
        x = np.arange(kernel_size) - kernel_size // 2
        kernel = np.exp(-x**2 / (2 * sigma**2))
        kernel = kernel / kernel.sum()

        padded = np.pad(cumulative_twist, kernel_size // 2, mode='edge')
        smoothed = np.convolve(padded, kernel, mode='valid')

        if len(smoothed) > n:
            smoothed = smoothed[:n]
        elif len(smoothed) < n:
            smoothed = np.pad(smoothed, (0, n - len(smoothed)), mode='edge')

        cumulative_twist = smoothed

    # Add initial rotation to get final twist angles
    twist_angles = cumulative_twist + initial_rotation

    return twist_angles.tolist()


def build_variable_twist_spine(
    path,
    twist_angles: list,
    spine_offset_radius: float = 5.0,
):
    """
    Build an auxiliary spine that encodes variable twist along the path.

    The auxiliary spine is used by CadQuery's sweep operation to control the
    orientation of the cross-section as it moves along the path. The spine
    runs parallel to the main path but offset perpendicular to the tangent,
    with the offset direction rotating according to the twist angles.

    Uses parallel transport to maintain a consistent local coordinate frame
    along curved paths, preventing frame discontinuities that can cause
    sweep failures.

    Args:
        path: A CadQuery Wire or Edge object representing the main sweep path
        twist_angles: List of twist angles in degrees, one for each sample point
        spine_offset_radius: Distance to offset the spine from the main path (default: 5.0)

    Returns:
        A CadQuery Edge object representing the auxiliary spine (spline)
    """
    n = len(twist_angles)
    if n < 2:
        raise ValueError("Need at least 2 twist angles to build auxiliary spine")

    spine_points = []
    prev_local_x = None
    prev_local_y = None

    for i in range(n):
        t = i / (n - 1)

        # Get position and tangent at this parameter
        pos = path.positionAt(t)
        tangent_vec = path.tangentAt(t)
        tangent = _normalize(np.array([tangent_vec.x, tangent_vec.y, tangent_vec.z]))

        if i == 0:
            # Initialize the local coordinate frame at the start
            # Choose a reference vector not parallel to the tangent
            if abs(tangent[2]) < 0.9:
                ref = np.array([0, 0, 1])
            else:
                ref = np.array([1, 0, 0])

            # Create initial local X and Y axes
            prev_local_x = _normalize(np.cross(tangent, ref))
            prev_local_y = _normalize(np.cross(tangent, prev_local_x))
        else:
            # Parallel transport: project previous local_x onto the plane
            # perpendicular to the current tangent to maintain consistency
            prev_local_x_proj = prev_local_x - np.dot(prev_local_x, tangent) * tangent
            proj_mag = np.linalg.norm(prev_local_x_proj)

            if proj_mag > 1e-6:
                prev_local_x = prev_local_x_proj / proj_mag
            else:
                # Frame degeneracy: tangent is nearly parallel to prev_local_x (e.g. after
                # a sharp bend or in high-curvature regions). Re-initialize with a stable
                # reference to avoid a sudden jump when the projection becomes valid again;
                # otherwise the aux spine gets a kink and the sweep orientation flips.
                if abs(tangent[2]) < 0.9:
                    ref = np.array([0, 0, 1])
                else:
                    ref = np.array([1, 0, 0])
                prev_local_x = _normalize(np.cross(tangent, ref))

            prev_local_y = _normalize(np.cross(tangent, prev_local_x))

        # Get the twist angle for this point and convert to radians
        twist_rad = math.radians(twist_angles[i])

        # Calculate the offset direction based on twist angle
        # The offset rotates in the plane perpendicular to the tangent
        offset_dir = prev_local_x * math.cos(twist_rad) + prev_local_y * math.sin(twist_rad)

        # Calculate the spine point
        spine_point = np.array([pos.x, pos.y, pos.z]) + offset_dir * spine_offset_radius
        spine_points.append(tuple(spine_point))

    # Create a spline through the spine points
    aux_spine = spline(spine_points)

    return aux_spine


def build_ribbon_aux_spine(
    path,
    config,
    *,
    num_samples: int = 50,
    spine_offset_radius: float = 5.0,
    flexible_tolerance: float = 0.01,
    rigid_tolerance: float = 0.002,
    initial_rotation: float = 0.0,
    smoothing_window: int = 7,
):
    """
    Build an auxiliary spine for any path that constrains ribbon twist using config.

    Uses path curvature to compute desired twist (align flexible axis with bend),
    enforces max twist rate from config (min_90_degree_twist_distance), and validates
    feasibility globally over arc length: for any two points i < j, the required twist
    change must not exceed max_twist_rate * arc_length(i,j), so twist can be spread
    along the path (e.g. begin before the bend). Returns an aux spine suitable for
    sweep(..., aux=...).

    Raises ValueError if for any pair of points the required twist change exceeds
    max_twist_rate times the arc length between them.

    Args:
        path: CadQuery Wire or Edge representing the sweep path.
        config: Config object with path_settings.min_90_degree_twist_distance.
        num_samples: Number of sample points along the path (default: 50).
        spine_offset_radius: Distance to offset the aux spine from the path (default: 5.0).
        flexible_tolerance: Max curvature (1/mm) in flexible direction (default: 0.01).
        rigid_tolerance: Max curvature (1/mm) in rigid direction (default: 0.002).
        initial_rotation: Starting rotation of the face in degrees (default: 0.0).
        smoothing_window: Window size for Gaussian smoothing of twist angles (default: 7).

    Returns:
        Tuple of (aux_spine, initial_rotation). Use aux_spine in sweep(face, path, aux=aux_spine)
        and initial_rotation in create_led_circle_face(..., rotation_z=initial_rotation).
    """
    max_twist_rate = 90.0 / config.path_settings.min_90_degree_twist_distance  # degrees/mm

    curvature_data = sample_path_curvature(path, num_samples=num_samples)
    n = len(curvature_data)
    if n < 2:
        raise ValueError("Path has too few samples to build auxiliary spine (need at least 2)")

    # Cumulative arc length s[0..n-1] (chord-length approximation)
    s = np.zeros(n)
    for i in range(1, n):
        prev_pt = np.array(curvature_data[i - 1]["point"])
        curr_pt = np.array(curvature_data[i]["point"])
        s[i] = s[i - 1] + float(np.linalg.norm(curr_pt - prev_pt))

    # Desired twist without rate limit to check feasibility
    desired_twist_angles = compute_optimal_twist_angles(
        curvature_data,
        initial_rotation=initial_rotation,
        flexible_tolerance=flexible_tolerance,
        rigid_tolerance=rigid_tolerance,
        max_twist_rate=1e6,
        smoothing_window=smoothing_window,
    )

    # Feasibility check: for every pair (i, j) with i < j, required twist change must not exceed max_twist_rate * arc_length(i,j)
    for i in range(n):
        for j in range(i + 1, n):
            arc_length_ij = s[j] - s[i]
            if arc_length_ij <= 0:
                continue
            required_change = abs(desired_twist_angles[j] - desired_twist_angles[i])
            allowed_change = max_twist_rate * arc_length_ij
            if required_change > allowed_change:
                t_i = curvature_data[i]["t"]
                t_j = curvature_data[j]["t"]
                required_rate = required_change / arc_length_ij
                raise ValueError(
                    "Twist required between t=%.4f and t=%.4f exceeds max rate: "
                    "required %.2f deg over %.2f mm arc (%.2f deg/mm), max allowed %.2f deg/mm "
                    "(min_90_degree_twist_distance=%.1f mm). "
                    "Increase path length (e.g. output bounds) or increase min_90_degree_twist_distance in path config."
                    % (
                        t_i,
                        t_j,
                        required_change,
                        arc_length_ij,
                        required_rate,
                        max_twist_rate,
                        config.path_settings.min_90_degree_twist_distance,
                    )
                )

    twist_angles = compute_optimal_twist_angles(
        curvature_data,
        initial_rotation=initial_rotation,
        flexible_tolerance=flexible_tolerance,
        rigid_tolerance=rigid_tolerance,
        max_twist_rate=max_twist_rate,
        smoothing_window=smoothing_window,
    )

    aux_spine = build_variable_twist_spine(
        path,
        twist_angles,
        spine_offset_radius=spine_offset_radius,
    )
    return (aux_spine, initial_rotation)
