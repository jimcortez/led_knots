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
        # Multiplicative shave on Tweaker-3 unprintability when an
        # orientation makes the LED-tube connectors stand vertically
        # (so they act as natural support columns). 0 disables.
        self.connector_bonus_weight: float = float(
            data.get("connector_bonus_weight", 0.7)
        )
        if not (0.0 <= self.connector_bonus_weight < 1.0):
            raise ValueError(
                "print_optimization.orientation.connector_bonus_weight must be in [0, 1)"
            )


class DrainHoleSettings:
    """Auto-drill drain/vent holes through trapped resin cavities."""

    def __init__(self, data: Dict[str, Any]):
        data = data or {}
        self.enabled: bool = bool(data.get("enabled", False))
        self.diameter_mm: float = float(data.get("diameter_mm", 1.5))
        self.min_cavity_volume_mm3: float = float(
            data.get("min_cavity_volume_mm3", 100.0)
        )
        # The drill cylinder extends this far beyond the part's z-extents
        # on both sides so the boolean cut cleanly punctures top + bottom
        # walls (a vent at the top breaks suction; a drain at the bottom
        # lets resin escape under gravity).
        self.margin_mm: float = float(data.get("margin_mm", 5.0))
        if self.diameter_mm <= 0:
            raise ValueError("print_optimization.drain_holes.diameter_mm must be > 0")
        if self.min_cavity_volume_mm3 < 0:
            raise ValueError("print_optimization.drain_holes.min_cavity_volume_mm3 must be >= 0")
        if self.margin_mm < 0:
            raise ValueError("print_optimization.drain_holes.margin_mm must be >= 0")


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
        self.drain_holes = DrainHoleSettings(data.get("drain_holes", {}))

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
                "connector_bonus_weight": float(
                    self.orientation.connector_bonus_weight
                ),
            },
            "drain_holes": {
                "enabled": bool(self.drain_holes.enabled),
                "diameter_mm": float(self.drain_holes.diameter_mm),
                "min_cavity_volume_mm3": float(self.drain_holes.min_cavity_volume_mm3),
                "margin_mm": float(self.drain_holes.margin_mm),
            },
        }
