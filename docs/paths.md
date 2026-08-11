# Paths and knots

This guide explains how knots are described as paths in the led_knots project, how those paths flow through the tube-building pipeline, what every built-in knot does, and how to add your own. It is the companion to the [Configuration reference](configuration.md), the [tube models guide](tube-models.md), and the [render pipeline](rendering-and-preview.md).

## What a "path" is in this project

A "path" is a 3D centerline that a tube cross-section is swept along. Concretely, every knot module in [src/led_knots/knots/](../src/led_knots/knots/) ends up producing a CadQuery `Wire` (or `Edge`) — almost always built by calling `cadquery.func.spline(points, ...)` on a list of `(x, y, z)` tuples. That single wire is the geometric backbone of the printed part; everything else (LED cross-section, twist, optional aux spine, slicing, drain holes) is layered on top.

Two structural distinctions matter:

- **Open vs closed.** The current sweep pipeline does not tolerate paths whose start and end coincide — when the path is closed the two end faces overlap and the sweep fails. Every knot module that comes from a periodic generator (all the pyknotid-based ones) drops the final point, which is [`draw_knot_points`](../src/led_knots/core/knot_build.py)'s `drop_last=1` default. The ring passes `drop_last=10` to trim more aggressively and leave a visible gap.
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
| trefoil | [trefoil.py](../src/led_knots/knots/trefoil.py) | `pyknotid.make.trefoil(num_points=200)` | Open (drops last point) | Classic 3_1 trefoil. Slot 3. |
| jog_bend | [jog_bend.py](../src/led_knots/knots/jog_bend.py) | 3-point spline in the y-z plane | Open | Smooth S-curve from origin to `(0, width, height)` with vertical start/end tangents. |
| jog_bend_3d | [jog_bend_3d.py](../src/led_knots/knots/jog_bend_3d.py) | 3-point spline with mixed tangents | Open | Diagonal version of `jog_bend` with a tangent flip at the midpoint; uses `build_ribbon_aux_spine` with 40 samples. |
| quarter_turn | [quarter_turn.py](../src/led_knots/knots/quarter_turn.py) | Two-point spline with vertical-to-horizontal tangents | Open | 90 degree bend from `(0,0,0)` to `(0, height, height)`. |
| twisted_rod | [twisted_rod.py](../src/led_knots/knots/twisted_rod.py) | Straight z-axis path + helical aux | Open | Straight vertical rod with a hand-built helical aux spine (`create_helix_points`) that imposes a 90 degree end-to-end twist. |
| twist_ring | [twist_ring.py](../src/led_knots/knots/twist_ring.py) | `torus_knot(p=5, q=10, num=150)` | Open (drops 5 trailing points) | A wound ring, not one of the 15 knotbook slots. |
| k2_1 | [k2_1.py](../src/led_knots/knots/k2_1.py) | `torus_knot(p=2, q=1, num=200)` | Open (drops last point) | Slot 2. Topologically the unknot; there is no 2-crossing knot. |
| k4_1 | [k4_1.py](../src/led_knots/knots/k4_1.py) | `pyknotid.make.k4_1(num_points=200)` | Open (drops last point) | Figure-eight knot. Slot 4. |
| k5_2 | [k5_2.py](../src/led_knots/knots/k5_2.py) | `pyknotid.make.k5_2(num_points=200)` | Open (drops last point) | Three-twist knot. Slot 5. |
| k8_21 | [k8_21.py](../src/led_knots/knots/k8_21.py) | `pyknotid.make.k8_21(num_points=200)` | Open (drops last point) | 8-crossing knot 8_21. Slot 8. |
| k6_3, k7_1, k9_2, k10_7, k11a6 | e.g. [k7_1.py](../src/led_knots/knots/k7_1.py) | `knot_from_name(<name>, num_points=200, relax_steps=400)` | Open (drops last point) | Slots 6, 7, 9, 10, 11. Catalogue DT code, relaxed into an atlas-like layout. |
| k12a6, k13a6, k14n2, k15n3 | e.g. [k15n3.py](../src/led_knots/knots/k15n3.py) | `knot_from_name(<name>, num_points=600, relax_steps=400)` | Open (drops last point) | Slots 12-15. **600 points, not 200** — see the warning below. |
| stevedore | [stevedore.py](../src/led_knots/knots/stevedore.py) | `pyknotid.make.k6_1(num_points=300)` | Open (drops last point) | The 6_1 (stevedore) knot. Outside the 15; slot 6 is `k6_3`. |
| k9_35 | [k9_35.py](../src/led_knots/knots/k9_35.py) | `Knot.from_dowker_code([8, 12, 16, ...])` | Open (drops last point) | Outside the 15; slot 9 is `k9_2`. |

