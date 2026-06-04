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

`uv sync` creates `.venv/` and installs the project plus dev tools. Drop into the venv with `source .venv/bin/activate`, or prefix any command with `uv run` (e.g. `uv run led-knots-rod --export /tmp/rod.stl`).

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

The first real exercise is to export a straight rod to disk:

```bash
python -m led_knots.knots.rod --export /tmp/rod.stl
# or: led-knots-rod --export /tmp/rod.stl
```

On success you will see CadQuery progress logs and a `/tmp/rod.stl` file you
can open in any slicer. The two invocation forms run the same code; the
`python -m` form is currently the more reliable one because the knot modules
do not define a `main()` symbol, which makes the `led-knots-*` console-script
wrappers raise an `ImportError` at the very end of the run even though the
`--export` file is produced correctly. See the
[CLI reference](cli-reference.md#equivalent-module-invocation) for details.

## Pick a knot

Each knot path ships as a standalone module under [src/led_knots/knots/](../src/led_knots/knots/) and is also exposed as a console script (see `[project.scripts]` in [pyproject.toml](../pyproject.toml#L42)). All scripts share the same CLI surface.

| Console script | Module | One-liner |
|---|---|---|
| `led-knots-rod` | [rod.py](../src/led_knots/knots/rod.py) | Straight vertical pipe — the simplest path. |
| `led-knots-ring` | [ring.py](../src/led_knots/knots/ring.py) | Single closed circular loop. |
| `led-knots-helix` | [helix.py](../src/led_knots/knots/helix.py) | Constant-pitch helical spiral. |
| `led-knots-sine-wave` | [sine_wave.py](../src/led_knots/knots/sine_wave.py) | Sinusoidal oscillation along an axis. |
| `led-knots-trefoil` | [trefoil.py](../src/led_knots/knots/trefoil.py) | Mathematical trefoil knot (3_1). |
| `led-knots-figure-8` | [figure_8.py](../src/led_knots/knots/figure_8.py) | Figure-8 / 4_1 knot. |
| `led-knots-jog-bend` | [jog_bend.py](../src/led_knots/knots/jog_bend.py) | Planar S-shaped jog between two parallel lines. |
| `led-knots-jog-bend-3d` | [jog_bend_3d.py](../src/led_knots/knots/jog_bend_3d.py) | Same jog with explicit 3D orientation control. |
| `led-knots-quarter-turn` | [quarter_turn.py](../src/led_knots/knots/quarter_turn.py) | A single 90-degree corner. |
| `led-knots-twisted-rod` | [twisted_rod.py](../src/led_knots/knots/twisted_rod.py) | Straight rod with a 90-degree axial twist. |

Two extra modules — [k4_1.py](../src/led_knots/knots/k4_1.py), [k8_21.py](../src/led_knots/knots/k8_21.py), and [stevedore.py](../src/led_knots/knots/stevedore.py) — live alongside but are not wired to console scripts; run them with `python -m led_knots.knots.<name>`.

To add a new path, see [Cookbook: paths](paths.md).

## Run a knot

The CLI is identical across scripts. The three modes you will use day-to-day:

### 1. Headless STL export

```bash
led-knots-trefoil --export trefoil.stl
```

`--export` accepts `.stl`, `.step`, `.stp`, `.3mf`, `.glb`, and `.gltf`. With no viewer flag set, the process builds the geometry, writes the file, and exits. See [CLI reference](cli-reference.md) for the full export-format matrix.

### 2. Browser preview against a long-running viewer

The default `server.viewer.mode` in [config.yaml](../config.yaml#L193) is `remote`, meaning each knot run POSTs the model to a separately-launched `cadquery-web-viewer` instance. In one terminal:

```bash
cadquery-web-viewer --host localhost --port 32323
```

In another terminal:

```bash
led-knots-trefoil --server
```

The CLI uploads the model and exits immediately; the viewer holds the browser tab. You can override the mode per-run with `--viewer remote` (same effect) or switch to in-process mode:

```bash
led-knots-trefoil --viewer embedded
```

`embedded` starts a Flask thread inside the CLI process and opens a browser tab; `embedded-block` is the "wait until the browser disconnects" variant.

### 3. PNG preview to a file

Skip the browser entirely and ask for a rendered image:

```bash
led-knots-trefoil --preview /tmp/trefoil.png
```

The image dimensions, camera, lighting, and colors are controlled by the `preview` block in [config.yaml](../config.yaml#L235). The preview pipeline also writes an intermediate STL into `preview.stl_cache` (default `cache/preview`).

## Tune dimensions

Project-wide defaults live in [config.yaml](../config.yaml). To customise without touching the tracked file, create a `config.local.yaml` in the repo root — its keys are deep-merged on top of the defaults at load time.

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
