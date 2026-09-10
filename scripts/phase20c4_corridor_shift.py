# ruff: noqa: E501  # diagnostic script (not production)
"""Phase 20C.4 follow-up — per-seed, per-candidate corridor correction dump of
the WARPED 32-seed survey (301–332, fault_count 1), run under one tree; two
dumps (the 925ce25 double-band tree vs the derived-window tree) are compared
by ``phase20c4_corridor_shift_compare.py``.

usage: python scripts/phase20c4_corridor_shift.py OUT.json [SEEDS]

Diagnostic only: nothing is tuned; the search is the production search.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend" / "src"))

from minegen.core.enums import ScenarioPreset  # noqa: E402
from minegen.core.models import Scenario  # noqa: E402
from minegen.layout.search import LayoutV2Search  # noqa: E402
from minegen.services.scenario_realizer import realize_scenario  # noqa: E402
from minegen.world.synthetic_world import generate_world  # noqa: E402

out_path = Path(sys.argv[1])
seeds = [int(s) for s in sys.argv[2].split(",")] if len(sys.argv) > 2 else list(range(301, 333))
t0 = time.perf_counter()
rows = []
for seed in seeds:
    ts = time.perf_counter()
    try:
        sc = Scenario(
            **realize_scenario(ScenarioPreset.RANDOM_WARPED_VEIN, seed, fault_count=1).model_dump()
        )
    except Exception as exc:
        rows.append({"seed": seed, "realized": False, "error": str(exc)[:200]})
        continue
    world = generate_world(sc)
    res = LayoutV2Search(sc, world).run()
    cands = []
    for c in res.candidates:
        corr = (c.derived or {}).get("corridorCorrection") if c.derived else None
        cands.append(
            {
                "candidateId": c.candidate_id,
                "family": c.params.family.value,
                "status": str(c.status),
                "shortlisted": bool(c.shortlisted),
                "constructed": c.points is not None,
                "corridorCorrection": corr,
                "failureReasons": sorted({str(r) for r in (c.failure_reasons or [])})[:6],
                "totalScore": None if c.scores is None else c.scores.total,
            }
        )
    rows.append(
        {
            "seed": seed,
            "realized": True,
            "status": "SUCCESS" if res.winner_id is not None else "NO_FEASIBLE_CANDIDATE",
            "winnerId": res.winner_id,
            "seconds": time.perf_counter() - ts,
            "candidates": cands,
        }
    )
    print(
        f"  seed {seed}: {rows[-1]['status']} winner={res.winner_id} ({time.perf_counter() - ts:.1f} s)",
        flush=True,
    )
out = {
    "artifact": "phase20c4_corridor_shift_dump",
    "gitHead": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=_ROOT).decode().strip(),
    "seeds": seeds,
    "totalRuntimeSeconds": time.perf_counter() - t0,
    "rows": rows,
}
out_path.write_text(json.dumps(out, indent=1))
print("wrote", out_path)
