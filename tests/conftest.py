"""Shared test helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from led_knots.core.config import Config
from led_knots.core.utils import parse_render_args


def write_test_config(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def argv_guard():
    old_argv = sys.argv
    yield
    sys.argv = old_argv


def load_test_config(tmp_path: Path, yaml_body: str) -> Config:
    cfg_path = write_test_config(tmp_path / "test_config.yaml", yaml_body)
    sys.argv = ["test", str(cfg_path)]
    return Config(args=parse_render_args())


def short_rod_config_path() -> Path:
    """Path to the shared short-rod led_circle_tube knot config."""
    return Path(__file__).resolve().parent.parent / "knot_configs" / "test_short_rod_led_tube.yaml"
