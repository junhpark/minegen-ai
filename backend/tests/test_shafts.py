"""Phase 20C.2B shaft planner unit tests (directive §50, rules 182–184).

Built on the cached TABULAR selection (development acceleration, never
release authority — FULL regenerates it): cached Effective Ramp + level
accesses → level development → deterministic shaft planning."""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pytest

from minegen.core.enums import Capability, ShaftRole
from minegen.core.models import (
    Point2D,
    Point3D,
    RestrictedZone,
    Scenario,
    ScenarioCreate,
    ShaftPlanningConfig,
    ShaftSpec,
)
from minegen.design.constraints import DesignContext
from minegen.design.cost_field import DesignCostEvaluator
from minegen.levels.builder import LevelDevelopmentBuilder, entries_from_level_accesses
from minegen.shafts.models import ShaftFailureCode, ShaftsPayload
from minegen.shafts.planner import ShaftPlanner, level_breakpoints
from minegen.world.synthetic_world import SyntheticWorld, generate_world
from tests.verification_support import load_fixture


@pytest.fixture(scope="module")
def tabular_levels() -> tuple[Scenario, SyntheticWorld, dict[str, Any]]:
    fx = load_fixture("tabular_small_selected")
    sc = Scenario(**fx["scenario"])
    world = generate_world(sc)
    drift = DesignCostEvaluator(world, sc.design)
    cross = DesignCostEvaluator(world, sc.design, DesignContext.crosscut(sc.design))
    levels = LevelDevelopmentBuilder(sc, world.orebody, drift, cross).build(
        fx["effectiveRamp"], "rev", entries=entries_from_level_accesses(fx["levelAccesses"])
    )
    assert levels.status == "SUCCESS", levels.failure_reason
    return sc, world, levels.model_dump(mode="json", by_alias=True)


def _plan(
    base: Scenario, world: SyntheticWorld, levels: dict[str, Any], *specs: ShaftSpec, **cfg: Any
) -> ShaftsPayload:
    sc = base.model_copy(update={"shafts": ShaftPlanningConfig(specs=list(specs), **cfg)})
    axis_ev = DesignCostEvaluator(world, sc.design, DesignContext.shaft(sc.design))
    access_ev = DesignCostEvaluator(world, sc.design)
    return ShaftPlanner(sc, world, axis_ev, access_ev).build(levels, "src", "lv")


def _with_design(base: Scenario, world: SyntheticWorld, **design: Any) -> tuple[Scenario, Any]:
    sc = base.model_copy(update={"design": base.design.model_copy(update=design)})
    return sc, DesignCostEvaluator(world, sc.design, DesignContext.shaft(sc.design))


# -- config --------------------------------------------------------------- #


def test_shaft_config_is_optional_and_role_resolves_capabilities() -> None:
    sc = ScenarioCreate()
    assert sc.shafts.specs == []  # no shaft by default (rule 184)
    assert ShaftSpec(role=ShaftRole.VENTILATION).capabilities == [Capability.VENTILATION_PATH]
    assert set(ShaftSpec().capabilities or []) == set(Capability)
    with pytest.raises(ValueError, match="unique"):
        ShaftPlanningConfig(specs=[ShaftSpec(), ShaftSpec()])
    with pytest.raises(ValueError, match="unique"):
        ShaftSpec(capabilities=[Capability.PERSONNEL_ACCESS, Capability.PERSONNEL_ACCESS])


# -- geometry ------------------------------------------------------------- #


