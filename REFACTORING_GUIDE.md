# Refactoring Guide: Migrating Knot Modules to New Configuration System

This document describes the refactoring pattern applied to `rod.py` that should be replicated across all other knot modules.

## Overview

The refactoring consolidates configuration management, simplifies the rendering pipeline, and removes boilerplate code by:
1. Using a centralized configuration system (`get_config()`)
2. Replacing manual face creation, sweeping, and rendering with a single `draw_part()` function
3. Removing hardcoded parameters in favor of config values
4. Simplifying imports and removing unnecessary code

## Before and After Comparison

### Before (Old Pattern)
```python
import logging
import cadquery as cq
from cadquery.func import *

from led_knots.core import parse_args, render_part
from led_knots.core import create_led_circle_face

def main():
    """Generate and render the rod knot."""
    logging.basicConfig(level=logging.DEBUG)

    tube_radius = 15
    height = 100.0
    wall_thickness = 1.0
    oval_wall_thickness = 2.0

    args = parse_args(description="Create and render a rod knot")

    path = spline([(0, 0, 0), (0, 0, height)], tgts=[(0, 0, 1), (0, 0, 1)])

    face_shape = create_led_circle_face(
        tube_radius, 
        wall_thickness=wall_thickness,
        oval_wall_thickness=oval_wall_thickness,
        orient_to_path=path
    )

    result = sweep(face_shape, path)

    render_part(result, "Rod Knot", args)

if __name__ == "__main__":
    main()
```

### After (New Pattern)
```python
from cadquery.func import spline
from led_knots.core import draw_part, get_config

# Load configuration
config = get_config(
    name="Rod Knot",
    description="Create and render a rod knot (straight vertical pipe)"
)

path = spline(
    [(0, 0, 0), (0, 0, config.output_bounds.height)])

# Create, sweep, and render the part
draw_part(path, config)
```

## Step-by-Step Refactoring Instructions

### 1. Update Imports

**Remove:**
- `import logging`
- `import cadquery as cq` (unless specifically needed for other CadQuery operations)
- `from cadquery.func import *` (replace with specific imports like `spline`, `sweep`, etc.)
- `from led_knots.core import parse_args, render_part`
- `from led_knots.core import create_led_circle_face`

**Add:**
- `from cadquery.func import spline` (or other specific functions needed)
- `from led_knots.core import draw_part, get_config`

### 2. Remove Function Wrapper (if present)

**Remove:**
- The `main()` function wrapper
- The `if __name__ == "__main__":` block
- `logging.basicConfig()` calls

**Note:** The code now runs at module level, which is simpler for these scripts.

### 3. Replace Hardcoded Parameters with Config

**Before:**
```python
tube_radius = 15
height = 100.0
width = 175.0
wall_thickness = 1.0
oval_wall_thickness = 2.0
```

**After:**
```python
config = get_config(
    name="Knot Name",
    description="Create and render a [knot name]"
)

# Use config values:
# - config.output_bounds.height (instead of height)
# - config.output_bounds.width (instead of width)
# - config.tube_settings.outer_radius (instead of tube_radius)
# - config.tube_settings.wall_thickness (instead of wall_thickness)
# - config.tube_settings.oval_wall_thickness (instead of oval_wall_thickness)
```

### 4. Replace Manual Face Creation, Sweep, and Render

**Before:**
```python
args = parse_args(description="...")

faces = create_led_circle_face(
    tube_radius, 
    wall_thickness=wall_thickness, 
    oval_wall_thickness=oval_wall_thickness, 
    orient_to_path=path,
    rotation_z=90  # if needed
)

result = sweep(faces, path)

render_part(result, "Knot Name", args)
```

**After:**
```python
# Create, sweep, and render the part
draw_part(path, config, rotation_z=90)  # rotation_z only if needed
```

**Key Points:**
- `draw_part()` automatically handles `create_led_circle_face()`, `sweep()`, and `render_part()`
- `orient_to_path` is automatically set to the path parameter - don't pass it
- Additional parameters like `rotation_z` can still be passed as kwargs
- The name comes from `config.name` (set in `get_config()`), not passed to `render_part()`

### 5. Update Path Creation to Use Config Values

**Before:**
```python
path = spline([(0, 0, 0), (0, 0, height)], tgts=[(0, 0, 1), (0, 0, 1)])
```

**After:**
```python
path = spline(
    [(0, 0, 0), (0, 0, config.output_bounds.height)], 
    tgts=[(0, 0, 1), (0, 0, 1)])
```

### 6. Simplify Docstring

**Before:**
```python
"""
Rod knot creation using CadQuery.

Creates a straight vertical pipe by sweeping an LED circle cross-section
along a vertical path. The path construction is the focus here; the cross-section
geometry is handled by the led_circle module.
"""
```

**After:**
```python
"""
Rod knot creation using CadQuery.

Creates a straight vertical pipe by sweeping an LED circle cross-section
along a vertical path. The path construction is the focus here;
"""
```

Remove references to implementation details like "the cross-section geometry is handled by the led_circle module" since that's now abstracted away.

## Special Cases

### Knots with Additional Parameters

If a knot needs additional parameters for `create_led_circle_face()` (like `rotation_z`), pass them as kwargs to `draw_part()`:

```python
draw_part(path, config, rotation_z=90)
```

### Knots with Auxiliary Spine (e.g., twisted_rod)

Knots that use an auxiliary spine for variable twist may need special handling. The `draw_part()` function currently doesn't support auxiliary spines - these may need to remain as manual implementations or `draw_part()` may need to be extended.

### Knots Using PyKnotID

Knots that generate paths using pyknotid (like `trefoil.py`, `figure_8.py`) should:
1. Keep the pyknotid path generation logic
2. Use `config.output_bounds` for scaling dimensions
3. Replace the face creation/sweep/render pattern with `draw_part()`

Example:
```python
# Generate path using pyknotid
k = make_trefoil(num_points=50)
knot_coords = scale_pyknot_points(
    k.points, 
    width=config.output_bounds.width, 
    height=config.output_bounds.width, 
    length=config.output_bounds.height
)
knot_points = [(float(p[0]), float(p[1]), float(p[2])) for p in knot_coords]
path = spline(knot_points[:-1])

# Create, sweep, and render
draw_part(path, config, rotation_z=90)
```

## Summary of Changes

1. **Imports**: Simplified to only what's needed (`spline`, `draw_part`, `get_config`)
2. **Configuration**: Replaced hardcoded values with `get_config()` call
3. **Rendering**: Replaced 3-step process (create face → sweep → render) with single `draw_part()` call
4. **Code Structure**: Removed function wrapper, runs at module level
5. **Parameters**: All tube settings come from config, path dimensions use `config.output_bounds`

## Benefits

- **Less boilerplate**: Reduced from ~30 lines to ~20 lines
- **Consistency**: All knots use the same configuration system
- **Maintainability**: Changes to rendering logic happen in one place
- **Flexibility**: Easy to override config values via `config.local.yaml`
- **Clarity**: Focus on path creation, not implementation details
