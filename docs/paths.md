# Paths and knots

This guide explains how knots are described as paths in the led_knots project, how those paths flow through the tube-building pipeline, what every built-in knot does, and how to add your own. It is the companion to the [Configuration reference](configuration.md), the [tube models guide](tube-models.md), and the [render pipeline](rendering-and-preview.md).

## What a "path" is in this project

A "path" is a 3D centerline that a tube cross-section is swept along. Concretely, every knot module in [src/led_knots/knots/](../src/led_knots/knots/) ends up producing a CadQuery `Wire` (or `Edge`) — almost always built by calling `cadquery.func.spline(points, ...)` on a list of `(x, y, z)` tuples. That single wire is the geometric backbone of the printed part; everything else (LED cross-section, twist, optional aux spine, slicing, drain holes) is layered on top.

Two structural distinctions matter:

- **Open vs closed.** The current sweep pipeline does not tolerate paths whose start and end coincide — when the path is closed the two end faces overlap and the sweep fails. Every knot module that comes from a periodic generator (the pyknotid-based ones — trefoil, k4_1, k8_21, stevedore, figure_8, ring) drops the final point with `spline(knot_points[:-1])` (or `[:-10]` in the ring case, which trims more aggressively to leave a visible gap). See the comment "Open path (closed path causes face overlap)" repeated across these modules, e.g. [trefoil.py:41](../src/led_knots/knots/trefoil.py#L41).
- **Smoothness.** The path's curvature governs how much twist the ribbon-shaped LED cross-section must accumulate. Sampling density (the `num_points` argument to the generator and the `num_samples` argument to `build_ribbon_aux_spine`) is the main lever for making the path smoother; 150 samples is the conventional balance between smoothness and build time.

The path is the only piece you have to invent when you add a new knot. Cross-section, twist solving, slicing, and export are all delegated.

## The path pipeline

Every built-in knot follows the same four-stage pipeline. Knowing the stages makes it easy to see where to intervene.

### 1. Generate raw points

The path starts as a list/array of 3D points. There are three idiomatic sources:

- **pyknotid generators** — `pyknotid.make.trefoil`, `pyknotid.make.k4_1`, `pyknotid.make.k6_1` (stevedore), `pyknotid.make.k8_21`, `pyknotid.make.torus_knot`. Each returns a `Knot` whose `.points` attribute is a `(num_points, 3)` numpy array in pyknotid's native scale.
- **Analytic numpy** — write a small loop or vectorized numpy expression for known curves: a sine wave ([sine_wave.py](../src/led_knots/knots/sine_wave.py)), a helix-shaped reference array, a parametric ring ([ring.py:30-35](../src/led_knots/knots/ring.py#L30)), or a hand-tuned bezier control polygon ([jog_bend.py](../src/led_knots/knots/jog_bend.py), [jog_bend_3d.py](../src/led_knots/knots/jog_bend_3d.py), [quarter_turn.py](../src/led_knots/knots/quarter_turn.py)).
- **CadQuery primitives** — `cadquery.Wire.makeHelix(pitch, height, radius)` produces a helix wire directly; this is used in [helix.py:47-51](../src/led_knots/knots/helix.py#L47).

### 2. Rescale to the configured build volume

For pyknotid-generated points the raw coordinates are in arbitrary units. `scale_pyknot_points` ([src/led_knots/core/pyknot_utils.py](../src/led_knots/core/pyknot_utils.py)) rescales the cloud to fit inside `output_bounds.width` (mapped to x and y) and `output_bounds.height` (mapped to z), with an optional `padding` (most modules pass `config.tube_settings.outer_radius` so the tube does not protrude past the build volume). The function returns a list of `(x, y, z)` tuples translated into the positive octant.

Analytic knots that already write directly in mm (rod, sine_wave, jog_bend, etc.) skip this step.

### 3. Build the centerline wire

The point list is converted into a `cadquery` `Wire` using `spline(points)`. When the path needs a specific entry/exit tangent (so it joins smoothly to a flat face or a continuation), pass `tgts=[(start_tangent), (end_tangent)]`, as in [sine_wave.py:42-44](../src/led_knots/knots/sine_wave.py#L42), [jog_bend.py:20-27](../src/led_knots/knots/jog_bend.py#L20), and [quarter_turn.py:20-23](../src/led_knots/knots/quarter_turn.py#L20).

### 4. (Optional) Build an auxiliary spine for ribbon twist

The LED strip cross-section is ribbon-shaped: it bends easily in one direction (the "flexible" axis) and resists bending in the other ("rigid"). When the path has non-trivial curvature, the cross-section must twist so its flexible axis aligns with the bend direction. `build_ribbon_aux_spine(path, config, ...)` sample the curvature, computes a twist schedule, and returns an `(aux_spine, initial_rotation)` tuple that can be passed straight into `draw_part`.

For purely straight paths (the rod) or for the cases where the project tolerates a small amount of off-axis bend (ring, sine_wave, jog_bend, quarter_turn), the aux spine is omitted and the sweep is driven by the default Frenet frame.

### 5. Hand off to `draw_part`

`draw_part(path, config, aux=aux_spine, rotation_z=initial_rotation)` (re-exported from [src/led_knots/core/utils.py](../src/led_knots/core/utils.py) via [src/led_knots/core/__init__.py](../src/led_knots/core/__init__.py)) sweeps the configured cross-section along the path, drills drain holes, slices into printable segments, and runs whichever combination of preview/export was requested on the CLI. See the [render pipeline guide](rendering-and-preview.md) for details. Past this point you are working with `Workplane` and `Solid` objects, not paths.

## `min_90_degree_twist_distance`

This is the central feasibility knob for any path that has bends. It lives under `path_settings` in [config.yaml](../config.yaml):

```yaml
path_settings:
  min_90_degree_twist_distance: 1   # mm - minimum path length for 90 degree twist
```

It is the minimum arc length (in millimetres) over which the LED ribbon is allowed to accumulate a 90 degree twist. Smaller values let the ribbon corkscrew more aggressively to follow tight bends; larger values force the twist to be spread over more path length.

Internally, `build_ribbon_aux_spine` ([path_utils.py:514](../src/led_knots/core/path_utils.py#L514)) converts this into a maximum twist rate `max_twist_rate = 90.0 / min_90_degree_twist_distance` (degrees per mm). After computing the unconstrained twist schedule it walks every pair of samples `(i, j)` and checks that `abs(desired_twist[j] - desired_twist[i]) <= max_twist_rate * arc_length(i, j)`. If any pair violates this inequality, the function raises a `ValueError` like:

```
Twist required between t=0.3200 and t=0.4400 exceeds max rate:
required 142.31 deg over 38.20 mm arc (3.72 deg/mm),
max allowed 90.00 deg/mm (min_90_degree_twist_distance=1.0 mm).
Increase path length (e.g. output bounds) or increase
min_90_degree_twist_distance in path config.
```

When you hit this error you have three real options:

1. **Relax the limit.** Raise `min_90_degree_twist_distance` in your config. Note that the *opposite* sense of "raise" applies physically: a larger value means less aggressive twist, so this only helps if the path actually needs *less* twist than your default allowed — which is rare. Usually you want the inverse.
2. **Make the path longer.** Increase `output_bounds.width` / `output_bounds.height` so the knot has more arc length to accumulate the same twist. This is the most common fix.
3. **Smooth or shorten the path.** Reduce sharp local curvature spikes by smoothing the input points, raising the generator's `num_points`, or simplifying the knot. The geometry's worst bend dominates the required twist rate.

If the path has no curvature at all (a straight rod), the twist solver computes a zero-twist schedule and the feasibility check is trivially satisfied; `build_ribbon_aux_spine` is therefore safe to call even on a rod, but is redundant.

## Built-in knots

| Name | Script | Path family | Open/Closed | Description |
| --- | --- | --- | --- | --- |
| rod | [rod.py](../src/led_knots/knots/rod.py) | Straight line on z | Open | Two-point spline from origin to `(0, 0, height)`. No aux spine. |
| ring | [ring.py](../src/led_knots/knots/ring.py) | Parametric circle (sin/cos) | Open (drops 10 trailing points) | Planar circle of radius 3 in pyknotid units, rescaled to bounds, with a visible gap. |
| helix | [helix.py](../src/led_knots/knots/helix.py) | `Wire.makeHelix` (CadQuery primitive) | Open | Helix with pitch `height/2`, radius `width/2`, plus an offset helix as aux spine. `rotation_z` derived from the pitch angle. |
| sine_wave | [sine_wave.py](../src/led_knots/knots/sine_wave.py) | Analytic `y = A * sin(2*pi*n*t)` along z | Open | Two periods, amplitude `width/2`, vertical start/end tangents. |
| trefoil | [trefoil.py](../src/led_knots/knots/trefoil.py) | `pyknotid.make.trefoil(num_points=150)` | Open (drops last point) | Classic 3_1 trefoil; uses `build_ribbon_aux_spine` with 150 samples. |
| figure_8 | [figure_8.py](../src/led_knots/knots/figure_8.py) | `torus_knot(p=5, q=10, num=150)` | Open (drops last point) | Despite the filename this is a 5,10 torus knot, not the topological 4_1 figure-8; `rotation_z=90` fixed, no aux spine. |
| jog_bend | [jog_bend.py](../src/led_knots/knots/jog_bend.py) | 3-point spline in the y-z plane | Open | Smooth S-curve from origin to `(0, width, height)` with vertical start/end tangents. |
| jog_bend_3d | [jog_bend_3d.py](../src/led_knots/knots/jog_bend_3d.py) | 3-point spline with mixed tangents | Open | Diagonal version of `jog_bend` with a tangent flip at the midpoint; uses `build_ribbon_aux_spine` with 40 samples. |
| quarter_turn | [quarter_turn.py](../src/led_knots/knots/quarter_turn.py) | Two-point spline with vertical-to-horizontal tangents | Open | 90 degree bend from `(0,0,0)` to `(0, height, height)`. |
| twisted_rod | [twisted_rod.py](../src/led_knots/knots/twisted_rod.py) | Straight z-axis path + helical aux | Open | Straight vertical rod with a hand-built helical aux spine (`create_helix_points`) that imposes a 90 degree end-to-end twist. |
| k4_1 | [k4_1.py](../src/led_knots/knots/k4_1.py) | `pyknotid.make.k4_1(num_points=150)` | Open (drops last point) | Figure-eight knot (topologically 4_1); same template as trefoil. |
| k8_21 | [k8_21.py](../src/led_knots/knots/k8_21.py) | `pyknotid.make.k8_21(num_points=300)` | Open (drops last point) | 8-crossing knot 8_21; generates 300 raw points, samples 150 for the aux spine. |
| stevedore | [stevedore.py](../src/led_knots/knots/stevedore.py) | `pyknotid.make.k6_1(num_points=300)` | Open (drops last point) | The 6_1 (stevedore) knot. |

All of the pyknotid-derived modules share the same scaffold: load points, scale with `scale_pyknot_points`, build an open spline, build the aux spine, call `draw_part`. The trefoil module is the cleanest reference template.

## Path utilities reference

These are the public helpers re-exported from [src/led_knots/core/__init__.py](../src/led_knots/core/__init__.py). Use them directly from a knot module — they are the documented surface for path work.

### `scale_pyknot_points(points, width, height, length, padding=0.0, preserve_aspect_ratio=True)`

Defined in [src/led_knots/core/pyknot_utils.py](../src/led_knots/core/pyknot_utils.py).

Rescales an `(N, 3)` numpy array of points so that, after subtracting `padding` from each side, the cloud fits in a `width x height x length` box and is translated into the positive octant. With `preserve_aspect_ratio=True` it uses a uniform scale factor (one shared `min` of the three per-axis scales); with `preserve_aspect_ratio=False` each axis is scaled independently to fill the padded extent.

Used by every pyknotid-based knot (trefoil, k4_1, k8_21, stevedore, figure_8, ring). All of them pass `width=output_bounds.width`, `height=output_bounds.width` (note: same value — the knot becomes square in the x-y plane), `length=output_bounds.height`, `padding=tube_settings.outer_radius`, and `preserve_aspect_ratio=False`.

Returns a plain Python list of `(x, y, z)` tuples ready to feed into `spline(...)`.

Gotcha: the parameter naming is loose — `length` is the z extent, `height` is the y extent, and the third positional argument the knots pass is actually `output_bounds.height`. Read the call sites carefully when adapting.

### `sample_path_curvature(path, num_samples=50)`

Defined in [path_utils.py:119](../src/led_knots/core/path_utils.py#L119).

Walks `path` at `num_samples` evenly spaced parameter values and returns a list of dicts with keys `t`, `point`, `tangent`, `curvature`, `curvature_direction`. Curvature is estimated by finite-differencing the tangent against arc length; the direction is the unit normal pointing toward the centre of curvature.

Used internally by `compute_optimal_twist_angles` and `build_ribbon_aux_spine`. You usually do not call it directly unless you are inspecting the path or building a custom twist solver.

Gotcha: at parameter values where the path is locally straight the curvature is near zero and `curvature_direction` collapses to the zero vector — handle that explicitly if you consume the result yourself.

### `sample_path_for_profiles(path, num_samples=50)`

Defined in [path_utils.py:201](../src/led_knots/core/path_utils.py#L201).

Delegates to `path_frames.sample_path_frames` and returns a list of dicts with `t`, `point`, `tangent`, `x_dir`, `y_dir`, `arc_length`. The `(x_dir, y_dir)` basis is parallel-transported from the start of the path so the cross-section orientation never flips on curves. This is the canonical sampling helper for tube models that need to place a cross-section profile at each step (the braided rope and pyramid-studded tube models consume it).

Used by tube models — see the [tube models guide](tube-models.md) for the consumer side.

### `compute_optimal_twist_angles(curvature_data, initial_rotation=0.0, flexible_tolerance=0.01, rigid_tolerance=0.002, max_twist_rate=2.0, smoothing_window=7)`

Defined in [path_utils.py:220](../src/led_knots/core/path_utils.py#L220).

Given the dicts produced by `sample_path_curvature`, computes a per-sample twist angle (in degrees) that keeps the cross-section's rigid component of curvature within `rigid_tolerance`. Uses parallel transport for the local frame, a two-pass scheme that rate-limits per-segment twist increments, and Gaussian smoothing with the given `smoothing_window`. Returns a Python list of angles, one per input sample.

Used by `build_ribbon_aux_spine` (twice — once with `max_twist_rate=1e6` to compute the unconstrained schedule for the feasibility check, then again with the real `max_twist_rate` to compute the spine).

Gotcha: `max_twist_rate` here is in degrees per mm, the same units as `90 / min_90_degree_twist_distance`. The default `2.0` is not used by any built-in knot — they all funnel through `build_ribbon_aux_spine` which derives the rate from config.

### `build_variable_twist_spine(path, twist_angles, spine_offset_radius=5.0)`

Defined in [path_utils.py:386](../src/led_knots/core/path_utils.py#L386).

Builds the offset spline (CadQuery `Edge`) that the sweep operation uses as its `aux` argument. For each twist angle it places a point offset perpendicular to the tangent by `spine_offset_radius`, where the offset direction rotates with the accumulated twist. Uses parallel transport for the perpendicular frame.

Used by `build_ribbon_aux_spine`. You can call it directly if you have a hand-built twist schedule (as `twisted_rod.py` effectively does — except that module shortcuts by building the helical aux spine itself).

Gotcha: needs at least two angles or it raises `ValueError`.

### `build_ribbon_aux_spine(path, config, *, num_samples=50, spine_offset_radius=5.0, flexible_tolerance=0.01, rigid_tolerance=0.002, initial_rotation=0.0, smoothing_window=7)`

Defined in [path_utils.py:476](../src/led_knots/core/path_utils.py#L476).

The high-level wrapper that every curved knot uses. Pulls `min_90_degree_twist_distance` from `config.path_settings`, samples the path, computes the desired twist schedule, runs the global feasibility check (see [min_90_degree_twist_distance](#min_90_degree_twist_distance) above), then builds the aux spine. Returns `(aux_spine, initial_rotation)` so the caller can plumb both into `draw_part`.

Used by trefoil, k4_1, k8_21, stevedore, jog_bend_3d. The rod, ring, sine_wave, jog_bend, quarter_turn, helix, twisted_rod, and figure_8 modules skip it.

Gotcha: the feasibility check is `O(n^2)` over the samples — `num_samples=150` runs roughly 11,000 comparisons. That is fine; do not bump `num_samples` into the thousands.

### `PathFrame` and `sample_path_frames(path, num_samples, *, uniform_arc=False)`

Defined in [src/led_knots/core/path_frames.py](../src/led_knots/core/path_frames.py).

`PathFrame` is a frozen dataclass — `t`, `point`, `tangent`, `x_dir`, `y_dir`, `arc_length` — describing one local coordinate system along the centerline. `sample_path_frames` returns `num_samples` of them with the in-plane `(x_dir, y_dir)` basis parallel-transported from the start. Passing `uniform_arc=True` uses OCC's `GCPnts_UniformAbscissa` to put the sample points at uniform arc length (only meaningful for single-edge wires); the default is uniform parameter `t`.

Used by `sample_path_for_profiles` and by the tube model implementations. This is the right surface to consume when you are building a custom tube model rather than a new knot.

Helpers: `frame_at_arc_length(frames, s)` returns a frame at an arbitrary arc length (linearly interpolating the origin, snapping the basis to the nearest upstream frame), and `frame_to_dict(frame)` produces the legacy dict shape that older consumers expect.

### `apply_gap_to_polyline_points(points, gap_length_mm, center_fraction=0.0)`

Defined in [path_utils.py:36](../src/led_knots/core/path_utils.py#L36).

Removes a contiguous chord-length segment from a polyline (used for cutting a physical gap into a closed-looking knot before splining). Returns the trimmed points and a `PathGapInfo` describing where the gap landed (start/end indices, mid point, tangent). `center_fraction` in `[-0.5, 0.5]` biases the gap toward the start (negative) or end (positive) of the polyline.

Not currently called from any of the built-in knot modules — it exists for tooling that wants to introduce a print joint at a controlled location. The ring module's `[:-10]` slice is the manual equivalent.

## Cookbook: add a new knot

1. **Create the module.** Copy [src/led_knots/knots/trefoil.py](../src/led_knots/knots/trefoil.py) to `src/led_knots/knots/<your_knot>.py`. The trefoil template is the most canonical: expose `build(config)`, generate points, rescale, open the path, build the aux spine, call `draw_part`.
2. **Generate the path.** Pick one of three sources:
   - **pyknotid** — `from pyknotid.make import some_knot; k = some_knot(num_points=150); pts = scale_pyknot_points(k.points, width=config.output_bounds.width, height=config.output_bounds.width, length=config.output_bounds.height, padding=config.tube_settings.outer_radius, preserve_aspect_ratio=False)`. Drop the last point: `path = spline(pts[:-1])`.
   - **Analytic numpy** — build a list of `(x, y, z)` tuples in millimetres directly. Anchor coordinates to `config.output_bounds.{width, height}` rather than literals so the part respects the configured build volume. See [sine_wave.py](../src/led_knots/knots/sine_wave.py).
   - **CadQuery primitive** — `Wire.makeHelix(...)` or a hand-written `cadquery.func.spline(...)` with explicit `tgts`.
3. **Build the aux spine** (only if the path has meaningful curvature):

   ```python
   aux_spine, initial_rotation = build_ribbon_aux_spine(
       path,
       config,
       num_samples=150,
       spine_offset_radius=5.0,
   )
   ```

   Wrap it in `try/except ValueError` if you want to fall back to a no-aux sweep with a clear message, or just let the error propagate so the user knows the bend is infeasible.
4. **Render inside `build(config)`.**

   ```python
   def build(config: Config) -> None:
       # ... build path and optional aux_spine ...
       draw_part(path, config, aux=aux_spine, rotation_z=initial_rotation)
   ```

   Omit `aux` and `rotation_z` for paths without a custom twist schedule.
5. **Add a config file.** Create a YAML under `knot_configs/` (or any path) with `knot_type` set to your module stem:

   ```yaml
   knot_type: my_knot
   rendering:
     name: my_knot
   ```

   No `pyproject.toml` entry is needed — knot modules are discovered by filename.
6. **Validate.** Run `render-knot knot_configs/my_knot.yaml`. The render bundle includes a preview PNG and STL by default. See the [render pipeline guide](rendering-and-preview.md) for all export formats.

## Cookbook: tune an existing knot

Most tuning is a config edit, not a code edit. Edit [config.yaml](../config.yaml) (or a project-local copy) and rerun the knot.

**Scale the trefoil up.** The trefoil's bounding box comes from `output_bounds.width` (used twice, for the x and y extents) and `output_bounds.height`. Doubling both makes the knot twice as big:

```yaml
output_bounds:
  width: 200
  height: 200
```

If the larger knot now exceeds your printer bed, the bed-fit gate (see [Configuration reference](configuration.md)) will refuse to export until you also raise `max_print_bounds` or accept slicing.

**Switch a knot to the `braided_rope` cross-section.** The tube model is selected by config, not by the knot module. See the [tube models guide](tube-models.md) for the full list; the relevant key is under `tube_settings`:

```yaml
tube_settings:
  model: braided_rope
```

Re-run the knot — `draw_part` looks up the model by name from the registry and the existing path is reused as-is. Beware that some tube models impose minimum bend radii of their own; if your knot fails the feasibility check after the swap, increase `output_bounds` or pick a knot with gentler curvature.

**Twist a rod.** [twisted_rod.py](../src/led_knots/knots/twisted_rod.py) is the in-tree example: a straight path plus a helical aux spine. To change the total twist, edit `total_rotation = 90.0` in that module, or copy the module and parameterise the angle yourself. The helical aux spine technique generalises — any time you want a twist that does not come from the path's own curvature, hand-roll the aux spine with `build_variable_twist_spine` (or build the offset points directly as `twisted_rod` does) instead of calling `build_ribbon_aux_spine`.

## Do's and don'ts

- **Do** respect `output_bounds` when scaling. Either let `scale_pyknot_points` handle it (passing `padding=config.tube_settings.outer_radius` so the tube wall stays inside the box) or, for analytic paths, anchor your coordinates to `config.output_bounds.{width, height}` and leave one `outer_radius` of slack at each side.
- **Do** pass `aux` and `rotation_z` from `build_ribbon_aux_spine` together. The returned `initial_rotation` is the rotation the swept face must start at to align with the aux spine; using one without the other produces a visibly misaligned LED channel.
- **Do** keep `num_samples` modest (40-300 in the existing knots). The feasibility check is `O(n^2)` and the aux spine smoothness saturates well before n=1000.
- **Don't** feed a closed path straight to `spline()`. CadQuery will accept the duplicate endpoint and produce a wire whose two end faces overlap when swept — the sweep then fails or produces a degenerate solid. Drop the last point (`pts[:-1]`) the way [trefoil.py:42](../src/led_knots/knots/trefoil.py#L42) does, or trim more aggressively (`pts[:-10]`) when you want a visible physical gap.
- **Don't** bypass `build_ribbon_aux_spine` for curved paths just to silence its `ValueError`. The exception is telling you the LED ribbon physically cannot follow the path; the fix is to lengthen the path, smooth the curvature, or relax `min_90_degree_twist_distance` — not to remove the guard.
- **Don't** hardcode dimensions in a knot module. Pull `output_bounds.width`, `output_bounds.height`, and `tube_settings.outer_radius` from `config` so the same module respects whatever config the user loads. The one acceptable hardcode is `spine_offset_radius = 5.0`, which is a frame-construction detail that does not affect the final shape.
- **Don't** call `get_config()` or `draw_part()` at module import time. Expose a `build(config)` function and let `render-knot` dispatch to it via the file-based registry.
