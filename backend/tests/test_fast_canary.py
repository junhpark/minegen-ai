"""VA-01 FAST canaries (cached upstream fixtures, unmarked → inner loop).

A cached fixture is DEVELOPMENT ACCELERATION, never release authority: FULL
regenerates the same upstream artifacts cleanly and compares fingerprints
(tests/test_verification_fixtures_fresh.py, marked canary+slow). These tests
start DOWNSTREAM of the expensive layout search:

* TABULAR small scenario: cached selected layout (Effective Ramp + level
  accesses) → level development (rule 43) → MineNetwork. For an analytic
  body the candidate clearance policy IS the exact world policy (rule 135
  closeout), so the cached chain is judged under the same certification the
  service uses.
* WARPED-301: section(z) geometry + footwall / offset traces under the WORLD
  policy (no search), pinned against the fixture summary.
"""

from __future__ import annotations

import numpy as np
import pytest

from minegen.core.enums import ScenarioPreset
from minegen.core.models import Scenario
from minegen.design.constraints import DesignContext
from minegen.design.cost_field import DesignCostEvaluator
from minegen.levels.builder import LevelDevelopmentBuilder, entries_from_level_accesses
from minegen.network.builder import MineNetworkBuilder
from minegen.services.scenario_realizer import realize_scenario
from minegen.world.synthetic_world import generate_world
from tests.verification_support import load_fixture, selection_fingerprint
from tests.warped_sections_summary import warped_sections_summary

LAYOUT_V2_SELECTED = "layout_v2_selected.json"


@pytest.fixture(scope="module")
def tabular_fixture() -> dict:  # type: ignore[type-arg]
    return load_fixture("tabular_small_selected")


def test_tabular_fixture_metadata_and_internal_fingerprint(tabular_fixture: dict) -> None:  # type: ignore[type-arg]
    meta = tabular_fixture["metadata"]
    assert meta["sourceStage"] == "LAYOUT_V2_SELECTED"
    assert "never release evidence" in meta["authority"]
    # the stored fingerprint must describe the stored payloads (no hand edits)
    assert meta["upstreamFingerprint"] == selection_fingerprint(
        tabular_fixture["effectiveRamp"], tabular_fixture["levelAccesses"]
    )


def test_tabular_cached_selection_drives_levels_and_network(tabular_fixture: dict) -> None:  # type: ignore[type-arg]
    sc = Scenario(**tabular_fixture["scenario"])
    world = generate_world(sc)
    ramp = tabular_fixture["effectiveRamp"]
    accesses = tabular_fixture["levelAccesses"]
    assert accesses["candidateId"] == tabular_fixture["winnerId"]
    drift = DesignCostEvaluator(world, sc.design)
    cross = DesignCostEvaluator(world, sc.design, DesignContext.crosscut(sc.design))
    levels = LevelDevelopmentBuilder(sc, world.orebody, drift, cross).build(
        ramp, "canary", entries=entries_from_level_accesses(accesses)
    )
    assert levels.status == "SUCCESS", levels.failure_reason
    assert levels.development_geometry == "TABULAR_RULE_43"
    assert levels.entry_source == "LEVEL_ACCESS"
    assert levels.metrics is not None and levels.metrics.crosscut_count > 0
    result = MineNetworkBuilder(sc).build(
        ramp,
        "canary",
        levels_payload=levels.model_dump(mode="json", by_alias=True),
        geometry_artifact=LAYOUT_V2_SELECTED,
        accesses_payload=accesses,
    )
    net = result.payload
    assert net.status == "SUCCESS", net.failure_reason
    assert net.validation is not None and net.validation.connected and net.validation.synchronized
    assert net.metrics is not None
    assert net.metrics.stope_access_count > 0 and net.metrics.crosscut_edge_count > 0
    assert net.metrics.level_access_edge_count == len(
        [a for a in accesses["accesses"] if a["status"] == "OK"]
    )


def test_warped_301_sections_match_cached_summary() -> None:
    fx = load_fixture("warped_301_sections")
    meta = fx["metadata"]
    assert meta["sourceStage"] == "SECTION_TRACES_WORLD_POLICY"
    sc = Scenario(
        **realize_scenario(
            ScenarioPreset.RANDOM_WARPED_VEIN,
            int(meta["seed"]),
            fault_count=int(meta["faultCount"]),
        ).model_dump()
    )
    world = generate_world(sc)
    summary = warped_sections_summary(sc, world)
    expected = fx["summary"]
    assert summary["policyBasis"] == expected["policyBasis"]
    assert summary["serviceableLevels"] == expected["serviceableLevels"]
    assert [r["levelId"] for r in summary["levels"]] == [r["levelId"] for r in expected["levels"]]
    for got, exp in zip(summary["levels"], expected["levels"], strict=True):
        assert got.get("traceFailure") == exp.get("traceFailure"), got["levelId"]
        for key in ("componentCount", "selectedComponentId", "selectedSamples"):
            assert got[key] == exp[key], (got["levelId"], key)
        for key in (
            "footwallTraceLength",
            "offsetTraceLength",
            "minContactDistance",
            "minClearance",
        ):
            if key in exp:
                assert got[key] == pytest.approx(exp[key], abs=1e-6), (got["levelId"], key)
        if "midpoint" in exp:
            assert np.allclose(got["midpoint"], exp["midpoint"], atol=1e-6), got["levelId"]
        # the delivered backbone never dips below the required design clearance
        if "minClearance" in got:
            assert got["minClearance"] >= summary["requiredClearance"] - 1e-9
