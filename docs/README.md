# LED Knots Documentation

This manual is the reference for `led_knots`, a Python toolkit for generating, rendering, and preparing parametric knot and tube geometries for SLA printing with embedded LED channels. It is written for developers who have cloned the repository and want to either drive the existing CLI to produce printable parts, or extend the code with new path families, tube cross-sections, or output stages. It assumes working familiarity with Python packaging, mesh-based CAD concepts (manifolds, booleans, STL/OBJ), and a command-line workflow; it does not re-teach those fundamentals.

## Map of the manual

### Getting started

- [getting-started.md](getting-started.md) — Install the package editable, run your first end-to-end render, and locate the outputs.
- [cli-reference.md](cli-reference.md) — Every subcommand, flag, and exit code for the `led_knots` entry point.
- [configuration.md](configuration.md) — The YAML/TOML config schema: every key, its default, its units, and which stage consumes it.

### Designing models

- [paths.md](paths.md) — The path registry: built-in knot/curve families, their parameters, and how to register a new path.
- [tube-models.md](tube-models.md) — The `TubeModel` registry: cross-sectional profiles swept along a path, LED channel layout, and how to add a new tube model.
- [parts.md](parts.md) — Composing paths and tube models into named, printable parts; part-level overrides and metadata.

### Rendering & preview

- [rendering-and-preview.md](rendering-and-preview.md) — Interactive previews, matplotlib/3D viewers, and the screenshot pipeline.
- [mesh-export.md](mesh-export.md) — STL/OBJ writers, mesh validation, units, and orientation conventions.

### Print preparation

- [print-optimization.md](print-optimization.md) — Bed-fit checks, drain-hole drilling, manifold repair, and the SLA print-optimization stage.
- [print-segmentation.md](print-segmentation.md) — Slicing large parts into bed-sized segments with registration features.

### Hacking

- [architecture.md](architecture.md) — High-level data flow from config to printable mesh; the stage pipeline and registries.
- [code-map.md](code-map.md) — Module-by-module tour of `src/led_knots/`.
- [developer-guide.md](developer-guide.md) — Running tests, adding stages, debugging meshes, and contribution conventions.

## Conventions

- **Units.** All lengths are in millimetres (mm) unless a field explicitly says otherwise. Volumes are mm^3, areas are mm^2.
- **Angles.** All angles are in degrees unless a field explicitly says otherwise. Trigonometric internals convert to radians at the boundary.
- **Repo paths.** Paths shown like `src/led_knots/core/utils.py` are relative to the repository root (the directory containing `pyproject.toml`). Markdown links in these docs use `../` because docs live one level below the root.
- **CLI examples.** All `led_knots ...` invocations assume the package has been installed editable (`pip install -e .`) into the active environment. If you prefer not to install, substitute `python -m led_knots ...`.
- **Coordinate frame.** Z is up; the print bed lies in the XY plane at Z=0 unless a stage repositions the part.

## Where to start

- **"I want to print a knot right now."** Read [getting-started.md](getting-started.md), then run the default config and hand the resulting STL to your slicer.
- **"I want to add a new knot or curve."** Skim [architecture.md](architecture.md) for the registry pattern, then follow the cookbook in [paths.md](paths.md).
- **"I want a different tube cross-section or LED channel layout."** Go straight to [tube-models.md](tube-models.md); the registry mirrors paths.
- **"I want to understand the SLA print prep."** Start with [print-optimization.md](print-optimization.md), then [print-segmentation.md](print-segmentation.md) if your part exceeds the bed.
- **"I want to hack on the code."** Read [code-map.md](code-map.md) and [developer-guide.md](developer-guide.md) in that order.
