"""Lightweight web scene payload (terrain, orebody, faults, field lattice
description, one rock-quality slice). All coordinates ENU Z-up; the frontend
converts at its rendering boundary (rule 4 / 17).

Large volumes are never sent whole: fields go out as axis-aligned slices on
request. There is no block payload (Phase 18): the orebody is visible through
its own backend-authored mesh, and a slice of the grade field carries an
explicit display MASK derived from the analytic orebody so the lattice is
never presented as ore blocks (rule 129). That mask is a cell/solid
INTERSECTION test; point membership stays ``orebody.contains`` alone.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import numpy.typing as npt

from minegen.config import CANONICAL_COORDINATE_SYSTEM
from minegen.core.enums import MiningMethodType
from minegen.core.models import METHOD_PARAMETER_CLASSES, Scenario
from minegen.mining.methods.registry import all_plans, plan_for
from minegen.mining.models import (
    CutFillPayload,
    RoomPillarPayload,
    StopesPayload,
    production_payload_class,
)
from minegen.world.field_grid import FieldGrid
from minegen.world.orebody import AnalyticOrebody, Orebody
from minegen.world.synthetic_world import SyntheticWorld

SliceAxis = Literal["x", "y", "z"]
SliceField = Literal["rockQuality", "grade", "faultInfluence", "faultZone"]

_FIELD_ATTR: dict[str, str] = {
    "rockQuality": "rock_quality",
    "grade": "grade",
    "faultInfluence": "fault_influence",
    "faultZone": "fault_zone",
}
_AXIS_INDEX: dict[str, int] = {"x": 0, "y": 1, "z": 2}

#: how the ``mask`` of a slice was derived (display semantics only)
MASK_BELOW_TERRAIN = "BELOW_TERRAIN"
#: the display CELL intersects the analytic orebody solid — an intersection
#: test, deliberately NOT called membership: membership is a property of a
#: point and belongs to ``orebody.contains`` alone (rule 129)
MASK_OREBODY_INTERSECTION_BELOW_TERRAIN = "OREBODY_INTERSECTION_BELOW_TERRAIN"
#: sub-samples per axis for the cell/solid intersection test
OREBODY_INTERSECTION_SUBSAMPLES = 3


def _finite_minmax(a: npt.NDArray[Any]) -> tuple[float, float]:
    f = a[np.isfinite(a)]
    if f.size == 0:
        return 0.0, 0.0
    return float(f.min()), float(f.max())


def cells_intersect_orebody(
    grid: FieldGrid,
    centers: npt.NDArray[np.float64],
    orebody: Orebody,
    n_sub: int = OREBODY_INTERSECTION_SUBSAMPLES,
) -> npt.NDArray[np.bool_]:
    """``True`` where the display CELL centred on each point intersects the
    orebody solid.

    This is an INTERSECTION test on a cell, never a membership claim about a
    point: membership is ``orebody.contains`` and nothing else (rule 129).
    Deciding it takes three steps, each of them the solid's own geometry:

    1. ``contains(center)`` — the center is inside, so the cell certainly
       intersects;
    2. a certain-miss cull: for an ANALYTIC body ``sdf(center) >
       cell_half_diagonal`` (exact distance); for an IMPLICIT body only the
       conservative bounding box is used — the approximate clearance is
       never treated as an exact rejection bound (rule 134/135);
    3. otherwise a deterministic ``n³`` sub-sample of the cell is tested with
       ``contains``.

    Step 3 is an inner approximation: an intersection thinner than the
    sub-sample spacing can be missed. It is a visualization mask, so a missed
    sliver hides a cell rather than inventing mineralization — the failure
    direction we want."""
    hit = orebody.contains(centers)
    half = grid.cell_half_diagonal
    if isinstance(orebody, AnalyticOrebody):
        undecided = (~hit) & (orebody.signed_distance(centers) <= half)
    else:
        lo, hi = orebody.bounding_box()
        # a cell can only reach the solid if its center is within half a
        # cell diagonal of the solid's conservative envelope
        undecided = (~hit) & np.all((centers >= lo - half) & (centers <= hi + half), axis=-1)
    if bool(undecided.any()):
        offsets = grid.cell_subsample_offsets(n_sub)
        pts = centers[undecided][:, None, :] + offsets[None, :, :]
        inside = orebody.contains(pts.reshape(-1, 3)).reshape(-1, offsets.shape[0])
        hit[undecided] = inside.any(axis=1)
    return np.asarray(hit, dtype=np.bool_)


def slice_mask(
    world: SyntheticWorld, field: SliceField, axis: SliceAxis, index: int
) -> tuple[npt.NDArray[np.bool_], str]:
    """Display mask for a slice: ``True`` where the value is shown.

    Every field is masked to terrain-supported cells (below ground). The
    grade field is additionally masked to the cells that actually intersect
    the analytic orebody solid, because a synthetic grade value outside the
    orebody has no mineral meaning (rule 129). The mask is a visualization
    device — never a resource classification, and never a membership claim
    about the sampled point."""
    ax = _AXIS_INDEX[axis]
    supported = np.take(world.fields.supported, index, axis=ax).ravel()
    if field != "grade":
        return np.asarray(supported, dtype=np.bool_), MASK_BELOW_TERRAIN
    grid = world.fields.grid
    intersects = cells_intersect_orebody(grid, grid.plane_centers(ax, index), world.orebody)
    return np.asarray(supported & intersects, dtype=np.bool_), (
        MASK_OREBODY_INTERSECTION_BELOW_TERRAIN
    )


def slice_payload(
    world: SyntheticWorld, field: SliceField, axis: SliceAxis, index: int
) -> dict[str, Any]:
    grid = world.fields.grid
    f = world.fields.field(_FIELD_ATTR[field])
    ax = _AXIS_INDEX[axis]
    n = grid.shape[ax]
    if not 0 <= index < n:
        raise IndexError(f"slice index {index} out of range [0, {n})")
    plane = f.slice(ax, index)
    # non-finite values (no-fault signed distances) never reach the wire
    plane = np.where(np.isfinite(plane), plane, 0.0)
    other = [a for a in range(3) if a != ax]
    names = ["x", "y", "z"]
    mask, semantics = slice_mask(world, field, axis, index)
    shown = plane.ravel()[mask]
    lo, hi = _finite_minmax(shown if shown.size else plane)
    return {
        "field": field,
        "axis": axis,
        "index": index,
        "count": n,
        "coordinate": float(grid.axis_centers(ax)[index]),
        "rows": {
            "axis": names[other[0]],
            "origin": grid.origin[other[0]],
            "spacing": grid.spacing[other[0]],
            "n": grid.shape[other[0]],
        },
        "cols": {
            "axis": names[other[1]],
            "origin": grid.origin[other[1]],
            "spacing": grid.spacing[other[1]],
            "n": grid.shape[other[1]],
        },
        "values": plane.ravel().tolist(),  # row-major: rows × cols
        "mask": mask.astype(np.uint8).tolist(),  # 1 = shown, 0 = hidden
        "maskSemantics": semantics,
        "min": lo,
        "max": hi,
    }


def mining_method_summary(scenario: Scenario) -> dict[str, Any]:
    """The Mining-tab method card (rule 192 → Phase 21B/C): the requested
    method, the registry's implementation status, the explicit scenario
    parameters, the persisted method-specific ``methodParameters`` (``None``
    for Longhole / reserved methods), the production kind of the active
    method and the registry's full method table with each method's canonical
    default parameters. The registry is the single authority — the frontend
    never maps a method to a status, never invents a default and performs no
    method engineering; it edits explicit parameters and submits them
    (rule 124)."""
    mining = scenario.mining
    plan = plan_for(mining.method)
    mp = mining.method_parameters
    return {
        "method": mining.method.value,
        "displayName": plan.display_name,
        "implementationStatus": plan.implementation_status,
        "sublevelInterval": float(mining.sublevel_interval),
        "stopeLength": float(mining.stope_length),
        "minimumPillar": float(mining.minimum_pillar),
        "methodParameters": mp.model_dump(mode="json", by_alias=True) if mp is not None else None,
        "productionKind": _production_kind(mining.method),
        "availableMethods": [
            {
                "method": m.value,
                "displayName": p.display_name,
                "implementationStatus": p.implementation_status,
                "productionKind": _production_kind(m),
                "defaultParameters": _default_parameters(m),
            }
            for m, p in all_plans().items()
        ],
    }


def _production_kind(method: MiningMethodType) -> str | None:
    """The production semantics kind of an IMPLEMENTED method; ``None`` for a
    reserved method — its persisted typed FAILED boundary is Longhole-SHAPED
    for compatibility but it has no production, so the UI never presents it
    as stopes (Phase 21B/C review)."""
    if plan_for(method).implementation_status != "IMPLEMENTED":
        return None
    return PRODUCTION_KIND[production_payload_class(method)]


def _default_parameters(method: MiningMethodType) -> dict[str, Any] | None:
    """The method's canonical default ``methodParameters`` (the same values
    ``MiningConfig(method=…)`` resolves), ``None`` for methods without one."""
    cls = METHOD_PARAMETER_CLASSES.get(method)
    if cls is None:
        return None
    return cls().model_dump(mode="json", by_alias=True)


#: the production semantics kind of each typed payload class (mirrors the
#: MineExchange omission groups)
PRODUCTION_KIND: dict[type, str] = {
    StopesPayload: "STOPES",
    CutFillPayload: "CUT_FILL",
    RoomPillarPayload: "ROOM_PILLAR",
}


def build_scene(scenario: Scenario, world: SyntheticWorld) -> dict[str, Any]:
    t = world.terrain
    verts, faces = world.orebody.mesh()
    grid = world.fields.grid
    box_min = np.asarray(grid.origin)
    box_max = np.asarray(grid.max_corner)

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
    zc = grid.axis_centers(2)
    k = int(np.clip(np.argmin(np.abs(zc - world.orebody.center[2])), 0, len(zc) - 1))
    rq_stats = world.fields.rock_quality.stats(world.fields.supported)

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
            # backend-authored DERIVED render mesh (rule 138): the client
            # assembles it as-is and never infers membership from it
            "meshVertices": int(verts.shape[0]),
            "meshTriangles": int(faces.shape[0]),
            "positions": verts.ravel().tolist(),
            "indices": faces.ravel().tolist(),
        },
        "faults": faults,
        # Phase 21A: read-only mining-method presentation (registry authority)
        "miningMethod": mining_method_summary(scenario),
        # numerical lattice description ONLY (rule 127): origin / spacing /
        # shape so the client can address slices — never blocks
        "fieldGrid": grid.to_dict(),
        "rockQuality": {
            "min": rq_stats["min"],
            "max": rq_stats["max"],
            "defaultSlice": slice_payload(world, "rockQuality", "z", k),
        },
        "stats": world.stats(scenario),
    }
