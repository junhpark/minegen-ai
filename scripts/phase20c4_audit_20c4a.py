# ruff: noqa: E402, E501, SIM115, N806, RUF059, RUF005, B007, B905  # diagnostic script (not production): sys.path bootstrap precedes imports
"""Phase 20C.4 Gate A — causal reference audit (diagnostic only, no production change).

Inputs: the committed 20C.3A census (classification per candidate) + the
production layout-v2 search re-run on the audited seeds (same call chain).
Measures, per candidate / required level, corridor and anchor positions
against (a) the global FootwallTrack edge and (b) the local section footwall
contact, under the candidate's own clearance policy, and runs two
counterfactuals with the AUTHORITATIVE access planner (all hard gates
intact): CF-ANCHOR (anchor moved to the rule-170 separation from the actual
ramp) and CF-RAMP (whole ramp rigidly shifted so the corridor sits at the
rule-170 separation from the anchor). Population B: per-cluster local vs
track reference at the worst sample.
"""

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
from minegen.layout.access import (
    LevelDevelopmentAnchor,
    plan_level_accesses,
    turnout_heading_change_deg,
)
from minegen.layout.families import rotate
from minegen.layout.search import LayoutV2Search, chainage_of
from minegen.services.scenario_realizer import realize_scenario
from minegen.world.synthetic_world import generate_world

CENSUS = json.load(open(_ROOT / "backend/golden/phase20c3a_failure_census.json"))
CLS = {(c["seed"], c["candidateId"]): c for c in CENSUS["perCandidate"]}
OUT = sys.argv[2]
JOBS = [j.split(":") for j in sys.argv[1].split(",")]  # preset:seed:role
INTENDED_SEP_WIDTHS = 6  # rule 170: corridor = fao + 6 widths, anchor plane at fao


def true_clear(orebody, pts):
    pts = np.asarray(pts, dtype=np.float64).reshape(-1, 3)
    if hasattr(orebody, "approximate_clearance"):
        return np.asarray(orebody.approximate_clearance(pts), dtype=np.float64)
    return np.asarray(orebody.signed_distance(pts), dtype=np.float64)


def plan_dist_to(poly, p):
    poly = np.asarray(poly)[:, :2]
    return float(np.min(np.hypot(poly[:, 0] - p[0], poly[:, 1] - p[1])))


def family_n_hat(cand, track):
    p = cand.params
    fam = p.family.value
    w = np.asarray(track.w_h)[:2]
    w = w / np.linalg.norm(w)
    u = np.asarray(track.u_h)[:2]
    u = u / np.linalg.norm(u)
    try:
        if fam == "SPIRAL":
            return np.asarray(rotate(w, float(p.entry_orientation_deg)))[
                :2
            ], "footwall_edge(z) + rotate(w_h, e)·(standoff + R): rim toward ore at standoff"
        if fam == "SWITCHBACK":
            leg = np.asarray(rotate(u, float(p.principal_orientation_deg)))[:2]
            n = np.array([leg[1], -leg[0]])
            if float(n @ w) < 0:
                n = -n
            return (
                n,
                "footwall_edge(z) + n_hat·standoff (near leg), n_hat ⟂ leg with +w_h component",
            )
        return w, "footwall_edge(z) + w_h·standoff"
    except Exception as exc:
        return w, f"fallback w_h ({exc})"


