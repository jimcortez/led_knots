"""led_circle_quad_tube: four equally-spaced connectors to the center tube.

The quad face must be identical to led_circle_tube except for two extra
connectors at 90° to the existing pair, all sharing `connector_width`.
"""

from __future__ import annotations

import pytest
from cadquery.func import circle, face

from led_knots.core.led_circle import (
    create_led_circle_quad_tube_face,
    create_led_circle_tube_face,
)

# config.yaml-like parameters (outer_diameter 30 → outer_radius 15).
_KWARGS = dict(
    outer_radius=15.0,
    wall_thickness=4.0,
    inner_tube_diameter=8.0,
    inner_tube_wall_thickness=0.5,
    connector_width=1.0,
)

_INNER_RADIUS = _KWARGS["outer_radius"] - _KWARGS["wall_thickness"]  # 11.0
_CENTER_OUTER_R = _KWARGS["inner_tube_diameter"] / 2.0 + _KWARGS["inner_tube_wall_thickness"]  # 4.5
_MID_R = (_INNER_RADIUS + _CENTER_OUTER_R) / 2.0  # mid-gap radius, connector territory


def _has_material_at(shape, x: float, y: float) -> bool:
    """True if the planar profile has material at (x, y)."""
    probe = face(circle(0.05)).moved(x=x, y=y)
    return (shape * probe).Area() > 1e-9


def _tube_and_quad():
    # rotation_z=0 keeps the base connector pair on the ±Y axis, which makes
    # the expected connector azimuths easy to probe.
    tube = create_led_circle_tube_face(rotation_z=0.0, **_KWARGS)
    quad = create_led_circle_quad_tube_face(rotation_z=0.0, **_KWARGS)
    return tube, quad


def test_quad_has_connectors_on_all_four_axes() -> None:
    tube, quad = _tube_and_quad()

    # Existing pair (±Y) is preserved...
    for sy in (1.0, -1.0):
        assert _has_material_at(tube, 0.0, sy * _MID_R)
        assert _has_material_at(quad, 0.0, sy * _MID_R)

    # ...and the quad adds a perpendicular pair (±X) the 2-connector face lacks.
    for sx in (1.0, -1.0):
        assert not _has_material_at(tube, sx * _MID_R, 0.0)
        assert _has_material_at(quad, sx * _MID_R, 0.0)

    # Neither face has material on the diagonals (equal spacing, no extras).
    d = _MID_R * 0.7071067811865476
    for sx in (1.0, -1.0):
        for sy in (1.0, -1.0):
            assert not _has_material_at(tube, sx * d, sy * d)
            assert not _has_material_at(quad, sx * d, sy * d)


def test_quad_area_adds_two_connectors() -> None:
    tube, quad = _tube_and_quad()
    extra = quad.Area() - tube.Area()
    # Two extra connectors spanning the ring-to-hub gap. The exact value is
    # slightly below width×gap because the fused boundary follows the circular
    # walls; allow a generous band around the nominal rectangle area.
    nominal = 2.0 * _KWARGS["connector_width"] * (_INNER_RADIUS - _CENTER_OUTER_R)
    assert 0.5 * nominal < extra < 1.2 * nominal


def test_two_connector_default_unchanged() -> None:
    # Regression guard for the connector_count refactor: the default call and
    # an explicit connector_count=2 must produce identical geometry.
    default = create_led_circle_tube_face(**_KWARGS)
    explicit = create_led_circle_tube_face(connector_count=2, **_KWARGS)
    assert default.Area() == pytest.approx(explicit.Area(), rel=1e-9)


def test_connector_count_validation() -> None:
    with pytest.raises(ValueError, match="connector_count"):
        create_led_circle_tube_face(connector_count=1, **_KWARGS)
    with pytest.raises(ValueError, match="connector_count"):
        create_led_circle_tube_face(connector_count=2.5, **_KWARGS)
