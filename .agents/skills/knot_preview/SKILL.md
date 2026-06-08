---
name: Knot Preview
description: >
  Run render-knot with uv run --no-cache to generate static PNG previews via
  the render bundle, then load those previews into context to visually verify
  knot geometry (knot type, crossings, strand thickness). Use when you need to
  preview or validate a specific knot (e.g., trefoil, rope, braided tube) as
  a static image.
---

# Knot Preview Skill

Use this skill to generate and verify static image previews for individual knots.

The core workflow:

- Create or choose a knot config YAML with `knot_type` set.
- Run `uv run --no-cache render-knot <config.yaml>`.
- Read the preview PNG from the latest folder under `renders/`.
- Load that PNG into context and visually verify the knot.

## Quickstart

1. **Create or identify a knot config**
   - The config must include `knot_type` matching a module under `src/led_knots/knots/`.
   - Example: `knot_configs/test_short_rod_led_tube.yaml` with `knot_type: rod`.

2. **Run render-knot**

   ```bash
   uv run --no-cache render-knot knot_configs/test_short_rod_led_tube.yaml
   ```

   For a one-off preview of another knot type, write a minimal config:

   ```yaml
   knot_type: trefoil
   rendering:
     name: trefoil
   ```

3. **Load the preview**
   - Find the newest bundle under `renders/`.
   - Load `{renders/<bundle>/<name>.png}` into context.

4. **Visual verification**
   - Topology matches intended knot type.
   - Crossings and strand thickness look correct.
   - No obvious clipping or self-intersection artifacts.