def audit_level_access(seed, cand, res, search, world, sc, role):
    """Per-level measurements + counterfactuals for one DETAILED candidate."""
    track = search.context.track
    sections = search.context.sections
    w = np.asarray(track.w_h)[:2]
    w = w / np.linalg.norm(w)
    evaluator, policy, refinement = search.candidate_policy(res, cand.candidate_id)
    bound = float(getattr(policy, "error_bound", 0.0) or 0.0)
    req = res.required_clearance
    width = sc.ramp.tunnel_width
    g = sc.ramp.max_gradient
    cfg = sc.layout.access
    plan_sep_min = cfg.minimum_ramp_to_entry_plan_separation or 6 * width
    intended_sep = INTENDED_SEP_WIDTHS * width
    n_hat, corridor_rule = family_n_hat(cand, track)
    pts = cand.points
    ch = chainage_of(pts)
    levels = res.serviceable_levels
    rec = {
        "seed": seed,
        "candidateId": cand.candidate_id,
        "family": cand.params.family.value,
        "role": role,
        "status": cand.status,
        "failureReasons": list(cand.failure_reasons),
        "census": CLS.get((seed, cand.candidate_id), {}).get("classification"),
        "clearance": {
            "basis": policy.basis,
            "errorBound": bound,
            "refinement": refinement,
            "required": req,
        },
        "corridorStandoff": res.standoff,
        "anchorStandoffUsed": search.anchor_standoff(req, policy),
        "corridorRule": corridor_rule,
        "intendedCorridorAnchorSeparation": intended_sep,
        "planSepMin": plan_sep_min,
        "levels": [],
    }
    accesses = {a.level_id: a for a in (cand.access_plan.accesses if cand.access_plan else [])}
    for i, lv in enumerate(levels):
        anc = cand.anchors[i] if i < len(cand.anchors) else None
        L = {"levelId": lv.level_id, "z": lv.elevation}
        if not isinstance(anc, LevelDevelopmentAnchor):
            L["anchor"] = "FAILURE" if anc is not None else None
            rec["levels"].append(L)
            continue
        a = accesses.get(lv.level_id)
        z = lv.elevation
        fe = np.asarray(track.footwall_edge(z))[:2]
        try:
            trace = sections.footwall_trace(lv, track.w_h)
            contact = np.asarray(trace.contact_points)
        except Exception:
            contact = None
        q = np.asarray(anc.position)
        qxy = q[:2]
        corridor_ref = fe + n_hat * res.standoff
        xing = cand.crossings[i] if i < len(cand.crossings) else None
        xp = np.asarray(xing.point) if xing is not None else None
        zsel = (pts[:, 2] <= z + cfg.junction_window_above) & (
            pts[:, 2] >= z - cfg.junction_window_below
        )
        near = None
        if zsel.any():
            d = np.hypot(pts[zsel, 0] - qxy[0], pts[zsel, 1] - qxy[1])
            k = int(np.argmin(d))
            pn = pts[zsel][k]
            near = {
                "planDist": float(d[k]),
                "dz": float(pn[2] - q[2]),
                "requiredRunAtGmax": float(abs(pn[2] - q[2]) / g),
            }
        cert_anchor = float(policy.signed_clearance(q[None, :])[0])
        true_anchor = float(true_clear(world.orebody, q[None, :])[0])
        L.update(
            {
                "anchorPosition": [round(float(v), 2) for v in q],
                "anchorStandoff": anc.standoff,
                "anchorTraceChainage": anc.trace_chainage,
                "anchorToTrackEdgeAlongWh": round(float((qxy - fe) @ w), 2),
                "anchorToTrackEdgePlan": round(float(np.hypot(*(qxy - fe))), 2),
                "anchorToLocalContact": round(
                    float(np.hypot(*(qxy - np.asarray(anc.ore_contact)[:2]))), 2
                )
                if anc.ore_contact is not None
                else None,
                "anchorToLocalContactMin": round(plan_dist_to(contact, qxy), 2)
                if contact is not None
                else None,
                "anchorCertifiedClearance": round(cert_anchor, 2),
                "anchorTrueClearance": round(true_anchor, 2),
                "trackEdgeTrueClearance": round(
                    float(true_clear(world.orebody, np.array([[fe[0], fe[1], z]]))[0]), 2
                ),
                "corridorRefPosition": [round(float(v), 2) for v in corridor_ref],
                "corridorRefToAnchorPlan": round(float(np.hypot(*(corridor_ref - qxy))), 2),
                "corridorRefToLocalContact": round(plan_dist_to(contact, corridor_ref), 2)
                if contact is not None
                else None,
                "corridorRefTrueClearance": round(
                    float(
                        true_clear(
                            world.orebody, np.array([[corridor_ref[0], corridor_ref[1], z]])
                        )[0]
                    ),
                    2,
                ),
                "rampCrossing": [round(float(v), 2) for v in xp] if xp is not None else None,
                "crossingToAnchorPlan": round(float(np.hypot(*(xp[:2] - qxy))), 2)
                if xp is not None
                else None,
                "crossingToLocalContact": round(plan_dist_to(contact, xp[:2]), 2)
                if (xp is not None and contact is not None)
                else None,
                "crossingToTrackEdgePlan": round(float(np.hypot(*(xp[:2] - fe))), 2)
                if xp is not None
                else None,
                "turnoutDegAtCrossing": round(
                    float(
                        turnout_heading_change_deg(
                            pts, ch, float(xing.chainage), cfg.minimum_turnout_straight_buffer
                        )
                    ),
                    1,
                )
                if xing is not None
                else None,
                "nearestRampInWindow": {k: round(v, 2) for k, v in near.items()} if near else None,
                "accessOk": bool(a.ok) if a else None,
                "accessFailure": a.failure_reason if a else None,
                "accessRejections": dict(a.rejection_counts) if a else None,
                "selected": (
                    {
                        "junctionChainage": a.junction_chainage,
                        "connector": a.connector_word,
                        "length3d": a.length3d if hasattr(a, "length3d") else None,
                        "horizontalLength": a.horizontal_length,
                        "maxGradient": a.max_gradient,
                        "junctionToEntryPlanSep": a.junction_to_entry_plan_sep,
                        "junctionOffsetFromCrossing": (
                            round(float(a.junction_chainage - xing.chainage), 1)
                            if (a.junction_chainage is not None and xing is not None)
                            else None
                        ),
                    }
                    if (a and a.ok)
                    else None
                ),
            }
        )
        # analytic counterfactual at the crossing: anchor at the intended separation from the corridor, dz = 0
        if xp is not None:
            sep_now = L["crossingToAnchorPlan"]
            deficit = max(0.0, plan_sep_min - sep_now)
            L["counterfactualAnalytic"] = {
                "separationNow": sep_now,
                "separationShared": max(sep_now, intended_sep),
                "separationDeficit": round(deficit, 2),
                "requiredRunAtGmaxNow": near["requiredRunAtGmax"] if near else None,
                "availableRunNow": near["planDist"] if near else None,
                "requiredRunShared": 0.0,
                "availableRunShared": intended_sep,
                "predictedCategoryShared": (
                    "TURNOUT_NOT_STRAIGHT"
                    if (L["turnoutDegAtCrossing"] or 0) > cfg.maximum_turnout_heading_change_deg
                    else "PREDICTED_OK"
                ),
            }
        rec["levels"].append(L)

    # ---- counterfactuals through the authoritative planner ----
    def run_plan(ramp_pts, anchors):
        plan = plan_level_accesses(
            ramp_pts, anchors, levels, cfg, sc.ramp, evaluator, search.shape, req
        )
        return {
            "feasible": plan.feasible,
            "perLevel": {x.level_id: (x.failure_reason or "OK") for x in plan.accesses},
            "okCount": sum(1 for x in plan.accesses if x.ok),
            "failedCount": sum(1 for x in plan.accesses if not x.ok),
            "meanLength": float(np.mean([x.horizontal_length for x in plan.accesses if x.ok]))
            if any(x.ok for x in plan.accesses)
            else None,
        }

    base = run_plan(pts, cand.anchors)
    # CF-ANCHOR: move each anchor away from its RL-crossing point so the crossing→anchor plan separation is max(now, planSepMin)
    cf_anchors = []
    moved = []
    for i, lv in enumerate(levels):
        anc = cand.anchors[i] if i < len(cand.anchors) else None
        xing = cand.crossings[i] if i < len(cand.crossings) else None
        if isinstance(anc, LevelDevelopmentAnchor) and xing is not None:
            xp = np.asarray(xing.point)[:2]
            q = np.asarray(anc.position)
            v = q[:2] - xp
            s = float(np.linalg.norm(v))
            if s < plan_sep_min and s > 1e-9:
                nq = q.copy()
                nq[:2] = xp + v / s * plan_sep_min
                moved.append(round(plan_sep_min - s, 2))
                cf_anchors.append(dataclasses.replace(anc, position=nq))
                continue
        cf_anchors.append(anc)
    cf_anchor = run_plan(pts, cf_anchors)
    cf_anchor["anchorsMoved"] = len(moved)
    cf_anchor["moveDistances"] = moved
    cf_anchor["movedAnchorCertifiedClearance"] = [
        round(float(policy.signed_clearance(np.asarray(x.position)[None, :])[0]), 2)
        for x, o in zip(cf_anchors, cand.anchors)
        if isinstance(x, LevelDevelopmentAnchor) and x is not o
    ]
    # CF-RAMP: rigid plan shift of the whole ramp by the median deficit along the median (crossing→anchor) direction reversed
    vecs = []
    for i, lv in enumerate(levels):
        anc = cand.anchors[i] if i < len(cand.anchors) else None
        xing = cand.crossings[i] if i < len(cand.crossings) else None
        if isinstance(anc, LevelDevelopmentAnchor) and xing is not None:
            xp = np.asarray(xing.point)[:2]
            q = np.asarray(anc.position)[:2]
            v = xp - q
            s = float(np.linalg.norm(v))
            if s < plan_sep_min and s > 1e-9:
                vecs.append(v / s * (plan_sep_min - s))
    if vecs:
        shift = np.median(np.array(vecs), axis=0)
        shifted = pts.copy()
        shifted[:, :2] += shift[None, :]
        cf_ramp = run_plan(shifted, cand.anchors)
        cf_ramp["shift"] = [round(float(shift[0]), 2), round(float(shift[1]), 2)]
        cf_ramp["shiftNorm"] = round(float(np.linalg.norm(shift)), 2)
        # ramp validity of the shifted corridor under the candidate policy (clearance only; terrain / world untouched by a plan shift of this size is NOT guaranteed)
        cert = policy.signed_clearance(shifted)
        cf_ramp["shiftedRampMinCertifiedClearance"] = round(float(np.min(cert)), 2)
        cf_ramp["shiftedRampClearanceOk"] = bool(np.min(cert) >= req - 1e-9)
    else:
        cf_ramp = {"skipped": "no level below the plan-separation minimum"}
    rec["counterfactual"] = {
        "baseline": base,
        "cfAnchorAtSharedSeparation": cf_anchor,
        "cfRampAtSharedSeparation": cf_ramp,
    }
    return rec


