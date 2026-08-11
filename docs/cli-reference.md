# CLI reference

LED Knots exposes three console commands declared in
[pyproject.toml](../pyproject.toml) under `[project.scripts]`:

| Command | Entry point | Purpose |
| --- | --- | --- |
| `render-knot` | `led_knots.cli:main_knot` | Build and export a knot from a config file |
| `render-part` | `led_knots.cli:main_part` | Build and export an accessory part from a config file |
| `upload-knot` | `led_knots.cli:main_upload_knot` | Upload an existing render bundle GLB to cadquery-web-viewer |

Both render commands share the same flag surface, parsed by `parse_render_args()` in
[src/led_knots/core/utils.py](../src/led_knots/core/utils.py).

## Invocation

```bash
render-knot knot_configs/test_short_rod_led_tube.yaml
render-part part_configs/hang_clamp.yaml
```

Each config file is merged on top of `config.yaml` and optional `config.local.yaml`.
The config must declare which model to build:

```yaml
# knot config
knot_type: trefoil   # matches src/led_knots/knots/trefoil.py

# part config
part_type: hang_clamp   # matches src/led_knots/parts/hang_clamp.py
```

Knot and part modules are discovered by filename — no per-model console scripts
or manual registry entries are required. Adding `my_knot.py` with a `build(config)`
function and setting `knot_type: my_knot` in YAML is sufficient.

## Knot types

All `*.py` modules under [src/led_knots/knots/](../src/led_knots/knots/) except
`__init__.py` and `registry.py` are valid `knot_type` values:

| `knot_type` | Module | Description |
| --- | --- | --- |
| `rod` | [rod.py](../src/led_knots/knots/rod.py) | Straight vertical pipe |
| `ring` | [ring.py](../src/led_knots/knots/ring.py) | Closed circular ring |
| `helix` | [helix.py](../src/led_knots/knots/helix.py) | Cylindrical helix |
| `sine_wave` | [sine_wave.py](../src/led_knots/knots/sine_wave.py) | Sine-wave path |
| `jog_bend` | [jog_bend.py](../src/led_knots/knots/jog_bend.py) | Planar jog-bend path |
| `jog_bend_3d` | [jog_bend_3d.py](../src/led_knots/knots/jog_bend_3d.py) | 3D jog-bend path |
| `quarter_turn` | [quarter_turn.py](../src/led_knots/knots/quarter_turn.py) | Single quarter-turn elbow |
| `twisted_rod` | [twisted_rod.py](../src/led_knots/knots/twisted_rod.py) | Vertical rod with axial twist |
| `twist_ring` | [twist_ring.py](../src/led_knots/knots/twist_ring.py) | (5,10) torus-knot ring |

The 15 knots proper — `ring`, `k2_1`, `trefoil`, `k4_1`, `k5_2`, `k6_3`, `k7_1`,
`k8_21`, `k9_2`, `k10_7`, `k11a6`, `k12a6`, `k13a6`, `k14n2`, `k15n3` — each
have a config under `knot_configs/`; see the
[code map](code-map.md#the-15-knot-set). Two more sit outside that set:
`stevedore` (6_1) and `k9_35`.

## Part types

All `*.py` modules under [src/led_knots/parts/](../src/led_knots/parts/) except
`__init__.py` and `registry.py` are valid `part_type` values:

| `part_type` | Module | Description |
| --- | --- | --- |
| `hang_clamp` | [hang_clamp.py](../src/led_knots/parts/hang_clamp.py) | Two-part tube clamp |
| `planet_spacer` | [planet_spacer.py](../src/led_knots/parts/planet_spacer.py) | Thick washer-like spacer |

## Positional `config` argument

- **Type:** path string (required).
- **Effect:** YAML file merged on top of `config.yaml` and `config.local.yaml`.
  Relative paths resolve against the repository root.
- **Precedence:** Wins over both YAML files; individual flags such as
  `--optimize` still override matching keys afterward.
- **Errors:** Raises `FileNotFoundError` if the path does not exist.
- **`render-knot`:** Config must include `knot_type`.
- **`render-part`:** Config must include `part_type`.

```bash
render-knot knot_configs/test_short_rod_led_tube.yaml
render-part part_configs/planet_spacer.yaml
```

## upload-knot

Upload a previously rendered bundle to cadquery-web-viewer without rebuilding geometry.

```bash
upload-knot renders/rod_20260612-152817
upload-knot renders/rod_20260612-152817/rod_20260612-152817.yaml
upload-knot renders/rod_20260612-152817 -v
```

### Positional `PATH` argument

- **Type:** path string (required).
- **Effect:** Render bundle directory or its `{stem}.yaml` config snapshot. The bundle
  must contain `{stem}.glb` where `{stem}` matches the directory name.
- **Viewer settings:** Always taken from `server.viewer` in the bundle YAML snapshot
  (merged with `config.yaml` / `config.local.yaml`). When the bundle YAML is missing,
  repo defaults apply. No `--server` flag on this command.
- **Prerequisite:** Start cadquery-web-viewer in another terminal first:

```bash
cadquery-web-viewer --host localhost --port 32323
```

### `-v` / `--verbose`

- **Effect:** Enable DEBUG-level logging.

See [Configuration](configuration.md) for layering rules and worked examples.

## Flags

### `--name NAME`

- **Effect:** Overrides the run name used for the render bundle folder and
  `{name}` / `{run_name}` filename templates.

### `--renders-dir DIR`

- **Effect:** Parent directory for render bundles (overrides `rendering.output_dir`).

### `--disable-export FORMATS`

- **Type:** comma-separated list (e.g. `glb,stats,obj`).
- **Effect:** Disables matching export jobs from `rendering.exports`.

### `--server`

- **Effect:** POST the model to a running remote cadquery-web-viewer after
  writing the render bundle. Connection settings come from `server.viewer` in
  config.

```bash
render-knot knot_configs/test_short_rod_led_tube.yaml --server
```

### `--optimize` / `--no-optimize`

- **Effect:** Enable or disable the SLA print-optimization stage (overrides
  `print_optimization.enabled` in config).

```bash
render-knot knot_configs/test_short_rod_led_tube.yaml --optimize
render-knot knot_configs/test_short_rod_led_tube.yaml --no-optimize
```

### `--auto-orient`

- **Effect:** Apply the top-ranked SLA build orientation to exported geometry.
  Implies `--optimize`.

```bash
render-knot knot_configs/test_short_rod_led_tube.yaml --auto-orient
```

### `--optimize-report-dir DIR`

- **Effect:** Write optimizer diagnostic PNGs to `DIR`. Implies `--optimize`.

```bash
render-knot knot_configs/test_short_rod_led_tube.yaml --optimize-report-dir out/opt_diag/
```

### `-v` / `--verbose`

- **Effect:** Enable DEBUG-level logging.

```bash
render-knot knot_configs/test_short_rod_led_tube.yaml -v
```

## Environment variables

`load_config()` calls `ServerSettings.apply_to_env()` before the render pipeline
imports `cadquery_web_viewer`, setting `CADQUERY_WEB_VIEWER_*` from the merged
`server:` block when viewer styling keys are present.

See [Rendering and preview](rendering-and-preview.md) for viewer setup.
