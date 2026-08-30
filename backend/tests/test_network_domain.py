"""Shared infrastructure network-domain tests (§38, rule 93): the extracted
domain is tested directly so communication and sensor builders only need to
verify typed FAILED mapping."""

from __future__ import annotations

import json

import numpy as np
import pytest

from minegen.infrastructure.network_domain import (
    DomainValidationError,
    InfrastructureNetworkDomain,
    UnsupportedEdgeTypeError,
)
from tests.test_communication import _line_points, _straight_fixture, _u_fixture


def _build(network, smoothed, levels):  # type: ignore[no-untyped-def]
    return InfrastructureNetworkDomain.build(network, smoothed, levels)


def _mutated(network, **top):  # type: ignore[no-untyped-def]
    n = json.loads(json.dumps(network))
    n.update(top)
    return n


def test_integrity_gates() -> None:
    network, smoothed, levels = _straight_fixture()
    with pytest.raises(DomainValidationError, match="is not consumable"):
        _build(_mutated(network, status="FAILED"), smoothed, levels)
    unsync = json.loads(json.dumps(network))
    unsync["validation"]["connected"] = False
    with pytest.raises(DomainValidationError, match="connected\\+synchronized"):
        _build(unsync, smoothed, levels)
    dup_node = json.loads(json.dumps(network))
    dup_node["nodes"].append(json.loads(json.dumps(dup_node["nodes"][0])))
    with pytest.raises(DomainValidationError, match="duplicate network node ids"):
        _build(dup_node, smoothed, levels)
    dup_edge = json.loads(json.dumps(network))
    dup_edge["edges"].append(json.loads(json.dumps(dup_edge["edges"][0])))
    with pytest.raises(DomainValidationError, match="duplicate network edge ids"):
        _build(dup_edge, smoothed, levels)
    dangling = json.loads(json.dumps(network))
    dangling["edges"][0]["toNode"] = "GHOST"
    with pytest.raises(DomainValidationError, match="missing node GHOST"):
        _build(dangling, smoothed, levels)
    two_portals = json.loads(json.dumps(network))
    two_portals["nodes"][1]["type"] = "PORTAL"
    with pytest.raises(DomainValidationError, match="exactly one PORTAL"):
        _build(two_portals, smoothed, levels)
    raise_net = json.loads(json.dumps(network))
    raise_net["edges"][0]["type"] = "RAISE"
    with pytest.raises(UnsupportedEdgeTypeError) as exc:
        _build(raise_net, smoothed, levels)
    assert exc.value.edge_id == "RAMP:X" and exc.value.edge_type == "RAISE"
    zero_len = json.loads(json.dumps(network))
    zero_len["edges"][0]["length3d"] = 0.0
    with pytest.raises(DomainValidationError, match="non-positive length3d"):
        _build(zero_len, smoothed, levels)


def test_disconnected_graph_is_typed() -> None:
    network, smoothed, levels = _straight_fixture()
    # island node with no edge: payload claims connected, domain recomputes
    island = json.loads(json.dumps(network))
    island["nodes"].append({"id": "Z9", "type": "JUNCTION", "position": [999.0, 0.0, 0.0]})
    with pytest.raises(DomainValidationError, match="not physically connected"):
        _build(island, smoothed, levels)


def test_geometry_gates() -> None:
    network, smoothed, levels = _straight_fixture()
    wrong_owner = json.loads(json.dumps(network))
    wrong_owner["edges"][0]["geometryRef"]["artifact"] = "levels.json"
    with pytest.raises(DomainValidationError, match="must be owned by"):
        _build(wrong_owner, smoothed, levels)
    for bad_index in (-1, 7, True, "0"):
        bad = json.loads(json.dumps(network))
        bad["edges"][0]["geometryRef"]["segmentIndex"] = bad_index
        with pytest.raises(DomainValidationError):
            _build(bad, smoothed, levels)
    stretched = json.loads(json.dumps(network))
    stretched["edges"][0]["length3d"] = 240.0 + 1e-5
    with pytest.raises(DomainValidationError, match="declares"):
        _build(stretched, smoothed, levels)
    flat7 = {"segments": [{"effectiveCenterline": {"points": [0.0] * 7}}]}
    with pytest.raises(DomainValidationError, match="multiple-of-3"):
        _build(network, flat7, levels)
    pts = _line_points([0, 0, 0], [240, 0, 0])
    pts[10] = "oops"
    with pytest.raises(DomainValidationError, match="non-numeric"):
        _build(network, {"segments": [{"effectiveCenterline": {"points": pts}}]}, levels)
    pts2 = _line_points([0, 0, 0], [240, 0, 0])
    pts2[3] = float("nan")
    with pytest.raises(DomainValidationError, match="non-finite"):
        _build(network, {"segments": [{"effectiveCenterline": {"points": pts2}}]}, levels)
    reversed_line = {
        "segments": [{"effectiveCenterline": {"points": _line_points([240, 0, 0], [0, 0, 0])}}]
    }
    with pytest.raises(DomainValidationError, match="orientation"):
        _build(network, reversed_line, levels)


def test_sampling_and_distances() -> None:
    network, smoothed, levels = _straight_fixture()
    domain = _build(network, smoothed, levels)
    rows = domain.sample(40.0, "X:CAND")
    ids = [r[0] for r in rows]
    assert ids[:2] == ["X:CAND:NODE:N1", "X:CAND:NODE:PORTAL"]  # sorted node order
    assert ids[2:] == [f"X:CAND:EDGE:RAMP:X:P{k}" for k in range(1, 6)]  # 40..200
    # no endpoint duplication: 240 (== edge length) is never an EDGE sample
    assert not any(r[3] in (0.0, 240.0) for r in rows if r[3] is not None)
    # exact same-edge chainage distance
    d = domain.location_distance((None, "RAMP:X", 40.0), (None, "RAMP:X", 200.0))
    assert d == pytest.approx(160.0, abs=1e-12)
    m = domain.pairwise(rows, rows)
    i40 = ids.index("X:CAND:EDGE:RAMP:X:P1")
    i200 = ids.index("X:CAND:EDGE:RAMP:X:P5")
    assert m[i40, i200] == pytest.approx(160.0, abs=1e-9)
    assert domain.total_network_length3d == pytest.approx(240.0)
    assert domain.portal_id == "PORTAL"


def test_folded_network_distance_never_euclidean() -> None:
    network, smoothed, levels = _u_fixture()
    domain = _build(network, smoothed, levels)
    p = ("P", None, None)
    c = ("C", None, None)
    d = domain.location_distance(p, c)
    # Euclidean separation is 5 m; the physical path is 300 + 5 + 300
    assert d == pytest.approx(605.0, abs=1e-9)
    euclid = float(np.linalg.norm(np.array([0.0, 0.0, 0.0]) - np.array([0.0, 5.0, 0.0])))
    assert euclid == pytest.approx(5.0)
    assert d > 100 * euclid
