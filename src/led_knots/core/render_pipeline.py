"""
Dependency-resolved render pipeline for CAD parts.

Builds a render bundle folder of export jobs (STL, GLB, preview PNG, config YAML,
stats CSV, optional STEP/GLTF/3MF/OBJ) then optionally uploads to the web viewer.
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import cadquery as cq
import trimesh
import yaml

from .config import RenderingExportJob
from .preview import render_glb_to_image
from .render_planner import ExportJob, RenderPlanner

logger = logging.getLogger(__name__)


def _viewer_tessellation_kwargs(config) -> Dict[str, float]:
    vs = config.server_settings.viewer
    return {
        "tolerance": float(vs.tessellation_tolerance),
        "angular_tolerance": float(vs.tessellation_angular_tolerance),
    }


def _ensure_remote_viewer_reachable(config) -> None:
    if config.viewer_server_type != "remote":
        return
    import httpx

    ro = config.viewer_remote_options or {}
    host = str(ro.get("host", "localhost"))
    port = int(ro.get("port", 32323))
    timeout = min(float(ro.get("post_timeout", 60.0)), 5.0)
    url = f"http://{host}:{port}/api/scene"
    try:
        with httpx.Client(timeout=timeout) as client:
            client.get(url)
    except httpx.HTTPError as exc:
        logger.error(
            "Remote cadquery-web-viewer not reachable at http://%s:%s/ (%s). "
            "Start it in another terminal: cadquery-web-viewer --host %s --port %s",
            host,
            port,
            exc,
            host,
            port,
        )
        sys.exit(1)


def _glb_bytes_via_viewer_render(obj, config, name: str) -> bytes:
    from cadquery_web_viewer import render

    tess_kw = _viewer_tessellation_kwargs(config)
    glbs = render(obj, names=name, **tess_kw)
    return glbs[0]


def _cadquery_web_viewer_show(config, names: Union[str, List[str], None], *objs) -> None:
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
    colored,
) -> None:
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


def _assembly_to_glb_bytes(assy: cq.Assembly, *, tolerance: float, angular: float) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as tf:
        tmp_path = tf.name
    try:
        assy.export(
            tmp_path,
            exportType="GLB",
            tolerance=float(tolerance),
            angularTolerance=float(angular),
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
    tolerance: float,
    angular_tolerance: float,
    stl_ascii: bool,
) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tf_stl:
        tmp_stl_path = tf_stl.name
    with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as tf_glb:
        tmp_glb_path = tf_glb.name
    try:
        cq.exporters.export(
            solid,
            tmp_stl_path,
            tolerance=float(tolerance),
            angularTolerance=float(angular_tolerance),
            opt={"ascii": bool(stl_ascii)},
        )
        loaded = trimesh.load(tmp_stl_path)
        mesh = loaded.dump(concatenate=True) if isinstance(loaded, trimesh.Scene) else loaded
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
    image_path: Path,
    preview_job: RenderingExportJob,
) -> None:
    with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as tf:
        tmp_glb = Path(tf.name)
    try:
        tmp_glb.write_bytes(glb_bytes)
        render_glb_to_image(tmp_glb, Path(image_path), preview_job)
    finally:
        try:
            os.unlink(tmp_glb)
        except OSError:
            pass


def _export_obj_from_glb(glb_bytes: bytes, output_path: Path, obj_job: RenderingExportJob) -> None:
    ext = output_path.suffix.lower()
    if ext != ".obj":
        logger.error("OBJ export only supports .obj extension (got %s).", ext)
        sys.exit(2)
    try:
        scene_or_mesh = trimesh.load(trimesh.util.wrap_as_stream(glb_bytes), file_type="glb")
    except Exception as exc:
        logger.error("Failed to load GLB for OBJ export: %r", exc)
        sys.exit(2)
    mesh = scene_or_mesh.dump(concatenate=True) if isinstance(scene_or_mesh, trimesh.Scene) else scene_or_mesh
    if obj_job.unit_scale_mm_to_m:
        mesh.apply_scale(0.001)
    if hasattr(mesh, "remove_degenerate_faces"):
        mesh.remove_degenerate_faces()
    if hasattr(mesh, "remove_unreferenced_vertices"):
        mesh.remove_unreferenced_vertices()
    if hasattr(mesh, "merge_vertices"):
        mesh.merge_vertices()
    if obj_job.watertight_required and not mesh.is_watertight:
        logger.error("Mesh export aborted: generated mesh is not watertight.")
        sys.exit(2)
    target = obj_job.target_face_count
    if target is not None and len(mesh.faces) > target > 0:
        try:
            mesh = mesh.simplify_quadratic_decimation(target)
        except Exception as exc:
            logger.warning("Mesh decimation failed (%r); continuing with original mesh.", exc)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(str(output_path), file_type="obj")
    logger.info("Exported mesh OBJ to %s", output_path)


class PartArtifacts:
    """Lazy builders for tessellated artifacts and bundle export emitters."""

    def __init__(
        self,
        part: Union[cq.Workplane, cq.Solid, cq.Compound, cq.Assembly],
        config: Any,
        *,
        path=None,
        aux=None,
        face_kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.part = part
        self.config = config
        self.path = path
        self.aux = aux
        self.face_kwargs = face_kwargs or {}
        self._solid: Optional[Any] = None
        self._assy: Optional[cq.Assembly] = None
        self._is_assembly = False
        self._normalized = False
        self.stl_written_path: Optional[Path] = None
        self.glb_bytes: Optional[bytes] = None

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

    def _tolerances(self) -> tuple[float, float]:
        r = self.config.rendering
        return float(r.tolerance), float(r.angular_tolerance)

    def _export_solid_to_stl(
        self,
        dest: Path,
        *,
        tolerance: float,
        angular_tolerance: float,
        ascii: bool = False,
    ) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        cq.exporters.export(
            self.solid,
            str(dest),
            tolerance=float(tolerance),
            angularTolerance=float(angular_tolerance),
            opt={"ascii": bool(ascii)},
        )

    def ensure_stl_at(self, dest: Path, *, stl_ascii: bool = True) -> Path:
        if self.stl_written_path == dest and dest.exists():
            return dest
        tol, ang = self._tolerances()
        self._export_solid_to_stl(dest, tolerance=tol, angular_tolerance=ang, ascii=stl_ascii)
        self.stl_written_path = dest
        return dest

    def ensure_glb_bytes(self, *, for_viewer: bool = False) -> bytes:
        if self.glb_bytes is not None:
            return self.glb_bytes
        tol, ang = self._tolerances()
        if for_viewer and self.config.viewer_enabled:
            self.glb_bytes = _glb_bytes_via_viewer_render(
                self.solid, self.config, self.config.name or "Knot"
            )
        elif self.is_assembly and self.assy is not None:
            self.glb_bytes = _assembly_to_glb_bytes(self.assy, tolerance=tol, angular=ang)
        else:
            stl_job = next((j for j in self.config.rendering.exports if j.format == "stl"), None)
            stl_ascii = bool(getattr(stl_job, "stl_ascii", True)) if stl_job else True
            self.glb_bytes = _solid_to_glb_bytes(
                self.solid,
                tolerance=tol,
                angular_tolerance=ang,
                stl_ascii=stl_ascii,
            )
        return self.glb_bytes

    def _preview_settings_for_job(self, job: ExportJob) -> RenderingExportJob:
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        for cfg_job in self.config.rendering.exports:
            if cfg_job.match_key == job.match_key and cfg_job.format == "preview":
                return cfg_job
        return RenderingExportJob({"format": "preview", **job.settings}, project_root)

    def _obj_settings_for_job(self, job: ExportJob) -> RenderingExportJob:
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        for cfg_job in self.config.rendering.exports:
            if cfg_job.match_key == job.match_key and cfg_job.format == "obj":
                return cfg_job
        return RenderingExportJob({"format": "obj", **job.settings}, project_root)

    def execute_job(self, job: ExportJob) -> None:
        stats = self.config.render_stats
        stage = f"render_pipeline.job.{job.format}.{job.resolved_path.name}"
        cm = stats.record_stage(stage) if stats is not None else nullcontext()
        with cm:
            if job.is_dependency_only:
                logger.info(
                    "Writing %s (required by %s; %s export disabled in config)",
                    job.resolved_path.name,
                    job.dependency_of,
                    job.format,
                )
            self._execute_job_inner(job)

    def _execute_job_inner(self, job: ExportJob) -> None:
        tol, ang = self._tolerances()
        path = job.resolved_path
        path.parent.mkdir(parents=True, exist_ok=True)

        if job.format == "stl":
            stl_ascii = bool(job.settings.get("stl_ascii", True))
            self.ensure_stl_at(path, stl_ascii=stl_ascii)
            logger.info("Exported STL to %s", path)
            return

        if job.format == "step":
            if self.is_assembly and self.assy is not None:
                self.assy.export(
                    str(path),
                    exportType="STEP",
                    mode="default",
                    write_pcurves=True,
                    precision_mode=0,
                )
            else:
                cq.exporters.export(self.solid, str(path), tolerance=tol, angularTolerance=ang)
            logger.info("Exported STEP to %s", path)
            return

        if job.format == "3mf":
            self.ensure_stl_at(path, stl_ascii=False)
            logger.info("Exported 3MF to %s", path)
            return

        if job.format == "glb":
            path.write_bytes(self.ensure_glb_bytes())
            logger.info("Exported GLB to %s", path)
            return

        if job.format == "gltf":
            glb = self.ensure_glb_bytes()
            scene_or_mesh = trimesh.load(trimesh.util.wrap_as_stream(glb), file_type="glb")
            mesh = scene_or_mesh.dump(concatenate=True) if isinstance(scene_or_mesh, trimesh.Scene) else scene_or_mesh
            mesh.export(str(path), file_type="gltf")
            logger.info("Exported GLTF to %s", path)
            return

        if job.format == "obj":
            obj_job = self._obj_settings_for_job(job)
            _export_obj_from_glb(self.ensure_glb_bytes(), path, obj_job)
            return

        if job.format == "preview":
            preview_cfg = self._preview_settings_for_job(job)
            glb = self.ensure_glb_bytes()
            _render_glb_bytes_to_image(glb, path, preview_cfg)
            return

        if job.format == "config":
            self._write_config_yaml(path)
            return

        if job.format == "stats":
            if self.config.render_stats is not None:
                self.config.render_stats.finalize_total_duration()
                self.config.render_stats.write_csv(path)
                logger.info("Exported stats CSV to %s", path)
            return

        logger.error("Unknown export format %r", job.format)
        sys.exit(2)

    def _write_config_yaml(self, path: Path) -> None:
        data = dict(self.config._config_data)
        rendering = dict(data.get("rendering") or {})
        rendering["name"] = self.config.run_name
        data["rendering"] = rendering
        path.write_text(
            yaml.safe_dump(data, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
        logger.info("Exported config YAML to %s", path)

    def emit_viewer(self, name: str) -> None:
        if not self.config.viewer_enabled:
            return
        if self.is_assembly and self.assy is not None:
            from .color_palette import colored_assembly_shapes, iter_assembly_leaf_solids

            leaves = iter_assembly_leaf_solids(self.assy)
            if len(leaves) >= 2:
                preview_job = self.config.rendering.first_preview_job()
                base_rgb = preview_job._color_rgb if preview_job else (0.7, 0.7, 0.7)
                part_names, colored = colored_assembly_shapes(self.assy, base_rgb)
                _cadquery_web_viewer_show_colored_parts(self.config, part_names, colored)
                return
        glb = self.ensure_glb_bytes(for_viewer=True)
        _cadquery_web_viewer_show(self.config, name, glb)


def deliver_part(
    part: Union[cq.Workplane, cq.Solid, cq.Compound, cq.Assembly],
    config: Any,
    *,
    path=None,
    aux=None,
    face_kwargs: Optional[Dict[str, Any]] = None,
) -> None:
    """Build render bundle artifacts and emit all configured export jobs."""
    if config.render_stats is None:
        from .render_stats import RenderStats

        config.render_stats = RenderStats()
        config.render_stats.populate_config_sources(
            base_path=getattr(config, "config_base_path", None),
            local_path=getattr(config, "config_local_path", None),
            overlay_path=getattr(config, "config_path", None),
        )
        config.render_stats.populate_git_info()
        config.render_stats.add_stat("render.run_name", config.run_name, "Resolved run name")
        config.render_stats.add_stat(
            "render.bundle_dir",
            str(config.render_bundle_dir),
            "Render bundle output directory",
        )

    plan = RenderPlanner.from_config(config)
    if not plan.has_side_effects:
        from .render_logging import discard_render_log_buffer

        discard_render_log_buffer()
        return

    if plan.want_viewer:
        _ensure_remote_viewer_reachable(config)

    plan.bundle_dir.mkdir(parents=True, exist_ok=True)
    from .render_logging import finalize_render_log

    finalize_render_log(plan.bundle_dir / f"{config.render_bundle_stem}.log")
    ctx = PartArtifacts(part, config, path=path, aux=aux, face_kwargs=face_kwargs)
    ctx._normalize()

    for job in plan.execution_order:
        ctx.execute_job(job)

    name = config.name or "Knot"
    ctx.emit_viewer(name)

    n_files = sum(1 for j in plan.jobs if j.resolved_path.exists())
    logger.info("Wrote render bundle to %s/ (%d files)", plan.bundle_dir, n_files)
