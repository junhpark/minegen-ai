# ruff: noqa: E402, E501, SIM115, N806, RUF059, F841  # diagnostic script (not production): sys.path bootstrap precedes imports
"""Phase 20C.4 Gate A — per-junction instrument (diagnostic only).

For every audited level the production lattice (_junction_candidates) is
replayed one junction at a time through the production gate sequence
(_search_level with used=[] so junction spacing is isolated), recording the
junction's chainage offset from the RL crossing, dz, plan separation to the
anchor, required horizontal run at g_max and the rejection it received. The
level's BINDING cause is then read from the grade-feasible junctions only —
never from the plurality label. Counterfactuals use the NEAREST ramp
approach inside the junction window: CF-ANCHOR (anchor moved away from the
ramp to the rule-171 plan separation) and CF-RAMP (rigid plan shift of the
ramp by the same deficit), both re-planned by the authoritative planner.
"""

import collections
import dataclasses
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend" / "src"))
sys.path.insert(0, str(_ROOT / "backend"))
import numpy as np

from minegen.core.enums import ScenarioPreset
from minegen.core.models import Scenario
from minegen.layout import access as acc
from minegen.layout.access import (
    LevelDevelopmentAnchor,
    plan_level_accesses,
    turnout_heading_change_deg,
)
from minegen.layout.search import LayoutV2Search, chainage_of
from minegen.services.scenario_realizer import realize_scenario
from minegen.world.synthetic_world import generate_world

CENSUS = json.load(open(_ROOT / "backend/golden/phase20c3a_failure_census.json"))
CLS = {(c["seed"], c["candidateId"]): c["classification"] for c in CENSUS["perCandidate"]}
OUT = sys.argv[2]
JOBS = [j.split(":") for j in sys.argv[1].split(",")]
SEP_REASONS = {
    "INSUFFICIENT_RAMP_TO_ENTRY_SEPARATION",
    "INSUFFICIENT_RAMP_PILLAR",
    "CONNECTOR_UNAVAILABLE",
}


def true_clear(orebody, pts):
    pts = np.asarray(pts, dtype=np.float64).reshape(-1, 3)
    return np.asarray(
        orebody.approximate_clearance(pts)
        if hasattr(orebody, "approximate_clearance")
        else orebody.signed_distance(pts),
        dtype=np.float64,
    )


