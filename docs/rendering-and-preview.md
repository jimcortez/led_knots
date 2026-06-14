# Rendering and preview

Every knot script ends with a single call into the same render pipeline
([src/led_knots/core/render_pipeline.py](../src/led_knots/core/render_pipeline.py)),
which inspects the resolved config and emits any combination of three
distinct outputs: a CAD export, a still preview image, and an interactive
browser viewer. This document covers how each output is produced, which
configuration keys control it, the on-disk caches involved, and how the
multi-part palette and the helper preview-generator script fit in.

For the YAML keys referenced below, see the
[Configuration reference](configuration.md) and the in-tree
[config.yaml](../config.yaml). For CLI flag wiring, see
[CLI reference](cli-reference.md).

## Three output modes (don't confuse them)

The three outputs are independent and can be requested simultaneously
(`--export model.stl --preview model.png --server` is a valid
invocation). They are coordinated by `RenderPlan.from_config` in
[render_pipeline.py:338](../src/led_knots/core/render_pipeline.py#L338) so
the underlying tessellation work is shared rather than repeated.

| Mode | CLI trigger | Produced file | Config block | Producer module |
| --- | --- | --- | --- | --- |
| CAD export | `--export PATH` | `.stl` / `.step` / `.stp` / `.3mf` / `.glb` / `.gltf` | `export.*` | `cq.exporters.export` and `Assembly.export` in [render_pipeline.py](../src/led_knots/core/render_pipeline.py#L486) |
| Preview image | `--preview PATH` | `.png` (or `.jpg/.jpeg`) | `preview.*` | [src/led_knots/core/preview.py](../src/led_knots/core/preview.py) via trimesh + pyrender + Pillow |
| Browser viewer | `--server` | live HTTP session to remote cadquery-web-viewer | `server.*` | `cadquery-web-viewer` driven from [render_pipeline.py](../src/led_knots/core/render_pipeline.py) |
| Simulation mesh (bonus) | `--output-mesh PATH` | `.obj` | `mesh.*` | trimesh load + decimate in [render_pipeline.py:170](../src/led_knots/core/render_pipeline.py#L170) |

Pick by goal:

- **You want a slicer-ready file**: use `--export`. STL/3MF go through
  CadQuery's STL tessellator (driven by `export.tolerance` /
  `export.angular_tolerance`); STEP goes through OCCT's BRep writer
  unchanged.
- **You want a thumbnail for the README, a PR, or `scripts/generate_previews.py`**:
  use `--preview`. This always tessellates into RAM (or into the preview
  STL cache) and renders offscreen — no GUI, no server.
- **You want to spin the model around in a browser**: start
  `cadquery-web-viewer`, then use `--server` on render or `upload-knot` on a
  bundle. Geometry is tessellated to GLB and POSTed to the remote server.

`RenderPlan` deduplicates work across these: if you ask for `--preview`
plus `--server`, the bundle GLB is also fed to the preview renderer; if you ask for `--preview` plus `--export model.stl`, the export
STL is reused as the preview source. See `preview_uses_export_stl` and
`preview_from_glb` in [render_pipeline.py:312](../src/led_knots/core/render_pipeline.py#L312).

## Export

`--export PATH` writes a single CAD file. The format is selected by the
extension; the per-format support matrix lives in
[render_pipeline.py:28](../src/led_knots/core/render_pipeline.py#L28):

| Extension | Solid / Compound | Assembly | Notes |
| --- | --- | --- | --- |
| `.stl` | yes | yes (fused) | Assembly is exported as a single fused STL |
| `.step` / `.stp` | yes | yes | Assemblies use `mode="default", write_pcurves=True, precision_mode=0` to preserve part boundaries |
| `.3mf` | yes | yes (fused) | Same STL tessellator under the hood |
| `.glb` | yes | yes | Binary glTF |
| `.gltf` | yes | yes | Text glTF; written by loading GLB into trimesh and re-exporting |

If `--export` is passed without a corresponding extension in
`_SUPPORTED_SOLID_EXPORT` / `_SUPPORTED_ASSEMBLY_EXPORT`, the pipeline
logs an error and exits with code 2
([render_pipeline.py:583](../src/led_knots/core/render_pipeline.py#L583)).

Relevant config keys (under `export:` in `config.yaml`,
parsed by `ExportSettings` at [config.py:422](../src/led_knots/core/config.py#L422)):

| Key | Default | Meaning |
| --- | --- | --- |
| `export.tolerance` | `0.00005` (YAML ships `0.0001`) | OCCT linear tessellation tolerance (mm) for STL/3MF/GLB. Lower = more triangles. |
| `export.angular_tolerance` | `0.05` | OCCT angular tessellation tolerance (rad). Lower = more triangles around curves. |
| `export.stl_ascii` | `true` (Python default; YAML matches) | `true` → ASCII STL (diff-friendly, larger), `false` → binary STL (smaller). Only consulted for `.stl` exports. |

Per-format quirks:

- **STEP assemblies** explicitly enable `write_pcurves` and force
  `precision_mode=0` so downstream viewers get parametric curves and
  uniform precision.
- **GLTF** is written by first producing GLB bytes and then re-exporting
  through trimesh, so any quirks of trimesh's glTF writer apply (in
  particular, assembly hierarchy is flattened into one mesh).
- **STL/3MF assemblies** are fused: leaf parts lose their identity and
  become one connected mesh. If you need per-part STLs, use the
  multi-part export helper described in [CLI reference](cli-reference.md) (`--export-parts`).

## Preview image

`--preview PATH` produces a single still image (PNG by default; `.jpg`
or `.jpeg` triggers a JPEG quality-95 save). The full pipeline is in
[preview.py](../src/led_knots/core/preview.py):

1. The model is tessellated to STL (via the preview STL cache; see below)
   or GLB (if the viewer is also active or `--export model.glb` is set).
2. trimesh loads the mesh and computes a bounding box.
3. pyrender builds a `MetallicRoughnessMaterial` from the configured
   color (auto-darkened to 82% to avoid blowing out to white;
   [preview.py:177](../src/led_knots/core/preview.py#L177)) and adds it
   to a `Scene` with `ambient_light=[0.35, 0.35, 0.35]`.
4. A `PerspectiveCamera` (`yfov=π/4`) is placed at `1.8 × max(extent)`
   away from the bbox center using the configured elevation, azimuth,
   and roll. World-up is +Y (matching the GLB convention).
5. A single `DirectionalLight` at intensity `1.2` is placed using
   `light_azimuth` and `light_elevation`.
6. `OffscreenRenderer(width, height)` produces an RGBA buffer; pyrender's
   transparent background is composited over the configured background
   color, then handed to Pillow for the save.

There is also `render_annotated_mesh_to_image`
([preview.py:271](../src/led_knots/core/preview.py#L271)) used by the
SLA optimizer to color faces (red overhangs, etc.). It takes the same
`preview.*` config but runs in the Z-up CAD frame because the annotated
mesh comes straight from CadQuery rather than from a GLB.

Relevant config keys (under `preview:` in `config.yaml`; parsed by
`PreviewSettings` at [config.py:432](../src/led_knots/core/config.py#L432)):

| Key | Default | Meaning |
| --- | --- | --- |
| `preview.stl_cache` | `cache/preview` | Directory (relative to repo root) where preview STLs are cached. Created on import; safe to delete. |
| `preview.mesh_tolerance` | `0.0005` mm | OCCT linear tolerance used when tessellating for the preview/viewer. Finer than export so curved tubes look smooth. |
| `preview.mesh_angular_tolerance` | `0.04` rad | OCCT angular tolerance for the same. |
| `preview.image_width` | `800` px | Output image width. |
| `preview.image_height` | `600` px | Output image height. |
| `preview.dpi` | `100` | Read but currently unused by the pyrender pipeline; kept for matplotlib backward-compat. |
| `preview.elevation` | `30` deg | Camera elevation above the XZ plane (Y-up). |
| `preview.azimuth` | `45` deg | Camera azimuth around the Y axis. |
| `preview.roll` | `0` deg | Camera roll around its view axis. |
| `preview.light_azimuth` | `225` deg | Directional-light azimuth around the model. |
| `preview.light_elevation` | `45` deg | Directional-light elevation. |
| `preview.color` | `#b3b3b3` | Base model color. Accepts hex (`#rrggbb`), CSS name (`red`), or `[r, g, b]` 0–1 list. Parsed via `matplotlib.colors.to_rgb`. |
| `preview.opacity` | `1.0` | Alpha for the model material, clamped to `[0, 1]`. |
| `preview.background` | `#ffffff` (Python default; YAML ships `#1a1a2e`) | Background color composited under the rendered RGBA. |

### The preview STL cache

When `--preview` runs without `--server`, the pipeline writes the
intermediate STL into `preview.stl_cache` and reuses it on subsequent
runs whose inputs hash to the same key.

The key is built by `cache_key_for_part` in
[cache_utils.py:153](../src/led_knots/core/cache_utils.py#L153):

```
<slug(part name)>-[<slug(face_kwargs)>-]<config_hash>-<path_hash>.stl
```

Components:

- **Part name slug**: `config.name` (set by each knot module) lowercased
  with non-alphanumerics replaced by `-`.
- **Rotation params slug**: serialization of the per-face `face_kwargs`
  passed to the tube model (excluding `orient_to_path`).
- **`config_hash`** ([cache_utils.py:76](../src/led_knots/core/cache_utils.py#L76)):
  16-char SHA256 prefix over `output_bounds`, `tube_settings` (active
  face block including per-model dicts like `pyramid_studded`,
  `braided_rope`), `path_settings`, `max_print_bounds` (including the
  full `joint` sub-block), and `print_optimization.cache_key_dict()`.
  Floats are rounded to 5 decimal places before hashing for stability.
- **`path_hash`** ([cache_utils.py:45](../src/led_knots/core/cache_utils.py#L45)):
  16-char SHA256 prefix over 1001 samples (`t` from 0 to 1 in steps of
  0.001) of `path.positionAt(t)` for the sweep path and any auxiliary
  path, each coordinate rounded to 5 decimal places.

Invalidation is implicit: any change that perturbs any of the hashed
inputs produces a new filename, and the old file simply sits unused.
Toggling `--optimize` / `--auto-orient` is captured because
`print_optimization` is part of the config hash
([cache_utils.py:144](../src/led_knots/core/cache_utils.py#L144)),
so reorientation invalidates stale preview STLs.

Manual cleanup is just `rm -rf cache/preview` (or whatever
`stl_cache` points to). The directory is recreated on the next run by
[config.py:543](../src/led_knots/core/config.py#L543).

Note: when the preview is fed from a GLB (because the viewer is also
active, or `--export` is GLB/GLTF) or from an already-written export STL,
the STL cache is bypassed — see `preview_uses_export_stl` and
`preview_from_glb` in `RenderPlan`. When the cache *is* bypassed the
intermediate STL is written to a tempfile and deleted afterwards
([render_pipeline.py:708](../src/led_knots/core/render_pipeline.py#L708)).

## Browser viewer

The interactive viewer is a wrapper around the third-party
`cadquery-web-viewer` package. Use `--server` on `render-knot` / `render-part`
to POST the bundle GLB after exports complete, or `upload-knot` on an existing
bundle. Both paths require a separately running `cadquery-web-viewer` server.

YAML lives under `server.viewer` and is parsed by `ViewerSettings`
([config.py:375](../src/led_knots/core/config.py#L375)):

| Key | Default | Meaning |
| --- | --- | --- |
| `server.viewer.host` | `localhost` | Host of the cadquery-web-viewer server. |
| `server.viewer.port` | `32323` | Port of that server. |
| `server.viewer.upload_timeout` | `300.0` s | HTTP upload timeout for the geometry POST. |
| `server.viewer.post_timeout` | `60.0` s | Per-request HTTP timeout. |
| `server.viewer.tessellation_tolerance` | `0.05` mm | Tessellation tolerance for uploads. |
| `server.viewer.tessellation_angular_tolerance` | `0.1` rad | Angular tessellation tolerance for uploads. |

Before uploading, the pipeline probes `http://{host}:{port}/api/scene` and
exits with an error if the server is unreachable
([render_pipeline.py:38](../src/led_knots/core/render_pipeline.py#L38)).

### Styling environment variables

`cadquery-web-viewer` reads several `CADQUERY_WEB_VIEWER_*` env vars at
import time to set the default scene styling. `ServerSettings`
([config.py:394](../src/led_knots/core/config.py#L394)) bridges YAML to
env vars via `_ENV_MAP`:

| YAML key | Env var |
| --- | --- |
| `server.protocol` | `CADQUERY_WEB_VIEWER_PROTOCOL` |
| `server.texture` | `CADQUERY_WEB_VIEWER_TEXTURE` |
| `server.color_faces` | `CADQUERY_WEB_VIEWER_COLOR_FACES` |
| `server.color_edges` | `CADQUERY_WEB_VIEWER_COLOR_EDGES` |
| `server.color_vertices` | `CADQUERY_WEB_VIEWER_COLOR_VERTICES` |

`load_config()` calls `apply_to_env()` before any of your code imports
`cadquery_web_viewer`, so values set in `config.yaml` win
([config.py:664](../src/led_knots/core/config.py#L664)). Keys that are
left unset in YAML are not written to the environment at all, so an
existing env-var setting in your shell is preserved.

### Tessellation

The browser viewer uses `server.viewer.tessellation_tolerance` and
`server.viewer.tessellation_angular_tolerance` for uploads
(`_viewer_tessellation_kwargs` at
[render_pipeline.py:30](../src/led_knots/core/render_pipeline.py#L30)).
When `--server` is set, the pipeline uploads the bundle GLB written by the
export job when one is enabled; otherwise it builds GLB bytes via the standard
CadQuery → STL → trimesh path.

## Multi-part assemblies

When a knot produces a `cq.Assembly` with multiple leaf solids (for
example, the tube plus the two halves of the clamp), the viewer path
colorizes each leaf so they stand out:

- `iter_assembly_leaf_solids`
  ([color_palette.py:64](../src/led_knots/core/color_palette.py#L64))
  walks `assy.traverse()` and returns each tessellatable solid.
- `palette_rgba` ([color_palette.py:28](../src/led_knots/core/color_palette.py#L28))
  derives `n` harmonious face colors from `preview.color`: it converts
  the base RGB to HSV and steps the hue evenly around the wheel. If the
  base color is near-grey (saturation < 0.12) it is auto-boosted to
  saturation `0.72` and value `≥ 0.55` so the parts read as distinct
  colors instead of as a row of grays. This is why the default
  `preview.color: '#b3b3b3'` still yields a usable multi-color preview.
- `_cadquery_web_viewer_show_colored_parts`
  ([render_pipeline.py:95](../src/led_knots/core/render_pipeline.py#L95))
  posts one part at a time with `color_faces=color, auto_clear=(idx == 0)`,
  so the viewer accumulates the colored parts in a single scene without
  the default white material overwriting them.

This only fires when `assy` has two or more tessellatable leaves; a
single-leaf assembly takes the regular `emit_viewer` path and uses the
plain `preview.color`.

The preview PNG and the CAD export both still see the assembly as one
geometry (preview PNG via merged GLB; STL/3MF as fused mesh; STEP/GLB
preserve hierarchy), so per-part colors only manifest in the browser
viewer.

## Generating all previews

[scripts/generate_previews.py](../scripts/generate_previews.py) is a
batch driver used to keep `assets/*.png` (referenced from the
[README](../README.md)) in sync. It:

1. Walks a hardcoded `KNOTS` list (`rod`, `twisted_rod`, `quarter_turn`,
   `ring`, `jog_bend`, `jog_bend_3d`, `helix`, `figure_8`, `trefoil`,
   `k4_1`, `stevedore`).
2. For each name, invokes
   `render-knot knot_configs/<name>.yaml` (preview PNG in the render bundle) as a
   subprocess from the project root (`subprocess.run(..., timeout=300)`).
3. Reopens the resulting PNG and overlays a black label box with the
   display name in the bottom-left, then writes it back in place.
4. Stitches all PNGs into `assets/previews.gif` (2 s per frame, infinite
   loop).

Run it from the project root:

```bash
uv run python scripts/generate_previews.py
# or:
python scripts/generate_previews.py
```

Any knot that fails or times out is collected into a `failed` list and
the script exits with code 1. Successful runs print
`<name> -> assets/<name>.png` per knot and a final `Combined GIF: ...`
summary.

To add a new knot to the gallery, append its module name to the `KNOTS`
list at the top of the script. Per-knot view angles, tessellation
quality, and colors are *not* overridable here — they all come from your
project-level `config.yaml` / `config.local.yaml`. If you want a
different look for the gallery than for your interactive work, edit
`config.local.yaml` before running the script.

## Troubleshooting

**Viewer logs `Posted ... to cadquery-web-viewer at http://localhost:32323/` and nothing happens.**
No standalone `cadquery-web-viewer` server is running on that host/port.
Start one in a separate terminal (`cadquery-web-viewer --host localhost --port 32323`),
then re-run with `--server` or `upload-knot`. The `post_timeout` setting
(default 60 s) controls how long the CLI waits before raising a connection error.

**Preview image looks blocky / faceted on curved tubes.**
`preview.mesh_tolerance` and `preview.mesh_angular_tolerance` are too
coarse. The defaults (`0.0005` mm linear, `0.04` rad angular) are tuned
for the LED-tube radii in the bundled knots; for much smaller features
drop both by an order of magnitude. Remember that finer tessellation
also slows down the viewer.

**Preview image is washed out / too white.**
The base color is auto-darkened to 82% to fight pyrender's bright
default ambient (`0.35` on each channel). If you want more vivid colors,
pick a saturated `preview.color` rather than tweaking ambient — the
ambient and the 82% factor are hardcoded in
[preview.py:177](../src/led_knots/core/preview.py#L177).

**Multi-part assembly shows up as one solid color in the viewer.**
The colored path only triggers for assemblies with two or more
tessellatable leaves. Verify your knot module is returning a
`cq.Assembly` with multiple parts (e.g. via `iter_assembly_leaf_solids`)
and that the active mode posts via `_cadquery_web_viewer_show_colored_parts`.

**Cache appears stale (you changed `config.yaml` but the preview is unchanged).**
Confirm the field you changed is actually part of `config_settings_hash`
([cache_utils.py:76](../src/led_knots/core/cache_utils.py#L76)). Only
`output_bounds`, the active `tube_settings` block, `path_settings`,
`max_print_bounds`, and `print_optimization` participate in the hash —
changing, say, `clamp.*` will not change the stem. As a fallback,
`rm -rf cache/preview` forces a full rebuild on the next run.

**macOS: `objc[...]: Class ... is implemented in both ...libvtkRenderingUI...`**
The PyPI `vtk` wheel ships a `libvtkRenderingUI.dylib` that duplicates
the one from `cadquery-vtk`. Run
[scripts/fix_macos_vtk_dylibs.sh](../scripts/fix_macos_vtk_dylibs.sh)
from anywhere — it locates the stray dylib inside `vtkmodules/.dylibs/`,
removes it, and reinstalls `cadquery-vtk` to restore the correct copy.
The script is safe to re-run; it is idempotent.

**`--export-parts` doesn't write anything.**
Both `--export-parts` and `--export-parts-dir` must be set, and the
knot must build an `Assembly`. See `maybe_export_named_parts` in
[utils.py:196](../src/led_knots/core/utils.py#L196) for the supported
tokens (`assembly`, `tube`, `clamp_a`, `clamp_b`, `clamp_halves`, `all`)
and [CLI reference](cli-reference.md) for usage.
