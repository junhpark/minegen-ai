"""Phase 21A — MineExchange 1.1: mining-method semantics and production
stopes (directive §X1–§X8).

The bundle is a READ-ONLY projection (rule 190): ``semantics/mining_method.json``
is always present (the scenario is its first authority), a SUCCESS
``stopes.json`` becomes one STOPE entity + one independently QA'd closed
prism per stope under ``production/``, an unsupported method exports typed
UNSUPPORTED_METHOD outcomes and never longhole geometry, and every
disagreement between the method authorities is a typed 409.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from minegen.core.artifacts import (
    CAPABILITY_GRAPH_ARTIFACT,
    LEVELS_ARTIFACT,
    NETWORK_ARTIFACT,
    STOPES_ARTIFACT,
)
from minegen.exchange.builder import stope_entity_id
from minegen.exchange.models import MINE_EXCHANGE_VERSION
from tests.conftest import small_scenario
from tests.test_exchange_bundle import (
    EXPORT,
    Bundle,
    TabularStack,
    _derived_state,
    assert_integrity,
    export,
)
from tests.test_layout_v2_api import _generate_layout, _winner
from tests.test_world_api import _create


def _post(client: TestClient, url: str, **kw: Any) -> dict[str, Any]:
    r = client.post(url, **kw)
    assert r.status_code == 200, r.text
    doc: dict[str, Any] = r.json()
    return doc


def _refused(client: TestClient, sid: str, code: str) -> str:
    r = client.post(f"/api/v1/scenarios/{sid}{EXPORT}")
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == code, r.text
    return str(r.json()["detail"].get("message") or r.json()["detail"])


# --------------------------------------------------------------------------- #
# module-scoped stacks
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def longhole(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TabularStack]:
    """The real LAYOUT_V2 longhole chain + Phase 09 stopes."""
    stack = TabularStack(tmp_path_factory.mktemp("exchange-longhole"))
    stack.build_layout_chain()
    doc = _post(stack.client, f"/api/v1/scenarios/{stack.sid}/design/stopes")
    assert doc["status"] == "SUCCESS" and doc["stopes"], doc.get("failureReason")
    yield stack
    stack.close()


@pytest.fixture(scope="module")
def longhole_bundle(longhole: TabularStack) -> Bundle:
    return export(longhole.client, longhole.sid)


@pytest.fixture(scope="module")
def cut_and_fill(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TabularStack]:
    """A reserved method: layout → levels (generic backbone only) → stopes
    (typed FAILED). No tunnel / network is needed for the method semantics."""
    stack = TabularStack(tmp_path_factory.mktemp("exchange-cut-and-fill"))
    c = stack.client
    sc = small_scenario(with_fault=True)
    payload = sc.model_dump(by_alias=True, exclude={"id", "schema_version"})
    payload["mining"]["method"] = "CUT_AND_FILL"
    r = c.post("/api/v1/scenarios", json=payload)
    assert r.status_code == 201, r.text
    stack.sid = str(r.json()["id"])
    base = f"/api/v1/scenarios/{stack.sid}/design"
    _post(c, f"/api/v1/scenarios/{stack.sid}/world/generate")
    cat = _generate_layout(c, stack.sid)
    _post(c, f"{base}/layout-v2/activate", json={"candidateId": _winner(cat)})
    levels = _post(c, f"{base}/levels")
    assert levels["status"] == "SUCCESS", levels.get("failureReason")
    assert levels["productionDevelopment"]["status"] == "UNSUPPORTED_METHOD"
    stopes = _post(c, f"{base}/stopes")
    assert stopes["status"] == "FAILED" and stopes["stopes"] == []
    yield stack
    stack.close()


# --------------------------------------------------------------------------- #
# X1 — world-only: method semantics without any design artifact
# --------------------------------------------------------------------------- #


def test_x1_world_only_export_carries_method_semantics_and_no_production(
    client: TestClient,
) -> None:
    sid = _create(client)
    _post(client, f"/api/v1/scenarios/{sid}/world/generate")
    b = export(client, sid)
    assert_integrity(b)
    om = b.omissions()
    assert om["STOPES"] == "ARTIFACT_ABSENT" and om["TIMELINE"] == "NOT_IN_V1"
    assert not any(p.startswith("production/") for p in b.entries)
    assert not any(e["kind"] == "STOPE" for e in b.manifest["entities"])
    mm = b.json("semantics/mining_method.json")
    assert mm["mineExchangeVersion"] == MINE_EXCHANGE_VERSION == "1.1.0"
    assert mm["semanticType"] == "MINING_METHOD"
    assert mm["requestedMethod"] == "LONGHOLE_OPEN_STOPING"
    assert mm["displayName"] == "Longhole Open Stoping"
    assert mm["implementationStatus"] == "IMPLEMENTED"
    mining = client.get(f"/api/v1/scenarios/{sid}").json()["mining"]
    assert mm["parameters"] == {
        "sublevelInterval": mining["sublevelInterval"],
        "stopeLength": mining["stopeLength"],
        "minimumPillar": mining["minimumPillar"],
    }
    assert mm["productionDevelopment"]["status"] == "NOT_GENERATED"
    assert mm["productionDevelopment"]["entityIds"] == []
    assert mm["production"] == {
        "status": "NOT_GENERATED",
        "failureReason": None,
        "sourceArtifact": None,
        "sourceRevision": None,
        "stopeCount": 0,
        "entityIds": [],
    }
    f = b.files["semantics/mining_method.json"]
    assert f["semanticType"] == "MINING_METHOD" and f["representation"] == "DOCUMENT"
    assert f["sourceArtifact"] == "scenario.json" and f["derived"] is False


# --------------------------------------------------------------------------- #
# X2 — full longhole: STOPE entities, closed prisms, semantics
# --------------------------------------------------------------------------- #


def test_x2_longhole_stopes_are_exported_as_independent_closed_solids(
    longhole: TabularStack, longhole_bundle: Bundle
) -> None:
    b = longhole_bundle
    assert_integrity(b)
    assert b.omissions() == {"TIMELINE": "NOT_IN_V1", "FIELD_LATTICE": "NOT_IN_V1"}
    src = longhole.artifact(STOPES_ARTIFACT)
    assert src["status"] == "SUCCESS"
    ids = sorted(str(s["id"]) for s in src["stopes"])
    assert ids and STOPES_ARTIFACT in b.manifest["sourceSnapshot"]["artifactRevisions"]

    stope_entities = [e for e in b.manifest["entities"] if e["kind"] == "STOPE"]
    assert [e["sourceId"] for e in stope_entities] == ids  # bundle order = sorted stope id
    prod = b.json("production/stopes.json")
    assert prod["semanticType"] == "PRODUCTION_STOPES"
    assert prod["sourceArtifact"] == STOPES_ARTIFACT
    assert prod["method"] == "LONGHOLE_OPEN_STOPING"
    assert [s["stopeId"] for s in prod["stopes"]] == ids
    assert prod["metrics"] == src["metrics"]

    by_id = {str(s["id"]): s for s in src["stopes"]}
    for ent, row in zip(stope_entities, prod["stopes"], strict=True):
        sid = ent["sourceId"]
        eid = stope_entity_id(sid)
        assert ent["entityId"] == eid == row["entityId"]
        assert ent["sourceArtifact"] == STOPES_ARTIFACT and ent["levelId"] is None
        assert len(ent["files"]) == 4 and ent["files"][-1] == "production/stopes.json"
        assert ent["files"] == row["files"]
        for path in ent["files"][:3]:
            assert path.startswith("production/stopes/"), path
            f = b.files[path]
            assert f["semanticType"] == "STOPE_SOLID"
            assert f["representation"] == "AUTHORITATIVE_CLOSED_MESH"
            assert f["sourceEntityIds"] == [eid]
            assert f["sourceArtifact"] == STOPES_ARTIFACT and f["derived"] is False
            g = f["geometry"]
            assert g["closed"] and g["watertight"] and g["manifold"]
            assert g["unioned"] is False and g["overlappingAtJunctions"] is False
            assert g["triangleCount"] == 12 and g["vertexCount"] == 8
        stl = next(p for p in ent["files"] if p.endswith(".stl"))
        qa = b.stl_qa(stl)
        assert qa.closed_solid and qa.signed_volume > 0, qa.problems
        # QA'd against the AUTHORITATIVE volume, never trusted from the source report
        declared = float(by_id[sid]["geometricVolumeM3"])
        assert abs(qa.signed_volume - declared) <= 1e-6 * declared
        assert row["geometricVolumeM3"] == declared
        assert row["upperAccessNodeId"] == by_id[sid]["upperAccessNodeId"]
        # the exported vertices ARE the artifact vertices (canonical frame)
        p, _ = b.stl(stl)
        src_v = np.asarray(by_id[sid]["geometry"]["vertices"]).reshape(-1, 3)
        assert np.allclose(np.sort(p, axis=0), np.sort(src_v, axis=0), atol=1e-6)
        glb = next(p for p in ent["files"] if p.endswith(".glb"))
        assert b.files[glb]["glb"]["sceneFrame"] == "GLTF_Y_UP"

    # access anchors cross-checked against the exported network
    net_nodes = {n["id"] for n in b.json("topology/network.json")["nodes"]}
    for row in prod["stopes"]:
        assert row["upperAccessNodeId"] in net_nodes and row["lowerAccessNodeId"] in net_nodes

    mm = b.json("semantics/mining_method.json")
    assert mm["implementationStatus"] == "IMPLEMENTED"
    pd = mm["productionDevelopment"]
    assert pd["status"] == "IMPLEMENTED" and pd["sourceArtifact"] == LEVELS_ARTIFACT
    crosscuts = [e["entityId"] for e in b.manifest["entities"] if e["kind"] == "CROSSCUT"]
    assert pd["entityIds"] == crosscuts and crosscuts
    assert mm["production"]["status"] == "SUCCESS"
    assert mm["production"]["stopeCount"] == len(ids)
    assert mm["production"]["entityIds"] == [stope_entity_id(s) for s in ids]
    assert mm["production"]["sourceArtifact"] == STOPES_ARTIFACT
    f = b.files["semantics/mining_method.json"]
    assert f["sourceArtifact"] == f"scenario.json,{LEVELS_ARTIFACT},{STOPES_ARTIFACT}"
    assert set(f["sourceEntityIds"]) == set(crosscuts) | set(mm["production"]["entityIds"])
    # nothing new in the manifest vocabulary beyond the declared 1.1 additions
    kinds = {e["kind"] for e in b.manifest["entities"]}
    assert not kinds & {"DRAWPOINT", "PILLAR", "BACKFILL", "ROOM", "CUT", "BENCH"}
    readme = b.text("README.txt")
    assert "mining_method.json" in readme and "production/stopes" in readme


# --------------------------------------------------------------------------- #
# X3 — unsupported method: typed outcomes, no longhole geometry
# --------------------------------------------------------------------------- #


def test_x3_unsupported_method_exports_typed_outcomes_and_no_stope_geometry(
    cut_and_fill: TabularStack,
) -> None:
    b = export(cut_and_fill.client, cut_and_fill.sid)
    assert_integrity(b)
    om = b.omissions()
    assert om["STOPES"] == "SOURCE_NOT_SUCCESS"
    stopes_om = next(o for o in b.manifest["omissions"] if o["group"] == "STOPES")
    assert "UNSUPPORTED_METHOD" in stopes_om["detail"]
    assert "LONGHOLE_OPEN_STOPING" in stopes_om["detail"]  # the rule 78 no-fallback text
    assert not any(p.startswith("production/") for p in b.entries)
    assert not any(e["kind"] in {"STOPE", "CROSSCUT"} for e in b.manifest["entities"])
    assert any(e["kind"] == "DRIFT" for e in b.manifest["entities"])  # generic backbone
    mm = b.json("semantics/mining_method.json")
    assert mm["requestedMethod"] == "CUT_AND_FILL"
    assert mm["displayName"] == "Cut & Fill"
    assert mm["implementationStatus"] == "UNSUPPORTED_METHOD"
    pd = mm["productionDevelopment"]
    assert pd["status"] == "UNSUPPORTED_METHOD" and pd["entityIds"] == []
    assert "rule 159" in pd["reason"] and "no longhole crosscut lattice" in pd["reason"]
    pr = mm["production"]
    assert pr["status"] == "FAILED" and pr["stopeCount"] == 0 and pr["entityIds"] == []
    assert pr["failureReason"].startswith("UNSUPPORTED_METHOD: CUT_AND_FILL")
    assert pr["sourceArtifact"] == STOPES_ARTIFACT


# --------------------------------------------------------------------------- #
# X6 — determinism (same snapshot → same bytes; read-only)
# --------------------------------------------------------------------------- #


def test_x6_stope_export_is_deterministic_and_read_only(
    longhole: TabularStack, longhole_bundle: Bundle
) -> None:
    before = _derived_state(longhole.derived)
    again = export(longhole.client, longhole.sid)
    assert again.data == longhole_bundle.data
    assert _derived_state(longhole.derived) == before


# --------------------------------------------------------------------------- #
# mutating tests — run LAST on the longhole stack
# --------------------------------------------------------------------------- #


def _rewrite(path: Path, doc: dict[str, Any]) -> None:
    path.write_text(json.dumps(doc), encoding="utf-8")


def test_x4_method_authority_mismatch_is_a_typed_409(
    longhole: TabularStack, cut_and_fill: TabularStack
) -> None:
    # (a) stopes.json generated for another method than the scenario requests
    path = longhole.derived / STOPES_ARTIFACT
    original = path.read_bytes()
    try:
        doc = json.loads(original)
        doc["method"] = "CUT_AND_FILL"
        _rewrite(path, doc)
        msg = _refused(longhole.client, longhole.sid, "MINE_EXCHANGE_EXPORT_FAILED")
        assert "authority mismatch" in msg and STOPES_ARTIFACT in msg
    finally:
        path.write_bytes(original)
    # (b) a SUCCESS stopes artifact under a method the registry does not implement
    path = cut_and_fill.derived / STOPES_ARTIFACT
    original = path.read_bytes()
    try:
        doc = json.loads(original)
        doc["status"], doc["failureReason"] = "SUCCESS", None
        _rewrite(path, doc)
        msg = _refused(cut_and_fill.client, cut_and_fill.sid, "MINE_EXCHANGE_EXPORT_FAILED")
        assert "does not implement" in msg
    finally:
        path.write_bytes(original)
    # (c) levels.json declaring production development for another method
    path = cut_and_fill.derived / LEVELS_ARTIFACT
    original = path.read_bytes()
    try:
        doc = json.loads(original)
        doc["productionDevelopment"]["method"] = "LONGHOLE_OPEN_STOPING"
        doc["productionDevelopment"]["status"] = "IMPLEMENTED"
        _rewrite(path, doc)
        r = cut_and_fill.client.post(f"/api/v1/scenarios/{cut_and_fill.sid}{EXPORT}")
        assert r.status_code == 409, r.text
        # either the validated read refuses the changed levels revision (the
        # stopes artifact is bound to it) or the authority check does — never 200
        assert r.json()["detail"]["code"] in {
            "MINE_EXCHANGE_EXPORT_FAILED",
            "STOPES_STALE",
            "ARTIFACT_MALFORMED",
        }, r.text
    finally:
        path.write_bytes(original)
    assert export(longhole.client, longhole.sid).files  # healthy again
    assert export(cut_and_fill.client, cut_and_fill.sid).files


def test_x5_stope_geometry_corruption_is_refused_never_trusted(longhole: TabularStack) -> None:
    path = longhole.derived / STOPES_ARTIFACT
    original = path.read_bytes()
    doc0 = json.loads(original)

    def corrupt(mutate: Any, code: str) -> str:
        doc = json.loads(original)
        mutate(doc)
        _rewrite(path, doc)
        try:
            return _refused(longhole.client, longhole.sid, code)
        finally:
            path.write_bytes(original)

    # a NaN vertex never passes the validated read (rule 34)
    corrupt(_rewrite_nan, "ARTIFACT_MALFORMED")

    # an out-of-range triangle index fails the independent closed-solid QA
    def bad_index(doc: dict[str, Any]) -> None:
        doc["stopes"][0]["geometry"]["triangleIndices"][0] = 99

    msg = corrupt(bad_index, "MINE_EXCHANGE_EXPORT_FAILED")
    assert "closed-solid QA failed" in msg

    # an inverted face breaks manifoldness / orientation
    def flipped_face(doc: dict[str, Any]) -> None:
        t = doc["stopes"][0]["geometry"]["triangleIndices"]
        t[0], t[1] = t[1], t[0]

    msg = corrupt(flipped_face, "MINE_EXCHANGE_EXPORT_FAILED")
    assert "closed-solid QA failed" in msg

    # a declared volume disagreeing with the exported mesh is refused
    def wrong_volume(doc: dict[str, Any]) -> None:
        doc["stopes"][0]["geometricVolumeM3"] = doc["stopes"][0]["geometricVolumeM3"] * 1.01

    msg = corrupt(wrong_volume, "MINE_EXCHANGE_EXPORT_FAILED")
    assert "disagrees with the artifact's geometric volume" in msg

    # a duplicated stope id is refused
    def duplicate(doc: dict[str, Any]) -> None:
        doc["stopes"].append(json.loads(json.dumps(doc["stopes"][0])))

    msg = corrupt(duplicate, "MINE_EXCHANGE_EXPORT_FAILED")
    assert "duplicate stope id" in msg

    # an access node the exported network does not carry is refused
    def foreign_node(doc: dict[str, Any]) -> None:
        doc["stopes"][0]["upperAccessNodeId"] = "STOPE_ACCESS:L99:S+00"

    msg = corrupt(foreign_node, "MINE_EXCHANGE_EXPORT_FAILED")
    assert "is not a node of the exported network" in msg
    assert path.read_bytes() == original and json.loads(original) == doc0


def _rewrite_nan(doc: dict[str, Any]) -> None:
    doc["stopes"][0]["geometry"]["vertices"][0] = float("nan")


def test_x7_stopes_change_during_export_is_refused(
    longhole: TabularStack, monkeypatch: pytest.MonkeyPatch
) -> None:
    from minegen.exchange.bundle import write_bundle

    target = longhole.derived / STOPES_ARTIFACT
    original = target.read_bytes()
    st0 = target.stat()

    def racing(spec: Any) -> Any:
        # a writer republishes stopes.json while the bundle is being built
        target.write_bytes(original)
        os.utime(target, ns=(st0.st_atime_ns, st0.st_mtime_ns + 1_000_000))
        return write_bundle(spec)

    monkeypatch.setattr("minegen.services.exchange_service.write_bundle", racing)
    _refused(longhole.client, longhole.sid, "READ_SNAPSHOT_CHANGED")
    monkeypatch.undo()
    os.utime(target, ns=(st0.st_atime_ns, st0.st_mtime_ns))
    assert export(longhole.client, longhole.sid).files


def test_x8_stopes_export_does_not_require_the_network(longhole: TabularStack) -> None:
    # the earlier mutating tests re-published stopes.json (new revision), so the
    # reference is a FRESH export of the current snapshot, not the module bundle
    reference = export(longhole.client, longhole.sid)
    net = longhole.derived / NETWORK_ARTIFACT
    cap = longhole.derived / CAPABILITY_GRAPH_ARTIFACT
    net_bytes, cap_bytes = net.read_bytes(), cap.read_bytes()
    net_st, cap_st = net.stat(), cap.stat()
    try:
        cap.unlink()
        net.unlink()
        b = export(longhole.client, longhole.sid)
        assert_integrity(b)
        om = b.omissions()
        assert om["NETWORK"] == "ARTIFACT_ABSENT" and om["CAPABILITY"] == "ARTIFACT_ABSENT"
        assert "STOPES" not in om
        assert "production/stopes.json" in b.entries
        stope_entities = [e for e in b.manifest["entities"] if e["kind"] == "STOPE"]
        full = [e for e in reference.manifest["entities"] if e["kind"] == "STOPE"]
        assert stope_entities == full and full  # identical entities without the cross-check
        for e in stope_entities:
            for path in e["files"][:3]:
                assert b.entries[path] == reference.entries[path]  # identical solid bytes
        assert b.json("production/stopes.json") == reference.json("production/stopes.json")
        mm = b.json("semantics/mining_method.json")
        assert mm["production"]["status"] == "SUCCESS"
        assert mm["production"]["entityIds"] == [e["entityId"] for e in full]
    finally:
        net.write_bytes(net_bytes)
        os.utime(net, ns=(net_st.st_atime_ns, net_st.st_mtime_ns))
        cap.write_bytes(cap_bytes)
        os.utime(cap, ns=(cap_st.st_atime_ns, cap_st.st_mtime_ns))
    assert export(longhole.client, longhole.sid).data == reference.data