All of the pyknotid-derived modules share the same scaffold — scale, open the spline, build the aux spine, `draw_part` — which now lives in one place as [`draw_knot_points`](../src/led_knots/core/knot_build.py). A knot module is just its path source plus one call to it. [trefoil.py](../src/led_knots/knots/trefoil.py) is the cleanest reference template.

### Relaxation can silently change the knot

`relax_knot_points` (used by every DT-code module via `dowker_to_knot(relax_steps=...)`) is a cosmetic curve-shortening flow. Its self-repulsion is short-range, so when the polyline is coarser than the gaps between strands, a strand passes through another and the result is a **different, simpler knot — with nothing raised**. At 200 points, K15n3 comes out as 6_2.

400 points is the lowest count measured to survive 12 through 15 crossings; the modules use 600 for margin, since at 600 several of them identify uniquely rather than as one of a candidate set. 250 does not survive — a curve relaxed at 600 and resampled down to 250 comes back as a different knot.

If you add a slot above 11 crossings, or lower a `NUM_POINTS` constant, confirm the curve with `Knot.identify()` first — [`tests/test_knot_catalogue.py`](../tests/test_knot_catalogue.py) does exactly that for every DT-code slot (`pytest -m slow`).

### Dense knots need a bigger build volume, and some need an unprintable one

A correct centerline is not enough to sweep. At the default `output_bounds` of 200 x 110 x 200 mm, half the 15 slots either fail with `Standard_Failure: BRepFill_Sweep::BuildEdge` / `Bnd_Box is void`, or — worse — return a solid that is not the part. `k6_3` at default bounds collapsed to a 0.5 mm blob with no error raised. **A clean exit from the sweep is not evidence of a real part; check the bounding box.**

Raising `output_bounds` in the knot's own config is the lever (scaling is linear). Measured results, all verified through `build_tube_from_path`:

| Slot | Bounds | Result |
| --- | --- | --- |
| k6_3, k9_2, k10_7 | 300 x 165 x 300 (1.5x) | Sweeps. Below 1.5x, k6_3 degenerates and the other two fail. |
| k11a6 | 600 x 330 x 600 (3x) | Sweeps. 1.5x and 2x both still fail. |
| k13a6 | 1600 x 880 x 1600 (8x) | Sweeps, strands 54.7 mm apart — but the part is **1.4 x 1.6 x 0.6 m**. 6x fails. |
| k15n3 | only at **48x** | Sweeps at 9600 x 5280 x 9600, producing a **9.5 m** part. Smallest working volume unknown. |
| k12a6 | **none found** | Untested above 1x, where it returns a self-intersecting solid without erroring. |
| k14n2 | **none found** | Fails at 1x, 48x *and* 64x. Not a scale problem. |
| k5_2, k8_21 | **none found** | Fail at default bounds and at their original point counts. Pre-existing. |

Three cautions about diagnosing this:

