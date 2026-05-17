"""
Shared utilities for creating knots from paths using loft operations in CadQuery.

This module provides a generic framework for creating knot variants by:
1. Taking a path (Wire) - defined in each knot variant file
2. Creating frames along the path
3. Generating sections at each frame (using any section generator function)
4. Lofting the sections together

This abstracts away the complexity of section management and loft operations,
making it easy to create new knot variants. Each knot variant file should define
its own unique path, while this module handles the shared lofting logic.
"""

import argparse
import logging
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple, Union
import numpy as np

import cadquery as cq
from cadquery.func import Plane, Location, sweep
import trimesh
from .cache_utils import cache_key_for_part, cache_path_for_part, preview_stl_path_for_part
from .led_circle import (
    _pyramid_ridge_height_at_t,
    create_led_circle_face,
    create_solid_circle_face,
    create_square_face,
)
from .path_utils import sample_path_for_profiles, sample_path_for_pyramid_profiles
from .preview import render_glb_to_image, render_stl_to_image
from .print_segmentation import build_segmented_tube_assembly

logger = logging.getLogger(__name__)


def _viewer_tessellation_kwargs(config) -> Dict[str, float]:
    """Tessellation options for cadquery-web-viewer ``show`` / ``render`` (preview mesh quality)."""
    ps = getattr(config, "preview_settings", None)
    if ps is None:
        return {}
    return {
        "tolerance": float(ps.mesh_tolerance),
        "angular_tolerance": float(ps.mesh_angular_tolerance),
    }


def _glb_bytes_via_viewer_render(obj, config, name: str) -> bytes:
    """Tessellate a CAD object to GLB using the same path as cadquery-web-viewer 2.x ``show``."""
    from cadquery_web_viewer import render

    glbs = render(obj, names=name, **_viewer_tessellation_kwargs(config))
    return glbs[0]


def _cadquery_web_viewer_show(config, name: str, *objs) -> None:
    """Send geometry to cadquery-web-viewer (embedded or remote per config)."""
    from cadquery_web_viewer import show

    tess_kw = _viewer_tessellation_kwargs(config)
    st = config.viewer_server_type
    block = bool(getattr(config, "viewer_block_until_disconnect", False))
    if st == "remote":
        ro = getattr(config, "viewer_remote_options", None) or {}
        show(
            *objs,
            names=name,
            server_type="remote",
            remote_options=ro,
            block_until_disconnect=False,
            **tess_kw,
        )
        logger.info(
            "Posted %s to cadquery-web-viewer at http://%s:%s/",
            name,
            ro.get("host", "localhost"),
            ro.get("port", 32323),
        )
        return
    so = getattr(config, "viewer_server_options", None) or {}
    show(
        *objs,
        names=name,
        server_type="in-process",
        server_options=so,
        block_until_disconnect=block,
        **tess_kw,
    )
    logger.info(
        "cadquery-web-viewer (%s): http://%s:%s/",
        name,
        so.get("host", "127.0.0.1"),
        so.get("port", 32323),
    )


def _exit_if_remote_viewer_idle(config, *, did_followup_glb_work: bool) -> None:
    """
    Remote uploads finish quickly, but interpreter teardown can still block (native threads).
    When this call has no GLB-cache / mesh / preview follow-up, exit immediately so the CLI
    returns without waiting on OCP/NumPy shutdown.
    """
    if did_followup_glb_work:
        return
    if not getattr(config, "viewer_enabled", False):
        return
    if getattr(config, "viewer_server_type", None) != "remote":
        return
    logger.debug("Remote viewer done with no local GLB follow-up; exiting process.")
    sys.exit(0)


# ============================================================================
# COMMAND LINE PARSING
# ============================================================================

