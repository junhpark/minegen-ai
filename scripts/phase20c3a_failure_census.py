"""Phase 20C.3A failure locality census (diagnostic script, NOT production).

Re-runs the production layout-v2 search on the 13 NO_FEASIBLE seeds of the
Phase 20C.2A 32-seed WARPED survey and, for every DETAILED candidate,
localizes the hard failure on the delivered polyline using the in-memory
per-sample validity of the shared validator (nothing is persisted by
production; the candidate-specific stage-4 evaluator is rebuilt through
LayoutV2Search.candidate_policy). Nothing is tuned; no threshold is changed.

This is the exact script that produced ``backend/golden/phase20c3a_failure_census.json``
(the raw per-candidate output was post-processed into that artifact's
provenance / population layout by the closeout; the cluster and
classification logic is this file). The 2R / 4R shoulder / span rule it
applies is an EXPLORATORY locality classifier, not a production contract.

Usage (from the repository root, backend venv):
    backend/.venv/bin/python scripts/phase20c3a_failure_census.py \
        302,303,306,307,308,309,312,316,319,320,321,324,328 /tmp/census.json
"""

import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend" / "src"))
sys.path.insert(0, str(_ROOT / "backend"))
import numpy as np  # noqa: E402

from minegen.core.enums import ScenarioPreset  # noqa: E402
from minegen.core.models import Scenario  # noqa: E402
from minegen.layout.search import LayoutV2Search, chainage_of  # noqa: E402
from minegen.layout.validation import validate_delivered_centerline  # noqa: E402
from minegen.services.scenario_realizer import realize_scenario  # noqa: E402
from minegen.world.synthetic_world import generate_world  # noqa: E402

SEEDS = (
    [int(s) for s in sys.argv[1].split(",")]
    if len(sys.argv) > 1
    else [302, 303, 306, 307, 308, 309, 312, 316, 319, 320, 321, 324, 328]
)
OUT = sys.argv[2] if len(sys.argv) > 2 else "phase20c3a_failure_census_raw.json"
RAMP_REASONS = {
    "ABOVE_TERRAIN",
    "WORLD_BOUNDS",
    "SURFACE_COVER",
    "OREBODY_CLEARANCE",
    "RESTRICTED_ZONE",
    "GEOMETRY_ASSEMBLY",
}


def runs(idx):
    """contiguous index runs"""
    out = []
    if len(idx) == 0:
        return out
    s = p = idx[0]
    for i in idx[1:]:
        if i == p + 1:
            p = i
        else:
            out.append((s, p))
            s = p = i
    out.append((s, p))
    return out


def merge_runs(rs, ch, gap):
    if not rs:
        return []
    m = [list(rs[0])]
    for s, e in rs[1:]:
        if ch[s] - ch[m[-1][1]] <= gap:
            m[-1][1] = e
        else:
            m.append([s, e])
    return [tuple(x) for x in m]


