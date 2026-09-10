# ruff: noqa: E402, E501, N803, N806, RUF001  # diagnostic script (not production)
"""Phase 20C.4 Gate C step 0 — open finding F1 investigation (diagnostic only).

F1 (Gate B §2): on the successful SWITCHBACK winners of WARPED-305 and
WARPED-322 the WORLD-policy construction backbone inside the candidate's own
footprint reads AT or BEYOND the delivered near leg on five levels
(305 L05 / L07 / L12, 322 L08 / L09) although the level access succeeded.

This script separates the two readings per level, on the actual geometry:

  (a) WINDOW_ARTEFACT  — the shadow's footprint support does not describe a
                         backbone the leg physically runs alongside (no trace
                         point inside the footprint at all → whole-trace
                         fallback, or the support point is far from the ramp)
  (b) GENUINE_CROSSING — the delivered main ramp and the level's development
                         backbone come within excavation-conflict distance in
                         3-D, or cross in plan at a small vertical gap

Both the WORLD (construction) backbone and the CANDIDATE-policy backbone the
level builder actually develops on (rule 180) are measured.  Nothing here
changes production behaviour; thresholds below are diagnostic classification
bands derived from existing planning constants, never new gates.

usage: python scripts/phase20c4_c0_f1.py RANDOM_WARPED_VEIN:305,RANDOM_WARPED_VEIN:322 out.json arrays_dir
"""

import json
import math
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend" / "src"))
import numpy as np

from minegen.core.enums import ScenarioPreset
from minegen.core.models import Scenario
from minegen.layout.access import (
    BACKBONE_END_MARGIN,
    MIN_DEVELOPMENT_TRACE_LENGTH,
    LevelDevelopmentAnchor,
)
from minegen.layout.families import RAMP_CORRIDOR_MARGIN_WIDTHS, rotate
from minegen.layout.geometry import find_crossing
from minegen.layout.search import LayoutV2Search
from minegen.services.scenario_realizer import realize_scenario
from minegen.world.synthetic_world import generate_world


def pts_to_segments_min(P: np.ndarray, A: np.ndarray, B: np.ndarray) -> tuple[np.ndarray, int]:
    """Per point of P: minimum distance to the polyline segments A→B (any dim).
    Returns (dist per point, index of the globally closest P row)."""
    if A.shape[0] == 0:
        return np.full(P.shape[0], np.inf), 0
    AB = B - A
    L2 = np.maximum(np.einsum("md,md->m", AB, AB), 1e-12)
    # (N, M, D)
    PA = P[:, None, :] - A[None, :, :]
    t = np.clip(np.einsum("nmd,md->nm", PA, AB) / L2[None, :], 0.0, 1.0)
    C = A[None, :, :] + t[:, :, None] * AB[None, :, :]
    d = np.linalg.norm(P[:, None, :] - C, axis=2)
    dmin = d.min(axis=1)
    return dmin, int(np.argmin(dmin))


