# Code map

A per-file reference of the `led_knots` package, its scripts, and its tests. Use this page to find the right module fast; deep dives live in [architecture.md](architecture.md), [tube-models.md](tube-models.md), [paths.md](paths.md), [print-segmentation.md](print-segmentation.md), [print-optimization.md](print-optimization.md), and [parts.md](parts.md).

## src/led_knots/

Top-level package. [`__init__.py`](../src/led_knots/__init__.py) declares `__version__` and re-exports the everyday helpers from `core` (`parse_args`, `render_part`, `scale_pyknot_points`, the path-utility functions, and the `create_*_face` cross-section factories) so user scripts can `from led_knots import ...` without diving into subpackages. Subpackages: [`core`](#srcled_knotscore) (shared utilities and the CAD pipeline), [`core/tube_models`](#srcled_knotscoretube_models) (face-type registry), [`knots`](#srcled_knotsknots) (one console script per knot/path), [`optimize`](#srcled_knotsoptimize) (SLA print-prep stage), and [`parts`](#srcled_knotsparts) (accessory hardware).

## src/led_knots/core/

Shared CAD pipeline: config loading, path framing, tube sweeping, segmentation, rendering, preview, and caching.

| File | Purpose |
| --- | --- |
| [`__init__.py`](../src/led_knots/core/__init__.py) | Re-exports the public surface: `parse_args`, `render_part`, `draw_part`, `build_tube_from_path`, `maybe_export_named_parts`, `scale_pyknot_points`, and the path-spine helpers. |
| [`cache_utils.py`](../src/led_knots/core/cache_utils.py) | Builds deterministic cache filenames for preview STLs from part name, sampled path geometry, face kwargs, and config. |
| [`color_palette.py`](../src/led_knots/core/color_palette.py) | Harmonious color palette + `ColoredShape` wrapper + assembly helpers so cadquery-web-viewer renders each part in a distinct color. |
| [`config.py`](../src/led_knots/core/config.py) | Loads `config.yaml` (+ `config.local.yaml` overrides), validates face types, exposes a typed config object; see [Configuration reference](configuration.md). |
| [`led_circle.py`](../src/led_knots/core/led_circle.py) | 2D cross-section factories used by the swept tube models: `create_led_circle_face`, `create_led_circle_tube_face`, `create_solid_circle_face`, `create_square_face`, plus geometry validation. |
| [`path_frames.py`](../src/led_knots/core/path_frames.py) | Parallel-transported frames along a centerline `Wire`; single source of truth consumed by every tube model. |
| [`path_utils.py`](../src/led_knots/core/path_utils.py) | Path curvature sampling, optimal twist computation, and ribbon / variable-twist auxiliary-spine builders. See [Path framing](paths.md). |
| [`preview.py`](../src/led_knots/core/preview.py) | Off-screen GLB / STL → PNG rendering via trimesh + pyrender + Pillow. |
| [`print_joint.py`](../src/led_knots/core/print_joint.py) | Registration pins and lap-joint geometry for segmented prints. |
| [`print_segmentation.py`](../src/led_knots/core/print_segmentation.py) | Wire-driven segmentation: splits a tube into print-bed-sized chunks with joints. See [Print segmentation](print-segmentation.md). |
| [`pyknot_utils.py`](../src/led_knots/core/pyknot_utils.py) | `scale_pyknot_points`: aspect-preserving rescale of pyknotid point arrays into a target bounding box. |
| [`render_pipeline.py`](../src/led_knots/core/render_pipeline.py) | Dependency-resolved render pipeline: turns CLI outcomes (preview / export / viewer / mesh) into STL + GLB built at most once and fanned out. |
| [`utils.py`](../src/led_knots/core/utils.py) | `parse_args`, `render_part`, `draw_part`, `build_tube_from_path`, `maybe_export_named_parts` — the high-level glue every knot module calls. |

## src/led_knots/core/tube_models/

Registry of `face_type → TubeModel` implementations. A `TubeModel` turns a centerline path into a 3D `Solid` or `Compound`. See [Tube models](tube-models.md).

| File | Purpose |
| --- | --- |
| [`__init__.py`](../src/led_knots/core/tube_models/__init__.py) | `_REGISTRY` mapping `face_type` strings to model instances plus `get_tube_model()` lookup. |
| [`_base.py`](../src/led_knots/core/tube_models/_base.py) | Runtime-checkable `TubeModel` `Protocol` defining the `build(path, aux, config, ...)` contract. |
| [`braided_rope.py`](../src/led_knots/core/tube_models/braided_rope.py) | Academic-grounded (He et al. 2020; Kyosev) braided-rope sleeve along the centerline using shared `path_frames`. |
| [`pyramid_studded.py`](../src/led_knots/core/tube_models/pyramid_studded.py) | Smooth base sweep with discrete 4-sided pyramid solids placed in axial rows on the outer surface; returned as a `Compound`. |
| [`swept_face.py`](../src/led_knots/core/tube_models/swept_face.py) | Single 2D face swept along the path; backs the `led_circle`, `led_circle_tube`, `solid_circle`, and `square` registry entries. |

## src/led_knots/knots/

One module per centerline shape. Each runs its entire pipeline at module
import time (no `main()` wrapper) by calling `draw_part(path, config)` after
constructing its path. The canonical invocation is `python -m
led_knots.knots.<name>`; ten of the modules also have `led-knots-*` console
scripts listed in [pyproject.toml](../pyproject.toml#L42) (see the
console-script note in the [developer guide](developer-guide.md)).

| Module | Console script | Shape |
| --- | --- | --- |
| [`rod.py`](../src/led_knots/knots/rod.py) | `led-knots-rod` | Straight vertical pipe along Z. |
| [`ring.py`](../src/led_knots/knots/ring.py) | `led-knots-ring` | Simple circular ring (uses pyknotid `unknot`). |
| [`helix.py`](../src/led_knots/knots/helix.py) | `led-knots-helix` | Helical spiral; computes pitch angle from pitch and radius. |
| [`sine_wave.py`](../src/led_knots/knots/sine_wave.py) | `led-knots-sine-wave` | Multi-period sine wave path. |
| [`trefoil.py`](../src/led_knots/knots/trefoil.py) | `led-knots-trefoil` | Mathematical trefoil knot via `pyknotid.make.trefoil` and a ribbon aux spine. |
| [`figure_8.py`](../src/led_knots/knots/figure_8.py) | `led-knots-figure-8` | Figure-8 / torus knot via `pyknotid.make.torus_knot`. |
| [`jog_bend.py`](../src/led_knots/knots/jog_bend.py) | `led-knots-jog-bend` | 2D jog bend (S-curve in one plane). |
| [`jog_bend_3d.py`](../src/led_knots/knots/jog_bend_3d.py) | `led-knots-jog-bend-3d` | 3D jog bend with ribbon-aware twist control. |
| [`quarter_turn.py`](../src/led_knots/knots/quarter_turn.py) | `led-knots-quarter-turn` | 90° turn between two tangent-controlled endpoints. |
| [`twisted_rod.py`](../src/led_knots/knots/twisted_rod.py) | `led-knots-twisted-rod` | Straight rod with a 90° twist driven by an auxiliary helical spine. |
| [`stevedore.py`](../src/led_knots/knots/stevedore.py) | (no script — run via `python -m`) | Stevedore knot (k6_1) via `pyknotid.make`. |
| [`k4_1.py`](../src/led_knots/knots/k4_1.py) | (no script — run via `python -m`) | k4_1 knot via `pyknotid.make`. |
| [`k8_21.py`](../src/led_knots/knots/k8_21.py) | (no script — run via `python -m`) | k8_21 knot via `pyknotid.make`. |

See [CLI reference](cli-reference.md) for the flags every knot accepts.

## src/led_knots/optimize/

SLA / resin print preparation: orient the part for printing, detect overhangs / islands / cavities, and drill drain holes. Public entry point is `optimize_part(part, opt_settings, *, name=None)`. See [Print optimization](print-optimization.md).

| File | Purpose |
| --- | --- |
| [`__init__.py`](../src/led_knots/optimize/__init__.py) | `optimize_part` entry point that runs orientation search, analyzers, and drain-hole drilling. |
| [`_tweaker.py`](../src/led_knots/optimize/_tweaker.py) | Verbatim vendored copy of Tweaker-3's `MeshTweaker.py` (GPL-3.0-or-later) for build-orientation scoring. |
| [`analysis.py`](../src/led_knots/optimize/analysis.py) | Mesh analyzers: `detect_overhangs`, `detect_islands`, `detect_trapped_cavities`. Pure functions over a trimesh in print orientation. |
| [`drain_holes.py`](../src/led_knots/optimize/drain_holes.py) | Drills vent / drain cylinders along world Z through each trapped cavity's centroid; requires `orientation.auto_apply=True`. |
| [`face_tagging.py`](../src/led_knots/optimize/face_tagging.py) | Tags mesh faces by structural role (e.g. "connector flank") using nearest path-sample local frames. |
| [`orient.py`](../src/led_knots/optimize/orient.py) | Adapter around the vendored Tweaker that returns the top-N `OrientationCandidate`s and silences upstream stdout. |
| [`report.py`](../src/led_knots/optimize/report.py) | `OrientationCandidate` / report dataclasses, console formatter, and face-color array builder for annotated PNGs. |
| [`settings.py`](../src/led_knots/optimize/settings.py) | YAML-block-mirrored settings classes (`OrientationSettings`, etc.) with validation in `__init__`. |

## src/led_knots/parts/

Parametric accessory hardware that mounts to the swept tubes.

| File | Purpose |
| --- | --- |
| [`__init__.py`](../src/led_knots/parts/__init__.py) | Package marker for the accessory parts. |
| [`hang_clamp.py`](../src/led_knots/parts/hang_clamp.py) | Two-piece tube clamp (`TubeClampParts`, `to_assembly`) for hanging a knot from above. |
| [`planet_spacer.py`](../src/led_knots/parts/planet_spacer.py) | Thick washer-like spacer (`build_planet_spacer`) parameterised in inches with optional fillet. |

See [Parts](parts.md) for assembly diagrams.

## scripts/

Standalone developer scripts, not part of the installed package.

| Script | What it does | When to run it |
| --- | --- | --- |
| [`generate_previews.py`](../scripts/generate_previews.py) | Runs each knot module with `--preview` and writes PNGs into `assets/`. | Refresh README and GitHub project visuals after geometry or config changes. |
| [`inspect_mesh.py`](../scripts/inspect_mesh.py) | Read-only trimesh inspector reporting watertightness and basic diagnostics for a `.glb` / `.obj` / `.stl` / etc. | Debugging exported meshes before slicing. |

## tests/

`pytest` suite (`uv run pytest tests/`). Currently focused on the print-optimization stage.

| Test file | Subsystem covered |
| --- | --- |
| [`__init__.py`](../tests/__init__.py) | Package marker for the test suite. |
| [`test_optimize_analysis.py`](../tests/test_optimize_analysis.py) | `optimize.analysis` overhang / island / trapped-cavity detectors. |
| [`test_optimize_drain_holes.py`](../tests/test_optimize_drain_holes.py) | `optimize.drain_holes` vent / drain cylinder drilling. |
| [`test_optimize_face_tagging.py`](../tests/test_optimize_face_tagging.py) | `optimize.face_tagging` classification on a synthetic swept LED tube built via the real pipeline. |
| [`test_optimize_orient.py`](../tests/test_optimize_orient.py) | `optimize.orient` scoring helpers and the Tweaker-3 wrapper. |
