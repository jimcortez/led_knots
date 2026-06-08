"""Collect render-run statistics and write space-aligned CSV."""

from __future__ import annotations

import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, List, Optional


@dataclass
class RenderStat:
    name: str
    value: str
    description: str


class RenderStats:
    """Namespaced stat collector passed through the render pipeline."""

    def __init__(self) -> None:
        self._stats: List[RenderStat] = []
        self._stage_starts: dict[str, float] = {}
        self._run_start = time.perf_counter()

    def add_stat(self, name: str, value: Any, description: str) -> None:
        self._stats.append(RenderStat(name=str(name), value=str(value), description=str(description)))

    @contextmanager
    def record_stage(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            self.add_stat(name, f"{elapsed:.4f}", f"Stage duration in seconds")

    def populate_git_info(self) -> None:
        for key, cmd, desc in (
            ("git.branch", ["git", "branch", "--show-current"], "Current git branch"),
            ("git.commit", ["git", "rev-parse", "HEAD"], "Current git commit hash"),
        ):
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=5,
                )
                value = result.stdout.strip()
            except (subprocess.SubprocessError, OSError):
                value = ""
            self.add_stat(key, value, desc)

    def populate_config_sources(
        self,
        *,
        base_path: Optional[Path],
        local_path: Optional[Path],
        overlay_path: Optional[Path],
    ) -> None:
        self.add_stat(
            "config.sources.base",
            str(base_path) if base_path else "",
            "Base config.yaml path",
        )
        self.add_stat(
            "config.sources.local",
            str(local_path) if local_path and local_path.exists() else "",
            "Local config.local.yaml path if present",
        )
        self.add_stat(
            "config.sources.overlay",
            str(overlay_path) if overlay_path else "",
            "CLI config file path if used",
        )

    def finalize_total_duration(self) -> None:
        total = time.perf_counter() - self._run_start
        self.add_stat("render.total.duration_s", f"{total:.4f}", "Wall-clock duration for entire render run")

    def write_csv(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [("name", "value", "description")]
        for stat in self._stats:
            rows.append((stat.name, stat.value, stat.description))
        col_widths = [
            max(len(row[i]) for row in rows)
            for i in range(3)
        ]
        lines = []
        for idx, row in enumerate(rows):
            padded = [
                row[0].ljust(col_widths[0]),
                row[1].ljust(col_widths[1]),
                row[2].ljust(col_widths[2]),
            ]
            lines.append(", ".join(padded))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
