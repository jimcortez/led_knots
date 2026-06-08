"""Tests for config file merging via render CLI."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

import led_knots.core.config as config_module
from led_knots.core.config import Config, _resolve_config_path
from led_knots.core.utils import parse_render_args


def _project_root() -> Path:
    return Path(config_module.__file__).parent.parent.parent.parent


@pytest.fixture
def argv_guard():
    old_argv = sys.argv
    yield
    sys.argv = old_argv


def test_overlay_overrides_scalar(tmp_path, argv_guard):
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text("face_type: solid_circle\n")

    sys.argv = ["test", str(overlay)]
    cfg = Config(args=parse_render_args())

    assert cfg.tube_settings.face_type == "solid_circle"


def test_overlay_deep_merges_nested_dict(tmp_path, argv_guard):
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text(
        "print_optimization:\n"
        "  orientation:\n"
        "    connector_bonus_weight: 0.25\n"
    )

    sys.argv = ["test", str(overlay)]
    cfg = Config(args=parse_render_args())

    assert cfg.print_optimization.orientation.connector_bonus_weight == 0.25
    assert cfg.print_optimization.orientation.top_n_candidates == 5


def test_overlay_wins_over_local(tmp_path, argv_guard):
    project_root = _project_root()
    local_path = project_root / "config.local.yaml"
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text("face_type: solid_circle\n")

    had_local = local_path.exists()
    old_local = local_path.read_text() if had_local else None
    try:
        local_path.write_text("face_type: led_circle\n")
        sys.argv = ["test", str(overlay)]
        cfg = Config(args=parse_render_args())
        assert cfg.tube_settings.face_type == "solid_circle"
    finally:
        if had_local:
            local_path.write_text(old_local)
        elif local_path.exists():
            local_path.unlink()


def test_missing_overlay_raises(argv_guard):
    sys.argv = ["test", "configs/does-not-exist.yaml"]
    with pytest.raises(FileNotFoundError, match="Config file not found"):
        Config(args=parse_render_args())


def test_relative_path_resolved_from_project_root(argv_guard):
    project_root = _project_root()
    configs_dir = project_root / "configs"
    configs_dir.mkdir(exist_ok=True)
    overlay = configs_dir / "test_overlay.yaml"
    overlay.write_text("face_type: square\n")

    old_cwd = os.getcwd()
    try:
        os.chdir("/tmp")
        sys.argv = ["test", "configs/test_overlay.yaml"]
        cfg = Config(args=parse_render_args())
        assert cfg.tube_settings.face_type == "square"
        assert cfg.config_path == overlay.resolve()
    finally:
        os.chdir(old_cwd)
        overlay.unlink(missing_ok=True)
        if configs_dir.exists() and not any(configs_dir.iterdir()):
            configs_dir.rmdir()


def test_resolve_config_path_absolute():
    project_root = Path("/repo")
    assert _resolve_config_path(project_root, "/abs/overlay.yaml") == Path(
        "/abs/overlay.yaml"
    )


def test_resolve_config_path_relative():
    project_root = Path("/repo")
    assert _resolve_config_path(project_root, "configs/foo.yaml") == Path(
        "/repo/configs/foo.yaml"
    )


def test_overlay_exports_merge_by_filename(tmp_path, argv_guard):
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text(
        "rendering:\n"
        "  exports:\n"
        "    - format: preview\n"
        "      filename: '{name}.png'\n"
        "      azimuth: 90\n"
    )
    sys.argv = ["test", str(overlay)]
    cfg = Config(args=parse_render_args())
    preview = next(j for j in cfg.rendering.exports if j.filename_template == "{name}.png")
    assert preview.azimuth == 90


def test_knot_type_parsed_from_config(tmp_path, argv_guard):
    overlay = tmp_path / "knot.yaml"
    overlay.write_text("knot_type: trefoil\n")
    sys.argv = ["test", str(overlay)]
    cfg = Config(args=parse_render_args())
    assert cfg.knot_type == "trefoil"
    assert cfg.part_type is None


def test_part_type_parsed_from_config(tmp_path, argv_guard):
    overlay = tmp_path / "part.yaml"
    overlay.write_text("part_type: hang_clamp\n")
    sys.argv = ["test", str(overlay)]
    cfg = Config(args=parse_render_args())
    assert cfg.part_type == "hang_clamp"
    assert cfg.knot_type is None
