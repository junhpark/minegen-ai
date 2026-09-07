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
from minegen.world.synthetic_world import SyntheticWorld, generate_world
from tests.conftest import small_scenario

REV = "rev-curved"


@pytest.fixture(scope="module")
def warped(warped_301: tuple[Scenario, SyntheticWorld]) -> tuple[Scenario, SyntheticWorld]:
    # VA-01: session-shared read-only DEFAULT WARPED-301 world (tests/conftest.py)
    return warped_301


@pytest.fixture(scope="module")
def warped_search(
    warped_301_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> tuple[LayoutV2Search, LayoutSearchResult]:
    return warped_301_search


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


class TestInwardNormalContract:
    """PR #24 follow-up §1 regressions: the crosscut direction is the exact
    ± horizontal perpendicular of the offset trace's local tangent, the ore
    side decided by bounded contains() probes; undecidable stations are
    typed (hard failure or NO_PERPENDICULAR_ORE_SUPPORT exclusion)."""

    def test_crosscuts_are_perpendicular_to_the_local_trace_tangent(
        self, warped, warped_search, warped_levels
    ) -> None:
        """The plan direction of every delivered crosscut is perpendicular
        to the offset trace's interpolated local tangent at its station.
        Tolerance 1e-9: the direction is CONSTRUCTED as the exact
        perpendicular of that tangent, so only float noise remains."""
        from minegen.design.profile import required_clearance
        from minegen.layout.families import build_footwall_track
        from minegen.layout.levels import LevelSections, required_levels
        from minegen.layout.sections import resolve_section_resolution
        from minegen.levels.builder import GENERIC_BACKBONE_END_CLEARANCE

        sc, world = warped
        search, res = warped_search
        payload, _, accesses = warped_levels
        assert payload.status == "SUCCESS"
        base = (
            sc.layout.access.anchor_standoff
            if sc.layout.access.anchor_standoff is not None
            else sc.ramp.footwall_access_offset
        )
        resolution = resolve_section_resolution(
            float(sc.layout.section_sampling_spacing), float(base)
        )
        levels = required_levels(
            world.orebody,
            sc.mining.sublevel_interval,
            sc.design.top_mining_margin,
            sc.design.bottom_mining_margin,
        )
        sections = LevelSections(
            world.orebody, levels, float(sc.layout.section_sampling_spacing), resolution
        )
        track = build_footwall_track(world.orebody, sections)
        _, policy, _ = search.candidate_policy(res, res.winner_id)
        req = required_clearance(sc.design, sc.ramp, sc.tunnel_profile)
        by_id = {lv.level_id: lv for lv in levels}
        standoffs = {
            a["levelId"]: float(a["anchor"]["standoff"])
            for a in accesses["accesses"]
            if a["status"] == "OK"
        }
        traces = {}
        checked = 0
        for d in payload.developments:
            if d.kind is not DevelopmentKind.CROSSCUT:
                continue
            lvid = d.level_id
            if lvid not in traces:
                traces[lvid] = sections.offset_trace(
                    by_id[lvid],
                    track.w_h,
                    standoffs[lvid],
                    2.0 * GENERIC_BACKBONE_END_CLEARANCE,
                    policy.signed_clearance,
                    "SELECTED",
                    req,
                )
            off = traces[lvid]
            pts = np.asarray(d.centerline.points).reshape(-1, 3)
            direction = pts[-1, :2] - pts[0, :2]
            n = float(np.linalg.norm(direction))
            assert n > 0
            tangent = off.tangent_at(float(d.station_u))
            assert abs(float(np.dot(direction / n, tangent))) <= 1e-9
            checked += 1
        assert checked > 0

    def test_stations_without_perpendicular_ore_support_are_excluded_typed(
        self, warped_levels
    ) -> None:
        """WARPED-301 (measured): 5 end stations sit past the local ore
        extent — the offset level set wraps around the body's tapered ends.
        Under the perpendicular contract they are typed-excluded from the
        REQUIRED lattice (rule 141 precedent), fully recorded, and never
        emitted as developments; the artifact stays SUCCESS. The removed
        KD-tree fallback had been bending these crosscuts up to ~59 degrees
        off perpendicular to force them through."""
        payload, _, _ = warped_levels
        assert payload.status == "SUCCESS"
        excluded = {
            lv.level_id: lv.excluded_stations for lv in payload.levels if lv.excluded_stations
        }
        flat = {(lid, e.station_index) for lid, lst in excluded.items() for e in lst}
        assert flat == {("L03", -4), ("L03", 3), ("L03", 4), ("L15", -6), ("L16", -5)}
        for lst in excluded.values():
            for e in lst:
                assert e.reason == "NO_PERPENDICULAR_ORE_SUPPORT"
                assert e.probe_length > 0
        emitted = {
            (d.level_id, d.station_index)
            for d in payload.developments
            if d.kind is DevelopmentKind.CROSSCUT
        }
        assert not (flat & emitted)

    def test_inward_probe_outcomes_are_typed(self) -> None:
        from minegen.levels.builder import _inward_contact

        class Slab:
            """ore occupies x >= x_min (vertical half-space in plan)."""

            def __init__(self, x_min: float) -> None:
                self.x_min = x_min

            def contains(self, points):
                pts = np.asarray(points, dtype=np.float64)
                return pts[:, 0] >= self.x_min

        class TwoSlabs:
            def contains(self, points):
                pts = np.asarray(points, dtype=np.float64)
                return np.abs(pts[:, 0]) >= 20.0

        class NoOre:
            def contains(self, points):
                return np.zeros(np.asarray(points).shape[0], dtype=bool)

        start = np.zeros(3)
        tangent = np.array([0.0, 1.0])  # perpendiculars point +-x
        # exactly one side -> decided, direction points at the ore, bracket tight
        decided = _inward_contact(Slab(15.0), start, tangent, 60.0)
        assert not isinstance(decided[0], str)
        direction, (end, gap) = decided
        # tangent +y makes normal = (-1, 0); ore at +x is the NEGATED normal
        assert direction[0] > 0 and abs(direction[1]) <= 1e-12
        assert end[0] == pytest.approx(15.0, abs=1e-6) and gap <= 1e-6
        # ore on both sides -> typed hard code
        both = _inward_contact(TwoSlabs(), start, tangent, 60.0)
        assert both[0] == "INWARD_AMBIGUOUS"
        # ore on neither side -> typed exclusion code (rule 141 precedent)
        none = _inward_contact(NoOre(), start, tangent, 60.0)
        assert none[0] == "NO_PERPENDICULAR_ORE_SUPPORT"
        # station inside the ore -> typed hard code
        inside = _inward_contact(Slab(-5.0), start, tangent, 60.0)
        assert inside[0] == "STATION_INSIDE_ORE"


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
