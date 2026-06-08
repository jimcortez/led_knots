# CLI reference

Every knot in `led_knots` is its own runnable script. There is no single top-level
binary or subcommands — each knot module owns its own `argparse` parser,
instantiated by a shared helper in
[src/led_knots/core/utils.py](../src/led_knots/core/utils.py). All knot scripts
therefore accept the same set of flags, documented below (including the shared
`--config` overlay flag).

## Console scripts

The following scripts are declared in [pyproject.toml](../pyproject.toml#L42-L52)
under `[project.scripts]`. After `pip install -e .` (or `uv pip install -e .`),
each is on `$PATH` and dispatches to the named module's `main()` (which is the
top-level execution of the knot file).

| Script | Module | Description |
| --- | --- | --- |
| `led-knots-rod` | [led_knots.knots.rod](../src/led_knots/knots/rod.py) | Straight vertical pipe; the simplest possible swept path. |
| `led-knots-ring` | [led_knots.knots.ring](../src/led_knots/knots/ring.py) | Closed circular ring. |
| `led-knots-helix` | [led_knots.knots.helix](../src/led_knots/knots/helix.py) | Cylindrical helix. |
| `led-knots-sine-wave` | [led_knots.knots.sine_wave](../src/led_knots/knots/sine_wave.py) | Sine-wave path swept into a tube. |
| `led-knots-trefoil` | [led_knots.knots.trefoil](../src/led_knots/knots/trefoil.py) | Trefoil (3_1) knot. |
| `led-knots-figure-8` | [led_knots.knots.figure_8](../src/led_knots/knots/figure_8.py) | Figure-eight (4_1) knot. |
| `led-knots-jog-bend` | [led_knots.knots.jog_bend](../src/led_knots/knots/jog_bend.py) | Planar jog-bend test path. |
| `led-knots-jog-bend-3d` | [led_knots.knots.jog_bend_3d](../src/led_knots/knots/jog_bend_3d.py) | 3D jog-bend test path. |
| `led-knots-quarter-turn` | [led_knots.knots.quarter_turn](../src/led_knots/knots/quarter_turn.py) | Single quarter-turn elbow. |
| `led-knots-twisted-rod` | [led_knots.knots.twisted_rod](../src/led_knots/knots/twisted_rod.py) | Vertical rod with axial twist applied to the cross-section. |

A few knot modules ship in the package but are not exposed as console scripts
(notably [k4_1.py](../src/led_knots/knots/k4_1.py),
[k8_21.py](../src/led_knots/knots/k8_21.py), and
[stevedore.py](../src/led_knots/knots/stevedore.py)). Invoke those with the
module form below.

## Equivalent module invocation

For every console script `led-knots-<name>` there is an exactly equivalent
module invocation:

```bash
python -m led_knots.knots.<name>
```