- **Neither strand clearance nor minimum curvature radius predicts failure.** `k7_1` sweeps with strands 10.5 mm apart; `k11a6` failed at 19.8 mm. Every slot that sweeps today sits *below* the 30 mm the tube diameter nominally demands, so treat clearance as a smell test for fused-looking strands, not as a pass/fail gate.
- **Scale is not always the lever, and neither is point count.** `k14n2` fails at 64x, where its strands are hundreds of millimetres apart — self-intersection cannot be the cause there. Decoupling the two point counts (relax at 600 to keep the topology, resample down for the spline) does not rescue it either: at 250 points the curve loses the knot type outright, and at 400 the topology survives but the sweep still fails. Counter-intuitively `k15n3` sweeps at 48x with 600 points and fails at the same volume with 400, so fewer control points is not reliably easier for OCC.
- **Sub-30 mm clearance still means strands merge.** `k9_2` at 1.5x leaves 26.3 mm against a 30 mm tube, so those strands fuse where they cross. That is a design call, not an error — but it blocks the LED channel at the fusion point.

For the 12-15 crossing slots the honest position is that a knot that dense, rendered in 30 mm tube, is a very large object — and for two of them no working setting is known at any size. The most promising unexplored lever is a smaller `face_settings.led_circle_tube.outer_diameter` in those configs, which relaxes the requirement proportionally; `max_print_bounds` segmentation is the alternative where a large part does sweep.

When measuring any of this, note that these configs are re-read per attempt — do not edit a knot's config while a bounds sweep against it is running, or the multipliers compound silently.

## Path utilities reference

These are the public helpers re-exported from [src/led_knots/core/__init__.py](../src/led_knots/core/__init__.py). Use them directly from a knot module — they are the documented surface for path work.

### `scale_pyknot_points(points, width, height, length, padding=0.0, preserve_aspect_ratio=True)`

Defined in [src/led_knots/core/pyknot_utils.py](../src/led_knots/core/pyknot_utils.py).

Rescales an `(N, 3)` numpy array of points so that, after subtracting `padding` from each side, the cloud fits in a `width x height x length` box and is translated into the positive octant. With `preserve_aspect_ratio=True` it uses a uniform scale factor (one shared `min` of the three per-axis scales); with `preserve_aspect_ratio=False` each axis is scaled independently to fill the padded extent.

Called for every pyknotid-based knot, from inside [`draw_knot_points`](../src/led_knots/core/knot_build.py), with `padding=tube_settings.outer_radius` and the three `output_bounds` axes. The ring is the exception: it overrides the bounds to `(width, width, height)` and passes `preserve_aspect_ratio=False` so the planar circle fills the plate.

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

Called from `draw_knot_points` for every knot module, and directly by jog_bend_3d. The rod, ring, sine_wave, jog_bend, quarter_turn, helix, and twisted_rod modules skip it — `draw_knot_points(..., aux=False)` in the ring's case.

Gotcha: the feasibility check is `O(n^2)` over the samples — `num_samples=150` runs roughly 11,000 comparisons. That is fine; do not bump `num_samples` into the thousands.

### `PathFrame` and `sample_path_frames(path, num_samples, *, uniform_arc=False)`

Defined in [src/led_knots/core/path_frames.py](../src/led_knots/core/path_frames.py).

`PathFrame` is a frozen dataclass — `t`, `point`, `tangent`, `x_dir`, `y_dir`, `arc_length` — describing one local coordinate system along the centerline. `sample_path_frames` returns `num_samples` of them with the in-plane `(x_dir, y_dir)` basis parallel-transported from the start. Passing `uniform_arc=True` uses OCC's `GCPnts_UniformAbscissa` to put the sample points at uniform arc length (only meaningful for single-edge wires); the default is uniform parameter `t`.

Used by `sample_path_for_profiles` and by the tube model implementations. This is the right surface to consume when you are building a custom tube model rather than a new knot.

Helpers: `frame_at_arc_length(frames, s)` returns a frame at an arbitrary arc length (linearly interpolating the origin, snapping the basis to the nearest upstream frame), and `frame_to_dict(frame)` produces the legacy dict shape that older consumers expect.

### `apply_gap_to_polyline_points(points, gap_length_mm, center_fraction=0.0)`