def parse_args(description: str = "Create and render a knot model"):
    """
    Parse command line arguments for knot rendering.
    
    Args:
        description: Description for the argument parser
        
    Returns:
        argparse.Namespace: Parsed arguments with:
            - export: Optional filepath to export the model to (STL, STEP format)
            - server: Legacy flag to enable web viewing (uses config server.viewer)
            - viewer: Optional explicit viewer mode (off / embedded / embedded-block / remote)
            - verbose: Boolean flag to enable DEBUG level logging
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        '--export',
        type=str,
        metavar='FILEPATH',
        help='Export the model to the specified file path. Supported formats: .stl, .step, .stp, .3mf'
    )
    parser.add_argument(
        '--server',
        action='store_true',
        help='Enable browser preview using server.viewer settings from config.yaml',
    )
    parser.add_argument(
        '--viewer',
        type=str,
        choices=('off', 'embedded', 'embedded-block', 'remote'),
        default=None,
        metavar='MODE',
        help=(
            'Web preview: off | embedded (in-process server) | embedded-block '
            '(wait until browser disconnect) | remote (HTTP to cadquery-web-viewer). '
            'When set, overrides server.viewer.mode from config.'
        ),
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose (DEBUG level) logging'
    )
    parser.add_argument(
        '--no-cache',
        action='store_true',
        help='Never use cache; always sweep and render'
    )
    parser.add_argument(
        '--only-cache',
        action='store_true',
        help='Only render if a cached GLB exists; do not sweep on cache miss'
    )
    parser.add_argument(
        '--preview',
        type=str,
        metavar='FILEPATH',
        help='Generate a preview image for the model and save to the specified file path'
    )
    parser.add_argument(
        '--output-mesh',
        type=str,
        metavar='FILEPATH',
        help='Export a simulation-focused mesh (currently OBJ only) using trimesh'
    )
    parser.add_argument(
        '--export-parts',
        type=str,
        metavar='PARTS',
        help=(
            "Optional multi-part export selector (comma-separated). "
            "Supported tokens: assembly,tube,clamp_a,clamp_b,clamp_halves,all. "
            "Only applies to knots that build an assembly."
        ),
    )
    parser.add_argument(
        '--export-parts-dir',
        type=str,
        metavar='DIR',
        help="Directory to write per-part exports when --export-parts is used.",
    )
    args = parser.parse_args()
    
    # Configure logging if verbose flag is set
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    
    return args


# ============================================================================
# PYKNOT SCALING UTILITIES
# ============================================================================

def scale_pyknot_points(
    points: np.ndarray,
    width: float,
    height: float,
    length: float,
    padding: Union[float, Tuple[float, float, float]] = 0.0,
    preserve_aspect_ratio: bool = True,
) -> np.ndarray:
    """
    Scale pyknot points to fit within a bounding box while preserving aspect ratio.
    
    Calculates the bounding box of the input points and scales them uniformly
    to fit within the specified width, height, and length constraints,
    optionally applying padding on each dimension before scaling.
    
    Args:
        points: numpy array of shape (n, 3) containing (x, y, z) coordinates
        width: Target width for the x dimension (mm)
        height: Target height for the y dimension (mm)
        length: Target length for the z dimension (mm)
        padding: Optional padding to subtract from (width, height, length).
                 If a single float, the same padding is applied to all three
                 dimensions. If a tuple of three numbers, interpreted as
                 (width_padding, height_padding, length_padding).
        preserve_aspect_ratio: When True (default), uses a uniform scale factor
            so the knot preserves its proportions. When False, scales each axis
            independently to fill the (padded) bounding box.
        
    Returns:
        numpy array of scaled points with the same shape as input
    """
    # Calculate the bounding box of the original points
    min_x, max_x = points[:, 0].min(), points[:, 0].max()
    min_y, max_y = points[:, 1].min(), points[:, 1].max()
    min_z, max_z = points[:, 2].min(), points[:, 2].max()
    
    # Calculate the spans (ranges) for each dimension
    span_x = max_x - min_x
    span_y = max_y - min_y
    span_z = max_z - min_z
    
    # Normalize padding to per-dimension values
    if isinstance(padding, (tuple, list)) and len(padding) == 3:
        pad_w, pad_h, pad_l = padding
    else:
        pad_w = pad_h = pad_l = float(padding)

    effective_width = width - pad_w
    effective_height = height - pad_h
    effective_length = length - pad_l

    # Calculate scale factors to fit within effective width (x), height (y),
    # and length (z), after padding
    scale_x = effective_width / span_x if span_x > 0 else 1.0
    scale_y = effective_height / span_y if span_y > 0 else 1.0
    scale_z = effective_length / span_z if span_z > 0 else 1.0

    if preserve_aspect_ratio:
        # Use the minimum scale factor to preserve aspect ratio and ensure it fits
        scale_factor = min(scale_x, scale_y, scale_z)
        scaled = points * scale_factor
    else:
        # Scale each axis independently to fill the (padded) bounding box
        scales = np.array([scale_x, scale_y, scale_z], dtype=float)
        scaled = points * scales

    # Translate so that the scaled points lie entirely in the positive octant
    # (i.e. the minimum x, y, z coordinates are at 0).
    min_scaled = scaled.min(axis=0)
    translated = scaled - min_scaled

    return [(float(p[0]), float(p[1]), float(p[2])) for p in translated]


# ============================================================================
# DISPLAY AND EXPORT UTILITIES
# ============================================================================

def _maybe_export_mesh_from_glb(glb_bytes: bytes, config) -> None:
    """
    Export an OBJ mesh from GLB bytes when `--output-mesh` is set.
    """
    mesh_cfg = getattr(config, "mesh", None)
    output_path = getattr(mesh_cfg, "filepath", None) if mesh_cfg else None
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

    # Unit scaling mm -> m when requested.
    if mesh_cfg.unit_scale_mm_to_m:
        mesh.apply_scale(0.001)

    # Basic cleanup for robustness (API varies slightly by trimesh version).
    if hasattr(mesh, "remove_degenerate_faces"):
        mesh.remove_degenerate_faces()
    if hasattr(mesh, "remove_unreferenced_vertices"):
        mesh.remove_unreferenced_vertices()
    if hasattr(mesh, "merge_vertices"):
        mesh.merge_vertices()

    # Watertightness check.
    if mesh_cfg.watertight_required and not mesh.is_watertight:
        logger.error("Mesh export aborted: generated mesh is not watertight.")
        sys.exit(2)

    # Optional decimation.
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
    """
    Export an assembly to GLB bytes using CadQuery (tempfile-backed).
    """
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as tf:
        tmp_path = tf.name
    try:
        # Use preview tessellation settings for smoothness when viewing/caching.
        tol = getattr(config, "preview_settings", None)
        tol_val = getattr(tol, "mesh_tolerance", None)
        ang_val = getattr(tol, "mesh_angular_tolerance", None)
        if tol_val is None:
            tol_val = config.export.tolerance
        if ang_val is None:
            ang_val = config.export.angular_tolerance

        assy.export(
            tmp_path,
            exportType="GLB",
            tolerance=float(tol_val),
            angularTolerance=float(ang_val),
        )
        with open(tmp_path, "rb") as f:
            return f.read()
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
    """
    Generate GLB bytes headlessly from a CadQuery solid/workplane using:
    CadQuery STL export -> trimesh STL load -> trimesh GLB export.
    """
    import tempfile

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
        with open(tmp_glb_path, "rb") as f:
            return f.read()
    finally:
        for p in (tmp_stl_path, tmp_glb_path):
            try:
                os.unlink(p)
            except OSError:
                pass


def render_part(
    part: Union[cq.Workplane, cq.Solid, cq.Compound, bytes],
    config,
    cache_path: Optional[Union[str, Path]] = None,
    path=None,
    aux=None,
    face_kwargs: Optional[dict] = None,
    preview_stl_path: Optional[Path] = None,
    preview_image_path: Optional[Union[str, Path]] = None,
):
    """
    Render the part based on configuration.

    Key behavior:
    - When ``config.viewer_enabled`` is false: never call ``cadquery_web_viewer`` for display.
      All GLB/mesh outputs are generated headlessly via CadQuery + Trimesh.
    - When ``config.viewer_enabled`` is true: models are sent with ``cadquery_web_viewer.show``
      (embedded or remote per ``config.yaml`` / ``--viewer``).
    """
    name = config.name or "Knot"
    is_glb_bytes = isinstance(part, bytes)

    if not is_glb_bytes and cache_path is None and path is not None:
        cache_path = cache_path_for_part(
            config, path, aux=aux, face_kwargs=face_kwargs or {}
        )

    use_viewer = bool(getattr(config, "viewer_enabled", False))

    if is_glb_bytes:
        glb_bytes = part

        if config.export.filepath:
            file_ext = os.path.splitext(config.export.filepath)[1].lower()
            export_dir = os.path.dirname(config.export.filepath)
            if export_dir and not os.path.exists(export_dir):
                os.makedirs(export_dir, exist_ok=True)

            if file_ext == ".glb":
                with open(config.export.filepath, "wb") as f:
                    f.write(glb_bytes)
                logger.info("Exported %s to %s (GLB format)", name, config.export.filepath)
            elif file_ext == ".gltf":
                scene_or_mesh = trimesh.load(
                    trimesh.util.wrap_as_stream(glb_bytes), file_type="glb"
                )
                if isinstance(scene_or_mesh, trimesh.Scene):
                    mesh = scene_or_mesh.dump(concatenate=True)
                else:
                    mesh = scene_or_mesh
                mesh.export(str(config.export.filepath), file_type="gltf")
                logger.info("Exported %s to %s (GLTF format)", name, config.export.filepath)
            else:
                logger.error(
                    "Export format %s not supported when using cached GLB",
                    file_ext,
                )
                sys.exit(2)

            _maybe_export_mesh_from_glb(glb_bytes, config)
            return

        # No export: browser preview when viewer is enabled.
        if use_viewer:
            _cadquery_web_viewer_show(config, name, glb_bytes)
        _maybe_export_mesh_from_glb(glb_bytes, config)
        mesh_fp = getattr(getattr(config, "mesh", None), "filepath", None)
        _exit_if_remote_viewer_idle(config, did_followup_glb_work=bool(mesh_fp))
        return

    is_assembly = isinstance(part, cq.Assembly)

    if is_assembly:
        assy: cq.Assembly = part

        if config.export.filepath:
            export_dir = os.path.dirname(config.export.filepath)
            if export_dir and not os.path.exists(export_dir):
                os.makedirs(export_dir, exist_ok=True)
            file_ext = os.path.splitext(config.export.filepath)[1].lower()

            if file_ext in [".step", ".stp"]:
                assy.export(
                    config.export.filepath,
                    exportType="STEP",
                    mode="default",
                    write_pcurves=True,
                    precision_mode=0,
                )
                logger.info("Exported %s to %s (STEP assembly)", name, config.export.filepath)
                return

            if file_ext in [".glb", ".gltf"]:
                assy.export(
                    config.export.filepath,
                    exportType="GLB" if file_ext == ".glb" else "GLTF",
                    tolerance=config.export.tolerance,
                    angularTolerance=config.export.angular_tolerance,
                )
                logger.info("Exported %s to %s (GLTF/GLB assembly)", name, config.export.filepath)

                # Optionally cache GLB bytes for preview flows.
                if (
                    cache_path is not None
                    and not getattr(config, "no_cache", False)
                    and file_ext == ".glb"
                ):
                    try:
                        cache_path_w = (
                            Path(cache_path)
                            if not isinstance(cache_path, Path)
                            else cache_path
                        )
                        cache_path_w.parent.mkdir(parents=True, exist_ok=True)
                        with open(config.export.filepath, "rb") as f:
                            glb_data = f.read()
                        with open(cache_path_w, "wb") as f:
                            f.write(glb_data)
                        logger.debug("Wrote cache %s", cache_path_w)
                    except Exception:
                        pass
                return

            if file_ext in [".stl", ".3mf"]:
                solid = assy.toCompound()
                cq.exporters.export(
                    solid,
                    config.export.filepath,
                    tolerance=config.export.tolerance,
                    angularTolerance=config.export.angular_tolerance,
                    opt={"ascii": config.export.stl_ascii} if file_ext == ".stl" else None,
                )
                logger.info(
                    "Exported %s to %s (%s fused)",
                    name,
                    config.export.filepath,
                    file_ext.upper().lstrip("."),
                )
                return

            logger.error(
                "Unknown export file extension '%s' for assembly. Supported: .step, .stp, .stl, .3mf, .glb, .gltf.",
                file_ext,
            )
            sys.exit(2)

        # Preview-only (no export): tessellate a fused compound to STL and render image.
        if getattr(config, "preview_filepath", None) is not None:
            compound = assy.toCompound()
            tol = config.preview_settings.mesh_tolerance
            ang_tol = config.preview_settings.mesh_angular_tolerance
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tf:
                tmp_stl = tf.name
            try:
                cq.exporters.export(
                    compound,
                    tmp_stl,
                    tolerance=tol,
                    angularTolerance=ang_tol,
                    opt={"ascii": False},
                )
                render_stl_to_image(
                    Path(tmp_stl),
                    Path(config.preview_filepath),
                    config.preview_settings,
                )
            finally:
                if os.path.exists(tmp_stl):
                    try:
                        os.unlink(tmp_stl)
                    except OSError:
                        pass
            return

        # No export path: browser preview when viewer is enabled.
        compound = assy.toCompound()
        viewer_glb: Optional[bytes] = None
        if use_viewer:
            viewer_glb = _glb_bytes_via_viewer_render(compound, config, name)
            _cadquery_web_viewer_show(config, name, viewer_glb)

        want_glb_for_cache = cache_path is not None and not getattr(config, "no_cache", False)
        want_glb_for_mesh = getattr(getattr(config, "mesh", None), "filepath", None) is not None
        want_glb_for_preview = getattr(config, "preview_filepath", None) is not None

        did_followup = False
        if cache_path is not None and (
            want_glb_for_cache or want_glb_for_mesh or want_glb_for_preview
        ):
            did_followup = True
            if use_viewer and viewer_glb is None and getattr(config, "viewer_server_type", None) == "remote":
                logger.info(
                    "Writing local GLB (and optional preview) after remote upload; "
                    "this tessellates again and may take a while; "
                    "pass --no-cache to skip updating the GLB cache for a fast exit after remote."
                )
            glb_data = (
                viewer_glb
                if viewer_glb is not None
                else _assembly_to_glb_bytes(assy, config)
            )
            cache_path_w = (
                Path(cache_path) if not isinstance(cache_path, Path) else cache_path
            )
            cache_path_w.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path_w, "wb") as f:
                f.write(glb_data)
            logger.debug("Wrote cache %s", cache_path_w)

            if want_glb_for_preview:
                render_glb_to_image(
                    cache_path_w,
                    Path(config.preview_filepath),
                    config.preview_settings,
                )
            if want_glb_for_mesh:
                _maybe_export_mesh_from_glb(glb_data, config)

        _exit_if_remote_viewer_idle(config, did_followup_glb_work=did_followup)
        return

    # Part is a solid/workplane
    if isinstance(part, (cq.Solid, cq.Compound)):
        solid = part
    elif hasattr(part, "val"):
        solid = part.val()
    else:
        solid = part

    if config.export.filepath:
        export_dir = os.path.dirname(config.export.filepath)
        if export_dir and not os.path.exists(export_dir):
            os.makedirs(export_dir, exist_ok=True)
        file_ext = os.path.splitext(config.export.filepath)[1].lower()

        if file_ext == ".stl":
            cq.exporters.export(
                solid,
                config.export.filepath,
                tolerance=config.export.tolerance,
                angularTolerance=config.export.angular_tolerance,
                opt={"ascii": config.export.stl_ascii},
            )
            logger.info("Exported %s to %s (STL format)", name, config.export.filepath)
            if preview_image_path:
                render_stl_to_image(
                    Path(config.export.filepath),
                    Path(preview_image_path),
                    config.preview_settings,
                )
            return

        if file_ext in [".step", ".stp"]:
            cq.exporters.export(
                solid,
                config.export.filepath,
                tolerance=config.export.tolerance,
                angularTolerance=config.export.angular_tolerance,
            )
            logger.info("Exported %s to %s (STEP format)", name, config.export.filepath)
            if preview_image_path and preview_stl_path is not None:
                cq.exporters.export(
                    solid,
                    str(preview_stl_path),
                    tolerance=config.export.tolerance,
                    angularTolerance=config.export.angular_tolerance,
                    opt={"ascii": config.export.stl_ascii},
                )
                render_stl_to_image(
                    preview_stl_path,
                    Path(preview_image_path),
                    config.preview_settings,
                )
            return

        if file_ext == ".3mf":
            cq.exporters.export(
                solid,
                config.export.filepath,
                tolerance=config.export.tolerance,
                angularTolerance=config.export.angular_tolerance,
            )
            logger.info("Exported %s to %s (3MF format)", name, config.export.filepath)
            if preview_image_path and preview_stl_path is not None:
                cq.exporters.export(
                    solid,
                    str(preview_stl_path),
                    tolerance=config.export.tolerance,
                    angularTolerance=config.export.angular_tolerance,
                    opt={"ascii": config.export.stl_ascii},
                )
                render_stl_to_image(
                    preview_stl_path,
                    Path(preview_image_path),
                    config.preview_settings,
                )
            return

        if file_ext in [".glb", ".gltf"]:
            glb_bytes = _solid_to_glb_bytes(
                solid,
                config=config,
                stl_tolerance=config.export.tolerance,
                stl_angular_tolerance=config.export.angular_tolerance,
                stl_ascii=config.export.stl_ascii,
            )

            if file_ext == ".glb":
                with open(config.export.filepath, "wb") as f:
                    f.write(glb_bytes)
                logger.info("Exported %s to %s (GLB format)", name, config.export.filepath)
            else:
                scene_or_mesh = trimesh.load(
                    trimesh.util.wrap_as_stream(glb_bytes), file_type="glb"
                )
                if isinstance(scene_or_mesh, trimesh.Scene):
                    mesh = scene_or_mesh.dump(concatenate=True)
                else:
                    mesh = scene_or_mesh
                mesh.export(str(config.export.filepath), file_type="gltf")
                logger.info(
                    "Exported %s to %s (GLTF format)", name, config.export.filepath
                )

            # Write cache (GLB bytes) when reuse is enabled.
            if cache_path is not None and not getattr(config, "no_cache", False):
                cache_path_w = (
                    Path(cache_path)
                    if not isinstance(cache_path, Path)
                    else cache_path
                )
                cache_path_w.parent.mkdir(parents=True, exist_ok=True)
                with open(cache_path_w, "wb") as f:
                    f.write(glb_bytes)
                logger.debug("Wrote cache %s", cache_path_w)

                if preview_image_path and cache_path_w.exists():
                    render_glb_to_image(
                        cache_path_w,
                        Path(preview_image_path),
                        config.preview_settings,
                    )

            _maybe_export_mesh_from_glb(glb_bytes, config)
            return

        logger.error(
            "Unknown export file extension '%s'. Supported: .stl, .step, .stp, .3mf, .glb, .gltf.",
            file_ext,
        )
        sys.exit(2)

    # Display path (no export): browser preview when viewer is enabled.
    viewer_glb: Optional[bytes] = None
    if use_viewer:
        viewer_glb = _glb_bytes_via_viewer_render(solid, config, name)
        _cadquery_web_viewer_show(config, name, viewer_glb)

    want_glb_for_cache = cache_path is not None and not getattr(config, "no_cache", False)
    want_glb_for_mesh = getattr(getattr(config, "mesh", None), "filepath", None) is not None
    did_followup = False
    if cache_path is not None and (want_glb_for_cache or want_glb_for_mesh):
        did_followup = True
        if (
            use_viewer
            and viewer_glb is None
            and getattr(config, "viewer_server_type", None) == "remote"
        ):
            logger.info(
                "Writing local GLB cache after remote upload; "
                "this tessellates again and may take a while; "
                "pass --no-cache to skip updating the GLB cache for a fast exit after remote."
            )
        if viewer_glb is not None:
            glb_bytes = viewer_glb
        else:
            glb_bytes = _solid_to_glb_bytes(
                solid,
                config=config,
                stl_tolerance=config.preview_settings.mesh_tolerance,
                stl_angular_tolerance=config.preview_settings.mesh_angular_tolerance,
                stl_ascii=False,
            )

        cache_path_w = (
            Path(cache_path) if not isinstance(cache_path, Path) else cache_path
        )
        cache_path_w.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path_w, "wb") as f:
            f.write(glb_bytes)
        logger.debug("Wrote cache %s", cache_path_w)

        if want_glb_for_mesh:
            _maybe_export_mesh_from_glb(glb_bytes, config)

    _exit_if_remote_viewer_idle(config, did_followup_glb_work=did_followup)


def build_tube_from_path(path, config, aux=None, face_kwargs: Optional[dict] = None):
    """
    Build (sweep) the tube solid from a path using the configured face type.

    This is the shared geometry builder used by `draw_part`, and can also be used
    by callers that want to post-process the tube solid into an assembly.
    """
    face_kwargs_dict = face_kwargs or {}
    face_type = config.tube_settings.face_type
    face_kw = config.tube_settings.to_led_circle_face_kwargs(
        orient_to_path=path,
        **face_kwargs_dict,
    )

    if face_type == 'led_circle_diffusion_pyramids':
        num_samples = 30
        samples = sample_path_for_profiles(path, num_samples=num_samples)
        path_length = samples[-1]['arc_length'] if samples else 0.0

        dr = config.tube_settings.diffusion_ridges
        if not dr:
            raise ValueError("led_circle_diffusion_pyramids requires diffusion_ridges in config")
        ridge_width = dr['ridge_width']
        ridge_spacing = dr['ridge_spacing']
        ridge_depth = dr['ridge_depth']

        n_samples = len(samples)
        logger.debug(
            "build_tube_from_path (led_circle_diffusion_pyramids): building %d section faces, "
            "path_length=%.2f mm",
            n_samples,
            path_length,
        )

        faces = []
        min_ridge = max(0.5, ridge_depth * 0.2)
        for idx, sample in enumerate(samples):
            t = sample['t']
            ridge_height = max(
                min_ridge,
                _pyramid_ridge_height_at_t(
                    t, path_length, ridge_width, ridge_spacing, ridge_depth
                ),
            )
            dr_at_t = {**dr, 'ridge_height': ridge_height}
            face_kw_at_t = {**face_kw, 'orient_to_path': None, 'diffusion_ridges': dr_at_t}
            face_i = create_led_circle_face(**face_kw_at_t)
            plane = Plane(origin=sample['point'], normal=sample['tangent'])
            face_i = face_i.moved(Location(plane))
            # Sort faces by area (descending) for consistent ordering across sections.
            sorted_faces = sorted(face_i.faces(), key=lambda f: f.Area(), reverse=True)
            from cadquery.func import compound
            face_i = compound(sorted_faces)
            faces.append(face_i)
            step = max(1, n_samples // 10)
            if (
                n_samples <= 20
                or idx == 0
                or idx == n_samples - 1
                or (idx + 1) % step == 0
            ):
                logger.debug(
                    "build_tube_from_path (led_circle_diffusion_pyramids): face %d/%d",
                    idx + 1,
                    n_samples,
                )

        logger.debug(
            "build_tube_from_path (led_circle_diffusion_pyramids): calling sweep (%d faces)",
            len(faces),
        )
        try:
            return sweep(faces, path, aux=aux)
        except Exception as e:
            raise RuntimeError(
                f"led_circle_diffusion_pyramids multisection sweep failed: {e!r}. "
                f"num_sections={len(faces)}, path_length={path_length:.1f}mm, "
                f"ridge_depth={ridge_depth}, ridge_width={ridge_width}, ridge_spacing={ridge_spacing}"
            ) from e

    if face_type == 'solid_circle_pyramid':
        dr = config.tube_settings.diffusion_ridges or {}
        ridge_width = dr.get('ridge_width', 2.0)
        ridge_spacing = dr.get('ridge_spacing', 1.0)
        ridge_depth = dr.get('ridge_depth', 2.5)
        pitch = ridge_width + ridge_spacing
        sections_per_pyramid = 5

        samples = sample_path_for_pyramid_profiles(
            path, pitch=pitch, sections_per_pyramid=sections_per_pyramid
        )
        path_length = samples[-1]['arc_length']
        num_pyramids = path_length / pitch
        logger.info(
            "solid_circle_pyramid: %d sections, %.1f mm path, ~%.0f pyramids (pitch=%.1f mm)",
            len(samples), path_length, num_pyramids, pitch,
        )
        base_radius = config.tube_settings.outer_radius

        n_sections = len(samples)
        logger.debug(
            "build_tube_from_path (solid_circle_pyramid): building %d section faces, "
            "path_length=%.2f mm",
            n_sections,
            path_length,
        )

        faces = []
        for idx, sample in enumerate(samples):
            t = sample['t']
            bulge = _pyramid_ridge_height_at_t(t, path_length, ridge_width, ridge_spacing, ridge_depth)
            radius = base_radius + bulge
            face_i = create_solid_circle_face(
                outer_radius=radius,
                wall_thickness=face_kw.get('wall_thickness', 1.0),
                orient_to_path=None,
            )
            plane = Plane(origin=sample['point'], normal=sample['tangent'])
            face_i = face_i.moved(Location(plane))
            faces.append(face_i)
            step = max(1, n_sections // 10)
            if (
                n_sections <= 20
                or idx == 0
                or idx == n_sections - 1
                or (idx + 1) % step == 0
            ):
                logger.debug(
                    "build_tube_from_path (solid_circle_pyramid): face %d/%d",
                    idx + 1,
                    n_sections,
                )

        logger.debug(
            "build_tube_from_path (solid_circle_pyramid): calling sweep (%d faces)",
            len(faces),
        )
        return sweep(faces, path, aux=aux)

    if face_type == 'led_circle':
        logger.debug("build_tube_from_path (led_circle): calling sweep (single profile)")
        return sweep(create_led_circle_face(**face_kw), path, aux=aux)
    if face_type == 'solid_circle':
        logger.debug("build_tube_from_path (solid_circle): calling sweep (single profile)")
        return sweep(create_solid_circle_face(**face_kw), path, aux=aux)
    if face_type == 'square':
        logger.debug("build_tube_from_path (square): calling sweep (single profile)")
        return sweep(create_square_face(**face_kw), path, aux=aux)

    raise ValueError(f"Unknown face_type: {face_type!r}")


def maybe_export_named_parts(named_parts: Dict[str, object], config) -> None:
    """
    Optional per-part export helper used by assembly-producing knot scripts.

    Behavior is controlled by CLI flags parsed into config:
    - config.export_parts: comma-separated tokens (assembly,tube,clamp_a,clamp_b,clamp_halves,all)
    - config.export_parts_dir: directory to write files into
    """
    parts_spec = getattr(config, "export_parts", None)
    out_dir = getattr(config, "export_parts_dir", None)
    if not parts_spec or not out_dir:
        return

    tokens = {t.strip().lower() for t in str(parts_spec).split(",") if t.strip()}
    if "all" in tokens:
        tokens = {"assembly", "tube", "clamp_a", "clamp_b"}
    if "clamp_halves" in tokens:
        tokens.discard("clamp_halves")
        tokens |= {"clamp_a", "clamp_b"}

    ext = ".stl"
    if getattr(config.export, "filepath", None):
        ext = os.path.splitext(config.export.filepath)[1].lower() or ".stl"
    os.makedirs(out_dir, exist_ok=True)

    for key in sorted(tokens):
        obj = named_parts.get(key)
        if obj is None:
            continue
        out_path = os.path.join(out_dir, f"{(config.name or 'knot')}_{key}{ext}")
        if isinstance(obj, cq.Assembly):
            obj.export(
                out_path,
                exportType="STEP" if ext in [".step", ".stp"] else ("GLB" if ext == ".glb" else None),
                tolerance=config.export.tolerance,
                angularTolerance=config.export.angular_tolerance,
            )
        else:
            solid = obj.val() if hasattr(obj, "val") else obj
            cq.exporters.export(
                solid,
                out_path,
                tolerance=config.export.tolerance,
                angularTolerance=config.export.angular_tolerance,
                opt={"ascii": config.export.stl_ascii} if ext == ".stl" else None,
            )


def draw_part(path, config, aux=None, **face_kwargs):
    """
    Create and render a part by sweeping a face profile along a path.

    The face type is selected from config.tube_settings.face_type:
    - "led_circle" (default): LED circle cross-section with oval cavity
    - "solid_circle": Simple filled circle
    - "square": Simple filled square

    When --export is set, always sweeps and renders (and writes to cache unless --no-cache).
    Otherwise, uses cache when available (unless --no-cache); on cache hit skips the sweep.
    With --only-cache, only renders if a cached GLB exists; does not sweep on cache miss.
    When --preview is set, always builds (sweeps) to produce STL for the preview image.
    With max_print_bounds enabled, sweeps once per printable segment; otherwise one sweep.

    Args:
        path: CadQuery Wire or Edge representing the sweep path
        config: Config object with tube_settings, export, viewer_enabled, name, no_cache, only_cache
        aux: Optional auxiliary path for sweep orientation
        **face_kwargs: Additional keyword arguments to pass to the face creation function
                       (e.g., rotation_z). orient_to_path is set automatically.

    Returns:
        The swept solid/compound result, or None when rendering from cache or on only-cache miss.
    """
    cache_path = cache_path_for_part(config, path, aux=aux, face_kwargs=face_kwargs)
    preview_filepath = getattr(config, 'preview_filepath', None)
    face_kwargs_dict = face_kwargs or {}

    # --only-cache (and no preview): only render if cached GLB exists; do not sweep
    if getattr(config, 'only_cache', False) and not preview_filepath:
        if cache_path is None or not cache_path.exists():
            logger.info("Object not in cache (--only-cache); skipping sweep.")
            return None
        with open(cache_path, 'rb') as f:
            glb_bytes = f.read()
        print(f"Rendering from cache: {cache_path}")
        render_part(glb_bytes, config)
        return None

    # No export, no preview: use cached GLB if available to avoid sweep
    if (
        not config.export.filepath
        and not preview_filepath
        and cache_path is not None
        and cache_path.exists()
        and not getattr(config, 'no_cache', False)
    ):
        with open(cache_path, 'rb') as f:
            glb_bytes = f.read()
        print(f"Rendering from cache: {cache_path}")
        render_part(glb_bytes, config)
        return None

    # We need geometry once (export, preview, or cache miss).
    logger.debug("Sweeping and rendering.")
    if config.max_print_bounds.enabled:
        result = build_segmented_tube_assembly(
            path,
            config,
            build_tube_from_path,
            aux=aux,
            face_kwargs=face_kwargs_dict,
        )
    else:
        result = build_tube_from_path(path, config, aux=aux, face_kwargs=face_kwargs_dict)

    # Preview-only (no export): tessellate with fine tolerance for smooth tube, render image
    if preview_filepath and not config.export.filepath:
        solid = result.val() if hasattr(result, 'val') else result
        tol = config.preview_settings.mesh_tolerance
        ang_tol = config.preview_settings.mesh_angular_tolerance
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tf:
            tmp_stl = tf.name
        try:
            cq.exporters.export(
                solid,
                tmp_stl,
                tolerance=tol,
                angularTolerance=ang_tol,
                opt={"ascii": False},
            )
            render_stl_to_image(
                Path(tmp_stl),
                Path(preview_filepath),
                config.preview_settings,
            )
            logger.debug("Wrote preview image %s (mesh tolerance=%.2e)", preview_filepath, tol)
        finally:
            if os.path.exists(tmp_stl):
                try:
                    os.unlink(tmp_stl)
                except OSError:
                    pass
        # Optionally write GLB to cache for other uses (e.g. viewer)
        if cache_path is not None:
            cache_path_w = (
                Path(cache_path) if not isinstance(cache_path, Path) else cache_path
            )
            cache_path_w.parent.mkdir(parents=True, exist_ok=True)
            glb_data = _solid_to_glb_bytes(
                solid,
                config=config,
                stl_tolerance=config.preview_settings.mesh_tolerance,
                stl_angular_tolerance=config.preview_settings.mesh_angular_tolerance,
                stl_ascii=False,
            )
            with open(cache_path_w, "wb") as f:
                f.write(glb_data)
            logger.debug("Wrote cache %s", cache_path_w)
        return result

    # Export (with optional preview): render_part exports and optionally generates preview image
    if config.export.filepath:
        preview_stl_path = None
        if preview_filepath:
            if os.path.splitext(config.export.filepath)[1].lower() == '.stl':
                preview_stl_path = Path(config.export.filepath)
            else:
                preview_stl_path = preview_stl_path_for_part(
                    config, path, aux=aux, face_kwargs=face_kwargs_dict
                )
        render_part(
            result,
            config,
            cache_path=cache_path,
            preview_stl_path=preview_stl_path,
            preview_image_path=preview_filepath,
        )
        return result

    # No export: show and optionally write GLB to cache
    render_part(result, config, cache_path=cache_path)
    return result