The two forms execute the same file with the same `argparse` parser and the
same effect — with one current caveat: knot modules do not yet define a
`main()` symbol, so the `led-knots-*` wrappers raise
`ImportError: cannot import name 'main' …` after the module's import-time
side effects (path build + `--export` write) have already run. The `--export`
file is produced correctly, but the wrapper exits non-zero. The `python -m`
form has no such issue. See the console-script note in the
[developer guide](developer-guide.md#knot-modules-execute-geometry-at-import-time)
for context. Use the console-script form for daily, interactive runs — it is
shorter and benefits from shell completion if you have it configured. Use the
module form when:

- You are running a knot module that is not registered as a console script
  (e.g. `python -m led_knots.knots.stevedore`).
- You are testing changes inside a virtualenv where the entry-point shims have
  not been regenerated (`pip install -e .` re-registers them, but you may
  prefer not to reinstall after every edit).
- You are invoking from another Python tool (subprocess, Make, CI) and want to
  bind to a specific `python` interpreter rather than rely on `$PATH`.
- You need to import-then-run the module under a profiler or debugger
  (`python -X dev -m led_knots.knots.trefoil`).

Behaviorally there is no difference.

## Flags

All flags are parsed by `parse_args()` in
[core/utils.py:32](../src/led_knots/core/utils.py#L32). The flag set is the
same for every knot script.

### `--config FILE`

- **Type:** path string.
- **Default:** `None`.
- **Effect:** Loads a YAML overlay and deep-merges it on top of `config.yaml`
  and `config.local.yaml`. Only keys present in the overlay file are changed;
  nested dicts are merged key-by-key. Relative paths resolve against the
  repository root (same anchor as `config.yaml`), so `configs/foo.yaml` works
  regardless of the current working directory.
- **Precedence:** Wins over both YAML files; individual flags such as
  `--optimize` still override matching keys afterward.
- **Errors:** Raises `FileNotFoundError` if the overlay path does not exist.

```bash
led-knots-trefoil --config configs/permutations/braided-tight.yaml --export out/trefoil.stl
```

See [Configuration](configuration.md) for layering rules and worked examples.

### `--export FILEPATH`

- **Type:** path string (no quoting required if your shell does not split it).
- **Default:** `None`.
- **Accepted suffixes:** `.stl`, `.step`, `.stp`, `.3mf`, `.glb`, `.gltf`. The
  pipeline picks the export path based on the extension; see
  [render-and-preview pipeline](rendering-and-preview.md) for details.
- **Effect:** Triggers a final geometry export of the assembled part. Internally
  fills `config.export.filepath`; tolerance and angular tolerance come from
  `export.*` in [config.yaml](../config.yaml).
- **Interactions:** When combined with `--preview` and a `.stl` export, the
  same STL is reused as the source for the PNG instead of being re-tessellated
  (see `preview_uses_export_stl` in
  [render_pipeline.py:349](../src/led_knots/core/render_pipeline.py#L349)).
  When `--auto-orient` is set, the exported geometry is the rotated, optimized
  pose.

```bash
led-knots-trefoil --export out/trefoil.stl
led-knots-ring    --export out/ring.step
```

### `--output-mesh FILEPATH`

- **Type:** path string.
- **Default:** `None`.
- **Accepted suffixes:** `.obj` only (the pipeline logs an error and skips for
  any other extension; see
  [render_pipeline.py:178](../src/led_knots/core/render_pipeline.py#L178)).
- **Effect:** Writes a simulation-focused mesh via trimesh, intended for
  physics engines. Honors the `mesh.*` block in [config.yaml](../config.yaml):
  `unit_scale_mm_to_m` (default `true`, converts mm to meters for Genesis and
  similar engines), `target_face_count` (optional decimation target), and
  `watertight_required` (default `true`, fails the export if the mesh is not
  watertight).
- **Interactions:** When `--server`/`--viewer` is in use, the OBJ is derived
  from the GLB sent to the viewer. Otherwise the pipeline produces a dedicated
  mesh from the CadQuery solid.

```bash
led-knots-helix --output-mesh sim/helix.obj
```

### `--preview FILEPATH`

- **Type:** path string.
- **Default:** `None`.
- **Effect:** Writes a rendered PNG of the model at `FILEPATH` using the
  `preview.*` settings from [config.yaml](../config.yaml) — image size, DPI,
  camera (`elevation`, `azimuth`, `roll`), lights, opacity, color, and
  background. Tessellation uses `preview.mesh_tolerance` and
  `preview.mesh_angular_tolerance`.
- **Interactions:** Combined with `--export`, the preview is generated from
  whichever export source minimizes redundant tessellation: a `.stl` export
  reuses the exported STL; a viewer/GLB run reuses the GLB; otherwise a
  fresh STL is written into `preview.stl_cache` (default `cache/preview`).

```bash
led-knots-figure-8 --preview out/figure_8.png
led-knots-figure-8 --export out/figure_8.stl --preview out/figure_8.png
```

### `--server`

- **Type:** boolean flag.
- **Default:** `False`.
- **Effect:** Legacy flag that enables the browser preview using whatever
  `server.viewer.mode` is set in [config.yaml](../config.yaml) (`embedded` or
  `remote`). If the YAML mode is `off`, `--server` falls back to `embedded`.
- **Interactions:** `--viewer` always overrides `--server`. When both are
  absent the viewer is disabled (`config.viewer_enabled = False`). The
  embedded server reads `server.viewer.embedded.{host,port,open_browser,
  wait_for_first_client,block_until_disconnect}`; the remote client reads
  `server.viewer.remote.{host,port,upload_timeout,post_timeout}`.

```bash
led-knots-trefoil --server
```

### `--viewer MODE`

- **Type:** string from a fixed choice set.
- **Default:** `None` (no override; YAML and `--server` decide).
- **Accepted values:**
  - `off` — disables the viewer regardless of `--server` or YAML.
  - `embedded` — starts the cadquery-web-viewer in-process server on
    `server.viewer.embedded.{host,port}` (default `127.0.0.1:32323`) and
    returns control to the shell after the first client connects (or
    immediately if `wait_for_first_client` is `false`).
  - `embedded-block` — same as `embedded` but holds the process until the
    browser disconnects (`viewer_block_until_disconnect = True`). Useful for
    interactive exploration where you do not want the script to terminate and
    tear down the server.
  - `remote` — posts the GLB to an already-running cadquery-web-viewer at
    `server.viewer.remote.{host,port}` (default `localhost:32323`). When this
    mode is used and there is no follow-up GLB work, the process exits
    immediately after the upload completes
    ([render_pipeline.py:158](../src/led_knots/core/render_pipeline.py#L158)).
- **Effect:** Overrides `server.viewer.mode` from the YAML. Sets
  `config.viewer_enabled`, `viewer_server_type` (`'in-process'` or `'remote'`),
  `viewer_block_until_disconnect`, and either `viewer_server_options` or
  `viewer_remote_options` (see
  [config.py:569](../src/led_knots/core/config.py#L569)).
- **Interactions:** Takes precedence over `--server`. `embedded-block` is the
  only way to force blocking behavior from the CLI without editing YAML.

```bash
led-knots-ring --viewer embedded
led-knots-ring --viewer embedded-block
led-knots-ring --viewer remote
led-knots-ring --viewer off    # disables even when server.viewer.mode = embedded
```

### `--optimize` / `--no-optimize`

- **Type:** mutually exclusive boolean pair (argparse group; passing both is
  an error).
- **Default:** unset; falls back to `print_optimization.enabled` in
  [config.yaml](../config.yaml).
- **Effect:** Force-enables or force-disables the SLA print-optimization stage
  (overhang scoring, orientation ranking, optional cavity/drain analysis).
  Internally sets `config.print_optimization.enabled` after parsing
  ([config.py:558](../src/led_knots/core/config.py#L558)).
- **Interactions:** `--auto-orient` and `--optimize-report-dir` both imply
  `--optimize`; passing `--no-optimize` alongside either of them is currently
  resolved by the implication path (the optimizer turns on). For predictable
  results, use one of the three forms explicitly.

```bash
led-knots-trefoil --optimize
led-knots-trefoil --no-optimize    # skip the stage even if config enables it
```

### `--auto-orient`

- **Type:** boolean flag.
- **Default:** `False`.
- **Effect:** After the optimizer ranks candidate build orientations, apply
  the top-ranked rotation to the exported geometry and to any downstream
  artifacts (STL, GLB, preview, mesh). Without this flag the optimizer
  produces a report but does not rotate the model. Internally sets
  `print_optimization.orientation.auto_apply = True`.
- **Interactions:** Implies `--optimize`. Required for the drain-hole drilling
  pass to actually run (the pass logs `drain_holes enabled but skipped —
  requires --auto-orient` otherwise; see
  [optimize/__init__.py:458](../src/led_knots/optimize/__init__.py#L458)).

```bash
led-knots-trefoil --auto-orient --export out/trefoil.stl
```

### `--optimize-report-dir DIR`

- **Type:** directory path (created if missing).
- **Default:** `None`.
- **Effect:** Writes annotated PNG diagnostics for the optimizer run into
  `DIR` — overhangs in red, supports highlighted, etc. Files are named with a
  slugified part name. See
  [optimize/report.py](../src/led_knots/optimize/report.py).
- **Interactions:** Implies `--optimize`. Only applies to single-piece parts;
  segmented assemblies driven by `max_print_bounds.enabled = true` are
  rescored per segment inside `build_segmented_tube_assembly` and the
  whole-part annotated PNG step is skipped (see
  [core/utils.py:284](../src/led_knots/core/utils.py#L284)).

```bash
led-knots-trefoil --optimize-report-dir out/opt_diag/
```

### `-v`, `--verbose`

- **Type:** boolean flag.
- **Default:** `False`.
- **Effect:** Calls `logging.basicConfig(level=logging.DEBUG)` immediately
  after argument parsing
  ([core/utils.py:141](../src/led_knots/core/utils.py#L141)). All
  `led_knots.*` loggers begin emitting DEBUG. There is no per-module log
  level flag — verbose is global.

```bash
led-knots-trefoil -v --export out/trefoil.stl
```

### `--export-parts PARTS`

- **Type:** comma-separated token list.
- **Default:** `None`.
- **Accepted tokens:** `assembly`, `tube`, `clamp_a`, `clamp_b`,
  `clamp_halves` (expands to `clamp_a,clamp_b`), `all` (expands to
  `assembly,tube,clamp_a,clamp_b`).
- **Effect:** Drives the optional per-part export helper
  `maybe_export_named_parts` in
  [core/utils.py:196](../src/led_knots/core/utils.py#L196). Only applies to
  knots that build an `Assembly` with named parts (tube + 2-piece clamp).
- **Interactions:** Requires `--export-parts-dir` to be set; without it the
  helper returns silently. The file extension for each part follows
  `--export` (default `.stl` when `--export` is also absent).

### `--export-parts-dir DIR`

- **Type:** directory path (created if missing).
- **Default:** `None`.
- **Effect:** Destination directory for files written by `--export-parts`.
  Filenames are `<config.name>_<token>.<ext>`.
- **Interactions:** No-op unless `--export-parts` is also set.

```bash
led-knots-trefoil --export out/trefoil.stl \
                  --export-parts clamp_halves \
                  --export-parts-dir out/parts/
```

## Default behavior with no flags

Running a knot script with no flags is the canonical "build it headlessly and
check the math" mode:

```bash
led-knots-trefoil
```

In this mode:

- Config is loaded from [config.yaml](../config.yaml) with optional overrides
  from [config.local.yaml](../config.local.yaml) deep-merged on top.
- The path is constructed, sampled, twisted, and swept into a tube.
- If `max_print_bounds.enabled = true`, the path is segmented into printable
  pieces; otherwise a single tube is produced.
- If `print_optimization.enabled = true` in YAML, the optimizer runs and
  prints a report to stdout (but does **not** rotate the model — that takes
  `--auto-orient`).
- No file is written and no viewer is launched
  (`config.export.filepath`, `config.preview_filepath`, `config.mesh.filepath`,
  and `config.viewer_enabled` are all falsy). The render pipeline's
  `has_side_effects` property returns `False`
  ([render_pipeline.py:330](../src/led_knots/core/render_pipeline.py#L330))
  and the run finishes after construction.

This is the fastest way to confirm a knot builds successfully before deciding
what to export.

## Exit codes and errors

The CLI relies on Python's default exit conventions: `0` on success, `1` for
an uncaught exception, and `2` for argparse errors. There are no custom exit
codes. The most common error paths you will hit:

### Twist-rate `ValueError`

Raised from `build_variable_twist_spine` in
[core/path_utils.py:550](../src/led_knots/core/path_utils.py#L550) when the
path requires more twist between two samples than
`path.min_90_degree_twist_distance` allows. The check is
`required_twist <= (90 / min_90_degree_twist_distance) * arc_length`. To fix,
either lower `path.min_90_degree_twist_distance` in `config.yaml` (allowing
faster twist) or relax the underlying knot geometry.

### `manifold3d` missing for drain holes

The trapped-cavity analyzer in
[optimize/analysis.py:210](../src/led_knots/optimize/analysis.py#L210)
imports `manifold3d` lazily. When it is absent, the optimizer reports a
single-line note (`cavity detection requires pip install manifold3d (boolean
engine).`) and skips the cavity stage rather than failing the build. The
package is declared as a hard dependency in `pyproject.toml` so a clean install
includes it; if you are seeing this note, your environment is incomplete —
run `pip install manifold3d` (or `uv sync`).

### Bed-fit rejection

When `print_optimization` is enabled on a single-piece part, the optimizer
filters orientation candidates against the bed dimensions. The bed reference
is `max_print_bounds` when its `width`/`length`/`height` are positive,
otherwise `output_bounds`. The clearance is `max_print_bounds.clearance_mm`
(default `2.0`). If no candidate fits, the optimizer keeps reporting but
appends a note like:

```
no candidate fits the configured bed (200x200x250mm, clearance 2.0mm);
reporting all anyway. Consider enabling max_print_bounds for segmentation.
```

(See [optimize/__init__.py:360](../src/led_knots/optimize/__init__.py#L360).)

### Segmentation failures

With `max_print_bounds.enabled = true`, two errors can come out of the
segmentation planner in
[core/print_segmentation.py](../src/led_knots/core/print_segmentation.py):

- `RuntimeError: Could not segment path to fit max_print_bounds. Increase
  bounds or reduce output size.` — no single contiguous run of the path fits
  inside the (clearance-shrunk) print volume from any rotation. Increase
  `max_print_bounds.width/length/height`, reduce `output_bounds`, or lower
  `max_print_bounds.clearance_mm`.
- `RuntimeError: Segmentation required N segments but
  max_print_bounds.max_segments=M.` — a fit was found, but it required more
  pieces than `max_segments` allows. Raise `max_segments` or enlarge the
  printable volume.

### Config validation errors

`Config(...)` raises `ValueError` on construction for invalid YAML — bad
`face_type`, negative dimensions, unknown viewer mode, `min_90_degree_twist_
distance <= 0`, joint or clamp dimensions out of range, and so on. See the
class constructors in [core/config.py](../src/led_knots/core/config.py) for
the exhaustive list.

## Environment variables

Almost all configuration goes through YAML and CLI flags. The exceptions are
the `CADQUERY_WEB_VIEWER_*` variables, which `cadquery_web_viewer` reads at
import time. The `ServerSettings` class bridges five YAML keys into env vars
by calling `apply_to_env()` from `get_config()`:

| YAML (`server.*`) | Environment variable |
| --- | --- |
| `protocol` | `CADQUERY_WEB_VIEWER_PROTOCOL` |
| `texture` | `CADQUERY_WEB_VIEWER_TEXTURE` |
| `color_faces` | `CADQUERY_WEB_VIEWER_COLOR_FACES` |
| `color_edges` | `CADQUERY_WEB_VIEWER_COLOR_EDGES` |
| `color_vertices` | `CADQUERY_WEB_VIEWER_COLOR_VERTICES` |

The mapping is defined in
[core/config.py:398](../src/led_knots/core/config.py#L398). Only keys whose
YAML value is not `None` are set, so the viewer's own defaults still apply
for anything you leave unspecified. If you set these env vars yourself before
launching the script, the YAML bridge will overwrite them — set them in
`config.local.yaml` instead.

No other environment variables are read by `led_knots`. Logging level is
controlled exclusively by `-v` / `--verbose`; cache directories come from
`preview.stl_cache` in YAML; the project root is resolved relative to
`config.py`'s own location, not from `$PWD` or any env var.

## See also

- [Configuration reference](configuration.md) — every `config.yaml` key, with
  defaults and types.
- [Rendering and preview](rendering-and-preview.md) — how `--export`,
  `--preview`, `--output-mesh`, and `--viewer` combine inside the render
  pipeline, and which artifact reuses which.