rows = []
seed_rows = []
for seed in SEEDS:
    t0 = time.perf_counter()
    create = realize_scenario(ScenarioPreset.RANDOM_WARPED_VEIN, seed, 1)
    sc = Scenario(**create.model_dump())
    world = generate_world(sc)
    search = LayoutV2Search(sc, world)
    res = search.run()
    R = sc.ramp.min_turn_radius
    spacing = sc.layout.sample_spacing
    req = res.required_clearance
    shoulder = 2.0 * R
    max_span = 4.0 * R
    detailed = [c for c in res.candidates if c.stage_reached == "DETAILED"]
    srow = {
        "seed": seed,
        "status": "SUCCESS" if res.winner_id else "NO_FEASIBLE",
        "R_min": R,
        "sampleSpacing": spacing,
        "requiredClearance": req,
        "detailed": len(detailed),
        "feasible": sum(1 for c in detailed if c.status == "FEASIBLE"),
        "levels": len(res.levels),
        "serviceable": len(res.serviceable_ids),
    }
    for c in detailed:
        rec = {
            "seed": seed,
            "candidateId": c.candidate_id,
            "family": c.params.family.value,
            "status": c.status,
            "failureReasons": list(c.failure_reasons),
            "failureDetail": (c.failure_detail or "")[:400],
        }
        pts = c.points
        ch = chainage_of(pts)
        L = float(ch[-1])
        rec["length"] = round(L, 1)
        rec["screenBlocked"] = c.screen_blocked
        rec["screenAuthority"] = c.screen_authority
        rec["withinReachLevels"] = c.screened_count
        rec["accessibleLevels"] = c.accessible_count
        rec["crossingChainages"] = [
            round(float(x.chainage), 1) for x in c.crossings if x is not None
        ]
        if c.status == "FEASIBLE":
            rec["class"] = "FEASIBLE"
            rows.append(rec)
            continue
        ramp_fail = [r for r in c.failure_reasons if r in RAMP_REASONS]
        if not ramp_fail:
            rec["class"] = "LEVEL_ACCESS_PROBLEM"
            if c.access_plan is not None:
                rec["levelAccessFailures"] = {
                    a.level_id: (a.failure_reason or "") for a in c.access_plan.accesses if not a.ok
                }
            rows.append(rec)
            continue
        # ramp-geometry failure: localize on the delivered polyline
        evaluator, policy, refinement = search.candidate_policy(res, c.candidate_id)
        rep = validate_delivered_centerline(evaluator, pts)
        ev = evaluator.evaluate_points(pts)
        surface = evaluator.surface_elevation(pts)
        invalid = ~rep.valid_mask
        clear_bad = rep.orebody_distance < req - 1e-9
        bad = invalid | clear_bad
        idx = np.flatnonzero(bad)
        raw = runs(list(idx))
        merged = merge_runs(raw, ch, shoulder)
        clusters = []
        for s, e in merged:
            reasons = {}
            for i in range(s, e + 1):
                if invalid[i]:
                    for r in ev.rejection_reasons[i]:
                        reasons[r.value] = reasons.get(r.value, 0) + 1
                if clear_bad[i]:
                    reasons["CLEARANCE_BELOW_REQUIRED"] = (
                        reasons.get("CLEARANCE_BELOW_REQUIRED", 0) + 1
                    )
            seg = slice(s, e + 1)
            clusters.append(
                {
                    "startChainage": round(float(ch[s]), 1),
                    "endChainage": round(float(ch[e]), 1),
                    "span": round(float(ch[e] - ch[s]), 1),
                    "spanRatio": round(float((ch[e] - ch[s]) / L), 4),
                    "startFrac": round(float(ch[s] / L), 3),
                    "samples": int(e - s + 1),
                    "reasons": reasons,
                    "maxAboveTerrain": round(float(np.max(pts[seg, 2] - surface[seg])), 2),
                    "clearanceDeficit": round(
                        float(max(0.0, req - np.min(rep.orebody_distance[seg]))), 2
                    ),
                    "touchesStart": bool(ch[s] < shoulder),
                    "touchesEnd": bool(L - ch[e] < shoulder),
                    "minDistToCrossing": round(
                        float(
                            min(
                                (abs(x - ch[i]) for x in rec["crossingChainages"] for i in (s, e)),
                                default=float("nan"),
                            )
                        ),
                        1,
                    ),
                }
            )
        rec.update(
            {
                "invalidSamples": int(invalid.sum()),
                "clearanceBadSamples": int(clear_bad.sum()),
                "sampleCount": len(pts),
                "rawClusters": len(raw),
                "clusters": clusters,
                "basis": policy.basis,
                "minClearance": round(float(np.min(rep.orebody_distance)), 2),
            }
        )
        # classification under the proposed geometry-derived rule
        if len(merged) == 0:
            cls = "INSUFFICIENT_DIAGNOSTICS"
        elif len(merged) >= 2:
            cls = "OTHER_NON_REPAIRABLE:MULTI_CLUSTER"
        else:
            cl = clusters[0]
            if cl["touchesStart"] and "ABOVE_TERRAIN" in cl["reasons"]:
                cls = "FAMILY_CONSTRUCTION_PROBLEM:PORTAL_APPROACH"
            elif cl["touchesStart"] or cl["touchesEnd"]:
                cls = "GLOBAL_GEOMETRY_PROBLEM:ENDPOINT"
            elif cl["span"] > max_span:
                cls = "GLOBAL_GEOMETRY_PROBLEM:SPAN"
            else:
                cls = "LOCAL_REPAIR_CANDIDATE"
        rec["class"] = cls
        # sensitivity: span thresholds 2R/4R/8R for the single-cluster case
        if len(merged) == 1 and not (clusters[0]["touchesStart"] or clusters[0]["touchesEnd"]):
            rec["localUnder"] = {f"{k}R": bool(clusters[0]["span"] <= k * R) for k in (2, 4, 8)}
        rows.append(rec)
        print(seed, c.candidate_id, cls, json.dumps(clusters)[:300], flush=True)
    srow["seconds"] = round(time.perf_counter() - t0, 1)
    seed_rows.append(srow)
    print("SEED", json.dumps(srow), flush=True)
    with open(OUT, "w") as fh:
        json.dump({"seeds": seed_rows, "candidates": rows}, fh, indent=1)
print("DONE")
