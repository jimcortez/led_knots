"""TubeModel protocol."""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, Union, runtime_checkable

import cadquery as cq


@runtime_checkable
class TubeModel(Protocol):
    """
    A tube model takes a centerline path and produces a 3D result.

    The contract matches what `build_tube_from_path` used to return: either a
    single `Solid`/`Compound` (one swept tube) or a `Compound` of multiple
    sub-solids (e.g. core + N braided strands).
    """

    def build(
        self,
        *,
        path,
        aux,
        config: Any,
        face_kwargs: Optional[Dict[str, Any]] = None,
    ) -> Union[cq.Solid, cq.Compound]: ...
