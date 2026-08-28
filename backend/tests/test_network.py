"""Phase 07 MineNetwork builder tests (rules 13, 68–70): typed payload,
geometry-reference-only edges, canonical direction semantics, undirected
redundancy advisory, determinism."""

from __future__ import annotations

import json
import math

import networkx as nx
import numpy as np
import pytest

from minegen.core.models import ScenarioCreate
from minegen.design.profile import build_profile
from minegen.network.builder import (
    MineNetworkBuilder,
    _surface_path_counts,
)
from minegen.services.scenario_service import ScenarioStore


def _scenario(store: ScenarioStore):  # type: ignore[no-untyped-def]
    return store.get(store.create(ScenarioCreate()).id)


def _segment(
    level_id: str,
    start: np.ndarray,  # type: ignore[type-arg]
    end: np.ndarray,  # type: ignore[type-arg]
    *,
    source: str = "SMOOTHED",
    n: int = 21,
) -> dict:  # type: ignore[type-arg]
    t = np.linspace(0.0, 1.0, n)[:, None]
    pts = start[None, :] * (1 - t) + end[None, :] * t
    return {
        "levelId": level_id,
        "candidateId": f"{level_id}-C01",
        "effectiveSource": source,
        "effectiveCenterline": {"points": pts.ravel().tolist()},
        "boundaryTangents": {"start": [0, 1, 0], "end": [0, 1, 0]},
        "smoothed": None,
        "report": {"fieldCostSmoothed": 111.0, "fieldCostRaw": 222.0},
    }


def _payload(*segments: dict) -> dict:  # type: ignore[type-arg]
    return {"status": "SUCCESS", "failureReason": None, "segments": list(segments), "totals": {}}


