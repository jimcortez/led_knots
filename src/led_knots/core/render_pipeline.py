"""
Dependency-resolved render pipeline for CAD parts.

Resolves CLI outcomes (preview PNG, CAD export, web viewer, mesh OBJ) into a
small set of artifacts (STL, GLB) built at most once, then fans out to all
requested outputs.
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import cadquery as cq
import trimesh

from .cache_utils import preview_stl_path_for_part
from .color_palette import ColoredShape, colored_assembly_shapes, iter_assembly_leaf_solids
from .preview import render_glb_to_image, render_stl_to_image

logger = logging.getLogger(__name__)

_SUPPORTED_SOLID_EXPORT = {".stl", ".step", ".stp", ".3mf", ".glb", ".gltf"}
_SUPPORTED_ASSEMBLY_EXPORT = {".step", ".stp", ".stl", ".3mf", ".glb", ".gltf"}


def _viewer_tessellation_kwargs(config) -> Dict[str, float]:
    """Tessellation options for cadquery-web-viewer ``show`` / ``render``."""
    ps = config.preview_settings
    return {
        "tolerance": float(ps.mesh_tolerance),
        "angular_tolerance": float(ps.mesh_angular_tolerance),
    }


def _glb_bytes_via_viewer_render(obj, config, name: str) -> bytes:
    """Tessellate a CAD object to GLB using cadquery-web-viewer ``render``."""
    from cadquery_web_viewer import render

    glbs = render(obj, names=name, **_viewer_tessellation_kwargs(config))
    return glbs[0]


def _cadquery_web_viewer_show(
    config,
    names: Union[str, List[str], None],
    *objs,
) -> None:
    """Send geometry to cadquery-web-viewer (embedded or remote per config)."""
    from cadquery_web_viewer import show

    tess_kw = _viewer_tessellation_kwargs(config)
    st = config.viewer_server_type
    block = bool(config.viewer_block_until_disconnect)
    label = names if isinstance(names, str) else ", ".join(names or [])
    if st == "remote":
        ro = config.viewer_remote_options or {}
        show(
            *objs,
            names=names,
            server_type="remote",
            remote_options=ro,
            block_until_disconnect=False,
            **tess_kw,
        )
        logger.info(
            "Posted %s to cadquery-web-viewer at http://%s:%s/",
            label,
            ro.get("host", "localhost"),
            ro.get("port", 32323),
        )
        return
    so = config.viewer_server_options or {}
    show(
        *objs,
        names=names,
        server_type="in-process",
        server_options=so,
        block_until_disconnect=block,
        **tess_kw,
    )
    logger.info(
        "cadquery-web-viewer (%s): http://%s:%s/",
        label,
        so.get("host", "127.0.0.1"),
        so.get("port", 32323),
    )


def _cadquery_web_viewer_show_colored_parts(
    config,
    names: List[str],
    colored: List[ColoredShape],
) -> None:
    """
    Show each assembly part with its own ``color_faces`` (and embedded vertex colors).

    Posts one object at a time so per-part colors are not lost when the viewer UI
    applies a default white material over the mesh.
    """
    from cadquery_web_viewer import show

    tess_kw = _viewer_tessellation_kwargs(config)
    st = config.viewer_server_type
    block = bool(config.viewer_block_until_disconnect)
    for idx, (part_name, shape) in enumerate(zip(names, colored)):
        kw = {
            **tess_kw,
            "color_faces": shape.color,
            "auto_clear": idx == 0,
        }
        if st == "remote":
            ro = config.viewer_remote_options or {}
            show(
                shape,
                names=part_name,
                server_type="remote",
                remote_options=ro,
                block_until_disconnect=False,
                **kw,
            )
        else:
            so = config.viewer_server_options or {}
            show(
                shape,
                names=part_name,
                server_type="in-process",
                server_options=so,
                block_until_disconnect=block and idx == len(colored) - 1,
                **kw,
            )
    label = ", ".join(names)
    if st == "remote":
        ro = config.viewer_remote_options or {}
        logger.info(
            "Posted %s (%d parts) to cadquery-web-viewer at http://%s:%s/",
            label,
            len(colored),
            ro.get("host", "localhost"),
            ro.get("port", 32323),
        )
    else:
        so = config.viewer_server_options or {}
        logger.info(
            "cadquery-web-viewer (%s, %d parts): http://%s:%s/",
            label,
            len(colored),
            so.get("host", "127.0.0.1"),
            so.get("port", 32323),
        )


def _exit_if_remote_viewer_idle(config, *, did_followup_glb_work: bool) -> None:
    """Exit immediately after remote viewer when no local GLB follow-up work."""
    if did_followup_glb_work:
        return
    if not config.viewer_enabled:
        return
    if config.viewer_server_type != "remote":
        return
    logger.debug("Remote viewer done with no local GLB follow-up; exiting process.")
    sys.exit(0)


def _maybe_export_mesh_from_glb(glb_bytes: bytes, config) -> None:
    """Export an OBJ mesh from GLB bytes when ``--output-mesh`` is set."""
    mesh_cfg = config.mesh
    output_path = mesh_cfg.filepath
    if not output_path:
        return

    ext = os.path.splitext(str(output_path))[1].lower()
    if ext != ".obj":
        logger.error("Mesh export only supports .obj for now (got %s).", ext)
        sys.exit(2)

    try:
        scene_or_mesh = trimesh.load(
            trimesh.util.wrap_as_stream(glb_bytes), file_type="glb"
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to load GLB for mesh export: %r", exc)
        sys.exit(2)

    if isinstance(scene_or_mesh, trimesh.Scene):
        mesh = scene_or_mesh.dump(concatenate=True)
    else:
        mesh = scene_or_mesh

    if mesh_cfg.unit_scale_mm_to_m:
        mesh.apply_scale(0.001)

    if hasattr(mesh, "remove_degenerate_faces"):
        mesh.remove_degenerate_faces()
    if hasattr(mesh, "remove_unreferenced_vertices"):
        mesh.remove_unreferenced_vertices()
    if hasattr(mesh, "merge_vertices"):
        mesh.merge_vertices()

    if mesh_cfg.watertight_required and not mesh.is_watertight:
        logger.error("Mesh export aborted: generated mesh is not watertight.")
        sys.exit(2)

    if mesh_cfg.target_face_count is not None:
        current_faces = len(mesh.faces)
        target = mesh_cfg.target_face_count
        if current_faces > target and target > 0:
            try:
                mesh = mesh.simplify_quadratic_decimation(target)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Mesh decimation failed (%r); continuing with original mesh.",
                    exc,
                )

    export_dir = os.path.dirname(str(output_path))
    if export_dir and not os.path.exists(export_dir):
        os.makedirs(export_dir, exist_ok=True)

    try:
        mesh.export(str(output_path), file_type="obj")
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to export OBJ mesh to %s: %r", output_path, exc)
        sys.exit(2)

    logger.info("Exported mesh OBJ to %s", output_path)


def _assembly_to_glb_bytes(assy: cq.Assembly, config) -> bytes:
    """Export an assembly to GLB bytes using CadQuery (tempfile-backed)."""
    with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as tf:
        tmp_path = tf.name
    try:
        tol_val = config.preview_settings.mesh_tolerance
        ang_val = config.preview_settings.mesh_angular_tolerance
        assy.export(
            tmp_path,
            exportType="GLB",
            tolerance=float(tol_val),
            angularTolerance=float(ang_val),
        )
        return Path(tmp_path).read_bytes()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _solid_to_glb_bytes(
    solid,
    *,
    config,
    stl_tolerance: float,
    stl_angular_tolerance: float,
    stl_ascii: bool,
) -> bytes:
    """Generate GLB bytes from a solid via STL tessellation and trimesh."""
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tf_stl:
        tmp_stl_path = tf_stl.name
    with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as tf_glb:
        tmp_glb_path = tf_glb.name

    try:
        cq.exporters.export(
            solid,
            tmp_stl_path,
            tolerance=float(stl_tolerance),
            angularTolerance=float(stl_angular_tolerance),
            opt={"ascii": bool(stl_ascii)},
        )

        loaded = trimesh.load(tmp_stl_path)
        if isinstance(loaded, trimesh.Scene):
            mesh = loaded.dump(concatenate=True)
        else:
            mesh = loaded

        mesh.export(tmp_glb_path, file_type="glb")
        return Path(tmp_glb_path).read_bytes()
    finally:
        for p in (tmp_stl_path, tmp_glb_path):
            try:
                os.unlink(p)
            except OSError:
                pass


def _render_glb_bytes_to_image(
    glb_bytes: bytes,
    image_path: Union[str, Path],
    preview_settings,
) -> None:
    """Write GLB bytes to a temp file and render a preview image."""
    with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as tf:
        tmp_glb = Path(tf.name)
    try:
        tmp_glb.write_bytes(glb_bytes)
        render_glb_to_image(tmp_glb, Path(image_path), preview_settings)
    finally:
        try:
            os.unlink(tmp_glb)
        except OSError:
            pass


@dataclass(frozen=True)
class RenderPlan:
    """Outcomes and derived artifact needs from ``config``."""

    want_preview_png: bool
    want_viewer: bool
    want_mesh_obj: bool
    export_ext: Optional[str]
    export_filepath: Optional[str]
    need_stl_preview: bool
    need_stl_export: bool
    need_glb_preview: bool
    need_glb_export: bool
    need_step_export: bool
    preview_uses_export_stl: bool
    preview_from_glb: bool

    @property
    def has_side_effects(self) -> bool:
        return (
            self.want_preview_png
            or self.want_viewer
            or self.want_mesh_obj
            or self.export_ext is not None
        )

    @classmethod
    def from_config(cls, config: Any) -> RenderPlan:
        export_filepath = config.export.filepath
        export_ext: Optional[str] = None
        if export_filepath:
            export_ext = os.path.splitext(export_filepath)[1].lower()

        want_preview_png = config.preview_filepath is not None
        want_viewer = bool(config.viewer_enabled)
        want_mesh_obj = config.mesh.filepath is not None

        preview_uses_export_stl = bool(
            want_preview_png and export_ext == ".stl" and export_filepath
        )
        need_stl_export = export_ext in (".stl", ".3mf")
        need_step_export = export_ext in (".step", ".stp")
        need_glb_export = export_ext in (".glb", ".gltf")
        need_glb_preview = want_viewer
        preview_from_glb = want_preview_png and (want_viewer or need_glb_export)
        need_stl_preview = (
            want_preview_png
            and not preview_uses_export_stl
            and not preview_from_glb
        )

        return cls(
            want_preview_png=want_preview_png,
            want_viewer=want_viewer,
            want_mesh_obj=want_mesh_obj,
            export_ext=export_ext,
            export_filepath=export_filepath,
            need_stl_preview=need_stl_preview,
            need_stl_export=need_stl_export,
            need_glb_preview=need_glb_preview,
            need_glb_export=need_glb_export,
            need_step_export=need_step_export,
            preview_uses_export_stl=preview_uses_export_stl,
            preview_from_glb=preview_from_glb,
        )


class PartArtifacts:
    """Lazy builders for tessellated artifacts and outcome emitters."""

    def __init__(
        self,
        part: Union[cq.Workplane, cq.Solid, cq.Compound, cq.Assembly],
        config: Any,
        plan: RenderPlan,
        *,
        path=None,
        aux=None,
        face_kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.part = part
        self.config = config
        self.plan = plan
        self.path = path
        self.aux = aux
        self.face_kwargs = face_kwargs or {}

        self._solid: Optional[Any] = None
        self._assy: Optional[cq.Assembly] = None
        self._is_assembly = False
        self._normalized = False

        self.stl_preview_path: Optional[Path] = None
        self.stl_export_written = False
        self.glb_preview_bytes: Optional[bytes] = None
        self.glb_export_bytes: Optional[bytes] = None

    def _normalize(self) -> None:
        if self._normalized:
            return
        self._is_assembly = isinstance(self.part, cq.Assembly)
        if self._is_assembly:
            self._assy = self.part
            self._solid = self._assy.toCompound()
        elif isinstance(self.part, (cq.Solid, cq.Compound)):
            self._solid = self.part
        elif hasattr(self.part, "val"):
            self._solid = self.part.val()
        else:
            self._solid = self.part
        self._normalized = True

    @property
    def solid(self):
        self._normalize()
        return self._solid

    @property
    def assy(self) -> Optional[cq.Assembly]:
        self._normalize()
        return self._assy

    @property
    def is_assembly(self) -> bool:
        self._normalize()
        return self._is_assembly

    def _export_solid_to_stl(
        self,
        dest: Union[str, Path],
        *,
        tolerance: float,
        angular_tolerance: float,
        ascii: bool = False,
    ) -> None:
        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        cq.exporters.export(
            self.solid,
            str(dest_path),
            tolerance=float(tolerance),
            angularTolerance=float(angular_tolerance),
            opt={"ascii": bool(ascii)},
        )

    def ensure_stl_preview(self) -> Path:
        if self.stl_preview_path is not None:
            return self.stl_preview_path

        ps = self.config.preview_settings
        tol = ps.mesh_tolerance
        ang = ps.mesh_angular_tolerance

        if self.path is not None:
            cached = preview_stl_path_for_part(
                self.config,
                self.path,
                aux=self.aux,
                face_kwargs=self.face_kwargs,
            )
            if cached is not None:
                self._export_solid_to_stl(
                    cached, tolerance=tol, angular_tolerance=ang, ascii=False
                )
                self.stl_preview_path = cached
                logger.debug("Wrote preview STL cache %s", cached)
                return cached

        with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tf:
            tmp = Path(tf.name)
        self._export_solid_to_stl(tmp, tolerance=tol, angular_tolerance=ang, ascii=False)
        self.stl_preview_path = tmp
        return tmp

    def ensure_stl_export(self) -> None:
        if self.stl_export_written or not self.plan.export_filepath:
            return
        export_path = self.plan.export_filepath
        ext = self.plan.export_ext
        exp = self.config.export
        cq.exporters.export(
            self.solid,
            export_path,
            tolerance=exp.tolerance,
            angularTolerance=exp.angular_tolerance,
            opt={"ascii": exp.stl_ascii} if ext == ".stl" else None,
        )
        self.stl_export_written = True

    def ensure_glb_preview(self, name: str) -> bytes:
        if self.glb_preview_bytes is not None:
            return self.glb_preview_bytes

        if self.plan.want_viewer:
            obj = self.solid
            self.glb_preview_bytes = _glb_bytes_via_viewer_render(obj, self.config, name)
        else:
            ps = self.config.preview_settings
            self.glb_preview_bytes = _solid_to_glb_bytes(
                self.solid,
                config=self.config,
                stl_tolerance=ps.mesh_tolerance,
                stl_angular_tolerance=ps.mesh_angular_tolerance,
                stl_ascii=False,
            )
        return self.glb_preview_bytes

    def ensure_glb_export(self) -> bytes:
        if self.glb_export_bytes is not None:
            return self.glb_export_bytes

        exp = self.config.export
        if self.is_assembly and self.assy is not None:
            import tempfile as _tf

            with _tf.NamedTemporaryFile(suffix=".glb", delete=False) as tf:
                tmp_path = tf.name
            try:
                export_type = "GLB" if self.plan.export_ext == ".glb" else "GLTF"
                self.assy.export(
                    tmp_path,
                    exportType=export_type,
                    tolerance=exp.tolerance,
                    angularTolerance=exp.angular_tolerance,
                )
                self.glb_export_bytes = Path(tmp_path).read_bytes()
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        else:
            self.glb_export_bytes = _solid_to_glb_bytes(
                self.solid,
                config=self.config,
                stl_tolerance=exp.tolerance,
                stl_angular_tolerance=exp.angular_tolerance,
                stl_ascii=exp.stl_ascii,
            )
        return self.glb_export_bytes

    def _mesh_glb_bytes(self) -> bytes:
        if self.glb_preview_bytes is not None:
            return self.glb_preview_bytes
        if self.glb_export_bytes is not None:
            return self.glb_export_bytes
        if self.plan.need_glb_preview:
            return self.ensure_glb_preview(self.config.name or "Knot")
        if self.plan.need_glb_export:
            return self.ensure_glb_export()
        ps = self.config.preview_settings
        if self.is_assembly and self.assy is not None:
            return _assembly_to_glb_bytes(self.assy, self.config)
        return _solid_to_glb_bytes(
            self.solid,
            config=self.config,
            stl_tolerance=ps.mesh_tolerance,
            stl_angular_tolerance=ps.mesh_angular_tolerance,
            stl_ascii=False,
        )

    def emit_cad_export(self, name: str) -> None:
        if not self.plan.export_filepath:
            return

        export_path = self.plan.export_filepath
        ext = self.plan.export_ext
        export_dir = os.path.dirname(export_path)
        if export_dir and not os.path.exists(export_dir):
            os.makedirs(export_dir, exist_ok=True)

        supported = (
            _SUPPORTED_ASSEMBLY_EXPORT if self.is_assembly else _SUPPORTED_SOLID_EXPORT
        )
        if ext not in supported:
            kind = "assembly" if self.is_assembly else "solid"
            logger.error(
                "Unknown export file extension '%s' for %s. Supported: %s.",
                ext,
                kind,
                ", ".join(sorted(supported)),
            )
            sys.exit(2)

        if self.plan.need_step_export:
            if self.is_assembly and self.assy is not None:
                self.assy.export(
                    export_path,
                    exportType="STEP",
                    mode="default",
                    write_pcurves=True,
                    precision_mode=0,
                )
                logger.info("Exported %s to %s (STEP assembly)", name, export_path)
            else:
                exp = self.config.export
                cq.exporters.export(
                    self.solid,
                    export_path,
                    tolerance=exp.tolerance,
                    angularTolerance=exp.angular_tolerance,
                )
                logger.info("Exported %s to %s (STEP format)", name, export_path)
            return

        if ext in (".glb", ".gltf"):
            glb_bytes = self.ensure_glb_export()
            if ext == ".glb":
                with open(export_path, "wb") as f:
                    f.write(glb_bytes)
                fmt = "GLB assembly" if self.is_assembly else "GLB format"
                logger.info("Exported %s to %s (%s)", name, export_path, fmt)
            else:
                scene_or_mesh = trimesh.load(
                    trimesh.util.wrap_as_stream(glb_bytes), file_type="glb"
                )
                if isinstance(scene_or_mesh, trimesh.Scene):
                    mesh = scene_or_mesh.dump(concatenate=True)
                else:
                    mesh = scene_or_mesh
                mesh.export(str(export_path), file_type="gltf")
                fmt = "GLTF/GLB assembly" if self.is_assembly else "GLTF format"
                logger.info("Exported %s to %s (%s)", name, export_path, fmt)
            return

        if ext in (".stl", ".3mf"):
            self.ensure_stl_export()
            label = ext.upper().lstrip(".")
            if self.is_assembly:
                logger.info(
                    "Exported %s to %s (%s fused)",
                    name,
                    export_path,
                    label,
                )
            elif ext == ".stl":
                logger.info("Exported %s to %s (STL format)", name, export_path)
            else:
                logger.info("Exported %s to %s (3MF format)", name, export_path)

    def emit_preview_png(self) -> None:
        if not self.plan.want_preview_png:
            return
        image_path = Path(self.config.preview_filepath)
        ps = self.config.preview_settings

        if self.plan.preview_uses_export_stl:
            render_stl_to_image(
                Path(self.plan.export_filepath),
                image_path,
                ps,
            )
            logger.debug("Wrote preview image %s (from export STL)", image_path)
            return

        if self.plan.preview_from_glb:
            glb = (
                self.glb_preview_bytes
                if self.glb_preview_bytes is not None
                else self.glb_export_bytes
            )
            if glb is None:
                if self.plan.need_glb_preview:
                    glb = self.ensure_glb_preview(self.config.name or "Knot")
                else:
                    glb = self.ensure_glb_export()
            _render_glb_bytes_to_image(glb, image_path, ps)
            logger.debug("Wrote preview image %s (from GLB)", image_path)
            return

        stl_path = self.stl_preview_path
        if stl_path is None:
            stl_path = self.ensure_stl_preview()
        render_stl_to_image(stl_path, image_path, ps)
        logger.debug("Wrote preview image %s (from preview STL)", image_path)

    def emit_viewer(self, name: str) -> None:
        if not self.plan.want_viewer:
            return
        if self.is_assembly and self.assy is not None:
            leaves = iter_assembly_leaf_solids(self.assy)
            if len(leaves) >= 2:
                base_rgb = self.config.preview_settings._color_rgb
                part_names, colored = colored_assembly_shapes(self.assy, base_rgb)
                _cadquery_web_viewer_show_colored_parts(self.config, part_names, colored)
                return
        glb = self.ensure_glb_preview(name)
        _cadquery_web_viewer_show(self.config, name, glb)

    def emit_mesh_obj(self) -> bool:
        """Return True if mesh export ran (for remote idle exit)."""
        if not self.plan.want_mesh_obj:
            return False
        _maybe_export_mesh_from_glb(self._mesh_glb_bytes(), self.config)
        return True

    def cleanup_temp_stl_preview(self) -> None:
        if self.stl_preview_path is None:
            return
        if self.path is not None:
            return
        try:
            if self.stl_preview_path.exists():
                self.stl_preview_path.unlink()
        except OSError:
            pass


def deliver_part(
    part: Union[cq.Workplane, cq.Solid, cq.Compound, cq.Assembly],
    config: Any,
    *,
    path=None,
    aux=None,
    face_kwargs: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Build artifacts once and emit all configured outcomes (export, preview, viewer, mesh).
    """
    plan = RenderPlan.from_config(config)
    if not plan.has_side_effects:
        return

    ctx = PartArtifacts(
        part,
        config,
        plan,
        path=path,
        aux=aux,
        face_kwargs=face_kwargs,
    )
    ctx._normalize()
    name = config.name or "Knot"

    if plan.need_stl_preview:
        ctx.ensure_stl_preview()
    if plan.need_stl_export:
        ctx.ensure_stl_export()
    if plan.need_glb_preview:
        ctx.ensure_glb_preview(name)
    if plan.need_glb_export:
        ctx.ensure_glb_export()

    ctx.emit_cad_export(name)
    ctx.emit_preview_png()
    ctx.emit_viewer(name)
    did_mesh = ctx.emit_mesh_obj()

    ctx.cleanup_temp_stl_preview()
    _exit_if_remote_viewer_idle(config, did_followup_glb_work=did_mesh)
