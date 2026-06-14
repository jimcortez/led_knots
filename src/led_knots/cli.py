"""CLI entry points for config-driven knot and part rendering."""

from __future__ import annotations

import logging
import sys
from argparse import Namespace
from pathlib import Path

from led_knots.core.config import Config, load_config
from led_knots.core.render_bundle import resolve_render_bundle
from led_knots.core.render_logging import attach_render_log_buffer
from led_knots.core.render_pipeline import upload_render_bundle
from led_knots.core.utils import parse_render_args, parse_upload_args
from led_knots.knots.registry import list_knot_types, load_builder as load_knot_builder
from led_knots.parts.registry import list_part_types, load_builder as load_part_builder

logger = logging.getLogger(__name__)


def _init_logging(verbose: bool) -> None:
    if logging.root.handlers:
        return
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
    )


def _log_render_destination(config: Config) -> None:
    logger.info("Render bundle destination: %s", config.render_bundle_dir)


def main_knot() -> None:
    args = parse_render_args(description="Render a knot from a config file")
    _init_logging(args.verbose)
    config = load_config(args=args)
    attach_render_log_buffer()
    _log_render_destination(config)
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
    _init_logging(args.verbose)
    config = load_config(args=args)
    attach_render_log_buffer()
    _log_render_destination(config)
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


def main_upload_knot() -> None:
    args = parse_upload_args()
    _init_logging(args.verbose)
    bundle = resolve_render_bundle(Path(args.bundle))
    config_args = Namespace(
        config=str(bundle.config_yaml) if bundle.config_yaml.is_file() else None,
        name=None,
        renders_dir=None,
        disable_export=None,
        server=False,
        verbose=args.verbose,
        optimize=None,
        auto_orient=False,
        optimize_report_dir=None,
    )
    config = load_config(args=config_args)
    config.apply_viewer_from_yaml()
    upload_render_bundle(bundle, config)


if __name__ == "__main__":
    main_knot()
