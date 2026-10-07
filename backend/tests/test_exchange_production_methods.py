"""MineExchange 1.2 semantics (now carried by 1.3.0) — Cut & Fill / Room & Pillar
production export (Phase 21B/C).

MX-1  version 1.3.0 (1.2 semantics unchanged); a Longhole bundle carries no
      CUT_FILL / ROOM_PILLAR group and no methodParameters block (1.1.0 shape unchanged)
MX-2  CF world-only: CUT_FILL ARTIFACT_ABSENT (no STOPES group), typed
      methodParameters DTO, productionKind CUT_FILL
MX-3  CF full: production/cut_fill.json, CUT solids (STL/OBJ/GLB, independent
      QA, verbatim vertices), BACKFILL semantic entities 1:1 referencing the cut
MX-4  CF metrics / parameters are typed projections of the artifact / scenario
MX-5  RP full: production/room_pillar.json, ROOM parents without geometry,
      BENCH + PILLAR closed solids under benches/ and pillars/
MX-6  a FAILED production artifact is an explicit SOURCE_NOT_SUCCESS omission
      of the ACTIVE method's group
MX-7  authority guard: payload / method disagreement is a typed 409
MX-8  corrupted CF / RP geometry is refused, never trusted
MX-9  deterministic and read-only
MX-10 partial export: cuts export without a network; access entity ids resolve
      to the exported CROSSCUT entities
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from minegen.core.artifacts import NETWORK_ARTIFACT, STOPES_ARTIFACT
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
from tests.test_exchange_mining_method import _post, _refused
from tests.test_layout_v2_api import _generate_layout, _winner
from tests.test_world_api import _create


def _method_stack(root: Path, method: str, params: dict[str, Any] | None = None) -> TabularStack:
    """layout → levels → production for a method (no tunnel / network: the
    production export must not need them)."""
    stack = TabularStack(root)
    c = stack.client
    sc = small_scenario(with_fault=True)
    payload = sc.model_dump(by_alias=True, exclude={"id", "schema_version"})
    payload["mining"]["method"] = method
    if params is not None:
        payload["mining"]["methodParameters"] = params
    r = c.post("/api/v1/scenarios", json=payload)
    assert r.status_code == 201, r.text
    stack.sid = str(r.json()["id"])
    base = f"/api/v1/scenarios/{stack.sid}/design"
    _post(c, f"/api/v1/scenarios/{stack.sid}/world/generate")
    cat = _generate_layout(c, stack.sid)
    _post(c, f"{base}/layout-v2/activate", json={"candidateId": _winner(cat)})
    levels = _post(c, f"{base}/levels")
    assert levels["status"] == "SUCCESS", levels.get("failureReason")
    prod = _post(c, f"{base}/production")
    assert prod["status"] == "SUCCESS" and prod["method"] == method, prod.get("failureReason")
    return stack


@pytest.fixture(scope="module")
def cut_fill(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TabularStack]:
    stack = _method_stack(tmp_path_factory.mktemp("exchange-cut-fill"), "CUT_AND_FILL")
    yield stack
    stack.close()


@pytest.fixture(scope="module")
def cut_fill_bundle(cut_fill: TabularStack) -> Bundle:
    return export(cut_fill.client, cut_fill.sid)


@pytest.fixture(scope="module")
def room_pillar(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TabularStack]:
    stack = _method_stack(
        tmp_path_factory.mktemp("exchange-room-pillar"),
        "ROOM_AND_PILLAR",
        {
            "kind": "ROOM_AND_PILLAR",
            "roomWidthM": 12.0,
            "pillarWidthM": 8.0,
            "headingHeightM": 4.0,
            "benchCount": 2,
            "boundaryPillarM": 6.0,
        },
    )
    yield stack
    stack.close()


@pytest.fixture(scope="module")
def room_pillar_bundle(room_pillar: TabularStack) -> Bundle:
    return export(room_pillar.client, room_pillar.sid)


def _entities(b: Bundle, kind: str) -> list[dict[str, Any]]:
    return [e for e in b.manifest["entities"] if e["kind"] == kind]


def _check_solid(b: Bundle, ent: dict[str, Any], semantic: str, rec: dict[str, Any]) -> None:
    solids = [p for p in ent["files"] if p.endswith((".stl", ".obj", ".glb"))]
    assert len(solids) == 3
    for path in solids:
        f = b.files[path]
        assert f["semanticType"] == semantic
        assert f["representation"] == "AUTHORITATIVE_CLOSED_MESH"
        assert f["sourceEntityIds"] == [ent["entityId"]]
        assert f["sourceArtifact"] == STOPES_ARTIFACT and f["derived"] is False
        g = f["geometry"]
        assert g["closed"] and g["watertight"] and g["manifold"] and g["unioned"] is False
        assert g["triangleCount"] == 12 and g["vertexCount"] == 8
    stl = next(p for p in solids if p.endswith(".stl"))
    qa = b.stl_qa(stl)
    assert qa.closed_solid and qa.signed_volume > 0, qa.problems
    declared = float(rec["geometricVolumeM3"])
    # the exporter QA'd the float64 vertices at 1e-6; the binary STL stores
    # float32 (≈ 1e-4 m at ~1 km coordinates), hence the looser re-check here
    assert abs(qa.signed_volume - declared) <= 1e-4 * declared
    p, _ = b.stl(stl)
    src_v = np.asarray(rec["geometry"]["vertices"]).reshape(-1, 3)
    assert np.allclose(np.sort(p, axis=0), np.sort(src_v, axis=0), atol=1e-6)
    glb = next(p for p in solids if p.endswith(".glb"))
    assert b.files[glb]["glb"]["sceneFrame"] == "GLTF_Y_UP"


# --------------------------------------------------------------------------- #
# MX-1 / MX-2
# --------------------------------------------------------------------------- #


def test_mx1_version_and_longhole_shape_unchanged(client: TestClient) -> None:
    sid = _create(client)
    _post(client, f"/api/v1/scenarios/{sid}/world/generate")
    b = export(client, sid)
    assert_integrity(b)
    assert MINE_EXCHANGE_VERSION == "1.3.0"
    assert b.manifest["mineExchangeVersion"] == "1.3.0"
    om = b.omissions()
    assert om["STOPES"] == "ARTIFACT_ABSENT"
    assert "CUT_FILL" not in om and "ROOM_PILLAR" not in om
    mm = b.json("semantics/mining_method.json")
    assert "methodParameters" not in mm["parameters"]
    assert mm["production"]["productionKind"] == "STOPES"
    assert mm["production"]["unitCount"] == 0


def test_mx2_cut_fill_world_only_omission_and_typed_parameters(client: TestClient) -> None:
    sc = small_scenario()
    payload = sc.model_dump(by_alias=True, exclude={"id", "schema_version"})
    payload["mining"]["method"] = "CUT_AND_FILL"
    r = client.post("/api/v1/scenarios", json=payload)
    assert r.status_code == 201, r.text
    sid = str(r.json()["id"])
    _post(client, f"/api/v1/scenarios/{sid}/world/generate")
    b = export(client, sid)
    assert_integrity(b)
    om = b.omissions()
    assert om["CUT_FILL"] == "ARTIFACT_ABSENT"
    assert "STOPES" not in om and "ROOM_PILLAR" not in om
    assert not any(p.startswith("production/") for p in b.entries)
    mm = b.json("semantics/mining_method.json")
    assert mm["requestedMethod"] == "CUT_AND_FILL"
    assert mm["displayName"] == "Cut & Fill"
    assert mm["implementationStatus"] == "IMPLEMENTED"
    assert mm["parameters"]["methodParameters"] == {
        "kind": "CUT_AND_FILL",
        "liftHeightM": 4.0,
        "cutLengthM": 15.0,
    }
    assert mm["production"]["status"] == "NOT_GENERATED"
    assert mm["production"]["productionKind"] == "CUT_FILL"


# --------------------------------------------------------------------------- #
# MX-3 / MX-4 — Cut & Fill
# --------------------------------------------------------------------------- #


def test_mx3_cut_fill_cuts_and_backfills(cut_fill: TabularStack, cut_fill_bundle: Bundle) -> None:
    b = cut_fill_bundle
    assert_integrity(b)
    om = b.omissions()
    assert "CUT_FILL" not in om and "STOPES" not in om and "ROOM_PILLAR" not in om
    src = cut_fill.artifact(STOPES_ARTIFACT)
    cuts_by_id = {c["id"]: c for c in src["cuts"]}
    doc = b.json("production/cut_fill.json")
    assert doc["semanticType"] == "PRODUCTION_CUT_FILL"
    assert doc["mineExchangeVersion"] == "1.3.0" and doc["method"] == "CUT_AND_FILL"
    assert doc["coordinateFrame"] == "LOCAL_ENU_Z_UP"
    assert doc["sourceArtifact"] == STOPES_ARTIFACT
    f = b.files["production/cut_fill.json"]
    assert f["semanticType"] == "PRODUCTION_CUT_FILL" and f["representation"] == "DOCUMENT"

    cut_entities = _entities(b, "CUT")
    backfill_entities = _entities(b, "BACKFILL")
    assert len(cut_entities) == len(src["cuts"]) == len(doc["cuts"]) > 0
    assert len(backfill_entities) == len(src["backfills"]) == len(doc["backfills"])
    assert len(backfill_entities) == len(cut_entities)
    # bundle order == persisted (mining) order
    assert [e["sourceId"] for e in cut_entities] == [c["id"] for c in src["cuts"]]
    assert [r["cutId"] for r in doc["cuts"]] == [c["id"] for c in src["cuts"]]
    backfill_by_entity = {e["entityId"]: e for e in backfill_entities}
    for ent, row in zip(cut_entities, doc["cuts"], strict=True):
        cid = ent["sourceId"]
        assert ent["entityId"] == f"cut:{cid}" == row["entityId"]
        assert ent["sourceArtifact"] == STOPES_ARTIFACT
        assert ent["levelId"] == cuts_by_id[cid]["lowerLevelId"]
        assert all(p.startswith("production/cut_fill/cuts/") for p in ent["files"][:3])
        assert "production/cut_fill.json" in ent["files"]
        _check_solid(b, ent, "CUT_SOLID", cuts_by_id[cid])
        assert row["geometricVolumeM3"] == cuts_by_id[cid]["geometricVolumeM3"]
        assert row["liftIndex"] == cuts_by_id[cid]["liftIndex"]
        assert row["accessDevelopmentId"] == cuts_by_id[cid]["accessDevelopmentId"]
        # the 1:1 backfill: semantic, no geometry file, parent = the cut
        bf = backfill_by_entity[row["backfillEntityId"]]
        assert bf["parentEntityId"] == ent["entityId"]
        assert bf["files"] == ["production/cut_fill.json"]
        assert not any(p.endswith((".stl", ".obj", ".glb")) for p in bf["files"])
    for bf_row in doc["backfills"]:
        assert bf_row["sourceCutEntityId"] == f"cut:{bf_row['sourceCutId']}"
        assert bf_row["entityId"] in backfill_by_entity
        assert bf_row["volumeM3"] == cuts_by_id[bf_row["sourceCutId"]]["geometricVolumeM3"]
    # lifts reference exported cuts only
    cut_eids = {e["entityId"] for e in cut_entities}
    assert len(doc["lifts"]) == len(src["lifts"])
    for lf in doc["lifts"]:
        assert lf["cutEntityIds"] and set(lf["cutEntityIds"]) <= cut_eids
    # no stope / room / bench / pillar content
    assert not _entities(b, "STOPE") and not _entities(b, "BENCH") and not _entities(b, "PILLAR")
    assert "production/stopes.json" not in b.entries
    assert "production/room_pillar.json" not in b.entries


def test_mx4_cut_fill_metrics_and_parameters_are_typed(
    cut_fill: TabularStack, cut_fill_bundle: Bundle
) -> None:
    b = cut_fill_bundle
    src = cut_fill.artifact(STOPES_ARTIFACT)
    doc = b.json("production/cut_fill.json")
    # every field named in the DTO carries the source value (the H2-CF block /
    # panel / rib-pillar / cemented metrics join the DTO in MineExchange 1.3.1)
    assert doc["metrics"] == {k: src["metrics"][k] for k in doc["metrics"]}
    assert set(doc["metrics"]) == {
        "cutCount",
        "backfillCount",
        "liftCount",
        "levelIntervalCount",
        "totalGeometricVolumeM3",
        "totalTonnes",
        "geometricExtractionFractionOfOrebody",
        "weightedMeanGradeProxy",
        "actualMeanLiftHeight",
        "actualMeanCutLength",
    }
    mining = cut_fill.client.get(f"/api/v1/scenarios/{cut_fill.sid}").json()["mining"]
    # the typed parameter DTO projects the scenario values it names (the
    # H2-CF sequencing fields join it in MineExchange 1.3.1)
    assert doc["parameters"] == {k: mining["methodParameters"][k] for k in doc["parameters"]}
    mm = b.json("semantics/mining_method.json")
    assert mm["parameters"]["methodParameters"] == doc["parameters"]
    pr = mm["production"]
    assert pr["status"] == "SUCCESS" and pr["productionKind"] == "CUT_FILL"
    assert pr["stopeCount"] == 0 and pr["unitCount"] == len(src["cuts"])
    assert pr["entityIds"] == [
        e["entityId"] for e in b.manifest["entities"] if e["kind"] in {"CUT", "BACKFILL"}
    ]
    assert mm["productionDevelopment"]["status"] == "IMPLEMENTED"


# --------------------------------------------------------------------------- #
# MX-5 — Room & Pillar
# --------------------------------------------------------------------------- #


def test_mx5_room_pillar_rooms_benches_pillars(
    room_pillar: TabularStack, room_pillar_bundle: Bundle
) -> None:
    b = room_pillar_bundle
    assert_integrity(b)
    om = b.omissions()
    assert "ROOM_PILLAR" not in om and "STOPES" not in om and "CUT_FILL" not in om
    src = room_pillar.artifact(STOPES_ARTIFACT)
    doc = b.json("production/room_pillar.json")
    assert doc["semanticType"] == "PRODUCTION_ROOM_PILLAR" and doc["method"] == "ROOM_AND_PILLAR"
    rooms, benches, pillars = _entities(b, "ROOM"), _entities(b, "BENCH"), _entities(b, "PILLAR")
    assert len(rooms) == len(src["rooms"]) == len(doc["rooms"]) > 0
    assert len(benches) == len(src["extractionUnits"]) == len(doc["extractionUnits"])
    assert len(pillars) == len(src["pillars"]) == len(doc["pillars"]) > 0
    units_by_id = {u["id"]: u for u in src["extractionUnits"]}
    pillars_by_id = {p["id"]: p for p in src["pillars"]}
    room_eids = {r["entityId"] for r in rooms}
    for ent in rooms:
        assert ent["files"] == ["production/room_pillar.json"]
        assert ent["sourceMemberIds"]  # its extraction units, persisted order
        assert all(f"bench:{u}" in {x["entityId"] for x in benches} for u in ent["sourceMemberIds"])
    for ent in benches:
        assert ent["parentEntityId"] in room_eids
        assert all(p.startswith("production/room_pillar/benches/") for p in ent["files"][:3])
        _check_solid(b, ent, "BENCH_SOLID", units_by_id[ent["sourceId"]])
    for ent in pillars:
        assert ent.get("parentEntityId") is None
        assert all(p.startswith("production/room_pillar/pillars/") for p in ent["files"][:3])
        _check_solid(b, ent, "PILLAR_SOLID", pillars_by_id[ent["sourceId"]])
    stages = {r["stage"] for r in doc["extractionUnits"]}
    assert "HEADING" in stages and stages & {"BENCH_1", "BENCH_2"}
    for row in doc["rooms"]:
        assert row["extractionUnitEntityIds"] == [
            f"bench:{u}"
            for u in next(r for r in src["rooms"] if r["id"] == row["roomId"])["extractionUnitIds"]
        ]
    assert doc["metrics"] == src["metrics"]
    mining = room_pillar.client.get(f"/api/v1/scenarios/{room_pillar.sid}").json()["mining"]
    assert doc["parameters"] == mining["methodParameters"]
    mm = b.json("semantics/mining_method.json")
    assert mm["production"]["productionKind"] == "ROOM_PILLAR"
    assert mm["production"]["unitCount"] == len(benches)
    assert mm["production"]["stopeCount"] == 0
    assert "production/stopes.json" not in b.entries and "production/cut_fill.json" not in b.entries
    for note in b.files["production/room_pillar.json"].get("notes", []) + doc["notes"]:
        assert "certif" not in note.lower() or "never" in note.lower()


# --------------------------------------------------------------------------- #
# MX-9 / MX-10 (read-only stacks first)
# --------------------------------------------------------------------------- #


def test_mx9_deterministic_and_read_only(
    cut_fill: TabularStack,
    cut_fill_bundle: Bundle,
    room_pillar: TabularStack,
    room_pillar_bundle: Bundle,
) -> None:
    for stack, bundle in ((cut_fill, cut_fill_bundle), (room_pillar, room_pillar_bundle)):
        before = _derived_state(stack.derived)
        again = export(stack.client, stack.sid)
        assert again.data == bundle.data
        assert _derived_state(stack.derived) == before


def test_mx10_partial_export_without_network_resolves_access_entities(
    cut_fill: TabularStack, cut_fill_bundle: Bundle
) -> None:
    b = cut_fill_bundle
    assert not (cut_fill.derived / NETWORK_ARTIFACT).exists()
    om = b.omissions()
    assert om["NETWORK"] == "ARTIFACT_ABSENT" and om["CAPABILITY"] == "ARTIFACT_ABSENT"
    crosscuts = {e["sourceId"]: e["entityId"] for e in _entities(b, "CROSSCUT")}
    assert crosscuts  # the central production access per level is exported
    doc = b.json("production/cut_fill.json")
    for row in doc["cuts"]:
        assert row["accessEntityId"] == crosscuts[row["accessDevelopmentId"]]
    mm = b.json("semantics/mining_method.json")
    assert set(mm["productionDevelopment"]["entityIds"]) == set(crosscuts.values())


# --------------------------------------------------------------------------- #
# MX-6 / MX-7 / MX-8 — mutating tests, run LAST
# --------------------------------------------------------------------------- #


def _rewrite(path: Path, doc: dict[str, Any]) -> None:
    path.write_text(json.dumps(doc), encoding="utf-8")


def test_mx6_failed_production_is_the_active_groups_source_not_success(
    room_pillar: TabularStack,
) -> None:
    path = room_pillar.derived / STOPES_ARTIFACT
    original = path.read_bytes()
    try:
        doc = json.loads(original)
        doc["status"], doc["failureReason"] = "FAILED", "PRODUCTION_COMPLEXITY_LIMIT: test"
        _rewrite(path, doc)
        b = export(room_pillar.client, room_pillar.sid)
        assert_integrity(b)
        om = b.omissions()
        assert om["ROOM_PILLAR"] == "SOURCE_NOT_SUCCESS"
        assert "STOPES" not in om and "CUT_FILL" not in om
        detail = next(o for o in b.manifest["omissions"] if o["group"] == "ROOM_PILLAR")["detail"]
        assert "PRODUCTION_COMPLEXITY_LIMIT" in detail
        assert not any(p.startswith("production/") for p in b.entries)
        assert not any(e["kind"] in {"ROOM", "BENCH", "PILLAR"} for e in b.manifest["entities"])
        mm = b.json("semantics/mining_method.json")
        assert mm["production"]["status"] == "FAILED" and mm["production"]["unitCount"] == 0
    finally:
        path.write_bytes(original)


def test_mx7_payload_method_authority_guard(cut_fill: TabularStack) -> None:
    path = cut_fill.derived / STOPES_ARTIFACT
    original = path.read_bytes()
    try:
        # (a) the payload declares another method than the scenario requests
        doc = json.loads(original)
        doc["method"] = "ROOM_AND_PILLAR"
        _rewrite(path, doc)
        r = cut_fill.client.post(f"/api/v1/scenarios/{cut_fill.sid}{EXPORT}")
        assert r.status_code == 409, r.text
        code = r.json()["detail"]["code"]
        assert code in {"MINE_EXCHANGE_EXPORT_FAILED", "ARTIFACT_MALFORMED"}
        if code == "MINE_EXCHANGE_EXPORT_FAILED":
            assert "authority mismatch" in r.json()["detail"]["message"]
        # (b) a Longhole-SHAPED document under the scenario's own method name
        doc = json.loads(original)
        longhole_shaped = {
            "status": "SUCCESS",
            "failureReason": None,
            "sourceRevision": doc["sourceRevision"],
            "method": "CUT_AND_FILL",
            "stopes": [],
            "metrics": None,
        }
        _rewrite(path, longhole_shaped)
        r = cut_fill.client.post(f"/api/v1/scenarios/{cut_fill.sid}{EXPORT}")
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] in {"MINE_EXCHANGE_EXPORT_FAILED", "ARTIFACT_MALFORMED"}
    finally:
        path.write_bytes(original)
    assert export(cut_fill.client, cut_fill.sid).files  # healthy again


def test_mx8_corrupted_geometry_is_refused_never_trusted(
    cut_fill: TabularStack, room_pillar: TabularStack
) -> None:
    def corrupt(stack: TabularStack, mutate: Any, code: str = "MINE_EXCHANGE_EXPORT_FAILED") -> str:
        path = stack.derived / STOPES_ARTIFACT
        original = path.read_bytes()
        doc = json.loads(original)
        mutate(doc)
        _rewrite(path, doc)
        try:
            return _refused(stack.client, stack.sid, code)
        finally:
            path.write_bytes(original)

    def bad_cut_index(doc: dict[str, Any]) -> None:
        doc["cuts"][0]["geometry"]["triangleIndices"][0] = 99

    assert "closed-solid QA failed" in corrupt(cut_fill, bad_cut_index)

    def wrong_cut_volume(doc: dict[str, Any]) -> None:
        doc["cuts"][0]["geometricVolumeM3"] *= 1.01

    assert "disagrees with the artifact's geometric volume" in corrupt(cut_fill, wrong_cut_volume)

    def wrong_backfill_volume(doc: dict[str, Any]) -> None:
        doc["backfills"][0]["volumeM3"] *= 1.01

    assert "disagrees with its cut's" in corrupt(cut_fill, wrong_backfill_volume)

    def duplicate_cut(doc: dict[str, Any]) -> None:
        doc["cuts"].append(json.loads(json.dumps(doc["cuts"][0])))

    assert "duplicate cut id" in corrupt(cut_fill, duplicate_cut)

    def orphan_backfill(doc: dict[str, Any]) -> None:
        doc["backfills"][0]["sourceCutId"] = "CUT:NOPE"

    msg = corrupt(cut_fill, orphan_backfill)
    assert "has no backfill" in msg or "unknown cut" in msg

    # a structurally malformed flat list (length not a multiple of three, or
    # non-numeric) is a TYPED refusal — never NumPy's bare ValueError → 500
    def ragged_vertex_list(doc: dict[str, Any]) -> None:
        doc["cuts"][0]["geometry"]["vertices"].append(1.0)

    assert "flat list of coordinate triples" in corrupt(cut_fill, ragged_vertex_list)

    def ragged_index_list(doc: dict[str, Any]) -> None:
        del doc["cuts"][0]["geometry"]["triangleIndices"][0]

    assert "flat list of coordinate triples" in corrupt(cut_fill, ragged_index_list)

    # a non-numeric coordinate is already refused STRUCTURALLY by the reader
    # (typed 409 ARTIFACT_MALFORMED at the read boundary, rule 189 analogue)
    def non_numeric_vertex(doc: dict[str, Any]) -> None:
        doc["cuts"][0]["geometry"]["vertices"][0] = "x"

    assert "not usable" in corrupt(cut_fill, non_numeric_vertex, "ARTIFACT_MALFORMED")

    def flipped_pillar_face(doc: dict[str, Any]) -> None:
        t = doc["pillars"][0]["geometry"]["triangleIndices"]
        t[0], t[1] = t[1], t[0]

    assert "closed-solid QA failed" in corrupt(room_pillar, flipped_pillar_face)

    def wrong_bench_volume(doc: dict[str, Any]) -> None:
        doc["extractionUnits"][0]["geometricVolumeM3"] *= 1.01

    assert "disagrees with the artifact's geometric volume" in corrupt(
        room_pillar, wrong_bench_volume
    )

    def unit_of_unknown_room(doc: dict[str, Any]) -> None:
        doc["extractionUnits"][0]["roomId"] = "ROOM:R999:C999"

    msg = corrupt(room_pillar, unit_of_unknown_room)
    assert "do not match" in msg or "unknown room" in msg
    assert export(cut_fill.client, cut_fill.sid).files
    assert export(room_pillar.client, room_pillar.sid).files
