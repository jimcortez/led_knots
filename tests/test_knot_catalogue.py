"""The 15-knot set: every slot has a module, a config, and the right topology.

knotbook.ipynb is the spec for which 15 knots this project builds. These tests
pin that spec to the two artefacts each slot needs -- a module in
led_knots.knots and a YAML in knot_configs/ -- and, for the slots built from a
DT code, check that the relaxed space curve is still the knot it claims to be.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import yaml

from led_knots.knots import registry

REPO_ROOT = Path(__file__).resolve().parent.parent
KNOT_CONFIGS = REPO_ROOT / "knot_configs"

# (slot, module stem, config filename). Mirrors knotbook.ipynb cell order.
KNOTBOOK_SLOTS = [
    (1, "ring", "k1_1-ring.yaml"),
    (2, "k2_1", "k2_1.yaml"),
    (3, "trefoil", "k3_1-trefoil.yaml"),
    (4, "k4_1", "k4_1-figure-eight.yaml"),
    (5, "k5_2", "k5_2-three-twist.yaml"),
    (6, "k6_3", "k6_3.yaml"),
    (7, "k7_1", "k7_1-septoil.yaml"),
    (8, "k8_21", "k8_21.yaml"),
    (9, "k9_2", "k9_2.yaml"),
    (10, "k10_7", "k10_7.yaml"),
    (11, "k11a6", "k11a6.yaml"),
    (12, "k12a6", "k12a6.yaml"),
    (13, "k13a6", "k13a6.yaml"),
    (14, "k14n2", "k14n2.yaml"),
    (15, "k15n3", "k15n3.yaml"),
]

# Slots whose path comes from a catalogue DT code, and the catalogue name each
# one asks for. These are the slots that run through relax_knot_points, which
# can change the knot type without raising, so they get an identify() check.
DT_CODE_SLOTS = {
    "k6_3": "6_3",
    "k7_1": "7_1",
    "k9_2": "9_2",
    "k10_7": "10_7",
    "k11a6": "K11a6",
    "k12a6": "K12a6",
    "k13a6": "K13a6",
    "k14n2": "K14n2",
    "k15n3": "K15n3",
}


def test_knotbook_has_fifteen_slots():
    assert [slot for slot, _, _ in KNOTBOOK_SLOTS] == list(range(1, 16))


@pytest.mark.parametrize(
    "knot_type,config_name",
    [(t, c) for _, t, c in KNOTBOOK_SLOTS],
    ids=[f"{slot:02d}-{t}" for slot, t, _ in KNOTBOOK_SLOTS],
)
def test_slot_has_module_and_config(knot_type, config_name):
    """Each slot's config exists and its knot_type resolves to a builder."""
    config_path = KNOT_CONFIGS / config_name
    assert config_path.is_file(), f"missing config {config_path}"

    declared = yaml.safe_load(config_path.read_text(encoding="utf-8"))["knot_type"]
    assert declared == knot_type

    assert callable(registry.load_builder(declared))


def test_private_modules_are_not_knot_types():
    """Underscore-prefixed stems are helpers, not selectable knot types."""
    assert not [t for t in registry.list_knot_types() if t.startswith("_")]


@pytest.mark.slow
@pytest.mark.parametrize("knot_type,catalogue_name", sorted(DT_CODE_SLOTS.items()))
def test_dt_slot_relaxes_to_the_right_knot(knot_type, catalogue_name):
    """The relaxed curve still identifies as the knot the module names.

    relax_knot_points is cosmetic and unpoliced: it can push a strand through
    another and hand back a different, simpler knot with no error. At 200
    points that is exactly what happens above 11 crossings (K15n3 comes out as
    6_2), which is why the 12+ modules raise NUM_POINTS. This test is what
    those constants are pinned by, so run it before changing them.

    identify() matches on invariants, so for the high-crossing knots it returns
    a set of candidates rather than one name -- membership is the strongest
    claim available here, not equality.
    """
    from led_knots.core import knot_from_name

    module = importlib.import_module(f"led_knots.knots.{knot_type}")
    knot = knot_from_name(
        catalogue_name,
        num_points=module.NUM_POINTS,
        relax_steps=module.RELAX_STEPS,
    )

    candidates = {str(entry).strip("<>").removeprefix("Knot ") for entry in knot.identify()}
    assert catalogue_name in candidates, (
        f"{knot_type}: relaxed curve identifies as {sorted(candidates)[:5]}, "
        f"not {catalogue_name}. Raise NUM_POINTS in "
        f"src/led_knots/knots/{knot_type}.py."
    )

