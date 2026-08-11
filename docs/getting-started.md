# Getting started

This guide walks a developer from `git clone` to a first STL export, then on to the browser preview and a config override. It assumes you are comfortable with Python virtual environments and have CadQuery prerequisites available on your platform.

For deeper material once you are up and running, jump to:

- [Configuration reference](configuration.md) — every key in `config.yaml`.
- [CLI reference](cli-reference.md) — every flag accepted by the knot scripts.
- [Cookbook: paths](paths.md) — adding a new knot path.
- [Cookbook: tube models](tube-models.md) — adding a new cross-section.
- [Developer guide](developer-guide.md) — repo layout, tests, contribution flow.

## Install

The project targets **Python 3.12 only**. The upper bound is pinned by `cadquery-web-viewer`; see `requires-python = ">=3.12,<3.13"` in [pyproject.toml](../pyproject.toml#L6). A 3.13 interpreter will fail to resolve the lockfile.

### Using uv (recommended)

[uv](https://github.com/astral-sh/uv) is the supported workflow because the lockfile pulls a handful of git-sourced dependencies (`pyknotid`, `py-lib3mf`) and an editable local checkout of `cadquery-web-viewer` (see `[tool.uv.sources]` in [pyproject.toml](../pyproject.toml#L61)). uv resolves these automatically:

```bash
git clone <repo-url> led_knots
cd led_knots
uv sync
```

`uv sync` creates `.venv/` and installs the project plus dev tools. Drop into the venv with `source .venv/bin/activate`, or prefix any command with `uv run` (e.g. `uv run render-knot knot_configs/test_short_rod_led_tube.yaml`).


### Using pip

If you cannot use uv, an editable install works for the runtime dependencies:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```

You will need to install the git-sourced dependencies (`pyknotid`, `py-lib3mf`) and `cadquery-web-viewer` by hand — pip does not read `[tool.uv.sources]`. See the URLs in [pyproject.toml](../pyproject.toml#L61) for the canonical sources.

### Optional dependencies

`manifold3d` is listed as a hard dependency in [pyproject.toml](../pyproject.toml#L32) and is therefore always installed by uv/pip. However, the features it unlocks are opt-in:

- **Trapped-cavity detection** in the SLA print optimizer.
- **Auto-drilled drain/vent holes** (`print_optimization.drain_holes.enabled` in [config.yaml](../config.yaml#L172)).

If you build `manifold3d` from source on an exotic platform and it fails, only those features are affected; the rest of the pipeline still works.

## Verify the install

A minimum smoke test confirms the import path and configuration loader:

```bash
python -c "import led_knots; print(led_knots.__file__)"
```

The first real exercise is to run a straight rod and inspect the render bundle:

```bash
render-knot knot_configs/test_short_rod_led_tube.yaml
```

On success you will see CadQuery progress logs and a folder under `renders/`
containing STL, preview PNG, GLB, config YAML, and stats CSV. See
[Mesh export](mesh-export.md) for all supported export formats.

## Pick a knot

Set `knot_type` in your config file to match a module stem under [src/led_knots/knots/](../src/led_knots/knots/). Modules are discovered by filename — no console script per knot.

| `knot_type` | Module | One-liner |
|---|---|---|
| `rod` | [rod.py](../src/led_knots/knots/rod.py) | Straight vertical pipe — the simplest path. |
| `ring` | [ring.py](../src/led_knots/knots/ring.py) | Single closed circular loop. |
| `helix` | [helix.py](../src/led_knots/knots/helix.py) | Constant-pitch helical spiral. |
| `sine_wave` | [sine_wave.py](../src/led_knots/knots/sine_wave.py) | Sinusoidal oscillation along an axis. |
| `trefoil` | [trefoil.py](../src/led_knots/knots/trefoil.py) | Mathematical trefoil knot (3_1). |
| `k4_1` | [k4_1.py](../src/led_knots/knots/k4_1.py) | Figure-eight knot (4_1). |
| `jog_bend` | [jog_bend.py](../src/led_knots/knots/jog_bend.py) | Planar S-shaped jog between two parallel lines. |
| `jog_bend_3d` | [jog_bend_3d.py](../src/led_knots/knots/jog_bend_3d.py) | Same jog with explicit 3D orientation control. |
| `quarter_turn` | [quarter_turn.py](../src/led_knots/knots/quarter_turn.py) | A single 90-degree corner. |
| `twisted_rod` | [twisted_rod.py](../src/led_knots/knots/twisted_rod.py) | Straight rod with a 90-degree axial twist. |

Those are the shapes to start with. The project's actual subject is a set of 15
knots, from the unknot up to 15 crossings, one config each — see
[knotbook.ipynb](../knotbook.ipynb) for previews and the
[code map](code-map.md#the-15-knot-set) for the slot-by-slot table.

Every other module under [src/led_knots/knots/](../src/led_knots/knots/) works the same way — set `knot_type` to the filename stem.

To add a new path, see [Cookbook: paths](paths.md).

## Run a knot

The CLI is identical across scripts. The three modes you will use day-to-day:

### 1. Render bundle (default)

```bash
render-knot knot_configs/my_trefoil.yaml   # knot_type: trefoil in the YAML
```

Writes `renders/{run-name}_{timestamp}/` with enabled jobs from `rendering.exports`
in [config.yaml](../config.yaml) (STL, preview PNG, GLB, config YAML, stats CSV
by default). Disable formats with `--disable-export glb,stats` or edit the YAML.
See [CLI reference](cli-reference.md) and [Mesh export](mesh-export.md).

### 2. Browser preview against a long-running viewer

Start cadquery-web-viewer in one terminal ([config.yaml](../config.yaml) `server.viewer.host` / `port`):

```bash
cadquery-web-viewer --host localhost --port 32323
```

In another terminal:

```bash
render-knot knot_configs/my_trefoil.yaml --server
```

The CLI uploads the model and exits immediately; the viewer holds the browser tab. You can also upload an existing bundle with `upload-knot renders/my_bundle/`.

### 3. Preview PNG in the render bundle

Preview images are written automatically into the render bundle. Camera and
lighting are configured on the `preview` export job under `rendering.exports`
in [config.yaml](../config.yaml).

## Tune dimensions

Project-wide defaults live in [config.yaml](../config.yaml). To customise without touching the tracked file, create a `config.local.yaml` in the repo root — its keys are deep-merged on top of the defaults at load time. To switch between named, git-tracked variants, pass the config file as the positional argument to `render-knot` or `render-part` (e.g. `render-knot configs/permutations/trefoil-tight.yaml`); the file wins over both YAML defaults.

A minimal override that resizes the build envelope and the tube outer diameter:

```yaml
# config.local.yaml
output_bounds:
  width: 150
  length: 150
  height: 200

face_type: led_circle

face_settings:
  led_circle:
    outer_diameter: 35
    wall_thickness: 1.5
```

`output_bounds` controls the bounding box the path is scaled into (the shipped default matches the Elegoo Saturn 4 Ultra 16k build volume — 200 × 110 × 200 mm; see [config.yaml:14](../config.yaml#L14)). `face_type` selects which entry under `face_settings` is active; the default is `led_circle_tube`. Every face type and its options are catalogued in [Configuration reference](configuration.md).

## Prepare for print

For SLA / resin parts the project has a print-optimization stage that scores build orientations, flags overhangs/islands/cavities, and can mutate the exported geometry:

- `--optimize` runs the analyzer and prints findings without changing geometry.
- `--auto-orient` applies the top-ranked orientation (implies `--optimize`).
- `--optimize-report-dir DIR` writes annotated PNG diagnostics.
- Tune defaults under `print_optimization` in [config.yaml](../config.yaml#L158): `overhang_threshold_deg` (35 for SLA), `orientation.top_n_candidates`, `orientation.connector_bonus_weight` (0.7), and the `drain_holes` block.

For knots larger than the build plate, enable the segmenter:

- Set `max_print_bounds.enabled: true` in [config.yaml](../config.yaml#L89) and the knot is split into printable segments joined by twin-pin or dovetail joints (`max_print_bounds.joint.style`).
- Pick `layout: path` to leave segments along the sweep, or `layout: print_bed` to lay them flat on the build plate.

Both stages are covered in depth in the [Print optimization](print-optimization.md) and [Print segmentation](print-segmentation.md).

## Next steps

- Extend the library: [Cookbook: paths](paths.md) and [Cookbook: tube models](tube-models.md).
- Understand the architecture and contribute: [Developer guide](developer-guide.md).
- Full CLI surface: [CLI reference](cli-reference.md).
- Every config key with defaults and effects: [Configuration reference](configuration.md).
