# Configuration

All runtime knobs for the LED-knots toolchain live in YAML. The loader is a
small, deliberate layer: a committed defaults file, an optional gitignored
override file, deep merge between them, and one entry point that every script
and notebook calls. This page is the canonical reference for every section,
every key, and every constraint enforced when the config is parsed.

## Files and overrides

Two files at the repository root drive configuration:

| File | Purpose | Tracked in git |
| --- | --- | --- |
| [config.yaml](../config.yaml) | Committed defaults. The source of truth for what every key means and what its default value is. | Yes |
| [config.local.yaml](../config.local.yaml) | Personal/local overrides. Set only the keys you want to change; the rest are inherited from `config.yaml`. | No (in [.gitignore](../.gitignore)) |

`get_config()` in [src/led_knots/core/config.py](../src/led_knots/core/config.py)
is the single entry point. Every knot script, every CLI, and the notebook all
call it; there is no other supported way to read configuration. It returns a
cached `Config` singleton, parses CLI args (see
[CLI reference](cli-reference.md)), and as a side effect can set
`CADQUERY_WEB_VIEWER_*` environment variables before the viewer is imported.

```python
from led_knots.core.config import get_config

cfg = get_config(description="Trefoil knot", name="trefoil")
print(cfg.tube_settings.outer_radius)
print(cfg.output_bounds.width, cfg.output_bounds.length, cfg.output_bounds.height)
```

The project root is located by walking three parents up from
[config.py](../src/led_knots/core/config.py) — config files are always read
from the repo root, regardless of where you launch a script from.

## Loading rules

