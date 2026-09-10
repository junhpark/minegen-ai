# ruff: noqa: E501, SIM115, F841  # diagnostic script (not production)
"""Gate B sanity: does footwall_edge(z)·n + standoff reproduce the DELIVERED near-leg / rim lateral, and how far is the
delivered ore-facing corridor from (a) the stage-4 anchors and (b) the WORLD-policy anchor-trace support inside the family footprint?"""

import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend" / "src"))
import numpy as np

from minegen.core.enums import ScenarioPreset
from minegen.core.models import Scenario
from minegen.layout.access import MIN_DEVELOPMENT_TRACE_LENGTH, LevelDevelopmentAnchor
from minegen.layout.families import RAMP_CORRIDOR_MARGIN_WIDTHS, rotate
from minegen.layout.search import LayoutV2Search
from minegen.services.scenario_realizer import realize_scenario
from minegen.world.synthetic_world import generate_world

out = []
for job in sys.argv[1].split(","):
    seed, cid = job.split("/")
    seed = int(seed)
    create = realize_scenario(ScenarioPreset.RANDOM_WARPED_VEIN, seed, 1)
    sc = Scenario(**create.model_dump())
    world = generate_world(sc)
    search = LayoutV2Search(sc, world)
    res = search.run()
    cand = res.candidate(cid) if cid != "WINNER" else res.candidate(res.winner_id)
    track = search.context.track
    sections = search.context.sections
    policy = search.policy
    req = res.required_clearance
    w = np.asarray(track.w_h)[:2]
    w /= np.linalg.norm(w)
    u = np.asarray(track.u_h)[:2]
    u /= np.linalg.norm(u)
    p = cand.params
    fam = p.family.value
    if fam == "SPIRAL":
        n = np.asarray(rotate(w, float(p.entry_orientation_deg)))[:2]
        along = np.array([n[1], -n[0]])
    else:
        leg = np.asarray(rotate(u, float(p.principal_orientation_deg)))[:2]
        n = np.array([leg[1], -leg[0]])
        n = n if float(n @ w) >= 0 else -n
        along = leg
    margin = RAMP_CORRIDOR_MARGIN_WIDTHS * sc.ramp.tunnel_width
    so = search.anchor_standoff(req, policy)
    pts = cand.points
    rows = []
    for i, lv in enumerate(res.serviceable_levels):
        z = lv.elevation
        fe = np.asarray(track.footwall_edge(z))[:2]
        sel = np.abs(pts[:, 2] - z) <= 3.0
        if not sel.any():
            continue
        proj = pts[sel, :2] @ n
        near_lat = float(np.min(proj))  # ore-facing extreme of the delivered ramp at this RL
        near_pt = pts[sel][int(np.argmin(proj))]
        old_lat = float(fe @ n + res.standoff)
        anc = cand.anchors[i] if i < len(cand.anchors) else None
        a_lat = (
            float(np.asarray(anc.position)[:2] @ n)
            if isinstance(anc, LevelDevelopmentAnchor)
            else None
        )
        try:
            off = sections.offset_trace(
                lv,
                track.w_h,
                so,
                MIN_DEVELOPMENT_TRACE_LENGTH,
                policy.signed_clearance,
                "WORLD",
                req,
            )
            tp = np.asarray(off.points)[:, :2]
            # footprint window along the family's along-direction around the delivered near point
            if fam == "SPIRAL":
                dzl = float(
                    abs(res.serviceable_levels[1].elevation - res.serviceable_levels[0].elevation)
                )
                R = dzl / (2 * math.pi * p.target_gradient * float(p.turns_per_level))
                win = np.abs(tp @ along - float(near_pt[:2] @ along)) <= R + margin
            else:
                leg_len = dzl if False else None
                win = (
                    np.abs(tp @ along - float(near_pt[:2] @ along)) <= 80.0 + margin
                )  # ± half of a ~160 m leg
            sup = float(np.max((tp @ n)[win])) if win.any() else float(np.max(tp @ n))
            sup_all = float(np.max(tp @ n))
        except Exception as exc:
            sup = sup_all = None
        acc = [
            a
            for a in (cand.access_plan.accesses if cand.access_plan else [])
            if a.level_id == lv.level_id
        ]
        rows.append(
            {
                "level": lv.level_id,
                "deliveredNearLateral": round(near_lat, 1),
                "formulaLateral(edge+standoff)": round(old_lat, 1),
                "formulaError": round(near_lat - old_lat, 1),
                "anchorLateral": round(a_lat, 1) if a_lat is not None else None,
                "anchorSepFromNearLeg": round(near_lat - a_lat, 1) if a_lat is not None else None,
                "traceSupportWindowed": round(sup, 1) if sup is not None else None,
                "sepFromTraceSupport": round(near_lat - sup, 1) if sup is not None else None,
                "traceSupportWhole": round(sup_all, 1) if sup_all is not None else None,
                "access": (acc[0].failure_reason or "OK") if acc else None,
            }
        )
    out.append({"seed": seed, "candidate": cand.candidate_id, "status": cand.status, "rows": rows})
    print(seed, cand.candidate_id, cand.status, flush=True)
    for r in rows:
        print("   ", r, flush=True)
json.dump(out, open(sys.argv[2], "w"), indent=1)
