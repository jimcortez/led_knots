"""
Single-2D-face-swept-along-path tube model.

Wraps the simple `create_*_face` factories and performs one `sweep(face, path)`
to produce a smooth tube. Covers `led_circle`, `led_circle_tube`,
`led_circle_quad_tube`, `solid_circle`, and `square`.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Union

import cadquery as cq
from cadquery.func import sweep

from ..led_circle import (
    create_led_circle_face,
    create_led_circle_quad_tube_face,
    create_led_circle_tube_face,
    create_solid_circle_face,
    create_square_face,
)

logger = logging.getLogger(__name__)


_FACE_FACTORIES = {
    "led_circle": (create_led_circle_face, "to_led_circle_face_kwargs"),
    "led_circle_tube": (create_led_circle_tube_face, "to_led_circle_tube_face_kwargs"),
    "led_circle_quad_tube": (create_led_circle_quad_tube_face, "to_led_circle_tube_face_kwargs"),
    "solid_circle": (create_solid_circle_face, "to_led_circle_face_kwargs"),
    "square": (create_square_face, "to_led_circle_face_kwargs"),
}


class SweptFaceModel:
    """Build a swept tube by calling the registered face factory and `sweep(face, path)`."""

    def __init__(self, face_type: str) -> None:
        if face_type not in _FACE_FACTORIES:
            raise ValueError(
                f"SweptFaceModel does not handle face_type {face_type!r}. "
                f"Supported: {sorted(_FACE_FACTORIES)!r}"
            )
        self.face_type = face_type
        self._factory, self._kwargs_method = _FACE_FACTORIES[face_type]

    def build_face(self, *, path, config: Any, face_kwargs: Optional[Dict[str, Any]] = None):
        """Build the oriented 2D face without sweeping (used by composite models)."""
        kwargs = self._resolve_face_kwargs(path=path, config=config, face_kwargs=face_kwargs)
        return self._factory(**kwargs)

    def build(
        self,
        *,
        path,
        aux,
        config: Any,
        face_kwargs: Optional[Dict[str, Any]] = None,
    ) -> Union[cq.Solid, cq.Compound]:
        face = self.build_face(path=path, config=config, face_kwargs=face_kwargs)
        logger.debug("SweptFaceModel(%s): sweeping single profile", self.face_type)
        return sweep(face, path, aux=aux)

    def _resolve_face_kwargs(
        self,
        *,
        path,
        config: Any,
        face_kwargs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        builder = getattr(config.tube_settings, self._kwargs_method)
        return builder(orient_to_path=path, **(face_kwargs or {}))
