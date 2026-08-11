"""Discover knot modules by filename and dispatch to their build() entry point."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Callable

from led_knots.core.config import Config

_KNOTS_DIR = Path(__file__).parent
_PACKAGE = "led_knots.knots"


def list_knot_types() -> list[str]:
    """Return sorted knot type names matching *.py stems in this package.

    Stems starting with an underscore are treated as private helpers, not knot
    types, so a shared module can live in this package without becoming a
    selectable ``knot_type``.
    """
    return sorted(
        path.stem
        for path in _KNOTS_DIR.glob("*.py")
        if not path.stem.startswith("_") and path.stem != "registry"
    )


def _format_available_types() -> str:
    return ", ".join(list_knot_types())


def load_builder(knot_type: str) -> Callable[[Config], None]:
    """Import the knot module for ``knot_type`` and return its ``build`` function."""
    name = str(knot_type).strip()
    available = list_knot_types()
    if name not in available:
        raise ValueError(
            f"knot_type {name!r} not found.\n"
            f"Available knot types (from {_KNOTS_DIR}):\n"
            f"  {_format_available_types()}"
        )
    module = importlib.import_module(f"{_PACKAGE}.{name}")
    build = getattr(module, "build", None)
    if build is None:
        raise AttributeError(
            f"Module {_PACKAGE}.{name} has no build(config) function."
        )
    return build
