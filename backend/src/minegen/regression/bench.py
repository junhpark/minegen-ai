"""Performance measurements for the Phase 18 field migration (rule 128).

Uses ONLY APIs that exist on both sides of the migration so the same script
produces the before / after numbers:

    world       generate_world(BASELINE)                 (default 1200×1200×600 m, 10 m)
    sampling    DesignCostEvaluator.rock_quality(N×3)    (N = 1,000,000 random points)
    evaluate    DesignCostEvaluator.evaluate_points(N×3) (N = 200,000)
    decline     targets + chained Hybrid-A* decline, BASELINE seed 42

    python -m minegen.regression.bench [--repeat 3] [--skip-decline]
"""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np

from minegen.core.enums import ScenarioPreset
from minegen.core.models import Scenario
from minegen.design.cost_field import DesignCostEvaluator
from minegen.services.design_service import DesignService
from minegen.services.scenario_realizer import realize_scenario
from minegen.services.scenario_service import ScenarioStore
from minegen.services.world_service import WorldService
from minegen.world.synthetic_world import generate_world


def _timeit(fn: Any, repeat: int) -> dict[str, float]:
    times: list[float] = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return {"min": min(times), "median": statistics.median(times), "max": max(times)}


def run(repeat: int = 3, skip_decline: bool = False) -> dict[str, Any]:
    scenario = Scenario(**realize_scenario(ScenarioPreset.BASELINE, 42).model_dump())
    out: dict[str, Any] = {"repeat": repeat}

    out["worldGenerationSeconds"] = _timeit(lambda: generate_world(scenario), repeat)
    world = generate_world(scenario)
    ev = DesignCostEvaluator(world, scenario.design)

    rng = np.random.default_rng(0)
    lo = np.array([-600.0, -600.0, -300.0])
    hi = np.array([600.0, 600.0, 400.0])
    pts = rng.uniform(lo, hi, size=(1_000_000, 3))
    ev.rock_quality(pts[:1000])  # warm-up (lazy dense view)
    t = _timeit(lambda: ev.rock_quality(pts), repeat)
    out["rockQualitySampling1M"] = {**t, "pointsPerSecond": 1_000_000 / t["median"]}

    pts2 = pts[:200_000]
    t = _timeit(lambda: ev.evaluate_points(pts2), repeat)
    out["evaluatePoints200k"] = {**t, "pointsPerSecond": 200_000 / t["median"]}

    if not skip_decline:
        root = Path(tempfile.mkdtemp(prefix="minegen-bench-"))
        store = ScenarioStore(root)
        worlds = WorldService(store)
        design = DesignService(store, worlds)
        sid = store.create(scenario).id
        worlds.generate(sid)
        design.generate_targets(sid)
        t0 = time.perf_counter()
        decline = design.generate_decline(sid)
        out["declineSeconds"] = time.perf_counter() - t0
        out["declineStatus"] = decline["status"]
        out["declineExpandedStates"] = decline["totals"]["expandedStates"]
        out["declineRawLength"] = decline["totals"]["rawLength"]
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m minegen.regression.bench")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--skip-decline", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    result = run(args.repeat, args.skip_decline)
    text = json.dumps(result, indent=2)
    print(text)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
