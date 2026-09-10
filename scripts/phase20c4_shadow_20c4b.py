# ruff: noqa: E402  # diagnostic script (not production)
"""Phase 20C.4 Gate B — shadow computation of the shared service reference on
CANDIDATE-SPECIFIC exact geometry (diagnostic only, no production change).

For every constructed SPIRAL / SWITCHBACK candidate of the production
enumeration (its own gradient g, turns/level n, legs/level k, station,
orientation) and every serviceable level:

  nearLateral   = ore-facing extreme of the DELIVERED candidate polyline
                  within ± half a level interval of the RL, projected on the
                  family lateral direction n (the real corridor position)
  footprint     = SPIRAL: |along − centre| ≤ R + margin, R = ΔZ / (2π g n)
                  SWITCHBACK: |along − centre| ≤ leg/2 + margin,
                  leg = ΔZ/(k g) − π R_min − station (the family's own rule 143
                  derivation), centre = mean along-coordinate of the near-leg
                  samples
  support       = max over the WORLD-policy offset-trace points (anchor
                  stand-off, token WORLD) inside the footprint of p·n
  delta         = max(0, support + RAMP_CORRIDOR_MARGIN_WIDTHS·width − nearLateral)
  deltaInterior = the same over the trace INTERIOR only — the end margins excluded exactly as
                  the anchor admissible range excludes them (min(BACKBONE_END_MARGIN, 0.25·length))

No hard-coded gradient, legs-per-level or leg length: every number comes
from the candidate's parameters or the delivered polyline. LONGITUDINAL is
reported informationally only (whole-trace support) — the Gate B contract
defers it unchanged. TABULAR keeps the analytic path (delta ≡ 0 by contract).
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
from minegen.layout.search import LayoutV2Search
from minegen.services.scenario_realizer import realize_scenario
from minegen.world.orebody import TabularOrebody
from minegen.world.synthetic_world import generate_world

JOBS = [j.split(":") for j in sys.argv[1].split(",")]
OUT = sys.argv[2]
out = {"jobs": []}
for preset, seed in JOBS:
    seed = int(seed)
    t0 = time.perf_counter()
    create = realize_scenario(ScenarioPreset[preset], seed, 1)
    sc = Scenario(**create.model_dump())
    world = generate_world(sc)
    search = LayoutV2Search(sc, world)
    res = search.run()
    track, sections, policy = search.context.track, search.context.sections, search.policy
    width = sc.ramp.tunnel_width
    margin = RAMP_CORRIDOR_MARGIN_WIDTHS * width
    req = res.required_clearance
    standoff_anchor = search.anchor_standoff(req, policy)
    tab = isinstance(world.orebody, TabularOrebody)
    w = np.asarray(track.w_h)[:2]
    w = w / np.linalg.norm(w)
    u = np.asarray(track.u_h)[:2]
    u = u / np.linalg.norm(u)
    levels = res.serviceable_levels
    dz_level = (
        float(abs(levels[1].elevation - levels[0].elevation)) if len(levels) > 1 else float("nan")
    )
    traces = {}
    if not tab:
        for lv in levels:
            try:
                off = sections.offset_trace(
                    lv,
                    track.w_h,
                    standoff_anchor,
                    MIN_DEVELOPMENT_TRACE_LENGTH,
                    policy.signed_clearance,
                    "WORLD",
                    req,
                )
                tpts = np.asarray(off.points)[:, :2]
                ch = np.asarray(off.chainage)
                total = float(off.total_length)
                end_margin = min(BACKBONE_END_MARGIN, 0.25 * total)
                interior = (ch >= end_margin - 1e-9) & (ch <= total - end_margin + 1e-9)
                traces[lv.level_id] = (tpts, interior)
            except Exception as exc:
                traces[lv.level_id] = repr(exc)[:160]
    job = {
        "preset": preset,
        "seed": seed,
        "status": "SUCCESS" if res.winner_id else "NO_FEASIBLE",
        "winnerId": res.winner_id,
        "basis": policy.basis,
        "errorBound": float(getattr(policy, "error_bound", 0.0) or 0.0),
        "corridorStandoff": res.standoff,
        "corridorStandoffSource": "EXPLICIT"
        if sc.layout.footwall_standoff is not None
        else "DEFAULT_OFFSET_PLUS_CORRIDOR_MARGIN",
        "anchorStandoffWorld": standoff_anchor,
        "corridorMargin": margin,
        "levelInterval": dz_level,
        "tabular": tab,
        "trackResidualsPerLevel": [round(float(r), 2) for r in track.residuals()],
        "candidates": [],
    }
    for cand in res.candidates:
        p = cand.params
        fam = p.family.value
        if cand.points is None or (fam == "LONGITUDINAL" and tab):
            continue
        pts = cand.points
        g = float(p.target_gradient)
        if fam == "SPIRAL":
            n = np.asarray(rotate(w, float(p.entry_orientation_deg)))[:2]
            along = np.array([n[1], -n[0]])
            R = dz_level / (2.0 * math.pi * g * float(p.turns_per_level))
            half = R + margin
            footprint = {"radius": round(R, 2), "half": round(half, 2)}
        elif fam == "SWITCHBACK":
            leg_dir = np.asarray(rotate(u, float(p.principal_orientation_deg)))[:2]
            n = np.array([leg_dir[1], -leg_dir[0]])
            if float(n @ w) < 0:
                n = -n
            along = leg_dir
            k = float(p.legs_per_level)
            station = float(p.station_length_m or 0.0)
            leg = dz_level / (k * g) - math.pi * sc.ramp.min_turn_radius - station
            half = 0.5 * leg + margin
            footprint = {
                "legLength": round(leg, 2),
                "legsPerLevel": k,
                "station": station,
                "half": round(half, 2),
            }
        else:
            n = w
            along = u
            half = float("inf")
            footprint = {
                "note": "LONGITUDINAL: whole trace, informational only (deferred unchanged)"
            }
        crec = {
            "candidateId": cand.candidate_id,
            "family": fam,
            "status": cand.status,
            "stageReached": cand.stage_reached,
            "gradient": g,
            "footprint": footprint,
            "levels": [],
        }
        deltas = []
        deltas_i = []
        for i, lv in enumerate(levels):
            z = lv.elevation
            fe = np.asarray(track.footwall_edge(z))[:2]
            old = float(fe @ n + res.standoff)
            zsel = (
                np.abs(pts[:, 2] - z) <= 0.5 * dz_level
                if np.isfinite(dz_level)
                else np.abs(pts[:, 2] - z) <= 12.5
            )
            if not zsel.any():
                continue
            proj = pts[zsel, :2] @ n
            near = float(np.min(proj))
            near_samples = pts[zsel][proj <= near + width]
            centre = float(np.mean(near_samples[:, :2] @ along))
            L = {
                "levelId": lv.level_id,
                "z": z,
                "formulaLateral": round(old, 2),
                "deliveredNearLateral": round(near, 2),
                "formulaError": round(near - old, 2),
            }
            anc = cand.anchors[i] if i < len(cand.anchors) else None
            if isinstance(anc, LevelDevelopmentAnchor):
                L["stage4AnchorSeparation"] = round(
                    near - float(np.asarray(anc.position)[:2] @ n), 2
                )
            if tab:
                L.update({"delta": 0.0, "note": "TABULAR analytic path unchanged by contract"})
            else:
                tp = traces.get(lv.level_id)
                if not isinstance(tp, tuple):
                    L["traceError"] = tp
                else:
                    tp, interior = tp
                    win = np.abs(tp @ along - centre) <= half
                    support = float(np.max((tp @ n)[win])) if win.any() else float(np.max(tp @ n))
                    win_i = win & interior
                    support_i = float(np.max((tp @ n)[win_i])) if win_i.any() else support
                    d = max(0.0, support + margin - near)
                    d_i = max(0.0, support_i + margin - near)
                    L.update(
                        {
                            "footprintCentre": round(centre, 2),
                            "tracePointsInFootprint": int(win.sum()),
                            "tracePointsInFootprintInterior": int(win_i.sum()),
                            "traceSupport": round(support, 2),
                            "traceSupportInterior": round(support_i, 2),
                            "separationFromBackbone": round(near - support, 2),
                            "separationFromBackboneInterior": round(near - support_i, 2),
                            "delta": round(d, 2),
                            "deltaInterior": round(d_i, 2),
                            "deltaVsFormula": round(max(0.0, support + margin - old), 2),
                        }
                    )
                    deltas.append(d)
                    deltas_i.append(d_i)
            crec["levels"].append(L)
        if deltas_i:
            crec["deltaInteriorMedian"] = round(float(np.median(deltas_i)), 2)
            crec["deltaInteriorMax"] = round(float(np.max(deltas_i)), 2)
        if deltas:
            crec["deltaMedian"] = round(float(np.median(deltas)), 2)
            crec["deltaMax"] = round(float(np.max(deltas)), 2)
            crec["deltaMin"] = round(float(np.min(deltas)), 2)
        job["candidates"].append(crec)
    # summaries by family / status
    summ = {}
    for fam in ("SPIRAL", "SWITCHBACK", "LONGITUDINAL"):
        for st in ("FEASIBLE", "INFEASIBLE", "NOT_VALIDATED"):
            cs = [
                c
                for c in job["candidates"]
                if c["family"] == fam and c["status"] == st and "deltaMedian" in c
            ]
            if cs:
                summ[f"{fam}/{st}"] = {
                    "candidates": len(cs),
                    "deltaMedianOfMedians": round(
                        float(np.median([c["deltaMedian"] for c in cs])), 2
                    ),
                    "deltaMaxOfMax": round(float(np.max([c["deltaMax"] for c in cs])), 2),
                    "candidatesWithDeltaAboveOne": sum(1 for c in cs if c["deltaMedian"] > 1.0),
                    "deltaInteriorMedianOfMedians": round(
                        float(np.median([c["deltaInteriorMedian"] for c in cs])), 2
                    ),
                    "deltaInteriorMaxOfMax": round(
                        float(np.max([c["deltaInteriorMax"] for c in cs])), 2
                    ),
                    "candidatesWithDeltaInteriorAboveOne": sum(
                        1 for c in cs if c["deltaInteriorMedian"] > 1.0
                    ),
                }
    if res.winner_id:
        wc = next((c for c in job["candidates"] if c["candidateId"] == res.winner_id), None)
        if wc:
            summ["WINNER"] = {
                "candidateId": wc["candidateId"],
                "family": wc["family"],
                "deltaMedian": wc.get("deltaMedian"),
                "deltaMax": wc.get("deltaMax"),
                "deltaInteriorMedian": wc.get("deltaInteriorMedian"),
                "deltaInteriorMax": wc.get("deltaInteriorMax"),
            }
    job["summary"] = summ
    job["seconds"] = round(time.perf_counter() - t0, 1)
    out["jobs"].append(job)
    print("JOB", seed, job["status"], json.dumps(summ), flush=True)
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1)
print("DONE")
