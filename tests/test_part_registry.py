"""Tests for part module discovery and dispatch."""

from __future__ import annotations

import pytest

from led_knots.parts import registry


EXPECTED_PART_TYPES = {"hang_clamp", "planet_spacer"}


def test_list_part_types_discovers_all_modules():
    assert set(registry.list_part_types()) == EXPECTED_PART_TYPES


def test_each_part_module_exposes_build():
    for part_type in registry.list_part_types():
        builder = registry.load_builder(part_type)
        assert callable(builder)


def test_unknown_part_type_raises_with_available_list():
    with pytest.raises(ValueError, match="part_type 'missing' not found"):
        registry.load_builder("missing")
