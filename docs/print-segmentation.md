# Print segmentation and joints

When a knot is bigger than your printer's build volume, `led_knots` splits the sweep into smaller printable parts, adds registration features at every cut, and (optionally) lays the parts out on a virtual build plate. This document covers the segmentation algorithm, the two joint families (`twin_pin`, `dovetail`), the rabbet/lap geometry that complements them, and the related `tube_gap` + `clamp` features that intentionally open the path for wire feed-through.

The pipeline lives in [src/led_knots/core/print_segmentation.py](../src/led_knots/core/print_segmentation.py) and [src/led_knots/core/print_joint.py](../src/led_knots/core/print_joint.py); the clamp half-pair lives in [src/led_knots/parts/hang_clamp.py](../src/led_knots/parts/hang_clamp.py). All configurable knobs are validated in [src/led_knots/core/config.py](../src/led_knots/core/config.py).

## When you need it

Segmentation is opt-in. It activates when `max_print_bounds.enabled: true` is set in `config.yaml` (or via `config.local.yaml` override). With that flag flipped on, [draw_part](../src/led_knots/core/utils.py#L244) dispatches the sweep through [build_segmented_tube_assembly](../src/led_knots/core/print_segmentation.py#L204) instead of producing a single solid; the resulting `cq.Assembly` always has named children `segment_00`, `segment_01`, ... regardless of how many segments are needed (one is allowed).

You typically need it when:

- The output bounds (`output_bounds.width/length/height`) exceed your printer's usable build volume, e.g. a 400 mm Celtic knot on a 200×110×200 mm SLA bed.
- You want lap-joint rabbets and registration pins/dovetails at every cut so glued segments stay aligned during assembly.

Two layout strategies decide where each segment lands in world coordinates:

| `max_print_bounds.layout` | Meaning |
| --- | --- |
| `path` (default) | Each segment stays on the original sweep, in situ; `layout_gap_mm` widens a small axial gap at every internal cut so the parts read as separate bodies in the viewer. Good for visualizing the assembled knot. |
| `print_bed` | Each segment is rotated to its bed-fit pose and translated onto a row along +X, with `layout_gap_mm` between parts and Z=0 as the bed plane. Good for visual sanity-check of "will this actually fit". |

See [Configuration reference](configuration.md) for the full schema and [Print optimization](print-optimization.md) for how the per-segment SLA rescoring (`--optimize` / `--auto-orient`) interacts with `print_bed` layout.

## The algorithm

[plan_segments](../src/led_knots/core/print_segmentation.py#L131) is a classic minimum-segment dynamic program over the sampled wire polyline:

1. **Sample the wire.** [sample_wire_points](../src/led_knots/core/print_segmentation.py#L61) calls `path.positionAt(t)` at `max_print_bounds.path_samples` evenly spaced values of `t ∈ [0, 1]` (default `1001`, minimum `8`).
2. **Compute the usable build box.** From [plan_segments](../src/led_knots/core/print_segmentation.py#L132): each printer dimension is shrunk by `2 * clearance_mm`, then sorted descending so the longest segment extent is matched against the longest printer side regardless of orientation.
3. **Compute the joint margin.** [_joint_margin](../src/led_knots/core/print_segmentation.py#L71) returns `max(outer_radius + 0.5*lap_step_height_mm, outer_radius + 0.5*pin_diameter_mm | outer_radius + 0.5*base_width_mm) + lap_overlap_mm`. This is added to every dimension so a candidate orientation only "fits" when the joint features fit too.
4. **DP over end indices.** For each candidate end index `e`, try every start index `s ≤ e - 3` (each segment must hold at least four points). The transition is feasible iff some rotation from the 24 axis-aligned cube symmetries (see [_rotation_candidates_24](../src/led_knots/core/print_segmentation.py#L46)) makes the rotated AABB plus joint inflation fit the usable box. The score being minimized is **segment count**: `dp[e] = dp[s] + 1` with `dp[0] = 0`.
5. **Bed-fit gate.** [_best_rotation_for_segment](../src/led_knots/core/print_segmentation.py#L118) returns `None` when no axis-aligned rotation fits. If `dp[n-1]` is still infinite at the end, you get `RuntimeError("Could not segment path to fit max_print_bounds. Increase bounds or reduce output size.")`.
6. **Safety cap.** If `dp[n-1] > max_segments` you get `RuntimeError("Segmentation required N segments but max_print_bounds.max_segments=...")`. The default cap is `32`; raise it explicitly rather than silently allowing 100-piece prints.
7. **Reconstruct.** The chosen `(start, end, euler)` triples are returned as `SegmentPlan` records and reversed into path order.

Two clearance numbers do different things — do not confuse them:

- `max_print_bounds.clearance_mm` (default `0.0`) is **printer margin**: subtracted from `width/length/height` once on each side. Bumps up the safety envelope of the build volume itself.
- `max_print_bounds.joint.clearance_mm` (default `0.2`) is **joint tolerance**: the female socket / female rabbet are dilated by this amount so the male pin slides in without binding (see below).

## `layout: path`

In path layout the world transform on each segment is the identity except for an optional small axial nudge. For each internal cut, [build_segmented_tube_assembly](../src/led_knots/core/print_segmentation.py#L340) translates the segment by `±0.5 * layout_gap_mm` along the local tangent ([joint_tangent_at_cut](../src/led_knots/core/print_joint.py#L26)): the part on the start side shifts forward, the part on the end side shifts backward, opening a slot at the cut without disturbing the rest of the sweep.

```python
gap = float(config.max_print_bounds.layout_gap_mm)
if gap > 0 and len(plans) > 1:
    offset = np.zeros(3, dtype=float)
    half = 0.5 * gap
    if idx > 0:
        offset += joint_tangent_at_cut(sampled_points, s) * half
    if idx < len(plans) - 1:
        offset -= joint_tangent_at_cut(sampled_points, e) * half
    placed = part_shape.translate(tuple(offset))
```

Notes:

- Per-segment Euler rotations are **not** applied in `path` layout; the segments remain in their original sweep pose. The SLA per-segment rescoring (`--auto-orient`) is also skipped in `path` mode because the orientation it picks would be discarded; see [print-optimization.md](print-optimization.md).
- `layout_gap_mm` defaults to `12.0` mm in code but the shipped `config.yaml` overrides this to `2`; for `path` layout, that gap is purely cosmetic — the lap rabbets and registration features already enforce the real fit, and `layout_gap_mm` just keeps the rendered segments visually distinguishable.
- If you set `layout_gap_mm: 0`, segments stay glued together visually and the joints still print correctly.

## `layout: print_bed`

In print_bed layout each segment is treated as an independent print on a row along +X starting at the world origin. For every segment in path order:

1. Rotate the part by `plan.euler_xyz_deg` (or the SLA-chosen replacement, see [print-optimization.md](print-optimization.md)).
2. Translate so the rotated AABB's `xmin` lands at the running cursor, `ymin` at 0, and `zmin` at 0 — the part sits on the bed (Z=0), pushed against +Y origin and the prior part's right edge.
3. Advance the cursor by `bb.xlen + layout_gap_mm`.

`layout_gap_mm` is the X gap between adjacent parts on the build plate. Setting it to 0 places parts edge-to-edge; the SLA print-optimization stage's per-segment rescoring (see [print-optimization.md](print-optimization.md)) runs only in this mode, because only here do per-segment rotations actually survive into the exported geometry.

## Joints

When `max_print_bounds.joint.enabled` is true (default in the shipped `config.yaml`), every internal cut gets two complementary features added to the geometry by [apply_lap_joint_features](../src/led_knots/core/print_joint.py#L146) and [apply_registration_features](../src/led_knots/core/print_joint.py#L230):

- A **rabbet** (stepped outer-wall lap) for adhesive surface area and torsional alignment.
- A **registration key** (twin pins, or a dovetail) that keys the two halves together rotationally and prevents wrong-way assembly.

Naming convention used by the code, and worth internalizing before you read the rest:

- The **start boundary** of each non-first segment receives the **female** (socket) variant.
- The **end boundary** of each non-last segment receives the **male** (key/pin/protrusion) variant.

This makes adjacent segments mate by construction: piece N's end key seats into piece N+1's start socket.

### Common joint config keys

All keys live under `max_print_bounds.joint`. Defaults from [PrintJointSettings](../src/led_knots/core/config.py#L84):

| Key | Default | Purpose |
| --- | --- | --- |
| `enabled` | `false` | Master toggle. When false, segments butt-cut with no features and no lap. |
| `style` | `twin_pin` | `twin_pin` or `dovetail`. Anything else raises at load time. |
| `clearance_mm` | `0.2` | Diametral/radial slop added to every female feature so the male slides in. Must be `>= 0`. Don't go below your printer's tolerance (resin ≈ 0.15–0.25 mm). |
| `close_loop` | `false` | When true, a closed-loop path gets an extra final joint between the last and first segment so the loop is glued shut. Currently consumed by the cache key (see [cache_utils.py](../src/led_knots/core/cache_utils.py#L131)); set this to invalidate cached previews when you intend a closed loop. |
| `lap_overlap_mm` | `4.0` | Axial overlap length at internal cuts (mm along the path tangent). Both neighbors extend by this much past the nominal cut — see [extend_segment_points_for_lap](../src/led_knots/core/print_joint.py#L79). When `0`, the lap reduces to `pin_depth_mm` via [lap_overlap_mm](../src/led_knots/core/print_joint.py#L69). |
| `lap_step_height_mm` | `3.0` | Radial step height of the rabbet on the outer wall. Capped at `0.45 * outer_radius` by [_make_lap_rabbet_feature](../src/led_knots/core/print_joint.py#L127) so the step never eats the whole wall. Must be `> 0`. |

### twin_pin

Two cylindrical pins, asymmetrically placed so a 180° flip never mates. Geometry in [_make_twin_pin_features](../src/led_knots/core/print_joint.py#L184); positions: one pin at `(base_x, +0.5*spacing)` and one at `(base_x, -0.20*spacing)` in the cut-local XY plane.

| Key | Default | Meaning |
| --- | --- | --- |
| `pin_diameter_mm` | `3.0` | Pin diameter. Female socket diameter is `pin_diameter_mm + clearance_mm`. |
| `pin_depth_mm` | `4.0` | Pin axial length (along the path tangent). Female socket depth is `pin_depth_mm + clearance_mm`. |
| `pin_spacing_mm` | `7.0` | Center-to-center distance between the two pins; the asymmetric (0.5, −0.20) split derives positions from this. |
| `pin_radial_offset_mm` | `17.0` | Nominal radial distance from the tube centerline to each pin axis. **Clamped** by [_pin_radial_offset_mm](../src/led_knots/core/print_joint.py#L111) to `outer_radius - pin_radius - 0.25` so pins never float outside the tube wall; if you request a value larger than the wall allows, the helper silently moves it inward. Floor is `pin_radius + 0.5`. |

### dovetail

A single trapezoidal key with the narrow neck pointing away from the cut. Geometry in [_make_dovetail_feature](../src/led_knots/core/print_joint.py#L203).

| Key | Default | Meaning |
| --- | --- | --- |
| `neck_width_mm` | `3.0` | Width at the open edge of the dovetail (away from the cut face). |
| `base_width_mm` | `5.0` | Width at the base (at the cut face). Must be `> neck_width_mm` — validated at load time. |
| `depth_mm` | `4.0` | Axial depth into the cut. Female pocket is dilated by `clearance_mm` on `neck`, `base`, and `depth`. |
| `flank_angle_deg` | `12.0` | Reserved for downstream flank shaping. Currently the dovetail flank slope is implied by `neck`/`base`/`depth`. |
| `pin_radial_offset_mm` | `17.0` | Same clamping logic as twin_pin; the dovetail centroid sits at this radius from the tube centerline. |

### How the rabbet and the key cooperate

For each internal cut, the segment geometry receives both features in this order:

1. [extend_segment_points_for_lap](../src/led_knots/core/print_joint.py#L79) pushes the segment polyline `lap_overlap_mm` past the cut on the relevant side(s), so when the sweep is built each neighbor extends into the shared boundary. The "cut" is therefore not a flat butt — both halves carry full-OD material across the seam.
2. [apply_lap_joint_features](../src/led_knots/core/print_joint.py#L146) carves a female rabbet (outer wall stepped inward by `lap_step_height_mm`, dilated by `clearance_mm`) on start boundaries and fuses a male rabbet (matching step) on end boundaries.
3. [apply_registration_features](../src/led_knots/core/print_joint.py#L230) cuts the female pin sockets / dovetail pocket on start boundaries and fuses the male pins / dovetail on end boundaries.

Net effect: the printed parts overlap axially by `lap_overlap_mm`, hide a stepped seam in the outer wall, and key together with non-symmetric registration features. Tolerance is concentrated entirely in `clearance_mm`.

## `tube_gap` (open segment)

Unrelated to `max_print_bounds` segmentation: `tube_gap` cuts an **intentional gap out of the tube** so you can feed wires/LED strips through the cavity later. Two strategies are used depending on the path:

- **Closed-loop knots** (the pyknotid knots drawn via `draw_knot_points`): the point loop is rolled and trimmed by `open_loop_with_gap` before splining, so the sweep is open and its end caps *are* the gap faces. A boolean cut is deliberately avoided here — a closed sweep has coincident start/end caps, and OCC booleans corrupt self-touching solids (webbed faces, open shells).
- **Open paths**: a boolean subtraction — an oversized disc is swept along the sub-path between arc lengths `s0..s1` and cut from the swept tube.

In both cases the gap faces are normal to the path tangent and the gap length is exact when measured along the path — even on curved knots.

Config block under `tube_gap` (see [TubeGapSettings](../src/led_knots/core/config.py#L194)):

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | `false` | Master toggle. Requires `gap_length_mm > 0` when on. |
| `gap_length_mm` | `0.0` | Arc length of tube removed by the subtraction (mm). Internally clamped to at most `0.8 * total_path_length` (with a warning). |
| `center_fraction` | `0.0` | Where to center the gap along the path arc length, in `[-0.5, 0.5]`. `0.0` = path midpoint; `-0.5` biases toward the start, `+0.5` toward the end. The center shifts inward if needed so the full gap always fits. |
| `cutter_radius_mm` | `null` | Open paths only (boolean strategy). Radius of the swept cutter disc. `null` = auto (`1.5 × tube_settings.outer_radius`). Shrink it if the oversized cutter would nick a neighboring strand where the knot passes near itself; it must still exceed the tube's outermost extent to sever it cleanly. |

The implementation lives in [core/tube_gap.py](../src/led_knots/core/tube_gap.py): `open_loop_with_gap` handles closed loops at the point level (invoked by `draw_knot_points` when `drop_last == 0`), while `compute_gap_placement` + `build_gap_cutter` + `apply_tube_gap` implement the boolean strategy for open paths inside `draw_part` (`compute_gap_placement` returns a `TubeGapPlacement` with start/end/mid points and unit tangent for clamp placement). For segmented prints of open paths the cutter is applied per-segment inside `build_segmented_tube_assembly` while segments are still in path coordinates; if a segment boundary falls inside the gap span, a warning is logged because the joint features at that cut get carved away. `apply_tube_gap` raises if handed a closed sweep rather than corrupting it.

## Clamps

A `tube_gap` leaves an opening; the **clamp** is a separately-printed two-half ring that closes that opening, holds the wire, and registers onto both tube ends. The geometry is built by [build_tube_clamp_parts](../src/led_knots/parts/hang_clamp.py#L64) and exposed by the `hang_clamp.py` script.

Local convention used by the builder:

- Clamp axis is local **+Z**.
- Split plane is **Y=0**, so the two halves sit on the `+Y` (`half_with_hole`) and `-Y` (`half_plain`) sides.
- The seam between them is a continuous radial rabbet running the full clamp length.

### Clamp config keys

All keys live under `clamp` (see [ClampSettings](../src/led_knots/core/config.py#L198)):

| Key | Default | Purpose |
| --- | --- | --- |
| `enabled` | `true` | Master toggle for the clamp parts. |
| `clearance_diameter_mm` | `1.0` | Diametral slip-fit allowance: `clamp_id = tube_od + clearance_diameter_mm`. |
| `length_mm` | `18.0` | Axial length of the clamp (Z extent). |
| `wall_thickness_mm` | `2.5` | Radial wall thickness outside the inner bore. |
| `lap_depth_mm` | `1.0` | How far the seam rabbet protrudes across the Y=0 split plane. Male step on `+Y`, matching recess (plus `lap_clearance_mm`) on `-Y`. |
| `lap_step_height_mm` | `1.5` | Radial step height of the seam rabbet, capped at `outer_radius - inner_radius - 0.2` so it never eats the wall. |
| `lap_clearance_mm` | `0.2` | Extra slop in the female seam recess so halves snap together. |
| `wire_hole_diameter_mm` | `4.0` | Through-hole diameter on `half_with_hole`, drilled radially along +Y. |
| `wire_ring_height_mm` | `4.0` | Height of the external collar around the wire hole. |
| `wire_ring_top_thickness_mm` | `1.0` | Collar wall thickness at the outer end. |
| `wire_ring_base_thickness_mm` | `2.0` | Collar wall thickness at the surface end (the collar tapers up from base to top via `loft`). |
| `adhesive_gap_mm` | `0.10` | Explicit glue line thickness, added on top of `reg_clearance_mm` in the tongue-and-groove. |
| `reg_lip_height_mm` | `0.8` | Radial height of the tongue (continuous lip) along the seam on `+Y`. |
| `reg_lip_width_mm` | `1.2` | Width of the tongue across the seam normal (Y). |
| `reg_clearance_mm` | `0.08` | Clearance between tongue and groove (resin-friendly). |
| `relief_enabled` | `true` | When true, three small adhesive escape pockets are cut into the female groove at Z = `-0.25*L`, `0`, `+0.25*L`. |
| `relief_depth_mm` | `0.3` | Radial pocket depth (clamped to ≤ groove width). |
| `relief_width_mm` | `0.5` | Pocket width across the seam normal. |
| `alignment_notch_enabled` | `true` | When true, a key-and-slot tab spans the seam at Z=0 to lock the halves against axial slip. |
| `alignment_notch_width_mm` | `3.0` | Tab length along Z (axial); clamped to `0.5 * L`. |
| `alignment_notch_depth_mm` | `0.8` | Tab protrusion into the mating half (Y); clamped to `lap_depth_mm`. |
| `alignment_notch_clearance_mm` | `0.1` | Slot clearance around the tab. |

All positive fields (everything except `adhesive_gap_mm`, `reg_clearance_mm`, `alignment_notch_clearance_mm` — those allow `0`) are validated to be `> 0` at config load.

### How the clamp pairs with `tube_gap`

The typical workflow:

1. Enable `tube_gap` with a `gap_length_mm` big enough to slip the clamp over both tube ends plus a small overlap.
2. Print the (possibly segmented) tube body; print the two clamp halves separately.
3. Thread the LED wires through `wire_hole_diameter_mm`, bridge the gap with the two clamp halves, and glue the seam — the lap rabbet, tongue-and-groove, alignment notch, and adhesive relief pockets all cooperate to hold alignment while the glue cures.

Use the `--export-parts` CLI flag (next section) to drop the clamp halves into their own STL files for slicing.

## Naming and export

A segmented run yields a `cq.Assembly` with one child per segment named `segment_NN` (zero-padded, in path order). Clamp scripts build an assembly named `Hang Clamp` with children `clamp_half_a` and `clamp_half_b`.

For multi-part STL/STEP/GLB output, [maybe_export_named_parts](../src/led_knots/core/utils.py#L196) accepts a comma-separated selector on the CLI:

```bash
render-knot knot_configs/my_trefoil.yaml \
  --export-parts assembly,tube,clamp_halves \
  --export-parts-dir out/
# Or equivalently with the installed console script:
# render-knot knot_configs/my_trefoil.yaml --disable-export preview,glb
```

Supported tokens:

| Token | Expands to |
| --- | --- |
| `assembly` | The full multi-part assembly as one file. |
| `tube` | The tube body. |
| `clamp_a` | The `half_with_hole` clamp half. |
| `clamp_b` | The `half_plain` clamp half. |
| `clamp_halves` | Both `clamp_a` and `clamp_b`. |
| `all` | Equivalent to `assembly,tube,clamp_a,clamp_b`. |

Filenames are `{config.name or 'knot'}_{token}{ext}` written into `--export-parts-dir`. The extension is taken from `--export` (defaulting to `.stl`); when the extension is `.step`/`.stp` an assembly is exported as STEP, `.glb` exports as GLB, otherwise STL with the `stl_ascii` flag honored. The selector tokens are iterated in sorted order, so file write order is deterministic. The helper is a no-op when either `--export-parts` or `--export-parts-dir` is missing.

See [CLI reference](cli-reference.md) for all related flags and [Mesh export](mesh-export.md) for the underlying writer behavior.

## Do's and don'ts

- **Do** set `max_print_bounds.width/length/height` to your printer's *actual usable* build volume, then pad with `clearance_mm` (default `2.0` in the shipped `config.yaml`) to account for raft, supports, and platform calibration. The shipped example targets an Elegoo Saturn 4 Ultra 16k (200×110×200 mm).
- **Do** enable `--optimize` (and `--auto-orient` to mutate geometry) alongside segmentation in `print_bed` layout so per-segment scores reflect the chosen orientation. See [print-optimization.md](print-optimization.md). In `path` layout the SLA rescoring is skipped on purpose; switch layouts if you want per-segment auto-orient.
- **Do** raise `max_segments` deliberately rather than reflexively. Hitting the cap usually means your output is too large for the bed at the requested face profile, not that the DP is wrong.
- **Don't** set `max_segments` too low for closed knots. When `joint.close_loop: true` is intended for a closed-loop path, the closing joint is logically an extra segment boundary; budget for it explicitly.
- **Don't** shrink `joint.clearance_mm` below your resin print tolerance (~0.15–0.25 mm). Sub-tolerance values produce female sockets that the male pin cannot enter post-cure, and forcing them risks splitting the wall — `clearance_mm` is dilation, not subtraction, so larger means looser.
- **Don't** confuse `max_print_bounds.clearance_mm` (printer-margin shrink applied to width/length/height) with `max_print_bounds.joint.clearance_mm` (joint fit-tolerance). They have different defaults (`0.0` vs `0.2`) and different effects.
- **Don't** rely on `layout_gap_mm` for joint clearance in `path` layout. The gap there is purely cosmetic separation in the viewer; the lap rabbet, registration key, and `joint.clearance_mm` are what make the joint actually fit.

Cross-references: [Configuration reference](configuration.md) for every key in context, [Print optimization](print-optimization.md) for the interplay with per-segment SLA orientation, [Parts](parts.md) for how named assemblies are composed, [Mesh export](mesh-export.md) for the writer side of `--export-parts`.