def test_vertical_shaft_default_placement_serves_every_developed_level(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    sc, world, levels = tabular_levels
    res = _plan(sc, world, levels, ShaftSpec())
    assert res.status == "SUCCESS", res.failure_reason
    (shaft,) = res.shafts
    assert shaft.status == "OK" and shaft.collar_source == "DEFAULT_DERIVED"
    # vertical axis: collar and bottom share the plan position, collar on terrain
    assert shaft.collar[:2] == shaft.bottom[:2]
    terrain_z = float(world.terrain.sample(np.array([shaft.collar[:2]]))[0])
    assert shaft.collar[2] == pytest.approx(terrain_z)
    assert shaft.collar[2] > shaft.bottom[2]
    # one station per developed level, descending elevation, on the axis
    assert [s.level_id for s in shaft.stations] == [lv["levelId"] for lv in levels["levels"]]
    zs = [s.elevation for s in shaft.stations]
    assert zs == sorted(zs, reverse=True)
    for st in shaft.stations:
        assert st.status == "OK" and st.point[:2] == shaft.collar[:2]
        assert st.connection_target is not None and st.access_centerline_index is not None
        assert st.point[2] == pytest.approx(st.connection_target.position[2])
    # bottom = lowest station − sump
    assert shaft.bottom[2] == pytest.approx(zs[-1] - 10.0)
    # segments collar→STN₁…→bottom in order, station drives owned here too
    segs = [res.centerlines[i] for i in shaft.segment_indices]
    assert [s.kind for s in segs] == ["SHAFT_SEGMENT"] * (len(zs) + 1)
    chain = [segs[0].centerline.points[:3]] + [s.centerline.points[3:] for s in segs]
    assert chain[0] == list(shaft.collar) and chain[-1] == list(shaft.bottom)
    assert [c[2] for c in chain] == sorted((c[2] for c in chain), reverse=True)
    assert shaft.validation is not None and shaft.validation.valid
    assert shaft.metrics is not None
    assert shaft.metrics.depth == pytest.approx(shaft.collar[2] - shaft.bottom[2])
    assert shaft.metrics.nominal_excavation_volume == pytest.approx(
        shaft.profile.analytic_area * shaft.metrics.depth
    )
    assert res.metrics is not None and res.metrics.station_count == len(zs)


def test_station_targets_existing_level_nodes_only(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    sc, world, levels = tabular_levels
    res = _plan(sc, world, levels, ShaftSpec())
    bps = level_breakpoints(levels)
    (shaft,) = res.shafts
    for st in shaft.stations:
        tgt = st.connection_target
        assert tgt is not None
        cands = bps[st.level_id]
        match = [b for b in cands if abs(b.u - tgt.station_u) <= 1e-6]
        assert len(match) == 1  # an EXISTING breakpoint, never a new node
        assert np.allclose(match[0].position, tgt.position)
        # nearest in plan among the level's breakpoints
        d = [float(np.linalg.norm(b.position[:2] - np.asarray(st.point[:2]))) for b in cands]
        assert tgt.plan_distance_to_axis == pytest.approx(min(d))
        # straight drive: 2 points, from the station to the node
        cl = res.centerlines[st.access_centerline_index or 0]
        assert cl.kind == "STATION_ACCESS" and cl.level_id == st.level_id
        assert cl.centerline.points[:3] == list(st.point)
        assert cl.centerline.points[3:] == list(tgt.position)


def test_explicit_collar_and_level_subset(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    sc, world, levels = tabular_levels
    base = _plan(sc, world, levels, ShaftSpec()).shafts[0]
    x, y = base.collar[0] + 5.0, base.collar[1] - 5.0
    res = _plan(sc, world, levels, ShaftSpec(collar=Point2D(x=x, y=y), level_ids=["L02", "L03"]))
    assert res.status == "SUCCESS", res.failure_reason
    (shaft,) = res.shafts
    assert shaft.collar_source == "EXPLICIT" and shaft.collar[:2] == (x, y)
    assert [s.level_id for s in shaft.stations] == ["L02", "L03"]


def test_planning_is_deterministic(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    sc, world, levels = tabular_levels
    a = _plan(sc, world, levels, ShaftSpec()).model_dump(mode="json", by_alias=True)
    b = _plan(sc, world, levels, ShaftSpec()).model_dump(mode="json", by_alias=True)
    a["metrics"].pop("planningSeconds")
    b["metrics"].pop("planningSeconds")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# -- typed failures ------------------------------------------------------- #


def test_collar_outside_world_fails_typed(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    sc, world, levels = tabular_levels
    res = _plan(sc, world, levels, ShaftSpec(collar=Point2D(x=5000.0, y=5000.0)))
    assert res.status == "FAILED"
    (shaft,) = res.shafts
    assert shaft.status == "FAILED"
    assert shaft.failure_code in (
        ShaftFailureCode.SHAFT_TERRAIN_INVALID,
        ShaftFailureCode.SHAFT_COLLAR_OUT_OF_BOUNDS,
    )
    assert shaft.stations == [] and res.centerlines == []


def test_shaft_through_the_orebody_fails_typed(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    sc, world, levels = tabular_levels
    lo, hi = world.orebody.bounding_box()
    # the orebody plan centre: a vertical axis there must cut the dipping body
    cx, cy = 0.5 * (lo[0] + hi[0]), 0.5 * (lo[1] + hi[1])
    res = _plan(sc, world, levels, ShaftSpec(collar=Point2D(x=cx, y=cy)))
    assert res.status == "FAILED"
    (shaft,) = res.shafts
    assert shaft.failure_code in (
        ShaftFailureCode.SHAFT_OREBODY_INTERSECTION,
        ShaftFailureCode.SHAFT_CLEARANCE_VIOLATION,
    )
    assert shaft.validation is not None and not shaft.validation.valid
    assert shaft.validation.rejection_counts  # explicit, never silent


def test_restricted_zone_on_the_axis_fails_typed(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    sc, world, levels = tabular_levels
    base = _plan(sc, world, levels, ShaftSpec()).shafts[0]
    x, y, zc = base.collar
    zone = RestrictedZone(
        name="box",
        min=Point3D(x=x - 3.0, y=y - 3.0, z=zc - 80.0),
        max=Point3D(x=x + 3.0, y=y + 3.0, z=zc - 60.0),
    )
    sc2, _ = _with_design(sc, world, restricted_zones=[zone])
    res = _plan(sc2, world, levels, ShaftSpec(collar=Point2D(x=x, y=y)))
    assert res.status == "FAILED"
    assert res.shafts[0].failure_code is ShaftFailureCode.SHAFT_RESTRICTED_ZONE_INTERSECTION


def test_unknown_required_level_is_a_station_level_mismatch(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    sc, world, levels = tabular_levels
    res = _plan(sc, world, levels, ShaftSpec(level_ids=["L01", "L99"]))
    assert res.status == "FAILED"
    assert res.shafts[0].failure_code is ShaftFailureCode.SHAFT_STATION_LEVEL_MISMATCH
    assert "L99" in (res.shafts[0].failure_reason or "")


def test_station_drive_too_long_fails_the_required_station_and_the_shaft(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    sc, world, levels = tabular_levels
    res = _plan(sc, world, levels, ShaftSpec(), maximum_station_access_length=20.0)
    assert res.status == "FAILED"
    (shaft,) = res.shafts
    assert shaft.failure_code is ShaftFailureCode.SHAFT_STATION_CONNECTION_INFEASIBLE
    failed = [s for s in shaft.stations if s.status == "FAILED"]
    assert failed and all(
        s.failure_code is ShaftFailureCode.SHAFT_STATION_CONNECTION_INFEASIBLE for s in failed
    )
    # diagnostics retained: every station is reported, none silently dropped
    assert len(shaft.stations) == len(levels["levels"])
    assert shaft.validation is not None and shaft.validation.valid  # axis itself is fine


def test_two_shafts_too_close_fail_the_second_typed(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    sc, world, levels = tabular_levels
    base = _plan(sc, world, levels, ShaftSpec()).shafts[0]
    x, y = base.collar[:2]
    res = _plan(
        sc,
        world,
        levels,
        ShaftSpec(shaft_id="SHAFT-01", collar=Point2D(x=x, y=y)),
        ShaftSpec(shaft_id="SHAFT-02", collar=Point2D(x=x + 4.0, y=y), role=ShaftRole.VENTILATION),
    )
    assert res.status == "FAILED"
    by_id = {s.shaft_id: s for s in res.shafts}
    assert by_id["SHAFT-01"].status == "OK"
    assert by_id["SHAFT-02"].failure_code is ShaftFailureCode.SHAFT_GEOMETRY_INVALID


def test_failed_levels_artifact_is_not_consumable(
    tabular_levels: tuple[Scenario, SyntheticWorld, dict[str, Any]],
) -> None:
    sc, world, levels = tabular_levels
    bad = dict(levels)
    bad["status"] = "FAILED"
    res = _plan(sc, world, bad, ShaftSpec())
    assert res.status == "FAILED" and "not consumable" in (res.failure_reason or "")
    assert res.shafts == []
