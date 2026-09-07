"""Phase 20C.2A commit A4 — curved level development along the
SECTION_FOOTWALL_OFFSET_TRACE backbone for implicit orebodies.

The WARPED-301 winner's level accesses feed ``LevelDevelopmentBuilder``:
level drifts follow the curved offset trace (chainage-graded, entry never
moved), LONGHOLE crosscut stations sit on curved drift chainage, and every
crosscut runs along its LOCAL inward normal to a contains()-bisection ore
contact. The WARPED stope boundary stays a typed explicit failure and the
TABULAR path is untouched (TABULAR_RULE_43)."""

from __future__ import annotations

import numpy as np
import pytest

from minegen.core.enums import ScenarioPreset
from minegen.core.models import Scenario
from minegen.design.constraints import DesignContext
from minegen.design.cost_field import DesignCostEvaluator, clearance_policy_for
from minegen.layout.search import (
    LayoutSearchResult,
    LayoutV2Search,
    materialize_effective_ramp,
    materialize_level_accesses,
)
from minegen.levels.builder import LevelDevelopmentBuilder, entries_from_level_accesses
from minegen.levels.models import DevelopmentKind, LevelsPayload
from minegen.mining.methods.base import strategy_for
from minegen.services.scenario_realizer import realize_scenario
from minegen.world.synthetic_world import SyntheticWorld, generate_world
from tests.conftest import small_scenario

REV = "rev-curved"


@pytest.fixture(scope="module")
def warped() -> tuple[Scenario, SyntheticWorld]:
    sc = Scenario(
        **realize_scenario(ScenarioPreset.RANDOM_WARPED_VEIN, 301, fault_count=1).model_dump()
    )
    return sc, generate_world(sc)


@pytest.fixture(scope="module")
def warped_search(
    warped: tuple[Scenario, SyntheticWorld],
) -> tuple[LayoutV2Search, LayoutSearchResult]:
    sc, world = warped
    search = LayoutV2Search(sc, world)
    return search, search.run()


def _build_levels(
    sc: Scenario,
    world: SyntheticWorld,
    search: LayoutV2Search,
    res: LayoutSearchResult,
) -> tuple[LevelsPayload, dict, dict]:
    assert res.winner_id is not None
    winner = res.candidate(res.winner_id)
    assert winner is not None
    ramp = materialize_effective_ramp(res, winner, search.evaluator, REV)
    accesses = materialize_level_accesses(res, winner, REV, sc.mining.method.value)
    # rule 172: the builder judges the development under the candidate's own
    # stage-4 certification, exactly as the service wires it
    _, policy, _ = search.candidate_policy(res, res.winner_id)
    drift_ev = DesignCostEvaluator(world, sc.design, clearance=policy)
    crosscut_ev = DesignCostEvaluator(
        world, sc.design, DesignContext.crosscut(sc.design), clearance=policy
    )
    builder = LevelDevelopmentBuilder(sc, world.orebody, drift_ev, crosscut_ev)
    payload = builder.build(ramp, REV, entries=entries_from_level_accesses(accesses))
    return payload, ramp, accesses


