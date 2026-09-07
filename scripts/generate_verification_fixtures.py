#!/usr/bin/env python
"""Generate the cached VERIFICATION fixtures under
backend/tests/fixtures/verification/ (VA-01 §21–24).

The fixtures are development acceleration for the FAST inner loop, never
release authority: FULL regenerates the same upstream artifacts CLEANLY and
compares the content fingerprint (tests/test_verification_fixtures_fresh.py).
Never edit a fixture by hand — rerun this generator.

Run from the repository root:
    cd backend && PYTHONPATH=src:. .venv/bin/python ../scripts/generate_verification_fixtures.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND / "src"))
sys.path.insert(0, str(BACKEND))

from tests.conftest import small_scenario  # noqa: E402
from tests.verification_support import (  # noqa: E402
    FIXTURE_DIR,
    FIXTURE_SCHEMA_VERSION,
    digest,
    selection_fingerprint,
)
from tests.warped_sections_summary import warped_sections_summary  # noqa: E402

from minegen.core.enums import ScenarioPreset  # noqa: E402
from minegen.core.models import Scenario  # noqa: E402
from minegen.layout.search import (  # noqa: E402
    LayoutV2Search,
    materialize_effective_ramp,
    materialize_level_accesses,
)
from minegen.services.scenario_realizer import realize_scenario  # noqa: E402
from minegen.world.synthetic_world import generate_world  # noqa: E402

FIXTURE_VERSION = 1
REV = "verification-fixture"


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:  # pragma: no cover - git absent
        return "unknown"


def _meta(
    source_stage: str, fingerprint: str, preset: str, seed: int, fault_count: int | None
) -> dict:
    return {
        "fixtureVersion": FIXTURE_VERSION,
        "schemaVersion": FIXTURE_SCHEMA_VERSION,
        "scenarioPreset": preset,
        "seed": seed,
        "faultCount": fault_count,
        "sourceStage": source_stage,
        "generatedFromGitSha": _git_sha(),
        "generatedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "upstreamFingerprint": fingerprint,
        "authority": "DEVELOPMENT_ACCELERATION_ONLY — never release evidence (VA-01 §20)",
    }


def tabular_small_selected() -> dict:
    """Small TABULAR scenario (tests.conftest.small_scenario): the selected
    layout-v2 winner materialized as Effective Ramp + level accesses. The
    FAST canary starts DOWNSTREAM of the search (levels → network)."""
    sc = small_scenario()
    world = generate_world(sc)
    search = LayoutV2Search(sc, world)
    res = search.run()
    assert res.winner_id is not None, "small TABULAR scenario must have a layout-v2 winner"
    winner = res.candidate(res.winner_id)
    assert winner is not None
    ramp = materialize_effective_ramp(res, winner, search.evaluator, REV)
    accesses = materialize_level_accesses(res, winner, REV, sc.mining.method.value)
    fp = selection_fingerprint(ramp, accesses)
    return {
        "metadata": _meta("LAYOUT_V2_SELECTED", fp, "tests.conftest.small_scenario", sc.seed, 1),
        "scenario": sc.model_dump(mode="json", by_alias=True),
        "winnerId": res.winner_id,
        "effectiveRamp": ramp,
        "levelAccesses": accesses,
    }


def warped_301_sections() -> dict:
    """WARPED-301 section(z) geometry + footwall/offset traces under the WORLD
    clearance policy — no layout search. The FAST canary recomputes the same
    summary and pins it (regression detector for the A1/A2 layers)."""
    sc = Scenario(
        **realize_scenario(ScenarioPreset.RANDOM_WARPED_VEIN, 301, fault_count=1).model_dump()
    )
    world = generate_world(sc)
    summary = warped_sections_summary(sc, world)
    return {
        "metadata": _meta(
            "SECTION_TRACES_WORLD_POLICY", digest(summary), "RANDOM_WARPED_VEIN", 301, 1
        ),
        "summary": summary,
    }


def main() -> int:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for name, builder in (
        ("tabular_small_selected", tabular_small_selected),
        ("warped_301_sections", warped_301_sections),
    ):
        data = builder()
        path = FIXTURE_DIR / f"{name}.json"
        path.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        print(
            f"wrote {path.relative_to(ROOT)} "
            f"fingerprint={data['metadata']['upstreamFingerprint'][:12]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
