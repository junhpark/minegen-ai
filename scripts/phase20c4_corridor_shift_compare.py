# ruff: noqa: E501, SIM115, RUF001, E731  # diagnostic script (not production)
"""Phase 20C.4 follow-up — compare two ``phase20c4_corridor_shift.py`` dumps
(925ce25 double-band tree vs the derived-window tree): per seed and per
candidate, how much LESS (or more) the corridor moved after the fix.

usage: python scripts/phase20c4_corridor_shift_compare.py BEFORE.json AFTER.json OUT.json

``maxDelta`` is the candidate's maximum outward corridor correction; for a
SWITCHBACK the per-level ``deltas`` are the window profile at the level
planes (after) / the band-max profile (before). Diagnostic only.
"""

import json
import sys
from pathlib import Path

before = json.load(open(sys.argv[1]))
after = json.load(open(sys.argv[2]))
out_path = Path(sys.argv[3])
rb = {r["seed"]: r for r in before["rows"]}
ra = {r["seed"]: r for r in after["rows"]}
per_seed = []
for seed in sorted(set(rb) & set(ra)):
    b, a = rb[seed], ra[seed]
    if not (b.get("realized") and a.get("realized")):
        per_seed.append({"seed": seed, "realized": False})
        continue
    cb = {c["candidateId"]: c for c in b["candidates"]}
    ca = {c["candidateId"]: c for c in a["candidates"]}
    cands = []
    for cid in sorted(set(cb) | set(ca)):
        x, y = cb.get(cid), ca.get(cid)
        mb = (x or {}).get("corridorCorrection") or {}
        ma = (y or {}).get("corridorCorrection") or {}
        mdb = mb.get("maxDelta") if mb.get("active") else (0.0 if x and x["constructed"] else None)
        mda = ma.get("maxDelta") if ma.get("active") else (0.0 if y and y["constructed"] else None)
        cands.append(
            {
                "candidateId": cid,
                "family": (x or y)["family"],
                "statusBefore": x["status"] if x else None,
                "statusAfter": y["status"] if y else None,
                "maxDeltaBefore": mdb,
                "maxDeltaAfter": mda,
                "movedLessBy": (mdb - mda) if (mdb is not None and mda is not None) else None,
                "shortlistedBefore": bool(x and x.get("shortlisted")),
                "shortlistedAfter": bool(y and y.get("shortlisted")),
            }
        )
    sw = [c for c in cands if c["family"] == "SWITCHBACK" and c["movedLessBy"] is not None]
    sp = [c for c in cands if c["family"] == "SPIRAL" and c["movedLessBy"] is not None]
    win_a = ca.get(a["winnerId"]) if a.get("winnerId") else None
    win_b = cb.get(b["winnerId"]) if b.get("winnerId") else None

    def _md(c):
        m = (c or {}).get("corridorCorrection") or {}
        return m.get("maxDelta") if m.get("active") else (0.0 if c and c["constructed"] else None)

    per_seed.append(
        {
            "seed": seed,
            "realized": True,
            "statusBefore": b["status"],
            "statusAfter": a["status"],
            "winnerBefore": b.get("winnerId"),
            "winnerAfter": a.get("winnerId"),
            "winnerMaxDeltaBefore": _md(win_b),
            "winnerMaxDeltaAfter": _md(win_a),
            "winnerAfterMaxDeltaBefore": _md(cb.get(a["winnerId"])) if a.get("winnerId") else None,
            "switchbackMovedLessBy": {
                "count": len(sw),
                "mean": (sum(c["movedLessBy"] for c in sw) / len(sw)) if sw else None,
                "min": min((c["movedLessBy"] for c in sw), default=None),
                "max": max((c["movedLessBy"] for c in sw), default=None),
                "largest": max(sw, key=lambda c: c["movedLessBy"])["candidateId"] if sw else None,
            },
            "spiralMaxAbsChange": max((abs(c["movedLessBy"]) for c in sp), default=None),
            "feasibleBefore": sum(1 for c in cb.values() if c["status"] == "FEASIBLE"),
            "feasibleAfter": sum(1 for c in ca.values() if c["status"] == "FEASIBLE"),
            # only candidates constructed in at least one tree carry a corridor
            "candidates": [
                c
                for c in cands
                if c["movedLessBy"] is not None
                or c["maxDeltaBefore"] is not None
                or c["maxDeltaAfter"] is not None
            ],
        }
    )
out = {
    "artifact": "phase20c4_corridor_shift_before_after",
    "beforeGitHead": before["gitHead"],
    "afterGitHead": after["gitHead"],
    "semantics": (
        "Per-seed, per-candidate maximum corridor correction (maxDelta) of the 925ce25 "
        "double-band SWITCHBACK consumption vs the derived pair window. movedLessBy = "
        "before − after (positive: the corridor moves less far outward after the fix). "
        "SPIRAL corridors are unchanged by construction (spiralMaxAbsChange is expected 0). "
        "Diagnostic only; nothing tuned."
    ),
    "perSeed": per_seed,
}
out_path.write_text(json.dumps(out, indent=1))
print(
    f"{'seed':>5} {'before':>12} {'after':>12} {'winner before -> after':<62} {'SB movedLess mean/min/max':>28} spiral|Δ|"
)
for r in per_seed:
    if not r["realized"]:
        print(f"{r['seed']:>5}  NOT REALIZED")
        continue
    m = r["switchbackMovedLessBy"]
    fmt = lambda v: "-" if v is None else f"{v:.1f}"
    print(
        f"{r['seed']:>5} {r['statusBefore'][:12]:>12} {r['statusAfter'][:12]:>12} "
        f"{str(r['winnerBefore']) + ' -> ' + str(r['winnerAfter']):<62} "
        f"{fmt(m['mean']):>8}/{fmt(m['min']):>8}/{fmt(m['max']):>8} {fmt(r['spiralMaxAbsChange']):>6}"
    )
