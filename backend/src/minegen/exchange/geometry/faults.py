"""Fault projection: the analytic ``FaultPlane`` parameters (authority) and
the plane clipped to the field-lattice box as a planar polygon (the SAME
clip the scene manifest ships — visualization geometry, never a solid)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.exchange.models import COORDINATE_FRAME, MINE_EXCHANGE_VERSION
from minegen.world.geology import FaultPlane
from minegen.world.synthetic_world import SyntheticWorld

FloatArray = npt.NDArray[np.float64]


def fault_entity_id(index: int) -> str:
    """Deterministic id: the scene's ``F-01`` numbering without the dash
    (``fault:F01``); faults carry no authoritative id of their own."""
    return f"fault:F{index + 1:02d}"


@dataclass(frozen=True)
class FaultProjection:
    entity_id: str
    plane: FaultPlane
    polygon: FloatArray  # (N, 3) ordered convex polygon (may be empty)


def project_faults(world: SyntheticWorld) -> list[FaultProjection]:
    grid = world.fields.grid
    box_min = np.asarray(grid.origin, dtype=np.float64)
    box_max = np.asarray(grid.max_corner, dtype=np.float64)
    return [
        FaultProjection(fault_entity_id(i), f, np.asarray(f.clip_to_box(box_min, box_max)))
        for i, f in enumerate(world.faults)
    ]


def faults_document(faults: list[FaultProjection]) -> dict[str, Any]:
    return {
        "mineExchangeVersion": MINE_EXCHANGE_VERSION,
        "semanticType": "FAULT_MODEL",
        "coordinateFrame": COORDINATE_FRAME,
        "units": {"length": "metre", "angle": "degree"},
        "conventions": {
            "strike": "clockwise azimuth from +Y (north)",
            "dip": "dip direction = strike + 90° (right-hand rule)",
            "halfWidths": "perpendicular half-widths from the plane (rule 36)",
        },
        "faults": [
            {
                "entityId": fp.entity_id,
                "origin": fp.plane.origin.tolist(),
                "normal": fp.plane.normal.tolist(),
                "strikeVector": fp.plane.u.tolist(),
                "dipVector": fp.plane.v.tolist(),
                "strikeDeg": fp.plane.config.strike_deg,
                "dipDeg": fp.plane.config.dip_deg,
                "coreHalfWidth": fp.plane.config.core_half_width,
                "influenceHalfWidth": fp.plane.config.influence_half_width,
                "corePenalty": fp.plane.config.core_penalty,
                "damageZonePenalty": fp.plane.config.damage_zone_penalty,
                "clippedPolygonVertexCount": int(fp.polygon.shape[0]),
                "representation": "PLANAR_SURFACE (clipped to the field-lattice box); not a solid",
            }
            for fp in faults
        ],
    }
