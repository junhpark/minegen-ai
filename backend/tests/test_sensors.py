"""Phase 12 sensor OSP tests (rules 93–98): pinned greedy fixture, the
mandatory through-rock regression, coverage-model contract + injection,
solver behaviour, hard gates and API sibling invalidation."""

from __future__ import annotations

import json

import numpy as np
import pytest

from minegen.core.models import InfrastructureConfig, SensorConfig
from minegen.infrastructure.coverage import NetworkDistanceMonitoringThresholdModel
from minegen.infrastructure.models import (
    CandidateSite,
    CoveragePlacementProblem,
    DemandPoint,
)
from minegen.infrastructure.sensors import SensorBuilder
from minegen.infrastructure.solver import solve_greedy_set_cover
from tests.test_communication import _straight_fixture, _u_fixture
from tests.test_levels import _setup


def _scenario(tmp_path, **sensors):  # type: ignore[no-untyped-def]
    sc, _world, _builder = _setup(tmp_path)
    sc.infrastructure = InfrastructureConfig(sensors=SensorConfig(**sensors))
    return sc


def _build(sc, network, smoothed, levels, model=None):  # type: ignore[no-untyped-def]
    return SensorBuilder(sc, coverage_model=model).build(network, smoothed, levels, "rev")


def test_straight_fixture_three_sensor_pin(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """§35: independent derivation under the frozen sampling + greedy
    tie-break contract. Coverage 60 m gains: P2/P3/P4 tie at 7 -> lexicographic
    P2(80); remaining max is P5(200) with 5 (160..240); the final uncovered
    portal demand {0} ties P1 vs NODE:PORTAL at gain 1 and 'E' < 'N' picks
    P1(40). Expected: exactly {P1, P2, P5}."""
    sc = _scenario(
        tmp_path,
        candidateSpacingM=40.0,
        demandSpacingM=20.0,
        monitoringRangeM=60.0,
        requiredCoverageFraction=1.0,
    )
    network, smoothed, levels = _straight_fixture()
    p = _build(sc, network, smoothed, levels)
    assert p.status == "SUCCESS", p.failure_reason
    m = p.metrics
    assert m is not None
    assert m.candidate_count == 7
    assert m.demand_count == 13
    assert m.selected_sensor_count == 3
    assert m.coverage_fraction == 1.0
    assert sorted(a.candidate_id for a in p.selected_sensors) == [
        "SENSOR:CAND:EDGE:RAMP:X:P1",
        "SENSOR:CAND:EDGE:RAMP:X:P2",
        "SENSOR:CAND:EDGE:RAMP:X:P5",
    ]
    for a in p.selected_sensors:
        assert a.asset_type.value == "GAS_SENSOR"
        assert a.id == f"SENSOR:ASSET:{a.candidate_id}"
    # deterministic repeat byte equality
    q = _build(sc, json.loads(json.dumps(network)), dict(smoothed), dict(levels))
    assert json.dumps(p.model_dump(mode="json", by_alias=True)) == json.dumps(
        q.model_dump(mode="json", by_alias=True)
    )


def test_monitoring_never_jumps_through_rock(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """§34 MANDATORY: candidate at PORTAL and demand at node C are ~5 m apart
    through rock but 605 m through tunnels; with monitoringRangeM=100 the
    demand must NOT be covered by the portal-side sensor."""
    network, smoothed, levels = _u_fixture()
    sc = _scenario(tmp_path, monitoringRangeM=100.0, requiredCoverageFraction=0.15)
    p = _build(sc, network, smoothed, levels)
    assert p.status == "SUCCESS", p.failure_reason
    # low target => greedy selects one max-gain sensor somewhere on the U;
    # regardless of which, C-side coverage can only come from C-side sensors
    cov = {r.demand_id: r for r in p.demand_coverage}
    for row in p.demand_coverage:
        if not row.covered:
            continue
        serving = next(s for s in p.selected_sensors if s.id == row.serving_sensor_id)
        assert row.network_distance_m is not None
        assert row.network_distance_m <= 100.0 + 1e-6
    sc2 = _scenario(tmp_path, monitoringRangeM=100.0, requiredCoverageFraction=1.0)
    p2 = _build(sc2, network, smoothed, levels)
    assert p2.status == "SUCCESS", p2.failure_reason
    cov2 = {r.demand_id: r for r in p2.demand_coverage}
    row = cov2["SENSOR:DEMAND:NODE:C"]
    serving = next(s for s in p2.selected_sensors if s.id == row.serving_sensor_id)
    # served through the physical U, never across the 5 m of rock
    assert serving.candidate_id.startswith(
        ("SENSOR:CAND:EDGE:DRIFT:2", "SENSOR:CAND:NODE:C", "SENSOR:CAND:NODE:B")
    )
    assert row.network_distance_m is not None and row.network_distance_m <= 100.0 + 1e-6
    # explicit anti-Euclidean pin: portal-side sensor never serves C
    portal_sensor = "SENSOR:ASSET:SENSOR:CAND:NODE:P"
    assert cov2["SENSOR:DEMAND:NODE:C"].serving_sensor_id != portal_sensor
    assert (
        cov["SENSOR:DEMAND:NODE:C"].covered is False
        or cov["SENSOR:DEMAND:NODE:C"].serving_sensor_id != portal_sensor
    )


def test_monitoring_threshold_model_contract() -> None:
    """§37: inside / exactly at / +1e-6 tolerance / outside; sorted ids."""
    model = NetworkDistanceMonitoringThresholdModel(monitoring_range_m=60.0)
    assert model.model_id == "NETWORK_DISTANCE_MONITORING_THRESHOLD_V0_1"
    cand = ["C1"]
    dem = ["D4", "D1", "D2", "D3"]
    dist = np.array([[59.0, 60.0, 60.0 + 5e-7, 60.0 + 1e-5]])
    cov = model.coverage_sets(cand, dem, dist)
    assert cov == {"C1": ["D1", "D2", "D4"]}  # sorted, tolerance honoured


def test_builder_consumes_sensor_coverage_model(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """§22: injected strategy output changes the placement — one candidate
    covering everything yields exactly that candidate, which the default
    threshold contract (3 sensors) could never produce."""

    class _OnlyP3CoversAll:
        model_id = "STUB_SENSOR_MODEL"

        def coverage_sets(self, candidate_ids, demand_ids, candidate_demand_distance):  # type: ignore[no-untyped-def]
            return {
                cid: (sorted(demand_ids) if cid == "SENSOR:CAND:EDGE:RAMP:X:P3" else [])
                for cid in candidate_ids
            }

    sc = _scenario(
        tmp_path,
        candidateSpacingM=40.0,
        demandSpacingM=20.0,
        monitoringRangeM=60.0,
    )
    network, smoothed, levels = _straight_fixture()
    p = _build(sc, network, smoothed, levels, model=_OnlyP3CoversAll())
    assert p.status == "SUCCESS", p.failure_reason
    assert [a.candidate_id for a in p.selected_sensors] == ["SENSOR:CAND:EDGE:RAMP:X:P3"]
    assert p.model is not None and p.model.coverage_model == "STUB_SENSOR_MODEL"


def _cand(cid):  # type: ignore[no-untyped-def]
    return CandidateSite(id=cid, location_kind="NODE", node_id=cid, position=(0.0, 0.0, 0.0))


def _dem(did):  # type: ignore[no-untyped-def]
    return DemandPoint(id=did, location_kind="NODE", node_id=did, position=(0.0, 0.0, 0.0))


def test_greedy_set_cover_solver_units() -> None:
    """§36: tie-break, no double selection, fraction<1 stop, infeasible."""
    tie = CoveragePlacementProblem(
        candidates=[_cand("B"), _cand("A")],
        demands=[_dem("d1"), _dem("d2")],
        candidate_coverage_sets={"A": ["d1"], "B": ["d2"]},
        required_coverage_fraction=0.5,
    )
    sol = solve_greedy_set_cover(tie)
    assert sol.status == "SUCCESS" and sol.selected_candidate_ids == ["A"]  # lexicographic
    full = CoveragePlacementProblem(
        candidates=[_cand("B"), _cand("A")],
        demands=[_dem("d1"), _dem("d2")],
        candidate_coverage_sets={"A": ["d1"], "B": ["d2"]},
        required_coverage_fraction=1.0,
    )
    sol = solve_greedy_set_cover(full)
    assert sol.selected_candidate_ids == ["A", "B"]  # never selected twice
    infeasible = CoveragePlacementProblem(
        candidates=[_cand("A")],
        demands=[_dem("d1"), _dem("d2")],
        candidate_coverage_sets={"A": ["d1"]},
        required_coverage_fraction=1.0,
    )
    sol = solve_greedy_set_cover(infeasible)
    assert sol.status == "FAILED"
    assert sol.failure_reason == "INFEASIBLE_SENSOR_COVERAGE"
    assert sol.covered_demand_ids == ["d1"]


def test_partial_target_stops_early(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sc = _scenario(tmp_path, monitoringRangeM=60.0, requiredCoverageFraction=0.5)
    network, smoothed, levels = _straight_fixture()
    p = _build(sc, network, smoothed, levels)
    assert p.status == "SUCCESS", p.failure_reason
    m = p.metrics
    assert m is not None
    assert 0.5 <= m.coverage_fraction < 1.0
    assert m.selected_sensor_count == 1  # single max-gain sensor reaches 7/13
    uncovered = [r for r in p.demand_coverage if not r.covered]
    assert all(r.serving_sensor_id is None for r in uncovered)
    assert m.uncovered_demand_count == len(uncovered) > 0


def test_assignment_nearest_and_tie_by_sensor_id(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sc = _scenario(tmp_path, monitoringRangeM=60.0)
    network, smoothed, levels = _straight_fixture()
    p = _build(sc, network, smoothed, levels)
    assert p.status == "SUCCESS", p.failure_reason
    cov = {r.demand_id: r for r in p.demand_coverage}
    # demand at 100 m: P2(80) is 20 m, P1(40) is 60 m -> nearest eligible P2
    assert cov["SENSOR:DEMAND:EDGE:RAMP:X:P5"].serving_sensor_id == (
        "SENSOR:ASSET:SENSOR:CAND:EDGE:RAMP:X:P2"
    )
    assert cov["SENSOR:DEMAND:EDGE:RAMP:X:P5"].network_distance_m == pytest.approx(20.0)
    # demand at 60 m is exactly 20 m from P1(40) and 20 m from P2(80):
    # equal distance -> lexicographically smallest sensor asset id (P1)
    assert cov["SENSOR:DEMAND:EDGE:RAMP:X:P3"].serving_sensor_id == (
        "SENSOR:ASSET:SENSOR:CAND:EDGE:RAMP:X:P1"
    )


def test_unsupported_asset_and_edge_types(tmp_path) -> None:  # type: ignore[no-untyped-def]
    network, smoothed, levels = _straight_fixture()
    sc = _scenario(tmp_path, assetType="CAMERA")
    p = _build(sc, network, smoothed, levels)
    assert p.status == "FAILED"
    assert "UNSUPPORTED_SENSOR_ASSET_TYPE" in (p.failure_reason or "")
    sc = _scenario(tmp_path)
    shaft = json.loads(json.dumps(network))
    shaft["edges"][0]["type"] = "SHAFT"
    p = _build(sc, shaft, smoothed, levels)
    assert p.status == "FAILED"
    assert "UNSUPPORTED_SENSOR_EDGE_TYPE" in (p.failure_reason or "")
    # domain failures map to typed FAILED through the sensor builder too
    bad = json.loads(json.dumps(network))
    bad["edges"][0]["geometryRef"]["segmentIndex"] = 9
    p = _build(sc, bad, smoothed, levels)
    assert p.status == "FAILED" and "out of range" in (p.failure_reason or "")


def test_infeasible_sensor_coverage_is_typed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The candidateSpacingM <= 2*monitoringRangeM lattice validator makes
    geometric infeasibility unreachable under a VALID config (every interior
    demand is within s/2 <= r of a candidate), which is exactly the §3
    feasibility guarantee — so builder-level infeasibility is exercised via
    a zero-coverage strategy, proving the solver failure propagates typed."""
    # config validator itself rejects an infeasible lattice
    with pytest.raises(Exception, match="2 \\* monitoringRangeM"):
        SensorConfig(candidateSpacingM=90.0, monitoringRangeM=5.0)

    class _CoversNothing:
        model_id = "STUB_EMPTY"

        def coverage_sets(self, candidate_ids, demand_ids, candidate_demand_distance):  # type: ignore[no-untyped-def]
            return {cid: [] for cid in candidate_ids}

    sc = _scenario(tmp_path)
    network, smoothed, levels = _straight_fixture()
    p = _build(sc, network, smoothed, levels, model=_CoversNothing())
    assert p.status == "FAILED"
    assert p.failure_reason == "INFEASIBLE_SENSOR_COVERAGE"


def test_sensor_api_lifecycle_and_sibling_invalidation(client, design_service) -> None:  # type: ignore[no-untyped-def]
    """§39: 409 chain, persistence, deterministic regeneration and the full
    sibling matrix (stopes/timeline/communication preserve sensors; sensors
    preserve communication/timeline; network/levels delete sensors)."""
    from tests.test_network_api import _levels, _network
    from tests.test_smoothing_api import _decline, _prepare
    from tests.test_timeline import _stopes_api
    from tests.test_tunnel_api import _smooth

    sid = _prepare(client)
    _decline(client, sid)
    _smooth(client, sid)
    _levels(client, sid)
    url = f"/api/v1/scenarios/{sid}/infrastructure/sensors"
    comm_url = f"/api/v1/scenarios/{sid}/infrastructure/communication"
    r = client.post(url)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NETWORK_NOT_GENERATED"
    _network(client, sid)
    r = client.get(url)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SENSORS_NOT_GENERATED"

    r = client.post(url)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "SUCCESS", body["failureReason"]
    assert body["model"]["optimalityClaim"] is False
    assert body["model"]["solver"] == "GREEDY_SET_COVER_V0_1"
    assert client.get(url).json() == body

    derived = design_service.store.derived_dir(sid)
    spath = derived / "sensors.json"
    cpath = derived / "communication.json"
    assert spath.is_file()

    # sensors regeneration preserves communication + timeline + upstream
    assert client.post(comm_url).status_code == 200
    comm_bytes = cpath.read_bytes()
    net_bytes = design_service.network_path(sid).read_bytes()
    assert client.post(url).status_code == 200
    assert cpath.read_bytes() == comm_bytes
    assert design_service.network_path(sid).read_bytes() == net_bytes
    # communication regeneration preserves sensors
    sensors_bytes = spath.read_bytes()
    assert client.post(comm_url).status_code == 200
    assert spath.read_bytes() == sensors_bytes
    # stopes + timeline regeneration preserve sensors
    _stopes_api(client, sid)
    assert spath.is_file()
    r = client.post(f"/api/v1/scenarios/{sid}/design/timeline")
    assert r.status_code == 200
    assert spath.is_file() and spath.read_bytes() == sensors_bytes

    # network regeneration deletes sensors (and communication)
    before = json.loads(spath.read_bytes())
    _network(client, sid)
    assert not spath.exists() and not cpath.exists()
    client.post(url)
    after = json.loads(spath.read_bytes())
    before.pop("sourceRevision")
    after.pop("sourceRevision")
    assert after == before  # deterministic regeneration
    # levels regeneration cascades to sensors
    _levels(client, sid)
    assert not spath.exists()
    r = client.get(url)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SENSORS_NOT_GENERATED"
