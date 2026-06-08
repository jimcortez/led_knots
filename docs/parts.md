# Auxiliary parts

The [src/led_knots/parts/](../src/led_knots/parts/) package collects parametric
accessory parts that ride alongside the knot tubes themselves: clamps to hold
the tube, spacers to set its position against other hardware, and so on. They
share the same config loader and render pipeline as the knot scripts, so you
get the same `--export`, `--output-mesh`, `--preview`, and `--server` /
`--viewer` behaviour for free.

This page documents the parts currently shipped and shows how to add another
one without re-inventing the surrounding plumbing.

See also: [Configuration reference](configuration.md),
[CLI reference](cli-reference.md), [Architecture](architecture.md),
[Rendering and preview](rendering-and-preview.md).

## Hang clamp

A two-part circular clamshell that wraps around the tube. One half carries a
through-hole and a tapered collar for routing a power wire out of the tube;
the other half is plain. The seam is a continuous stepped lap (rabbet) along
the `Y=0` plane with a tongue-and-groove for registration, an alignment tab to
prevent axial slipping, and optional relief pockets so glue can escape. Use it
wherever you have introduced a `tube_gap` in the sweep and need to hang the
assembly from a ceiling hook or mount it to a fixture.

The implementation lives in
[src/led_knots/parts/hang_clamp.py](../src/led_knots/parts/hang_clamp.py).

### Geometry

- Local `+Z` is the clamp axis (aligned with the tube tangent).
- The clamp inner radius equals `tube_settings.outer_radius + 0.5 *
  clearance_diameter_mm` (equivalently: clamp ID = tube OD +
  `clearance_diameter_mm`); the OD adds another `wall_thickness_mm` on top.
- The clamshell splits at `Y=0`. The `+Y` half is the "hole" half and carries
  the wire through-hole and tapered collar; the `-Y` half is plain.
- The lap joint deliberately crosses the split plane so the halves overlap
  rather than meeting on a flat seam. The tongue is nested inside the lap
  area; the groove on the mating half is enlarged by `reg_clearance_mm` and
  `adhesive_gap_mm`.
- The wire hole is drilled perpendicular to the clamp axis (along `+Y`), and a
  lofted collar tapers from `wire_ring_base_thickness_mm` at the body to
  `wire_ring_top_thickness_mm` at the tip.

