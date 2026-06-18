# Tube models and cross-section faces

A *tube model* is the thing that turns a centerline `Wire` into a 3D solid (or
compound) of tube geometry. It is the second half of the knot pipeline: the
path code in [src/led_knots/core/path_utils.py](../src/led_knots/core/path_utils.py)
produces a centerline, and a tube model wraps that centerline in printable
material.

This doc covers the `TubeModel` protocol, the registry that maps a `face_type`
string to a concrete implementation, every built-in model, the
`SweptFaceModel` adapter used by all the simple cross-sections, and two
cookbooks for extending the system.

See also:

- [Configuration reference](configuration.md) — the `face_type` and `face_settings.*` keys driven by these models.
- [Architecture overview](architecture.md) — where tube models sit in the build pipeline.

## What is a tube model

A `TubeModel` is a runtime-checkable `Protocol` with a single method, defined
in [src/led_knots/core/tube_models/_base.py](../src/led_knots/core/tube_models/_base.py):

```python
@runtime_checkable
class TubeModel(Protocol):
    """
    A tube model takes a centerline path and produces a 3D result.

    The contract matches what `build_tube_from_path` used to return: either a
    single `Solid`/`Compound` (one swept tube) or a `Compound` of multiple
    sub-solids (e.g. core + N braided strands).
    """

    def build(
        self,
        *,
        path,
        aux,
        config: Any,
        face_kwargs: Optional[Dict[str, Any]] = None,
    ) -> Union[cq.Solid, cq.Compound]: ...
```

All arguments are keyword-only:

- `path` — a CadQuery `Wire` representing the centerline. Models that need
  arc-length sampling pass it through `sample_path_frames` /
  `frame_at_arc_length` from [path_frames.py](../src/led_knots/core/path_frames.py).
- `aux` — the *auxiliary* path used by `cadquery.func.sweep` to control twist.
  Pass-through for simple swept models; the braided rope ignores it because it
  computes its own helical phase.
- `config` — the active `KnotConfig`. Tube models read
  `config.tube_settings.*` (active face settings, including the per-model
  sub-dict like `config.tube_settings.pyramid_studded`).
- `face_kwargs` — optional dict of extra keyword overrides forwarded to the
  face builder. Composite models that wrap a `SweptFaceModel` thread this
  through unchanged.