def test_nodes_edges_attributes_and_geometry_reference(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = ScenarioStore(root=tmp_path)
    sc = _scenario(store)
    p0 = np.array([0.0, 0.0, 100.0])
    p1 = np.array([0.0, 100.0, 88.0])
    p2 = np.array([80.0, 160.0, 76.0])
    payload = _payload(_segment("L01", p0, p1), _segment("L02", p1, p2, source="RAW_FALLBACK"))
    res = MineNetworkBuilder(sc).build(payload, "rev123")
    assert res.success, res.payload.failure_reason
    body = res.payload.model_dump(mode="json", by_alias=True)
    assert body["sourceRevision"] == "rev123"

    # namespaced deterministic node IDs; coordinates from the centerline
    assert [n["id"] for n in body["nodes"]] == ["PORTAL", "LEVEL_ENTRY:L01", "LEVEL_ENTRY:L02"]
    assert body["nodes"][0]["position"] == pytest.approx(list(p0))
    assert body["nodes"][1]["position"] == pytest.approx(list(p1))
    assert body["nodes"][2]["position"] == pytest.approx(list(p2))
    assert body["nodes"][1]["candidateId"] == "L01-C01"
    assert body["nodes"][2]["elevation"] == pytest.approx(76.0)

    e1, e2 = body["edges"]
    assert (e1["id"], e1["fromNode"], e1["toNode"]) == ("RAMP:L01", "PORTAL", "LEVEL_ENTRY:L01")
    assert (e2["fromNode"], e2["toNode"]) == ("LEVEL_ENTRY:L01", "LEVEL_ENTRY:L02")

    # scalar attrs; geometry is a REFERENCE, never a polyline (rule 68)
    assert e1["length3d"] == pytest.approx(float(np.linalg.norm(p1 - p0)))
    assert e1["meanGradientSigned"] == pytest.approx(-12.0 / 100.0)
    assert e1["maxAbsGradient"] == pytest.approx(0.12)
    assert e1["geometryRef"] == {"artifact": "decline_smoothed.json", "segmentIndex": 0}
    assert e2["geometryRef"]["segmentIndex"] == 1
    assert "points" not in json.dumps(e1)

    # fieldCost selection follows the effective source
    assert e1["effectiveSource"] == "SMOOTHED" and e1["fieldCost"] == pytest.approx(111.0)
    assert e2["effectiveSource"] == "RAW_FALLBACK" and e2["fieldCost"] == pytest.approx(222.0)

    shape = build_profile(sc.ramp, sc.tunnel_profile)
    cs = e1["crossSection"]
    assert cs == {
        "width": sc.ramp.tunnel_width,
        "height": sc.ramp.tunnel_height,
        "analyticArea": shape.analytic_area,
    }
    assert e1["simulation"] == {
        "haulage": None,
        "ventilation": None,
        "communication": None,
        "rockRisk": None,
    }

    # metrics + graph mirror
    m = body["metrics"]
    assert (m["nodeCount"], m["edgeCount"], m["levelCount"]) == (3, 2, 2)
    assert m["totalRampLength3d"] == pytest.approx(e1["length3d"] + e2["length3d"])
    assert m["minimumElevation"] == pytest.approx(76.0)
    assert m["verticalDropFromPortal"] == pytest.approx(24.0)
    assert isinstance(res.graph, nx.MultiDiGraph)
    assert set(res.graph.nodes) == {n["id"] for n in body["nodes"]}
    assert res.graph.number_of_edges() == 2


def test_weld_error_fails_explicitly(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = ScenarioStore(root=tmp_path)
    sc = _scenario(store)
    p0 = np.array([0.0, 0.0, 100.0])
    p1 = np.array([0.0, 100.0, 88.0])
    p1_off = p1 + np.array([0.01, 0.0, 0.0])  # 1 cm weld break
    p2 = np.array([80.0, 160.0, 76.0])
    res = MineNetworkBuilder(sc).build(
        _payload(_segment("L01", p0, p1), _segment("L02", p1_off, p2)), "rev"
    )
    assert not res.success
    assert res.payload.status == "FAILED"
    assert res.payload.failure_reason is not None and "weld error" in res.payload.failure_reason
    assert res.payload.validation is not None
    assert res.payload.validation.synchronized is False
    assert res.payload.validation.max_node_sync_error == pytest.approx(0.01)


def test_surface_path_advisory_single_chain(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = ScenarioStore(root=tmp_path)
    sc = _scenario(store)
    p0 = np.array([0.0, 0.0, 100.0])
    p1 = np.array([0.0, 100.0, 88.0])
    p2 = np.array([80.0, 160.0, 76.0])
    res = MineNetworkBuilder(sc).build(
        _payload(_segment("L01", p0, p1), _segment("L02", p1, p2)), "rev"
    )
    body = res.payload.model_dump(mode="json", by_alias=True)
    (adv,) = body["surfacePathAdvisory"]
    assert adv["criterion"] == "TWO_EDGE_DISJOINT_SURFACE_PATHS"
    assert adv["requiredPaths"] == 2 and adv["advisoryOnly"] is True
    assert [e["independentSurfacePaths"] for e in adv["perNode"]] == [1, 1]
    assert all(e["meetsCriterion"] is False for e in adv["perNode"])
    # no statutory/legal compliance language anywhere in the payload (rule 70)
    text = json.dumps(body).lower()
    assert "complian" not in text and "egress" not in text and "statut" not in text


def test_surface_path_counts_edge_disjoint_semantics() -> None:
    """Max-flow on the undirected capacity projection: parallel physical
    edges and multiple PORTAL-type surface nodes each add a disjoint path;
    canonical edge direction never limits reachability (rule 69)."""
    g: nx.MultiDiGraph[str] = nx.MultiDiGraph()
    for n in ("P1", "P2", "A", "B"):
        g.add_node(n)
    # deep node A: one ramp up to B; B reaches BOTH portals; direction is
    # deliberately canonical (downhill) — undirected projection must be used
    g.add_edge("P1", "B", key="RAMP:1")
    g.add_edge("P2", "B", key="RAMP:2")
    g.add_edge("B", "A", key="RAMP:3")
    counts = _surface_path_counts(g, ["P1", "P2"], ["A", "B"])
    assert counts["B"] == 2  # two edge-disjoint surface paths via two portals
    assert counts["A"] == 1  # bottleneck: the single B–A ramp
    g.add_edge("B", "A", key="RAMP:4")  # parallel physical development
    counts = _surface_path_counts(g, ["P1", "P2"], ["A"])
    assert counts["A"] == 2  # parallel edge legitimately adds capacity
    # disconnected node
    g.add_node("C")
    assert _surface_path_counts(g, ["P1"], ["C"])["C"] == 0


def test_payload_determinism(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = ScenarioStore(root=tmp_path)
    sc = _scenario(store)
    p0 = np.array([0.0, 0.0, 100.0])
    p1 = np.array([37.0, 91.0, 87.5])
    payload = _payload(_segment("L01", p0, p1))
    a = MineNetworkBuilder(sc).build(payload, "rev")
    b = MineNetworkBuilder(sc).build(json.loads(json.dumps(payload)), "rev")
    assert json.dumps(a.payload.model_dump(mode="json", by_alias=True)) == json.dumps(
        b.payload.model_dump(mode="json", by_alias=True)
    )


def test_gradient_sign_convention(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """meanGradientSigned is Δz over horizontal length in the canonical
    portal→deeper direction — negative when descending; maxAbsGradient ≥ 0."""
    store = ScenarioStore(root=tmp_path)
    sc = _scenario(store)
    start = np.array([0.0, 0.0, 100.0])
    end = np.array([0.0, 50.0, 94.0])
    res = MineNetworkBuilder(sc).build(_payload(_segment("L01", start, end)), "rev")
    (edge,) = res.payload.edges
    assert edge.mean_gradient_signed == pytest.approx(-0.12)
    assert edge.max_abs_gradient == pytest.approx(0.12)
    assert edge.max_abs_gradient >= 0.0
    assert edge.length3d == pytest.approx(math.hypot(50.0, 6.0))


def test_failed_smoothed_artifact_never_yields_a_network(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Blocker-1 regression (rule 68): a FAILED Phase 05 artifact containing
    an otherwise-valid partial segment must produce an explicit FAILED
    network with ZERO physical nodes/edges — never a SUCCESS partial graph."""
    store = ScenarioStore(root=tmp_path)
    sc = _scenario(store)
    good_partial = _segment("L01", np.array([0.0, 0.0, 100.0]), np.array([0.0, 100.0, 88.0]))
    payload = _payload(good_partial)
    payload["status"] = "FAILED"
    payload["failureReason"] = "L02 smoothing failed"
    res = MineNetworkBuilder(sc).build(payload, "rev")
    assert not res.success
    body = res.payload
    assert body.status == "FAILED"
    assert body.nodes == [] and body.edges == []
    assert body.metrics is None and body.validation is None
    assert body.surface_path_advisory == []
    assert res.graph.number_of_nodes() == 0 and res.graph.number_of_edges() == 0
    assert body.failure_reason is not None and "prerequisite" in body.failure_reason
    # SUCCESS_WITH_FALLBACK remains consumable
    payload["status"] = "SUCCESS_WITH_FALLBACK"
    ok = MineNetworkBuilder(sc).build(payload, "rev")
    assert ok.success and len(ok.payload.edges) == 1


def _levels_payload_for(entry: np.ndarray, level_id: str = "L01") -> dict:  # type: ignore[type-arg,no-untyped-def]
    """Hand-built levels payload: two drift pieces split at one JUNCTION
    station plus one entry-coincident station, and two crosscuts."""
    e = entry

    def line(a, b, n=5):  # type: ignore[no-untyped-def]
        t = np.linspace(0.0, 1.0, n)[:, None]
        return (np.asarray(a)[None, :] * (1 - t) + np.asarray(b)[None, :] * t).ravel().tolist()

    j = e + np.array([40.0, 0.0, 0.0])
    sa0 = e + np.array([0.0, 25.0, 0.0])
    sa1 = j + np.array([0.0, 25.0, 0.0])

    def dev(did, kind, frm, to, pts, station_index=None, station_u=None):  # type: ignore[no-untyped-def]
        return {
            "id": did,
            "kind": kind,
            "levelId": level_id,
            "stationIndex": station_index,
            "stationU": station_u,
            "fromU": frm,
            "toU": to,
            "centerline": {"points": pts},
            "length3d": 40.0 if kind == "DRIFT" else 25.0,
            "meanGradientSigned": 0.0,
            "maxAbsGradient": 0.0,
            "report": {
                "startWeldError": 0.0,
                "envelopeHardViolations": 0,
                "envelopeAboveTerrain": 0,
                "terminalSdf": 0.0 if kind == "CROSSCUT" else None,
                "interiorBreachSamples": 0,
                "fieldCost": 7.0,
                "valid": True,
                "failureReason": None,
            },
        }

    return {
        "status": "SUCCESS",
        "failureReason": None,
        "sourceRevision": "lv",
        "developments": [
            dev("DRIFT:L01:00", "DRIFT", 0.0, 40.0, line(e, j)),
            # station S+00 coincides with the LEVEL_ENTRY → node reuse
            dev("CROSSCUT:L01:S+00", "CROSSCUT", 0.0, 0.0, line(e, sa0), 0, 0.0),
            dev("CROSSCUT:L01:S+01", "CROSSCUT", 40.0, 40.0, line(j, sa1), 1, 40.0),
        ],
        "levels": [],
        "metrics": None,
    }


def test_level_development_topology_weaving(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Rule 73: DRIFT edges split at graph nodes, entry-coincident station
    reuses LEVEL_ENTRY (no duplicate co-located JUNCTION), STOPE_ACCESS
    terminals, levels.json geometryRef, advisory over ALL underground
    nodes."""
    store = ScenarioStore(root=tmp_path)
    sc = _scenario(store)
    p0 = np.array([0.0, 0.0, 100.0])
    p1 = np.array([0.0, 100.0, 88.0])
    smoothed = _payload(_segment("L01", p0, p1))
    levels = _levels_payload_for(p1)
    res = MineNetworkBuilder(sc).build(smoothed, "rev", levels_payload=levels)
    assert res.success, res.payload.failure_reason
    body = res.payload

    ids = [n.id for n in body.nodes]
    assert "LEVEL_ENTRY:L01" in ids
    assert sum(1 for n in body.nodes if n.type.value == "JUNCTION") == 1
    assert sum(1 for n in body.nodes if n.type.value == "STOPE_ACCESS") == 2
    # co-located station reused the entry: no JUNCTION at the entry position
    entry = next(n for n in body.nodes if n.id == "LEVEL_ENTRY:L01")
    for n in body.nodes:
        if n.type.value == "JUNCTION":
            assert np.linalg.norm(np.asarray(n.position) - np.asarray(entry.position)) > 1.0

    by_id = {e.id: e for e in body.edges}
    drift = by_id["DRIFT:L01:00"]
    assert (drift.from_node, drift.to_node) == ("LEVEL_ENTRY:L01", drift.to_node)
    assert drift.to_node.startswith("JUNCTION:L01:")
    assert drift.effective_source == "ANALYTIC"
    assert drift.geometry_ref.artifact == "levels.json"
    assert drift.geometry_ref.segment_index == 0
    cc0 = by_id["CROSSCUT:L01:S+00"]
    assert cc0.from_node == "LEVEL_ENTRY:L01"  # reuse rule
    assert cc0.to_node == "STOPE_ACCESS:L01:S+00"
    cc1 = by_id["CROSSCUT:L01:S+01"]
    assert cc1.from_node == drift.to_node
    assert by_id["CROSSCUT:L01:S+01"].geometry_ref.segment_index == 2

    m = body.metrics
    assert m is not None
    assert (m.drift_edge_count, m.crosscut_edge_count) == (1, 2)
    assert (m.junction_count, m.stope_access_count) == (1, 2)
    assert m.total_drift_length3d == pytest.approx(40.0)
    assert m.total_crosscut_length3d == pytest.approx(50.0)

    # advisory covers EVERY underground node (LE + J + SA = 4), all with 1
    (adv,) = body.surface_path_advisory
    assert len(adv.per_node) == len(body.nodes) - 1
    assert all(e.independent_surface_paths == 1 for e in adv.per_node)
    covered = {e.node_id for e in adv.per_node}
    assert any(n.startswith("STOPE_ACCESS") for n in covered)
    assert any(n.startswith("JUNCTION") for n in covered)


def test_failed_levels_artifact_never_yields_a_network(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = ScenarioStore(root=tmp_path)
    sc = _scenario(store)
    p0 = np.array([0.0, 0.0, 100.0])
    p1 = np.array([0.0, 100.0, 88.0])
    levels = _levels_payload_for(p1)
    levels["status"] = "FAILED"
    res = MineNetworkBuilder(sc).build(
        _payload(_segment("L01", p0, p1)), "rev", levels_payload=levels
    )
    assert not res.success
    assert res.payload.nodes == [] and res.payload.edges == []
    assert res.payload.failure_reason is not None and "levels" in res.payload.failure_reason
