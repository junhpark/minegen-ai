"""Phase 21B/C Longhole baseline support (directive §39).

Extends the Phase 21A parity cases with the artifacts Phase 21B/C touches
downstream of production — MineNetwork and the MineTimeline — so the
Longhole path can be proven unchanged through the multi-method migration:

  LEGACY_DEFAULT   default scenario, synthetic Phase 05 segments → levels + stopes
  LEGACY_WELDED    small scenario, welded portal→L01→L02→L03 legacy ramp →
                   levels + stopes + network + timeline
  LAYOUT_SMALL     small scenario, layout-v2 winner → level accesses → levels +
                   stopes + network + timeline
  WARPED_LONGHOLE  WARPED-301 layout-v2 winner → curved levels; the stope
                   path stops at the typed Phase 09 boundary

The same two-tier comparator as Phase 21A (``phase21a_parity_support
.parity_differences``: HARD structure / ids / counts / strings exact, NUMERIC
floats within 1e-10, canonical digests advisory) judges every case. The
fixture is captured ONCE on the pinned pre-migration HEAD and never
regenerated for this Phase.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np

from minegen.core.artifacts import LAYOUT_V2_SELECTED_ARTIFACT
from minegen.core.models import Scenario
from minegen.layout.materialize import materialize_effective_ramp, materialize_level_accesses
from minegen.layout.search import LayoutV2Search
from minegen.levels.builder import entries_from_level_accesses
from minegen.network.builder import MineNetworkBuilder
from minegen.scheduling.builder import MineTimelineBuilder
from minegen.world.synthetic_world import SyntheticWorld
from tests.phase21a_parity_support import (
    REV,
    _builder,
    _stopes,
    digest,
    levels_summary,
    stopes_summary,
)


def network_summary(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": doc["status"],
        "failureReason": doc.get("failureReason"),
        "nodes": [
            {
                "id": n["id"],
                "type": n["type"],
                "levelId": n.get("levelId"),
                "stationIndex": n.get("stationIndex"),
                "position": n["position"],
            }
            for n in doc["nodes"]
        ],
        "edges": [
            {
                "id": e["id"],
                "type": e["type"],
                "fromNode": e["fromNode"],
                "toNode": e["toNode"],
                "length3d": e["length3d"],
                "geometryRef": e["geometryRef"],
            }
            for e in doc["edges"]
        ],
        "metrics": doc.get("metrics"),
    }


def timeline_summary(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": doc["status"],
        "failureReason": doc.get("failureReason"),
        "startDay": doc.get("startDay"),
        "endDay": doc.get("endDay"),
        "tasks": [
            {
                "id": t["id"],
                "taskType": t["taskType"],
                "targetKind": t["targetKind"],
                "targetId": t["targetId"],
                "durationDays": t["durationDays"],
                "startDay": t["startDay"],
                "endDay": t["endDay"],
                "dependencies": t["dependencies"],
                "basis": t["basis"],
            }
            for t in doc.get("tasks", [])
        ],
        "developments": [
            {
                "edgeId": d["edgeId"],
                "edgeType": d["edgeType"],
                "taskId": d["taskId"],
                "transitions": d["transitions"],
                "excavationStartNode": d.get("excavationStartNode"),
                "progressDirection": d.get("progressDirection"),
                "fractionCount": len(d["pointChainageFractions"]),
                "fractionEnds": [d["pointChainageFractions"][0], d["pointChainageFractions"][-1]],
            }
            for d in doc.get("developments", [])
        ],
        "stopes": doc.get("stopes", []),
        "metrics": doc.get("metrics"),
    }


def legacy_welded_chain(
    sc: Scenario, world: SyntheticWorld, entry_us_zs: list[tuple[float, float]]
) -> dict[str, Any]:
    """The ``tests.test_timeline._chain`` construction: welded synthetic
    legacy ramp segments so the rule-68 weld gate holds and the network +
    timeline can be built."""
    from tests.test_levels import _entry_segment, _smoothed

    entries = []
    metas = []
    for i, (u_entry, z) in enumerate(entry_us_zs, start=1):
        seg = json.loads(json.dumps(_entry_segment(world, sc, u_entry=u_entry, level_z=z)))
        entries.append(np.asarray(seg["effectiveCenterline"]["points"]).reshape(-1, 3)[-1])
        metas.append((f"L{i:02d}", seg))
    segs = []
    prev = entries[0] + np.array([0.0, -60.0, 6.0])
    for (level_id, seg), entry in zip(metas, entries, strict=True):
        pts = np.linspace(prev, entry, 31)
        seg["levelId"] = level_id
        seg["candidateId"] = f"{level_id}-C01"
        seg["effectiveCenterline"] = {"points": pts.ravel().tolist()}
        segs.append(seg)
        prev = entry
    smoothed = _smoothed(*segs)
    levels = _builder(sc, world).build(smoothed, REV).model_dump(mode="json", by_alias=True)
    network = MineNetworkBuilder(sc).build(smoothed, REV, levels_payload=levels)
    network_d = network.payload.model_dump(mode="json", by_alias=True)
    stopes = _stopes(sc, world, levels)
    timeline = (
        MineTimelineBuilder(sc)
        .build(network_d, stopes, smoothed, levels, REV)
        .model_dump(mode="json", by_alias=True)
    )
    return {"levels": levels, "stopes": stopes, "network": network_d, "timeline": timeline}


def layout_full_chain(sc: Scenario, world: SyntheticWorld) -> dict[str, Any]:
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
    if "typedBoundary" in out["stopes"]:
        return out
    network = MineNetworkBuilder(sc).build(
        ramp,
        REV,
        levels_payload=levels,
        geometry_artifact=LAYOUT_V2_SELECTED_ARTIFACT,
        accesses_payload=accesses,
    )
    out["network"] = network.payload.model_dump(mode="json", by_alias=True)
    out["timeline"] = (
        MineTimelineBuilder(sc)
        .build(out["network"], out["stopes"], ramp, levels, REV, accesses_payload=accesses)
        .model_dump(mode="json", by_alias=True)
    )
    return out


def reduce_full(case: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "winnerId" in case:
        out["winnerId"] = case["winnerId"]
    out["levelsDigest"] = digest(case["levels"])
    out["levels"] = levels_summary(case["levels"])
    out["stopesDigest"] = digest(case["stopes"])
    out["stopes"] = (
        case["stopes"] if "typedBoundary" in case["stopes"] else stopes_summary(case["stopes"])
    )
    if "network" in case:
        out["networkDigest"] = digest(case["network"])
        out["network"] = network_summary(case["network"])
    if "timeline" in case:
        out["timelineDigest"] = digest(case["timeline"])
        out["timeline"] = timeline_summary(case["timeline"])
    return out
