# LED Knots

A Python tool for generating 3D printable mathematical knot models designed to house LED strips. Built using the [CadQuery](https://cadquery.readthedocs.io/) CAD engine.

## Overview

LED Knots creates parametric 3D models of various mathematical knots and paths, each designed with an internal channel to accommodate LED strips. The models can be exported to STL, STEP, or other 3D formats for 3D printing.

### Features

- **Multiple knot types**: From simple rods and rings to complex trefoil and torus knots
- **LED-optimized cross-sections**: Custom cross-section profiles designed for LED strip insertion
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
- **Tube settings**: Cross-section parameters (outer diameter, wall thickness, LED tolerances)
- **LED strip settings**: LED strip specifications (width, height, LED count, twist requirements)
- **Export settings**: Export tolerances for 3D file formats

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

## Project Structure

```
led_knots/
├── src/
│   └── led_knots/
│       ├── __init__.py          # Package exports
│       ├── core/                 # Core utilities
│       │   ├── __init__.py
│       │   ├── utils.py         # CLI, rendering, path analysis
│       │   └── led_circle.py    # LED cross-section creation
│       └── knots/               # Knot generators
│           ├── __init__.py
│           ├── rod.py           # Straight rod
│           ├── ring.py          # Circular ring
│           ├── helix.py         # Helical path
│           ├── sine_wave.py     # Sine wave path
│           ├── trefoil.py       # Trefoil knot
│           ├── figure_8.py      # Figure-8/torus knot
│           ├── jog_bend.py      # 2D jog bend
│           ├── jog_bend_3d.py   # 3D jog bend with twist
│           ├── quarter_turn.py  # 90-degree turn
│           └── twisted_rod.py   # Twisted straight rod
├── pyproject.toml
└── README.md
```

## LED Cross-Section Design

The LED cross-section consists of:

1. **Outer ring**: The main structural housing
2. **Center oval**: An elliptical cavity with a rectangular inner cutout for the LED strip
3. **Connecting bars**: Links between the outer ring and center oval

This design allows the LED strip to be inserted into the center channel while the outer ring provides structural support and diffusion.



## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.
