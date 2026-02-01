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

### Generate a knot model

Each knot type can be run as a standalone script:

```bash
# Using the module directly
python -m led_knots.knots.trefoil --export trefoil.stl

# Or using installed entry points
led-knots-trefoil --export trefoil.stl
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

```bash
led-knots-trefoil --help

Options:
  --export FILEPATH  Export the model to the specified file path
                     Supported formats: .stl, .step, .stp, .3mf, .glb, .gltf
  --server           Start the yacv server for web viewing
```

## Configuration

LED Knots uses a centralized configuration system via `config.yaml`. This file controls:

- **Output bounds**: Dimensions for the generated models (width, length, height)
- **Tube settings**: Cross-section parameters (auto-diameter or manual outer diameter, wall thickness, oval wall thickness, connector width, LED tolerances, diffusion ridges)
- **LED strip settings**: LED strip specifications (width, height, LED count, twist requirements)
- **Export settings**: Export tolerances for 3D file formats

### New Configuration Features

#### Auto-Diameter Calculation

When `auto_diameter: true` is set in `tube_settings`, the outer diameter is automatically calculated based on the LED count to optimize light diffusion. The calculation ensures the distance between LEDs matches the inner radius of the tube, providing optimal spacing for uniform light distribution.

```yaml
tube_settings:
  auto_diameter: true  # Automatically calculate diameter from LED count
  # outer_diameter: 30  # Only needed if auto_diameter is false
```

#### Diffusion Ridges

Optional triangular ridges can be added to the outside of the oval cross-section to enhance light diffusion and create visual effects. Configure ridges in `tube_settings`:

```yaml
tube_settings:
  diffusion_ridges:
    ridge_height: 2.5  # Height of ridges in mm
    ridge_width: 2.0   # Width of each ridge base in mm
    ridge_spacing: 1   # Spacing between ridges in mm
```

Set `diffusion_ridges: false` or omit the section to disable ridges.

#### Enhanced LED Strip Integration

The configuration system now automatically calculates inner rectangle dimensions from LED strip settings, accounting for:
- LED strip width and height
- Tolerance values for fit
- Double-sided LED support (automatically doubles height when enabled)

### Customizing Configuration

You can override the default `config.yaml` by creating a `config.local.yaml` file in the project root. This allows you to customize settings without modifying the default configuration.

Example `config.local.yaml`:
```yaml
output_bounds:
  width: 150
  height: 200

tube_settings:
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
