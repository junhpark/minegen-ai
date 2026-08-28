"""Design-side hard constraints shared by the cost evaluator and (later) the
decline generator. Everything here is a predicate on continuous points.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
import numpy.typing as npt

from minegen.core.models import DesignConfig, RestrictedZone

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]


class RejectionReason(StrEnum):
    OUTSIDE_WORLD = "OUTSIDE_WORLD"
    ABOVE_TERRAIN = "ABOVE_TERRAIN"
    INSUFFICIENT_COVER = "INSUFFICIENT_COVER"
    INSIDE_OREBODY = "INSIDE_OREBODY"
    OREBODY_BUFFER = "OREBODY_BUFFER"
    RESTRICTED_ZONE = "RESTRICTED_ZONE"
    # access-target lattice reasons (targets.py)
    OUTSIDE_OREBODY_STRIKE_EXTENT = "OUTSIDE_OREBODY_STRIKE_EXTENT"
    OUTSIDE_OREBODY_DIP_EXTENT = "OUTSIDE_OREBODY_DIP_EXTENT"


@dataclass(frozen=True)
class DesignContext:
    """What kind of excavation is being costed. The default is the decline
    context: the orebody and a buffer around it are hard exclusions.
    Phase 08 crosscuts will use a context that permits entering the
    orebody (``orebody_exclusion_buffer = 0``, ``allow_inside_orebody = True``)."""

    name: str = "decline"
    orebody_exclusion_buffer: float = 5.0
    allow_inside_orebody: bool = False
    minimum_surface_cover: float = 0.0
    restricted_zones: tuple[RestrictedZone, ...] = field(default_factory=tuple)

    @classmethod
    def decline(cls, cfg: DesignConfig) -> DesignContext:
        return cls(
            name="decline",
            orebody_exclusion_buffer=cfg.orebody_exclusion_buffer,
            allow_inside_orebody=False,
            minimum_surface_cover=cfg.minimum_surface_cover,
            restricted_zones=tuple(cfg.restricted_zones),
        )

    @classmethod
    def crosscut(cls, cfg: DesignConfig) -> DesignContext:
        """Phase 08 crosscut context (rule 72): the crosscut deliberately
        reaches the orebody contact, so the orebody exclusion is disabled
        (buffer 0, inside allowed) while world, terrain and restricted-zone
        hard constraints are retained unchanged."""
        return cls(
            name="crosscut",
            orebody_exclusion_buffer=0.0,
            allow_inside_orebody=True,
            minimum_surface_cover=cfg.minimum_surface_cover,
            restricted_zones=tuple(cfg.restricted_zones),
        )


def in_restricted_zone(points: FloatArray, zones: tuple[RestrictedZone, ...]) -> BoolArray:
    p = np.asarray(points, dtype=np.float64)
    hit = np.zeros(p.shape[:-1], dtype=bool)
    for z in zones:
        lo = np.array(z.min.as_tuple())
        hi = np.array(z.max.as_tuple())
        hit |= np.all((p >= lo) & (p <= hi), axis=-1)
    return hit
