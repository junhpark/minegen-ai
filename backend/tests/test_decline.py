"""Phase 04 gate tests: chained decline generation (rules 21–22, 53–54)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from minegen.core.coordinates import wrap_angle_rad
from minegen.core.models import Point3D, RestrictedZone
from minegen.design.cost_field import DesignCostEvaluator
from minegen.design.mine_designer import ChainedDeclineGenerator, LevelStatus
from minegen.design.targets import generate_access_targets, resolve_portal
from minegen.world.synthetic_world import generate_world
from tests.conftest import small_scenario


@pytest.fixture(scope="module")
def chain():  # type: ignore[no-untyped-def]
    sc = small_scenario(with_fault=True)
    sc.design.candidate_count = 1  # u = 0 only: keeps the test fast
    sc.design.search.max_expansions_per_candidate = 20000
    w = generate_world(sc)
    ev = DesignCostEvaluator(w, sc.design)
    portal, gen = resolve_portal(sc, w)
    ts = generate_access_targets(
        w, sc.design, sc.ramp, sc.mining.sublevel_interval, ev, portal, gen
    )
    res = ChainedDeclineGenerator(ev, sc.ramp, sc.design.search).generate(ts)
    return sc, ts, res


def test_all_levels_completed_and_targets_hit_exactly(chain) -> None:  # type: ignore[no-untyped-def]
    _sc, ts, res = chain
    assert res.status == "SUCCESS" and res.completed_levels == len(ts.levels) == 4
    for lv_res, lv in zip(res.levels, ts.levels, strict=True):
        sel = lv_res.selected
        assert lv_res.status is LevelStatus.SUCCESS and sel is not None
        assert float(np.linalg.norm(sel.result.end_pose.position - sel.candidate.position)) < 1e-9  # type: ignore[union-attr]
        assert sel.result.end_pose.z == pytest.approx(lv.elevation)  # type: ignore[union-attr]


def test_terminal_heading_is_inherited_by_next_segment(chain) -> None:  # type: ignore[no-untyped-def]
    _, _, res = chain
    for prev, nxt in zip(res.levels, res.levels[1:], strict=False):
        a, b = prev.selected, nxt.selected
        assert a is not None and b is not None
        assert wrap_angle_rad(a.result.end_pose.heading - b.initial_heading) == pytest.approx(
            0.0, abs=1e-12
        )  # type: ignore[union-attr]
        assert np.array_equal(a.result.end_pose.position, b.result.path.start.position)  # type: ignore[union-attr]


def test_centerline_is_continuous_and_within_constraints(chain) -> None:  # type: ignore[no-untyped-def]
    sc, _, res = chain
    cl = res.centerline()
    steps = np.linalg.norm(np.diff(cl, axis=0), axis=1)
    assert steps.max() <= 2.2  # ≤ sample spacing (+ connector rounding)
    t = res.totals()
    assert t["maxGrade"] <= sc.ramp.max_gradient + 1e-9
    assert t["minimumRadius"] >= sc.ramp.min_turn_radius - 1e-9
    # samples are chords of the arcs, so their sum is slightly below the arc length
    assert float(steps.sum()) <= t["rawLength"] + 1e-6
    assert t["rawLength"] == pytest.approx(float(steps.sum()), rel=5e-4)
    d = res.to_dict()
    assert d["centerline"]["pointCount"] == cl.shape[0]
    import json

    json.dumps(d)


def test_first_segment_heading_points_at_candidate(chain) -> None:  # type: ignore[no-untyped-def]
    _, ts, res = chain
    first = res.levels[0].candidate_results[0]
    portal = ts.portal
    expected = math.atan2(
        first.candidate.position[0] - portal[0], first.candidate.position[1] - portal[1]
    )
    assert wrap_angle_rad(first.initial_heading - expected) == pytest.approx(0.0, abs=1e-12)


def test_selection_score_uses_next_level_bound(chain) -> None:  # type: ignore[no-untyped-def]
    _, _, res = chain
    for lv in res.levels[:-1]:
        for c in lv.candidate_results:
            if c.result.success:
                assert c.selection_score == pytest.approx(
                    c.result.cost + (c.candidate.next_level_accessibility or 0.0) * 1.0
                )
    for c in res.levels[-1].candidate_results:
        if c.result.success:
            assert c.selection_score == pytest.approx(c.result.cost)


def test_sealed_level_yields_structured_infeasible_and_skips_rest() -> None:
    sc = small_scenario(with_fault=True)
    sc.design.candidate_count = 1
    sc.design.search.max_expansions_per_candidate = 300
    w = generate_world(sc)
    ev = DesignCostEvaluator(w, sc.design)
    portal, gen = resolve_portal(sc, w)
    ts = generate_access_targets(
        w, sc.design, sc.ramp, sc.mining.sublevel_interval, ev, portal, gen
    )
    # seal level 2's candidate inside a no-go box after targets were generated
    c2 = ts.levels[1].candidates[0].position
    zone = RestrictedZone(
        min=Point3D(x=c2[0] - 15, y=c2[1] - 15, z=c2[2] - 15),
        max=Point3D(x=c2[0] + 15, y=c2[1] + 15, z=c2[2] + 15),
    )
    sc.design.restricted_zones = [zone]
    ev2 = DesignCostEvaluator(w, sc.design)
    sc.design.search.max_expansions_per_candidate = 20000
    res = ChainedDeclineGenerator(ev2, sc.ramp, sc.design.search).generate(ts, max_levels=3)
    statuses = [lv.status for lv in res.levels]
    assert statuses[0] is LevelStatus.SUCCESS
    assert statuses[1] is LevelStatus.INFEASIBLE
    assert statuses[2] is LevelStatus.SKIPPED
    assert res.status == "PARTIAL"
    d = res.to_dict()["levels"][1]
    assert d["status"] == "INFEASIBLE" and d["selectedCandidateId"] is None
    assert d["candidateResults"][0]["status"] in ("EXPANSION_LIMIT", "INFEASIBLE")
    assert d["candidateResults"][0]["diagnostics"]["expandedStates"] > 0
    assert sc.ramp.max_gradient == 0.12 and sc.ramp.min_turn_radius == 18.0  # untouched


def test_chain_backtracks_out_of_trapped_best_arrival() -> None:
    """Backtracking regression: level 1's best-scored candidate arrival is
    one-step launchable (a short pocket ahead) but leaves level 2 with no
    feasible corridor; the sibling candidate is clean. The chain must advance
    deterministically to the sibling and complete 2/2 with exactly one
    accepted backtrack."""
    from minegen.core.models import Point3D as Pt3
    from minegen.core.models import RestrictedZone, TerrainConfig
    from minegen.design.targets import AccessCandidate, AccessTargetSet, LevelAccessTargets

    sc = small_scenario(with_fault=False)
    sc.terrain = TerrainConfig(grid_spacing=10, base_elevation=100, relief=0, octaves=1)
    sc.orebody.center = Pt3(x=150.0, y=150.0, z=-400.0)  # far away: no buffer effects
    sc.design.minimum_surface_cover = 0.0
    trap = np.array([0.0, 0.0, 60.0])
    # pocket around the trap arrival (approach from the south stays open):
    # walls east/west/north leave a ~24 m channel — one successor primitive
    # fits (launchable) but nothing can turn out of it toward level 2
    sc.design.restricted_zones = [
        RestrictedZone(min=Pt3(x=-60.0, y=-40.0, z=30.0), max=Pt3(x=-14.0, y=60.0, z=90.0)),
        RestrictedZone(min=Pt3(x=14.0, y=-40.0, z=30.0), max=Pt3(x=60.0, y=60.0, z=90.0)),
        RestrictedZone(min=Pt3(x=-60.0, y=26.0, z=30.0), max=Pt3(x=60.0, y=60.0, z=90.0)),
    ]
    w = generate_world(sc)
    ev = DesignCostEvaluator(w, sc.design)

    def cand(cid: str, level_id: str, pos, nla: float) -> AccessCandidate:  # type: ignore[no-untyped-def]
        return AccessCandidate(
            id=cid,
            level_id=level_id,
            position=np.asarray(pos, dtype=np.float64),
            u_coord=0.0,
            v_coord=0.0,
            footwall_offset=20.0,
            valid=True,
            next_level_accessibility=nla,
        )

    ts = AccessTargetSet(
        portal=np.array([0.0, -160.0, 100.0]),
        portal_generated=False,
        levels=[
            LevelAccessTargets(
                "L01",
                0,
                60.0,
                [
                    # trap first with a better (lower) accessibility bias
                    cand("L01-TRAP", "L01", trap, nla=0.0),
                    cand("L01-ALT", "L01", [90.0, -20.0, 60.0], nla=500.0),
                ],
            ),
            LevelAccessTargets("L02", 1, 35.0, [cand("L02-C01", "L02", [140.0, 60.0, 35.0], 0.0)]),
        ],
    )
    gen = ChainedDeclineGenerator(ev, sc.ramp, sc.design.search)
    res = gen.generate(ts)
    assert res.chain_backtracks == 1
    assert [lr.status for lr in res.levels] == [LevelStatus.SUCCESS, LevelStatus.SUCCESS]
    sel1 = res.levels[0].selected
    assert sel1 is not None and sel1.candidate.id == "L01-ALT"
    trap_res = next(c for c in res.levels[0].candidate_results if c.candidate.id == "L01-TRAP")
    assert trap_res.result.success  # searched fine and one-step launchable...
    assert not trap_res.selected  # ...but deselected by the backtrack
    assert res.status == "SUCCESS" and res.completed_levels == 2
