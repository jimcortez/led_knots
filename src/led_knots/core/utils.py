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
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Union

import cadquery as cq
from cadquery.func import Plane, Location, sweep
from .led_circle import (
    _pyramid_ridge_height_at_t,
    create_led_circle_face,
    create_led_circle_tube_face,
    create_solid_circle_face,
    create_square_face,
)
from .path_utils import sample_path_for_profiles, sample_path_for_pyramid_profiles
from .print_segmentation import build_segmented_tube_assembly

logger = logging.getLogger(__name__)


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
    # Print optimization (SLA / resin). See config.yaml print_optimization block.
    opt_group = parser.add_mutually_exclusive_group()
    opt_group.add_argument(
        '--optimize',
        dest='optimize',
        action='store_true',
        default=None,
        help='Enable the SLA print-optimization stage (overrides config).',
    )
    opt_group.add_argument(
        '--no-optimize',
        dest='optimize',
        action='store_false',
        default=None,
        help='Disable the SLA print-optimization stage (overrides config).',
    )
    parser.add_argument(
        '--auto-orient',
        action='store_true',
        default=False,
        help=(
            'Apply the top-ranked SLA build orientation to the exported geometry. '
            'Implies --optimize. Without this flag the optimizer reports findings only.'
        ),
    )
    parser.add_argument(
        '--optimize-report-dir',
        type=str,
        metavar='DIR',
        default=None,
        help=(
            'Write annotated PNG diagnostics (overhangs in red, etc.) for the '
            'optimizer run to DIR. Implies --optimize.'
        ),
    )
    args = parser.parse_args()
    
    # Configure logging if verbose flag is set
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    
    return args


def render_part(
    part: Union[cq.Workplane, cq.Solid, cq.Compound, cq.Assembly],
    config,
    preview_stl_path: Optional[Path] = None,
    preview_image_path: Optional[Union[str, Path]] = None,
    *,
    path=None,
    aux=None,
    face_kwargs: Optional[dict] = None,
):
    """
    Render the part based on configuration.

    Delegates to ``deliver_part`` (dependency-resolved pipeline). Optional
    ``path`` / ``aux`` / ``face_kwargs`` enable preview STL cache keys for swept parts.
    ``preview_stl_path`` and ``preview_image_path`` are ignored (use ``config`` flags).
    """
    del preview_stl_path, preview_image_path
    from .render_pipeline import deliver_part

    deliver_part(
        part,
        config,
        path=path,
        aux=aux,
        face_kwargs=face_kwargs,
    )


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

    if face_type == 'led_circle_tube':
        tube_kw = config.tube_settings.to_led_circle_tube_face_kwargs(
            orient_to_path=path,
            **face_kwargs_dict,
        )
        logger.debug("build_tube_from_path (led_circle_tube): calling sweep (single profile)")
        return sweep(create_led_circle_tube_face(**tube_kw), path, aux=aux)
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
    parts_spec = config.export_parts
    out_dir = config.export_parts_dir
    if not parts_spec or not out_dir:
        return

    tokens = {t.strip().lower() for t in str(parts_spec).split(",") if t.strip()}
    if "all" in tokens:
        tokens = {"assembly", "tube", "clamp_a", "clamp_b"}
    if "clamp_halves" in tokens:
        tokens.discard("clamp_halves")
        tokens |= {"clamp_a", "clamp_b"}

    ext = ".stl"
    if config.export.filepath:
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

    When --export or --preview is set, sweeps and renders. With max_print_bounds enabled,
    sweeps once per printable segment; otherwise one sweep.

    Args:
        path: CadQuery Wire or Edge representing the sweep path
        config: Config object with tube_settings, export, viewer_enabled, name
        aux: Optional auxiliary path for sweep orientation
        **face_kwargs: Additional keyword arguments to pass to the face creation function
                       (e.g., rotation_z). orient_to_path is set automatically.

    Returns:
        The swept solid/compound/assembly result.
    """
    face_kwargs_dict = face_kwargs or {}

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

    if config.print_optimization.enabled:
        # Segmented assemblies are SLA-rescored inside
        # build_segmented_tube_assembly itself (per-segment), so here we
        # only run the whole-part optimizer for single-piece outputs.
        if isinstance(result, cq.Assembly):
            logger.debug(
                "[optimize] %s: segmented assembly — per-segment rescoring "
                "already applied inside build_segmented_tube_assembly",
                config.name or "part",
            )
        else:
            from led_knots.optimize import optimize_part, format_console
            result, report = optimize_part(
                result, config.print_optimization, name=config.name or "part"
            )
            print(format_console(report, part_name=config.name or "part"))
            report_dir = getattr(config, "optimize_report_dir", None)
            if report_dir and report.mesh is not None:
                from led_knots.optimize.report import write_annotated_pngs
                from led_knots.core.cache_utils import slugify
                written = write_annotated_pngs(
                    report,
                    report.mesh,
                    Path(report_dir),
                    part_name=slugify(config.name or "knot"),
                    preview_settings=config.preview_settings,
                )
                for p in written:
                    logger.info("[optimize] annotated PNG: %s", p)

    render_part(
        result,
        config,
        path=path,
        aux=aux,
        face_kwargs=face_kwargs_dict,
    )
    return result
