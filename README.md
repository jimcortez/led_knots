# LED Knots

A Python tool for generating 3D printable mathematical knot models designed to house LED strips. Built using the [CadQuery](https://cadquery.readthedocs.io/) CAD engine.

## Overview

LED Knots creates parametric 3D models of various mathematical knots and paths, each designed with an internal channel to accommodate LED strips. The models can be exported to STL, STEP, or other 3D formats for 3D printing.

### Features

- **Multiple knot types**: From simple rods and rings to complex trefoil and torus knots
- **LED-optimized cross-sections**: Custom cross-section profiles designed for LED strip insertion
- **Auto-diameter calculation**: Automatically calculates optimal tube diameter based on LED count for best light diffusion
- **Diffusion ridges**: Optional triangular ridges on the oval surface for enhanced light diffusion and visual effects
- **Flexible orientation control**: Advanced path curvature analysis and twist optimization
- **Multiple export formats**: STL, STEP, 3MF, GLB/GLTF support
- **Web-based preview**: Optional yacv-server integration for browser-based 3D viewing
- **GLB cache**: Cached previews by path and config so repeated viewing is fast; optional `--no-cache` and `--only-cache` flags

## Installation

### Using uv (recommended)

```bash
uv pip install -e .
```

### Using pip

```bash
pip install -e .
```

### Dependencies

- Python 3.13+
- CadQuery 2.6.1+
- NumPy
- pyknotid (for mathematical knot generation)
- yacv-server (for 3D visualization)

## Quick Start

Each knot type can be run as a standalone script. Export to a file, or view in the built-in viewer.

```bash
# Export to STL (or .step, .3mf, .glb, .gltf)
python -m led_knots.knots.trefoil --export trefoil.stl
# or, if installed: led-knots-trefoil --export trefoil.stl

# View in the default viewer (uses cache when available)
python -m led_knots.knots.trefoil

# Start the yacv web server and view in your browser
python -m led_knots.knots.trefoil --server
```

### Available commands

| Command | Description |
|---------|-------------|
| `led-knots-rod` | Straight vertical pipe |
| `led-knots-ring` | Simple circular ring |
| `led-knots-helix` | Helical spiral path |
| `led-knots-sine-wave` | Sine wave oscillation path |
| `led-knots-trefoil` | Mathematical trefoil knot |
| `led-knots-figure-8` | Figure-8 / torus knot |
| `led-knots-jog-bend` | 2D jog bend path |
| `led-knots-jog-bend-3d` | 3D jog bend with orientation control |
| `led-knots-quarter-turn` | 90-degree turn path |
| `led-knots-twisted-rod` | Straight rod with 90-degree twist |

### Command line options

All knot commands accept the same options:

| Option | Description |
|--------|-------------|
| `--export FILEPATH` | Export the model to a file. Supported formats: `.stl`, `.step`, `.stp`, `.3mf`, `.glb`, `.gltf` |
| `--server` | Start the yacv web server and open the model in your browser |
| `-v`, `--verbose` | Enable debug-level logging |
| `--no-cache` | Always rebuild the 3D model from the path; never use or update the GLB cache |
| `--only-cache` | Only show the model if a cached GLB exists; skip building if not (useful for quick previews) |

When you omit `--export` and `--server`, the model is shown in the default viewer. Use `--server` to keep a local web server running for browser-based viewing.

## Configuration

LED Knots uses a centralized configuration system via `config.yaml` in the project root. This file controls:

- **Output bounds**: Dimensions for the generated models (width, length, height)
- **face_type**: Top-level key selecting the cross-section face (e.g. `led_circle`, `square`)
- **Face settings**: Per-face options keyed by face name: `outer_diameter` or `outer_width` (for square), `wall_thickness` (e.g. in led_circle), `rect_inner_x` / `rect_inner_y` (led_circle cavity, with comments referencing original strip values), oval/connector/diffusion options. Use `inherit_from` to inherit from another face and override keys.
- **Path**: `min_90_degree_twist_distance` (mm) for twist rate limits along the path
- **Server**: Object cache location and optional yacv-server options (host, port, colors, etc.)
- **Export settings**: Export tolerances for 3D file formats

### Server and cache

The **server** section in `config.yaml` configures where GLB previews are cached and how the yacv web viewer behaves:

```yaml
server:
  object_cache: 'cache/glb_blobs'   # Folder for cached GLB files (created automatically)
  # Optional overrides for yacv-server (uncomment to use):
  # host: 'localhost'
  # port: 32323
  # color_faces: '#ffbf00'
  # color_edges: '#1a1aff'
  # color_vertices: '#1a1a1a'
  # disable_server: false
```

- **object_cache**: Directory (relative to the project root) where built GLB models are stored. When you view a knot without `--export`, a hash of the path and settings is used as the filename; if that file exists, it is loaded instead of rebuilding. This speeds up repeated previews. The folder is created on first run if it does not exist.
- **yacv overrides**: Any option you set here (e.g. `host`, `port`, `color_faces`) is applied as the corresponding `YACV_*` environment variable before the viewer starts, so you can customize the server without editing shell env by hand.

Cache is **not** used when you pass `--export`: the model is always built from the path and then exported. Use `--no-cache` to force a full rebuild even when only viewing, and `--only-cache` to only open a previously cached GLB (no build).

### Configuration details

#### Face type and face settings

- **face_type** is a top-level key (e.g. `face_type: led_circle`). It selects which face from `face_settings` is used.
- **face_settings** is keyed by face name (`led_circle`, `led_circle_diffusion_pyramids`, `solid_circle`, `solid_circle_pyramid`, `square`). Each face defines its own dimensions and options:
  - **led_circle**: `outer_diameter`, `wall_thickness`, `rect_inner_x`, `rect_inner_y` (cavity for LED strip; comments in config can reference original strip width/height + tolerances), `oval_wall_thickness`, `connector_width`, `diffusion_ridges`.
  - **solid_circle**: `outer_diameter` only.
  - **solid_circle_pyramid**: `outer_diameter`, `wall_thickness`, `diffusion_ridges`.
  - **square**: `outer_width` (side length in mm).
- **inherit_from**: A face entry can set `inherit_from: <face_name>`. Resolved settings are the inherited face’s settings (recursively), then the current block’s keys overlaid (nested dicts deep-merged). Cycles and missing parents cause an error.

Example:

```yaml
face_type: led_circle

face_settings:
  led_circle:
    outer_diameter: 30
    wall_thickness: 1.0
    rect_inner_x: 4.6   # from strip height 1.8*2 (double-sided) + tolerance 1
    rect_inner_y: 11.0  # from strip width 10 + tolerance 1
    oval_wall_thickness: 0.5
    connector_width: 0.5
    diffusion_ridges: { ridge_height: 2.5, ridge_width: 2.0, ridge_spacing: 1, ridge_depth: 2.5 }
  led_circle_diffusion_pyramids:
    inherit_from: led_circle
    diffusion_ridges: { ridge_height: 3.0, ... }  # override
  solid_circle:
    outer_diameter: 30
  square:
    outer_width: 30
```

#### Path settings

The **path** section provides twist limits along the sweep path:

```yaml
path:
  min_90_degree_twist_distance: 5  # mm minimum distance for 90° twist
```

#### Diffusion Ridges

Optional triangular ridges on the oval cross-section (e.g. for `led_circle` or `led_circle_diffusion_pyramids`) are configured under **face_settings**:

```yaml
face_settings:
  led_circle:
    diffusion_ridges:
      ridge_height: 2.5
      ridge_width: 2.0
      ridge_spacing: 1
      ridge_depth: 2.5
```

Set `diffusion_ridges: false` or omit the key to disable ridges for that face.

#### LED cavity dimensions (led_circle)

Inner rectangle dimensions `rect_inner_x` and `rect_inner_y` in **face_settings.led_circle** define the cavity for the LED strip. Set them to match your strip width/height plus tolerances (e.g. strip width 10 mm + tolerance 1 mm → `rect_inner_y: 11.0`; strip height 1.8 mm, double-sided, + tolerance → `rect_inner_x: 4.6`). The config file comments can reference these original values.

### Customizing Configuration

You can override the default `config.yaml` by creating a `config.local.yaml` file in the project root. This allows you to customize settings without modifying the default configuration.

Example `config.local.yaml`:
```yaml
output_bounds:
  width: 150
  height: 200

face_type: led_circle

face_settings:
  led_circle:
    outer_diameter: 35
    wall_thickness: 1.5
```

All knot modules automatically use these configuration values, making it easy to adjust model dimensions and tube parameters across all knot types.

## LED Cross-Section Design

The LED cross-section consists of:

1. **Outer ring**: The main structural housing
2. **Center oval**: An elliptical cavity with a rectangular inner cutout for the LED strip
3. **Connecting bars**: Links between the outer ring and center oval
4. **Diffusion ridges** (optional): Triangular ridges on the outside of the oval for enhanced light diffusion

This design allows the LED strip to be inserted into the center channel while the outer ring provides structural support and diffusion. The optional diffusion ridges create additional surface area and light-scattering effects for improved visual appearance.



## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.
