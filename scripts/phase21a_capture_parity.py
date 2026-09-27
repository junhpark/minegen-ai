"""Write ``backend/tests/fixtures/phase21a/longhole_parity.json`` from the
CURRENT code. Run ONCE on the pre-migration HEAD (recorded in ``metadata``);
``backend/tests/test_mining_method_parity.py`` compares the migrated code
against it. Never re-run to make a failing parity test pass (Phase 21A
directive §14).

    cd backend && .venv/bin/python ../scripts/phase21a_capture_parity.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from tests.conftest import small_scenario  # noqa: E402
from tests.phase21a_parity_support import (  # noqa: E402
    layout_chain,
    legacy_chain,
    reduce,
    with_method,
)

from minegen.core.enums import MiningMethodType, ScenarioPreset  # noqa: E402
from minegen.core.models import Scenario, ScenarioCreate  # noqa: E402
from minegen.services.scenario_realizer import realize_scenario  # noqa: E402
from minegen.world.synthetic_world import generate_world  # noqa: E402

OUT = BACKEND / "tests" / "fixtures" / "phase21a" / "longhole_parity.json"
#: the ONLY HEAD this baseline may be captured on (tests/test_mining_method_parity.py
#: pins the same value). Running anywhere else is refused: a new baseline is an
#: explicit, reviewed decision, never a re-run.
PRE_MIGRATION_HEAD = "39c293e71790b6ec490275a24bb8735631334e4e"


def main() -> None:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    if head != PRE_MIGRATION_HEAD:
        raise SystemExit(
            f"refusing to capture the longhole parity baseline on {head}: it is pinned to the "
            f"pre-migration HEAD {PRE_MIGRATION_HEAD} (edit PRE_MIGRATION_HEAD here AND in "
            "tests/test_mining_method_parity.py only as an explicit, reviewed baseline change)"
        )
    # the legacy chain uses the DEFAULT scenario exactly as tests/test_stopes.py
    # does (three synthetic Phase 05 segments → 2 intervals × 17 stations)
    dsc = Scenario(**ScenarioCreate(name="phase21a-default").model_dump())
    dworld = generate_world(dsc)
    sc = small_scenario()
    world = generate_world(sc)
    cases = {
        "TABULAR_LEGACY": reduce(legacy_chain(dsc, dworld, (60.0, 35.0, 10.0))),
        "TABULAR_LAYOUT": reduce(layout_chain(sc, world)),
        "CUT_AND_FILL": reduce(layout_chain(with_method(sc, MiningMethodType.CUT_AND_FILL), world)),
    }
    wsc = Scenario(
        **realize_scenario(ScenarioPreset.RANDOM_WARPED_VEIN, 301, fault_count=1).model_dump()
    )
    wworld = generate_world(wsc)
    cases["WARPED_LONGHOLE"] = reduce(layout_chain(wsc, wworld))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {"metadata": {"capturedAtHead": head, "phase": "21A pre-migration"}, "cases": cases},
            indent=1,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    for name, case in cases.items():
        print(
            name,
            "levels",
            case["levels"]["status"],
            case["levelsDigest"][:12],
            "stopes",
            case["stopes"].get("status", case["stopes"].get("typedBoundary")),
            case["stopesDigest"][:12],
        )
    print("wrote", OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
