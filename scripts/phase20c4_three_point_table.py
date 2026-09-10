# ruff: noqa: E501, SIM115, RUF001  # diagnostic script (not production)
"""Phase 20C.4 follow-up — three-time-point table of the WARPED 32-seed survey
and the 20C.3A failure census: 20C.2A baseline / 20C.4 at 925ce25 (double
± 2·drop band) / 20C.4 after the derived pair window.

usage: python scripts/phase20c4_three_point_table.py SURVEY_A SURVEY_B SURVEY_C CENSUS_A CENSUS_B CENSUS_C OUT.json

SURVEY_* are ``warped-seeds`` reports; CENSUS_A is the 20C.3A census golden
(``perCandidate[].classification``), CENSUS_B / CENSUS_C are
``phase20c4_census_before_after`` artifacts (``current.populations``).
Diagnostic only; nothing tuned.
"""

import json
import sys
from collections import Counter
from pathlib import Path

paths = [Path(p) for p in sys.argv[1:7]]
out_path = Path(sys.argv[7])
surveys = [json.load(open(p)) for p in paths[:3]]
censuses = [json.load(open(p)) for p in paths[3:6]]
labels = ["20C.2A", "20C.4 (925ce25)", "20C.4 after"]


def survey_rows(s: dict) -> dict[int, dict]:
    return {int(r["seed"]): r for r in s["rows"]}


def hist(rows: dict[int, dict], key: str) -> Counter:
    c: Counter = Counter()
    for r in rows.values():
        v = r.get(key)
        if isinstance(v, dict):
            c.update({k: int(n) for k, n in v.items()})
        elif v is not None:
            c[str(v)] += 1
    return c


def census_pops(c: dict) -> dict[str, int]:
    if "perCandidate" in c and "current" not in c:
        return dict(Counter(x["classification"] for x in c["perCandidate"]))
    return dict(c["current"]["populations"])


cols = []
for label, s, c in zip(labels, surveys, censuses, strict=True):
    rows = survey_rows(s)
    la = hist(rows, "levelAccessFailureReasons")
    pops = census_pops(c)
    fam = hist(rows, "winnerFamily")
    cols.append(
        {
            "label": label,
            "surveyGitHead": s.get("gitHead"),
            "censusGitSha": c.get("baselineGitSha") or c.get("current", {}).get("gitSha"),
            "success": sum(1 for r in rows.values() if r.get("status") == "SUCCESS"),
            "seedCount": len(rows),
            "levelAccessRejections": int(sum(la.values())),
            "levelAccessReasons": dict(sorted(la.items())),
            "censusLevelAccessProblem": int(pops.get("LEVEL_ACCESS_PROBLEM", 0)),
            "censusMultiClusterClearance": int(pops.get("MULTI_CLUSTER_CLEARANCE", 0)),
            "censusPortalApproach": int(pops.get("PORTAL_APPROACH", 0)),
            "censusFeasible": int(pops.get("FEASIBLE", 0)),
            "censusPopulations": pops,
            "winnerSwitchback": int(fam.get("SWITCHBACK", 0)),
            "winnerSpiral": int(fam.get("SPIRAL", 0)),
            "winnerLongitudinal": int(fam.get("LONGITUDINAL", 0)),
            "feasibleCandidates": int(
                sum(int(r.get("detailedFeasibleCount") or 0) for r in rows.values())
            ),
            "statuses": {str(k): r.get("status") for k, r in sorted(rows.items())},
            "winners": {str(k): r.get("winnerId") for k, r in sorted(rows.items())},
        }
    )


def flips(a: dict, b: dict) -> tuple[list[int], list[int]]:
    regressed = [
        int(k)
        for k in a["statuses"]
        if a["statuses"][k] == "SUCCESS" and b["statuses"].get(k) != "SUCCESS"
    ]
    recovered = [
        int(k)
        for k in a["statuses"]
        if a["statuses"][k] != "SUCCESS" and b["statuses"].get(k) == "SUCCESS"
    ]
    return regressed, recovered


r_ab, c_ab = flips(cols[0], cols[1])
r_bc, c_bc = flips(cols[1], cols[2])
r_ac, c_ac = flips(cols[0], cols[2])
winner_changes_bc = sorted(
    int(k) for k in cols[1]["winners"] if cols[1]["winners"][k] != cols[2]["winners"].get(k)
)
out = {
    "artifact": "phase20c4_followup_three_point",
    "columns": cols,
    "regressedSeeds": {"B_vs_A": r_ab, "C_vs_B": r_bc, "C_vs_A": r_ac},
    "recoveredSeeds": {"B_vs_A": c_ab, "C_vs_B": c_bc, "C_vs_A": c_ac},
    "winnerChangedSeeds_C_vs_B": winner_changes_bc,
    "semantics": (
        "Survey columns: fixed 32-seed RANDOM_WARPED_VEIN survey (301-332, fault_count 1). "
        "Census columns: the 13 NO_FEASIBLE seeds of the 20C.3A census (DETAILED candidates "
        "per population). Nothing was tuned to move these numbers; every seed status and "
        "winner is listed."
    ),
}
out_path.write_text(json.dumps(out, indent=1))
keys = [
    ("SUCCESS / 32", "success"),
    ("level-access rejections (survey)", "levelAccessRejections"),
    ("LEVEL_ACCESS_PROBLEM (census)", "censusLevelAccessProblem"),
    ("multi-cluster clearance (census)", "censusMultiClusterClearance"),
    ("PORTAL_APPROACH (census)", "censusPortalApproach"),
    ("FEASIBLE (census)", "censusFeasible"),
    ("winner SWITCHBACK", "winnerSwitchback"),
    ("winner SPIRAL", "winnerSpiral"),
    ("feasible candidates (survey)", "feasibleCandidates"),
]
print("| metric | " + " | ".join(labels) + " |")
print("|---|" + "---|" * 3)
for name, k in keys:
    print(f"| {name} | " + " | ".join(str(c[k]) for c in cols) + " |")
print(f"| regressed seeds (vs previous column) | – | {r_ab} | {r_bc} |")
print(f"| recovered seeds (vs previous column) | – | {c_ab} | {c_bc} |")
print(f"C vs A: regressed {r_ac} recovered {c_ac}; winner changed C vs B: {winner_changes_bc}")
