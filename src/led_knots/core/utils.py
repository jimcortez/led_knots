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
        '--config',
        type=str,
        metavar='FILE',
        default=None,
        help=(
            'YAML config overlay merged on top of config.yaml and config.local.yaml. '
            'Only specify keys you want to override.'
        ),
    )
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
    Build the 3D tube geometry for `path` using the configured tube model.

    Resolves `config.tube_settings.face_type` against the tube-model registry
    (see `core/tube_models/__init__.py`) and delegates the build. Used by
    `draw_part` and by callers that want to post-process the geometry into an
    assembly.
    """
    from .tube_models import get_tube_model

    model = get_tube_model(config.tube_settings.face_type)
    return model.build(
        path=path,
        aux=aux,
        config=config,
        face_kwargs=face_kwargs or {},
    )


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
            # Bed-fit reference: prefer max_print_bounds (the user's
            # explicit printer dimensions) over output_bounds (which is
            # the path-scaling target and may exclude tube wall thickness).
            mp = config.max_print_bounds
            if mp.width > 0 and mp.length > 0 and mp.height > 0:
                bed_bounds = mp
                bed_clearance = float(getattr(mp, "clearance_mm", 2.0))
            else:
                bed_bounds = config.output_bounds
                bed_clearance = 2.0
            result, report = optimize_part(
                result,
                config.print_optimization,
                name=config.name or "part",
                path=path,
                tube_settings=config.tube_settings,
                output_bounds=bed_bounds,
                bed_clearance_mm=bed_clearance,
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
