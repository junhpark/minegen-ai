"""Phase 11 communication OSP tests (rules 87–92): deterministic sampling,
geometry ownership, the mandatory network-vs-Euclidean regression, connected
greedy behaviour, hard gates and API invalidation."""

from __future__ import annotations

import json

import numpy as np
import pytest

from minegen.core.models import CommunicationConfig, InfrastructureConfig
from minegen.infrastructure.builder import CommunicationBuilder
from minegen.infrastructure.models import (
    CandidateSite,
    DemandPoint,
    PlacementProblem,
)
from minegen.infrastructure.solver import solve_connected_greedy
from tests.test_levels import _setup


def _scenario(tmp_path, **comm):  # type: ignore[no-untyped-def]
    sc, _world, _builder = _setup(tmp_path)
    sc.infrastructure = InfrastructureConfig(communication=CommunicationConfig(**comm))
    return sc


def _line_points(a, b, n=25):  # type: ignore[no-untyped-def]
    return np.linspace(np.asarray(a, float), np.asarray(b, float), n).ravel().tolist()


def _straight_fixture():  # type: ignore[no-untyped-def]
    """§32: simple straight 240 m physical network owned by one RAMP segment."""
    network = {
        "status": "SUCCESS",
        "validation": {"connected": True, "synchronized": True},
        "nodes": [
            {"id": "PORTAL", "type": "PORTAL", "position": [0.0, 0.0, 0.0]},
            {"id": "N1", "type": "LEVEL_ENTRY", "position": [240.0, 0.0, 0.0]},
        ],
        "edges": [
            {
                "id": "RAMP:X",
                "type": "RAMP",
                "fromNode": "PORTAL",
                "toNode": "N1",
                "length3d": 240.0,
                "geometryRef": {"artifact": "decline_smoothed.json", "segmentIndex": 0},
            }
        ],
    }
    smoothed = {
        "segments": [{"effectiveCenterline": {"points": _line_points([0, 0, 0], [240, 0, 0])}}]
    }
    levels = {"developments": []}
    return network, smoothed, levels


def _u_fixture():  # type: ignore[no-untyped-def]
    """§31C: folded network — PORTAL and node C are 5 m apart through rock
    but 605 m apart along the physical tunnels."""
    network = {
        "status": "SUCCESS",
        "validation": {"connected": True, "synchronized": True},
        "nodes": [
            {"id": "P", "type": "PORTAL", "position": [0.0, 0.0, 0.0]},
            {"id": "A", "type": "JUNCTION", "position": [300.0, 0.0, 0.0]},
            {"id": "B", "type": "JUNCTION", "position": [300.0, 5.0, 0.0]},
            {"id": "C", "type": "JUNCTION", "position": [0.0, 5.0, 0.0]},
        ],
        "edges": [
            {
                "id": "DRIFT:1",
                "type": "DRIFT",
                "fromNode": "P",
                "toNode": "A",
                "length3d": 300.0,
                "geometryRef": {"artifact": "levels.json", "segmentIndex": 0},
            },
            {
                "id": "CROSSCUT:1",
                "type": "CROSSCUT",
                "fromNode": "A",
                "toNode": "B",
                "length3d": 5.0,
                "geometryRef": {"artifact": "levels.json", "segmentIndex": 1},
            },
            {
                "id": "DRIFT:2",
                "type": "DRIFT",
                "fromNode": "B",
                "toNode": "C",
                "length3d": 300.0,
                "geometryRef": {"artifact": "levels.json", "segmentIndex": 2},
            },
        ],
    }
    levels = {
        "developments": [
            {"centerline": {"points": _line_points([0, 0, 0], [300, 0, 0])}},
            {"centerline": {"points": _line_points([300, 0, 0], [300, 5, 0], n=5)}},
            {"centerline": {"points": _line_points([300, 5, 0], [0, 5, 0])}},
        ]
    }
    smoothed = {"segments": []}
    return network, smoothed, levels


