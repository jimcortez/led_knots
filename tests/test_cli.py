"""Tests for render-knot and render-part CLI entry points."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from led_knots.cli import main_knot, main_part
from tests.conftest import load_test_config, short_rod_config_path


def test_main_knot_missing_knot_type_exits(tmp_path, argv_guard):
    cfg = tmp_path / "no_type.yaml"
    cfg.write_text("face_type: led_circle\n")
    sys.argv = ["render-knot", str(cfg)]
    with pytest.raises(SystemExit, match="knot_type is required"):
        main_knot()


def test_main_part_missing_part_type_exits(tmp_path, argv_guard):
    cfg = tmp_path / "no_type.yaml"
    cfg.write_text("face_type: led_circle\n")
    sys.argv = ["render-part", str(cfg)]
    with pytest.raises(SystemExit, match="part_type is required"):
        main_part()


def test_main_knot_unknown_type_exits(tmp_path, argv_guard):
    cfg = tmp_path / "bad.yaml"
    cfg.write_text("knot_type: not_a_real_knot\n")
    sys.argv = ["render-knot", str(cfg)]
    with pytest.raises(SystemExit, match="not_a_real_knot"):
        main_knot()


def test_short_rod_config_has_knot_type():
    assert short_rod_config_path().exists()
    cfg = load_test_config(short_rod_config_path().parent, short_rod_config_path().read_text())
    assert cfg.knot_type == "rod"
