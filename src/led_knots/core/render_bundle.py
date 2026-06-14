"""Resolve existing render bundle folders for re-upload to the web viewer."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RenderBundle:
    """Paths for a flat render bundle directory."""

    bundle_dir: Path
    stem: str
    glb_path: Path
    config_yaml: Path


def resolve_render_bundle(path: Path) -> RenderBundle:
    """
    Resolve a render bundle directory or its config YAML to bundle artifact paths.

    Args:
        path: Bundle directory or ``{stem}.yaml`` inside the bundle.

    Returns:
        RenderBundle with absolute paths.

    Raises:
        ValueError: If ``path`` is not a directory or YAML file.
        FileNotFoundError: If the bundle GLB is missing.
    """
    resolved = path.resolve()
    if resolved.is_file() and resolved.suffix in {".yaml", ".yml"}:
        bundle_dir = resolved.parent
        stem = bundle_dir.name
    elif resolved.is_dir():
        bundle_dir = resolved
        stem = resolved.name
    else:
        raise ValueError(
            f"Render bundle path must be a directory or YAML file, got: {path}"
        )

    glb_path = bundle_dir / f"{stem}.glb"
    config_yaml = bundle_dir / f"{stem}.yaml"

    if not glb_path.is_file():
        raise FileNotFoundError(f"Render bundle GLB not found: {glb_path}")

    if not config_yaml.is_file():
        logger.info(
            "Render bundle config YAML not found at %s; using repo config.yaml only",
            config_yaml,
        )

    return RenderBundle(
        bundle_dir=bundle_dir,
        stem=stem,
        glb_path=glb_path,
        config_yaml=config_yaml,
    )
