"""Explicit Ventsim seed adapter parameters (``docs/external-adapters.md``
§7 / §10 / §11.4). Every value here is either user-supplied or resolved to a
DOCUMENTED adapter default that the report records as
``ADAPTER_DEFAULT_EXPLICIT``; nothing is hidden in code."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from minegen.core.models import ApiModel

#: Q1 default: sub-metre 3-D Douglas–Peucker on the 2 m sampled centerlines
#: (a 0.5 m chord tolerance is one tenth of the default 5 m tunnel width,
#: far below any airway-resistance relevance, and cuts a spiral's airway
#: count several-fold). ``0`` delivers the authoritative polyline verbatim.
DEFAULT_SIMPLIFICATION_TOLERANCE_M = 0.5
#: a tolerance beyond one tunnel width would not be a representation
#: tolerance any more — validated, never clamped
MAX_SIMPLIFICATION_TOLERANCE_M = 5.0


class VentsimSeedConfig(ApiModel):
    #: ``None`` → ``DEFAULT_SIMPLIFICATION_TOLERANCE_M`` (recorded as an
    #: explicit adapter default); ``0`` → polyline-faithful
    simplification_tolerance_m: float | None = Field(
        default=None, ge=0.0, le=MAX_SIMPLIFICATION_TOLERANCE_M
    )
    #: metres, added to every emitted coordinate on the source axes (an
    #: explicit user re-basing; the default is no translation)
    origin_offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    #: how airway dimensions reach Ventsim — DXF carries geometry only, so the
    #: 0.1.0 adapter delivers width / height / shape through the attribute
    #: table for post-conversion assignment (the only documented path)
    dimension_delivery_policy: Literal["ATTRIBUTE_TABLE"] = "ATTRIBUTE_TABLE"
    #: the one target format this adapter version produces
    target_format: Literal["DXF_R12_3D_POLYLINES"] = "DXF_R12_3D_POLYLINES"
