"""AC-01I contract tests — geometry reference / endpoint / shaft reference
semantics that every consumer must keep IDENTICAL while the resolvers are
consolidated (Phase B of the directive).

Three consumers read the same ``network.json`` ``geometryRef`` and the same
owning artifacts today: the shared infrastructure domain (rule 93), the
timeline builder and the capability-graph builder. These tests pin, on ONE
shaft-bearing network, that

* a malformed reference is a TYPED failure in all three (``DomainValidationError``
  / ``status == FAILED`` with a reason) — never a KeyError / IndexError /
  TypeError / ValueError (B1);
* a malformed endpoint (an edge naming a node that does not exist) is
  rejected identically (B2);
* a valid shaft reference resolves to the declared shaft, an incompatible
  one (wrong owning artifact) and a withheld shaft artifact fail typed (B3);
* the ``ramp-source`` summary keeps its exact key set, key order and the
  ``null`` / value distinction of every optional field (B4).

The coordinate contract of the effective ramp (B5) and the activate wrapper
are pinned in ``test_artifact_read_api.py`` on the shared LAYOUT_V2 stack.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from minegen.capability.builder import CapabilityGraphBuilder
from minegen.capability.models import CapabilitySource
from minegen.core.artifacts import LEVELS_ARTIFACT, SHAFTS_ARTIFACT
from minegen.core.models import ShaftSpec
from minegen.infrastructure.network_domain import (
    DomainValidationError,
    InfrastructureNetworkDomain,
)
from minegen.scheduling.builder import MineTimelineBuilder
from tests.test_shafts import _network, _plan, _stopes, tabular_levels  # noqa: F401
from tests.verification_support import load_fixture

API = "/api/v1/scenarios"

RAMP_SOURCE_KEYS = (
    "activeSource",
    "owningArtifact",
    "available",
    "legacyAvailable",
    "layoutV2Available",
    "layoutV2Selected",
    "sourceKind",
    "sourceRevision",
    "candidateId",
    "family",
    "status",
    "segmentCount",
)


class Consumers:
    """One shaft-bearing chain and the three consumers of its references."""

    def __init__(self, tabular: tuple[Any, Any, dict[str, Any]]) -> None:
        sc, world, levels = tabular
        fx = load_fixture("tabular_small_selected")
        shafts = _plan(sc, world, levels, ShaftSpec())
        assert shafts.status == "SUCCESS", shafts.failure_reason
        self.sc = sc
        self.levels = levels
        self.ramp = fx["effectiveRamp"]
        self.accesses = fx["levelAccesses"]
        self.shafts = shafts.model_dump(mode="json", by_alias=True)
        self.stopes = _stopes(sc, world, levels)
        res = _network(sc, levels, shafts)
        assert res.success, res.payload.failure_reason
        self.network = res.payload.model_dump(mode="json", by_alias=True)

    # -- the three consumers, each fed the SAME network document ---------- #
    def domain(self, network: dict[str, Any]) -> InfrastructureNetworkDomain:
        return InfrastructureNetworkDomain.build(
            network, self.ramp, self.levels, self.accesses, self.shafts
        )

    def timeline(self, network: dict[str, Any]) -> Any:
        return MineTimelineBuilder(self.sc).build(
            network, self.stopes, self.ramp, self.levels, "rev", self.accesses, self.shafts
        )

    def capability(self, network: dict[str, Any], *, withhold_shafts: bool = False) -> Any:
        payload = None if withhold_shafts else self.shafts
        return CapabilityGraphBuilder(self.sc).build(
            network, payload, "src", str(network.get("sourceRevision") or "")
        )

    def edge(self, edge_type: str) -> int:
        return next(i for i, e in enumerate(self.network["edges"]) if e["type"] == edge_type)

    def mutated(self, index: int, geometry_ref: Any) -> dict[str, Any]:
        doc = json.loads(json.dumps(self.network))
        doc["edges"][index]["geometryRef"] = geometry_ref
        return doc


@pytest.fixture(scope="module")
def consumers(tabular_levels: tuple[Any, Any, dict[str, Any]]) -> Consumers:  # noqa: F811
    return Consumers(tabular_levels)


def test_the_valid_chain_resolves_identically_in_every_consumer(consumers: Consumers) -> None:
    """Positive contract: the same reference resolves to the same owning
    centerline in all three consumers (point counts agree edge by edge and
    every shaft edge carries SHAFT_DECLARED capabilities)."""
    domain = consumers.domain(consumers.network)
    timeline = consumers.timeline(consumers.network)
    assert timeline.status == "SUCCESS", timeline.failure_reason
    graph = consumers.capability(consumers.network)
    assert graph.status == "SUCCESS", graph.failure_reason
    by_edge = {d.edge_id: d for d in timeline.developments}
    for edge_id, geometry in domain.geometries.items():
        assert len(by_edge[edge_id].point_chainage_fractions) == geometry.points.shape[0]
    shaft_edges = {e["id"] for e in consumers.network["edges"] if e["type"].startswith("SHAFT")}
    assert shaft_edges
    for ce in graph.edges:
        if ce.edge_id in shaft_edges:
            assert ce.source is CapabilitySource.SHAFT_DECLARED


MALFORMED_REFS: list[tuple[str, Any]] = [
    ("not-an-object", "layout_v2_selected.json:0"),
    ("unknown-artifact", {"artifact": "bogus.json", "segmentIndex": 0}),
    ("negative-index", {"artifact": None, "segmentIndex": -1}),
    ("bool-index", {"artifact": None, "segmentIndex": True}),
    ("string-index", {"artifact": None, "segmentIndex": "0"}),
    ("missing-index", {"artifact": None}),
    ("out-of-range", {"artifact": None, "segmentIndex": 9999}),
]


def _ref(edge: dict[str, Any], template: Any) -> Any:
    """``artifact: None`` in a template means "keep the edge's own artifact"."""
    if isinstance(template, dict) and template.get("artifact") is None and "artifact" in template:
        return {**template, "artifact": edge["geometryRef"]["artifact"]}
    return template


@pytest.mark.parametrize(("label", "template"), MALFORMED_REFS, ids=[m[0] for m in MALFORMED_REFS])
@pytest.mark.parametrize("edge_type", ["RAMP", "DRIFT", "LEVEL_ACCESS", "SHAFT"])
def test_b1_a_malformed_geometry_ref_is_a_typed_failure_in_every_geometry_consumer(
    consumers: Consumers, edge_type: str, label: str, template: Any
) -> None:
    """The two consumers that RESOLVE every edge's geometry (domain, timeline)
    refuse every malformed form with a typed failure."""
    index = consumers.edge(edge_type)
    doc = consumers.mutated(index, _ref(consumers.network["edges"][index], template))
    # shared domain: typed DomainValidationError, never Key/Index/Type/ValueError
    with pytest.raises(DomainValidationError):
        consumers.domain(doc)
    # timeline: typed FAILED payload with a reason, no tasks
    tl = consumers.timeline(doc)
    assert tl.status == "FAILED" and tl.failure_reason, label
    assert tl.tasks == []


@pytest.mark.parametrize(("label", "template"), MALFORMED_REFS, ids=[m[0] for m in MALFORMED_REFS])
def test_b1_a_malformed_shaft_reference_is_a_typed_failure_in_the_capability_graph(
    consumers: Consumers, label: str, template: Any
) -> None:
    """The capability graph resolves ONLY shaft references (rule 185); a
    malformed one must be a typed FAILED payload, never an exception and
    never a lenient success. Before AC-01I commit 2 the builder's private
    slice crashed on a non-object reference and accepted a numeric string
    (``int("0")``); it now goes through the ONE shared resolver."""
    index = consumers.edge("SHAFT")
    doc = consumers.mutated(index, _ref(consumers.network["edges"][index], template))
    graph = consumers.capability(doc)
    assert graph.status == "FAILED" and graph.failure_reason, label


def test_b2_a_malformed_endpoint_is_rejected_identically(consumers: Consumers) -> None:
    doc = json.loads(json.dumps(consumers.network))
    doc["edges"][0]["toNode"] = "GHOST:NODE"
    with pytest.raises(DomainValidationError, match="missing node"):
        consumers.domain(doc)
    tl = consumers.timeline(doc)
    assert tl.status == "FAILED" and "missing node" in (tl.failure_reason or "")
    graph = consumers.capability(doc)
    assert graph.status == "FAILED" and "missing endpoints" in (graph.failure_reason or "")


def test_b3_shaft_reference_semantics(consumers: Consumers) -> None:
    index = consumers.edge("SHAFT")
    edge = consumers.network["edges"][index]
    assert edge["geometryRef"]["artifact"] == SHAFTS_ARTIFACT
    # (a) valid: the shaft edge resolves to the declared shaft
    graph = consumers.capability(consumers.network)
    assert graph.status == "SUCCESS", graph.failure_reason
    # (b) incompatible owner: a SHAFT edge pointing at the levels artifact
    wrong = consumers.mutated(index, {"artifact": LEVELS_ARTIFACT, "segmentIndex": 0})
    with pytest.raises(DomainValidationError, match="must be owned by"):
        consumers.domain(wrong)
    assert consumers.timeline(wrong).status == "FAILED"
    g = consumers.capability(wrong)
    assert g.status == "FAILED" and "shaft artifact" in (g.failure_reason or "")
    # (c) withheld shaft artifact: the edges exist, the owner does not
    with pytest.raises(DomainValidationError, match="out of range"):
        InfrastructureNetworkDomain.build(
            consumers.network, consumers.ramp, consumers.levels, consumers.accesses
        )
    tl = MineTimelineBuilder(consumers.sc).build(
        consumers.network,
        consumers.stopes,
        consumers.ramp,
        consumers.levels,
        "rev",
        consumers.accesses,
    )
    assert tl.status == "FAILED" and "out of range" in (tl.failure_reason or "")
    g = consumers.capability(consumers.network, withhold_shafts=True)
    assert g.status == "FAILED" and "shaft artifact" in (g.failure_reason or "")
    # (d) a shaft index that exists in the network but not in the artifact
    oob = consumers.mutated(index, {"artifact": SHAFTS_ARTIFACT, "segmentIndex": 9999})
    g = consumers.capability(oob)
    assert g.status == "FAILED" and "does not resolve to a shaft" in (g.failure_reason or "")


def test_b4_ramp_source_summary_null_and_optional_contract(client: Any) -> None:
    """The ramp-source summary is the closed 12-key document below, in this
    key order, with EXPLICIT nulls for the optional provenance fields (never
    omitted) and ``segmentCount`` 0 when no ramp exists."""
    from tests.conftest import small_scenario

    payload = small_scenario().model_dump(by_alias=True, exclude={"id", "schema_version"})
    created = client.post(API, json=payload)
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    # without a world every derived read is the typed 409 (AC-01F contract)
    absent = client.get(f"{API}/{sid}/design/ramp-source")
    assert absent.status_code == 409
    assert absent.json()["detail"]["code"] == "WORLD_NOT_GENERATED"
    assert client.post(f"{API}/{sid}/world/generate").status_code == 200
    body = client.get(f"{API}/{sid}/design/ramp-source").json()
    assert tuple(body.keys()) == RAMP_SOURCE_KEYS
    assert body == {
        "activeSource": "LEGACY",
        "owningArtifact": "decline_smoothed.json",
        "available": False,
        "legacyAvailable": False,
        "layoutV2Available": False,
        "layoutV2Selected": False,
        "sourceKind": None,
        "sourceRevision": None,
        "candidateId": None,
        "family": None,
        "status": None,
        "segmentCount": 0,
    }
    # LAYOUT_V2 without a persisted selection is the typed 409
    refused = client.put(f"{API}/{sid}/design/ramp-source", json={"activeSource": "LAYOUT_V2"})
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "LAYOUT_V2_NOT_SELECTED"
    # an explicit LEGACY switch answers the same closed document
    kept = client.put(f"{API}/{sid}/design/ramp-source", json={"activeSource": "LEGACY"})
    assert kept.status_code == 200
    assert tuple(kept.json().keys()) == RAMP_SOURCE_KEYS
    assert kept.json() == body
    # an unknown source is a 422 validation error, not a 500
    bad = client.put(f"{API}/{sid}/design/ramp-source", json={"activeSource": "NOPE"})
    assert bad.status_code == 422


# --------------------------------------------------------------------------- #
# the two AC-01I authorities directly
# --------------------------------------------------------------------------- #


def test_the_shared_resolver_narrows_by_edge_type_and_accepts_the_union_without_one() -> None:
    from minegen.network.geometry_refs import (
        OWNING_ARTIFACTS,
        OWNING_ARTIFACTS_BY_EDGE_TYPE,
        GeometryRefError,
        resolve_owning_centerline,
    )

    levels = {"developments": [{"centerline": {"points": [0.0, 0.0, 0.0, 1.0, 0.0, 0.0]}}]}
    ref = {"artifact": LEVELS_ARTIFACT, "segmentIndex": 0}
    # with an edge type the owner must match that type's artifacts
    ok = resolve_owning_centerline(ref, edge_type="DRIFT", levels_payload=levels)
    assert ok.points == [0.0, 0.0, 0.0, 1.0, 0.0, 0.0] and ok.array.shape == (2, 3)
    assert ok.owner is levels["developments"][0]
    with pytest.raises(GeometryRefError, match="must be owned by"):
        resolve_owning_centerline(ref, edge_type="SHAFT", levels_payload=levels)
    with pytest.raises(GeometryRefError, match="has no owning artifact"):
        resolve_owning_centerline(ref, edge_type="RAISE", levels_payload=levels)
    # without one, any owning artifact is accepted (the timeline contract)
    assert resolve_owning_centerline(ref, levels_payload=levels).segment_index == 0
    with pytest.raises(GeometryRefError, match="unknown owning artifact"):
        resolve_owning_centerline({"artifact": "bogus.json", "segmentIndex": 0})
    # a payload the caller does not hold is an out-of-range reference into 0 entries
    with pytest.raises(GeometryRefError, match=r"out of range for shafts.json \(0 entries\)"):
        resolve_owning_centerline({"artifact": SHAFTS_ARTIFACT, "segmentIndex": 0})
    # malformed owning geometry is typed, never a reshape / conversion exception
    for points in (
        [0.0, 0.0, 0.0],
        [0.0] * 7,
        [0.0, 0.0, 0.0, "x", 0.0, 0.0],
        [0.0] * 5 + [float("inf")],
    ):
        with pytest.raises(GeometryRefError):
            resolve_owning_centerline(
                ref, levels_payload={"developments": [{"centerline": {"points": points}}]}
            )
    assert set(OWNING_ARTIFACTS) == {
        a for owners in OWNING_ARTIFACTS_BY_EDGE_TYPE.values() for a in owners
    }


def test_the_node_id_grammar_round_trips() -> None:
    from minegen.network.node_ids import (
        level_entry_id,
        ramp_junction_id,
        shaft_bottom_id,
        shaft_collar_id,
        shaft_station_id,
        shaft_station_shaft_id,
    )

    assert level_entry_id("L03") == "LEVEL_ENTRY:L03"
    assert ramp_junction_id("L03") == "RAMP_JUNCTION:L03"
    assert shaft_collar_id("SHAFT-01") == "SHAFT_COLLAR:SHAFT-01"
    assert shaft_bottom_id("SHAFT-01") == "SHAFT_BOTTOM:SHAFT-01"
    assert shaft_station_id("SHAFT-01", "L03") == "SHAFT_STATION:SHAFT-01:L03"
    assert shaft_station_shaft_id("SHAFT_STATION:SHAFT-01:L03") == "SHAFT-01"
    for malformed in ("SHAFT_STATION:SHAFT-01", "SHAFT_COLLAR:SHAFT-01", "SHAFT_STATION::L03", "x"):
        assert shaft_station_shaft_id(malformed) is None