@pytest.fixture(scope="module")
def warped_levels(
    warped: tuple[Scenario, SyntheticWorld],
    warped_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> tuple[LevelsPayload, dict, dict]:
    sc, world = warped
    search, res = warped_search
    return _build_levels(sc, world, search, res)


class TestCurvedLevelDevelopment:
    def test_warped_levels_succeed_on_the_curved_backbone(self, warped_levels) -> None:
        payload, _, accesses = warped_levels
        assert payload.status == "SUCCESS", payload.failure_reason
        assert payload.development_geometry == "SECTION_FOOTWALL_OFFSET_TRACE"
        assert payload.entry_source == "LEVEL_ACCESS"
        assert payload.production_development is not None
        assert payload.production_development.status == "IMPLEMENTED"
        ok_accesses = [a for a in accesses["accesses"] if a["status"] == "OK"]
        assert payload.metrics is not None
        assert payload.metrics.level_count == len(ok_accesses) > 0
        assert all(lv.valid for lv in payload.levels)
        assert payload.metrics.crosscut_count > 0

    def test_entry_never_moves(self, warped_levels) -> None:
        payload, _, accesses = warped_levels
        terminals = {}
        for a in accesses["accesses"]:
            if a["status"] == "OK":
                pts = np.asarray(a["centerline"]["points"]).reshape(-1, 3)
                terminals[a["levelId"]] = pts[-1]
        for lv in payload.levels:
            assert np.allclose(np.asarray(lv.entry), terminals[lv.level_id], atol=1e-9)

    def test_drift_follows_a_curved_backbone(self, warped_levels) -> None:
        payload, _, _ = warped_levels
        # at least one level's drift turns measurably in plan — a straight
        # global-axis backbone cannot represent this body
        max_turn = 0.0
        for level in payload.levels:
            pieces = [
                np.asarray(d.centerline.points).reshape(-1, 3)
                for d in payload.developments
                if d.kind is DevelopmentKind.DRIFT and d.level_id == level.level_id
            ]
            pts = np.vstack(pieces)
            az = np.arctan2(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
            turn = float(np.sum(np.abs(np.diff(np.unwrap(2.0 * az) / 2.0))))
            max_turn = max(max_turn, np.degrees(turn))
        assert max_turn > 10.0

    def test_drift_gradient_and_chainage_span(self, warped_levels) -> None:
        payload, _, _ = warped_levels
        g = 0.0  # default level_drift_gradient
        for d in payload.developments:
            if d.kind is DevelopmentKind.DRIFT:
                assert d.to_u > d.from_u
                assert d.max_abs_gradient <= g + 1e-9
                assert d.report.valid
                assert d.report.start_weld_error <= 1e-6

    def test_crosscuts_reach_the_ore_contact_locally(self, warped, warped_levels) -> None:
        _, world = warped
        payload, _, _ = warped_levels
        crosscuts = [d for d in payload.developments if d.kind is DevelopmentKind.CROSSCUT]
        assert crosscuts
        for d in crosscuts:
            assert d.report.valid, d.report.failure_reason
            assert d.report.terminal_contact_gap is not None
            assert d.report.terminal_contact_gap <= 1e-6
            assert d.report.interior_breach_samples == 0
            pts = np.asarray(d.centerline.points).reshape(-1, 3)
            # horizontal (rule 72 analogue) and ends just OUTSIDE the ore
            assert d.max_abs_gradient <= 1e-12  # horizontal up to float noise
            assert not bool(world.orebody.contains(pts[-1:])[0])
            # one step past the terminal is inside (the contact is real)
            direction = pts[-1] - pts[0]
            direction /= np.linalg.norm(direction)
            probe = pts[-1] + 1e-3 * direction
            assert bool(world.orebody.contains(probe[None, :])[0])

    def test_warped_stope_boundary_stays_typed(self, warped, warped_levels) -> None:
        # a SUCCESS curved levels artifact now REACHES the stope strategy —
        # and the Phase 09 boundary stays the explicit typed failure
        # (WARPED stope geometry is future scope; STOPE_ACCESS anchors exist)
        sc, world = warped
        payload, _, _ = warped_levels
        strategy = strategy_for(sc.mining.method)
        assert strategy is not None
        stopes = strategy.generate(
            sc,
            world,
            payload.model_dump(mode="json", by_alias=True),
            DesignCostEvaluator(world, sc.design, clearance=clearance_policy_for(world.orebody)),
            REV,
        )
        assert stopes.status == "FAILED"
        assert "TABULAR" in (stopes.failure_reason or "")

    def test_dispatch_guards_are_typed(self, warped, warped_search) -> None:
        sc, world = warped
        search, res = warped_search
        assert res.winner_id is not None
        winner = res.candidate(res.winner_id)
        ramp = materialize_effective_ramp(res, winner, search.evaluator, REV)
        accesses = materialize_level_accesses(res, winner, REV, sc.mining.method.value)
        _, policy, _ = search.candidate_policy(res, res.winner_id)
        drift_ev = DesignCostEvaluator(world, sc.design, clearance=policy)
        crosscut_ev = DesignCostEvaluator(
            world, sc.design, DesignContext.crosscut(sc.design), clearance=policy
        )
        builder = LevelDevelopmentBuilder(sc, world.orebody, drift_ev, crosscut_ev)
        entries = entries_from_level_accesses(accesses)
        # anchors stripped → the implicit body has no development contract
        bare = [e.__class__(e.level_id, e.position, e.candidate_id, None) for e in entries]
        p1 = builder.build(ramp, REV, entries=bare)
        assert p1.status == "FAILED"
        assert (p1.failure_reason or "").startswith("SECTION_TRACE_ANCHORS_REQUIRED")
        # mixed contracts → typed failure
        mixed = [entries[0], *bare[1:]] if len(entries) > 1 else entries
        if len(entries) > 1:
            p2 = builder.build(ramp, REV, entries=mixed)
            assert p2.status == "FAILED"
            assert (p2.failure_reason or "").startswith("MIXED_DEVELOPMENT_GEOMETRY")


class TestTabularUnchanged:
    def test_tabular_declares_rule_43_geometry(self) -> None:
        sc = small_scenario()
        world = generate_world(sc)
        search = LayoutV2Search(sc, world)
        res = search.run()
        assert res.winner_id is not None
        payload, _, _ = _build_levels(sc, world, search, res)
        assert payload.status == "SUCCESS", payload.failure_reason
        assert payload.development_geometry == "TABULAR_RULE_43"