def polyline_min_distance(X: np.ndarray, Y: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    """Minimum distance between two polylines (any dim) + the closest pair
    (point of X to a segment of Y or point of Y to a segment of X)."""
    dx, ix = (
        pts_to_segments_min(X, Y[:-1], Y[1:])
        if Y.shape[0] > 1
        else (np.full(X.shape[0], np.inf), 0)
    )
    dy, iy = (
        pts_to_segments_min(Y, X[:-1], X[1:])
        if X.shape[0] > 1
        else (np.full(Y.shape[0], np.inf), 0)
    )
    if dx[ix] <= dy[iy]:
        return float(dx[ix]), X[ix], Y[int(np.argmin(np.linalg.norm(Y - X[ix], axis=1)))]
    return float(dy[iy]), X[int(np.argmin(np.linalg.norm(X - Y[iy], axis=1)))], Y[iy]


def plan_intersections(R: np.ndarray, T: np.ndarray) -> list[dict]:
    """All plan (XY) intersections between ramp polyline R (N,3) and trace
    polyline T (K,3 or K,2). Returns the ramp z at the crossing."""
    out = []
    if R.shape[0] < 2 or T.shape[0] < 2:
        return out
    P = R[:-1, :2]
    r = R[1:, :2] - P
    Q = T[:-1, :2]
    s = T[1:, :2] - Q
    # cross(r, s) (N, K)
    rxs = r[:, None, 0] * s[None, :, 1] - r[:, None, 1] * s[None, :, 0]
    qp = Q[None, :, :] - P[:, None, :]
    qpxr = qp[:, :, 0] * r[:, None, 1] - qp[:, :, 1] * r[:, None, 0]
    qpxs = qp[:, :, 0] * s[None, :, 1] - qp[:, :, 1] * s[None, :, 0]
    with np.errstate(divide="ignore", invalid="ignore"):
        t = qpxs / rxs
        u = qpxr / rxs
    hit = (np.abs(rxs) > 1e-12) & (t >= 0) & (t <= 1) & (u >= 0) & (u <= 1)
    for i, k in zip(*np.nonzero(hit), strict=True):
        tt = float(t[i, k])
        xy = P[i] + tt * r[i]
        z = float(R[i, 2] + tt * (R[i + 1, 2] - R[i, 2]))
        out.append(
            {
                "rampSegment": int(i),
                "traceSegment": int(k),
                "x": round(float(xy[0]), 2),
                "y": round(float(xy[1]), 2),
                "rampZ": round(z, 2),
            }
        )
    return out


def classify(d3: float, width: float) -> str:
    """Diagnostic bands from existing planning constants (rule 171 pillar
    2×width; rule 170 corridor 6×width). Never a gate."""
    if d3 < 3.0 * width:
        return "CONFLICT"  # centerlines closer than half-width + 2-width pillar + half-width
    if d3 < RAMP_CORRIDOR_MARGIN_WIDTHS * width:
        return "ENCROACH"  # below the corridor separation intent
    return "CLEAR"


JOBS = [j.split(":") for j in sys.argv[1].split(",")]
OUT = sys.argv[2]
ARR = Path(sys.argv[3])
ARR.mkdir(parents=True, exist_ok=True)
out: dict = {"jobs": []}
for preset, seed_s in JOBS:
    seed = int(seed_s)
    t0 = time.perf_counter()
    create = realize_scenario(ScenarioPreset[preset], seed, 1)
    sc = Scenario(**create.model_dump())
    world = generate_world(sc)
    search = LayoutV2Search(sc, world)
    res = search.run()
    track, sections, wpolicy = search._track, search._sections, search.policy
    width = float(sc.ramp.tunnel_width)
    margin = RAMP_CORRIDOR_MARGIN_WIDTHS * width
    req = res.required_clearance
    standoff_world = search.anchor_standoff(req, wpolicy)
    levels = res.serviceable_levels
    dz_level = float(abs(levels[1].elevation - levels[0].elevation))
    w = np.asarray(track.w_h)[:2]
    w = w / np.linalg.norm(w)
    u = np.asarray(track.u_h)[:2]
    u = u / np.linalg.norm(u)
    job: dict = {
        "preset": preset,
        "seed": seed,
        "winnerId": res.winner_id,
        "tunnelWidth": width,
        "corridorMargin": margin,
        "corridorStandoff": res.standoff,
        "anchorStandoffWorld": standoff_world,
        "worldBasis": wpolicy.basis,
        "requiredClearance": req,
        "levelInterval": dz_level,
        "bands": {
            "CONFLICT": f"3D centerline distance < 3 × width = {3 * width:g} m",
            "ENCROACH": f"< {RAMP_CORRIDOR_MARGIN_WIDTHS:g} × width = {margin:g} m",
        },
        "levels": [],
    }
    if not res.winner_id:
        job["error"] = "NO_FEASIBLE"
        out["jobs"].append(job)
        continue
    cand = res.candidate(res.winner_id)
    p = cand.params
    pts = cand.points
    g = float(p.target_gradient)
    _, cpolicy, refinement = search.candidate_policy(res, res.winner_id)
    standoff_cand = search.anchor_standoff(req, cpolicy)
    ctoken = "WORLD" if cpolicy is wpolicy else cand.candidate_id
    job.update(
        {
            "family": p.family.value,
            "candidateBasis": cpolicy.basis,
            "candidateRefinement": refinement,
            "anchorStandoffCandidate": standoff_cand,
        }
    )
    if p.family.value == "SWITCHBACK":
        leg_dir = np.asarray(rotate(u, float(p.principal_orientation_deg)))[:2]
        n = np.array([leg_dir[1], -leg_dir[0]])
        if float(n @ w) < 0:
            n = -n
        along = leg_dir
        k = float(p.legs_per_level)
        station = float(p.station_length_m or 0.0)
        leg = dz_level / (k * g) - math.pi * sc.ramp.min_turn_radius - station
        half = 0.5 * leg + margin
        job["footprint"] = {"legLength": leg, "half": half, "station": station, "k": k}
    else:
        n = np.asarray(rotate(w, float(p.entry_orientation_deg)))[:2]
        along = np.array([n[1], -n[0]])
        R = dz_level / (2.0 * math.pi * g * float(p.turns_per_level))
        half = R + margin
        job["footprint"] = {"radius": R, "half": half}
    # per-segment ramp heading for leg identification
    seg_dir = pts[1:, :2] - pts[:-1, :2]
    seg_len = np.linalg.norm(seg_dir, axis=1)
    seg_hat = seg_dir / np.maximum(seg_len, 1e-12)[:, None]
    # TIGHTENED footprint (C0 candidate refinement of the Gate B contract):
    # the ramp's OWN along-extent — SWITCHBACK legs share one along-centre
    # (all straight legs are stacked on it) and each cycle extends R_min
    # beyond the leg end through its hairpin; SPIRAL keeps the rim (R).
    # The 6-width margin then applies LATERALLY only, never along the leg.
    r_min = float(sc.ramp.min_turn_radius)
    if p.family.value == "SWITCHBACK":
        leg_seg = np.abs(seg_hat @ along) > 0.999
        mids = 0.5 * (pts[1:, :2] + pts[:-1, :2])
        centre_global = float(np.mean(mids[leg_seg] @ along)) if leg_seg.any() else float("nan")
        half_tight = 0.5 * job["footprint"]["legLength"] + r_min
    else:
        centre_global = float("nan")  # per level from the rim samples
        half_tight = job["footprint"]["radius"]
    job["tightenedFootprint"] = {
        "half": half_tight,
        "centreGlobal": centre_global,
        "rule": "SWITCHBACK |along − legCentre| ≤ leg/2 + R_min; SPIRAL |along − rimCentre| ≤ R",
    }
    np.savez(
        ARR / f"ramp_{seed}.npz",
        points=pts,
        n=n,
        along=along,
        w=w,
        u=u,
    )
    for i, lv in enumerate(levels):
        z = lv.elevation
        L: dict = {"levelId": lv.level_id, "z": z}
        # --- the shadow quantities, recomputed (same definitions) ---
        zsel = np.abs(pts[:, 2] - z) <= 0.5 * dz_level
        proj = pts[zsel, :2] @ n
        near = float(np.min(proj))
        near_samples = pts[zsel][proj <= near + width]
        centre = float(np.mean(near_samples[:, :2] @ along))
        L["deliveredNearLateral"] = round(near, 2)
        L["footprintCentre"] = round(centre, 2)
        # is the near set a straight leg? (heading parallel to the leg direction)
        idx = np.nonzero(zsel)[0]
        idx = idx[proj <= near + width]
        idx_seg = idx[idx < seg_hat.shape[0]]
        par = np.abs(seg_hat[idx_seg] @ along) if idx_seg.size else np.zeros(0)
        L["nearSamplesOnStraightLegFraction"] = (
            round(float(np.mean(par > 0.999)), 3) if par.size else None
        )
        cr = find_crossing(pts, z)
        L["rlCrossing"] = [round(float(v), 2) for v in cr.point] if cr is not None else None
        sec = sections.geometry(lv)
        contour = np.asarray(sec.outer_contour_xy)
        traces = {}
        for name, standoff, clearance, token in (
            ("WORLD", standoff_world, wpolicy.signed_clearance, "WORLD"),
            ("CANDIDATE", standoff_cand, cpolicy.signed_clearance, ctoken),
        ):
            try:
                off = sections.offset_trace(
                    lv, track.w_h, standoff, MIN_DEVELOPMENT_TRACE_LENGTH, clearance, token, req
                )
            except Exception as exc:  # typed section failures are reported, not hidden
                L[f"{name.lower()}TraceError"] = repr(exc)[:200]
                continue
            tp = np.asarray(off.points)
            ch = np.asarray(off.chainage)
            total = float(off.total_length)
            end_margin = min(BACKBONE_END_MARGIN, 0.25 * total)
            interior = (ch >= end_margin - 1e-9) & (ch <= total - end_margin + 1e-9)
            traces[name] = tp
            rec: dict = {
                "standoff": standoff,
                "points": int(tp.shape[0]),
                "length": round(total, 1),
            }
            # footprint window support (shadow definition) + where it came from
            win = np.abs(tp[:, :2] @ along - centre) <= half
            rec["tracePointsInFootprint"] = int(win.sum())
            if win.any():
                j = int(np.argmax(np.where(win, tp[:, :2] @ n, -np.inf)))
                rec["supportSource"] = "FOOTPRINT_WINDOW"
            else:
                j = int(np.argmax(tp[:, :2] @ n))
                rec["supportSource"] = "WHOLE_TRACE_FALLBACK"
            support = float(tp[j, :2] @ n)
            rec["support"] = round(support, 2)
            rec["separationFromNearLeg"] = round(near - support, 2)
            rec["delta"] = round(max(0.0, support + margin - near), 2)
            sp = tp[j]
            d_sp_plan, _ = pts_to_segments_min(sp[None, :2], pts[:-1, :2], pts[1:, :2])
            d_sp_3d, _ = pts_to_segments_min(sp[None, :], pts[:-1], pts[1:])
            # tightened footprint (own along-extent), empty window ⇒ δ = 0
            c_t = centre_global if np.isfinite(centre_global) else centre
            win_t = (np.abs(tp[:, :2] @ along - c_t) <= half_tight) & interior
            if win_t.any():
                support_t = float(np.max((tp[:, :2] @ n)[win_t]))
                rec["tightened"] = {
                    "tracePointsInWindow": int(win_t.sum()),
                    "support": round(support_t, 2),
                    "separationFromNearLeg": round(near - support_t, 2),
                    "delta": round(max(0.0, support_t + margin - near), 2),
                }
                # obliquity: mean backbone tangent inside the window vs the leg
                seg_t = tp[1:, :2] - tp[:-1, :2]
                wseg = win_t[1:] & win_t[:-1]
                if wseg.any():
                    tmean = np.sum(seg_t[wseg], axis=0)
                    tmean = tmean / max(float(np.linalg.norm(tmean)), 1e-12)
                    rec["tightened"]["backboneObliquityDeg"] = round(
                        math.degrees(math.acos(min(1.0, abs(float(tmean @ along))))), 1
                    )
            else:
                rec["tightened"] = {"tracePointsInWindow": 0, "delta": 0.0, "support": None}
            rec["supportPoint"] = [round(float(v), 2) for v in sp]
            rec["supportPointToRampPlan"] = round(float(d_sp_plan[0]), 2)
            rec["supportPointToRamp3D"] = round(float(d_sp_3d[0]), 2)
            rec["supportPointAlongOffsetFromCentre"] = round(float(sp[:2] @ along - centre), 2)
            # --- physical proximity: whole ramp vs this level's backbone ---
            d3, a3, b3 = polyline_min_distance(pts, tp)
            rec["minDistance3D"] = round(d3, 2)
            rec["closestRampPoint"] = [round(float(v), 2) for v in a3]
            rec["closestTracePoint"] = [round(float(v), 2) for v in b3]
            rec["closestRampZGap"] = round(float(a3[2] - z), 2)
            d2, a2, b2 = (
                polyline_min_distance(pts[zsel][:, :2], tp[:, :2])
                if zsel.sum() > 1
                else (float("inf"), None, None)
            )
            rec["minPlanDistanceInZWindow"] = round(d2, 2)
            # outward move that would restore the 6-width plan separation at
            # the actual closest approach (lower bound: oblique backbones need
            # slightly more than the perpendicular shortfall)
            rec["requiredMovePlanLowerBound"] = round(max(0.0, margin - d2), 2)
            # interior-only (developed backbone) 3-D distance
            if interior.sum() > 1:
                d3i, _, _ = polyline_min_distance(pts, tp[interior])
                rec["minDistance3DInterior"] = round(d3i, 2)
            # plan crossings with the vertical gap at each
            xs = plan_intersections(pts, tp)
            for x in xs:
                x["zGap"] = round(x["rampZ"] - z, 2)
            rec["planCrossings"] = len(xs)
            rec["planCrossingMinAbsZGap"] = (
                round(min(abs(x["zGap"]) for x in xs), 2) if xs else None
            )
            rec["planCrossingList"] = xs[:12]
            rec["band3D"] = classify(d3, width)
            L[name] = rec
            np.savez(
                ARR / f"trace_{seed}_{lv.level_id}_{name}.npz",
                points=tp,
                interior=interior,
                window=win,
            )
        # ramp vs ore section (certified clearance sanity)
        if contour.shape[0] > 1 and zsel.sum() > 1:
            dc, _, _ = polyline_min_distance(pts[zsel][:, :2], contour)
            L["rampToSectionContourPlanInZWindow"] = round(dc, 2)
        np.savez(ARR / f"section_{seed}_{lv.level_id}.npz", contour=contour)
        # stage-4 anchor + access
        anc = cand.anchors[i] if i < len(cand.anchors) else None
        if isinstance(anc, LevelDevelopmentAnchor):
            L["anchor"] = [round(float(v), 2) for v in anc.position]
            L["anchorSeparation"] = round(near - float(np.asarray(anc.position)[:2] @ n), 2)
        acc = (
            cand.access_plan.accesses[i]
            if cand.access_plan and i < len(cand.access_plan.accesses)
            else None
        )
        if acc is not None:
            L["access"] = {
                "status": acc.status,
                "junction": [round(float(v), 2) for v in acc.junction_position]
                if acc.junction_position is not None
                else None,
                "length": round(float(acc.length3d), 1) if getattr(acc, "length3d", None) else None,
            }
            if acc.points is not None:
                np.savez(ARR / f"access_{seed}_{lv.level_id}.npz", points=np.asarray(acc.points))
        # --- classification ---
        wr = L.get("WORLD")
        cr_ = L.get("CANDIDATE")
        verdict = []
        if wr:
            if wr["supportSource"] == "WHOLE_TRACE_FALLBACK":
                verdict.append("WORLD_SUPPORT_IS_FALLBACK")
            if wr["band3D"] == "CONFLICT" or (
                wr["planCrossings"]
                and wr["planCrossingMinAbsZGap"] is not None
                and wr["planCrossingMinAbsZGap"] < 3.0 * width
            ):
                verdict.append("WORLD_GENUINE_CROSSING")
            elif wr["band3D"] == "ENCROACH":
                verdict.append("WORLD_ENCROACH")
            else:
                verdict.append("WORLD_CLEAR")
        if cr_:
            if cr_["band3D"] == "CONFLICT" or (
                cr_["planCrossings"]
                and cr_["planCrossingMinAbsZGap"] is not None
                and cr_["planCrossingMinAbsZGap"] < 3.0 * width
            ):
                verdict.append("CANDIDATE_GENUINE_CROSSING")
            elif cr_["band3D"] == "ENCROACH":
                verdict.append("CANDIDATE_ENCROACH")
            else:
                verdict.append("CANDIDATE_CLEAR")
        L["verdict"] = verdict
        job["levels"].append(L)
        print(
            "LEVEL",
            seed,
            lv.level_id,
            "near",
            L["deliveredNearLateral"],
            "W",
            wr
            and (
                wr["supportSource"],
                wr["support"],
                wr["minDistance3D"],
                wr["planCrossings"],
                wr["band3D"],
            ),
            "C",
            cr_ and (cr_["support"], cr_["minDistance3D"], cr_["planCrossings"], cr_["band3D"]),
            verdict,
            flush=True,
        )
    job["seconds"] = round(time.perf_counter() - t0, 1)
    out["jobs"].append(job)
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1)
print("DONE")
