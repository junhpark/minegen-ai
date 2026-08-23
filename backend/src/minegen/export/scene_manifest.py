"""Lightweight web scene payload for Phase 02 (terrain, orebody, faults,
ore blocks, one rock-quality slice). All coordinates ENU Z-up; the frontend
converts at its rendering boundary (rule 4 / 17).

Large volumes are never sent whole: rock quality goes out as axis-aligned
slices on request, ore blocks only as the (small) set of ore-flagged blocks.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import numpy.typing as npt

from minegen.config import CANONICAL_COORDINATE_SYSTEM
from minegen.core.models import Scenario
from minegen.world.block_model import BlockModel
from minegen.world.synthetic_world import SyntheticWorld

SliceAxis = Literal["x", "y", "z"]
SliceField = Literal["rockQuality", "grade", "faultInfluence", "faultZone", "oreFraction"]

_FIELD_ATTR: dict[str, str] = {
    "rockQuality": "rock_quality",
    "grade": "grade",
    "faultInfluence": "fault_influence",
    "faultZone": "fault_zone",
    "oreFraction": "ore_fraction",
}
_AXIS_INDEX: dict[str, int] = {"x": 0, "y": 1, "z": 2}


def _finite_minmax(a: npt.NDArray[Any]) -> tuple[float, float]:
    f = a[np.isfinite(a)]
    if f.size == 0:
        return 0.0, 0.0
    return float(f.min()), float(f.max())


def slice_payload(bm: BlockModel, field: SliceField, axis: SliceAxis, index: int) -> dict[str, Any]:
    arr = getattr(bm, _FIELD_ATTR[field])
    ax = _AXIS_INDEX[axis]
    n = bm.grid.shape[ax]
    if not 0 <= index < n:
        raise IndexError(f"slice index {index} out of range [0, {n})")
    plane = np.take(arr, index, axis=ax).astype(np.float64)
    # non-finite values (no-fault signed distances) never reach the wire
    plane = np.where(np.isfinite(plane), plane, 0.0)
    other = [a for a in range(3) if a != ax]
    names = ["x", "y", "z"]
    lo, hi = _finite_minmax(plane)
    return {
        "field": field,
        "axis": axis,
        "index": index,
        "count": n,
        "coordinate": float(bm.grid.axis_centers(ax)[index]),
        "rows": {
            "axis": names[other[0]],
            "origin": bm.grid.origin[other[0]],
            "spacing": bm.grid.spacing[other[0]],
            "n": bm.grid.shape[other[0]],
        },
        "cols": {
            "axis": names[other[1]],
            "origin": bm.grid.origin[other[1]],
            "spacing": bm.grid.spacing[other[1]],
            "n": bm.grid.shape[other[1]],
        },
        "values": plane.ravel().tolist(),  # row-major: rows × cols
        "min": lo,
        "max": hi,
    }


def ore_blocks_payload(bm: BlockModel) -> dict[str, Any]:
    idx = np.argwhere(bm.ore_flag)
    centers = bm.grid.origin + (idx + 0.5) * np.asarray(bm.grid.spacing)
    grade = bm.grade[bm.ore_flag].astype(np.float64)
    lo, hi = _finite_minmax(grade)
    return {
        "count": int(idx.shape[0]),
        "spacing": list(bm.grid.spacing),
        "centers": centers.ravel().tolist(),
        "grade": grade.tolist(),
        "gradeMin": lo,
        "gradeMax": hi,
    }


def build_scene(scenario: Scenario, world: SyntheticWorld) -> dict[str, Any]:
    t = world.terrain
    verts, faces = world.orebody.mesh()
    bm = world.block_model
    box_min = np.asarray(bm.grid.origin)
    box_max = np.asarray(bm.grid.max_corner)

    faults = []
    for i, f in enumerate(world.faults):
        poly = f.clip_to_box(box_min, box_max)
        faults.append(
            {
                "id": f"F-{i + 1:02d}",
                "strikeDeg": f.config.strike_deg,
                "dipDeg": f.config.dip_deg,
                "coreHalfWidth": f.config.core_half_width,
                "influenceHalfWidth": f.config.influence_half_width,
                "origin": f.origin.tolist(),
                "normal": f.normal.tolist(),
                "polygon": poly.ravel().tolist(),
                "vertexCount": int(poly.shape[0]),
            }
        )

    # default rock-quality slice: horizontal through the orebody center
    zc = bm.grid.axis_centers(2)
    k = int(np.clip(np.argmin(np.abs(zc - world.orebody.center[2])), 0, len(zc) - 1))
    rq_lo, rq_hi = _finite_minmax(bm.rock_quality[bm.rock_type != 0])

    return {
        "scenarioId": scenario.id,
        "coordinateSystem": CANONICAL_COORDINATE_SYSTEM,
        "world": {
            "sizeX": scenario.world.size_x,
            "sizeY": scenario.world.size_y,
            "depth": scenario.world.depth,
            "bottomElevation": scenario.world.bottom_elevation(scenario.terrain.base_elevation),
            "referenceElevation": scenario.terrain.base_elevation,
        },
        "terrain": {
            "x0": t.x0,
            "y0": t.y0,
            "spacing": t.spacing,
            "nx": t.nx,
            "ny": t.ny,
            "z": t.z.ravel().tolist(),  # row-major (i over x, j over y)
            "zMin": t.z_min,
            "zMax": t.z_max,
        },
        "orebody": {
            **world.orebody.to_dict(),
            "positions": verts.ravel().tolist(),
            "indices": faces.ravel().tolist(),
        },
        "faults": faults,
        "oreBlocks": ore_blocks_payload(bm),
        "blockGrid": bm.grid.to_dict(),
        "rockQuality": {
            "min": rq_lo,
            "max": rq_hi,
            "defaultSlice": slice_payload(bm, "rockQuality", "z", k),
        },
        "stats": world.stats(scenario),
    }
