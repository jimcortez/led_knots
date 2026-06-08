"""Tests for knot module discovery and dispatch."""

from __future__ import annotations

import pytest

from led_knots.knots import registry


EXPECTED_KNOT_TYPES = {
    "figure_8",
    "helix",
    "jog_bend",
    "jog_bend_3d",
    "k4_1",
    "k8_21",
    "quarter_turn",
    "ring",
    "rod",
    "sine_wave",
    "stevedore",
    "trefoil",
    "twisted_rod",
}


def test_list_knot_types_discovers_all_modules():
    assert set(registry.list_knot_types()) == EXPECTED_KNOT_TYPES


def test_each_knot_module_exposes_build():
    for knot_type in registry.list_knot_types():
        builder = registry.load_builder(knot_type)
        assert callable(builder)


def test_unknown_knot_type_raises_with_available_list():
    with pytest.raises(ValueError, match="knot_type 'missing' not found"):
        registry.load_builder("missing")
