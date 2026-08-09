# SLA print optimization

## What it does

The print-optimization stage looks at the tessellated mesh of a built part and reports the things that ruin SLA / resin prints: large overhanging faces, topologically disconnected islands, and trapped internal cavities that would hold uncured resin. It runs after the part is built but before export, so the same pipeline that produces your STL also tells you whether the geometry will actually print.

When asked to take action it also picks a build orientation. The core search is Tweaker-3 (vendored at [src/led_knots/optimize/_tweaker.py](../src/led_knots/optimize/_tweaker.py)), which ranks rotations by an "unprintability" score that prefers low overhang area and a flat bottom. On top of that this codebase adds a connector-aware rescoring step: when a candidate orientation makes the LED-tube connector strips stand vertically — so they double as natural support columns — its score is shaved by a configurable factor. The default bonus is large enough (`0.7`, i.e. 70%) that the connectors-as-supports pose normally wins over Tweaker's default volume-minimising pick.

Optionally, after the part has been re-oriented, the stage can also drill a straight cylinder along the build axis through every trapped cavity, opening both a top vent (to equalise peel pressure) and a bottom drain (so resin escapes under gravity). Drain holes only make sense in a known build orientation, so they require `--auto-orient`.

## Invoking it

There are three command-line flags, all defined in [core/utils.py:103-137](../src/led_knots/core/utils.py#L103). They are wired into config in [core/config.py:555-567](../src/led_knots/core/config.py#L555).

| Flag | Effect | Mutates geometry? |
| --- | --- | --- |
| `--optimize` / `--no-optimize` | Forces `print_optimization.enabled` on or off, overriding the value in `config.yaml`. Runs analyzers and reports orientation candidates. | No — reports only. |
| `--auto-orient` | Implies `--optimize`. Sets `orientation.auto_apply=true` so the top-ranked rotation is applied to the exported geometry. Required for drain holes. | Yes — rotates the part. |
| `--optimize-report-dir DIR` | Implies `--optimize`. Writes the annotated PNG diagnostics (red overhangs, green connectors) into `DIR`. | No — read-only diagnostic output. |

Typical usage:

```bash
# Step 1: read-only inspection on a new part.
render-knot knot_configs/my_trefoil.yaml --optimize --optimize-report-dir reports/trefoil

# Step 2: once the report looks sane, let the optimizer pick + apply orientation.
render-knot knot_configs/my_trefoil.yaml --auto-orient --optimize-report-dir reports/trefoil

# Step 3 (optional): enable drain holes in config.yaml first, then re-run.
render-knot knot_configs/my_trefoil.yaml --auto-orient
```

`--optimize` and `--no-optimize` are mutually exclusive. When none of the three flags are passed, the stage uses whatever `print_optimization.enabled` is set to in [config.yaml:158](../config.yaml#L158) (default: `false`).

## The pipeline

Driven by `optimize_part` in [optimize/__init__.py:242](../src/led_knots/optimize/__init__.py#L242). For a single (non-assembly) part:

1. **Tessellate** the CadQuery part to a coarse `trimesh.Trimesh` via an STL temp file (`_to_trimesh`, [optimize/__init__.py:52](../src/led_knots/optimize/__init__.py#L52)). The optimizer only needs face normals and areas, not viewing-quality smoothness.
2. **Enumerate orientations** with `find_best_orientations` ([orient.py:166](../src/led_knots/optimize/orient.py#L166)) — Tweaker-3 with `min_volume=True`, capped at `top_n_candidates`.
3. **Rescore with connector bonus** ([orient.py:118](../src/led_knots/optimize/orient.py#L118)) when a knot path and tube settings are available, the active face type has connectors, and `connector_bonus_weight > 0`.
4. **Bed-fit gate** (`_filter_candidates_by_bed`, [optimize/__init__.py:191](../src/led_knots/optimize/__init__.py#L191)) drops candidates whose rotated AABB exceeds `max_print_bounds` (minus clearance). If every candidate fails the gate, all are retained with a note instead of returning empty.
5. **Diagnostic warnings**: e.g. when no candidate has any defensible flat side (all `bottom_area_mm2 <= 1.0`), the report flags that supports are unavoidable regardless of orientation ([optimize/__init__.py:371](../src/led_knots/optimize/__init__.py#L371)).
6. **Apply rotation** (`_apply_rotation`, [optimize/__init__.py:89](../src/led_knots/optimize/__init__.py#L89)) — only if `orientation.auto_apply` is true; otherwise the part is returned untouched.
7. **Run analyzers** on the (rotated, if applicable) mesh: `detect_overhangs`, `detect_islands`, `detect_trapped_cavities`. When the orientation was applied, the mesh's vertices are rotated in place to keep face indices valid.
8. **Drill drain holes** (`drill_drain_holes`, [drain_holes.py:39](../src/led_knots/optimize/drain_holes.py#L39)) if drain holes are enabled, orientation was actually applied, and trapped cavities were found. The part is re-tessellated after drilling so PNGs reflect the holes.
9. **Build the report** (`OptimizationReport`, [report.py:62](../src/led_knots/optimize/report.py#L62)) and emit it via `format_console`. If `--optimize-report-dir` was passed, also write the annotated PNGs.

Assembly inputs (the segmented-print flow) are handled per-segment inside `build_segmented_tube_assembly` rather than here; `optimize_part` returns a no-op report for assemblies with `note="skipped: assembly inputs..."`.

## Analysis

All analyzers live in [optimize/analysis.py](../src/led_knots/optimize/analysis.py) and operate on a single `trimesh.Trimesh` in build orientation. None of them mutate the input mesh.

### Overhangs

`detect_overhangs` ([analysis.py:49](../src/led_knots/optimize/analysis.py#L49)) flags every face whose normal makes an angle with straight-down smaller than `overhang_threshold_deg` (default `35.0` for SLA; ~45° for FDM). Faces in the bottom build layer (`z <= z_min + 0.2 mm`) are excluded since they rest on the plate. Surviving faces are grouped into connected clusters via `trimesh.face_adjacency`; clusters under `min_cluster_area_mm2` (default `0.5 mm²`) are dropped as tessellation noise. Returns an `OverhangResult` with per-face boolean mask, sorted cluster list, and total area in mm².

### Islands

`detect_islands` ([analysis.py:140](../src/led_knots/optimize/analysis.py#L140)) splits the mesh into topologically disconnected bodies via `mesh.split(only_watertight=False)`. This is a whole-mesh sanity check — anything beyond one body means something is unanchored. The minimum-area floor defaults to `max(0.5 mm², 0.1% of total mesh area)` so tessellation slivers (the `sine_wave` knot's 325 pseudo-islands, for example) don't drown the report. Per-layer island detection — the more common SLA failure mode — requires a slicer pass and is not implemented here.

### Trapped cavities

`detect_trapped_cavities` ([analysis.py:265](../src/led_knots/optimize/analysis.py#L265)) computes `convex_hull - mesh` as a first-pass cavity finder, then runs a 26-ray trap test on each candidate's centroid. The 26 directions cover the cube's 6 faces, 12 edge-diagonals, and 8 corners — dense enough that any escape opening in a non-convex cavity will leave at least one ray un-hit. A centroid surrounded by the mesh on all 26 rays is `is_trapped=True`; anything with an escape direction is open.

The boolean engine is `manifold3d`. If the package isn't installed, the analyzer returns `CavityResult(available=False, note="cavity detection requires `pip install manifold3d`...")` and the rest of the pipeline continues without it. Drain hole drilling silently skips when cavity detection is unavailable, since it depends on the cavity list.

## Orientation

The orientation search is in [optimize/orient.py](../src/led_knots/optimize/orient.py) and wraps the vendored Tweaker-3 at [optimize/_tweaker.py](../src/led_knots/optimize/_tweaker.py).

**Candidate enumeration.** `find_best_orientations` ([orient.py:166](../src/led_knots/optimize/orient.py#L166)) feeds the mesh's triangles into `Tweak(..., extended_mode=True, min_volume=True)` and returns up to `top_n_candidates` `OrientationCandidate` rows. Each row carries Tweaker's `unprintability` score, the bottom-contact area, the overhang area, the contour length, and — crucially — the same `(axis, angle)` pair Tweaker used to build its rotation matrix. We pass the axis-angle through to `cq.Solid.rotate` unchanged so the CadQuery rotation and the trimesh matrix never drift apart (e.g. through a sign flip at angle = π).

**Unprintability score.** This is Tweaker-3's metric — a combination of overhang area, bottom contact, and contour length, with `min_volume=True` biasing toward low support volume. The number itself is opaque; lower is better, and only relative comparisons within a single run are meaningful.

**Connector bonus.** `connector_verticality_bonus` ([orient.py:87](../src/led_knots/optimize/orient.py#L87)) computes an area-weighted fraction in `[0, 1]` measuring how much of the tagged connector-flank area becomes vertical after a candidate rotation (1 = every tagged face is perfectly vertical; 0 = all horizontal). `rescore_candidates_with_connector_bonus` ([orient.py:118](../src/led_knots/optimize/orient.py#L118)) then multiplies each candidate's `unprintability` by `(1 - connector_bonus_weight * bonus)` and re-sorts.

The default weight is `0.7`. From [config.yaml:167-171](../config.yaml#L167):

> `0.7` means a fully-vertical-connectors orientation cuts Tweaker-3's unprintability score by 70%, usually enough to flip the default volume-minimising pick to the connectors-as-supports pose.

Set `connector_bonus_weight: 0.0` to disable the bonus entirely. The settings validator ([settings.py:33](../src/led_knots/optimize/settings.py#L33)) requires `0.0 <= weight < 1.0`.

**top_n_candidates.** Number of orientations Tweaker returns and rescores. Default `5`; must be `>= 1` ([settings.py:25](../src/led_knots/optimize/settings.py#L25)). Larger values explore more poses at linear cost.

**Bed-fit gate.** `_filter_candidates_by_bed` ([optimize/__init__.py:191](../src/led_knots/optimize/__init__.py#L191)) compares each candidate's rotated AABB extents (largest dimension first) against `max_print_bounds` minus `2 * bed_clearance_mm` on each side. The driver in [core/utils.py:295-301](../src/led_knots/core/utils.py#L295) prefers `max_print_bounds` over `output_bounds` because the former is the explicit printer dimensions; if `max_print_bounds` is not set, it falls back to `output_bounds` with a 2 mm clearance. If every candidate fails, all are retained with a `"no candidate fits the configured bed"` note so the user sees the dimensions rather than silently getting an empty list.

**auto_apply.** When `orientation.auto_apply` is `false` (the default, and what `--optimize` alone leaves it as), the optimizer reports the ranked candidates but does not rotate the part. `--auto-orient` flips this to `true` and the rank-1 candidate is applied via `cq.Solid.rotate((0,0,0), axis, angle_deg)`. Rotation for assemblies raises `NotImplementedError` here — the segmented flow handles that path separately.

## Face tagging

Face tagging ([optimize/face_tagging.py](../src/led_knots/optimize/face_tagging.py)) classifies the faces of a swept LED-tube mesh by structural role. The role this codebase cares about is **connector flank**: the two long flat sides of the radial strips that join the outer ring to the inner tube or oval cavity. Standing those flanks vertically is what makes the connectors act as natural support columns.

The classifier is purely geometric. For each face centroid it finds the nearest path sample, builds a local frame `(T, R_hat, B_hat = T × R_hat)`, and flags faces whose normal aligns with the azimuthal direction `B_hat` (cosine threshold `0.7`, i.e. within ~45° of pure azimuthal). A radial-gap gate also requires the face to sit between the inner feature wall and the outer-ring inner wall, which filters out fillets and end-cap remnants that happen to have an azimuthal normal.

Only the `led_circle`, `led_circle_tube`, and `led_circle_quad_tube` face types have connectors ([face_tagging.py:31](../src/led_knots/optimize/face_tagging.py#L31)). Any other face type (`solid_circle`, `square`, `pyramid_studded`, `braided_rope`, ...) returns an empty connector mask with `note="face type ... has no connectors"`, and the connector bonus is effectively zero.

In the annotated PNG output, the role colors are defined in [report.py:27-30](../src/led_knots/optimize/report.py#L27):

| Category | Color | Notes |
| --- | --- | --- |
| Default | grey `(180, 180, 180)` | Untagged faces. |
| Overhang | red `(255, 60, 60)` | Painted last — wins over connector if a face is both. |
| Connector | green `(60, 200, 100)` | Painted before overhang, so an overhanging connector reads red. |
| Island extra | yellow `(255, 200, 0)` | Defined for future per-island tinting. |

The report itself surfaces overhang clusters (top 3 by area, with centroid), island count, and trapped/open cavity counts. See `format_console` in [report.py:87](../src/led_knots/optimize/report.py#L87) for the exact lines.

## Drain holes

Drain hole drilling runs only when **all** of the following are true ([optimize/__init__.py:427-435](../src/led_knots/optimize/__init__.py#L427)):

- `print_optimization.drain_holes.enabled` is `true` in config.
- `--auto-orient` was passed, so the build axis is actually world Z.
- The cavity analyzer was available (i.e. `manifold3d` is installed) and reported at least one `is_trapped=True` cavity.

For each trapped cavity above the volume threshold, `drill_drain_holes` builds a Z-aligned `cq.Solid.makeCylinder` at the cavity's `(x, y)` centroid spanning `[z_min - margin, z_max + margin]` of the part's AABB, then cuts it from the part. One cylinder pierces both the top wall (vent) and the bottom wall (drain) in a single boolean operation.

Config keys, validated in [settings.py:39](../src/led_knots/optimize/settings.py#L39):

| Key | Default | Description |
| --- | --- | --- |
| `enabled` | `false` | Master toggle. Off by default — opt in only after the cavity report on your part looks correct. |
| `diameter_mm` | `1.5` | Hole diameter. Must be `> 0`. |
| `min_cavity_volume_mm3` | `100.0` | Cavities smaller than this are not drilled. Must be `>= 0`. |
| `margin_mm` | `5.0` | How far past the part's Z-extents the drill cylinder extends on each end, to guarantee clean puncture of both walls. Must be `>= 0`. |

If `drain_holes.enabled` is set but `--auto-orient` is not passed, the stage logs `[optimize] drain_holes enabled but skipped — requires --auto-orient` and does nothing.

> **Warning.** Drilling is geometric, not semantic. The drill goes through whatever sits at the cavity centroid's `(x, y)` along Z — including embedded clamp slots, joint pins, or the LED tube channel itself if the cavity centroid happens to share an XY column with them. **Always** run `--optimize` first and inspect the cavity entries in the console report (and the PNG diagnostics) before flipping `enabled: true`. The `min_cavity_volume_mm3` floor is your primary defence against drilling micro-cavities that are actually tessellation noise.

## Reports

The console report is printed after every optimizer run via `format_console` ([report.py:87](../src/led_knots/optimize/report.py#L87)). It lists the orientation candidates with their unprintability score, bottom-contact area, overhang area, connector bonus (when nonzero), rotated AABB (when the bed-fit gate ran), and axis-angle pair. A `*` marks the applied candidate when `--auto-orient` was passed.

When `--optimize-report-dir DIR` is supplied, `write_annotated_pngs` ([report.py:190](../src/led_knots/optimize/report.py#L190)) writes two PNGs per part into `DIR`:

- `{part_name}_overhangs_top.png` — view from above, elevation `+|preview.elevation|`.
- `{part_name}_overhangs_bottom.png` — view from below, elevation `-|preview.elevation|`. Most SLA overhangs are on the underside; the top view alone usually hides them.

The part name is `slugify(config.name or "knot")` ([core/utils.py:320](../src/led_knots/core/utils.py#L320)). Both views use `report.mesh` (the analyzer mesh, post-rotation and post-drilling if applicable) and the color array assembled by `build_face_color_array` ([report.py:170](../src/led_knots/optimize/report.py#L170)) — overhangs in red over connectors in green over default grey. The view angles otherwise inherit from `preview.*` in `config.yaml`. If neither overhangs nor connector tags were computed, no PNGs are written.

## Configuration reference

All keys live under `print_optimization:` in [config.yaml:158-181](../config.yaml#L158). See the full [Configuration reference](configuration.md) for the surrounding context; this table is the in-line view.

| Key | Default | Units | Description |
| --- | --- | --- | --- |
| `print_optimization.enabled` | `false` | bool | Master toggle. CLI `--optimize` / `--no-optimize` / `--auto-orient` / `--optimize-report-dir` all override this. |
| `print_optimization.target` | `sla` | enum | `sla` or `fdm`. PR1 wires up `sla` only. |
| `print_optimization.overhang_threshold_deg` | `35` | deg | Faces within this angle of straight-down count as overhangs. Validator requires `(0, 90)`. SLA: ~35°; FDM: ~45°. |
| `print_optimization.orientation.enabled` | `true` | bool | When false, `optimize_part` returns a no-op report with `note="orientation disabled in config"`. |
| `print_optimization.orientation.auto_apply` | `false` | bool | When true, the rank-1 candidate is applied to the geometry. `--auto-orient` flips this to true at runtime. |
| `print_optimization.orientation.top_n_candidates` | `5` | int | Number of Tweaker-3 orientations to keep and rescore. Must be `>= 1`. |
| `print_optimization.orientation.connector_bonus_weight` | `0.7` | float | Multiplicative shave on `unprintability` for connector-vertical poses. Must be in `[0, 1)`. `0` disables; `0.7` means a fully-vertical-connectors orientation cuts the score by 70%. |
| `print_optimization.drain_holes.enabled` | `false` | bool | Master toggle for drain/vent drilling. Requires `--auto-orient` and an available cavity analyzer. |
| `print_optimization.drain_holes.diameter_mm` | `1.5` | mm | Hole diameter. Must be `> 0`. |
| `print_optimization.drain_holes.min_cavity_volume_mm3` | `100.0` | mm³ | Cavities below this volume are not drilled. Must be `>= 0`. |
| `print_optimization.drain_holes.margin_mm` | `5.0` | mm | Distance the drill cylinder extends past the part's Z-extents on each end. Must be `>= 0`. |

The bed-fit gate also reads `max_print_bounds.width`/`length`/`height` and `max_print_bounds.clearance_mm` when they're set. See the segmentation doc for those keys.

## Do's and don'ts

- **Do** run `--optimize` (read-only) first on a new part. Inspect the console report and the PNGs in `--optimize-report-dir` before ever passing `--auto-orient`.
- **Do** verify the trapped-cavity report on your specific part — including centroids and volumes — before flipping `print_optimization.drain_holes.enabled` to `true`. Drilling is geometric and will happily cut through anything that happens to share an XY column with a cavity centroid.
- **Do** install `manifold3d` (`pip install manifold3d`) if you want cavity detection. Without it, the analyzer returns a `available=False` note and drain holes are silently skipped.
- **Don't** enable `max_print_bounds` without setting its `width`/`length`/`height` to match your actual printer. The bed-fit gate uses those dimensions verbatim minus `clearance_mm`; wrong numbers will reject otherwise-fine orientations and may print the `"no candidate fits the configured bed"` note for every part.
- **Don't** expect the optimizer to fix bad geometry. It picks an orientation (and optionally adds drain holes); it does not change topology, add chamfers, fill voids, or split a part. If every candidate has `<= 1 mm²` of bed contact, the report says so explicitly — supports will be needed regardless of which orientation you pick.
- **Don't** enable drain holes without `--auto-orient`. They depend on world-Z being the build axis, and the stage will log a skip message and do nothing otherwise.