def audit(seed, cand, res, search, world, sc, role):
    evaluator, policy, refinement = search.candidate_policy(res, cand.candidate_id)
    req = res.required_clearance
    cfg = sc.layout.access
    g = sc.ramp.max_gradient
    width = sc.ramp.tunnel_width
    ctx = acc._plan_context(
        cand.points, cfg, sc.ramp, evaluator, search.shape, req, acc.LONG_ACCESS_COEF
    )
    pts = cand.points
    ch = chainage_of(pts)
    levels = res.serviceable_levels
    accesses = {a.level_id: a for a in (cand.access_plan.accesses if cand.access_plan else [])}
    rec = {
        "seed": seed,
        "candidateId": cand.candidate_id,
        "family": cand.params.family.value,
        "role": role,
        "status": cand.status,
        "census": CLS.get((seed, cand.candidate_id)),
        "basis": policy.basis,
        "errorBound": float(getattr(policy, "error_bound", 0.0) or 0.0),
        "planSepMin": ctx.plan_sep_min,
        "excSepMin": ctx.exc_sep_min,
        "corridorStandoff": res.standoff,
        "anchorStandoffUsed": search.anchor_standoff(req, policy),
        "levels": [],
    }
    nearest_vecs = []
    for i, lv in enumerate(levels):
        anc = cand.anchors[i] if i < len(cand.anchors) else None
        L = {"levelId": lv.level_id, "z": lv.elevation}
        if not isinstance(anc, LevelDevelopmentAnchor):
            L["anchor"] = "FAILURE/NONE"
            rec["levels"].append(L)
            continue
        a = accesses.get(lv.level_id)
        q = np.asarray(anc.position)
        xing = cand.crossings[i] if i < len(cand.crossings) else None
        L["accessOk"] = bool(a.ok) if a else None
        L["reportedReason"] = a.failure_reason if a else None
        L["reportedRejections"] = dict(a.rejection_counts) if a else None
        cands = acc._junction_candidates(pts, lv.elevation, cfg, q[:2], ctx.ramp_ch, ctx.ramp_az)
        rows = []
        for c in cands:
            best, tried, valid, rej = acc._search_level(ctx, lv, anc, [c], [])
            sep = float(np.hypot(*(c.position[:2] - q[:2])))
            dz = float(c.position[2] - q[2])
            reason = (
                "OK"
                if best is not None
                else (max(rej.items(), key=lambda kv: (kv[1], kv[0]))[0] if rej else "NONE")
            )
            rows.append(
                {
                    "chainage": round(c.chainage, 1),
                    "offsetFromCrossing": round(float(c.chainage - xing.chainage), 1)
                    if xing
                    else None,
                    "dz": round(dz, 2),
                    "planSep": round(sep, 2),
                    "requiredRun": round(abs(dz) / g, 2),
                    "gradeFeasibleByPlanSep": bool(sep >= abs(dz) / g),
                    "reason": reason,
                    "connectorHorizontal": (
                        round(float(best[1].horizontal_length), 1) if best is not None else None
                    ),
                }
            )
        gf = [r for r in rows if r["gradeFeasibleByPlanSep"]]
        gf_reasons = collections.Counter(r["reason"] for r in gf)
        if any(r["reason"] == "OK" for r in gf) or any(r["reason"] == "OK" for r in rows):
            binding = "OK_IGNORING_SPACING" if not (a and a.ok) else "OK"
        elif gf and all(r["reason"] in SEP_REASONS for r in gf):
            binding = "SEPARATION_BOUND"
        elif not gf:
            binding = "NO_GRADE_FEASIBLE_JUNCTION"
        else:
            binding = "MIXED:" + ",".join(sorted(gf_reasons))
        # nearest approach in window
        zsel = (pts[:, 2] <= lv.elevation + cfg.junction_window_above) & (
            pts[:, 2] >= lv.elevation - cfg.junction_window_below
        )
        near = None
        if zsel.any():
            d = np.hypot(pts[zsel, 0] - q[0], pts[zsel, 1] - q[1])
            k = int(np.argmin(d))
            pn = pts[zsel][k]
            near = {
                "planDist": round(float(d[k]), 2),
                "dz": round(float(pn[2] - q[2]), 2),
                "requiredRun": round(float(abs(pn[2] - q[2]) / g), 2),
            }
            if d[k] < ctx.plan_sep_min:
                nearest_vecs.append((i, (pn[:2] - q[:2]) / d[k] * (ctx.plan_sep_min - d[k])))
        L.update(
            {
                "junctionCount": len(rows),
                "gradeFeasibleCount": len(gf),
                "gradeFeasibleReasons": dict(gf_reasons),
                "allReasons": dict(collections.Counter(r["reason"] for r in rows)),
                "bindingCause": binding,
                "nearestApproach": near,
                "anchorTrueClearance": round(float(true_clear(world.orebody, q[None, :])[0]), 2),
                "anchorCertifiedClearance": round(float(policy.signed_clearance(q[None, :])[0]), 2),
                "turnoutDegAtCrossing": round(
                    float(
                        turnout_heading_change_deg(
                            pts, ch, float(xing.chainage), cfg.minimum_turnout_straight_buffer
                        )
                    ),
                    1,
                )
                if xing
                else None,
                "sharedReferencePrediction": (
                    {
                        "separationShared": ctx.plan_sep_min,
                        "requiredRunAtNearest": near["requiredRun"],
                        "availableRunShared": ctx.plan_sep_min,
                        "predicted": "PREDICTED_OK"
                        if near["requiredRun"] <= ctx.plan_sep_min
                        else "GRADE_LIMIT_PERSISTS",
                    }
                    if near
                    else None
                ),
                "junctions": rows,
            }
        )
        if a and a.ok:
            L["selected"] = {
                "junctionChainage": a.junction_chainage,
                "offsetFromCrossing": round(float(a.junction_chainage - xing.chainage), 1)
                if (xing and a.junction_chainage is not None)
                else None,
                "horizontalLength": a.horizontal_length,
                "planSep": a.junction_to_entry_plan_sep,
                "maxGradient": a.max_gradient,
                "connector": a.connector_word,
            }
        rec["levels"].append(L)

    def run_plan(ramp_pts, anchors):
        plan = plan_level_accesses(
            ramp_pts, anchors, levels, cfg, sc.ramp, evaluator, search.shape, req
        )
        return {
            "feasible": plan.feasible,
            "perLevel": {x.level_id: (x.failure_reason or "OK") for x in plan.accesses},
            "okCount": sum(1 for x in plan.accesses if x.ok),
            "failedCount": sum(1 for x in plan.accesses if not x.ok),
        }

    base = run_plan(pts, cand.anchors)
    cf_anchors = list(cand.anchors)
    moved = []
    for i, v in nearest_vecs:
        anc = cand.anchors[i]
        nq = np.asarray(anc.position).copy()
        nq[:2] = nq[:2] - v
        cf_anchors[i] = dataclasses.replace(anc, position=nq)
        moved.append(round(float(np.linalg.norm(v)), 2))
    cf_anchor = run_plan(pts, cf_anchors)
    cf_anchor["anchorsMoved"] = len(moved)
    cf_anchor["moveDistances"] = moved
    cf_anchor["movedAnchorCertifiedClearance"] = [
        round(float(policy.signed_clearance(np.asarray(cf_anchors[i].position)[None, :])[0]), 2)
        for i, _ in nearest_vecs
    ]
    cf_anchor["movedAnchorTrueClearance"] = [
        round(float(true_clear(world.orebody, np.asarray(cf_anchors[i].position)[None, :])[0]), 2)
        for i, _ in nearest_vecs
    ]
    if nearest_vecs:
        shift = np.median(np.array([v for _, v in nearest_vecs]), axis=0)
        shifted = pts.copy()
        shifted[:, :2] += shift[None, :]
        cf_ramp = run_plan(shifted, cand.anchors)
        cert = policy.signed_clearance(shifted)
        cf_ramp.update(
            {
                "shift": [round(float(shift[0]), 2), round(float(shift[1]), 2)],
                "shiftNorm": round(float(np.linalg.norm(shift)), 2),
                "shiftedRampMinCertifiedClearance": round(float(np.min(cert)), 2),
                "shiftedRampClearanceOk": bool(np.min(cert) >= req - 1e-9),
                "note": "rigid plan shift; terrain / world / family coupling of the shifted ramp NOT re-validated",
            }
        )
    else:
        cf_ramp = {"skipped": "no level with nearest approach below planSepMin"}
    rec["counterfactual"] = {
        "baseline": base,
        "cfAnchorAtSharedSeparation": cf_anchor,
        "cfRampAtSharedSeparation": cf_ramp,
    }
    return rec