def audit_clusters(seed, cand, res, search, world, sc, cls_rec):
    """Population B: per cluster (from the census), worst sample local vs track reference."""
    track = search.context.track
    evaluator, policy, refinement = search.candidate_policy(res, cand.candidate_id)
    bound = float(getattr(policy, "error_bound", 0.0) or 0.0)
    req = res.required_clearance
    pts = cand.points
    ch = chainage_of(pts)
    cert = np.asarray(policy.signed_clearance(pts))
    tru = true_clear(world.orebody, pts)
    fe_all = np.array([np.asarray(track.footwall_edge(float(z)))[:2] for z in pts[:, 2]])
    d_track = np.hypot(pts[:, 0] - fe_all[:, 0], pts[:, 1] - fe_all[:, 1])
    offset = (
        d_track - tru
    )  # how far the LOCAL contact sits outside the track edge, seen from the sample
    in_cluster = np.zeros(len(pts), bool)
    clusters = []
    for c in cls_rec["failureClusters"]:
        if c.get("portalArtifact"):
            continue
        sel = (ch >= c["startChainage"] - 1e-6) & (ch <= c["endChainage"] + 1e-6)
        in_cluster |= sel
        if not sel.any():
            continue
        idx = np.flatnonzero(sel)
        k = idx[int(np.argmin(cert[sel]))]
        clusters.append(
            {
                "startChainage": c["startChainage"],
                "endChainage": c["endChainage"],
                "span": c["span"],
                "reasons": c["reasons"],
                "worstSample": {
                    "chainage": round(float(ch[k]), 1),
                    "z": round(float(pts[k, 2]), 1),
                    "certifiedClearance": round(float(cert[k]), 2),
                    "trueClearance": round(float(tru[k]), 2),
                    "effectiveBound": round(float(tru[k] - cert[k]), 2),
                    "distToTrackEdge": round(float(d_track[k]), 2),
                    "localContactOffsetFromTrackEdge": round(float(offset[k]), 2),
                    "deficit": round(float(max(0.0, req - cert[k])), 2),
                    "trueBelowRequired": bool(tru[k] < req),
                },
                "predictedIfCorridorAtStandoffFromLocalContact": {
                    "trueClearance": res.standoff,
                    "certified": round(float(res.standoff - (tru[k] - cert[k])), 2),
                    "satisfied": bool(res.standoff - (tru[k] - cert[k]) >= req),
                },
            }
        )
    band = d_track <= res.standoff + 15.0  # samples on / near the ore-facing corridor
    out = {
        "seed": seed,
        "candidateId": cand.candidate_id,
        "family": cand.params.family.value,
        "basis": policy.basis,
        "errorBound": bound,
        "required": req,
        "corridorStandoff": res.standoff,
        "clusters": clusters,
        "offsetStats": {
            "inClusterMean": round(float(np.mean(offset[in_cluster])), 2)
            if in_cluster.any()
            else None,
            "outsideClusterOnCorridorMean": round(float(np.mean(offset[band & ~in_cluster])), 2)
            if (band & ~in_cluster).any()
            else None,
            "outsideClusterOnCorridorP90": round(
                float(np.percentile(offset[band & ~in_cluster], 90)), 2
            )
            if (band & ~in_cluster).any()
            else None,
            "inClusterMin": round(float(np.min(offset[in_cluster])), 2)
            if in_cluster.any()
            else None,
            "trackResidualP90": None,
        },
        "rankTest": None,
    }
    # do clusters sit at the maxima of the local-contact offset along the corridor band?
    if in_cluster.any() and (band & ~in_cluster).any():
        thr = float(np.percentile(offset[band], 80))
        out["rankTest"] = {
            "p80OffsetOnCorridor": round(thr, 2),
            "fractionOfClusterSamplesAboveP80": round(float(np.mean(offset[in_cluster] >= thr)), 3),
            "fractionOfNonClusterCorridorSamplesAboveP80": round(
                float(np.mean(offset[band & ~in_cluster] >= thr)), 3
            ),
        }
    return out


