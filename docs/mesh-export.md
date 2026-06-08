# Mesh export (simulation OBJ and CAD formats)

Every knot run writes a **render bundle** under `rendering.output_dir` (default
`renders/`). Export formats are configured as jobs in `rendering.exports` in
[config.yaml](../config.yaml).

See also: [CLI reference](cli-reference.md), [Configuration reference](configuration.md),
[Rendering and preview](rendering-and-preview.md).

## Render bundle exports

Each enabled job in `rendering.exports` writes one file inside a timestamped
folder: `renders/{slugified-run-name}_{YYYYMMDD-HHMMSS}/`.

| format | default filename | Writer | Notes |
| --- | --- | --- | --- |
| `stl` | `{name}.stl` | CadQuery STL export | `stl_ascii` per job |
| `step` | `{name}.step` | CadQuery STEP export | Use `{name}.stp` in filename if desired |
| `3mf` | `{name}.3mf` | STL tessellation | |
| `glb` | `{name}.glb` | CadQuery / trimesh GLB | |
| `gltf` | `{name}.gltf` | GLB → trimesh → GLTF | |
| `obj` | `{name}.obj` | GLB → trimesh cleanup → OBJ | Simulation mesh (see below) |
| `preview` | `{name}.png` | trimesh + pyrender | Multiple preview jobs allowed |
| `config` | `{name}.yaml` | Full merged config snapshot (includes `knot_type` / `part_type`) | Re-runnable via `render-knot` / `render-part` |
| `stats` | `{name}.csv` | Render run statistics | Space-aligned CSV columns |

Shared tessellation tolerances: `rendering.tolerance`, `rendering.angular_tolerance`.

Disable formats for one run: `--disable-export obj,stats` (disables all jobs of that format).

## Simulation OBJ (`format: obj`)

The OBJ export uses a GLB intermediate (same pipeline as before):

```
CadQuery solid / assembly
        → GLB bytes
        → trimesh load + cleanup
        → optional decimation / watertight check
        → OBJ file
```

Job-specific keys on the `obj` export entry:

| Key | Default | Behavior |
| --- | --- | --- |
| `unit_scale_mm_to_m` | `true` | `mesh.apply_scale(0.001)` after GLB load |
| `target_face_count` | `null` | Quadratic decimation when face count exceeds target |
| `watertight_required` | `false` | Exit code 2 if mesh is not watertight |

Only `.obj` extensions are accepted for `format: obj` jobs.

## Recipe: Genesis-ready mesh

Enable the OBJ export job in `config.yaml` or an overlay:

```yaml
rendering:
  exports:
    - format: obj
      enabled: true
      filename: "{name}.obj"
      unit_scale_mm_to_m: true
      target_face_count: 30000
      watertight_required: true
```

Then run the knot (no separate mesh flag):

```bash
render-knot knot_configs/my_trefoil.yaml
# → renders/trefoil-knot_YYYYMMDD-HHMMSS/trefoil-knot_YYYYMMDD-HHMMSS.obj
```

## Multiple exports and overlays

Add multiple jobs of the same format with distinct `filename` templates. When
merging config layers (`config.local.yaml`, user config file), entries
match on the `filename` template string and deep-merge.

If two jobs resolve to the same output path, the run fails with
`DuplicateExportFilenameError`.

If an enabled export needs another format (e.g. preview needs GLB), that
dependency file is still written even when the dependency format is disabled in
config.

## Limitations

- OBJ export always emits a single fused mesh (`Scene.dump(concatenate=True)`).
- Decimation is best-effort; failures log a warning and export the original mesh.
- Inspect OBJ output with [scripts/inspect_mesh.py](../scripts/inspect_mesh.py).
