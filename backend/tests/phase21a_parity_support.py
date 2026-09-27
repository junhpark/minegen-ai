"""Phase 21A Longhole parity support (directive §14 / §39 / §40).

Builds the boundary cases the mining-method migration must leave unchanged
and reduces every payload to (a) its canonical JSON digest and (b) a
readable structural summary. ``capture`` wrote the committed fixture on the
PRE-migration code; ``tests/test_mining_method_parity.py`` rebuilds the same
cases on the current code and compares in TWO tiers (PR #46 review):

  HARD parity     status, method, ids, counts, station indices, ordering,
                  topology, every string / int / bool / null — EXACT.
  NUMERIC parity  lengths, coordinates, volumes, tonnes, grade — every
                  float within ``PARITY_REL_TOL`` / ``PARITY_ABS_TOL``.
  ADVISORY        the full canonical-JSON digests: recorded, never a gate
                  (the same code prints 1085.4613279254309 on one CI CPU and
                  1085.4613279254306 on another — a 3e-13 last-digit
                  difference that byte identity across runners cannot
                  distinguish from a real change).

The tolerance is orders of magnitude below every engineering resolution the
pipeline uses (1e-6 m welds, 0.05 m radius tolerance) and orders above the
observed cross-runner floating-point noise, so a genuine Longhole change
(a moved station, a different lattice, a re-derived coordinate) still fails
the gate. The fixture itself is never regenerated for such noise.

Cases
  TABULAR_LEGACY   small scenario, synthetic legacy ramp segments (the
                   ``test_stopes`` chain): levels + stopes
  TABULAR_LAYOUT   small scenario, layout-v2 winner → level accesses →
                   levels (LEVEL_ACCESS entries) + stopes
  CUT_AND_FILL     same layout-v2 chain with the reserved method: generic
                   backbone levels (UNSUPPORTED_METHOD) + typed FAILED stopes
  WARPED_LONGHOLE  WARPED_VEIN-301 layout-v2 winner → curved levels
                   (stations / excluded stations / crosscuts) — stopes stay
                   the typed Phase 09 boundary
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from minegen.core.enums import MiningMethodType
from minegen.core.models import Scenario
from minegen.design.constraints import DesignContext
from minegen.design.cost_field import DesignCostEvaluator
from minegen.layout.materialize import materialize_effective_ramp, materialize_level_accesses
from minegen.layout.search import LayoutV2Search
from minegen.levels.builder import LevelDevelopmentBuilder, entries_from_level_accesses
from minegen.world.synthetic_world import SyntheticWorld

REV = "phase21a-parity"
#: NUMERIC parity tolerance (relative AND absolute, `math.isclose`) —
#: cross-runner floating-point noise measured at ≈ 3e-13 absolute on
#: ≈ 1e3 m lengths; engineering resolutions start at 1e-6 m.
PARITY_REL_TOL = 1e-10
PARITY_ABS_TOL = 1e-10


def parity_differences(
    expected: Any,
    actual: Any,
    path: str = "$",
    *,
    rel_tol: float = PARITY_REL_TOL,
    abs_tol: float = PARITY_ABS_TOL,
) -> list[str]:
    """Recursive two-tier comparison. Returns one readable line per
    difference (JSON path, expected, actual); an empty list means parity.

    Structure (dict keys, list lengths), strings, booleans, ``None`` and
    integers are compared EXACTLY; floats within the tolerance. A float is
    compared numerically against an int only when the baseline holds a float
    (an int baseline — a count, an index — is a HARD field)."""
    out: list[str] = []
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: expected object, got {type(actual).__name__}"]
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        if missing:
            out.append(f"{path}: missing keys {missing}")
        if extra:
            out.append(f"{path}: unexpected keys {extra}")
        for key in sorted(set(expected) & set(actual)):
            out.extend(
                parity_differences(
                    expected[key], actual[key], f"{path}.{key}", rel_tol=rel_tol, abs_tol=abs_tol
                )
            )
        return out
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return [f"{path}: expected array, got {type(actual).__name__}"]
        if len(expected) != len(actual):
            return [f"{path}: length {len(expected)} != {len(actual)}"]
        for i, (e, a) in enumerate(zip(expected, actual, strict=True)):
            out.extend(parity_differences(e, a, f"{path}[{i}]", rel_tol=rel_tol, abs_tol=abs_tol))
        return out
    if isinstance(expected, bool) or expected is None or isinstance(expected, str | int):
        # HARD tier: exact (bool before int — True is an int in Python)
        if type(expected) is not type(actual) or expected != actual:
            out.append(f"{path}: {expected!r} != {actual!r}")
        return out
    if isinstance(expected, float):
        if isinstance(actual, bool) or not isinstance(actual, int | float):
            return [f"{path}: expected number, got {actual!r}"]
        if not math.isclose(expected, float(actual), rel_tol=rel_tol, abs_tol=abs_tol):
            out.append(f"{path}: {expected!r} != {actual!r} (|Δ| = {abs(expected - actual):.3e})")
        return out
    return [f"{path}: unsupported baseline type {type(expected).__name__}"]


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(payload: Any) -> str:
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def levels_summary(doc: dict[str, Any]) -> dict[str, Any]:
    devs = doc["developments"]
    return {
        "status": doc["status"],
        "failureReason": doc.get("failureReason"),
        "entrySource": doc.get("entrySource"),
        "developmentGeometry": doc.get("developmentGeometry"),
        "productionDevelopment": doc.get("productionDevelopment"),
        "metrics": doc.get("metrics"),
        "developmentIds": [d["id"] for d in devs],
        "stations": [
            {
                "id": d["id"],
                "levelId": d["levelId"],
                "stationIndex": d.get("stationIndex"),
                "stationU": d.get("stationU"),
                "fromU": d.get("fromU"),
                "toU": d.get("toU"),
                "length3d": d["length3d"],
                "pointCount": len(d["centerline"]["points"]) // 3,
                "valid": d["report"]["valid"],
            }
            for d in devs
        ],
        "levels": [
            {
                "levelId": lv["levelId"],
                "driftPieceCount": lv["driftPieceCount"],
                "crosscutCount": lv["crosscutCount"],
                "valid": lv["valid"],
                "excludedStations": lv.get("excludedStations"),
            }
            for lv in doc["levels"]
        ],
    }


def stopes_summary(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": doc["status"],
        "failureReason": doc.get("failureReason"),
        "method": doc["method"],
        "metrics": doc.get("metrics"),
        "stopes": [
            {
                "id": s["id"],
                "stationIndex": s["stationIndex"],
                "stationU": s["stationU"],
                "upperLevelId": s["upperLevelId"],
                "lowerLevelId": s["lowerLevelId"],
                "upperAccessNodeId": s["upperAccessNodeId"],
                "lowerAccessNodeId": s["lowerAccessNodeId"],
                "localBounds": s["localBounds"],
                "vertices": s["geometry"]["vertices"],
                "triangleIndices": s["geometry"]["triangleIndices"],
                "tonnes": s["tonnes"],
                "meanGradeProxy": s["meanGradeProxy"],
                "strikePillarClearance": s["report"]["strikePillarClearance"],
                "valid": s["report"]["valid"],
            }
            for s in doc["stopes"]
        ],
    }


def _stopes(sc: Scenario, world: SyntheticWorld, levels_doc: dict[str, Any]) -> dict[str, Any]:
    """The service's stope path: the registry-resolved plan (the committed
    fixture was captured through the pre-migration strategy factory).
    An implicit orebody stops at the typed Phase 09 boundary BEFORE any
    plan runs (the exact-only evaluator refuses it, rule 135); that boundary
    is recorded as a typed marker, never as a payload."""
    from minegen.design.cost_field import ExactDistanceRequiredError

    try:
        hard_ev = DesignCostEvaluator(world, sc.design, DesignContext.crosscut(sc.design))
    except ExactDistanceRequiredError as err:
        return {"typedBoundary": type(err).__name__, "detail": str(err)}
    from minegen.mining.methods.registry import plan_for

    payload = plan_for(sc.mining.method).generate_production(sc, world, levels_doc, hard_ev, REV)
    return payload.model_dump(mode="json", by_alias=True)


def _builder(sc: Scenario, world: SyntheticWorld, policy: Any = None) -> LevelDevelopmentBuilder:
    kw = {"clearance": policy} if policy is not None else {}
    drift = DesignCostEvaluator(world, sc.design, **kw)
    cross = DesignCostEvaluator(world, sc.design, DesignContext.crosscut(sc.design), **kw)
    return LevelDevelopmentBuilder(sc, world.orebody, drift, cross)


def layout_chain(sc: Scenario, world: SyntheticWorld) -> dict[str, Any]:
    search = LayoutV2Search(sc, world)
    res = search.run()
    assert res.winner_id is not None, "layout search has no winner"
    winner = res.candidate(res.winner_id)
    assert winner is not None
    ramp = materialize_effective_ramp(res, winner, search.evaluator, REV)
    accesses = materialize_level_accesses(res, winner, REV, sc.mining.method.value)
    _, policy, _ = search.candidate_policy(res, res.winner_id)
    levels = (
        _builder(sc, world, policy)
        .build(ramp, REV, entries=entries_from_level_accesses(accesses))
        .model_dump(mode="json", by_alias=True)
    )
    out: dict[str, Any] = {"winnerId": res.winner_id, "levels": levels}
    out["stopes"] = _stopes(sc, world, levels)
    return out


def legacy_chain(
    sc: Scenario, world: SyntheticWorld, level_zs: tuple[float, ...]
) -> dict[str, Any]:
    from tests.test_levels import _entry_segment, _smoothed

    segs = []
    for i, z in enumerate(level_zs, start=1):
        seg = json.loads(json.dumps(_entry_segment(world, sc, u_entry=0.0, level_z=z)))
        seg["levelId"] = f"L{i:02d}"
        seg["candidateId"] = f"L{i:02d}-C01"
        segs.append(seg)
    levels = _builder(sc, world).build(_smoothed(*segs), REV).model_dump(mode="json", by_alias=True)
    return {"levels": levels, "stopes": _stopes(sc, world, levels)}


def with_method(sc: Scenario, method: MiningMethodType) -> Scenario:
    return sc.model_copy(update={"mining": sc.mining.model_copy(update={"method": method})})


def reduce(case: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "winnerId" in case:
        out["winnerId"] = case["winnerId"]
    out["levelsDigest"] = digest(case["levels"])
    out["levels"] = levels_summary(case["levels"])
    if "stopes" in case:
        out["stopesDigest"] = digest(case["stopes"])
        out["stopes"] = (
            case["stopes"] if "typedBoundary" in case["stopes"] else stopes_summary(case["stopes"])
        )
    return out