Defined in [path_utils.py:36](../src/led_knots/core/path_utils.py#L36).

Removes a contiguous chord-length segment from a polyline (used for cutting a physical gap into a closed-looking knot before splining). Returns the trimmed points and a `PathGapInfo` describing where the gap landed (start/end indices, mid point, tangent). `center_fraction` in `[-0.5, 0.5]` biases the gap toward the start (negative) or end (positive) of the polyline.

Not currently called from any of the built-in knot modules — it exists for tooling that wants to introduce a print joint at a controlled location. `draw_knot_points(..., drop_last=10)` is the manual equivalent.

### `draw_knot_points(points, config, *, drop_last=1, bounds=None, preserve_aspect_ratio=True, aux=True, num_samples=150, spine_offset_radius=5.0)`

Defined in [src/led_knots/core/knot_build.py](../src/led_knots/core/knot_build.py).

The whole back half of a knot module in one call: scale the raw pyknotid points into the build volume, drop the trailing points that open the loop, solve the twist schedule with `build_ribbon_aux_spine`, and hand path plus aux spine to `draw_part`. Every pyknotid-derived knot module goes through it, so a module is just its path source.

`bounds` overrides `config.output_bounds` when a planar knot wants a different axis mapping (the ring is the only current case). `aux=False` skips the twist solver for paths with no meaningful curvature. `ValueError` from the feasibility check propagates — see [min_90_degree_twist_distance](#min_90_degree_twist_distance).

## Cookbook: add a new knot

1. **Create the module.** Copy [src/led_knots/knots/trefoil.py](../src/led_knots/knots/trefoil.py) to `src/led_knots/knots/<your_knot>.py`. It is the canonical template and is down to two statements: get points, call `draw_knot_points`.
2. **Generate the path.** Pick one of four sources:
   - **A named knot from the catalogue** — `k = knot_from_name("10_7", num_points=200, relax_steps=400)`. Handles Rolfsen (`10_7`) and Knot Atlas (`K11a6`) names. Above 11 crossings raise `num_points` to 600 and verify with `Knot.identify()`; see [Relaxation can silently change the knot](#relaxation-can-silently-change-the-knot).
   - **pyknotid generators** — `from pyknotid.make import some_knot; k = some_knot(num_points=200)`.
   - **Analytic numpy** — build an `(N, 3)` array directly, as [ring.py](../src/led_knots/knots/ring.py) does. Anchor coordinates to `config.output_bounds.{width, height}` rather than literals so the part respects the configured build volume, or let `draw_knot_points` rescale for you. See also [sine_wave.py](../src/led_knots/knots/sine_wave.py).
   - **CadQuery primitive** — `Wire.makeHelix(...)` or a hand-written `cadquery.func.spline(...)` with explicit `tgts`. These bypass `draw_knot_points` and call `draw_part` themselves.
3. **Render inside `build(config)`.**

   ```python
   def build(config: Config) -> None:
       k = knot_from_name("10_7", num_points=200, relax_steps=400)
       draw_knot_points(k.points, config)
   ```

   Pass `aux=False` for paths with no meaningful curvature, `drop_last=N` to widen the gap, `bounds=(w, h, l)` to override the axis mapping.
4. **Add a config file.** Create a YAML under `knot_configs/` (or any path) with `knot_type` set to your module stem:

   ```yaml
   knot_type: my_knot
   rendering:
     name: my_knot
   ```

   No `pyproject.toml` entry is needed — knot modules are discovered by filename. A stem starting with `_` is treated as a private helper and is not offered as a `knot_type`.
5. **Validate.** Run `render-knot knot_configs/my_knot.yaml`. The render bundle includes a preview PNG and STL by default. See the [render pipeline guide](rendering-and-preview.md) for all export formats.
6. **Register it in the tests.** Add the stem to `EXPECTED_KNOT_TYPES` in [tests/test_knot_registry.py](../tests/test_knot_registry.py), which asserts set equality against the filesystem. If it is a DT-code knot, add it to `DT_CODE_SLOTS` in [tests/test_knot_catalogue.py](../tests/test_knot_catalogue.py) too, so its topology is checked.

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
