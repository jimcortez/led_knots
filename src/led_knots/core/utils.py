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
from tqdm.auto import tqdm
from .print_segmentation import build_segmented_tube_assembly

logger = logging.getLogger(__name__)


# ============================================================================
# COMMAND LINE PARSING
# ============================================================================

def _add_render_optional_flags(parser: argparse.ArgumentParser) -> None:
    """Register shared optional flags for render-knot and render-part."""
    parser.add_argument(
        '--name',
        type=str,
        metavar='NAME',
        default=None,
        help='Run name for the render bundle folder and default filename templates',
    )
    parser.add_argument(
        '--renders-dir',
        type=str,
        metavar='DIR',
        default=None,
        help='Parent directory for render bundles (overrides rendering.output_dir)',
    )
    parser.add_argument(
        '--disable-export',
        type=str,
        metavar='FORMATS',
        default=None,
        help='Disable export jobs for comma-separated formats (e.g. glb,stats,obj)',
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


def parse_render_args(description: str = "Render a model from a config file"):
    """
    Parse command line arguments for render-knot and render-part.

    Args:
        description: Description for the argument parser

    Returns:
        argparse.Namespace with a required positional ``config`` path and shared optional flags.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "config",
        type=str,
        metavar="FILE",
        help=(
            "YAML config file merged on top of config.yaml and config.local.yaml. "
            "Must include knot_type (render-knot) or part_type (render-part)."
        ),
    )
    _add_render_optional_flags(parser)
    args = parser.parse_args()

    return args


# Backward-compatible alias for tests and library callers.
parse_args = parse_render_args


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


def draw_part(path, config, aux=None, **face_kwargs):
    """
    Create and render a part by sweeping a face profile along a path.

    The face type is selected from config.tube_settings.face_type:
    - "led_circle" (default): LED circle cross-section with oval cavity
    - "solid_circle": Simple filled circle
    - "square": Simple filled square

    When print optimization or segmentation is enabled, builds accordingly then
    writes a render bundle under rendering.output_dir (default renders/).

    Args:
        path: CadQuery Wire or Edge representing the sweep path
        config: Config object with tube_settings, rendering, viewer settings
        aux: Optional auxiliary path for sweep orientation
        **face_kwargs: Additional keyword arguments to pass to the face creation function
                       (e.g., rotation_z). orient_to_path is set automatically.

    Returns:
        The swept solid/compound/assembly result.
    """
    from .render_stats import RenderStats

    if config.render_stats is None:
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

    face_kwargs_dict = face_kwargs or {}

    with config.render_stats.record_stage("draw_part.sweep"):
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

    if not isinstance(result, cq.Assembly):
        from .fuse_utils import fuse_part_solids

        result = fuse_part_solids(result, name=config.name or "part")

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

            logger.info(
                "Running print optimization on %s...",
                config.name or "part",
            )
            mp = config.max_print_bounds
            if mp.width > 0 and mp.length > 0 and mp.height > 0:
                bed_bounds = mp
                bed_clearance = float(getattr(mp, "clearance_mm", 2.0))
            else:
                bed_bounds = config.output_bounds
                bed_clearance = 2.0
            with config.render_stats.record_stage("draw_part.optimize"):
                result, report = optimize_part(
                    result,
                    config.print_optimization,
                    name=config.name or "part",
                    path=path,
                    tube_settings=config.tube_settings,
                    output_bounds=bed_bounds,
                    bed_clearance_mm=bed_clearance,
                    render_stats=config.render_stats,
                )
            print(format_console(report, part_name=config.name or "part"))
            logger.info(
                "Print optimization finished (%s); exporting/rendering.",
                report.note or "ok",
            )
            report_dir = getattr(config, "optimize_report_dir", None)
            if report_dir and report.mesh is not None:
                from led_knots.optimize.report import write_annotated_pngs
                from led_knots.core.cache_utils import slugify
                written = write_annotated_pngs(
                    report,
                    report.mesh,
                    Path(report_dir),
                    part_name=slugify(config.name or "knot"),
                    preview_settings=config.rendering.first_preview_job(),
                )
                if written:
                    if sys.stderr.isatty():
                        for _ in tqdm(
                            written,
                            total=len(written),
                            desc="Writing annotated PNGs",
                            unit="png",
                        ):
                            pass
                    else:
                        for p in written:
                            logger.info("[optimize] annotated PNG: %s", p)
                    logger.info(
                        "[optimize] wrote %d annotated PNG(s) to %s",
                        len(written),
                        report_dir,
                    )

    render_part(
        result,
        config,
        path=path,
        aux=aux,
        face_kwargs=face_kwargs_dict,
    )
    return result
