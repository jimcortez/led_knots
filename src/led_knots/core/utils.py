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
from cadquery.func import sweep
from .cache_utils import cache_key_for_part, cache_path_for_part
from .led_circle import create_led_circle_face

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
            - server: Boolean flag (not used for CadQuery, but kept for compatibility)
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
        help='Start the yacv server for web viewing'
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
    args = parser.parse_args()
    
    # Configure logging if verbose flag is set
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    
    return args


# ============================================================================
# PYKNOT SCALING UTILITIES
# ============================================================================

def scale_pyknot_points(points: np.ndarray, width: float, height: float, length: float) -> np.ndarray:
    """
    Scale pyknot points to fit within a bounding box while preserving aspect ratio.
    
    Calculates the bounding box of the input points and scales them uniformly
    to fit within the specified width, height, and length constraints.
    
    Args:
        points: numpy array of shape (n, 3) containing (x, y, z) coordinates
        width: Target width for the x dimension (mm)
        height: Target height for the y dimension (mm)
        length: Target length for the z dimension (mm)
        
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
    
    # Calculate scale factors to fit within width (x), height (y), and length (z)
    scale_x = width / span_x if span_x > 0 else 1.0
    scale_y = height / span_y if span_y > 0 else 1.0
    scale_z = length / span_z if span_z > 0 else 1.0
    
    # Use the minimum scale factor to preserve aspect ratio and ensure it fits
    scale_factor = min(scale_x, scale_y, scale_z)
    
    # Scale the points
    return points * scale_factor


# ============================================================================
# DISPLAY AND EXPORT UTILITIES
# ============================================================================

def render_part(
    part: Union[cq.Workplane, cq.Solid, cq.Compound, bytes],
    config,
    cache_path: Optional[Union[str, Path]] = None,
    path=None,
    aux=None,
    face_kwargs: Optional[dict] = None,
):
    """
    Render the part based on configuration.

    Args:
        part: The Workplane, Solid, Compound, or GLB bytes (from cache) to render.
        config: Config object with export, server, name, no_cache, etc.
        cache_path: Optional path to write GLB bytes after building (when part is solid
                    and not config.no_cache). Ignored when part is bytes.
        path: Optional sweep path; when provided and cache_path is not, cache path is
              derived from config and path/aux/face_kwargs (only used when part is solid).
        aux: Optional auxiliary path for sweep orientation (used to derive cache path).
        face_kwargs: Optional dict passed to cache key (e.g. rotation_z) when deriving cache path.
    """
    name = config.name or "Knot"
    is_glb_bytes = isinstance(part, bytes)
    # Derive cache path when rendering a solid and path is provided
    if not is_glb_bytes and cache_path is None and path is not None:
        cache_path = cache_path_for_part(
            config, path, aux=aux, face_kwargs=face_kwargs or {}
        )
    # Set environment variable before importing yacv_server if we only want export
    if config.export.filepath and not config.server:
        os.environ['YACV_DISABLE_SERVER'] = '1'

    # Import yacv_server (server will auto-start unless disabled)
    from yacv_server import yacv, show

    if is_glb_bytes:
        glb_bytes = part
        # Pre-built GLB from cache: show and/or write to export path
        if config.export.filepath:
            file_ext = os.path.splitext(config.export.filepath)[1].lower()
            if file_ext in ['.glb', '.gltf']:
                export_dir = os.path.dirname(config.export.filepath)
                if export_dir and not os.path.exists(export_dir):
                    os.makedirs(export_dir, exist_ok=True)
                with open(config.export.filepath, 'wb') as f:
                    f.write(glb_bytes)
                logger.info("Exported %s to %s (GLB format)", name, config.export.filepath)
                return
            # Other formats not supported when part is from cache
            logger.error("Export format %s not supported when using cached GLB", file_ext)
            sys.exit(2)
        show(glb_bytes, names=name)
        if config.server:
            if yacv.server_thread is None:
                yacv.start()
            logger.info("Server started. View %s in the web interface.", name)
            if yacv.server is not None:
                logger.info("Server URL: http://%s:%s", yacv.server.server_name, yacv.server.server_port)
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                logger.info("Shutting down server...")
                yacv.stop()
        return

    # Part is a solid/workplane
    if isinstance(part, (cq.Solid, cq.Compound)):
        solid = part
    elif hasattr(part, 'val'):
        solid = part.val()
    else:
        solid = part

    # If export is specified, export to the filepath
    if config.export.filepath:
        export_dir = os.path.dirname(config.export.filepath)
        if export_dir and not os.path.exists(export_dir):
            os.makedirs(export_dir, exist_ok=True)
        file_ext = os.path.splitext(config.export.filepath)[1].lower()

        if file_ext == '.stl':
            cq.exporters.export(
                solid,
                config.export.filepath,
                tolerance=config.export.tolerance,
                angularTolerance=config.export.angular_tolerance
            )
            logger.info("Exported %s to %s (STL format)", name, config.export.filepath)
            return
        if file_ext in ['.step', '.stp']:
            cq.exporters.export(
                solid,
                config.export.filepath,
                tolerance=config.export.tolerance,
                angularTolerance=config.export.angular_tolerance
            )
            logger.info("Exported %s to %s (STEP format)", name, config.export.filepath)
            return
        if file_ext == '.3mf':
            cq.exporters.export(
                solid,
                config.export.filepath,
                tolerance=config.export.tolerance,
                angularTolerance=config.export.angular_tolerance
            )
            logger.info("Exported %s to %s (3MF format)", name, config.export.filepath)
            return
        if file_ext in ['.glb', '.gltf']:
            show(solid, names=name)
            export_data = yacv.export(name)
            if export_data is None:
                logger.error("Could not export %s", name)
                sys.exit(1)
            glb_data, _ = export_data
            with open(config.export.filepath, 'wb') as f:
                f.write(glb_data)
            logger.info("Exported %s to %s (GLB format)", name, config.export.filepath)
            if cache_path is not None and not getattr(config, 'no_cache', False):
                cache_path = Path(cache_path) if not isinstance(cache_path, Path) else cache_path
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                with open(cache_path, 'wb') as f:
                    f.write(glb_data)
                logger.debug("Wrote cache %s", cache_path)
            return

        logger.error(
            "Unknown export file extension '%s'. Supported: .stl, .step, .stp, .3mf, .glb, .gltf.",
            file_ext
        )
        sys.exit(2)

    # Display path (no export): show solid, optionally write GLB to cache
    show(solid, names=name)
    if cache_path is not None and not getattr(config, 'no_cache', False):
        export_data = yacv.export(name)
        if export_data is not None:
            glb_data, _ = export_data
            cache_path = Path(cache_path) if not isinstance(cache_path, Path) else cache_path
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, 'wb') as f:
                f.write(glb_data)
            logger.debug("Wrote cache %s", cache_path)

    if config.server:
        if yacv.server_thread is None:
            yacv.start()
        logger.info("Server started. View %s in the web interface.", name)
        if yacv.server is not None:
            logger.info("Server URL: http://%s:%s", yacv.server.server_name, yacv.server.server_port)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down server...")
            yacv.stop()


def draw_part(path, config, aux=None, **face_kwargs):
    """
    Create and render a part by sweeping an LED circle face along a path.

    When --export is set, always sweeps and renders (and writes to cache unless --no-cache).
    Otherwise, uses cache when available (unless --no-cache); on cache hit skips the sweep.
    With --only-cache, only renders if a cached GLB exists; does not sweep on cache miss.

    Args:
        path: CadQuery Wire or Edge representing the sweep path
        config: Config object with tube_settings, export, server, name, no_cache, only_cache
        aux: Optional auxiliary path for sweep orientation
        **face_kwargs: Additional keyword arguments to pass to create_led_circle_face
                       (e.g., rotation_z). orient_to_path is set automatically.

    Returns:
        The swept solid/compound result, or None when rendering from cache or on only-cache miss.
    """
    cache_path = cache_path_for_part(config, path, aux=aux, face_kwargs=face_kwargs)

    # When --export is set: always sweep, render, and (unless --no-cache) write to cache
    if config.export.filepath:
        logger.debug("Export requested; sweeping and rendering (cache write if not --no-cache)")
        face_shape = create_led_circle_face(
            **config.tube_settings.to_led_circle_face_kwargs(
                orient_to_path=path,
                **face_kwargs
            )
        )
        result = sweep(face_shape, path, aux=aux)
        render_part(result, config, cache_path=cache_path)
        return result

    # --only-cache: only render if cached GLB exists
    if getattr(config, 'only_cache', False):
        if cache_path is None or not cache_path.exists():
            logger.info("Object not in cache (--only-cache); skipping sweep.")
            return None
        with open(cache_path, 'rb') as f:
            glb_bytes = f.read()
        logger.info("Rendering from cache: %s", cache_path)
        render_part(glb_bytes, config)
        return None

    # Cache hit: use cached GLB instead of sweeping
    if cache_path is not None and cache_path.exists() and not getattr(config, 'no_cache', False):
        with open(cache_path, 'rb') as f:
            glb_bytes = f.read()
        logger.info("Cache hit; rendering from cache: %s", cache_path)
        render_part(glb_bytes, config)
        return None

    # Cache miss: sweep and render, then write to cache if not --no-cache
    logger.debug("Cache miss; sweeping and rendering.")
    face_shape = create_led_circle_face(
        **config.tube_settings.to_led_circle_face_kwargs(
            orient_to_path=path,
            **face_kwargs
        )
    )
    result = sweep(face_shape, path, aux=aux)
    render_part(result, config, cache_path=cache_path)
    return result
