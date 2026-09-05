"""Phase 20B — ramp junctions, level accesses and mining-method-aware level
development (directive §22 tests B–M that the layout / API files do not
already cover): connector geometry, typed failures, junction spacing,
determinism, effective-ramp separation, longhole vs CUT_AND_FILL level
development, and the network shortcut ban."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from minegen.core.enums import MiningMethodType
from minegen.core.models import RampConstraints, Scenario, TunnelProfile
from minegen.design.constraints import DesignContext
from minegen.design.cost_field import DesignCostEvaluator
from minegen.design.profile import build_profile
from minegen.layout.access import (
    LONG_ACCESS_COEF,
    AccessFailure,
    access_length_cost,
    build_anchor,
    build_connector,
    build_cs_connectors,
    effective_preferred_access_length,
    plan_level_accesses,
)
from minegen.layout.families import build_footwall_track
from minegen.layout.geometry import analyze_centerline, plan_radii
from minegen.layout.levels import LevelSections, required_levels
from minegen.layout.search import (
    LayoutSearchResult,
    LayoutV2Search,
    materialize_effective_ramp,
    materialize_level_accesses,
    required_clearance,
)
from minegen.levels.builder import LevelDevelopmentBuilder, entries_from_level_accesses
from minegen.network.builder import MineNetworkBuilder
from minegen.world.synthetic_world import SyntheticWorld, generate_world

from .conftest import small_scenario


@pytest.fixture(scope="module")
def tabular() -> tuple[Scenario, SyntheticWorld]:
    sc = small_scenario()
    return sc, generate_world(sc)


@pytest.fixture(scope="module")
def search(tabular: tuple[Scenario, SyntheticWorld]) -> tuple[LayoutV2Search, LayoutSearchResult]:
    sc, world = tabular
    s = LayoutV2Search(sc, world)
    return s, s.run()


def _winner(search: LayoutV2Search, res: LayoutSearchResult):  # type: ignore[no-untyped-def]
    assert res.winner_id is not None
    w = res.candidate(res.winner_id)
    assert w is not None and w.access_plan is not None and w.access_plan.feasible
    return w


# --------------------------------------------------------------------------- #
# connector geometry
# --------------------------------------------------------------------------- #


def _compass(d: np.ndarray) -> float:
    return math.atan2(d[0], d[1]) % (2.0 * math.pi)


@pytest.mark.parametrize("kind", ["L", "R"])
def test_connector_is_one_turn_cs_with_constant_chord_gradient(kind: str) -> None:
    """Phase 20B.2-A: a level access is ONE turnout arc followed by ONE
    straight (or a pure straight). The terminal heading is FREE — it is the
    heading of the final straight, not a prescribed drift direction — so no
    second (terminal) arc exists."""
    start = np.array([0.0, 0.0, 10.0])
    # the target sits on the turn side (compass 66° for R, −26° for L from a
    # 20° start heading); the opposite sense would need more than a half-turn
    end = np.array([80.0, 35.0, 4.0]) if kind == "R" else np.array([-35.0, 80.0, 4.0])
    conn = build_connector(start, math.radians(20.0), end, 18.0, 2.0, kind)
    assert conn is not None
    other = build_connector(start, math.radians(20.0), end, 18.0, 2.0, "L" if kind == "R" else "R")
    assert other is None
    pts = conn.points
    np.testing.assert_allclose(pts[0], start)
    np.testing.assert_allclose(pts[-1], end, atol=1e-9)
    # initial direction = start heading (tangent continuity with the ramp)
    d0 = pts[1] - pts[0]
    assert math.isclose(_compass(d0), math.radians(20.0), abs_tol=0.12)
    # pieces: at most one ARC, then exactly one STRAIGHT — never a terminal arc
    kinds = [p["kind"] for p in conn.pieces]
    assert kinds in (["STRAIGHT"], ["ARC", "STRAIGHT"])
    assert conn.word in ("S", "LS", "RS") and conn.word[-1] == "S"
    # the final straight's heading IS the reported terminal heading (exact)
    d1 = pts[-1] - pts[-2]
    assert math.isclose(_compass(d1), conn.terminal_heading, abs_tol=1e-9)
    # heading is constant over the whole straight (post-turnout variation 0)
    n_straight = max(2, int(conn.straight_length / 2.0))
    tail = np.diff(pts[-n_straight:], axis=0)
    heads = np.array([_compass(d) for d in tail])
    assert float(np.max(np.abs(np.unwrap(heads) - np.unwrap(heads)[0]))) < 1e-9
    # every edge carries the same chord gradient
    seg = np.diff(pts, axis=0)
    grads = seg[:, 2] / np.hypot(seg[:, 0], seg[:, 1])
    np.testing.assert_allclose(grads, grads[0], rtol=1e-9)
    assert math.isclose(abs(grads[0]), 6.0 / conn.horizontal_length, rel_tol=1e-6)
    # the arc delivers EXACTLY the turning radius (circumradius), nothing tighter
    r = plan_radii(pts)
    assert float(np.min(r)) >= 18.0 - 1e-6
    assert np.all(np.isfinite(pts)) and np.all(np.linalg.norm(seg, axis=1) > 1e-6)
    # analytic arc + straight vs delivered chord length (chords are shorter)
    analytic = conn.arc_length + conn.straight_length
    assert conn.horizontal_length <= analytic + 1e-9
    assert math.isclose(analytic, conn.horizontal_length, rel_tol=1e-3)
    assert conn.sense == ("CCW" if kind == "L" else "CW")


def test_connector_pure_straight_when_target_is_dead_ahead() -> None:
    start = np.array([0.0, 0.0, 0.0])
    end = np.array([0.0, 60.0, -3.0])  # exactly along heading 0 (north)
    for kind in ("L", "R"):
        conn = build_connector(start, 0.0, end, 18.0, 2.0, kind)
        assert conn is not None
        assert conn.word == "S" and conn.pieces[0]["kind"] == "STRAIGHT"
        assert conn.sense is None and conn.arc_length == 0.0
        assert math.isclose(conn.straight_length, 60.0, rel_tol=1e-9)
        assert math.isclose(conn.terminal_heading, 0.0, abs_tol=1e-12)
    # the pair helper reports the straight ONCE
    conns = build_cs_connectors(start, 0.0, end, 18.0, 2.0)
    assert [c.word for c in conns] == ["S"]


def test_connector_refuses_target_inside_turning_circle_and_behind() -> None:
    start = np.array([0.0, 0.0, 0.0])
    # inside the left turning circle (centre (-18, 0) for heading north)
    inside = np.array([-18.0, 5.0, 0.0])
    assert build_connector(start, 0.0, inside, 18.0, 2.0, "L") is None
    # straight behind: both senses would need more than a half-turn -> refused
    behind = np.array([0.0, -60.0, 0.0])
    assert build_cs_connectors(start, 0.0, behind, 18.0, 2.0) == []
    # off to one side: only the matching sense stays within a half-turn
    conns = build_cs_connectors(start, 0.0, np.array([60.0, 5.0, 0.0]), 18.0, 2.0)
    words = [c.word for c in conns]
    assert "RS" in words and all(w in ("S", "LS", "RS") for w in words)


def test_connector_refuses_degenerate_poses() -> None:
    p = np.array([0.0, 0.0, 0.0])
    assert build_connector(p, 0.0, p + np.array([0.2, 0.0, 0.0]), 18.0, 2.0) is None


def test_heading_axis_mismatch_is_undirected() -> None:
    from minegen.layout.access import heading_axis_mismatch_deg

    assert math.isclose(heading_axis_mismatch_deg(0.0, 0.0), 0.0, abs_tol=1e-12)
    assert math.isclose(heading_axis_mismatch_deg(0.0, math.pi), 0.0, abs_tol=1e-9)
    assert math.isclose(heading_axis_mismatch_deg(math.radians(30.0), 0.0), 30.0, abs_tol=1e-9)
    assert math.isclose(heading_axis_mismatch_deg(math.radians(150.0), 0.0), 30.0, abs_tol=1e-9)
    assert math.isclose(heading_axis_mismatch_deg(math.radians(90.0), 0.0), 90.0, abs_tol=1e-9)


# --------------------------------------------------------------------------- #
# plan: welds, hard limits, typed failures, spacing, determinism
# --------------------------------------------------------------------------- #


#: the shared RampConstraints profile every access and the main ramp are
#: driven with (5 m wide, 5 m high D-profile on the floor centerline)
SHAPE = build_profile(RampConstraints(), TunnelProfile())


def _plan(
    sc: Scenario,
    world: SyntheticWorld,
    search: LayoutV2Search,
    res: LayoutSearchResult,
    **access_overrides: object,
):  # type: ignore[no-untyped-def]
    w = _winner(search, res)
    levels = required_levels(
        world.orebody,
        sc.mining.sublevel_interval,
        sc.design.top_mining_margin,
        sc.design.bottom_mining_margin,
    )
    sections = LevelSections(world.orebody, levels, sc.layout.section_sampling_spacing)
    track = build_footwall_track(world.orebody, sections)
    assert track is not None
    req = required_clearance(sc.design, sc.ramp, sc.tunnel_profile)
    cfg = (
        sc.layout.access.model_copy(update=access_overrides)
        if access_overrides
        else sc.layout.access
    )
    serviceable = sections.serviceable()
    anchors = [
        build_anchor(
            world.orebody,
            lv,
            sections,
            track,
            w.points,
            search.anchor_standoff(req),
            "LONGHOLE_OPEN_STOPING",
        )
        for lv in serviceable
    ]
    plan = plan_level_accesses(
        w.points,
        anchors,
        serviceable,
        cfg,
        sc.ramp,
        search.evaluator,
        build_profile(sc.ramp, sc.tunnel_profile),
        req,
    )
    return w, plan


def test_every_serviceable_level_has_exactly_one_welded_validated_access(
    tabular: tuple[Scenario, SyntheticWorld], search: tuple[LayoutV2Search, LayoutSearchResult]
) -> None:
    sc, world = tabular
    s, res = search
    w, plan = _plan(sc, world, s, res)
    assert plan.feasible and len(plan.accesses) == len(res.serviceable_ids)
    assert len({a.level_id for a in plan.accesses}) == len(plan.accesses)
    used: list[float] = []
    for a in plan.accesses:
        assert a.ok and a.points is not None and a.anchor is not None
        # B: exact junction weld to the main ramp (the junction lies ON the ramp)
        assert a.junction_position is not None and a.junction_chainage is not None
        np.testing.assert_allclose(a.points[0], a.junction_position, atol=1e-6)
        ch = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(w.points, axis=0), axis=1))])
        i = int(np.searchsorted(ch, a.junction_chainage, side="right") - 1)
        t = (a.junction_chainage - ch[i]) / (ch[i + 1] - ch[i])
        on_ramp = w.points[i] + t * (w.points[i + 1] - w.points[i])
        np.testing.assert_allclose(a.junction_position, on_ramp, atol=1e-6)
        # C: exact level-entry weld to the development anchor
        np.testing.assert_allclose(a.points[-1], a.anchor.position, atol=1e-6)
        assert a.points[-1, 2] == a.elevation
        # D: delivered geometry limits
        d = analyze_centerline(a.points)
        assert d.max_abs_gradient <= sc.ramp.max_gradient + 1e-9
        assert d.min_plan_radius is None or d.min_plan_radius >= sc.ramp.min_turn_radius - 0.05
        assert d.monotonic_descent or a.points[0, 2] <= a.points[-1, 2]  # bounded vertical
        assert np.all(np.abs(a.points[:, 0]) <= sc.world.size_x / 2)
        assert np.all(np.abs(a.points[:, 1]) <= sc.world.size_y / 2)
        assert a.validation["envelopeHardViolations"] == 0
        assert a.validation["minimumOrebodyDistance"] >= plan.required_clearance - 1e-9
        assert (
            sc.layout.access.minimum_access_length
            <= a.length3d
            <= sc.layout.access.maximum_access_length
        )
        # junction spacing rule
        assert all(
            abs(a.junction_chainage - u) >= sc.layout.access.minimum_ramp_junction_spacing
            for u in used
        )
        used.append(a.junction_chainage)


def test_typed_access_failures(
    tabular: tuple[Scenario, SyntheticWorld], search: tuple[LayoutV2Search, LayoutSearchResult]
) -> None:
    sc, world = tabular
    s, res = search
    # no junction candidate in the window
    _, plan = _plan(sc, world, s, res, junction_window_above=0.0, junction_window_below=0.0)
    assert not plan.feasible
    assert {a.failure_reason for a in plan.accesses if not a.ok} <= {
        AccessFailure.NO_JUNCTION_IN_WINDOW,
        AccessFailure.GRADE_LIMIT,
        AccessFailure.ACCESS_TOO_SHORT,
    }
    # gradient impossible: a nearly flat access limit
    _, plan = _plan(sc, world, s, res, max_gradient=0.001)
    assert not plan.feasible
    failed = [a for a in plan.accesses if not a.ok]
    assert failed and all(a.rejection_counts.get(AccessFailure.GRADE_LIMIT, 0) > 0 for a in failed)
    # turning radius impossible: a huge access radius. Since 20B.2-A the
    # connector is one-turn CS: an entry INSIDE the 400 m turning circle has
    # no tangent at all (CONNECTOR_UNAVAILABLE — the structural loop ban),
    # instead of a Dubins loop failing later on length or radius.
    _, plan = _plan(sc, world, s, res, min_turn_radius=400.0)
    assert not plan.feasible
    failed = [a for a in plan.accesses if not a.ok]
    assert failed and all(
        a.failure_reason
        in (
            AccessFailure.ACCESS_TOO_LONG,
            AccessFailure.GRADE_LIMIT,
            AccessFailure.WORLD_BOUNDS,
            AccessFailure.TURN_RADIUS,
            AccessFailure.CONNECTOR_UNAVAILABLE,
        )
        for a in failed
    )
    # junction spacing conflict forces a typed failure when the ramp cannot
    # host two turnouts far enough apart
    _, plan = _plan(sc, world, s, res, minimum_ramp_junction_spacing=5000.0)
    assert not plan.feasible
    assert any(a.failure_reason == AccessFailure.JUNCTION_SPACING_CONFLICT for a in plan.accesses)
    # every failure is inspectable: counts + detail, never a NaN
    for a in plan.accesses:
        if not a.ok:
            assert a.failure_reason and a.failure_detail
            assert a.candidates_tried == sum(a.rejection_counts.values()) or a.candidates_tried == 0
    json.dumps(plan.to_dict(), allow_nan=False)


def test_access_plan_is_deterministic(
    tabular: tuple[Scenario, SyntheticWorld], search: tuple[LayoutV2Search, LayoutSearchResult]
) -> None:
    sc, world = tabular
    s, res = search
    _, a = _plan(sc, world, s, res)
    _, b = _plan(sc, world, s, res)
    assert a.to_dict() == b.to_dict()
    again = LayoutV2Search(sc, world).run()
    w1 = _winner(s, res)
    w2 = _winner(s, again)
    assert w1.candidate_id == w2.candidate_id
    assert w1.access_plan.to_dict() == w2.access_plan.to_dict()  # type: ignore[union-attr]


def test_level_access_geometry_is_never_inserted_into_the_effective_ramp(
    search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    s, res = search
    w = _winner(s, res)
    ramp = materialize_effective_ramp(res, w, s.evaluator, "r")
    accesses = materialize_level_accesses(res, w, "r", "LONGHOLE_OPEN_STOPING")
    ramp_pts = np.vstack(
        [
            np.asarray(seg["effectiveCenterline"]["points"]).reshape(-1, 3)
            for seg in ramp["segments"]
        ]
    )
    for a in accesses["accesses"]:
        pts = np.asarray(a["centerline"]["points"]).reshape(-1, 3)
        # only the junction (first point) touches the ramp; the entry never does
        d_entry = np.min(np.linalg.norm(ramp_pts - pts[-1], axis=1))
        assert d_entry > 1.0
    assert math.isclose(
        sum(seg["report"]["rawLength"] for seg in ramp["segments"]), w.diagnostics.length3d
    )  # type: ignore[union-attr]
    assert "accesses" not in ramp and all("centerline" not in seg for seg in ramp["segments"])


# --------------------------------------------------------------------------- #
# level development: longhole vs cut-and-fill, entries, shortcut ban
# --------------------------------------------------------------------------- #


def _levels_builder(sc: Scenario, world: SyntheticWorld) -> LevelDevelopmentBuilder:
    drift = DesignCostEvaluator(world, sc.design)
    cross = DesignCostEvaluator(world, sc.design, DesignContext.crosscut(sc.design))
    return LevelDevelopmentBuilder(sc, world.orebody, drift, cross)


def test_parametric_ramp_requires_level_access_entries(
    tabular: tuple[Scenario, SyntheticWorld], search: tuple[LayoutV2Search, LayoutSearchResult]
) -> None:
    sc, world = tabular
    s, res = search
    w = _winner(s, res)
    ramp = materialize_effective_ramp(res, w, s.evaluator, "r")
    payload = _levels_builder(sc, world).build(ramp, "r")
    assert payload.status == "FAILED" and "LEVEL_ACCESSES_REQUIRED" in (
        payload.failure_reason or ""
    )


def test_longhole_levels_anchor_at_level_entries_and_keep_the_station_lattice(
    tabular: tuple[Scenario, SyntheticWorld], search: tuple[LayoutV2Search, LayoutSearchResult]
) -> None:
    sc, world = tabular
    s, res = search
    w = _winner(s, res)
    ramp = materialize_effective_ramp(res, w, s.evaluator, "r")
    accesses = materialize_level_accesses(res, w, "r", "LONGHOLE_OPEN_STOPING")
    builder = _levels_builder(sc, world)
    payload = builder.build(ramp, "r", entries=entries_from_level_accesses(accesses))
    assert payload.status == "SUCCESS", payload.failure_reason
    assert payload.entry_source == "LEVEL_ACCESS"
    assert payload.production_development is not None
    assert payload.production_development.status == "IMPLEMENTED"
    entries = {a["levelId"]: np.asarray(a["levelEntry"]) for a in accesses["accesses"]}
    junctions = {j["levelId"]: np.asarray(j["position"]) for j in ramp["rampJunctions"]}
    for lv in payload.levels:
        np.testing.assert_allclose(np.asarray(lv.entry), entries[lv.level_id], atol=1e-9)
        assert np.linalg.norm(np.asarray(lv.entry) - junctions[lv.level_id]) > 1.0
        assert lv.crosscut_count == len(builder.station_us(world.orebody))  # type: ignore[arg-type]
    # a drift piece starts exactly at the entry (weld) and crosscuts start on the drift
    for lv in payload.levels:
        pieces = [
            d for d in payload.developments if d.kind.value == "DRIFT" and d.level_id == lv.level_id
        ]
        starts = [np.asarray(d.centerline.points[:3]) for d in pieces]
        ends = [np.asarray(d.centerline.points[-3:]) for d in pieces]
        assert any(np.linalg.norm(p - np.asarray(lv.entry)) < 1e-6 for p in starts + ends)


def test_cut_and_fill_gets_generic_level_access_and_backbone_but_no_longhole_lattice(
    tabular: tuple[Scenario, SyntheticWorld],
) -> None:
    sc, world = tabular
    caf = sc.model_copy(
        update={"mining": sc.mining.model_copy(update={"method": MiningMethodType.CUT_AND_FILL})}
    )
    s = LayoutV2Search(caf, world)
    res = s.run()
    w = _winner(s, res)
    assert all(
        a.anchor is not None and a.anchor.mining_method == "CUT_AND_FILL"
        for a in w.access_plan.accesses
    )  # type: ignore[union-attr]
    ramp = materialize_effective_ramp(res, w, s.evaluator, "r")
    accesses = materialize_level_accesses(res, w, "r", "CUT_AND_FILL")
    assert accesses["miningMethod"] == "CUT_AND_FILL" and accesses["status"] == "SUCCESS"
    payload = _levels_builder(caf, world).build(
        ramp, "r", entries=entries_from_level_accesses(accesses)
    )
    assert payload.status == "SUCCESS", payload.failure_reason
    assert payload.production_development is not None
    assert payload.production_development.status == "UNSUPPORTED_METHOD"
    assert "CUT_AND_FILL" in (payload.production_development.reason or "")
    kinds = {d.kind.value for d in payload.developments}
    assert kinds == {"DRIFT"}  # generic backbone only — no longhole crosscut lattice
    assert payload.metrics is not None and payload.metrics.crosscut_count == 0
    # the network still has the full generic route PORTAL → RAMP → RAMP_JUNCTION →
    # LEVEL_ACCESS → LEVEL_ENTRY → DRIFT, and no shortcut from the ramp to the drift
    net = (
        MineNetworkBuilder(caf)
        .build(
            ramp,
            "r",
            levels_payload=payload.model_dump(mode="json", by_alias=True),
            geometry_artifact="layout_v2_selected.json",
            accesses_payload=accesses,
        )
        .payload
    )
    assert net.status == "SUCCESS", net.failure_reason
    types = {n.id: n.type.value for n in net.nodes}
    for e in net.edges:
        if e.type.value in ("DRIFT", "CROSSCUT"):
            assert types[e.from_node] not in ("RAMP_JUNCTION", "RAMP_END")
            assert types[e.to_node] not in ("RAMP_JUNCTION", "RAMP_END")
        if e.type.value == "LEVEL_ACCESS":
            assert types[e.from_node] == "RAMP_JUNCTION" and types[e.to_node] == "LEVEL_ENTRY"
    assert net.metrics is not None and net.metrics.level_access_edge_count == len(
        accesses["accesses"]
    )


def test_cut_and_fill_generic_backbone_is_independent_of_longhole_parameters(
    tabular: tuple[Scenario, SyntheticWorld],
) -> None:
    """Rule 159 regression: ``stope_length`` / ``minimum_pillar`` are LONGHOLE
    production parameters. Changing them must not move the CUT_AND_FILL
    generic backbone drift (same pieces, same extent, same length), while the
    production portion stays UNSUPPORTED_METHOD with zero crosscuts."""
    sc, world = tabular

    def scenario_with(stope_length: float, minimum_pillar: float) -> Scenario:
        return sc.model_copy(
            update={
                "mining": sc.mining.model_copy(
                    update={
                        "method": MiningMethodType.CUT_AND_FILL,
                        "stope_length": stope_length,
                        "minimum_pillar": minimum_pillar,
                    }
                )
            }
        )

    def generic_levels(caf: Scenario):  # type: ignore[no-untyped-def]
        s = LayoutV2Search(caf, world)
        res = s.run()
        w = _winner(s, res)
        ramp = materialize_effective_ramp(res, w, s.evaluator, "r")
        accesses = materialize_level_accesses(res, w, "r", "CUT_AND_FILL")
        payload = _levels_builder(caf, world).build(
            ramp, "r", entries=entries_from_level_accesses(accesses)
        )
        assert payload.status == "SUCCESS", payload.failure_reason
        assert payload.production_development is not None
        assert payload.production_development.status == "UNSUPPORTED_METHOD"
        assert payload.metrics is not None and payload.metrics.crosscut_count == 0
        return payload

    a = generic_levels(scenario_with(20.0, 5.0))
    b = generic_levels(scenario_with(50.0, 15.0))
    assert [d.id for d in a.developments] == [d.id for d in b.developments]
    for da, db in zip(a.developments, b.developments, strict=True):
        assert da.kind.value == "DRIFT" and db.kind.value == "DRIFT"
        assert math.isclose(da.from_u, db.from_u, abs_tol=1e-9)
        assert math.isclose(da.to_u, db.to_u, abs_tol=1e-9)
        assert math.isclose(da.length3d, db.length3d, abs_tol=1e-9)
        np.testing.assert_allclose(da.centerline.points, db.centerline.points, atol=1e-9)
    assert a.metrics is not None and b.metrics is not None
    assert math.isclose(a.metrics.total_drift_length3d, b.metrics.total_drift_length3d)
    # the generic extent is the strike extent minus the fixed end clearance —
    # never ``stope_length/2 + minimum_pillar``
    ob = world.orebody
    lo, hi = LevelDevelopmentBuilder.generic_backbone_extent(ob)  # type: ignore[arg-type]
    assert math.isclose(lo, -ob.half_length + 5.0) and math.isclose(hi, ob.half_length - 5.0)  # type: ignore[attr-defined]
    for d in a.developments:
        assert lo - 1e-9 <= d.from_u <= d.to_u <= hi + 1e-9
    assert min(d.from_u for d in a.developments) == pytest.approx(lo)
    assert max(d.to_u for d in a.developments) == pytest.approx(hi)
    # LONGHOLE remains parameter-dependent: its lattice is production geometry
    longhole = sc.model_copy(
        update={
            "mining": sc.mining.model_copy(update={"stope_length": 20.0, "minimum_pillar": 5.0})
        }
    )
    stations_20 = _levels_builder(longhole, world).station_us(ob)  # type: ignore[arg-type]
    stations_30 = _levels_builder(sc, world).station_us(ob)  # type: ignore[arg-type]
    assert stations_20 != stations_30


# --------------------------------------------------------------------------- #
# closeout v3 §2: preferred access length
# --------------------------------------------------------------------------- #


def test_preferred_access_length_default_and_validation() -> None:
    from pydantic import ValidationError

    from minegen.core.models import LevelAccessConfig, RampConstraints

    ramp = RampConstraints()
    cfg = LevelAccessConfig()
    p, source = effective_preferred_access_length(cfg, ramp)
    assert source == "DEFAULT_6X_TUNNEL_WIDTH"
    assert p == max(cfg.minimum_access_length, 6.0 * ramp.tunnel_width) == 30.0
    # narrower tunnels: 3.5 m → 21 m, 4.5 m → 27 m; the hard floor wins below it
    assert effective_preferred_access_length(cfg, ramp.model_copy(update={"tunnel_width": 3.5}))[
        0
    ] == pytest.approx(21.0)
    assert effective_preferred_access_length(cfg, ramp.model_copy(update={"tunnel_width": 4.5}))[
        0
    ] == pytest.approx(27.0)
    assert effective_preferred_access_length(cfg, ramp.model_copy(update={"tunnel_width": 2.0}))[
        0
    ] == pytest.approx(cfg.minimum_access_length)
    # explicit value: validated inside [min, max], never clamped
    explicit = LevelAccessConfig(preferred_access_length=25.0)
    assert effective_preferred_access_length(explicit, ramp) == (25.0, "EXPLICIT")
    with pytest.raises(ValidationError):
        LevelAccessConfig(preferred_access_length=10.0)
    with pytest.raises(ValidationError):
        LevelAccessConfig(preferred_access_length=500.0)
    with pytest.raises(ValidationError):
        LevelAccessConfig(minimum_access_length=50.0, maximum_access_length=40.0)
    # the hard floor is untouched by the preferred length
    assert LevelAccessConfig().minimum_access_length == 15.0
    # selection cost: symmetric below, extra-penalized above the preferred length
    assert access_length_cost(30.0, 30.0) == 0.0
    assert access_length_cost(20.0, 30.0) == pytest.approx(10.0)
    assert access_length_cost(40.0, 30.0) == pytest.approx(10.0 + LONG_ACCESS_COEF * 10.0)
    assert access_length_cost(40.0, 30.0, 1.0) == pytest.approx(20.0)


def test_selection_targets_the_preferred_length_instead_of_the_hard_floor(
    tabular: tuple[Scenario, SyntheticWorld], search: tuple[LayoutV2Search, LayoutSearchResult]
) -> None:
    sc, world = tabular
    s, res = search
    _, plan = _plan(sc, world, s, res)
    assert plan.feasible and plan.preferred_length == 30.0
    assert plan.preferred_source == "DEFAULT_6X_TUNNEL_WIDTH"
    ok = [a for a in plan.accesses if a.ok]
    floor = sc.layout.access.minimum_access_length
    # closeout v3 §2 established the preferred-length objective against the
    # floor-hugging shortest-first one. Since 20B.1 commit C the corridor
    # margin makes the SHORTEST feasible branch itself exceed both the floor
    # and the preferred length in this fixture, so the two objectives select
    # identically here — the preferred objective must never be WORSE, and no
    # branch can hug the old 15 m floor at all.
    _, shortest = _plan(sc, world, s, res, preferred_access_length=floor)
    ok_short = [a for a in shortest.accesses if a.ok]
    mean_short = float(np.mean([a.length3d for a in ok_short]))
    mean_pref = float(np.mean([a.length3d for a in ok]))
    assert mean_pref >= mean_short
    assert float(np.mean([abs(a.length3d - 30.0) for a in ok])) <= float(
        np.mean([abs(a.length3d - 30.0) for a in ok_short])
    )
    assert min(a.length3d for a in ok) > floor + 2.0  # nothing on the floor
    # every selected branch still honours every hard limit
    for a in ok:
        assert floor <= a.length3d <= sc.layout.access.maximum_access_length
        assert a.max_gradient <= plan.max_gradient_limit + 1e-9
        assert a.preferred_length == 30.0
        assert a.length_deviation == pytest.approx(a.length3d - 30.0)
        assert a.selection_cost == pytest.approx(access_length_cost(a.length3d, 30.0))
    summary = plan.summary()
    assert summary["effectivePreferredAccessLength"] == 30.0
    assert summary["preferredAccessSource"] == "DEFAULT_6X_TUNNEL_WIDTH"
    assert summary["longAccessCoefficient"] == LONG_ACCESS_COEF
    assert summary["meanAbsDeviationFromPreferred"] is not None
    d = plan.to_dict()["accesses"][0]
    assert {
        "effectivePreferredAccessLength",
        "lengthDeviationFromPreferred",
        "selectionCost",
    } <= set(d)


def test_preferred_selection_is_deterministic(
    tabular: tuple[Scenario, SyntheticWorld], search: tuple[LayoutV2Search, LayoutSearchResult]
) -> None:
    sc, world = tabular
    s, res = search
    _, a = _plan(sc, world, s, res)
    _, b = _plan(sc, world, s, res)
    for x, y in zip(a.accesses, b.accesses, strict=True):
        assert (x.junction_chainage, x.terminal_heading, x.length3d, x.connector_word) == (
            y.junction_chainage,
            y.terminal_heading,
            y.length3d,
            y.connector_word,
        )
    assert a.to_dict() == b.to_dict()


# --------------------------------------------------------------------------- #
# Phase 20B.1 commit O — separation observability (reporting only)
# --------------------------------------------------------------------------- #


def test_separation_metrics_on_synthetic_geometry() -> None:
    """The four O-1 metrics and the O-2 turnout diagnostic on hand-built
    geometry with known answers. Since 20B.1-v2 1.2 the excavation
    separation is the DIRECTION-AWARE profile-support gap at the closest
    centerline pair: this branch drives straight AWAY from the ramp, so the
    direction to the ramp runs along the branch's own axis (its cross-section
    has no support there) while the ramp's profile contributes its lateral
    half-span — ``d − 0 − width/2``. The first SEPARATION_TAPER_EXCLUSION_ARC
    metres of the branch are excluded."""
    from minegen.layout.access import (
        SEPARATION_TAPER_EXCLUSION_ARC,
        LevelAccess,
        fill_separation_metrics,
        min_distance_to_polyline,
        turnout_heading_change_deg,
    )
    from minegen.layout.geometry import chainage

    # straight ramp along +Y, descending at 0.12
    y = np.arange(0.0, 200.0 + 1e-9, 5.0)
    ramp = np.column_stack([np.zeros_like(y), y, -0.12 * y])
    ramp_ch = chainage(ramp)
    j = ramp[20].copy()  # y = 100
    # branch: straight line perpendicular to the ramp, 30 m to +X at level z
    n = 16
    t = np.linspace(0.0, 1.0, n)
    entry = j + np.array([30.0, 0.0, 0.0])
    pts = j[None, :] + t[:, None] * (entry - j)[None, :]
    access = LevelAccess(
        "L01",
        float(entry[2]),
        "OK",
        None,
        junction_chainage=float(ramp_ch[20]),
        junction_position=j,
        points=pts,
    )
    fill_separation_metrics(access, ramp, ramp_ch, SHAPE)
    assert access.junction_to_entry_plan_sep == pytest.approx(30.0)
    assert access.junction_to_entry_dist3d == pytest.approx(30.0)
    # nearest far-sample to the ramp is the first sample at arc >= exclusion
    arc = chainage(pts)
    far = pts[arc >= SEPARATION_TAPER_EXCLUSION_ARC]
    expected = float(np.min(min_distance_to_polyline(far, ramp)))
    assert access.ramp_centerline_distance == pytest.approx(expected)
    assert expected == pytest.approx(float(far[0, 0]), abs=0.2)  # ~ its x offset
    assert access.excavation_separation == pytest.approx(expected - 2.5, abs=0.05)
    # straight ramp: zero heading change through the turnout window
    assert access.turnout_heading_change_deg == pytest.approx(0.0, abs=1e-9)

    # turnout inside a curve: an R = 18 m arc accumulates ~2*25/18 rad over
    # the +-25 m window (the arc is 72 m long so the window never truncates)
    ang = np.linspace(0.0, 4.0, 321)  # rad along the arc
    arc_pts = np.column_stack([18.0 * np.sin(ang), 18.0 * (1 - np.cos(ang)), -2.16 * ang])
    arc_ch = chainage(arc_pts)
    mid = float(arc_ch[160])
    got = turnout_heading_change_deg(arc_pts, arc_ch, mid)
    assert got == pytest.approx(math.degrees(50.0 / 18.0), rel=0.05)

    # branch shorter than the taper exclusion (commit B): the TERMINAL is
    # always judged, so a 6 m stub reports its entry separation (its entry is
    # 6 m off the ramp -> direction-aware gap 6 − 0 − 2.5 = 3.5 m), never
    # None and never 0
    short = LevelAccess(
        "L02",
        0.0,
        "OK",
        None,
        junction_chainage=float(ramp_ch[20]),
        junction_position=j,
        points=pts[:4],  # 6 m
    )
    fill_separation_metrics(short, ramp, ramp_ch, SHAPE)
    assert short.ramp_centerline_distance == pytest.approx(6.0, abs=0.05)
    assert short.excavation_separation == pytest.approx(3.5, abs=0.05)
    assert short.junction_to_entry_plan_sep == pytest.approx(6.0)


def test_separation_metrics_reported_for_every_selected_access(
    tabular: tuple[Scenario, SyntheticWorld], search: tuple[LayoutV2Search, LayoutSearchResult]
) -> None:
    """O-1/O-3: every OK access of a real plan carries the four metrics and
    the payload / summary expose them; the metrics never gate feasibility in
    commit O (an access with a sub-width pillar is still OK here)."""
    sc, world = tabular
    s, res = search
    _, plan = _plan(sc, world, s, res)
    assert plan.feasible
    for a in plan.accesses:
        assert a.junction_to_entry_plan_sep is not None and a.junction_to_entry_plan_sep > 0.0
        assert a.junction_to_entry_dist3d is not None
        assert a.junction_to_entry_dist3d >= a.junction_to_entry_plan_sep - 1e-9
        assert a.turnout_heading_change_deg is not None
        assert a.turnout_heading_change_deg >= 0.0
        assert a.excavation_separation is not None
        assert a.ramp_centerline_distance is not None
        # direction-aware gap: never larger than the centerline distance and
        # never more than two profile reaches (5 m each) below it
        assert a.excavation_separation <= a.ramp_centerline_distance + 1e-9
        assert a.excavation_separation >= a.ramp_centerline_distance - 10.0 - 1e-9
        d = a.to_dict(include_points=False)
        assert {
            "junctionToEntryPlanSep",
            "junctionToEntryDist3d",
            "rampCenterlineDistance",
            "excavationSeparation",
            "turnoutHeadingChangeDeg",
        } <= set(d)
    summary = plan.summary()
    assert summary["minJunctionToEntryPlanSep"] is not None
    assert summary["minExcavationSeparation"] is not None
    assert summary["maxTurnoutHeadingChangeDeg"] is not None


# --------------------------------------------------------------------------- #
# Phase 20B.1 commit B — hard separation / pillar / turnout gates
# --------------------------------------------------------------------------- #


def test_gate_taper_arc_closed_form() -> None:
    from minegen.layout.access import gate_taper_arc

    # lateral within one turn: R * arccos(1 - l/R)
    assert gate_taper_arc(18.0, 15.0) == pytest.approx(18.0 * math.acos(1.0 - 15.0 / 18.0))
    assert gate_taper_arc(18.0, 0.0) == 0.0
    # beyond one radius: quarter turn then perpendicular straight
    assert gate_taper_arc(18.0, 40.0) == pytest.approx(18.0 * math.pi / 2.0 + 22.0)
    # monotone in the lateral requirement
    assert gate_taper_arc(18.0, 10.0) < gate_taper_arc(18.0, 15.0) < gate_taper_arc(18.0, 20.0)


def test_selected_accesses_satisfy_every_hard_gate(
    tabular: tuple[Scenario, SyntheticWorld], search: tuple[LayoutV2Search, LayoutSearchResult]
) -> None:
    """B-6: every SELECTED access of the winner plan honours the resolved
    gates — plan separation, rock pillar (beyond the geometric taper,
    terminal included) and turnout curvature."""
    from minegen.layout.access import SEPARATION_TOLERANCE

    sc, world = tabular
    s, res = search
    _, plan = _plan(sc, world, s, res)
    assert plan.feasible
    assert plan.plan_separation_required == pytest.approx(6.0 * sc.ramp.tunnel_width)
    assert plan.excavation_separation_required == pytest.approx(2.0 * sc.ramp.tunnel_width)
    assert plan.gate_taper_arc_m is not None and plan.gate_taper_arc_m > 0.0
    for a in plan.accesses:
        assert a.ok
        assert a.junction_to_entry_plan_sep is not None
        assert a.junction_to_entry_plan_sep >= plan.plan_separation_required - SEPARATION_TOLERANCE
        assert a.excavation_separation is not None
        assert a.excavation_separation >= plan.excavation_separation_required - SEPARATION_TOLERANCE
        assert a.turnout_heading_change_deg is not None
        assert (
            a.turnout_heading_change_deg
            <= sc.layout.access.maximum_turnout_heading_change_deg + 1e-6
        )
    summary = plan.summary()
    assert summary["minimumPlanSeparationRequired"] == plan.plan_separation_required
    assert summary["minimumExcavationSeparationRequired"] == plan.excavation_separation_required
    assert summary["gateTaperArc"] == plan.gate_taper_arc_m


def test_hard_gates_reject_with_typed_reasons(
    tabular: tuple[Scenario, SyntheticWorld], search: tuple[LayoutV2Search, LayoutSearchResult]
) -> None:
    sc, world = tabular
    s, res = search
    # B-2: an impossible pillar demand fails typed, never clamped
    _, plan = _plan(sc, world, s, res, minimum_excavation_separation=200.0)
    assert not plan.feasible
    failed = [a for a in plan.accesses if not a.ok]
    assert failed
    assert all(
        a.rejection_counts.get(AccessFailure.INSUFFICIENT_RAMP_PILLAR, 0) > 0
        or a.failure_reason == AccessFailure.INSUFFICIENT_RAMP_PILLAR
        for a in failed
    )
    # B-1: an impossible plan-separation demand fails typed
    _, plan = _plan(sc, world, s, res, minimum_ramp_to_entry_plan_separation=299.0)
    assert not plan.feasible
    failed = [a for a in plan.accesses if not a.ok]
    assert failed
    assert any(
        a.rejection_counts.get(AccessFailure.INSUFFICIENT_RAMP_TO_ENTRY_SEPARATION, 0) > 0
        for a in failed
    )
    # B-3: a near-zero curvature tolerance rejects in-curve junctions typed;
    # any access that still succeeds sits in genuinely straight chainage
    _, plan = _plan(sc, world, s, res, maximum_turnout_heading_change_deg=1e-3)
    for a in plan.accesses:
        if a.ok:
            assert a.turnout_heading_change_deg is not None
            assert a.turnout_heading_change_deg <= 1e-3 + 1e-6
        else:
            assert a.rejection_counts.get(AccessFailure.TURNOUT_NOT_STRAIGHT, 0) > 0


def test_starvation_diagnostic_distinguishes_greedy_from_geometry(
    tabular: tuple[Scenario, SyntheticWorld], search: tuple[LayoutV2Search, LayoutSearchResult]
) -> None:
    """B-5: with an absurd junction-spacing rule the FIRST level consumes the
    whole ramp; deeper levels fail on JUNCTION_SPACING_CONFLICT and the
    diagnostic re-run (ignoring only the used spacing) proves valid
    candidates exist — assignment starvation, not geometry. Nothing is
    relaxed for the recorded result."""
    sc, world = tabular
    s, res = search
    _, plan = _plan(sc, world, s, res, minimum_ramp_junction_spacing=5000.0)
    assert not plan.feasible
    ok = [a for a in plan.accesses if a.ok]
    starved = [
        a for a in plan.accesses if a.failure_reason == AccessFailure.JUNCTION_SPACING_CONFLICT
    ]
    assert ok and starved
    for a in starved:
        d = a.assignment_diagnostic
        assert d is not None
        assert d["starvationSuspected"] is True
        assert d["validCandidatesIgnoringSpacing"] > 0
    # a level that fails WITHOUT any spacing conflict carries no diagnostic
    _, plan_geo = _plan(sc, world, s, res, minimum_excavation_separation=200.0)
    for a in plan_geo.accesses:
        if not a.ok and a.rejection_counts.get(AccessFailure.JUNCTION_SPACING_CONFLICT, 0) == 0:
            assert a.assignment_diagnostic is None


# --------------------------------------------------------------------------- #
# Phase 20B.1-v2 1.2 — direction-aware rock-pillar support
# --------------------------------------------------------------------------- #


def _line(x: float, z: float, n: int = 41, length: float = 200.0, grade: float = 0.0) -> np.ndarray:
    y = np.linspace(0.0, length, n)
    return np.column_stack([np.full_like(y, x), y, z - grade * y])


def test_directional_support_horizontal_parallel_matches_width_rule() -> None:
    """A: two horizontal parallel drives 15 m apart read width/2 + width/2 —
    the former fixed rule is preserved exactly where it was right."""
    from minegen.layout.access import gated_separation

    ramp, branch = _line(0.0, 0.0), _line(15.0, 0.0)
    d, gap = gated_separation(branch, ramp, SHAPE, taper_arc=0.0)
    assert d == pytest.approx(15.0)
    assert gap == pytest.approx(15.0 - 2.5 - 2.5)


def test_directional_support_vertically_stacked_is_stricter_than_width_rule() -> None:
    """B: a drive 12 m BELOW another one: the lower profile reaches
    ``height`` up to the upper floor centerline, which has no downward
    extent — ``height + 0``. With a 6 m high profile that is 6 m of rock,
    stricter than the fixed-width rule's 7 m and far less pessimistic than
    the forbidden isotropic ``2·hypot(width/2, height)`` (−1 m)."""
    from minegen.layout.access import gated_separation

    tall = build_profile(RampConstraints(tunnel_width=5.0, tunnel_height=6.0), TunnelProfile())
    upper, lower = _line(0.0, 0.0), _line(0.0, -12.0)
    d, gap = gated_separation(lower, upper, tall, taper_arc=0.0)
    assert d == pytest.approx(12.0)
    assert gap == pytest.approx(12.0 - 6.0 - 0.0)
    assert gap < 12.0 - 5.0  # stricter than the old "− tunnel_width"
    assert gap > 12.0 - 2.0 * math.hypot(2.5, 6.0)  # never the isotropic bound
    # the branch ABOVE the ramp reads the same rock: 0 + height
    d2, gap2 = gated_separation(upper, lower, tall, taper_arc=0.0)
    assert d2 == pytest.approx(12.0) and gap2 == pytest.approx(gap)


def test_directional_support_follows_the_gravity_frame_on_a_slope() -> None:
    """C: a sloped access stacked under a sloped ramp. The closest-pair
    direction of two parallel sloped drives is their common normal — the
    gravity frame's ``up`` — along which the lower profile's support is the
    full ``height``; along TRUE vertical the same profile only reaches
    ``height·cos(slope)``. The support therefore depends on the tangent's
    gravity frame, and the gate reads the frame-correct value."""
    from minegen.layout.access import gated_separation, profile_support

    g = 0.12
    upper, lower = _line(0.0, 0.0, grade=g), _line(0.0, -12.0, grade=g)
    d, gap = gated_separation(lower, upper, SHAPE, taper_arc=0.0)
    cos_slope = 1.0 / math.hypot(1.0, g)
    # the vertical separation of two parallel sloped lines is measured along
    # the common normal: d = 12·cos(slope)
    assert d == pytest.approx(12.0 * cos_slope, abs=1e-6)
    t = np.array([[0.0, 1.0, -g]]) / math.hypot(1.0, g)
    up_support = profile_support(SHAPE, t, np.array([[0.0, 0.0, 1.0]]))
    assert up_support[0] == pytest.approx(5.0 * cos_slope, rel=1e-9)
    assert up_support[0] < 5.0
    # along the common normal (the frame's up) the support is the full height
    frame_up = np.array([[0.0, g, 1.0]]) / math.hypot(1.0, g)
    assert profile_support(SHAPE, t, frame_up)[0] == pytest.approx(5.0, rel=1e-9)
    assert gap == pytest.approx(d - 5.0 - 0.0, abs=1e-6)


def test_directional_support_is_symmetric_in_the_pair() -> None:
    """Swapping branch and ramp on identically sampled parallel lines gives
    the same gap (the support pair is evaluated on the same closest points)."""
    from minegen.layout.access import gated_separation

    a, b = _line(0.0, 0.0), _line(9.0, -4.0)
    assert gated_separation(a, b, SHAPE, 0.0) == pytest.approx(gated_separation(b, a, SHAPE, 0.0))


def test_pillar_gate_uses_the_directional_support(
    tabular: tuple[Scenario, SyntheticWorld], search: tuple[LayoutV2Search, LayoutSearchResult]
) -> None:
    """The B-2 gate and the reported metric share the direction-aware
    definition: every selected access of the reference plan reports a gap
    at/above the floor, computed by ``gated_separation`` on its own points."""
    from minegen.layout.access import SEPARATION_TOLERANCE, gated_separation

    sc, world = tabular
    s, res = search
    _, plan = _plan(sc, world, s, res)
    assert plan.feasible and plan.excavation_separation_required is not None
    winner = res.candidate(res.winner_id or "")
    assert winner is not None and winner.points is not None
    for a in plan.accesses:
        assert a.points is not None and a.excavation_separation is not None
        assert plan.gate_taper_arc_m is not None
        _, gap = gated_separation(a.points, winner.points, SHAPE, plan.gate_taper_arc_m)
        assert a.excavation_separation == pytest.approx(gap)
        assert gap >= plan.excavation_separation_required - SEPARATION_TOLERANCE - 1e-9