results = {"levelAccess": [], "clusters": [], "seeds": []}
for preset, seed, role in JOBS:
    seed = int(seed)
    t0 = time.perf_counter()
    create = realize_scenario(ScenarioPreset[preset], seed, 1)
    sc = Scenario(**create.model_dump())
    world = generate_world(sc)
    search = LayoutV2Search(sc, world)
    res = search.run()
    detailed = [c for c in res.candidates if c.stage_reached == "DETAILED"]
    seedrec = {
        "preset": preset,
        "seed": seed,
        "role": role,
        "status": "SUCCESS" if res.winner_id else "NO_FEASIBLE",
        "winnerId": res.winner_id,
        "detailed": len(detailed),
    }
    picks = []
    if role == "CONTROL":
        feas = [c for c in detailed if c.status == "FEASIBLE"]
        picks = (
            feas[:3]
            if res.winner_id is None
            else (
                [res.candidate(res.winner_id)]
                + [c for c in feas if c.candidate_id != res.winner_id][:2]
            )
        )
    else:
        picks = [
            c
            for c in detailed
            if CLS.get((seed, c.candidate_id), {}).get("classification") == "LEVEL_ACCESS_PROBLEM"
        ][:6]
    for c in picks:
        try:
            results["levelAccess"].append(audit_level_access(seed, c, res, search, world, sc, role))
        except Exception as exc:
            results["levelAccess"].append(
                {"seed": seed, "candidateId": c.candidate_id, "error": repr(exc)}
            )
        print(seed, c.candidate_id, "LA done", flush=True)
    for c in detailed:
        cr = CLS.get((seed, c.candidate_id))
        if cr and cr["classification"] == "MULTI_CLUSTER_CLEARANCE":
            try:
                results["clusters"].append(audit_clusters(seed, c, res, search, world, sc, cr))
            except Exception as exc:
                results["clusters"].append(
                    {"seed": seed, "candidateId": c.candidate_id, "error": repr(exc)}
                )
            print(seed, c.candidate_id, "MC done", flush=True)
    seedrec["seconds"] = round(time.perf_counter() - t0, 1)
    results["seeds"].append(seedrec)
    print("SEED", json.dumps(seedrec), flush=True)
    json.dump(results, open(OUT, "w"), indent=1)
print("DONE")
