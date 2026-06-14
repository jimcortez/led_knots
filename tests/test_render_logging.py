"""Tests for per-render log buffering and bundle log files."""

from __future__ import annotations

import io
import logging
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import led_knots.core.render_logging as render_logging_module
from led_knots.core.config import Config
from led_knots.core.render_logging import (
    attach_render_log_buffer,
    discard_render_log_buffer,
    finalize_render_log,
)
from led_knots.core.utils import parse_render_args

TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} ")


@pytest.fixture
def clean_render_logging():
    old_handlers = logging.root.handlers[:]
    old_level = logging.root.level
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
        handler.close()
    render_logging_module._memory_handler = None
    render_logging_module._saved_root_level = None
    yield
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
        handler.close()
    for handler in old_handlers:
        logging.root.addHandler(handler)
    logging.root.setLevel(old_level)
    render_logging_module._memory_handler = None
    render_logging_module._saved_root_level = None


def test_finalize_writes_timestamped_debug_and_info(tmp_path, clean_render_logging):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    attach_render_log_buffer()
    log = logging.getLogger("test.module")
    log.debug("debug line")
    log.info("info line")

    log_path = tmp_path / "run.log"
    finalize_render_log(log_path)

    text = log_path.read_text(encoding="utf-8")
    assert "debug line" in text
    assert "info line" in text
    for line in text.strip().splitlines():
        assert TIMESTAMP_RE.match(line), line


def test_discard_does_not_write_log(tmp_path, clean_render_logging):
    logging.basicConfig(level=logging.INFO)
    attach_render_log_buffer()
    logging.getLogger("test").info("msg")

    log_path = tmp_path / "run.log"
    discard_render_log_buffer()

    assert not log_path.exists()


def test_file_log_includes_debug_while_stderr_is_info(tmp_path, clean_render_logging):
    stream = io.StringIO()
    stream_handler = logging.StreamHandler(stream)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    logging.root.addHandler(stream_handler)
    logging.root.setLevel(logging.INFO)

    attach_render_log_buffer()
    log = logging.getLogger("test")
    log.debug("secret debug")
    log.info("visible info")

    finalize_render_log(tmp_path / "run.log")

    output = stream.getvalue()
    assert "secret debug" not in output
    assert "visible info" in output
    text = (tmp_path / "run.log").read_text(encoding="utf-8")
    assert "secret debug" in text
    assert "visible info" in text


def test_deliver_part_writes_log_file(tmp_path, clean_render_logging, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text("knot_type: rod\nrendering:\n  name: Test\n")
    sys.argv = ["test", str(cfg_path)]
    config = Config(args=parse_render_args())
    config.render_stats = __import__(
        "led_knots.core.render_stats", fromlist=["RenderStats"]
    ).RenderStats()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    attach_render_log_buffer()
    logging.getLogger("test").debug("buffered debug")

    bundle_dir = tmp_path / "renders" / "test_20250101-120000"
    with patch("led_knots.core.render_pipeline.RenderPlanner.from_config") as plan_fn:
        plan_fn.return_value = SimpleNamespace(
            has_side_effects=True,
            want_viewer=False,
            bundle_dir=bundle_dir,
            execution_order=[],
            jobs=[],
        )
        with patch("led_knots.core.render_pipeline.PartArtifacts") as artifacts_cls:
            artifacts_cls.return_value = SimpleNamespace(
                _normalize=lambda: None,
                execute_job=lambda job: None,
                emit_viewer=lambda name: None,
            )
            from led_knots.core.render_pipeline import deliver_part

            deliver_part(MagicMock(), config)

    log_path = bundle_dir / f"{config.render_bundle_stem}.log"
    assert log_path.exists()
    text = log_path.read_text(encoding="utf-8")
    assert "buffered debug" in text
    assert TIMESTAMP_RE.match(text.strip().splitlines()[0])


def test_deliver_part_without_side_effects_discards_log(tmp_path, clean_render_logging, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text("knot_type: rod\n")
    sys.argv = ["test", str(cfg_path)]
    config = Config(args=parse_render_args())
    config.render_stats = __import__(
        "led_knots.core.render_stats", fromlist=["RenderStats"]
    ).RenderStats()

    logging.basicConfig(level=logging.INFO)
    attach_render_log_buffer()
    logging.getLogger("test").info("should not persist")

    with patch("led_knots.core.render_pipeline.RenderPlanner.from_config") as plan_fn:
        plan_fn.return_value = SimpleNamespace(has_side_effects=False)
        from led_knots.core.render_pipeline import deliver_part

        deliver_part(MagicMock(), config)

    renders_dir = tmp_path / "renders"
    if renders_dir.exists():
        assert not list(renders_dir.glob("**/*.log"))
