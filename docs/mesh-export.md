# Mesh export (simulation OBJ)

The `--output-mesh` flag writes an OBJ tuned for physics simulators such as
[Genesis](https://genesis-embodied-ai.github.io/). It runs as a separate
output stage of the render pipeline ([src/led_knots/core/render_pipeline.py](../src/led_knots/core/render_pipeline.py))
and is configured by the `mesh.*` block of [config.yaml](../config.yaml).

This page covers the differences between `--export` and `--output-mesh`, the
pipeline that produces the OBJ, every `mesh.*` config key, and a
copy-pasteable recipe for producing a Genesis-ready mesh.

See also: [CLI reference](cli-reference.md), [Configuration reference](configuration.md),
[Rendering and preview](rendering-and-preview.md).

## `--export` vs `--output-mesh`

The repo has two file-output flags that look similar but serve different
audiences:

| Aspect | `--export FILEPATH` | `--output-mesh FILEPATH` |
| --- | --- | --- |
| Intended consumer | Slicers, CAD tools, web viewers | Physics simulators (e.g. Genesis) |
| Writer | CadQuery exporters (and trimesh for GLTF) | trimesh |
| Supported extensions | `.stl`, `.step` / `.stp`, `.3mf`, `.glb`, `.gltf` | `.obj` only |
| Units | Millimeters (CadQuery native) | Optionally scaled to meters via `mesh.unit_scale_mm_to_m` |
| Cleanup | None beyond CadQuery tessellation | Degenerate-face removal, unreferenced-vertex pruning, vertex merge |
| Watertight check | No | Optional gate via `mesh.watertight_required` |
| Decimation | No | Optional `mesh.target_face_count` via quadratic decimation |
| Configured by | `export.*` block | `mesh.*` block |
| Code path | `PartArtifacts._export_*` in [render_pipeline.py](../src/led_knots/core/render_pipeline.py) | [`_maybe_export_mesh_from_glb`](../src/led_knots/core/render_pipeline.py#L170) |

The two flags are independent. Setting both writes a CAD file *and* an OBJ
in the same run, sharing the GLB intermediate. The CLI definitions live in
[src/led_knots/core/utils.py:47-86](../src/led_knots/core/utils.py#L47).

## Pipeline

`--output-mesh` always goes through GLB before producing the OBJ:

```
CadQuery solid / assembly
        │
        │  STL tessellation  (cq.exporters.export → STL)
        │  or GLB tessellation (assembly.export(exportType="GLB"))
        ▼
GLB bytes (in memory)
        │
        │  trimesh.load(..., file_type="glb")
        │  Scene.dump(concatenate=True)  → single Trimesh
        ▼
trimesh.Trimesh
        │
        │  apply_scale(0.001)              # if unit_scale_mm_to_m
        │  remove_degenerate_faces()
        │  remove_unreferenced_vertices()
        │  merge_vertices()
        │  watertight check                # if watertight_required
        │  simplify_quadratic_decimation() # if target_face_count
        ▼
mesh.export(path, file_type="obj")
```

Why GLB as the intermediate, and not STL directly? The render pipeline
already builds GLB bytes for the in-browser viewer and PNG previews
(see [RenderPlan.from_config](../src/led_knots/core/render_pipeline.py#L338)),
so the mesh export reuses those bytes when they exist instead of
re-tessellating the OCCT solid. For solids that have not produced GLB yet,
[`_solid_to_glb_bytes`](../src/led_knots/core/render_pipeline.py#L255) goes
STL → trimesh → GLB; for assemblies,
[`_assembly_to_glb_bytes`](../src/led_knots/core/render_pipeline.py#L234)
uses CadQuery's native `exportType="GLB"`. Either way, the OBJ stage starts
from a GLB stream so the multi-part fuse logic only has to live in one place.

The dispatch happens in [`PartArtifacts.emit_mesh_obj`](../src/led_knots/core/render_pipeline.py#L701),
which is only called when `RenderPlan.want_mesh_obj` is `True` — i.e. when
`--output-mesh` was passed.

## Configuration

All keys live under the top-level `mesh:` block in `config.yaml` and are
parsed by [`MeshSettings`](../src/led_knots/core/config.py#L467). Defaults
shown are the values shipped in [config.yaml](../config.yaml#L217).

### `mesh.unit_scale_mm_to_m`

- Type: `bool`
- Default: `true` in `config.yaml`; the `MeshSettings` constructor also
  defaults to `True` when the key is missing.
- Behavior: when `true`, the pipeline calls `mesh.apply_scale(0.001)` after
  loading the GLB, converting millimeter geometry to meters
  ([render_pipeline.py:195-196](../src/led_knots/core/render_pipeline.py#L195)).

CadQuery models the knots in millimeters. Genesis, MuJoCo, Bullet, and most
other physics engines expect SI units (meters). Leave this `true` for
simulation use. Set it `false` only if your downstream tool already expects
millimeters — note that the OBJ format itself is unit-less, so the scale you
write is the scale your simulator will see.

### `mesh.target_face_count`

- Type: `int | null`
- Default: `null` (no decimation).
- Behavior: when set to a positive integer `N`, the pipeline compares the
  current face count to `N`; if the mesh has more than `N` faces, it calls
  `trimesh.Trimesh.simplify_quadratic_decimation(N)` to aim for roughly that
  triangle budget ([render_pipeline.py:209-219](../src/led_knots/core/render_pipeline.py#L209)).
- Failure mode: if decimation raises (e.g. the underlying `fast-simplification`
  / `open3d` backend is missing), the pipeline logs a warning and exports the
  un-decimated mesh — the export does *not* abort.
- No-op cases: `null`, `0`, or any value greater than or equal to the current
  face count.

Quadratic edge collapse is approximate; the resulting face count is usually
within a few percent of the target, not exact. For Genesis, a budget of
20k–50k faces per knot is typically enough for collision; finer meshes mainly
cost CPU during broadphase.

### `mesh.watertight_required`

- Type: `bool`
- Default: `false` in `config.yaml`; the `MeshSettings` constructor defaults
  to `True` when the key is missing — so omitting the key behaves *stricter*
  than the shipped config.
- Check: after cleanup but before decimation, the pipeline tests
  `mesh.is_watertight` ([render_pipeline.py:205-207](../src/led_knots/core/render_pipeline.py#L205)).
- Failure mode: if `true` and the mesh is not watertight, the process logs
  `"Mesh export aborted: generated mesh is not watertight."` at ERROR level
  and exits with status `2`. No OBJ is written.

For rigid-body simulation a non-watertight mesh is usually fine. For soft
bodies, signed-distance-field collision, or any code that needs a closed
volume, flip this to `true` so a bad tessellation surfaces immediately
instead of silently producing a leaky mesh.

## Recipe: produce a Genesis-ready mesh

The following produces an OBJ in meters, decimated to roughly 30k faces,
with a watertight guarantee:

1. Edit `config.yaml` (or a `config.local.yaml` override — see
   [Configuration reference](configuration.md)) so the `mesh:` block reads:

   ```yaml
   mesh:
     unit_scale_mm_to_m: true
     target_face_count: 30000
     watertight_required: true
   ```

2. Run a knot module with `--output-mesh`:

   ```bash
   python -m led_knots.knots.trefoil --output-mesh out/trefoil.obj
   ```

3. On success the log line is `Exported mesh OBJ to out/trefoil.obj`. The
   file is a standard Wavefront OBJ; load it in Genesis with the asset
   loader of your choice (e.g. `genesis.morphs.Mesh(file="out/trefoil.obj")`).

You can combine `--output-mesh` with a regular CAD export and a preview PNG
in the same invocation — the GLB intermediate is built once and reused:

```bash
python -m led_knots.knots.figure_8 \
  --export out/figure_8.stl \
  --output-mesh out/figure_8.obj \
  --preview out/figure_8.png
```

If you want to inspect the OBJ before handing it to a simulator, the repo
ships [scripts/inspect_mesh.py](../scripts/inspect_mesh.py).

## Limitations

- **Only `.obj` is supported.** Any other extension passed to `--output-mesh`
  is rejected before the GLB is loaded. The error is logged as
  `Mesh export only supports .obj for now (got <ext>).` and the process
  exits with status `2`
  ([render_pipeline.py:177-180](../src/led_knots/core/render_pipeline.py#L177)).
  For other mesh-style formats (`.glb`, `.gltf`, `.stl`, `.3mf`) use
  `--export` instead — those go through CadQuery's exporters and do not run
  the trimesh cleanup, scaling, or watertight check.
- **No per-part export.** `--output-mesh` always emits a single fused OBJ
  built from `Scene.dump(concatenate=True)`. The `--export-parts` /
  `--export-parts-dir` flags only apply to `--export`.
- **Decimation is best-effort.** A failure in
  `simplify_quadratic_decimation` is logged at WARNING and the original mesh
  is exported anyway, so a successful exit does not guarantee that
  `target_face_count` was hit.
- **Unit scaling is unconditional.** When `unit_scale_mm_to_m` is `true`
  every coordinate is multiplied by `0.001`, including any geometry that was
  already authored in meters. There is no per-part override.