results = {"candidates": [], "seeds": []}
for preset, seed, role in JOBS:
    seed = int(seed)
    t0 = time.perf_counter()
    create = realize_scenario(ScenarioPreset[preset], seed, 1)
    sc = Scenario(**create.model_dump())
    world = generate_world(sc)
    search = LayoutV2Search(sc, world)
    res = search.run()
    detailed = [c for c in res.candidates if c.stage_reached == "DETAILED"]
    if role == "CONTROL":
        feas = [c for c in detailed if c.status == "FEASIBLE"]
        picks = ([res.candidate(res.winner_id)] if res.winner_id else []) + [
            c for c in feas if c.candidate_id != res.winner_id
        ][:2]
    else:
        picks = [c for c in detailed if CLS.get((seed, c.candidate_id)) == "LEVEL_ACCESS_PROBLEM"][
            :6
        ]
    for c in picks:
        try:
            results["candidates"].append(audit(seed, c, res, search, world, sc, role))
        except Exception as exc:
            results["candidates"].append(
                {"seed": seed, "candidateId": c.candidate_id, "error": repr(exc)}
            )
        print(seed, c.candidate_id, "done", flush=True)
    results["seeds"].append(
        {
            "preset": preset,
            "seed": seed,
            "role": role,
            "status": "SUCCESS" if res.winner_id else "NO_FEASIBLE",
            "winnerId": res.winner_id,
            "seconds": round(time.perf_counter() - t0, 1),
        }
    )
    json.dump(results, open(OUT, "w"), indent=1)
    print("SEED", seed, flush=True)
print("DONE")
