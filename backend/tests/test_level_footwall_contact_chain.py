"""Hardening H0 §3.1 acceptance on the real chains (slow, rule 181):

(a) RANDOM_TABULAR seed 42 — the plan's reproduction case — through the
    layout-v2 search, selection, level accesses and level development:
    levels SUCCESS with 12 developed levels and L01 reported excluded;
(b) the 12 RANDOM_TABULAR golden cases: the layout-v2 serviceable set equals
    the set of levels the legacy access targets do not reject for
    ``OUTSIDE_OREBODY_DIP_EXTENT`` — ONE guard, two call sites — and the
    read-only census of the plan (101 / 105 / 106 overshoot, all others 0).
"""

from __future__ import annotations

import pytest

from minegen.core.enums import ScenarioPreset
from minegen.core.models import Scenario
from minegen.design.constraints import DesignContext, RejectionReason
from minegen.design.cost_field import DesignCostEvaluator
from minegen.design.targets import generate_access_targets, resolve_portal
from minegen.layout.levels import LevelSections, required_levels
from minegen.layout.materialize import materialize_effective_ramp, materialize_level_accesses
from minegen.layout.search import LayoutV2Search
from minegen.levels.builder import LevelDevelopmentBuilder, entries_from_level_accesses
from minegen.regression.golden import FULL_SUITE
from minegen.services.scenario_realizer import realize_scenario
from minegen.world.orebody import TabularOrebody
from minegen.world.synthetic_world import generate_world

#: the plan's read-only census (overshoot of L01, metres down-dip)
EXPECTED_CENSUS = {
    "RANDOM_TABULAR-101": 2.818,
    "RANDOM_TABULAR-105": 7.139,
    "RANDOM_TABULAR-106": 1.681,
}


def test_seed_42_layout_v2_chain_develops_twelve_levels_with_l01_excluded() -> None:
    sc = Scenario(**realize_scenario(ScenarioPreset.RANDOM_TABULAR, 42, None).model_dump())
    world = generate_world(sc)
    search = LayoutV2Search(sc, world)
    res = search.run()
    assert res.winner_id is not None, "the reproduction case must have a feasible layout"
    assert res.serviceable_ids == [f"L{i:02d}" for i in range(2, 14)]
    assert list(res.level_exclusions) == ["L01"]
    exc = res.level_exclusions["L01"]
    assert exc.reason == "NO_FOOTWALL_CONTACT_AT_LEVEL"
    assert exc.overshoot_m == pytest.approx(2.1206, abs=1e-3)
    assert exc.minimum_top_mining_margin_m == pytest.approx(11.865, abs=1e-2)
    winner = res.candidate(res.winner_id)
    assert winner is not None and winner.access_plan is not None
    assert [a.level_id for a in winner.access_plan.accesses] == res.serviceable_ids
    ramp = materialize_effective_ramp(res, winner, search.evaluator, "rev")
    accesses = materialize_level_accesses(res, winner, "rev", sc.mining.method.value)
    _, policy, _ = search.candidate_policy(res, res.winner_id)
    builder = LevelDevelopmentBuilder(
        sc,
        world.orebody,
        DesignCostEvaluator(world, sc.design, clearance=policy),
        DesignCostEvaluator(world, sc.design, DesignContext.crosscut(sc.design), clearance=policy),
    )
    levels = builder.build(
        ramp,
        "rev",
        entries=entries_from_level_accesses(accesses),
        level_exclusion_reasons={k: v.reason for k, v in res.level_exclusions.items()},
    )
    assert levels.status == "SUCCESS", levels.failure_reason
    assert len(levels.levels) == 12
    assert [lv.level_id for lv in levels.levels] == res.serviceable_ids
    (excluded,) = levels.excluded_levels
    assert excluded.level_id == "L01" and excluded.reason == "NO_FOOTWALL_CONTACT_AT_LEVEL"
    assert excluded.overshoot_m == pytest.approx(2.1206, abs=1e-3)
    assert excluded.minimum_top_mining_margin_m == pytest.approx(11.865, abs=1e-2)
    (interval,) = levels.unserved_intervals
    assert (interval.upper_level_id, interval.lower_level_id) == ("L01", "L02")


@pytest.mark.parametrize(
    "key", [c.key for c in FULL_SUITE if c.preset is ScenarioPreset.RANDOM_TABULAR]
)
def test_random_tabular_goldens_layout_v2_serviceable_equals_legacy_dip_extent_valid(
    key: str,
) -> None:
    case = next(c for c in FULL_SUITE if c.key == key)
    sc = case.realize()
    world = generate_world(sc)
    ob = world.orebody
    assert isinstance(ob, TabularOrebody)
    portal, generated = resolve_portal(sc, world)
    targets = generate_access_targets(
        world,
        sc.design,
        sc.ramp,
        sc.mining.sublevel_interval,
        DesignCostEvaluator(world, sc.design),
        portal,
        generated,
    )
    legacy_dip_valid = [
        lv.level_id
        for lv in targets.levels
        if not all(
            RejectionReason.OUTSIDE_OREBODY_DIP_EXTENT in c.rejection_reasons for c in lv.candidates
        )
    ]
    levels = required_levels(
        ob, sc.mining.sublevel_interval, sc.design.top_mining_margin, sc.design.bottom_mining_margin
    )
    sections = LevelSections(ob, levels, sc.layout.section_sampling_spacing)
    assert [lv.level_id for lv in sections.serviceable()] == legacy_dip_valid
    assert [lv.level_id for lv in targets.levels] == [lv.level_id for lv in levels]
    excluded = sections.excluded()
    expected = EXPECTED_CENSUS.get(key)
    if expected is None:
        assert excluded == []
    else:
        (exc,) = excluded
        assert exc.level_id == "L01" and exc.reason == "NO_FOOTWALL_CONTACT_AT_LEVEL"
        assert exc.overshoot_m == pytest.approx(expected, abs=1e-3)
