"""Tests for render bundle naming, exports merge, and planner."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import led_knots.core.config as config_module
from led_knots.core.cache_utils import render_bundle_stem
from led_knots.core.config import (
    Config,
    RenderingSettings,
    _merge_exports_by_filename,
    resolve_filename_template,
)
from led_knots.core.render_planner import DuplicateExportFilenameError, RenderPlanner
from led_knots.core.utils import parse_render_args

from tests.conftest import load_test_config


def test_render_bundle_stem():
    stem = render_bundle_stem("Trefoil Knot", now=__import__("datetime").datetime(2025, 6, 7, 14, 30, 22))
    assert stem == "trefoil-knot_20250607-143022"


def test_run_name_from_knot_when_yaml_null(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = load_test_config(tmp_path, "knot_type: k11a6\n")
    assert cfg.run_name == "k11a6"


def test_rendering_exports_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = load_test_config(tmp_path, "knot_type: rod\n")
    formats = {j.format: j.enabled for j in cfg.rendering.exports}
    assert formats["stl"] is True
    assert formats["stats"] is True
    assert formats["obj"] is False
    assert formats["step"] is False


def test_exports_merge_by_filename():
    base = [
        {"format": "preview", "filename": "{name}.png", "azimuth": 45},
        {"format": "stl", "filename": "{name}.stl", "enabled": True},
    ]
    override = [
        {"format": "preview", "filename": "{name}.png", "azimuth": 90},
        {"format": "preview", "filename": "{name}-iso.png", "azimuth": 135},
    ]
    merged = _merge_exports_by_filename(base, override)
    by_key = {e["filename"]: e for e in merged}
    assert by_key["{name}.png"]["azimuth"] == 90
    assert "{name}-iso.png" in by_key
    assert "{name}.stl" in by_key


def test_duplicate_filename_raises():
    config = SimpleNamespace(
        rendering=RenderingSettings(
            {
                "exports": [
                    {"format": "stl", "filename": "{name}.stl", "enabled": True},
                    {"format": "3mf", "filename": "{name}.stl", "enabled": True},
                ]
            },
            Path("/tmp"),
            model_name="K",
            cli_name=None,
        ),
        render_bundle_stem="k_20250101-120000",
        render_bundle_dir=Path("/tmp/renders/k_20250101-120000"),
        run_name="K",
        viewer_enabled=False,
    )
    with pytest.raises(DuplicateExportFilenameError):
        RenderPlanner.from_config(config)


def test_disable_export_cli(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text("knot_type: rod\n")
    sys.argv = ["test", str(cfg_path), "--disable-export", "glb,stats"]
    cfg = Config(args=parse_render_args())
    enabled = {j.format for j in cfg.rendering.enabled_jobs()}
    assert "glb" not in enabled
    assert "stats" not in enabled
    assert "stl" in enabled


def test_resolve_filename_template():
    name = resolve_filename_template(
        "{run_name}-{name}.png",
        bundle_stem="rod_20250101-120000",
        run_name="Rod",
    )
    assert name == "Rod-rod_20250101-120000.png"


@pytest.fixture
def reset_config_singleton():
    config_module._config_instance = None
    yield
    config_module._config_instance = None


def test_deliver_part_writes_before_viewer(tmp_path, reset_config_singleton, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text("knot_type: rod\nrendering:\n  name: Test\n")
    sys.argv = ["test", str(cfg_path)]
    config = Config(args=parse_render_args())
    config.render_stats = __import__(
        "led_knots.core.render_stats", fromlist=["RenderStats"]
    ).RenderStats()
    order = []

    class FakeCtx:
        def _normalize(self):
            pass

        def execute_job(self, job):
            order.append(("file", job.format))

        def emit_viewer(self, name):
            order.append(("viewer", name))

    with patch("led_knots.core.render_pipeline.RenderPlanner.from_config") as plan_fn:
        plan_fn.return_value = SimpleNamespace(
            has_side_effects=True,
            want_viewer=True,
            bundle_dir=tmp_path / "renders" / "x",
            execution_order=[SimpleNamespace(format="stl")],
            jobs=[],
        )
        with patch("led_knots.core.render_pipeline.PartArtifacts", return_value=FakeCtx()):
            with patch("led_knots.core.render_pipeline._ensure_remote_viewer_reachable"):
                from led_knots.core.render_pipeline import deliver_part

                deliver_part(MagicMock(), config)

    assert order[0][0] == "file"
    assert order[-1] == ("viewer", config.name)