Defined by [`Config.__init__`](../src/led_knots/core/config.py#L491) and
[`Config._merge_dicts`](../src/led_knots/core/config.py#L627):

1. **Precedence (lowest to highest):**
   1. Hard-coded defaults inside each settings class (e.g. `OutputBounds`
      defaults to 100 mm if `output_bounds` is omitted).
   2. Values in `config.yaml`.
   3. Values in `config.local.yaml` (if the file exists).
   4. CLI arguments (only a small subset, see below).
2. **Deep merge.** Dictionaries are merged recursively. If a key exists in
   both files and both values are dicts, the dicts are merged key-by-key. If a
   value is a scalar, list, or one is non-dict, the override replaces the base
   wholesale. Lists are **not** appended — they are replaced.
3. **Missing files.** `config.yaml` is mandatory; if it is missing,
   `open()` raises `FileNotFoundError`. `config.local.yaml` is optional —
   absence is silently ignored. An empty YAML file is treated as `{}`.
4. **Invalid YAML.** `yaml.safe_load` raises `yaml.YAMLError`. The loader
   does not catch it; the script crashes with the parser's line/column.
5. **Validation.** Each settings class validates eagerly in its constructor
   and raises `ValueError` with the dotted path of the bad key (for example
   `clamp.length_mm must be > 0 (got -1.0)`).
6. **CLI overrides** (parsed by
   [`parse_args`](../src/led_knots/core/utils.py)) only touch a few fields:
   `export.filepath` (from `--export`), `mesh.filepath` (from `--output-mesh`),
   `print_optimization.enabled` (from `--optimize` / `--no-optimize` /
   `--auto-orient`), `print_optimization.orientation.auto_apply` (from
   `--auto-orient`), and viewer mode (from `--viewer` / `--server`).

## Section-by-section reference

### `output_bounds`

Target bounding box used to scale the knot path. Defaults match the Elegoo
Saturn 4 Ultra 16k build volume.

```yaml
output_bounds:
  width: 200    # mm
  length: 110   # mm
  height: 200   # mm
```

| Key | Type | Default | Units | Description |
| --- | --- | --- | --- | --- |
| `output_bounds.width` | float | 100.0 | mm | X-axis extent of the knot's scaled bounding box. |
| `output_bounds.length` | float | 100.0 | mm | Y-axis extent. |
| `output_bounds.height` | float | 100.0 | mm | Z-axis extent. |

Hard-coded defaults are 100 mm per axis when the whole section is missing.
The committed YAML overrides those to the Saturn 4 build volume.

### `face_type`

Selects which entry of `face_settings` is resolved into `cfg.tube_settings`.

```yaml
face_type: led_circle_tube
```

| Key | Type | Default | Units | Description |
| --- | --- | --- | --- | --- |
| `face_type` | string enum | `led_circle` | — | One of `led_circle`, `led_circle_tube`, `solid_circle`, `square`, `pyramid_studded`, `braided_rope`. Anything else raises `ValueError`. |

The enum is defined by `VALID_FACE_TYPES` in
[config.py:19](../src/led_knots/core/config.py#L19). See
[Tube models](tube-models.md) for what each face produces.

### `face_settings`

A registry of per-face-type parameter blocks. Only the entry named by
`face_type` is consumed at load time; the rest are stored but ignored. Each
entry may use `inherit_from:` to copy keys from another entry, with
deep merge applied. See [face_settings deep-dive](#face_settings-deep-dive)
below for the full inheritance algorithm.

```yaml
face_settings:
  led_circle:
    outer_diameter: 30
    wall_thickness: 4.0
    rect_inner_x: 4.6
    rect_inner_y: 11.0
    oval_wall_thickness: 0.5
    connector_width: 0.5

  led_circle_tube:
    outer_diameter: 30
    wall_thickness: 4.0
    inner_tube_diameter: 10
    inner_tube_wall_thickness: 0.5
    connector_width: 0.5

  solid_circle:
    inherit_from: led_circle
    outer_diameter: 30

  square:
    outer_width: 30

  pyramid_studded:
    inherit_from: solid_circle
    pyramid_studded:
      base_face_type: solid_circle
      base_size: 2.0
      height: 2.5
      axial_pitch: 4.0
      axial_margin: 4.0
      circumferential_count: 12
      stagger_rows: true
      embed_depth: 0.3

  braided_rope:
    inherit_from: solid_circle
    braided_rope:
      num_strands_per_dir: 25
      float_length: 1
      helix_angle_deg: 30.0
      strand_aspect_ratio: 1.6
      tilt_to_helix_angle: true
      weave_amplitude_factor: 1.05
      pack_factor: 0.7
      samples_per_period: 20
      strand_start: 2.0
      strand_end_offset: 2.0
```

Keys consumed by `TubeSettings`
([config.py:266](../src/led_knots/core/config.py#L266)):

| Key | Type | Default | Units | Description |
| --- | --- | --- | --- | --- |
| `face_settings.<face>.outer_diameter` | float | — | mm | OD for every face except `square`. Required at use time; missing values raise `ValueError` when `outer_radius` is accessed. |
| `face_settings.<face>.outer_width` | float | — | mm | Side length for `square`. Required for square; raises `ValueError` if absent when used. |
| `face_settings.<face>.wall_thickness` | float | 1.0 | mm | Outer ring wall thickness. |
| `face_settings.<face>.oval_wall_thickness` | float | 2.0 | mm | Wall around the central oval cavity (`led_circle` only). |
| `face_settings.<face>.connector_width` | float | 1.0 | mm | Width of the spoke connectors between outer ring and center cavity. |
| `face_settings.<face>.rect_inner_x` | float | 4.0 | mm | Inner rectangular cavity X (`led_circle`). |
| `face_settings.<face>.rect_inner_y` | float | 12.0 | mm | Inner rectangular cavity Y (`led_circle`). |
| `face_settings.<face>.inner_tube_diameter` | float | none | mm | Inner diameter of the central circular tube. Required for `led_circle_tube`. |
| `face_settings.<face>.inner_tube_wall_thickness` | float | none | mm | Wall thickness around the central tube. Required for `led_circle_tube`. |
| `face_settings.<face>.inherit_from` | string | none | — | Name of another `face_settings` entry to inherit from. Stripped before merge. |
| `face_settings.<face>.pyramid_studded.*` | dict | none | — | Pass-through dict consumed by the `pyramid_studded` tube model. See below. |
| `face_settings.<face>.braided_rope.*` | dict | none | — | Pass-through dict consumed by the `braided_rope` tube model. See below. |

The `pyramid_studded` and `braided_rope` sub-blocks are not strongly typed
by the loader — they are stored as plain dicts on
`cfg.tube_settings.pyramid_studded` / `cfg.tube_settings.braided_rope` and
parsed by the model code in
[src/led_knots/core/tube_models/](../src/led_knots/core/tube_models/). See
[Tube models](tube-models.md) for what each key does geometrically. The
defaults shown in the YAML above are the ones the committed config ships.

### `path`

Twist limits used by the swept-tube generator.

```yaml
path:
  min_90_degree_twist_distance: 1   # mm
```

| Key | Type | Default | Units | Description |
| --- | --- | --- | --- | --- |
| `path.min_90_degree_twist_distance` | float | 90.0 (committed YAML overrides to 1) | mm | Minimum arc length over which the face is allowed to rotate 90°. Must be `> 0`; non-positive values raise `ValueError`. |

The loader also accepts the misspelled alias
`min_90_degtree_twist_distance` for historical compatibility
([config.py:175](../src/led_knots/core/config.py#L175)).

### `max_print_bounds`

Optional auto-segmentation into printable parts that fit a build volume. The
joint sub-block describes the registration geometry stamped into each
internal cut.

```yaml
max_print_bounds:
  enabled: false
  width: 200
  length: 110
  height: 200
  clearance_mm: 2.0
  max_segments: 32
  layout: path
  layout_gap_mm: 2
  path_samples: 1001
  joint:
    enabled: true
    style: twin_pin
    clearance_mm: 0.2
    close_loop: false
    pin_diameter_mm: 3.0
    pin_depth_mm: 4.0
    pin_radial_offset_mm: 17.0
    pin_spacing_mm: 7.0
    lap_overlap_mm: 4.0
    lap_step_height_mm: 3.0
    neck_width_mm: 3.0
    base_width_mm: 5.0
    depth_mm: 4.0
    flank_angle_deg: 12.0
```

| Key | Type | Default | Units | Description |
| --- | --- | --- | --- | --- |
| `max_print_bounds.enabled` | bool | `false` | — | Master switch. When `false`, no segmentation runs and the rest of the section is ignored. |
| `max_print_bounds.width` | float | 0.0 | mm | X extent of the printable volume. Must be `> 0` when enabled. |
| `max_print_bounds.length` | float | 0.0 | mm | Y extent. Must be `> 0` when enabled. |
| `max_print_bounds.height` | float | 0.0 | mm | Z extent. Must be `> 0` when enabled. |
| `max_print_bounds.clearance_mm` | float | 0.0 | mm | Subtracted from each side of the usable volume. Must be `>= 0`. The usable volume `(w-2c, l-2c, h-2c)` must remain strictly positive. |
| `max_print_bounds.max_segments` | int | 32 | count | Hard cap on segments produced by the DP segmenter. Must be `>= 1`. |
| `max_print_bounds.layout` | string enum | `path` | — | `path` keeps each segment on the original sweep; `print_bed` lays them flat on the build plate. Anything else raises `ValueError`. |
| `max_print_bounds.layout_gap_mm` | float | 12.0 | mm | `print_bed`: gap along the build-plate row (X). `path`: axial clearance at each internal joint (±half along path tangent). Must be `>= 0`. |
| `max_print_bounds.path_samples` | int | 1001 | count | Wire-sample count used by the segmentation DP. Must be `>= 8`. |

Cross-key constraint: when `enabled: true`, `width - 2*clearance_mm`,
`length - 2*clearance_mm`, and `height - 2*clearance_mm` must all be
strictly positive — otherwise the loader rejects the config.

#### `max_print_bounds.joint`

Registration geometry between adjacent segments.

| Key | Type | Default | Units | Description |
| --- | --- | --- | --- | --- |
| `max_print_bounds.joint.enabled` | bool | `false` | — | Master toggle for adding registration geometry to each internal cut. |
| `max_print_bounds.joint.style` | string enum | `twin_pin` | — | `twin_pin` or `dovetail`. Anything else raises `ValueError`. |
| `max_print_bounds.joint.clearance_mm` | float | 0.2 | mm | Slip-fit clearance between mating features. Must be `>= 0`. |
| `max_print_bounds.joint.close_loop` | bool | `false` | — | Add a final joint at the wrap-around for closed-loop paths. |
| `max_print_bounds.joint.pin_diameter_mm` | float | 3.0 | mm | Twin-pin: pin OD. Must be `> 0`. |
| `max_print_bounds.joint.pin_depth_mm` | float | 4.0 | mm | Twin-pin: pin protrusion length. Must be `> 0`. |
| `max_print_bounds.joint.pin_radial_offset_mm` | float | 17.0 | mm | Twin-pin: distance from centerline to pin axis (clamped to tube OD if too large). Must be `> 0`. |
| `max_print_bounds.joint.pin_spacing_mm` | float | 7.0 | mm | Twin-pin: distance between the two pin centers. Must be `> 0`. |
| `max_print_bounds.joint.lap_overlap_mm` | float | 4.0 | mm | Axial overlap (mm along path tangent) at each internal cut. Both neighbors extend. Must be `>= 0`. |
| `max_print_bounds.joint.lap_step_height_mm` | float | 3.0 | mm | Radial rabbet step on the outer wall at each lap. Must be `> 0`. |
| `max_print_bounds.joint.neck_width_mm` | float | 3.0 | mm | Dovetail: neck width. Must be `> 0` and **strictly less than** `base_width_mm`. |
| `max_print_bounds.joint.base_width_mm` | float | 5.0 | mm | Dovetail: base width. Must be `> 0`. |
| `max_print_bounds.joint.depth_mm` | float | 4.0 | mm | Dovetail/pocket depth. Must be `> 0`. |
| `max_print_bounds.joint.flank_angle_deg` | float | 12.0 | deg | Dovetail flank angle. Must be `> 0`. |

### `tube_gap`

Opens a length of the swept tube to insert wiring and LEDs.

```yaml
tube_gap:
  enabled: false
  gap_length_mm: 25.0
  center_fraction: 0.0
```

| Key | Type | Default | Units | Description |
| --- | --- | --- | --- | --- |
| `tube_gap.enabled` | bool | `false` | — | Master switch for the gap. |
| `tube_gap.gap_length_mm` | float | 0.0 | mm | Arc length removed from the sweep path. Must be `>= 0`. |
| `tube_gap.center_fraction` | float | 0.0 | — | Where to center the gap along the polyline length. `0.0` = centered; range `[-0.5, 0.5]`. Outside that range raises `ValueError`. |

### `clamp`

Two-part snap/glue clamp used to bridge the `tube_gap`. The defaults here
target a resin-printed lap-jointed clamp with registration tongue and
alignment notch. Validation: all positive-floats listed below must be
`> 0`; clearance keys must be `>= 0`.

```yaml
clamp:
  enabled: true
  clearance_diameter_mm: 0.5
  length_mm: 18.0
  wall_thickness_mm: 1.25
  wire_hole_diameter_mm: 4.0
  wire_ring_height_mm: 4.0
  wire_ring_top_thickness_mm: 1.0
  wire_ring_base_thickness_mm: 2.0
  lap_depth_mm: 1.0
  lap_step_height_mm: 1.5
  lap_clearance_mm: 0.2
  adhesive_gap_mm: 0.10
  reg_lip_height_mm: 0.8
  reg_lip_width_mm: 1.2
  reg_clearance_mm: 0.08
  relief_enabled: true
  relief_depth_mm: 0.3
  relief_width_mm: 0.5
  alignment_notch_enabled: true
  alignment_notch_width_mm: 3.0
  alignment_notch_depth_mm: 0.8
  alignment_notch_clearance_mm: 0.1
```

| Key | Type | Default (class) | Units | Description |
| --- | --- | --- | --- | --- |
| `clamp.enabled` | bool | `true` | — | Master switch. |
| `clamp.clearance_diameter_mm` | float | 1.0 | mm | Diameter clearance: clamp ID = tube OD + this. Must be `> 0`. |
| `clamp.length_mm` | float | 18.0 | mm | Axial length of the clamp. Must be `> 0`. |
| `clamp.wall_thickness_mm` | float | 2.5 | mm | Clamp wall thickness outside the tube. Must be `> 0`. |
| `clamp.lap_depth_mm` | float | 1.0 | mm | How far the lap joint steps into the wall. Must be `> 0`. |
| `clamp.lap_step_height_mm` | float | 1.5 | mm | Radial step height for the seam rabbet. Must be `> 0`. |
| `clamp.lap_clearance_mm` | float | 0.2 | mm | Extra clearance between mating lap halves. |
| `clamp.wire_hole_diameter_mm` | float | 4.0 | mm | Through-hole for wires on one half. Must be `> 0`. |
| `clamp.wire_ring_height_mm` | float | 4.0 | mm | Ring height above the surface. Must be `> 0`. |
| `clamp.wire_ring_top_thickness_mm` | float | 1.0 | mm | Ring wall thickness at the top. Must be `> 0`. |
| `clamp.wire_ring_base_thickness_mm` | float | 2.0 | mm | Ring wall thickness at the base (tapers up to top). Must be `> 0`. |
| `clamp.adhesive_gap_mm` | float | 0.10 | mm | Explicit glue-line thickness. Must be `>= 0`. |
| `clamp.reg_lip_height_mm` | float | 0.8 | mm | Registration tongue height (radial). Must be `> 0`. |
| `clamp.reg_lip_width_mm` | float | 1.2 | mm | Registration tongue width (across seam normal). Must be `> 0`. |
| `clamp.reg_clearance_mm` | float | 0.08 | mm | Clearance between tongue and groove. Must be `>= 0`. |
| `clamp.relief_enabled` | bool | `true` | — | Escape-pocket relief features. |
| `clamp.relief_depth_mm` | float | 0.3 | mm | Escape pocket depth (radial). Must be `> 0`. |
| `clamp.relief_width_mm` | float | 0.5 | mm | Escape pocket width (across seam normal). Must be `> 0`. |
| `clamp.alignment_notch_enabled` | bool | `true` | — | Key-and-slot to prevent halves from sliding axially. |
| `clamp.alignment_notch_width_mm` | float | 3.0 | mm | Length along Z (axial). Must be `> 0`. |
| `clamp.alignment_notch_depth_mm` | float | 0.8 | mm | Protrusion into mating half (Y). Must be `> 0`. |
| `clamp.alignment_notch_clearance_mm` | float | 0.1 | mm | Clearance for easy assembly. Must be `>= 0`. |

### `print_optimization`

SLA / resin print prep stage. Disabled by default; CLI flags `--optimize`,
`--no-optimize`, `--auto-orient`, and `--optimize-report-dir` override these
values. See [Print optimization](print-optimization.md) for the actual
algorithms.

```yaml
print_optimization:
  enabled: false
  target: sla
  overhang_threshold_deg: 35
  orientation:
    enabled: true
    auto_apply: false
    top_n_candidates: 5
    connector_bonus_weight: 0.7
  drain_holes:
    enabled: false
    diameter_mm: 1.5
    min_cavity_volume_mm3: 100.0
    margin_mm: 5.0
```

| Key | Type | Default | Units | Description |
| --- | --- | --- | --- | --- |
| `print_optimization.enabled` | bool | `false` | — | Master switch. Promoted to `true` by `--auto-orient`, `--optimize`, or `--optimize-report-dir`. |
| `print_optimization.target` | string enum | `sla` | — | `sla` or `fdm` (only `sla` is wired up today). Anything else raises `ValueError`. |
| `print_optimization.overhang_threshold_deg` | float | 35.0 | deg | Angle below which a face is considered an overhang. Must be in `(0, 90)`. SLA ~35°, FDM ~45°. |

#### `print_optimization.orientation`

| Key | Type | Default | Units | Description |
| --- | --- | --- | --- | --- |
| `print_optimization.orientation.enabled` | bool | `true` | — | Run the orientation search. |
| `print_optimization.orientation.auto_apply` | bool | `false` | — | Rotate the model in place to the winning orientation. Requires explicit opt-in via `--auto-orient` or this flag — analysis-only by default. |
| `print_optimization.orientation.top_n_candidates` | int | 5 | count | How many candidate orientations to score. Must be `>= 1`. |
| `print_optimization.orientation.connector_bonus_weight` | float | 0.7 | — | Multiplicative shave on Tweaker-3 unprintability when LED-tube connectors stand vertically (free support columns). `0` disables; must be in `[0, 1)`. |

#### `print_optimization.drain_holes`

Auto-drill drain + vent holes through trapped resin cavities. Requires
`--auto-orient` and `manifold3d` to be installed.

| Key | Type | Default | Units | Description |
| --- | --- | --- | --- | --- |
| `print_optimization.drain_holes.enabled` | bool | `false` | — | Master switch. Off by default — opt in only after the cavity report on your part looks correct. |
| `print_optimization.drain_holes.diameter_mm` | float | 1.5 | mm | Drill diameter. Must be `> 0`. |
| `print_optimization.drain_holes.min_cavity_volume_mm3` | float | 100.0 | mm³ | Ignore cavities smaller than this. Must be `>= 0`. |
| `print_optimization.drain_holes.margin_mm` | float | 5.0 | mm | How far the drill cylinder extends past the part's Z extents. Must be `>= 0`. |

### `server`

cadquery-web-viewer styling and the viewer connection. The top-level
`server.*` styling keys are forwarded to the viewer as
`CADQUERY_WEB_VIEWER_*` environment variables when `get_config(...)` is
called with `set_env_vars=True` (the default).

```yaml
server:
  # protocol: HTTP
  # texture: "data:image/png;base64,..."
  # color_faces: "#ffbf00"
  # color_edges: "#1a1aff"
  # color_vertices: "#1a1a1a"
  viewer:
    mode: remote
    embedded:
      host: 127.0.0.1
      port: 32323
      open_browser: true
      wait_for_first_client: false
      block_until_disconnect: false
    remote:
      host: localhost
      port: 32323
```

Top-level styling keys (any non-`None` value is exported to the
environment by [`ServerSettings.apply_to_env`](../src/led_knots/core/config.py#L414)):

| Key | Type | Default | Env var written |
| --- | --- | --- | --- |
| `server.protocol` | string | none | `CADQUERY_WEB_VIEWER_PROTOCOL` |
| `server.texture` | string | none | `CADQUERY_WEB_VIEWER_TEXTURE` |
| `server.color_faces` | string | none | `CADQUERY_WEB_VIEWER_COLOR_FACES` |
| `server.color_edges` | string | none | `CADQUERY_WEB_VIEWER_COLOR_EDGES` |
| `server.color_vertices` | string | none | `CADQUERY_WEB_VIEWER_COLOR_VERTICES` |

#### `server.viewer`

| Key | Type | Default | Units | Description |
| --- | --- | --- | --- | --- |
| `server.viewer.mode` | string enum | `remote` | — | `off`, `embedded`, or `remote`. Anything else raises `ValueError`. |

#### `server.viewer.embedded`

Used when an in-process viewer is launched (e.g. `--viewer embedded`).

| Key | Type | Default | Units | Description |
| --- | --- | --- | --- | --- |
| `server.viewer.embedded.host` | string | `127.0.0.1` | — | Bind address. |
| `server.viewer.embedded.port` | int | 32323 | — | Listen port. |
| `server.viewer.embedded.open_browser` | bool | `true` | — | Launch a browser tab when the server starts. |
| `server.viewer.embedded.wait_for_first_client` | bool | `false` | — | Block until at least one client connects before pushing the part. |
| `server.viewer.embedded.block_until_disconnect` | bool | `false` | — | Keep the script alive until the client disconnects. |

#### `server.viewer.remote`

Used when posting to a running `cadquery-web-viewer` (e.g. `--viewer remote`).

| Key | Type | Default | Units | Description |
| --- | --- | --- | --- | --- |
| `server.viewer.remote.host` | string | `localhost` | — | Viewer host. |
| `server.viewer.remote.port` | int | 32323 | — | Viewer port. |
| `server.viewer.remote.upload_timeout` | float | 300.0 | s | HTTP upload timeout. |
| `server.viewer.remote.post_timeout` | float | 60.0 | s | HTTP POST timeout for control messages. |

### `export`

Geometry export tolerances and STL format. The `filepath` is populated from
`--export` on the command line, not from YAML.

```yaml
export:
  tolerance: 0.0001
  angular_tolerance: 0.05
  stl_ascii: true
```

| Key | Type | Default | Units | Description |
| --- | --- | --- | --- | --- |
| `export.tolerance` | float | 0.00005 (YAML overrides to 0.0001) | mm | Linear tessellation tolerance. |
| `export.angular_tolerance` | float | 0.05 | rad | Angular tessellation tolerance. |
| `export.stl_ascii` | bool | `true` | — | `true` writes ASCII STL (GitHub-renderable); `false` writes binary. |

### `mesh`

Simulation-oriented OBJ output. The `filepath` is populated from
`--output-mesh` on the command line.

```yaml
mesh:
  unit_scale_mm_to_m: true
  target_face_count: null
  watertight_required: false
```

| Key | Type | Default (class) | Units | Description |
| --- | --- | --- | --- | --- |
| `mesh.unit_scale_mm_to_m` | bool | `true` | — | Convert mm (CadQuery default) to meters (Genesis, MuJoCo, etc.). |
| `mesh.target_face_count` | int or null | `null` | count | If set, trimesh decimates to roughly this many faces. `null` skips decimation. |
| `mesh.watertight_required` | bool | `true` (class) / `false` (YAML) | — | When `true`, mesh export fails with a clear error if the mesh is not closed. The committed YAML loosens this to `false`. |

### `preview`

Mesh-to-image preview pipeline (used for README previews and notebook
output). Mesh tolerance is intentionally finer than `export.tolerance` so
the tube looks smooth.

```yaml
preview:
  stl_cache: cache/preview
  mesh_tolerance: 0.0005
  mesh_angular_tolerance: 0.04
  image_width: 800
  image_height: 600
  dpi: 100
  elevation: 30
  azimuth: 45
  roll: 0
  light_azimuth: 225
  light_elevation: 45
  color: '#b3b3b3'
  opacity: 1.0
  background: '#1a1a2e'
```

| Key | Type | Default (class) | Units | Description |
| --- | --- | --- | --- | --- |
| `preview.stl_cache` | string (path) | `cache/preview` | — | Directory (relative to project root) for cached STL renders. Created on load. |
| `preview.mesh_tolerance` | float | 0.0005 | mm | Linear tessellation tolerance for the preview mesh. |
| `preview.mesh_angular_tolerance` | float | 0.04 | rad | Angular tessellation tolerance. |
| `preview.image_width` | int | 800 | px | Output image width. |
| `preview.image_height` | int | 600 | px | Output image height. |
| `preview.dpi` | int | 100 | — | Matplotlib DPI. |
| `preview.elevation` | float | 30 | deg | View elevation. |
| `preview.azimuth` | float | 45 | deg | View azimuth. |
| `preview.roll` | float | 0 | deg | View roll. |
| `preview.light_azimuth` | float | 225 | deg | Directional-light azimuth. |
| `preview.light_elevation` | float | 45 | deg | Directional-light elevation. |
| `preview.color` | string | `#b3b3b3` | — | Hex or named color for the model. Also the base hue for per-part colors when a multi-part assembly is sent to the `--server` viewer. |
| `preview.opacity` | float | 1.0 | — | Opacity in `[0.0, 1.0]`; values outside the range are silently clamped. |
| `preview.background` | string | `#ffffff` (class) / `#1a1a2e` (YAML) | — | Hex or named background color. |

Colors are parsed with `matplotlib.colors.to_rgb`; any matplotlib-accepted
spec works (hex `#rrggbb`, named colors, `(r,g,b)` triples in `[0,1]`).

## face_settings deep-dive

`face_settings` is the only place inheritance happens. The algorithm lives
in [`resolve_face_settings`](../src/led_knots/core/config.py#L46):

1. Look up the entry named by `face_type` (top-level key). If it does not
   exist, an empty dict is returned and `TubeSettings` falls back to its
   per-field defaults.
2. If the entry has an `inherit_from:` key, recurse into the parent entry,
   resolving the parent's `inherit_from` first.
3. Deep-merge the resolved parent into the child via
   [`_deep_merge_face_settings`](../src/led_knots/core/config.py#L29):
   nested dicts (`pyramid_studded`, `braided_rope`) are merged key-by-key;
   scalars in the child override scalars in the parent. The `inherit_from`
   key itself is dropped from the result.
4. **Cycle detection.** Inheritance walks track a visited set; a cycle
   raises `ValueError: face_settings inheritance cycle: a -> b -> a`.
5. **Missing parent.** If `inherit_from:` names an entry that does not
   exist, the loader raises
   `ValueError: face_settings: 'child' has inherit_from: 'missing' but that face type is not defined`.

Inheritance is unrelated to `VALID_FACE_TYPES`: the parent name simply has
to be a key in the `face_settings` block, even if you would never set
`face_type:` to that name directly.

### Worked example

```yaml
face_settings:
  solid_circle:
    outer_diameter: 30
    wall_thickness: 4.0

  pyramid_studded:
    inherit_from: solid_circle
    pyramid_studded:
      base_face_type: solid_circle
      base_size: 2.0
      height: 2.5
```

With `face_type: pyramid_studded` this resolves to:

```python
{
    "outer_diameter": 30,
    "wall_thickness": 4.0,
    "pyramid_studded": {
        "base_face_type": "solid_circle",
        "base_size": 2.0,
        "height": 2.5,
    },
}
```

If `solid_circle` itself had a `pyramid_studded:` sub-block, the child's
sub-block would be deep-merged on top of it — child keys win, missing keys
fall through to the parent.

### `tube_settings` convenience object

After resolution, `Config` constructs a single `TubeSettings` instance
([config.py:266](../src/led_knots/core/config.py#L266)) exposed as
`cfg.tube_settings`. It surfaces the resolved values as attributes for
ergonomic access:

| Attribute | Notes |
| --- | --- |
| `tube_settings.face_type` | The active face type (string). |
| `tube_settings.outer_radius` | Computed: `outer_width/2` for `square`, otherwise `outer_diameter/2`. Raises `ValueError` if the relevant key is missing for the active face. |
| `tube_settings.outer_diameter` | Raw value from face_settings (None for `square`). |
| `tube_settings.wall_thickness` | Default 1.0. |
| `tube_settings.oval_wall_thickness` | Default 2.0. |
| `tube_settings.connector_width` | Default 1.0. |
| `tube_settings.rect_inner_x` / `rect_inner_y` | Default 4.0 / 12.0. |
| `tube_settings.inner_tube_diameter` / `inner_tube_wall_thickness` | None unless face_settings supplies them. Both required for `led_circle_tube`. |
| `tube_settings.pyramid_studded` | Resolved dict or `None`. |
| `tube_settings.braided_rope` | Resolved dict or `None`. |
| `tube_settings.to_led_circle_face_kwargs(**overrides)` | Returns the kwargs dict expected by `create_led_circle_face` / `create_square_face`. |
| `tube_settings.to_led_circle_tube_face_kwargs(**overrides)` | Returns the kwargs for `create_led_circle_tube_face`; raises if `inner_tube_*` is missing. |

## Worked examples

### 1. Make every model larger

Bump the bounding box without touching anything else.

```yaml
# config.local.yaml
output_bounds:
  width: 300
  length: 200
  height: 300
```

### 2. Switch to braided_rope cross-section

The committed [config.local.yaml](../config.local.yaml) already does this;
the snippet below is a minimal variant. The `inherit_from: solid_circle`
brings in `outer_diameter` and `wall_thickness`; the nested
`braided_rope:` block configures the weave.

```yaml
# config.local.yaml
face_type: braided_rope
face_settings:
  braided_rope:
    inherit_from: solid_circle
    braided_rope:
      num_strands_per_dir: 8
      float_length: 1
      helix_angle_deg: 30.0
      strand_aspect_ratio: 1.6
      tilt_to_helix_angle: true
      strand_start: 1.0
      strand_end_offset: 1.0
```

### 3. Enable print optimization with auto-orient and drain holes

Turn the whole pipeline on, let it rotate the model, and drill drain/vent
holes through any cavity larger than 100 mm³. You will still typically pass
`--auto-orient` on the command line — but with `auto_apply: true` set here,
plain `--optimize` is enough.

```yaml
# config.local.yaml
print_optimization:
  enabled: true
  orientation:
    enabled: true
    auto_apply: true
    top_n_candidates: 8
    connector_bonus_weight: 0.7
  drain_holes:
    enabled: true
    diameter_mm: 2.0
    min_cavity_volume_mm3: 150.0
    margin_mm: 5.0
```

---

See also:

- [CLI reference](cli-reference.md) for the flags that override these keys.
- [Tube models](tube-models.md) for what each `face_type` produces and how
  `face_settings.*.pyramid_studded` / `braided_rope` blocks are consumed.
- [Print optimization](print-optimization.md) for what `print_optimization`
  actually does to the geometry.
