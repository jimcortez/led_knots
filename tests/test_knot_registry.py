"""Tests for knot module discovery and dispatch."""

from __future__ import annotations

import pytest

from led_knots.knots import registry


EXPECTED_KNOT_TYPES = {
    # The 15 knotbook slots (see tests/test_knot_catalogue.py for the mapping).
    "ring",
    "k2_1",
    "trefoil",
    "k4_1",
    "k5_2",
    "k6_3",
    "k7_1",
    "k8_21",
    "k9_2",
    "k10_7",
    "k11a6",
    "k12a6",
    "k13a6",
    "k14n2",
    "k15n3",
    # Extra knots, outside the 15.
    "k9_35",
    "stevedore",
    "twist_ring",
    # Non-knot test and utility shapes.
    "helix",
    "jog_bend",
    "jog_bend_3d",
    "quarter_turn",
    "rod",
    "sine_wave",
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
