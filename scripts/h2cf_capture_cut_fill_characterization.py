"""Capture the Cut & Fill schedule CHARACTERIZATION of the small scenario
(hardening PR-2, H2-CF). Run from a checkout's root:

    backend/.venv/bin/python scripts/h2cf_capture_cut_fill_characterization.py <label> <out.json>

The summary is SHAPE-AGNOSTIC so the pre-H2-CF payload (no blocks / panels)
and the H2-CF payload can be compared side by side: counts, timeline
milestones, PREP dependency categories, the dependency-graph digest, the
observed concurrency and the cure durations. ``tests/test_cut_fill_
characterization.py`` compares the current code with the committed
``after`` record; the ``before`` record (captured on the PR-2 baseline
1bd68c8) is the documented comparison input, never a gate.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "src"))

from tests.conftest import small_scenario  # noqa: E402
from tests.phase21a_parity_support import with_method  # noqa: E402
from tests.phase21bc_baseline_support import layout_full_chain  # noqa: E402

from minegen.core.enums import MiningMethodType  # noqa: E402
from minegen.world.synthetic_world import generate_world  # noqa: E402

PREP = "STOPE_PREPARATION"


def _digest(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()


def _max_overlap(windows: list[tuple[float, float]]) -> int:
    events = sorted([(s, 1) for s, _ in windows] + [(e, -1) for _, e in windows])
    best = cur = 0
    # ends before starts at equal day: a window [a, b) is closed at b
    for _, d in sorted(events, key=lambda x: (x[0], x[1])):
        cur += d
        best = max(best, cur)
    return best


def characterize(case: dict[str, Any]) -> dict[str, Any]:
    prod, tl, levels = case["stopes"], case["timeline"], case["levels"]
    tasks = {t["id"]: t for t in tl["tasks"]}
    by_target: dict[str, dict[str, dict[str, Any]]] = {}
    for t in tl["tasks"]:
        by_target.setdefault(t["targetId"], {})[t["taskType"]] = t
    prep_dep_kinds: dict[str, int] = {}
    for t in tl["tasks"]:
        if t["taskType"] != PREP:
            continue
        for dep in t["dependencies"]:
            kind = tasks[dep]["taskType"]
            prep_dep_kinds[kind] = prep_dep_kinds.get(kind, 0) + 1
    stoping_windows = [
        (t["startDay"], t["endDay"]) for t in tl["tasks"] if t["taskType"] == "STOPING"
    ]
    cut_windows = [
        (chain[PREP]["startDay"], chain["CURE_BACKFILL"]["endDay"])
        for target, chain in by_target.items()
        if PREP in chain and "CURE_BACKFILL" in chain
    ]
    panel_windows: list[tuple[float, float]] = []
    for panel in prod.get("panels", []):
        chains = [by_target[cid] for cid in panel["cutIds"]]
        panel_windows.append(
            (
                min(c[PREP]["startDay"] for c in chains),
                max(c["CURE_BACKFILL"]["endDay"] for c in chains),
            )
        )
    metrics = prod.get("metrics") or {}
    return {
        "scenario": "tests.conftest.small_scenario(seed 42) + CUT_AND_FILL canonical defaults",
        "levels": {
            "status": levels["status"],
            "levelCount": len(levels["levels"]),
            "crosscutCount": levels["metrics"]["crosscutCount"],
            "stationsPerLevel": levels["metrics"]["stationsPerLevel"],
        },
        "production": {
            "status": prod["status"],
            "cutCount": metrics.get("cutCount"),
            "backfillCount": metrics.get("backfillCount"),
            "liftCount": metrics.get("liftCount"),
            "levelIntervalCount": metrics.get("levelIntervalCount"),
            "blockCount": metrics.get("blockCount", 0),
            "panelCount": metrics.get("panelCount", 0),
            "ribPillarCount": metrics.get("ribPillarCount", 0),
            "cementedBackfillCount": metrics.get("cementedBackfillCount", 0),
            "totalGeometricVolumeM3": metrics.get("totalGeometricVolumeM3"),
            "totalTonnes": metrics.get("totalTonnes"),
            "cutIdDigest": _digest([c["id"] for c in prod["cuts"]]),
            "sequencing": {
                k: v
                for k, v in (prod.get("sequencing") or {}).items()
                if k not in ("panelStartOrder", "blockOrderIds")
            },
        },
        "timeline": {
            "status": tl["status"],
            "taskCount": tl["metrics"]["taskCount"],
            "productionTaskCount": tl["metrics"].get("productionTaskCount"),
            "rampCompletionDay": tl["metrics"]["rampCompletionDay"],
            "firstStopingDay": tl["metrics"]["firstStopingDay"],
            "endDay": tl["metrics"]["endDay"],
            "prepDependencyKinds": dict(sorted(prep_dep_kinds.items())),
            "maxConcurrentCuts": _max_overlap(cut_windows),
            "maxConcurrentStoping": _max_overlap(stoping_windows),
            "maxConcurrentPanels": _max_overlap(panel_windows) if panel_windows else None,
            "cureDurations": sorted(
                {t["durationDays"] for t in tl["tasks"] if t["taskType"] == "CURE_BACKFILL"}
            ),
            "dependencyDigest": _digest(
                [f"{t['id']}<-{d}" for t in tl["tasks"] for d in t["dependencies"]]
            ),
            "taskIdDigest": _digest(list(tasks)),
        },
    }


def main() -> None:
    label, out = sys.argv[1], Path(sys.argv[2])
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, cwd=ROOT
    ).stdout.strip()
    sc = with_method(small_scenario(), MiningMethodType.CUT_AND_FILL)
    case = layout_full_chain(sc, generate_world(sc))
    record = {"label": label, "generatedFromGitSha": sha, **characterize(case)}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out} ({label} @ {sha[:10]})")


if __name__ == "__main__":
    main()
