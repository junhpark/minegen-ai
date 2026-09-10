# ruff: noqa: E501, SIM115  # diagnostic script (not production)
import collections
import json
import sys

import numpy as np

S = sys.argv[1] if len(sys.argv) > 1 else "."
J = json.load(open(f"{S}/audit_20c4a_junctions.json"))
A = json.load(open(f"{S}/audit_20c4a.json"))
print(
    "=== PER-JUNCTION AUDIT: candidates",
    len(J["candidates"]),
    "seeds",
    [(s["seed"], s["role"], s["status"]) for s in J["seeds"]],
)
rows = []
for r in J["candidates"]:
    if "error" in r:
        print("ERR", r["seed"], r["candidateId"], r["error"][:200])
        continue
    for L in r["levels"]:
        if "junctions" not in L:
            continue
        rows.append(
            {
                "seed": r["seed"],
                "cand": r["candidateId"],
                "family": r["family"],
                "role": r["role"],
                "basis": r["basis"],
                "level": L["levelId"],
                "ok": L["accessOk"],
                "reported": L["reportedReason"],
                "binding": L["bindingCause"],
                "near": L["nearestApproach"]["planDist"] if L["nearestApproach"] else None,
                "nearDz": L["nearestApproach"]["dz"] if L["nearestApproach"] else None,
                "pred": (L["sharedReferencePrediction"] or {}).get("predicted"),
                "gf": L["gradeFeasibleCount"],
                "gfReasons": L["gradeFeasibleReasons"],
                "selOffset": (L.get("selected") or {}).get("offsetFromCrossing"),
                "selLen": (L.get("selected") or {}).get("horizontalLength"),
                "selSep": (L.get("selected") or {}).get("planSep"),
                "anchorTrue": L["anchorTrueClearance"],
                "anchorCert": L["anchorCertifiedClearance"],
            }
        )


def tab(rs, title):
    print("\n--", title, "levels:", len(rs))
    print("   reported reason x binding cause:")
    ct = collections.Counter((x["reported"] or "OK", x["binding"]) for x in rs)
    for (rep, b), n in sorted(ct.items(), key=lambda kv: -kv[1]):
        print(f"     {rep:32s} {b:40s} {n}")
    near = [x["near"] for x in rs if x["near"] is not None]
    if near:
        print(
            "   nearest ramp approach to anchor (plan, m): p10/p50/p90 =",
            np.percentile(near, [10, 50, 90]).round(1),
            "| fraction < 30 m:",
            round(float(np.mean(np.array(near) < 30)), 3),
        )
    pr = collections.Counter(x["pred"] for x in rs)
    print("   shared-reference analytic prediction:", dict(pr))


failed = [x for x in rows if x["role"] == "LA" and not x["ok"]]
okla = [x for x in rows if x["role"] == "LA" and x["ok"]]
tab(failed, "POPULATION A failed levels (LA seeds)")
tab(okla, "POPULATION A OK levels on the same failed candidates")
sel = [x for x in okla if x["selLen"] is not None]
if sel:
    print(
        "   OK levels: selected connector horizontal length p10/p50/p90:",
        np.percentile([x["selLen"] for x in sel], [10, 50, 90]).round(1),
        "| |junction offset from crossing| p50:",
        round(
            float(np.median([abs(x["selOffset"]) for x in sel if x["selOffset"] is not None])), 1
        ),
        "| plan sep p50:",
        round(float(np.median([x["selSep"] for x in sel if x["selSep"]])), 1),
    )
for fam in ("SPIRAL", "SWITCHBACK"):
    tab([x for x in failed if x["family"] == fam], f"POPULATION A failed levels — {fam}")
ctrl = [x for x in rows if x["role"] == "CONTROL"]
for key in sorted({(x["seed"], x["basis"]) for x in ctrl}):
    rs = [x for x in ctrl if (x["seed"], x["basis"]) == key]
    tab(rs, f"CONTROL seed {key[0]} ({key[1]})")
    sel = [x for x in rs if x["selLen"] is not None]
    if sel:
        print(
            "   selected connector length p10/p50/p90:",
            np.percentile([x["selLen"] for x in sel], [10, 50, 90]).round(1),
            "| plan sep p50:",
            round(float(np.median([x["selSep"] for x in sel if x["selSep"]])), 1),
            "| anchor true clearance p50:",
            round(float(np.median([x["anchorTrue"] for x in rs])), 1),
            "cert p50:",
            round(float(np.median([x["anchorCert"] for x in rs])), 1),
        )
