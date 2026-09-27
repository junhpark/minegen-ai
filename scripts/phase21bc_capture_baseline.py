"""Capture the Phase 21B/C Longhole baseline (directive §39) on the PINNED
pre-migration HEAD. Run ONCE:

    cd backend && .venv/bin/python ../scripts/phase21bc_capture_baseline.py

Refuses any other HEAD: a new baseline is an explicit, reviewed decision.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "src"))

from tests.conftest import small_scenario  # noqa: E402
from tests.phase21a_parity_support import legacy_chain, reduce  # noqa: E402
from tests.phase21bc_baseline_support import (  # noqa: E402
    layout_full_chain,
    legacy_welded_chain,
    reduce_full,
)

from minegen.core.enums import ScenarioPreset  # noqa: E402
from minegen.core.models import Scenario, ScenarioCreate  # noqa: E402
from minegen.services.scenario_realizer import realize_scenario  # noqa: E402
from minegen.world.synthetic_world import generate_world  # noqa: E402

OUT = BACKEND / "tests" / "fixtures" / "phase21bc" / "longhole_baseline.json"
#: PR #46 merge commit — the ONLY HEAD this baseline may be captured on
#: (tests/test_longhole_baseline_21bc.py pins the same value)
PRE_MIGRATION_HEAD = "70526063e3a61cda41af283ac7fa578ba0805d77"


def main() -> None:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    if head != PRE_MIGRATION_HEAD:
        raise SystemExit(
            f"refusing to capture the 21B/C longhole baseline on {head}: pinned to "
            f"{PRE_MIGRATION_HEAD} (edit PRE_MIGRATION_HEAD here AND in "
            "tests/test_longhole_baseline_21bc.py only as an explicit, reviewed change)"
        )
    dsc = Scenario(**ScenarioCreate(name="phase21bc-default").model_dump())
    dworld = generate_world(dsc)
    sc = small_scenario()
    world = generate_world(sc)
    cases = {
        "LEGACY_DEFAULT": reduce(legacy_chain(dsc, dworld, (60.0, 35.0, 10.0))),
        # the tests.test_timeline._chain construction: DEFAULT scenario (the
        # small one fails a legacy crosscut terminal gate, as test_stopes notes)
        "LEGACY_WELDED": reduce_full(
            legacy_welded_chain(dsc, dworld, [(25.0, 60.0), (25.0, 35.0), (25.0, 10.0)])
        ),
        "LAYOUT_SMALL": reduce_full(layout_full_chain(sc, world)),
    }
    wsc = Scenario(
        **realize_scenario(ScenarioPreset.RANDOM_WARPED_VEIN, 301, fault_count=1).model_dump()
    )
    cases["WARPED_LONGHOLE"] = reduce_full(layout_full_chain(wsc, generate_world(wsc)))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {"metadata": {"capturedAtHead": head, "phase": "21B/C pre-migration"}, "cases": cases},
            indent=1,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    for name, case in cases.items():
        st = case["stopes"]
        print(
            name,
            case["levels"]["status"],
            st.get("status", st.get("typedBoundary")),
            case.get("timeline", {}).get("status", "-"),
        )
    print("wrote", OUT)


if __name__ == "__main__":
    main()
