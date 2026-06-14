"""Tests for upload-knot CLI and render bundle resolution."""

from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from led_knots.cli import main_upload_knot
from led_knots.core.config import Config, load_config
from led_knots.core.render_bundle import resolve_render_bundle
from led_knots.core.utils import parse_render_args, parse_upload_args


def _write_bundle(
    tmp_path: Path,
    stem: str = "rod_20260612-152817",
    *,
    with_yaml: bool = True,
    with_glb: bool = True,
    yaml_body: str | None = None,
) -> Path:
    bundle_dir = tmp_path / stem
    bundle_dir.mkdir(parents=True)
    if with_glb:
        (bundle_dir / f"{stem}.glb").write_bytes(b"glb-bytes")
    if with_yaml:
        body = yaml_body or (
            "knot_type: rod\n"
            "rendering:\n  name: rod\n"
            "server:\n  viewer:\n    host: testhost\n    port: 42424\n"
        )
        (bundle_dir / f"{stem}.yaml").write_text(body, encoding="utf-8")
    return bundle_dir


def test_resolve_render_bundle_from_directory(tmp_path):
    bundle_dir = _write_bundle(tmp_path)
    bundle = resolve_render_bundle(bundle_dir)
    assert bundle.stem == bundle_dir.name
    assert bundle.glb_path == bundle_dir / f"{bundle_dir.name}.glb"
    assert bundle.config_yaml == bundle_dir / f"{bundle_dir.name}.yaml"


def test_resolve_render_bundle_from_yaml_path(tmp_path):
    bundle_dir = _write_bundle(tmp_path)
    yaml_path = bundle_dir / f"{bundle_dir.name}.yaml"
    bundle = resolve_render_bundle(yaml_path)
    assert bundle.bundle_dir == bundle_dir.resolve()
    assert bundle.glb_path.name == f"{bundle_dir.name}.glb"


def test_resolve_render_bundle_missing_glb_raises(tmp_path):
    bundle_dir = _write_bundle(tmp_path, with_glb=False)
    with pytest.raises(FileNotFoundError, match="GLB not found"):
        resolve_render_bundle(bundle_dir)


def test_resolve_render_bundle_invalid_path_raises(tmp_path):
    with pytest.raises(ValueError, match="directory or YAML"):
        resolve_render_bundle(tmp_path / "missing.txt")


def test_apply_viewer_from_yaml_remote(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(
        "knot_type: rod\n"
        "server:\n  viewer:\n    host: testhost\n    port: 42424\n",
        encoding="utf-8",
    )
    sys.argv = ["test", str(cfg_path)]
    config = Config(args=parse_render_args())
    config.apply_viewer_from_yaml()
    assert config.viewer_enabled is True
    assert config.viewer_remote_options is not None
    assert config.viewer_remote_options["host"] == "testhost"
    assert config.viewer_remote_options["port"] == 42424


def test_init_viewer_from_args_server_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(
        "knot_type: rod\n"
        "server:\n  viewer:\n    host: localhost\n    port: 32323\n",
        encoding="utf-8",
    )
    sys.argv = ["test", str(cfg_path), "--server"]
    config = Config(args=parse_render_args())
    assert config.viewer_enabled is True
    assert config.viewer_remote_options["host"] == "localhost"
    assert config.viewer_remote_options["port"] == 32323


def test_main_upload_knot_posts_glb(tmp_path, argv_guard, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bundle_dir = _write_bundle(tmp_path)
    sys.argv = ["upload-knot", str(bundle_dir)]
    with patch("led_knots.core.render_pipeline._cadquery_web_viewer_show") as show_mock:
        with patch("led_knots.core.render_pipeline._ensure_remote_viewer_reachable"):
            main_upload_knot()
    show_mock.assert_called_once()
    config, name, glb_bytes = show_mock.call_args[0]
    assert name == "rod"
    assert glb_bytes == b"glb-bytes"
    assert config.viewer_remote_options["host"] == "testhost"
    assert config.viewer_remote_options["port"] == 42424


def test_parse_upload_args_bundle_and_verbose():
    sys.argv = ["upload-knot", "renders/foo", "-v"]
    args = parse_upload_args()
    assert args.bundle == "renders/foo"
    assert args.verbose is True
