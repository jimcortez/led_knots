"""
Configuration for the print-optimization stage.

Mirrors the validation pattern used by the other settings classes in
``led_knots.core.config``: one class per YAML block, validates in
``__init__`` and raises ``ValueError`` for nonsense values.
"""

from __future__ import annotations

from typing import Any, Dict


_VALID_TARGETS = ("sla", "fdm")


class OrientationSettings:
    """Search settings for the build-orientation optimizer."""

    def __init__(self, data: Dict[str, Any]):
        data = data or {}
        self.enabled: bool = bool(data.get("enabled", True))
        self.auto_apply: bool = bool(data.get("auto_apply", False))
        self.top_n_candidates: int = int(data.get("top_n_candidates", 5))
        if self.top_n_candidates < 1:
            raise ValueError("print_optimization.orientation.top_n_candidates must be >= 1")


class PrintOptimizationSettings:
    """Top-level toggles for the SLA/resin print-optimization stage."""

    def __init__(self, data: Dict[str, Any]):
        data = data or {}
        self.enabled: bool = bool(data.get("enabled", False))
        self.target: str = str(data.get("target", "sla")).strip().lower()
        if self.target not in _VALID_TARGETS:
            raise ValueError(
                f"print_optimization.target must be one of {_VALID_TARGETS!r} (got {self.target!r})"
            )
        self.overhang_threshold_deg: float = float(data.get("overhang_threshold_deg", 35.0))
        if not (0.0 < self.overhang_threshold_deg < 90.0):
            raise ValueError(
                "print_optimization.overhang_threshold_deg must be in (0, 90)"
            )
        self.orientation = OrientationSettings(data.get("orientation", {}))

    def cache_key_dict(self) -> Dict[str, Any]:
        """
        Stable dict representation for inclusion in
        ``cache_utils.config_settings_hash``. Including this in the cache key
        prevents stale preview STLs from being served when optimization
        toggles change.
        """
        return {
            "enabled": bool(self.enabled),
            "target": str(self.target),
            "overhang_threshold_deg": float(self.overhang_threshold_deg),
            "orientation": {
                "enabled": bool(self.orientation.enabled),
                "auto_apply": bool(self.orientation.auto_apply),
                "top_n_candidates": int(self.orientation.top_n_candidates),
            },
        }