def _build(sc, network, smoothed, levels):  # type: ignore[no-untyped-def]
    return CommunicationBuilder(sc).build(network, smoothed, levels, "rev")


def test_straight_fixture_deterministic_solution(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """§32 lightweight solver fixture. Independent derivation of the expected
    count under the sampling contract: candidates PORTAL(0), P1..P5
    (40..200; 240 excluded strictly), N1(240); demands every 20 m. With
    coverage 60 / backhaul 80 the connected greedy picks P2(80) [gain 4],
    then P4(160) [gain 4], then P5(200) vs NODE:N1 tie broken
    lexicographically toward the EDGE candidate => portal + 3 = 4 routers."""
    sc = _scenario(
        tmp_path,
        candidateSpacingM=40.0,
        demandSpacingM=20.0,
        coverageRangeM=60.0,
        backhaulRangeM=80.0,
        requiredCoverageFraction=1.0,
    )
    network, smoothed, levels = _straight_fixture()
    p = _build(sc, network, smoothed, levels)
    assert p.status == "SUCCESS", p.failure_reason
    m = p.metrics
    assert m is not None
    assert m.candidate_count == 7  # 2 nodes + 5 interior (240 is NOT duplicated)
    assert m.demand_count == 13  # 2 nodes + 11 interior
    assert m.selected_asset_count == 4
    assert m.coverage_fraction == 1.0
    sel = sorted(a.candidate_id for a in p.selected_assets)
    assert sel == [
        "COMM:CAND:EDGE:RAMP:X:P2",
        "COMM:CAND:EDGE:RAMP:X:P4",
        "COMM:CAND:EDGE:RAMP:X:P5",
        "COMM:CAND:NODE:PORTAL",
    ]
    # stable ids + no endpoint duplication (§31A)
    assert not any(c.location_kind == "EDGE" and c.chainage_m in (0.0, 240.0) for c in p.candidates)
    root = next(a for a in p.selected_assets if a.backhaul_parent_asset_id is None)
    assert root.candidate_id == "COMM:CAND:NODE:PORTAL" and root.hop_count == 0
    # deterministic repeat: byte-identical (§31M)
    q = _build(sc, json.loads(json.dumps(network)), dict(smoothed), dict(levels))
    assert json.dumps(p.model_dump(mode="json", by_alias=True)) == json.dumps(
        q.model_dump(mode="json", by_alias=True)
    )


def test_network_distance_not_euclidean(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """§31C MANDATORY: coverage follows network-geodesic distance and never
    covers through rock."""
    network, smoothed, levels = _u_fixture()
    # low target so only the mandatory PORTAL root gets selected
    sc = _scenario(tmp_path, coverageRangeM=100.0, requiredCoverageFraction=0.15)
    p = _build(sc, network, smoothed, levels)
    assert p.status == "SUCCESS", p.failure_reason
    assert [a.candidate_id for a in p.selected_assets] == ["COMM:CAND:NODE:P"]
    cov = {r.demand_id: r for r in p.demand_coverage}
    # demand at node C: 5 m through rock from the portal router but 605 m of
    # tunnel -> MUST NOT be covered
    assert cov["COMM:DEMAND:NODE:C"].covered is False
    assert cov["COMM:DEMAND:NODE:C"].serving_asset_id is None
    # far end of DRIFT:2 (chainage 280 => 20 m from C, 585 m network) uncovered
    assert cov["COMM:DEMAND:EDGE:DRIFT:2:P14"].covered is False
    # while a same-tunnel demand 100 m along DRIFT:1 IS covered
    assert cov["COMM:DEMAND:EDGE:DRIFT:1:P5"].covered is True
    d = cov["COMM:DEMAND:EDGE:DRIFT:1:P5"].network_distance_m
    assert d == pytest.approx(100.0, abs=1e-9)
    # full solve at 1.0 covers C only via routers along the physical U
    sc2 = _scenario(tmp_path, coverageRangeM=100.0, requiredCoverageFraction=1.0)
    p2 = _build(sc2, network, smoothed, levels)
    assert p2.status == "SUCCESS", p2.failure_reason
    cov2 = {r.demand_id: r for r in p2.demand_coverage}
    row = cov2["COMM:DEMAND:NODE:C"]
    assert row.covered is True
    serving = next(a for a in p2.selected_assets if a.id == row.serving_asset_id)
    # the serving router lies on the C-side drift, not across the rock
    assert serving.candidate_id.startswith(("COMM:CAND:EDGE:DRIFT:2", "COMM:CAND:NODE:C"))
    assert all(
        r.network_distance_m is None or r.network_distance_m <= 100.0 + 1e-6
        for r in p2.demand_coverage
    )


def test_relay_path_and_tie_break_solver_units() -> None:
    """§31F/G at the PlacementProblem level."""

    def cand(cid):  # type: ignore[no-untyped-def]
        return CandidateSite(id=cid, location_kind="NODE", node_id=cid, position=(0.0, 0.0, 0.0))

    def dem(did):  # type: ignore[no-untyped-def]
        return DemandPoint(id=did, location_kind="NODE", node_id=did, position=(0.0, 0.0, 0.0))

    relay = PlacementProblem(
        candidates=[cand("R"), cand("A"), cand("B")],
        demands=[dem("d1")],
        candidate_coverage_sets={"R": [], "A": [], "B": ["d1"]},
        candidate_backhaul_graph={"R": ["A"], "A": ["R", "B"], "B": ["A"]},
        required_coverage_fraction=1.0,
        mandatory_candidate_ids=["R"],
    )
    sol = solve_connected_greedy(relay)
    # A covers nothing but is required as a relay on the path to B
    assert sol.status == "SUCCESS" and sol.selected_candidate_ids == ["A", "B", "R"]

    tie = PlacementProblem(
        candidates=[cand("R"), cand("X1"), cand("X2")],
        demands=[dem("d1"), dem("d2")],
        candidate_coverage_sets={"R": [], "X1": ["d1"], "X2": ["d2"]},
        candidate_backhaul_graph={"R": ["X1", "X2"], "X1": ["R"], "X2": ["R"]},
        required_coverage_fraction=0.5,
        mandatory_candidate_ids=["R"],
    )
    a = solve_connected_greedy(tie)
    b = solve_connected_greedy(tie)
    # symmetric gain/cost -> lexicographically smallest candidate, repeatably
    assert a.selected_candidate_ids == ["R", "X1"]
    assert json.dumps(a.model_dump(mode="json")) == json.dumps(b.model_dump(mode="json"))

    infeasible = PlacementProblem(
        candidates=[cand("R"), cand("X1")],
        demands=[dem("d1")],
        candidate_coverage_sets={"R": [], "X1": []},
        candidate_backhaul_graph={"R": ["X1"], "X1": ["R"]},
        required_coverage_fraction=1.0,
        mandatory_candidate_ids=["R"],
    )
    sol = solve_connected_greedy(infeasible)
    assert sol.status == "FAILED"
    assert sol.failure_reason == "INFEASIBLE_COMMUNICATION_COVERAGE"


def test_unsupported_asset_and_edge_types(tmp_path) -> None:  # type: ignore[no-untyped-def]
    network, smoothed, levels = _straight_fixture()
    sc = _scenario(tmp_path, assetType="WIFI_AP")
    p = _build(sc, network, smoothed, levels)
    assert p.status == "FAILED"
    assert "UNSUPPORTED_COMMUNICATION_ASSET_TYPE" in (p.failure_reason or "")
    sc = _scenario(tmp_path)
    raise_net = json.loads(json.dumps(network))
    raise_net["edges"][0]["type"] = "RAISE"
    p = _build(sc, raise_net, smoothed, levels)
    assert p.status == "FAILED"
    assert "UNSUPPORTED_COMMUNICATION_EDGE_TYPE" in (p.failure_reason or "")


def test_integrity_and_prerequisite_gates(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sc = _scenario(tmp_path)
    network, smoothed, levels = _straight_fixture()
    failed_net = json.loads(json.dumps(network))
    failed_net["status"] = "FAILED"
    assert _build(sc, failed_net, smoothed, levels).status == "FAILED"
    unsync = json.loads(json.dumps(network))
    unsync["validation"]["synchronized"] = False
    p = _build(sc, unsync, smoothed, levels)
    assert p.status == "FAILED" and "connected+synchronized" in (p.failure_reason or "")
    dup_node = json.loads(json.dumps(network))
    dup_node["nodes"].append(json.loads(json.dumps(dup_node["nodes"][0])))
    p = _build(sc, dup_node, smoothed, levels)
    assert p.status == "FAILED" and "duplicate network node ids" in (p.failure_reason or "")
    dup_edge = json.loads(json.dumps(network))
    dup_edge["edges"].append(json.loads(json.dumps(dup_edge["edges"][0])))
    p = _build(sc, dup_edge, smoothed, levels)
    assert p.status == "FAILED" and "duplicate network edge ids" in (p.failure_reason or "")
    dangling = json.loads(json.dumps(network))
    dangling["edges"][0]["toNode"] = "GHOST"
    p = _build(sc, dangling, smoothed, levels)
    assert p.status == "FAILED" and "missing node" in (p.failure_reason or "")
    two_portals = json.loads(json.dumps(network))
    two_portals["nodes"][1]["type"] = "PORTAL"
    p = _build(sc, two_portals, smoothed, levels)
    assert p.status == "FAILED" and "exactly one PORTAL" in (p.failure_reason or "")


def test_geometry_ownership_gates(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sc = _scenario(tmp_path)
    network, smoothed, levels = _straight_fixture()
    wrong_owner = json.loads(json.dumps(network))
    wrong_owner["edges"][0]["geometryRef"]["artifact"] = "levels.json"
    p = _build(sc, wrong_owner, smoothed, levels)
    assert p.status == "FAILED" and "must be owned by" in (p.failure_reason or "")
    oob = json.loads(json.dumps(network))
    oob["edges"][0]["geometryRef"]["segmentIndex"] = 7
    p = _build(sc, oob, smoothed, levels)
    assert p.status == "FAILED" and "out of range" in (p.failure_reason or "")
    stretched = json.loads(json.dumps(network))
    stretched["edges"][0]["length3d"] = 241.0
    p = _build(sc, stretched, smoothed, levels)
    assert p.status == "FAILED" and "declares" in (p.failure_reason or "")
    reversed_line = {
        "segments": [{"effectiveCenterline": {"points": _line_points([240, 0, 0], [0, 0, 0])}}]
    }
    p = _build(sc, network, reversed_line, levels)
    assert p.status == "FAILED" and "orientation" in (p.failure_reason or "")


def test_infeasible_coverage_is_typed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # coverage 5 m < the 20 m offset of mid demands from any candidate
    sc = _scenario(tmp_path, coverageRangeM=5.0, backhaulRangeM=40.0)
    network, smoothed, levels = _straight_fixture()
    p = _build(sc, network, smoothed, levels)
    assert p.status == "FAILED"
    assert p.failure_reason == "INFEASIBLE_COMMUNICATION_COVERAGE"


def test_metrics_exact_agreement_and_gates(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sc = _scenario(tmp_path)
    network, smoothed, levels = _u_fixture()
    p = _build(sc, network, smoothed, levels)
    assert p.status == "SUCCESS", p.failure_reason
    m = p.metrics
    assert m is not None
    covered = [r for r in p.demand_coverage if r.covered]
    assert m.candidate_count == len(p.candidates)
    assert m.demand_count == len(p.demands) == len(p.demand_coverage)
    assert m.selected_asset_count == len(p.selected_assets)
    assert m.covered_demand_count == len(covered)
    assert m.uncovered_demand_count == len(p.demand_coverage) - len(covered)
    assert m.coverage_fraction == pytest.approx(len(covered) / len(p.demand_coverage))
    dists = [r.network_distance_m for r in covered]
    assert m.max_serving_distance_m == pytest.approx(max(d for d in dists if d is not None))
    assert m.backhaul_link_count == m.selected_asset_count - 1
    assert m.total_network_length3d == pytest.approx(605.0)
    roots = [a for a in p.selected_assets if a.backhaul_parent_asset_id is None]
    assert len(roots) == 1 and roots[0].hop_count == 0
    asset_ids = {a.id for a in p.selected_assets}
    for a in p.selected_assets:
        if a.backhaul_parent_asset_id is not None:
            assert a.backhaul_parent_asset_id in asset_ids
            assert a.hop_count >= 1


def test_synthetic_chain_full_build_deterministic(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Full-fidelity synthetic Phase 05→08 chain (no Hybrid-A*): SUCCESS,
    root-connected, deterministic."""
    from tests.test_timeline import _chain

    sc, smoothed, levels_d, network_d, _stopes_d = _chain(
        tmp_path, [(25.0, 60.0), (25.0, 35.0), (25.0, 10.0)]
    )
    sc.infrastructure = InfrastructureConfig(communication=CommunicationConfig())
    p = CommunicationBuilder(sc).build(network_d, smoothed, levels_d, "rev")
    assert p.status == "SUCCESS", p.failure_reason
    m = p.metrics
    assert m is not None
    assert m.coverage_fraction >= 1.0 - 1e-12
    assert m.selected_asset_count >= 1
    roots = [a for a in p.selected_assets if a.backhaul_parent_asset_id is None]
    assert len(roots) == 1
    q = CommunicationBuilder(sc).build(
        json.loads(json.dumps(network_d)), json.loads(json.dumps(smoothed)), levels_d, "rev"
    )
    assert json.dumps(p.model_dump(mode="json", by_alias=True)) == json.dumps(
        q.model_dump(mode="json", by_alias=True)
    )


def test_communication_api_lifecycle_and_invalidation(client, design_service) -> None:  # type: ignore[no-untyped-def]
    """§23–24: 409 chain, sibling semantics (stopes/timeline preserve
    communication), network/levels regeneration invalidates it, and
    communication regeneration leaves upstream byte-identical."""
    from tests.test_network_api import _levels, _network
    from tests.test_smoothing_api import _decline, _prepare
    from tests.test_timeline import _stopes_api
    from tests.test_tunnel_api import _smooth

    sid = _prepare(client)
    _decline(client, sid)
    _smooth(client, sid)
    _levels(client, sid)
    url = f"/api/v1/scenarios/{sid}/infrastructure/communication"
    r = client.post(url)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NETWORK_NOT_GENERATED"
    _network(client, sid)
    r = client.get(url)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "COMMUNICATION_NOT_GENERATED"

    r = client.post(url)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "SUCCESS", body["failureReason"]
    assert body["model"]["optimalityClaim"] is False
    assert client.get(url).json() == body

    paths = {
        "levels": design_service.levels_path(sid),
        "network": design_service.network_path(sid),
    }
    before = {k: p.read_bytes() for k, p in paths.items()}
    cpath = design_service.store.derived_dir(sid) / "communication.json"
    assert cpath.is_file()

    # communication regeneration touches NOTHING upstream
    assert client.post(url).status_code == 200
    for k, p in paths.items():
        assert p.read_bytes() == before[k], k

    # stopes regeneration PRESERVES communication (siblings, rule 92)
    _stopes_api(client, sid)
    assert cpath.is_file()
    # timeline regeneration PRESERVES communication
    r = client.post(f"/api/v1/scenarios/{sid}/design/timeline")
    assert r.status_code == 200
    assert cpath.is_file()
    # network regeneration deletes communication only
    comm_before = json.loads(cpath.read_bytes())
    _network(client, sid)
    assert not cpath.exists()
    client.post(url)
    comm_after = json.loads(cpath.read_bytes())
    # deterministic content; only sourceRevision follows the new fingerprint
    comm_before.pop("sourceRevision")
    comm_after.pop("sourceRevision")
    assert comm_after == comm_before
    # levels regeneration cascades through network to communication
    _levels(client, sid)
    assert not cpath.exists()
    r = client.get(url)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "COMMUNICATION_NOT_GENERATED"


def test_threshold_model_contract() -> None:
    """Blocker 1a: NetworkDistanceThresholdModel implements the exact frozen
    threshold contract (geodesic <= range + 1e-6, no self backhaul)."""
    from minegen.infrastructure.coverage import NetworkDistanceThresholdModel

    model = NetworkDistanceThresholdModel(coverage_range_m=60.0, backhaul_range_m=80.0)
    assert model.model_id == "NETWORK_DISTANCE_THRESHOLD_V0_1"
    cand = ["C1", "C2"]
    dem = ["D1", "D2", "D3"]
    dist = np.array(
        [
            [60.0, 60.0 + 5e-7, 60.0 + 1e-5],  # exact, inside tolerance, outside
            [200.0, 0.0, 59.999999],
        ]
    )
    cov = model.coverage_sets(cand, dem, dist)
    assert cov == {"C1": ["D1", "D2"], "C2": ["D2", "D3"]}
    cc = np.array([[0.0, 80.0 + 5e-7], [80.0 + 5e-7, 0.0]])
    bh = model.backhaul_graph(cand, cc)
    assert bh == {"C1": ["C2"], "C2": ["C1"]}  # tolerance honoured, no self-loop
    cc2 = np.array([[0.0, 80.0 + 1e-5], [80.0 + 1e-5, 0.0]])
    assert model.backhaul_graph(cand, cc2) == {"C1": [], "C2": []}


def test_builder_consumes_coverage_model_abstraction(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Blocker 1b: the builder delegates coverage/backhaul evaluation to the
    injected strategy instead of reimplementing thresholds — a stub model
    that covers everything from the portal yields a single selected router,
    which the default threshold semantics (4 routers) could never produce."""

    class _PortalCoversAllStub:
        model_id = "STUB_MODEL"

        def coverage_sets(self, candidate_ids, demand_ids, candidate_demand_distance):  # type: ignore[no-untyped-def]
            return {
                cid: (sorted(demand_ids) if cid == "COMM:CAND:NODE:PORTAL" else [])
                for cid in candidate_ids
            }

        def backhaul_graph(self, candidate_ids, candidate_candidate_distance):  # type: ignore[no-untyped-def]
            return {cid: [] for cid in candidate_ids}

    sc = _scenario(
        tmp_path,
        candidateSpacingM=40.0,
        demandSpacingM=20.0,
        coverageRangeM=60.0,
        backhaulRangeM=80.0,
    )
    network, smoothed, levels = _straight_fixture()
    p = CommunicationBuilder(sc, coverage_model=_PortalCoversAllStub()).build(
        network, smoothed, levels, "rev"
    )
    assert p.status == "SUCCESS", p.failure_reason
    assert [a.candidate_id for a in p.selected_assets] == ["COMM:CAND:NODE:PORTAL"]
    assert p.metrics is not None and p.metrics.coverage_fraction == 1.0
    # and without injection the default strategy still yields the pinned 4
    q = CommunicationBuilder(sc).build(network, smoothed, levels, "rev")
    assert q.metrics is not None and q.metrics.selected_asset_count == 4


def test_malformed_centerline_is_typed_failed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Blocker 2: malformed owning centerlines return typed FAILED payloads,
    never reshape/conversion exceptions."""
    sc = _scenario(tmp_path)
    network, _smoothed, levels = _straight_fixture()
    flat7 = {"segments": [{"effectiveCenterline": {"points": [0.0] * 7}}]}
    p = _build(sc, network, flat7, levels)
    assert p.status == "FAILED"
    assert "multiple-of-3" in (p.failure_reason or "")
    pts = _line_points([0, 0, 0], [240, 0, 0])
    pts[10] = "oops"
    non_numeric = {"segments": [{"effectiveCenterline": {"points": pts}}]}
    p = _build(sc, network, non_numeric, levels)
    assert p.status == "FAILED"
    assert "non-numeric" in (p.failure_reason or "")
