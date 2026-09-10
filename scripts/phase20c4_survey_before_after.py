# ruff: noqa: E501, SIM115  # diagnostic script (not production)
"""Phase 20C.4 Gate D — before / after comparison of two WARPED 32-seed
layout-v2 surveys (``python -m minegen.regression warped-seeds``), mirroring
``phase20c2a_warped_seed_before_after.json``.

usage: python scripts/phase20c4_survey_before_after.py BEFORE.json AFTER.json LABEL OUT.json

Diagnostic only: no threshold, coefficient or gate is changed to move these
numbers; every per-seed difference is listed, winner changes included.
"""

import json
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

COMPARED_FIELDS = (
    "status",
    "winnerId",
    "winnerFamily",
    "detailedFeasibleCount",
    "detailedCount",
    "cheapFeasibleCount",
    "bestAccessibleLevels",
    "winnerAccessibleLevels",
    "bestConservativeClearance",
    "dominantFailure",
    "dominantLevelAccessFailure",
)


def _rows(report: dict) -> dict[int, dict]:
    return {int(r["seed"]): r for r in report["rows"]}


def _hist(rows: dict[int, dict], key: str) -> dict[str, int]:
    c: Counter[str] = Counter()
    for r in rows.values():
        v = r.get(key)
        if isinstance(v, dict):
            c.update({k: int(n) for k, n in v.items()})
        elif v is not None:
            c[str(v)] += 1
    return dict(sorted(c.items()))


before_path, after_path, label, out_path = sys.argv[1:5]
before = json.load(open(before_path))
after = json.load(open(after_path))
rb, ra = _rows(before), _rows(after)
seeds = sorted(set(rb) & set(ra))
changed: list[dict] = []
per_seed: list[dict] = []
flips: Counter[str] = Counter()
identical = 0
for seed in seeds:
    b, a = rb[seed], ra[seed]
    diffs = {}
    for k in COMPARED_FIELDS:
        if b.get(k) != a.get(k):
            diffs[k] = {"before": b.get(k), "after": a.get(k)}
    per_seed.append(
        {
            "seed": seed,
            "layoutBefore": b.get("status"),
            "layoutAfter": a.get("status"),
            "winnerBefore": b.get("winnerId"),
            "winnerAfter": a.get("winnerId"),
            "feasibleBefore": b.get("detailedFeasibleCount"),
            "feasibleAfter": a.get("detailedFeasibleCount"),
        }
    )
    if b.get("status") != a.get("status"):
        flips[f"{b.get('status')}->{a.get('status')}"] += 1
    if diffs:
        changed.append({"seed": seed, "diffs": diffs})
    else:
        identical += 1
out = {
    "label": label,
    "baselineLabel": before.get("label"),
    "currentLabel": after.get("label"),
    "baselineGitHead": before.get("gitHead"),
    "currentGitHead": after.get("gitHead"),
    "seedCount": len(seeds),
    "seeds": seeds,
    "semantics": (
        "Phase 20C.4 Gate D: fixed 32-seed RANDOM_WARPED_VEIN survey (301-332), the "
        "20C.2A / 20C.3A baseline tree vs the Gate C tree (construction ServiceReference "
        "read by the SPIRAL and SWITCHBACK corridors; LONGITUDINAL, gates, thresholds, "
        "scores and the screen unchanged). Diagnostic only: no threshold, coefficient or "
        "gate was changed to move these numbers; winner changes are listed, never hidden."
    ),
    "layout": {
        "successCountBefore": sum(1 for r in rb.values() if r.get("status") == "SUCCESS"),
        "successCountAfter": sum(1 for r in ra.values() if r.get("status") == "SUCCESS"),
        "statusFlips": dict(flips),
        "identicalSeeds": identical,
        "changedSeeds": changed,
        "dominantFailureHistogramBefore": _hist(rb, "dominantFailure"),
        "dominantFailureHistogramAfter": _hist(ra, "dominantFailure"),
        "levelAccessFailureReasonsBefore": _hist(rb, "levelAccessFailureReasons"),
        "levelAccessFailureReasonsAfter": _hist(ra, "levelAccessFailureReasons"),
        "feasibleCandidatesBefore": sum(
            int(r.get("detailedFeasibleCount") or 0) for r in rb.values()
        ),
        "feasibleCandidatesAfter": sum(
            int(r.get("detailedFeasibleCount") or 0) for r in ra.values()
        ),
        "winnerFamilyBefore": _hist(rb, "winnerFamily"),
        "winnerFamilyAfter": _hist(ra, "winnerFamily"),
        "runtimeSecondsBefore": before.get("totalRuntimeSeconds"),
        "runtimeSecondsAfter": after.get("totalRuntimeSeconds"),
        "runtimeNote": "wall-clock only (observation, not a gate)",
    },
    "perSeed": per_seed,
}
Path(out_path).write_text(json.dumps(out, indent=1))
lay = out["layout"]
print(
    f"success {lay['successCountBefore']} -> {lay['successCountAfter']} | flips {lay['statusFlips']} | "
    f"identical {identical} | changed {len(changed)} | feasible candidates "
    f"{lay['feasibleCandidatesBefore']} -> {lay['feasibleCandidatesAfter']}"
)
for row in per_seed:
    if row["layoutBefore"] != row["layoutAfter"] or row["winnerBefore"] != row["winnerAfter"]:
        print(
            f"  {row['seed']}: {row['layoutBefore']} -> {row['layoutAfter']}  winner "
            f"{row['winnerBefore']} -> {row['winnerAfter']}  feasible "
            f"{row['feasibleBefore']} -> {row['feasibleAfter']}"
        )
