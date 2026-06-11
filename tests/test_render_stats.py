"""Tests for render stats collection and CSV output."""

from __future__ import annotations

import logging
from pathlib import Path

from led_knots.core.render_stats import RenderStats, describe_stage


def test_describe_stage_known_stages():
    assert describe_stage("draw_part.sweep") == "Sweeping tube along path"
    assert describe_stage("draw_part.optimize") == "Running print optimization"


def test_describe_stage_export_job():
    assert describe_stage("render_pipeline.job.stl.part.stl") == "Exporting STL (part.stl)"
    assert describe_stage("render_pipeline.job.preview.part.png") == "Rendering preview (part.png)"
    assert describe_stage("render_pipeline.job.config.part.yaml") == "Writing config snapshot (part.yaml)"


def test_record_stage_logs_start_and_end(caplog):
    caplog.set_level(logging.INFO, logger="led_knots.core.render_stats")
    stats = RenderStats()
    with stats.record_stage("draw_part.sweep"):
        pass
    messages = [record.message for record in caplog.records]
    assert messages[0] == "Sweeping tube along path"
    assert messages[1].startswith("Sweeping tube along path completed (")
    assert messages[1].endswith("s)")


def test_add_stat_namespacing():
    stats = RenderStats()
    stats.add_stat("draw_part.sweep.duration_s", 1.25, "Sweep stage duration")
    assert len(stats._stats) == 1
    assert stats._stats[0].name == "draw_part.sweep.duration_s"


def test_write_csv_column_alignment(tmp_path: Path):
    stats = RenderStats()
    stats.add_stat("a", "x", "short")
    stats.add_stat("longer.name", "value", "much longer description field")
    out = tmp_path / "stats.csv"
    stats.write_csv(out)
    text = out.read_text(encoding="utf-8")
    lines = text.strip().splitlines()
    assert len(lines) == 3
    assert lines[0].startswith("name")
    assert ", " in lines[1]
    widths = [len(part) for part in lines[1].split(", ")]
    widths2 = [len(part) for part in lines[2].split(", ")]
    assert widths[0] == widths2[0]
    assert widths[1] == widths2[1]


def test_git_and_config_sources_populated(tmp_path: Path):
    stats = RenderStats()
    stats.populate_config_sources(
        base_path=tmp_path / "config.yaml",
        local_path=tmp_path / "config.local.yaml",
        overlay_path=None,
    )
    stats.populate_git_info()
    names = {s.name for s in stats._stats}
    assert "config.sources.base" in names
    assert "git.branch" in names
    assert "git.commit" in names
