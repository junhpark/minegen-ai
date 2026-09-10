# ruff: noqa: E501, SIM115  # diagnostic script (not production)
"""Phase 20C.4 Gate D — controlled comparison of the committed 20C.3A failure
census (``backend/golden/phase20c3a_failure_census.json``, the historical
diagnostic baseline) with a re-run of the SAME census script on the SAME 13
NO_FEASIBLE seeds under the Gate C tree.

usage: python scripts/phase20c4_census_before_after.py AFTER_RAW.json OUT.json

The raw re-run classes are mapped onto the census population names exactly
as the 20C.3A closeout did (one-to-one); FEASIBLE is the new after-state of
a DETAILED candidate. PHYSICALLY_LOCAL_REPAIRABLE (the closeout's physical
sub-check of LOCAL_REPAIR_GEOMETRY_RULE) is not re-derived here — that
population is out of the 20C.4 scope. Diagnostic only: no threshold,
coefficient or gate was changed to move these numbers; the census is never
an optimization target.
"""

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
GOLDEN = _ROOT / "backend" / "golden" / "phase20c3a_failure_census.json"

CLASS_TO_POPULATION = {
    "LEVEL_ACCESS_PROBLEM": "LEVEL_ACCESS_PROBLEM",
    "FAMILY_CONSTRUCTION_PROBLEM:PORTAL_APPROACH": "PORTAL_APPROACH",
    "OTHER_NON_REPAIRABLE:MULTI_CLUSTER": "MULTI_CLUSTER_CLEARANCE",
    "GLOBAL_GEOMETRY_PROBLEM:SPAN": "FIRST_LEG_GLOBAL_ABOVE_TERRAIN",
    "LOCAL_REPAIR_CANDIDATE": "LOCAL_REPAIR_GEOMETRY_RULE",
    "PORTAL_ARTIFACT_ONLY": "PORTAL_ARTIFACT_ONLY",
    "FEASIBLE": "FEASIBLE",
}

after_raw = json.load(open(sys.argv[1]))
out_path = Path(sys.argv[2])
golden = json.load(open(GOLDEN))
census_seeds = [int(s) for s in golden["censusSeeds"]]
before_seed = {int(r["seed"]): r for r in golden["perSeed"] if int(r["seed"]) in census_seeds}
after_seed = {int(r["seed"]): r for r in after_raw["seeds"]}
before_cand = {(int(c["seed"]), c["candidateId"]): c for c in golden["perCandidate"]}
after_cand = {(int(c["seed"]), c["candidateId"]): c for c in after_raw["candidates"]}
unknown = sorted({c["class"] for c in after_raw["candidates"]} - set(CLASS_TO_POPULATION))
if unknown:
    raise SystemExit(f"unmapped raw classes: {unknown}")

per_seed = []
for seed in census_seeds:
    b, a = before_seed[seed], after_seed.get(seed)
    per_seed.append(
        {
            "seed": seed,
            "before": b["result"],
            "after": a["status"] if a else None,
            "detailedBefore": b["detailedCandidates"],
            "detailedAfter": a["detailed"] if a else None,
            "feasibleBefore": b["detailedFeasible"],
            "feasibleAfter": a["feasible"] if a else None,
            "serviceableLevels": b["serviceableLevels"],
        }
    )
pop_before = Counter(c["classification"] for c in before_cand.values())
pop_after = Counter(CLASS_TO_POPULATION[c["class"]] for c in after_cand.values())
transitions: Counter[str] = Counter()
per_candidate = []
for key, b in sorted(before_cand.items()):
    a = after_cand.get(key)
    after_pop = CLASS_TO_POPULATION[a["class"]] if a else "NOT_DETAILED"
    transitions[f"{b['classification']}->{after_pop}"] += 1
    per_candidate.append(
        {
            "seed": key[0],
            "candidateId": key[1],
            "family": b["family"],
            "before": b["classification"],
            "after": after_pop,
            "afterStatus": a["status"] if a else None,
            "afterFailureReasons": a.get("failureReasons") if a else None,
        }
    )
new_detailed = sorted(set(after_cand) - set(before_cand))
new_after = Counter(CLASS_TO_POPULATION[after_cand[k]["class"]] for k in new_detailed)
out = {
    "artifact": "phase20c4_census_before_after",
    "gate": "D",
    "auditType": "CONTROLLED_COMPARISON_VS_20C3A_CENSUS",
    "baseline": {
        "artifact": golden["artifact"],
        "baselineGitSha": golden["baselineGitSha"],
        "censusSeeds": census_seeds,
        "detailedCandidates": len(before_cand),
        "populations": dict(pop_before),
    },
    "current": {
        "gitSha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=_ROOT).decode().strip(),
        "detailedCandidates": len(after_cand),
        "populations": dict(pop_after),
        "seedsSuccess": sum(1 for r in per_seed if r["after"] == "SUCCESS"),
        "seedsNoFeasible": sum(1 for r in per_seed if r["after"] == "NO_FEASIBLE"),
    },
    "classToPopulation": CLASS_TO_POPULATION,
    "semantics": (
        "The 13 NO_FEASIBLE seeds of the 20C.3A census re-run with the SAME census "
        "script under the Gate C tree (construction ServiceReference read by the SPIRAL "
        "and SWITCHBACK corridors). Per-candidate transitions are reported for every "
        "baseline DETAILED candidate (NOT_DETAILED = no longer in the shortlist); "
        "candidates DETAILED only now are listed separately. The census is a historical "
        "diagnostic baseline, never an optimization target; no threshold, coefficient or "
        "gate was changed to move these numbers. PHYSICALLY_LOCAL_REPAIRABLE is not re-derived."
    ),
    "perSeed": per_seed,
    "transitions": dict(sorted(transitions.items())),
    "newlyDetailed": {"count": len(new_detailed), "populations": dict(new_after)},
    "perCandidate": per_candidate,
}
out_path.write_text(json.dumps(out, indent=1))
print("seeds SUCCESS after:", out["current"]["seedsSuccess"], "/", len(census_seeds))
print("populations before:", dict(pop_before))
print("populations after :", dict(pop_after))
print("newly detailed    :", len(new_detailed), dict(new_after))
for k, v in sorted(transitions.items(), key=lambda kv: -kv[1]):
    print(f"  {v:3d}  {k}")
for r in per_seed:
    print(
        f"  {r['seed']}: {r['before']} -> {r['after']}  feasible {r['feasibleBefore']} -> {r['feasibleAfter']}"
    )
