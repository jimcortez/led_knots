"""Discover part modules by filename and dispatch to their build() entry point."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Callable

from led_knots.core.config import Config

_PARTS_DIR = Path(__file__).parent
_PACKAGE = "led_knots.parts"


def list_part_types() -> list[str]:
    """Return sorted part type names matching *.py stems in this package (excluding __init__)."""
    return sorted(
        path.stem
        for path in _PARTS_DIR.glob("*.py")
        if path.stem != "__init__" and path.stem != "registry"
    )


def _format_available_types() -> str:
    return ", ".join(list_part_types())


def load_builder(part_type: str) -> Callable[[Config], None]:
    """Import the part module for ``part_type`` and return its ``build`` function."""
    name = str(part_type).strip()
    available = list_part_types()
    if name not in available:
        raise ValueError(
            f"part_type {name!r} not found.\n"
            f"Available part types (from {_PARTS_DIR}):\n"
            f"  {_format_available_types()}"
        )
    module = importlib.import_module(f"{_PACKAGE}.{name}")
    build = getattr(module, "build", None)
    if build is None:
        raise AttributeError(
            f"Module {_PACKAGE}.{name} has no build(config) function."
        )
    return build
