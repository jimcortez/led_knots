# Developer guide

This guide captures the conventions, helpers, and rough edges you need to be
productive in `led_knots` without breaking the things you can't see. Read it
before adding a new knot, a new tube model, or a new optional dependency.

Cross-references:

- [Architecture overview](architecture.md) — module map and data flow.
- [Configuration reference](configuration.md) — every key in `config.yaml`.
- [Knot authoring guide](paths.md) — deeper recipe for adding a knot.
- [Tube models](tube-models.md) — how `face_type` is dispatched.
- [Print optimization](print-optimization.md) — the `optimize/` package.

## Setup

`led_knots` targets **Python 3.12 only** (`requires-python = ">=3.12,<3.13"`
in [pyproject.toml](../pyproject.toml#L6)). Anything newer will not resolve
because `cadquery`'s vendored `OCP` wheels are pinned to 3.12 in this lock.

The supported workflow uses [uv](https://github.com/astral-sh/uv):

```bash
# from the repo root
uv venv --python 3.12
uv pip install -e ".[dev]"
```

The `[dev]` extra (defined in [pyproject.toml](../pyproject.toml#L36)) adds
`pytest` and `pytest-cov`. The separate `[dependency-groups].dev` block adds
Jupyter / ipympl / vispy for notebook-driven exploration; install those with
`uv sync` if you want the notebook stack.

`uv` materializes the venv at `.venv/` in the repo root. Activate it with
`source .venv/bin/activate`, or prefix every command with `uv run`. The
`render-knot` and `render-part` console scripts declared in
[pyproject.toml](../pyproject.toml#L42) resolve once the editable install is in
place.

### macOS VTK dylib gotcha

`cadquery` pulls in `cadquery-vtk`, but transitively the PyPI `vtk` wheel also
ships its own `libvtkRenderingUI.dylib`. On macOS the duplicate Objective-C
class registration produces noisy warnings and occasionally crashes the
viewer. Run [scripts/fix_macos_vtk_dylibs.sh](../scripts/fix_macos_vtk_dylibs.sh)
once after every `uv pip install` that touches `vtk`:

```bash
./scripts/fix_macos_vtk_dylibs.sh
```

The script removes the stray `libvtkRenderingUI.dylib` from `vtkmodules/.dylibs`
and reinstalls `cadquery-vtk` so its own copy stays canonical.

## Repo conventions

These patterns are load-bearing. Match them when you add new code; deviating
will work in isolation but break tooling that walks the tree.

### Knot and part modules expose `build(config)`

Every file under [src/led_knots/knots/](../src/led_knots/knots/) and
[src/led_knots/parts/](../src/led_knots/parts/) exposes a `build(config: Config)
-> None` entry point. The CLI loads a YAML config (with `knot_type` or
`part_type`), merges it with repo defaults, and dispatches via the file-based
registry in `knots/registry.py` or `parts/registry.py`.

- Importing a knot module does **not** run geometry — only `build(config)` does.
- The canonical invocation is `render-knot knot_configs/my_knot.yaml` or
  `render-part part_configs/my_part.yaml`.
- Adding a new model = add `<name>.py` with `build(config)` + set
  `knot_type` / `part_type` in YAML. No `pyproject.toml` entry per model.

### `TubeModel`s register via side-effects in `tube_models/__init__.py`

The registry lives in
[src/led_knots/core/tube_models/__init__.py](../src/led_knots/core/tube_models/__init__.py).
Module import populates a `_REGISTRY: Dict[str, TubeModel]`. New tube
implementations must add an entry there (either by appending to the literal
dict or by calling `register_tube_model(...)`). `get_tube_model(face_type)`
is the only correct lookup path; do not import individual model classes from
callers.

### Config flows through `load_config()`

Use `from led_knots.core.config import load_config` with
`parse_render_args()` and treat the returned object as read-only. Do not call
`yaml.safe_load("config.yaml")` yourself. `load_config()` layers
`config.local.yaml`, the user config file, and CLI overrides on top of
`config.yaml`.

### Use the helpers in `src/led_knots/core/`

If you find yourself reaching for raw splines or twist math, stop and check
[src/led_knots/core/](../src/led_knots/core/) first:

- [path_utils.py](../src/led_knots/core/path_utils.py#L476) —
  `build_ribbon_aux_spine(path, ...)` produces the auxiliary spine that
  keeps the cross-section's orientation consistent along the sweep and
  enforces the configured `min_90_degree_twist_distance`.
- [pyknot_utils.py](../src/led_knots/core/pyknot_utils.py#L10) —
  `scale_pyknot_points(points, ...)` rescales raw `pyknotid` output into
  the configured `output_bounds`.
- [utils.py](../src/led_knots/core/utils.py#L244) — `draw_part(path, config,
  aux=..., **face_kwargs)` is the canonical entry point for "turn this path
  into a solid". It dispatches into the tube-model registry and applies the
  cache layer.

Rolling new spline/twist logic in a knot file is the most common way to ship
geometry that looks fine on screen but fails at sweep time on a different
`face_type`. Don't.

### Cache layout

`cache/preview/` is owned by `core/cache_utils.py` and the preview pipeline.
Treat it as opaque output: do not read individual files, do not write into
it from knot or tube code, and do not commit it (it is gitignored at the
repo root). If you need a per-run scratch directory, create one under
`/tmp` and clean it yourself.

## Where to add new code

| You want to add...               | Put the code in...                                                                          | Then update...                                                                                                |
| -------------------------------- | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| A new knot                       | [src/led_knots/knots/<name>.py](../src/led_knots/knots/) with `build(config)`              | A config YAML with `knot_type: <name>` under `knot_configs/`                                                  |
| A new cross-section face         | [src/led_knots/core/led_circle.py](../src/led_knots/core/led_circle.py)                     | [src/led_knots/core/tube_models/__init__.py](../src/led_knots/core/tube_models/__init__.py#L17) registry      |
| A new `TubeModel`                | [src/led_knots/core/tube_models/<your>.py](../src/led_knots/core/tube_models/)              | [src/led_knots/core/tube_models/__init__.py](../src/led_knots/core/tube_models/__init__.py#L17) registry      |
| A new auxiliary part             | [src/led_knots/parts/<name>.py](../src/led_knots/parts/) with `build(config)`               | A config YAML with `part_type: <name>` under `part_configs/`                                                  |
| A new optimization heuristic     | [src/led_knots/optimize/](../src/led_knots/optimize/)                                       | [src/led_knots/optimize/settings.py](../src/led_knots/optimize/settings.py) if it needs a knob                |

Match the file naming used by neighbors: snake_case modules, one knot or one
tube model per file.

## Do's and don'ts for adding new paths

This is the checklist you actually want pinned above your monitor when you
start a new knot.

**DO**

- **Honor `min_90_degree_twist_distance`** by always running your path
  through `build_ribbon_aux_spine` in
  [path_utils.py:476](../src/led_knots/core/path_utils.py#L476). The aux
  spine controls cross-section orientation along the sweep; building your
  own ribbon will not enforce the twist-rate guard.
- **Scale your points into `output_bounds`** with `scale_pyknot_points` in
  [pyknot_utils.py:10](../src/led_knots/core/pyknot_utils.py#L10), or
  otherwise clamp to the configured bound before sweeping. The bed-fit
  optimizer assumes the model already respects `output_bounds`.
- **Call `draw_part(path, config, aux=aux_spine, rotation_z=initial_rotation)`**
  ([utils.py:244](../src/led_knots/core/utils.py#L244)) as your final step.
  It picks up the correct tube model, applies caching, and exposes the
  result to the render pipeline. The `rotation_z=initial_rotation`
  convention is how knots align their seam to the bed.
- **Drop the duplicate trailing point on closed paths before `spline()`**.
  `pyknotid` and a few of the analytical generators emit `points[0] ==
  points[-1]` so the path closes; CadQuery's `spline()` will treat the
  duplicate as a zero-length segment and either error or produce a
  degenerate face. Slice with `points[:-1]` (or check and trim) before
  handing the list to `spline()`.

**DON'T**

- **Don't hardcode tube radius or wall thickness.** Pull them from
  `config.tube_settings`. If a knot reads its own magic number you get a
  model that ignores `config.local.yaml` and silently desynchronises from
  the rest of the suite.
- **Don't mutate the `Config` object** returned by `load_config()`.
  Treat it as frozen. If you need a one-off variant, copy the field into a
  local before mutating.
- **Don't bypass `build_ribbon_aux_spine`.** If it raises `ValueError`
  about an unachievable twist rate, that is your early-warning that the
  centerline is physically infeasible to sweep at the configured face. The
  fix is to relax the centerline (more arc length, gentler bends) or to
  loosen `min_90_degree_twist_distance` — not to skip the check.
- **Don't pair the LED-circle face with a closed spline directly.** The
  `led_circle` face is asymmetric and the duplicate-face overlap at the
  seam breaks the sweep. Either trim the closure or use the
  `led_circle_tube` variant that handles the join.

## Testing

`pytest` is the test runner. The configuration lives in
[pyproject.toml](../pyproject.toml#L66):

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_functions = ["test_*"]
```

The four test files under [tests/](../tests/) cover the optimization
package:

| File                                                                                            | Targets                                                                                       |
| ----------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| [test_optimize_orient.py](../tests/test_optimize_orient.py)                                     | `optimize/orient.py` — bed orientation search and support-volume scoring                      |
| [test_optimize_analysis.py](../tests/test_optimize_analysis.py)                                 | `optimize/analysis.py` — overhangs, trapped-cavity detection (gated on `manifold3d`)          |
| [test_optimize_face_tagging.py](../tests/test_optimize_face_tagging.py)                         | `optimize/face_tagging.py` — labeling overhang / down-facing / cavity faces for the report    |
| [test_optimize_drain_holes.py](../tests/test_optimize_drain_holes.py)                           | `optimize/drain_holes.py` — automatic drain-hole drilling (gated on `manifold3d`)             |

Run the whole suite:

```bash
uv run pytest -q
```

Run a single test:

```bash
uv run pytest tests/test_optimize_orient.py::test_name -q
```

The drain-hole and cavity-detection tests need `manifold3d` installed. It is
in the core dependency list in [pyproject.toml](../pyproject.toml#L32), but
if you've stripped it out (or are running on a platform where the wheel
won't build) those tests will skip or fail at import. Install it with
`uv pip install manifold3d` to restore coverage.

**There are currently no tests for the knot modules themselves.** Geometry
correctness is validated visually via the preview pipeline (see below) and
by exporting STL/STEP and loading the result in a slicer. Treat preview
generation as part of your PR review.

## Generating previews

The repo ships a batch preview script. Run:

```bash
uv run python scripts/generate_previews.py
```

It walks the list of knot module names baked into
[scripts/generate_previews.py](../scripts/generate_previews.py#L21), invokes
each one with `--preview`, and writes the resulting PNGs (plus a combined
GIF) into [assets/](../assets/). Use those PNGs for README / GitHub project
visuals. If you add a new knot, append its module name to the `KNOTS` list
in that script so it picks up the preview.

## Git hygiene

The repo's [.gitignore](../.gitignore) already covers most of this, but for
the record, do not commit:

- `cache/` — owned by the cache layer; large, machine-specific, gitignored
  at the repo root.
- Generated `*.stl`, `*.obj`, `*.png`, `*.step`, `*.3mf` files **outside
  `assets/`**. The `export/` and `exports/` directories are gitignored and
  exist for ad-hoc exports.
- `config.local.yaml` — per-developer override, explicitly gitignored.
- The `.venv/` directory and the usual Python build artefacts (already
  covered by the upstream Python gitignore template).

Commit *only* curated previews into `assets/`; do not dump the full output
of `generate_previews.py` if it includes experimental knots.

## Working with optional dependencies

Three dependencies are heavier or platform-finicky enough to deserve
explicit handling:

- **`manifold3d`** ([pyproject.toml:32](../pyproject.toml#L32)) — used for
  the boolean engine behind trapped-cavity detection and drain-hole
  drilling in [src/led_knots/optimize/](../src/led_knots/optimize/). The
  code in `optimize/analysis.py` (~line 210) wraps the import in a
  `try/except ImportError` and degrades to a one-line "install manifold3d
  to enable" note in the report instead of crashing. Match that pattern if
  you add another optimizer that needs a boolean engine.
- **`cadquery-web-viewer`** ([pyproject.toml:31](../pyproject.toml#L31),
  sourced editable from a sibling repo via
  [`[tool.uv.sources]`](../pyproject.toml#L61)) — powers `--server` and
  `upload-knot` remote uploads declared in [utils.py:56](../src/led_knots/core/utils.py#L56).
- **`pyknotid`** ([pyproject.toml:27](../pyproject.toml#L27), sourced from
  GitHub via `[tool.uv.sources]`) — the source of truth for mathematical
  knot parameterizations (used by `trefoil`, `figure_8`, `k4_1`, `k8_21`,
  `stevedore`, and a few others). Knots that don't need it (e.g. `rod`,
  `ring`, `helix`) should not import it. If `pyknotid` fails to install,
  the analytical knots continue to work.

Graceful degradation means: catch `ImportError` at the point of use, surface
a one-line "install X to enable Y" message, and let the rest of the
pipeline run. Don't gate import of unrelated code on optional packages.

## Adding a new dependency

1. Add the package to the appropriate list in [pyproject.toml](../pyproject.toml):
   - Runtime dep → `[project].dependencies`
   - Dev-only (tests, lint, notebooks) → `[project.optional-dependencies].dev`
     or `[dependency-groups].dev`
2. If the package needs a non-PyPI source (git fork, local editable),
   add the entry to [`[tool.uv.sources]`](../pyproject.toml#L61). Existing
   examples: `pyknotid` from a GitHub fork, `py-lib3mf` from a tagged
   GitHub release, `cadquery-web-viewer` from a sibling working copy.
3. Re-resolve and re-install:

   ```bash
   uv pip install -e ".[dev]"
   ```

   Plain `pip install -e .` works too, but `uv` honors
   `[tool.uv.sources]` directly — `pip` will silently fall back to the
   PyPI name.
4. Document any platform caveats. The current ones are macOS-specific:
   re-run [scripts/fix_macos_vtk_dylibs.sh](../scripts/fix_macos_vtk_dylibs.sh)
   if your new dependency transitively brings in another copy of `vtk`.
5. If the dependency is optional, follow the graceful-degradation pattern
   above.

## When you change shared core code

Anything under [src/led_knots/core/](../src/led_knots/core/),
[src/led_knots/core/tube_models/](../src/led_knots/core/tube_models/), or
[src/led_knots/optimize/](../src/led_knots/optimize/) is shared by every
knot and every printable-output path. Before opening a PR:

1. Run the full test suite:

   ```bash
   uv run pytest -q
   ```

2. Headlessly export every bundled knot. The minimal smoke loop (the `python
   -m` form is preferred — see the console-script note above):

   ```bash
   for k in rod twisted_rod quarter_turn ring jog_bend jog_bend_3d \
            helix figure_8 trefoil k4_1 k8_21 stevedore; do
     uv run python -m "led_knots.knots.${k}" --export "/tmp/${k}.stl" \
       || echo "FAIL: $k"
   done
   ```

   The `--export` flag is documented in
   [utils.py:46](../src/led_knots/core/utils.py#L46).
3. Regenerate previews and eyeball them:

   ```bash
   uv run python scripts/generate_previews.py
   ```

4. If you touched `optimize/`, run at least one knot through the
   bed-fit / orient stage end-to-end (not just the unit tests). The unit
   tests use synthetic geometry; real knots are what catch boolean engine
   regressions.

A change to shared core that breaks one knot will usually break all of
them, so this smoke loop is fast and high-value. Don't skip it.
