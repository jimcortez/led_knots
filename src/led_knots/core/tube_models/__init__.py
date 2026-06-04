"""
Tube model registry: maps a `face_type` from config to a `TubeModel`.

A `TubeModel` turns a centerline path into a 3D solid (or compound) of tube
geometry. The simple swept-face models, the pyramid-studded model, and the
braided-rope model all implement the same interface and share path-frame
utilities from `path_frames.py`.
"""

from __future__ import annotations

from typing import Dict

from ._base import TubeModel
from .swept_face import SweptFaceModel

_REGISTRY: Dict[str, TubeModel] = {
    "led_circle": SweptFaceModel("led_circle"),
    "led_circle_tube": SweptFaceModel("led_circle_tube"),
    "solid_circle": SweptFaceModel("solid_circle"),
    "square": SweptFaceModel("square"),
}


def get_tube_model(face_type: str) -> TubeModel:
    """Return the registered `TubeModel` for `face_type`."""
    try:
        return _REGISTRY[face_type]
    except KeyError:
        raise ValueError(
            f"Unknown face_type: {face_type!r}. Registered: {sorted(_REGISTRY)!r}"
        ) from None


def register_tube_model(face_type: str, model: TubeModel) -> None:
    """Register or replace a tube model under `face_type`."""
    _REGISTRY[face_type] = model


def registered_face_types() -> tuple:
    return tuple(sorted(_REGISTRY))


# Register higher-level models after the registry exists so they can themselves
# look up `SweptFaceModel` for their base tube.
from .pyramid_studded import PyramidStuddedModel  # noqa: E402
from .braided_rope import BraidedRopeModel  # noqa: E402

_REGISTRY["pyramid_studded"] = PyramidStuddedModel()
_REGISTRY["braided_rope"] = BraidedRopeModel()


__all__ = [
    "TubeModel",
    "get_tube_model",
    "register_tube_model",
    "registered_face_types",
]
