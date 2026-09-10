# ruff: noqa: E402, E501, SIM115, E741  # diagnostic script (not production)
"""Phase 20C.4 Gate B — shadow computation of the proposed shared service
reference (diagnostic only, no production change).

For every serviceable level and every family lateral direction n of the
declared grids, compare the CURRENT corridor lateral coordinate
(footwall_edge(z)·n + footwallStandoff) with the SHARED-reference one
(max(current, support of the WORLD-policy offset trace at the anchor
stand-off along n + RAMP_CORRIDOR_MARGIN_WIDTHS·width)). delta = new − old.
TABULAR keeps the analytic path (delta ≡ 0 by contract); its track-fit
residual is reported for information only.
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
from minegen.layout.access import MIN_DEVELOPMENT_TRACE_LENGTH
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
    track = search._track
    sections = search._sections
    policy = search.policy
    width = sc.ramp.tunnel_width
    margin = RAMP_CORRIDOR_MARGIN_WIDTHS * width
    req = res.required_clearance
    standoff_corr = res.standoff
    standoff_anchor = search.anchor_standoff(req, policy)
    tab = isinstance(world.orebody, TabularOrebody)
    w = np.asarray(track.w_h)[:2]
    w /= np.linalg.norm(w)
    u = np.asarray(track.u_h)[:2]
    u /= np.linalg.norm(u)
    dirs = {}
    for e in (
        sc.layout.spiral.entry_orientations_deg if hasattr(sc.layout, "spiral") else (-45, 0, 45)
    ):
        dirs[f"SPIRAL e{float(e):+.0f}"] = np.asarray(rotate(w, float(e)))[:2]
    for p in (
        sc.layout.switchback.principal_orientations_deg
        if hasattr(sc.layout, "switchback")
        else (-20, 0, 20)
    ):
        leg = np.asarray(rotate(u, float(p)))[:2]
        n = np.array([leg[1], -leg[0]])
        if float(n @ w) < 0:
            n = -n
        dirs[f"SWITCHBACK p{float(p):+.0f}"] = n
    dirs["LONGITUDINAL"] = w
    job = {
        "preset": preset,
        "seed": seed,
        "status": "SUCCESS" if res.winner_id else "NO_FEASIBLE",
        "basis": policy.basis,
        "errorBound": float(getattr(policy, "error_bound", 0.0) or 0.0),
        "corridorStandoff": standoff_corr,
        "anchorStandoffWorld": standoff_anchor,
        "corridorMargin": margin,
        "tabular": tab,
        "trackResidualsPerLevel": [round(float(r), 2) for r in track.residuals()],
        "levels": [],
    }
    for lv in res.serviceable_levels:
        z = lv.elevation
        fe = np.asarray(track.footwall_edge(z))[:2]
        L = {"levelId": lv.level_id, "z": z, "byDirection": {}}
        if tab:
            for name, n in dirs.items():
                L["byDirection"][name] = {
                    "oldLateral": round(float(fe @ n + standoff_corr), 3),
                    "delta": 0.0,
                    "note": "TABULAR analytic path unchanged by contract",
                }
            job["levels"].append(L)
            continue
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
            pts = np.asarray(off.points)[:, :2]
        except Exception as exc:
            L["traceError"] = repr(exc)[:200]
            job["levels"].append(L)
            continue
        L["traceLength"] = round(float(off.total_length), 1)
        L["tracePoints"] = int(pts.shape[0])
        uc = float(np.asarray(track.centroid(z))[:2] @ u)
        for name, n in dirs.items():
            old = float(fe @ n + standoff_corr)
            anchor_plane_track = float(fe @ n + standoff_anchor)
            proj = pts @ n
            support_all = float(np.max(proj))
            # spiral window: ±(R + margin) around the centroid's along-strike coordinate, R from the level interval at g 0.12, n=1
            dzl = (
                float(abs(np.diff([l.elevation for l in res.serviceable_levels[:2]])[0]))
                if len(res.serviceable_levels) > 1
                else 25.0
            )
            if name.startswith("SPIRAL"):
                # helix footprint: ±(R + margin) around the axis' along-strike coordinate (axis sits at the track centroid's u)
                R = dzl / (2 * math.pi * 0.12)
                win = np.abs(pts @ u - uc) <= R + margin
                support = float(np.max(proj[win])) if win.any() else support_all
            elif name.startswith("SWITCHBACK"):
                # near-leg footprint: the leg is centred on the centroid along leg_dir; k = 1 gives the longest leg (conservative window)
                leg_dir = np.array([n[1], -n[0]])
                leg_len = dzl / 0.12 - math.pi * sc.ramp.min_turn_radius
                cc = float(np.asarray(track.centroid(z))[:2] @ leg_dir)
                win = np.abs(pts @ leg_dir - cc) <= 0.5 * leg_len + margin
                support = float(np.max(proj[win])) if win.any() else support_all
            else:
                support = support_all
            delta = max(0.0, support + margin - old)
            delta_all = max(0.0, support_all + margin - old)
            L["byDirection"][name] = {
                "oldLateral": round(old, 3),
                "anchorPlaneTrackBased": round(anchor_plane_track, 3),
                "anchorTraceSupport": round(support, 3),
                "anchorTraceSupportWhole": round(support_all, 3),
                "backboneProtrusion": round(support - anchor_plane_track, 3),
                "delta": round(delta, 3),
                "deltaWholeTrace": round(delta_all, 3),
                "newLateral": round(old + delta, 3),
            }
        job["levels"].append(L)
    # per-direction summary
    summ = {}
    for name in dirs:
        ds = [
            L["byDirection"][name]["delta"]
            for L in job["levels"]
            if name in L.get("byDirection", {})
        ]
        pr = [
            L["byDirection"][name].get("backboneProtrusion", 0.0)
            for L in job["levels"]
            if name in L.get("byDirection", {})
        ]
        if ds:
            summ[name] = {
                "levels": len(ds),
                "deltaMedian": round(float(np.median(ds)), 2),
                "deltaMax": round(float(np.max(ds)), 2),
                "deltaMin": round(float(np.min(ds)), 2),
                "protrusionMedian": round(float(np.median(pr)), 2),
            }
    job["summary"] = summ
    job["seconds"] = round(time.perf_counter() - t0, 1)
    out["jobs"].append(job)
    print("JOB", seed, job["status"], json.dumps(summ), flush=True)
    json.dump(out, open(OUT, "w"), indent=1)
print("DONE")