The return value must be a `cq.Solid` (one body) or a `cq.Compound` (multiple
bodies that downstream code will tessellate and slice together). Returning a
`Workplane` will break the consumers in
[utils.py:176](../src/led_knots/core/utils.py#L176) and
[render_pipeline.py](../src/led_knots/core/render_pipeline.py).

The protocol is `@runtime_checkable`, so `isinstance(obj, TubeModel)` works
for sanity checks but only verifies that `build` exists, not that the
signature is correct.

## The registry

Tube models are looked up by string. The registry lives in
[src/led_knots/core/tube_models/\_\_init\_\_.py](../src/led_knots/core/tube_models/__init__.py)
and is a plain module-level `Dict[str, TubeModel]`:

```python
_REGISTRY: Dict[str, TubeModel] = {
    "led_circle": SweptFaceModel("led_circle"),
    "led_circle_tube": SweptFaceModel("led_circle_tube"),
    "solid_circle": SweptFaceModel("solid_circle"),
    "square": SweptFaceModel("square"),
}
# ...later, after their modules import cleanly:
_REGISTRY["pyramid_studded"] = PyramidStuddedModel()
_REGISTRY["braided_rope"] = BraidedRopeModel()
```

The public API is three functions plus the `TubeModel` re-export:

| Symbol | Behavior |
| --- | --- |
| `get_tube_model(face_type)` | Returns the registered model for `face_type`. Raises `ValueError` listing the registered keys when the type is unknown. Called once per build from [utils.py:185](../src/led_knots/core/utils.py#L185). |
| `register_tube_model(face_type, model)` | Inserts or replaces an entry. Useful from a downstream script that wants to add a custom model without editing the package. |
| `registered_face_types()` | Returns a sorted `tuple` of the currently registered keys — handy for CLIs, tests, and error messages. |

Built-in registry contents:

| `face_type` | Implementation | One-line summary |
| --- | --- | --- |
| `led_circle` | `SweptFaceModel("led_circle")` | Annular outer ring + LED-strip oval cavity + two connectors, swept along the path. |
| `led_circle_tube` | `SweptFaceModel("led_circle_tube")` | Annular outer ring + concentric inner tube (for wires) + two radial connectors. |
| `solid_circle` | `SweptFaceModel("solid_circle")` | Plain filled disc, swept. The dumb base case used by other models. |
| `square` | `SweptFaceModel("square")` | Plain filled square, swept. |
| `pyramid_studded` | `PyramidStuddedModel()` | A base swept tube with discrete 4-sided pyramidal solids placed on its outer surface. |
| `braided_rope` | `BraidedRopeModel()` | Smooth core loft + 2N interlacing lenticular helical strands as a single `Compound`. |

The set of legal `face_type` strings is **also** validated against
`VALID_FACE_TYPES` in [config.py:19](../src/led_knots/core/config.py#L19) when
the config loads — keep these two lists in sync if you add a built-in.

## Built-in tube models

Each built-in reads its parameters out of the resolved
`face_settings.<face_type>` block from [config.yaml](../config.yaml). Inheritance
between blocks is handled by `resolve_face_settings` in
[config.py](../src/led_knots/core/config.py) before the model ever sees the data.

### `led_circle`

The "real" LED-strip cross-section. Implemented by `create_led_circle_face`
in [led_circle.py:223](../src/led_knots/core/led_circle.py#L223):

- An **outer annular ring** of `outer_diameter` with `wall_thickness`.
- A **center oval cavity** sized to leave at least `oval_wall_thickness` around
  a fixed-size inner rectangle (`rect_inner_x` by `rect_inner_y`) where the
  LED strip lives.
- **Two connectors** of width `connector_width` joining the inner ring to the
  oval, top and bottom, so the wall is one continuous piece for SLA printing.

Config keys (`face_settings.led_circle`):

| Key | Meaning | Example default |
| --- | --- | --- |
| `outer_diameter` | Tube OD in mm. | `30` |
| `wall_thickness` | Outer-ring wall thickness in mm. | `4.0` |
| `rect_inner_x` | LED-strip cavity X in mm. **Fixed**, never scaled. | `4.6` |
| `rect_inner_y` | LED-strip cavity Y in mm. **Fixed**, never scaled. | `11.0` |
| `oval_wall_thickness` | Wall around the oval cavity (also used as `min_oval_wall_thickness`) in mm. | `0.5` |
| `connector_width` | Width of the two oval-to-ring connectors in mm. | `0.5` |

Pick this when you actually want to thread an addressable LED strip through
the knot.

### `led_circle_tube`

Same outer ring as `led_circle`, but the LED-strip cavity is replaced by a
concentric circular **inner tube** suitable for routing bundled wires.
Implemented by `create_led_circle_tube_face` in
[led_circle.py:514](../src/led_knots/core/led_circle.py#L514).

Config keys (`face_settings.led_circle_tube`):

| Key | Meaning | Example default |
| --- | --- | --- |
| `outer_diameter` | Tube OD in mm. | `30` |
| `wall_thickness` | Outer-ring wall thickness in mm. | `4.0` |
| `inner_tube_diameter` | ID of the central wire tube in mm. | `10` |
| `inner_tube_wall_thickness` | Wall around the inner tube in mm. | `0.5` |
| `connector_width` | Width of the two radial connectors in mm. | `0.5` |

Validation in `create_led_circle_tube_face` rejects geometries where the
center tube OD does not fit inside the outer ring's inner radius — you must
leave a positive gap for the connectors.

Pick this for the default LED-knot use case where wires (not a strip) run
through the core.

### `solid_circle`

A simple filled disc. Implemented by `create_solid_circle_face` in
[led_circle.py:604](../src/led_knots/core/led_circle.py#L604).

It reuses the `to_led_circle_face_kwargs` builder, so the signature accepts
all of `led_circle`'s keys, but **only `outer_radius` is honored** — every
other parameter (`wall_thickness`, `rect_inner_*`, `oval_wall_thickness`,
`connector_width`) is silently ignored. The stock config inherits from
`led_circle` and only overrides `outer_diameter`.

Pick this when you want a plain solid tube — most commonly as the base
geometry under `pyramid_studded` or `braided_rope`.

### `square`

A filled square of side length `2 * outer_radius`, swept along the path.
Implemented by `create_square_face` in
[led_circle.py:660](../src/led_knots/core/led_circle.py#L660).

Special config: this is the only built-in that uses `outer_width` (the square's
side length in mm) instead of `outer_diameter` in `face_settings`. The
`outer_radius` property in `TubeSettings`
([config.py:313](../src/led_knots/core/config.py#L313)) returns
`outer_width / 2` for this face type.

| Key | Meaning | Example default |
| --- | --- | --- |
| `outer_width` | Square side length in mm. | `30` |

Pick this for stress tests, printability checks, or non-circular designs.

### `pyramid_studded`

A base swept tube plus discrete 4-sided pyramidal **solids** anchored on the
outer surface. Implemented by `PyramidStuddedModel` in
[tube_models/pyramid_studded.py](../src/led_knots/core/tube_models/pyramid_studded.py).

What it builds:

1. A base tube via `SweptFaceModel(base_face_type)`, typically `solid_circle`
   or `led_circle`.
2. Pyramid sites laid out in rows along the centerline (axial spacing
   `axial_pitch`, skipping `axial_margin` from each end). Optional half-pitch
   `stagger_rows` rotates every other row.
3. For each site, a real 4-sided pyramid (`_make_pyramid_solid`) is
   constructed by stitching its 5 faces into a `Shell` and capped into a
   `Solid`.
4. The base tube and all pyramids are returned as one `Compound` — **no
   boolean union is performed**. Downstream tessellation and slicing merge the
   geometry.

Config keys (`face_settings.pyramid_studded.pyramid_studded`):

| Key | Meaning | Default in code |
| --- | --- | --- |
| `base_face_type` | Which smooth face the studs sit on. Anything but `pyramid_studded` itself. | `solid_circle` |
| `base_size` | Square pyramid base edge length in mm. | `2.0` |
| `height` | Apex distance above the outer surface in mm. | `2.5` |
| `axial_pitch` | Row-to-row distance along the path in mm. | `4.0` |
| `axial_margin` | Skip-zone at each path end in mm. | `4.0` |
| `circumferential_count` | Studs per row around the perimeter. | `12` |
| `stagger_rows` | Rotate every other row by half a stud. | `True` |
| `embed_depth` | Sink each pyramid base into the wall by this much for clean fusion (mm). Must be `< outer_radius`. | `0.3` |
| `path_frame_samples` | Number of `PathFrame`s sampled along the centerline. | `200` |

`base_size`, `height`, `axial_pitch`, and `circumferential_count` must all be
positive; the model raises `ValueError` otherwise. If the path is too short
for any row (`< axial_pitch * 0.5` of usable length after margins), the model
logs a warning and returns the bare base tube. Note that the model also
inherits the smooth tube's `face_settings` (e.g. `outer_diameter`,
`wall_thickness`) via `inherit_from`, so the same block drives both the base
sweep and the stud placement.

Pick this when you want texture / grip on the outside of the tube.

### `braided_rope`

A braided-rope sleeve along the centerline, ported from the original
proof-of-concept and re-grounded on the shared `path_frames` helpers.
Implemented by `BraidedRopeModel` in
[tube_models/braided_rope.py](../src/led_knots/core/tube_models/braided_rope.py).

What it builds:

1. A smooth **core** loft of circles at `params.core_radius`.
2. `2 * num_strands_per_dir` lenticular **strands**: half clockwise, half
   counter-clockwise, phase-staggered so they interlace. Each strand is
   computed from He et al. 2020 Eqs. 17/18 (braiding curve) with Kyosev's
   lenticular cross-section, then lofted or swept along its trajectory.
3. Strands are built lazily and folded one at a time into a running result so
   memory stays bounded at high strand counts (see `fuse_method` below). The
   build returns either a single fused `Solid` (`fuse_method: brep`, default) or
   a watertight `trimesh.Trimesh` (`fuse_method: mesh`).

Config keys (`face_settings.braided_rope.braided_rope`):

| Key | Meaning | Default |
| --- | --- | --- |
| `num_strands_per_dir` | Strands per direction; total strands = `2 * this`. | `25` |
| `outer_radius` | Outer radius of the rope in mm. Defaults to `config.tube_settings.outer_radius` if not set. | inherited |
| `float_length` | He et al. `F`: 1 = 1×1 diamond, 2 = 2×2 regular, etc. Must divide `num_strands_per_dir`. | `1` |
| `helix_angle_deg` | Helix angle of each strand in degrees. | `30.0` |
| `pack_factor` | `k` in the paper; controls how tightly packed the strands are. Overridden by `braid_tightness` on swept bases. | `0.7` |
| `strand_aspect_ratio` | Lenticular ellipse major/minor ratio. `1.0` = circular strand. | `1.6` |
| `tilt_to_helix_angle` | Tilt the ellipse major axis to align with the braid direction. | `True` |
| `weave_amplitude_factor` | Multiplier on `A_min`; `1.0` is minimum weave lift (tighter peaks). | `1.05` |
| `braid_tightness` | Swept-base only: `0` = use `pack_factor` as-is; up to `1` modestly increases `pack_factor` for a tighter sleeve. Does not retarget `outer_radius`. | `0.0` |
| `samples_per_period` | Loft sample density (interacts with auto-bounded `loft_samples`). | `20` |
| `strand_start` | Trim from path start in mm. | `2.0` |
| `strand_end_offset` | Trim from path end in mm. | `2.0` |
| `valley_embed_depth` | Swept-base only (`base_face_type` not `braid_core`): target depth (mm) for braid valley centerlines below the tube OD. Controls weave placement and print overlap; strand solids are clipped at the tube OD before fuse so the base wall stays cylindrical. Must be `>= 0`, `< outer_radius`, and `<= wall_thickness`. Ignored for standalone `braided_rope`. When `outer_radius` is not set explicitly, the model auto-scales the braid envelope to the tube OD before applying valley embed. | `0.5` |
| `fuse_method` | How the `2N` strands and core are assembled. `brep` builds each strand, clips it, and folds it into a running fused `Solid` one batch at a time (bounded memory; output is a single B-rep `Solid`, so STEP export and the SLA optimize/drain-hole stages keep working). `mesh` tessellates each strand and unions it into a watertight mesh via the `manifold` engine (much faster and lighter for high strand counts, but the output is a `trimesh.Trimesh`: STEP export and `--optimize`/`--auto-orient` are unavailable and will raise). | `brep` |
| `fuse_batch_size` | `brep` only: how many strands are fused into the running accumulator per batch. Lower values cap peak RAM (fewer strands resident at once) at the cost of more fuse calls; higher values process larger chunks. | `12` |
| `mesh_batch_size` | `mesh` only: how many strand meshes are unioned into one chunk before map-reduce pairing. Lower values cap peak RAM during union (especially on curved paths). | `2` |
| `mesh_tolerance` | `mesh` only: finest linear tessellation tolerance (mm) tried for each strand. On curved paths the build auto-selects a coarser tolerance up to `mesh_tolerance_max` so each strand stays under `mesh_max_strand_faces`. | `0.05` |
| `mesh_angular_tolerance` | `mesh` only: angular tessellation tolerance (rad) at `mesh_tolerance`; scales up when auto-coarsening. | `0.3` |
| `mesh_tolerance_max` | `mesh` only: coarsest linear tolerance (mm) tried when auto-scaling for the face budget. If the reference strand still exceeds `mesh_max_strand_faces` at this tolerance, the build raises. | `0.3` |
| `mesh_max_strand_faces` | `mesh` only: upper bound on triangle count per strand before union. Curved knots (e.g. `quarter_turn`) tessellate far denser than straight rods at the same tolerance; the build probes one reference strand and picks the finest tolerance within this budget. | `80000` |

> Note on very high strand counts: B-rep boolean fusion (`fuse_method: brep`) scales poorly as the fused accumulator grows, so a 150-strand braid can take many hours even though memory stays bounded. For high strand counts prefer `fuse_method: mesh`, which unions watertight strand meshes via the `manifold` engine in minutes. The trade-off is that the mesh output cannot be exported as STEP and is not accepted by the SLA optimize / drain-hole stages; use `brep` (the default) when you need those.
>
> Curved paths: at the default `mesh_tolerance` a `quarter_turn` strand can tessellate to ~450k faces (vs ~35k on a straight rod). Mesh builds auto-scale tolerance to `mesh_max_strand_faces`, union strand batches into the core mesh immediately (small `mesh_batch_size`), and call `gc` after each strand so memory stays bounded; check the log line `mesh tessellation: using tol=...`.

The constructor derives `Rr`, `a`, `p`, `A`, `pitch`, and `core_radius` from
these inputs; if `core_radius` ends up `<= 0` it raises `ValueError` with
guidance (reduce `weave_amplitude_factor` or `strand_aspect_ratio`, or
increase `num_strands_per_dir`).

`aux` and `face_kwargs` are deliberately **ignored** — braided rope drives
its own twist from the braid model, so any swept-tube auxiliary path would
fight the helix.

Pick this when you want a decorative rope/cable look. Build time is much
higher than the swept models because each strand is its own loft.

## SweptFaceModel

`SweptFaceModel` in
[tube_models/swept_face.py](../src/led_knots/core/tube_models/swept_face.py) is
the shared implementation behind every simple cross-section. It exists so
adding a new flat profile is one config-and-dispatch entry, not a new
`TubeModel` class.

It carries one piece of state — the `face_type` string — and looks up its
factory and kwargs-builder method name from `_FACE_FACTORIES`:

```python
_FACE_FACTORIES = {
    "led_circle":      (create_led_circle_face,      "to_led_circle_face_kwargs"),
    "led_circle_tube": (create_led_circle_tube_face, "to_led_circle_tube_face_kwargs"),
    "solid_circle":    (create_solid_circle_face,    "to_led_circle_face_kwargs"),
    "square":          (create_square_face,          "to_led_circle_face_kwargs"),
}
```

Construction validates the string against this table, so trying to wire a new
key without registering the factory raises immediately:

```python
SweptFaceModel("triangle")
# ValueError: SweptFaceModel does not handle face_type 'triangle'. Supported: ...
```

Two methods of note:

- `build_face(*, path, config, face_kwargs=None)` — builds the oriented 2D
  face without sweeping. Used by composite models (e.g.
  `PyramidStuddedModel`) that want to control the sweep themselves or
  decorate the resulting solid.
- `build(*, path, aux, config, face_kwargs=None)` — the full `TubeModel`
  contract: build the face, then call `cadquery.func.sweep(face, path, aux=aux)`
  and return the resulting `Solid`/`Compound`.

Kwargs resolution is uniform:

```python
builder = getattr(config.tube_settings, self._kwargs_method)
return builder(orient_to_path=path, **(face_kwargs or {}))
```

That is, `TubeSettings.to_led_circle_face_kwargs` /
`to_led_circle_tube_face_kwargs` ([config.py:324](../src/led_knots/core/config.py#L324),
[config.py:341](../src/led_knots/core/config.py#L341)) produce the named
arguments the face factory expects, the caller can override individual keys
through `face_kwargs`, and `orient_to_path` is always set to the centerline
so the face is positioned and rotated for the sweep.

`solid_circle` and `square` reuse `to_led_circle_face_kwargs` even though
they ignore most of its keys — the helper is harmless when the factory
discards extras.

## Cookbook: add a new face shape (SweptFaceModel-compatible)

Use this path when the new cross-section is one flat 2D `Face` that is the
same all along the tube. You do **not** need to write a new `TubeModel`
class.

1. **Write the face factory.** Add a function to
   [src/led_knots/core/led_circle.py](../src/led_knots/core/led_circle.py)
   (or a new module if it warrants its own file). Match the signature of the
   existing factories: accept `outer_radius`, anything else your shape needs,
   plus `orient_to_path: Wire = None` and `rotation_z: float = 90.0`. Return
   a `cq.Face` or `cq.Compound`. When `orient_to_path` is not `None`, move
   the result to a `Plane(origin=orient_to_path.startPoint(), normal=orient_to_path.tangentAt(0))`
   like the existing factories do.

2. **Wire it into the dispatch table.** Add an entry to `_FACE_FACTORIES` in
   [tube_models/swept_face.py](../src/led_knots/core/tube_models/swept_face.py):

   ```python
   _FACE_FACTORIES = {
       ...,
       "my_shape": (create_my_shape_face, "to_led_circle_face_kwargs"),
   }
   ```

   Reuse `to_led_circle_face_kwargs` if your shape is happy with the
   `outer_diameter` / `wall_thickness` / `connector_width` / `rect_inner_*`
   set. If you need a different param set, add a new builder method to
   `TubeSettings` in [config.py](../src/led_knots/core/config.py) (next to
   `to_led_circle_tube_face_kwargs`) and reference that method's name here.

3. **Declare config defaults.** Add a block under `face_settings` in
   [config.yaml](../config.yaml):

   ```yaml
   face_settings:
     my_shape:
       inherit_from: solid_circle   # or write the full set of keys
       outer_diameter: 30
       # ...whatever your factory reads
   ```

   Also add `'my_shape'` to `VALID_FACE_TYPES` in
   [config.py:19](../src/led_knots/core/config.py#L19) so config validation
   accepts the new string.

4. **Register the model.** In
   [tube_models/\_\_init\_\_.py](../src/led_knots/core/tube_models/__init__.py)
   add the entry to `_REGISTRY`:

   ```python
   _REGISTRY["my_shape"] = SweptFaceModel("my_shape")
   ```

5. **Validate against an existing knot.** Run any knot script with
   `face_type: my_shape` (top-level in `config.yaml` or via
   `config.local.yaml`). Watch the preview / STL output. Iterate on the
   factory until the swept solid looks right.

## Cookbook: add a fully-custom TubeModel (non-swept)

Use this path when the geometry is not a single swept face — for example, you
want discrete decorations like `pyramid_studded`, multiple strands like
`braided_rope`, or any tube whose cross-section varies along the path.

1. **Create a module.** Add a file under
   [src/led_knots/core/tube_models/](../src/led_knots/core/tube_models/),
   e.g. `tube_models/my_model.py`. Use `pyramid_studded.py` or
   `braided_rope.py` as a template.

2. **Implement `build`.** Define a class with a `build(self, *, path, aux,
   config, face_kwargs=None)` method that returns a `cq.Solid` or
   `cq.Compound`. The class does not need to subclass anything — the
   `TubeModel` protocol is structural — but a `runtime_checkable` `isinstance`
   check helps catch typos:

   ```python
   from ._base import TubeModel
   assert isinstance(MyModel(), TubeModel)
   ```

3. **Decide on composition.** Two patterns exist in the codebase:

   - **Compose a base sweep**, like `PyramidStuddedModel`:
     instantiate `SweptFaceModel(settings["base_face_type"])`, call its
     `build` (or `build_face` if you want to control the sweep), then add
     your decorations on top and return a `Compound` of everything.
   - **Bespoke geometry**, like `BraidedRopeModel`: ignore `aux` and
     `face_kwargs`, sample your own `PathFrame`s with `sample_path_frames` /
     `frame_at_arc_length`, and build solids directly with CadQuery's `Wire`,
     `Face`, `Shell`, `Solid`, and `Compound` APIs.

4. **Declare config defaults.** Add a block under `face_settings.<my_model>`
   in [config.yaml](../config.yaml). The convention is to inherit a base
   smooth tube and put model-specific keys in a nested dict named after the
   model itself, so `getattr(config.tube_settings, "my_model", None)` returns
   that dict. You will also need to expose the nested block from
   `TubeSettings.__init__` in
   [config.py](../src/led_knots/core/config.py) the same way
   `pyramid_studded` and `braided_rope` already do (around
   [config.py:301](../src/led_knots/core/config.py#L301)).
   Add `'my_model'` to `VALID_FACE_TYPES` at the top of `config.py`.

5. **Register it.** Edit
   [tube_models/\_\_init\_\_.py](../src/led_knots/core/tube_models/__init__.py).
   If your module imports `SweptFaceModel` or `_REGISTRY` itself, put the
   import **after** `_REGISTRY` is initialized using the
   `# noqa: E402` pattern already in place:

   ```python
   from .my_model import MyModel  # noqa: E402

   _REGISTRY["my_model"] = MyModel()
   ```

6. **Test against an existing knot.** Set `face_type: my_model` in
   [config.yaml](../config.yaml) (or in `config.local.yaml`) and run any
   knot script. Iterate on geometry until the preview and exports look
   correct. Add a test under [tests/](../tests/) that builds your model
   against a short canned path so regressions surface in CI.

## Do's and don'ts

Do:

- **Reuse `path_frames` helpers.** `sample_path_frames` and
  `frame_at_arc_length` give you parallel-transported frames that every
  other model already uses, which keeps decorations and strands consistent
  across models.
- **Honor `aux` and `rotation_z` when they apply.** Swept models pass `aux`
  straight through to `cadquery.func.sweep`; if your model performs its own
  sweep on a smooth profile, do the same so the user's twist control still
  works.
- **Fail loudly on missing config.** Follow the existing models'
  `if X is None: raise ValueError(...)` style with a message that names the
  key and the `face_type`. Silent defaults make later debugging painful.
- **Return a `Solid` or `Compound`.** Use `Compound.makeCompound([...])` when
  you have multiple bodies. Downstream tessellation, slicing, and export all
  handle compounds.
- **Update `VALID_FACE_TYPES` and the registry together.** A `face_type`
  accepted by the config that's missing from the registry (or vice versa)
  fails late, far from the actual edit.

Don't:

- **Don't reach into another model's face creator.** Compose through
  `SweptFaceModel.build` / `build_face`. Direct imports of
  `create_led_circle_face` from outside the swept-face dispatcher bypass the
  kwargs-builder contract in `TubeSettings`.
- **Don't bypass the registry.** Call `get_tube_model(face_type)` (used by
  [utils.py:185](../src/led_knots/core/utils.py#L185)); never instantiate a
  model class directly from `draw_part`-style code. That's what
  `register_tube_model(...)` is for if you want to inject a custom model
  from a downstream script.
- **Don't perform boolean unions you don't need.** `pyramid_studded`
  intentionally returns a `Compound` and lets STL / GLB tessellation merge
  the geometry; unions are slow and brittle on these meshes.
- **Don't write to `cache/`.** That directory is owned by preview /
  slicing pipelines (see `preview.stl_cache` in
  [config.yaml](../config.yaml)). Tube models are pure geometry producers —
  return the solid and let the caller cache it.
- **Don't make `aux` or `face_kwargs` required.** The `TubeModel` protocol
  marks them as something every caller passes, but composite models like
  `BraidedRopeModel` legitimately ignore them. Accept and discard rather
  than crash.