print("\n=== COUNTERFACTUALS (authoritative planner) per candidate")
print(
    f"{'seed':>4} {'candidate':34s} {'basis':22s} base_ok/fail  cfAnchor_ok/fail (moved, cert min)   cfRamp_ok/fail (shift, rampClearOk)"
)
for r in J["candidates"]:
    if "error" in r:
        continue
    cf = r["counterfactual"]
    b = cf["baseline"]
    ca = cf["cfAnchorAtSharedSeparation"]
    cr = cf["cfRampAtSharedSeparation"]
    print(
        f"{r['seed']:>4} {r['candidateId']:34s} {r['basis']:22s} {b['okCount']:2d}/{b['failedCount']:<2d}        {ca['okCount']:2d}/{ca['failedCount']:<2d} ({ca['anchorsMoved']}, {min(ca['movedAnchorCertifiedClearance']) if ca['movedAnchorCertifiedClearance'] else '-'})        "
        + (
            f"{cr['okCount']:2d}/{cr['failedCount']:<2d} ({cr['shiftNorm']}, {cr['shiftedRampClearanceOk']})"
            if "okCount" in cr
            else str(cr.get("skipped"))
        )
        + f"   [{r['role']} {r['status']}]"
    )
print("\n=== POPULATION B clusters:", len(A["clusters"]))
for r in A["clusters"]:
    if "error" in r:
        print("ERR", r)
        continue
    cl = r["clusters"]
    ws = [c["worstSample"] for c in cl]
    print(
        f"{r['seed']} {r['candidateId']:34s} {r['family']:10s} {r['basis']:22s} clusters {len(cl)} | trueBelowReq {sum(w['trueBelowRequired'] for w in ws)}/{len(ws)} | effBound p50 {np.median([w['effectiveBound'] for w in ws]):.1f} | distTrack p50 {np.median([w['distToTrackEdge'] for w in ws]):.1f} | localOffset in {r['offsetStats']['inClusterMean']} out {r['offsetStats']['outsideClusterOnCorridorMean']} p90out {r['offsetStats']['outsideClusterOnCorridorP90']} | rank {r['rankTest']} | predictedFix {sum(c['predictedIfCorridorAtStandoffFromLocalContact']['satisfied'] for c in cl)}/{len(cl)}"
    )

print("\n=== §7 PER-REASON DECOMPOSITION (Population A failed levels, LA seeds)")
for reason in (
    "GRADE_LIMIT",
    "CONNECTOR_UNAVAILABLE",
    "INSUFFICIENT_RAMP_PILLAR",
    "TURNOUT_NOT_STRAIGHT",
):
    rs = [x for x in failed if x["reported"] == reason]
    if not rs:
        print(f"  {reason}: 0 levels")
        continue
    sepb = sum(1 for x in rs if x["binding"] == "SEPARATION_BOUND")
    mixed = sum(1 for x in rs if x["binding"].startswith("MIXED"))
    nogf = sum(1 for x in rs if x["binding"] == "NO_GRADE_FEASIBLE_JUNCTION")
    near = np.array([x["near"] for x in rs if x["near"] is not None])
    print(
        f"  {reason}: {len(rs)} levels | binding SEPARATION_BOUND {sepb} ({sepb / len(rs):.0%}), MIXED(sep+turnout) {mixed}, NO_GRADE_FEASIBLE {nogf} | nearest approach < 30 m: {np.mean(near < 30):.0%} (p50 {np.median(near):.1f} m) | analytic shared-ref prediction OK: {sum(1 for x in rs if x['pred'] == 'PREDICTED_OK')}/{len(rs)}"
    )
print("\n=== COUNTERFACTUAL LEVEL FLIPS (LA seeds)")
tot = collections.Counter()
for r in J["candidates"]:
    if "error" in r or r["role"] != "LA":
        continue
    cf = r["counterfactual"]
    b = cf["baseline"]["perLevel"]
    for name in ("cfAnchorAtSharedSeparation", "cfRampAtSharedSeparation"):
        c = cf[name]
        if "perLevel" not in c:
            continue
        for lv, res0 in b.items():
            res1 = c["perLevel"].get(lv)
            if res0 != "OK" and res1 == "OK":
                tot[(name, "fixed")] += 1
            elif res0 == "OK" and res1 != "OK":
                tot[(name, "broken")] += 1
            elif res0 != "OK":
                tot[(name, "stillFailed")] += 1
        tot[(name, "candidatesFeasible")] += int(c["feasible"])
    tot[("baseline", "candidatesFeasible")] += int(cf["baseline"]["feasible"])
for k, v in sorted(tot.items()):
    print("  ", k, v)
print("\n=== POPULATION B fit summary")
fit = collections.Counter()
for r in A["clusters"]:
    if "error" in r:
        continue
    rt = r["rankTest"] or {}
    f = rt.get("fractionOfClusterSamplesAboveP80", 0)
    g = rt.get("fractionOfNonClusterCorridorSamplesAboveP80", 1)
    ok = f >= 0.9 and g <= 0.25
    fit[(r["family"], "FITS" if ok else "DOES_NOT_FIT")] += 1
    if not ok:
        print("   non-fit:", r["seed"], r["candidateId"], rt, r["offsetStats"])
print("  ", dict(fit))
tb = [
    c["worstSample"]["trueBelowRequired"]
    for r in A["clusters"]
    if "clusters" in r
    for c in r["clusters"]
]
print(
    "   clusters total",
    len(tb),
    "| true clearance below required at worst sample:",
    sum(tb),
    "| certified-only deficits:",
    len(tb) - sum(tb),
)
