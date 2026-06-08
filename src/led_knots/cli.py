"""CLI entry points for config-driven knot and part rendering."""

from __future__ import annotations

import sys

from led_knots.core.config import load_config
from led_knots.core.utils import parse_render_args
from led_knots.knots.registry import list_knot_types, load_builder as load_knot_builder
from led_knots.parts.registry import list_part_types, load_builder as load_part_builder


def main_knot() -> None:
    args = parse_render_args(description="Render a knot from a config file")
    config = load_config(args=args)
    if not config.knot_type:
        available = ", ".join(list_knot_types())
        raise SystemExit(
            f"Error: knot_type is required in the config file.\n"
            f"Available knot types (from src/led_knots/knots/):\n"
            f"  {available}"
        )
    try:
        load_knot_builder(config.knot_type)(config)
    except ValueError as exc:
        raise SystemExit(f"Error: {exc}") from exc


def main_part() -> None:
    args = parse_render_args(description="Render a part from a config file")
    config = load_config(args=args)
    if not config.part_type:
        available = ", ".join(list_part_types())
        raise SystemExit(
            f"Error: part_type is required in the config file.\n"
            f"Available part types (from src/led_knots/parts/):\n"
            f"  {available}"
        )
    try:
        load_part_builder(config.part_type)(config)
    except ValueError as exc:
        raise SystemExit(f"Error: {exc}") from exc


if __name__ == "__main__":
    main_knot()
