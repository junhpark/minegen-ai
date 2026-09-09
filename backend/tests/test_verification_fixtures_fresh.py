"""VA-01 §23–24: cached verification fixtures are validated against CLEAN
regeneration in FEATURE / FULL (marked canary; the TABULAR one is also
slow-by-fixture-cost). A mismatch is an explicit STALE VERIFICATION FIXTURE
failure of the verification infrastructure — the clean E2E result itself is
what FULL trusts — and is never auto-rewritten: regenerate with
scripts/generate_verification_fixtures.py."""

from __future__ import annotations

from minegen.core.enums import ScenarioPreset
from minegen.core.models import Scenario
from minegen.layout.search import (
    LayoutV2Search,
    materialize_effective_ramp,
    materialize_level_accesses,
)
from minegen.services.scenario_realizer import realize_scenario
from minegen.world.synthetic_world import generate_world
from tests.conftest import small_scenario
from tests.verification_support import (
    digest,
    load_fixture,
    selection_fingerprint,
    stale_message,
)
from tests.warped_sections_summary import warped_sections_summary


def test_tabular_selection_fixture_matches_clean_regeneration() -> None:
    fx = load_fixture("tabular_small_selected")
    sc = small_scenario()
    # the scenario id is minted per instantiation and carries no geometry
    current = {k: v for k, v in sc.model_dump(mode="json", by_alias=True).items() if k != "id"}
    stored = {k: v for k, v in fx["scenario"].items() if k != "id"}
    assert current == stored, (
        "STALE VERIFICATION FIXTURE tabular_small_selected: the small scenario definition changed"
    )
    world = generate_world(sc)
    search = LayoutV2Search(sc, world)
    res = search.run()
    assert res.winner_id is not None
    winner = res.candidate(res.winner_id)
    assert winner is not None
    ramp = materialize_effective_ramp(res, winner, search.evaluator, "verification-fixture")
    accesses = materialize_level_accesses(
        res, winner, "verification-fixture", sc.mining.method.value
    )
    actual = selection_fingerprint(ramp, accesses)
    expected = fx["metadata"]["upstreamFingerprint"]
    assert actual == expected, stale_message("tabular_small_selected", expected, actual)


def test_warped_sections_fixture_matches_clean_regeneration() -> None:
    fx = load_fixture("warped_301_sections")
    meta = fx["metadata"]
    sc = Scenario(
        **realize_scenario(
            ScenarioPreset.RANDOM_WARPED_VEIN,
            int(meta["seed"]),
            fault_count=int(meta["faultCount"]),
        ).model_dump()
    )
    actual = digest(warped_sections_summary(sc, generate_world(sc)))
    expected = meta["upstreamFingerprint"]
    assert actual == expected, stale_message("warped_301_sections", expected, actual)
