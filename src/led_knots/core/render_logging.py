"""Per-render log buffering and file output for render bundles."""

from __future__ import annotations

import logging
import logging.handlers
import time
from pathlib import Path

_FILE_LOG_FORMAT = "%(asctime)s %(levelname)s:%(name)s:%(message)s"
_FILE_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

_memory_handler: logging.handlers.MemoryHandler | None = None
_saved_root_level: int | None = None


class _RenderLogFormatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        ct = self.converter(record.created)
        fmt = datefmt or _FILE_LOG_DATEFMT
        stamp = time.strftime(fmt, ct)
        return f"{stamp},{int(record.msecs):03d}"


def _file_formatter() -> logging.Formatter:
    return _RenderLogFormatter(_FILE_LOG_FORMAT, datefmt=_FILE_LOG_DATEFMT)


def attach_render_log_buffer() -> None:
    """Buffer DEBUG+ records in memory until finalize or discard."""
    global _memory_handler, _saved_root_level
    if _memory_handler is not None:
        return
    root = logging.root
    _saved_root_level = root.level
    root.setLevel(logging.DEBUG)
    handler = logging.handlers.MemoryHandler(capacity=-1)
    handler.setLevel(logging.DEBUG)
    root.addHandler(handler)
    _memory_handler = handler


def finalize_render_log(log_path: Path) -> None:
    """Flush buffered records to a timestamped log file and keep logging to it."""
    global _memory_handler
    if _memory_handler is None:
        return
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(_file_formatter())
    _memory_handler.setTarget(file_handler)
    _memory_handler.flush()
    root = logging.root
    root.removeHandler(_memory_handler)
    _memory_handler.close()
    _memory_handler = None
    root.addHandler(file_handler)


def discard_render_log_buffer() -> None:
    """Drop buffered records without writing a log file."""
    global _memory_handler, _saved_root_level
    if _memory_handler is None:
        return
    root = logging.root
    root.removeHandler(_memory_handler)
    _memory_handler.close()
    _memory_handler = None
    if _saved_root_level is not None:
        root.setLevel(_saved_root_level)
        _saved_root_level = None