Use [`location_from_point_tangent(point_xyz, tangent_xyz)`](../src/led_knots/parts/hang_clamp.py#L41)
to place an instance along a knot path: it returns a `cq.Location` whose local
`+Z` points along the supplied tangent.

### Parameters (`clamp.*`)

All values come from the top-level `clamp:` block in `config.yaml`. Units are
millimetres unless noted. Defaults are the values shipped in
[config.yaml](../config.yaml).

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Whether the hang clamp build is active for assemblies that consume it. |
| `clearance_diameter_mm` | `0.5` | Clamp ID = tube OD + this value (radial gap is half). |
| `length_mm` | `18.0` | Axial length of the clamp (along `+Z`). |
| `wall_thickness_mm` | `1.25` | Radial wall thickness outside the tube. |
| `wire_hole_diameter_mm` | `4.0` | Diameter of the through-hole on the `+Y` half. Set to `0` to omit the hole and collar. |
| `wire_ring_height_mm` | `4.0` | Height of the tapered collar above the outer surface. |
| `wire_ring_top_thickness_mm` | `1.0` | Wall thickness of the collar at the tip. |
| `wire_ring_base_thickness_mm` | `2.0` | Wall thickness of the collar where it meets the body (tapers up from here). |
| `lap_depth_mm` | `1.0` | How far the lap joint crosses the seam plane (in `Y`). |
| `lap_step_height_mm` | `1.5` | Radial step height of the seam rabbet. Auto-clamped so it cannot exceed wall thickness minus 0.2 mm. |
| `lap_clearance_mm` | `0.2` | Extra clearance added to the female recess so halves slip together. |
| `adhesive_gap_mm` | `0.10` | Explicit glue-line thickness baked into the groove. |
| `reg_lip_height_mm` | `0.8` | Tongue height (radial) for the registration tongue-and-groove. |
| `reg_lip_width_mm` | `1.2` | Tongue width across the seam normal. |
| `reg_clearance_mm` | `0.08` | Clearance between tongue and groove (resin-print friendly). |
| `relief_enabled` | `true` | Cut small relief pockets inside the groove so glue can escape. |
| `relief_depth_mm` | `0.3` | Radial depth of each relief pocket. |
| `relief_width_mm` | `0.5` | Width of each relief pocket across the seam normal. |
| `alignment_notch_enabled` | `true` | Add a key-and-slot tab that prevents axial sliding. |
| `alignment_notch_width_mm` | `3.0` | Axial length (along `Z`) of the alignment tab. |
| `alignment_notch_depth_mm` | `0.8` | Protrusion depth of the tab into the mating half (`Y`). |
| `alignment_notch_clearance_mm` | `0.1` | Clearance applied to the slot so the tab seats easily. |

The build also reads `tube_settings.outer_radius` from the active tube model
(see [Tube models](tube-models.md)) so the clamp ID always matches whichever
profile the rest of the sweep is using.

### Invocation

```bash
render-part part_configs/hang_clamp.yaml
```

The config must include `part_type: hang_clamp`. Standard CLI flags (`--server`,
`--viewer`, `--optimize` / `--auto-orient`, `--optimize-report-dir`, `-v`)
work — see the [CLI reference](cli-reference.md).

Use it from Python when assembling a larger model:

```python
from led_knots.core.config import load_config
from led_knots.parts.hang_clamp import (
    build_tube_clamp_parts,
    location_from_point_tangent,
)

config = load_config(args=...)  # or construct Config with merged YAML
parts = build_tube_clamp_parts(config)

# Each half is a cq.Solid; or get a cq.Assembly:
assembly = parts.to_assembly(name="Hang Clamp")

# Pose the clamp at a sampled point along your knot path:
loc = location_from_point_tangent((0.0, 0.0, 50.0), (0.0, 0.0, 1.0))
positioned = assembly.moved(loc)  # or apply loc to each half individually
```

`build_tube_clamp_parts` returns a frozen
[`TubeClampParts`](../src/led_knots/parts/hang_clamp.py#L17) dataclass with
`half_with_hole` and `half_plain` solids. The `.to_assembly()` helper places
both halves in their native positions, so the preview shows the clamp as it
would sit when glued.

## Planet spacer

A thick washer-like ring intended as a planet-style spacer between hardware
plates (e.g., setting standoff distance for a planet bracket holding the
knot). It has rounded top and bottom edges so it looks finished without
needing post-processing.

The implementation lives in
[src/led_knots/parts/planet_spacer.py](../src/led_knots/parts/planet_spacer.py).

### Geometry

- Local `+Z` is the spacer axis. The solid is centred about `Z=0` for nicer
  previews and exports.
- The body is an extruded annulus (outer circle minus inner hole), with a
  fillet applied to the top and bottom circular edges.
- All dimensions are accepted in **inches** and converted internally
  (`MM_PER_IN = 25.4`); the fillet alone is in millimetres.
- If the requested fillet fails (e.g., the radius would exceed the wall), the
  build logs a warning and retries with a smaller fillet
  (`min(0.5, fillet_mm * 0.66)`) before giving up silently.

### Parameters

`build_planet_spacer` takes its dimensions as function arguments rather than
from `config.yaml`. Defaults reflect the part as currently shipped.

| Argument | Default | Units | Meaning |
|---|---|---|---|
| `outer_diameter_in` | `1.75` | inches | OD of the spacer ring. |
| `height_in` | `0.25` | inches | Axial thickness. |
| `hole_diameter_in` | `0.25` | inches | ID of the through-hole. Must be `> 0` and strictly less than the outer diameter. |
| `fillet_mm` | `0.75` | mm | Fillet radius applied to the top and bottom circular edges. Set to `0` to skip the fillet. |

The constructor validates inputs and raises `ValueError` if radii are
non-positive, if `hole_diameter_in >= outer_diameter_in`, or if `height_in <= 0`.

### Invocation

```bash
render-part part_configs/planet_spacer.yaml
```

The config must include `part_type: planet_spacer`. Standard CLI flags apply.

Import it to build custom-sized variants:

```python
from led_knots.core import render_part
from led_knots.parts.planet_spacer import build_planet_spacer

spacer = build_planet_spacer(
    outer_diameter_in=2.0,
    height_in=0.375,
    hole_diameter_in=0.196,  # #10 clearance
    fillet_mm=0.5,
)
render_part(spacer, config)
```

There is no `planet_spacer.*` block in `config.yaml`; if you want the spacer
parameters to live in config, add a section and pass them through (see the
cookbook below for the wiring pattern).

## Cookbook: add a new part module

Use this recipe when you have a new accessory (mount, end cap, bracket, ...)
that fits the existing build-and-render pattern.

1. **Create the module.** Add a new file under
   [src/led_knots/parts/](../src/led_knots/parts/), e.g.
   `src/led_knots/parts/my_bracket.py`. Mirror the layout of an existing part:

   ```python
   from __future__ import annotations

   import logging
   import cadquery as cq
   from cadquery.func import *  # functional API style used across the repo

   from led_knots.core import render_part
   from led_knots.core.config import Config

   logger = logging.getLogger(__name__)

   def build_my_bracket(config: Config) -> cq.Solid:
       ...

   def build(config: Config) -> None:
       part = build_my_bracket(config)
       render_part(part, config)
   ```

2. **Add a config file** under `part_configs/` with `part_type` set to your module stem:

   ```yaml
   part_type: my_bracket
   rendering:
     name: my_bracket
   ```

   Run with `render-part part_configs/my_bracket.yaml`. No `pyproject.toml`
   entry is needed — parts are discovered by filename.

3. **Wire new config keys into `config.yaml`.** If the part has tunable
   parameters that should live in config rather than as function arguments,
   add a top-level block (e.g., `my_bracket:`) to
   [config.yaml](../config.yaml). Read it inside `build_my_bracket` via the
   same `config.<section>.<key>` attribute access used by
   [hang_clamp.py](../src/led_knots/parts/hang_clamp.py#L72). Document every
   key with a `# mm` (or equivalent) inline comment and a default that
   actually prints. Cross-reference the new section in
   [Configuration reference](configuration.md).

4. **Add tests and a preview.** Add a `tests/test_my_bracket.py` exercising
   the build function with representative parameters and asserting geometric
   invariants you actually care about (volume bounds, hole exists, halves
   fit together). If the part is visually meaningful, generate a preview
   image and reference it from [screenshots.md](screenshots.md).

## Do's and don'ts

**Do**

- Reuse core helpers rather than copy-pasting. Expose `build(config)` and call
  `render_part` from [src/led_knots/core/](../src/led_knots/core/) — `render-part`
  dispatches to your module via the file-based registry.
- Use the path-frame helpers from
  [src/led_knots/core/path_frames.py](../src/led_knots/core/path_frames.py)
  (and the local `location_from_point_tangent` pattern shown in
  [hang_clamp.py](../src/led_knots/parts/hang_clamp.py#L41)) when placing
  parts along a sampled knot path. Don't invent your own frame logic.
- Match the functional CadQuery import style (`from cadquery.func import *`)
  that every part in this package already uses, so booleans look the same
  across the codebase.
- Call `clean(...)` on solids that have been through repeated booleans before
  returning them, as
  [hang_clamp.py](../src/led_knots/parts/hang_clamp.py#L251) does — it
  reduces residual edges and makes downstream slicing/exporting happier.
- Validate inputs early and raise `ValueError` with a clear message, as
  [planet_spacer.py](../src/led_knots/parts/planet_spacer.py#L33) does.

**Don't**

- Don't bake printer-specific dimensions (build volume, clearances, layer
  height) into a part. Go through `config.yaml` — the `output_bounds`,
  `max_print_bounds`, and `clamp.*` blocks already capture printer-side
  tolerances; extend them rather than hard-coding new ones in part code.
- Don't reach across packages by importing from `led_knots.knots.*` inside a
  part. Parts should depend on `led_knots.core.*` (and CadQuery) only; that
  keeps the dependency graph one-directional and lets knot scripts compose
  parts without circular imports.
- Don't duplicate the tube outer radius in a parts config block — read it
  from `tube_settings.outer_radius` so the same config drives both the knot
  sweep and any clamps or collars riding on it.
- Don't skip the `main()` + `if __name__ == "__main__":` wrapper if your part
  is runnable; the project's CLI conventions
  (see [CLI reference](cli-reference.md)) rely on it.
