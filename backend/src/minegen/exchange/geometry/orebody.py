"""Orebody projection: the authoritative solid contract (``to_dict``) plus
its backend-authored derived surface mesh. The mesh is a DERIVED
representation; membership authority stays with the analytic / implicit
solid (rules 120 / 133)."""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.core.models import Scenario
from minegen.exchange.models import COORDINATE_FRAME, MINE_EXCHANGE_VERSION
from minegen.world.orebody import AnalyticOrebody, Orebody

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

OREBODY_ENTITY_ID = "orebody:primary"


def orebody_document(scenario: Scenario, orebody: Orebody) -> dict[str, Any]:
    """``orebody.json``: the existing authority projected (``to_dict`` —
    type, centre, u/v/w axes, extents / semi-axes / morphology, bbox,
    volume + method, distance contract; WARPED_VEIN keeps its
    shapeModelVersion, geometry lattice, morphology and clearance metadata)
    plus the persisted scenario orebody parameters. Nothing is invented."""
    model = orebody.to_dict()
    return {
        "mineExchangeVersion": MINE_EXCHANGE_VERSION,
        "semanticType": "OREBODY_MODEL",
        "entityId": OREBODY_ENTITY_ID,
        "coordinateFrame": COORDINATE_FRAME,
        "units": {"length": "metre", "volume": "cubic metre"},
        "authority": "ANALYTIC_SOLID" if isinstance(orebody, AnalyticOrebody) else "IMPLICIT_SOLID",
        "membershipAuthority": (
            "the solid model below (contains / signed distance or implicit level); "
            "the exported mesh is a derived surface, never the membership authority"
        ),
        "model": model,
        "sourceParameters": scenario.orebody.model_dump(mode="json", by_alias=True),
    }


def orebody_mesh(orebody: Orebody) -> tuple[FloatArray, IntArray]:
    verts, faces = orebody.mesh()
    return (
        np.asarray(verts, dtype=np.float64).reshape(-1, 3),
        np.asarray(faces, dtype=np.int64).reshape(-1, 3),
    )
