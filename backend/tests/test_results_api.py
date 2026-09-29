"""Phase 23C result lifecycle, binding, compatibility, isolation and
read-only proofs over the FAST real LEGACY chain (directive §11–§24,
§45–§50, §82–§90, rules 213–218)."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from minegen.exchange.models import SourceSnapshot
from minegen.results.package import MAX_UPLOAD_BYTES
from minegen.services.result_service import ResultService, snapshot_differences
from tests.results_support import (
    ResultsStack,
    anylogic_package,
    export_kit,
    manifest_of,
    post_zip,
    scenario_state,
    unzip,
    ventsim_package,
    zip_bytes,
)
from tests.test_world_api import _create


@pytest.fixture(scope="module")
def mine(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ResultsStack]:
    stack = ResultsStack(tmp_path_factory.mktemp("results-api"))
    stack.build_legacy_chain()
    yield stack
    stack.close()


@pytest.fixture(scope="module")
def kits(mine: ResultsStack) -> dict[str, dict[str, bytes]]:
    return {
        "ventsim": export_kit(mine.client, mine.sid, "ventsim"),
        "anylogic": export_kit(mine.client, mine.sid, "anylogic"),
    }


def _list(mine: ResultsStack) -> list[dict[str, Any]]:
    r = mine.client.get(f"/api/v1/scenarios/{mine.sid}/results")
    assert r.status_code == 200, r.text
    out: list[dict[str, Any]] = r.json()["results"]
    return out


def _vent(kits: dict[str, dict[str, bytes]], value: float, **kw: Any) -> bytes:
    return ventsim_package(kits["ventsim"], [["RAMP:L01", None, value, None]], **kw)


# -- lifecycle ------------------------------------------------------------------- #


def test_lifecycle_import_is_idempotent_and_delete_is_final(
    mine: ResultsStack, kits: dict[str, dict[str, bytes]]
) -> None:
    c, sid = mine.client, mine.sid
    data = _vent(kits, 101.0)
    r = post_zip(c, sid, "ventsim", data)
    assert r.status_code == 201 and r.headers["x-mineresult-version"] == "1.0.0", r.text
    assert r.headers["cache-control"] == "no-store"
    first = r.json()
    rid = first["result"]["resultId"]
    assert len(rid) == 16
    r = post_zip(c, sid, "ventsim", data)
    assert r.status_code == 200, r.text
    assert r.json()["created"] is False and r.json()["result"] == first["result"]
    assert [x["resultId"] for x in _list(mine) if x["resultId"] == rid] == [rid]
    detail = c.get(f"/api/v1/scenarios/{sid}/results/{rid}")
    assert detail.status_code == 200 and detail.json() == first["result"]
    assert not {"values", "vehicles", "edgeMetrics"} & set(detail.json())  # metadata only
    assert c.delete(f"/api/v1/scenarios/{sid}/results/{rid}").status_code == 204
    assert rid not in {x["resultId"] for x in _list(mine)}
    r = c.get(f"/api/v1/scenarios/{sid}/results/{rid}")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "RESULT_NOT_FOUND"
    r = c.delete(f"/api/v1/scenarios/{sid}/results/{rid}")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "RESULT_NOT_FOUND"
    r = c.get(f"/api/v1/scenarios/{sid}/results/{rid}/export")
    assert r.status_code == 404
    r = c.get(f"/api/v1/scenarios/{sid}/results/not-a-result-id")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "RESULT_NOT_FOUND"
    # deleting a result never touches the mine
    assert c.get(f"/api/v1/scenarios/{sid}/network").status_code == 200


def test_unknown_scenario_and_missing_world_are_typed(client: TestClient) -> None:
    for path in ("results", "results/0000000000000000"):
        r = client.get(f"/api/v1/scenarios/nope/{path}")
        assert r.status_code == 404 and r.json()["detail"]["code"] == "SCENARIO_NOT_FOUND"
    r = client.post(
        "/api/v1/scenarios/nope/results/import/ventsim",
        content=b"x",
        headers={"content-type": "application/zip"},
    )
    assert r.status_code == 404 and r.json()["detail"]["code"] == "SCENARIO_NOT_FOUND"
    sid = _create(client)
    assert client.get(f"/api/v1/scenarios/{sid}/results").json() == {
        "scenarioId": sid,
        "results": [],
    }
    r = client.post(
        f"/api/v1/scenarios/{sid}/results/import/ventsim",
        content=zip_bytes({"result_manifest.json": b"{}"}),
        headers={"content-type": "application/zip"},
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "WORLD_NOT_GENERATED", r.text


# -- upload guards ------------------------------------------------------------------ #


def test_upload_guards(mine: ResultsStack, kits: dict[str, dict[str, bytes]]) -> None:
    c, sid = mine.client, mine.sid
    url = f"/api/v1/scenarios/{sid}/results/import/ventsim"
    r = c.post(url, json={"not": "a zip"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "RESULT_PACKAGE_INVALID"
    assert "Content-Type" in r.json()["detail"]["message"]
    r = c.post(url, content=b"", headers={"content-type": "application/zip"})
    assert r.status_code == 422 and "empty" in r.json()["detail"]["message"]
    r = c.post(url, content=b"PK garbage", headers={"content-type": "application/zip"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "RESULT_PACKAGE_INVALID"
    r = c.post(
        url,
        content=b"x",
        headers={"content-type": "application/zip", "content-length": str(MAX_UPLOAD_BYTES + 1)},
    )
    assert r.status_code == 413 and r.json()["detail"]["code"] == "RESULT_LIMIT_EXCEEDED"
    m = manifest_of(kits["ventsim"])
    m["mineResultVersion"] = "2.0.0"
    r = post_zip(c, sid, "ventsim", _vent(kits, 1.0, manifest=m))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "RESULT_VERSION_UNSUPPORTED"
    # every refusal leaves NO result behind
    before = {x["resultId"] for x in _list(mine)}
    r = post_zip(c, sid, "ventsim", zip_bytes({"result_manifest.json": b"{}"}))
    assert r.status_code == 422
    assert {x["resultId"] for x in _list(mine)} == before


# -- binding ------------------------------------------------------------------------- #


def test_binding_refuses_other_scenarios_and_other_snapshots(
    mine: ResultsStack, kits: dict[str, dict[str, bytes]]
) -> None:
    c, sid = mine.client, mine.sid
    m = manifest_of(kits["ventsim"])
    m["sourceScenarioId"] = "someone-else"
    r = post_zip(c, sid, "ventsim", _vent(kits, 1.0, manifest=m))
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "RESULT_SOURCE_SCENARIO_MISMATCH"
    m = manifest_of(kits["ventsim"])
    m["sourceSnapshot"]["artifactRevisions"]["network.json"] = "0" * 16
    r = post_zip(c, sid, "ventsim", _vent(kits, 1.0, manifest=m))
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "RESULT_SOURCE_SNAPSHOT_MISMATCH"
    assert "artifactRevisions.network.json" in r.json()["detail"]["message"]
    m = manifest_of(kits["ventsim"])
    m["sourceSnapshot"]["activeRampSource"] = "LAYOUT_V2"
    r = post_zip(c, sid, "ventsim", _vent(kits, 1.0, manifest=m))
    assert r.status_code == 409 and "activeRampSource" in r.json()["detail"]["message"]
    a = SourceSnapshot(
        scenario_revision="s",
        arrays_revision="a",
        active_ramp_source="LEGACY",
        artifact_revisions={"x": "1"},
    )
    b = a.model_copy(update={"artifact_revisions": {"x": "2", "y": "3"}, "scenario_revision": "t"})
    assert snapshot_differences(a, b) == [
        "scenarioRevision",
        "artifactRevisions.x",
        "artifactRevisions.y",
    ]
    assert snapshot_differences(a, a) == []


# -- compatibility ------------------------------------------------------------------ #


def test_stale_results_survive_regeneration_and_refuse_only_overlay(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    stack = ResultsStack(tmp_path_factory.mktemp("results-stale"))
    try:
        stack.build_legacy_chain()
        c, sid = stack.client, stack.sid
        kit = export_kit(c, sid, "ventsim")
        akit = export_kit(c, sid, "anylogic")
        r = post_zip(c, sid, "ventsim", ventsim_package(kit, [["RAMP:L01", None, 3.0, None]]))
        assert r.status_code == 201, r.text
        vid = r.json()["result"]["resultId"]
        r = post_zip(
            c,
            sid,
            "anylogic",
            anylogic_package(akit, [[0, "T1", "TRUCK", "RAMP:L01", 0.5, "", 1]]),
        )
        assert r.status_code == 201, r.text
        oid = r.json()["result"]["resultId"]
        base = f"/api/v1/scenarios/{sid}/results"
        exported_before = c.get(f"{base}/{vid}/export").content

        # a downstream regeneration (new network revision) → STALE, never deleted
        r = c.post(f"/api/v1/scenarios/{sid}/network/generate")
        assert r.status_code == 200 and r.json()["status"] == "SUCCESS"
        listed = {x["resultId"]: x for x in c.get(base).json()["results"]}
        assert listed[vid]["compatibility"] == "STALE"
        assert listed[oid]["compatibility"] == "STALE"
        assert c.get(f"{base}/{vid}").json()["compatibility"] == "STALE"
        for path, params in (
            (f"{base}/{vid}/ventilation", {"metric": "airflowM3s"}),
            (f"{base}/{vid}/geometry", {}),
            (f"{base}/{oid}/operations/frame", {"time": 0}),
            (f"{base}/{oid}/geometry", {}),
        ):
            r = c.get(path, params=params)
            assert r.status_code == 409, r.text
            assert r.json()["detail"]["code"] == "RESULT_STALE"
            assert "older mine snapshot" in r.json()["detail"]["message"]
        r = c.get(f"{base}/{vid}/export")
        assert r.status_code == 200 and r.content == exported_before  # export still allowed
        # a fresh kit is bound to the NEW snapshot and imports COMPATIBLE
        kit2 = export_kit(c, sid, "ventsim")
        assert manifest_of(kit2)["sourceSnapshot"] != manifest_of(kit)["sourceSnapshot"]
        r = post_zip(c, sid, "ventsim", ventsim_package(kit2, [["RAMP:L01", None, 3.0, None]]))
        assert r.status_code == 201 and r.json()["result"]["compatibility"] == "COMPATIBLE"
        vid2 = r.json()["result"]["resultId"]
        assert vid2 != vid  # same content, different snapshot → different identity
        # the OLD kit is refused now
        r = post_zip(c, sid, "ventsim", ventsim_package(kit, [["RAMP:L01", None, 4.0, None]]))
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "RESULT_SOURCE_SNAPSHOT_MISMATCH"

        # world regeneration clears derived/ but NEVER results/
        results_dir = stack.store.scenario_dir(sid) / "results"
        assert sorted(p.name for p in results_dir.iterdir() if p.is_dir()) == sorted(
            [vid, oid, vid2]
        )
        r = c.post(f"/api/v1/scenarios/{sid}/world/generate")
        assert r.status_code == 200, r.text
        assert not (stack.derived / "network.json").exists()  # derived/ cleared
        assert sorted(p.name for p in results_dir.iterdir() if p.is_dir()) == sorted(
            [vid, oid, vid2]
        )
        listed = {x["resultId"]: x for x in c.get(base).json()["results"]}
        assert {x["compatibility"] for x in listed.values()} == {"STALE"}
        r = c.get(f"{base}/{vid2}/ventilation", params={"metric": "airflowM3s"})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "RESULT_STALE"
        assert c.delete(f"{base}/{vid}").status_code == 204
        # a scenario PUT (full invalidation) keeps the results too
        doc = c.get(f"/api/v1/scenarios/{sid}").json()
        doc.pop("id"), doc.pop("schemaVersion")
        doc["name"] = "renamed"
        assert c.put(f"/api/v1/scenarios/{sid}", json=doc).status_code == 200
        listed = {x["resultId"]: x for x in c.get(base).json()["results"]}
        assert set(listed) == {oid, vid2} and listed[oid]["compatibility"] == "STALE"
        # a world-less scenario still lists (everything STALE), frames typed
        r = c.get(f"{base}/{oid}/operations/frame", params={"time": 0})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "RESULT_STALE"
    finally:
        stack.close()


# -- read-only / no generation / isolation --------------------------------------------- #


def test_results_are_read_only_over_the_mine_and_never_exported_back(
    mine: ResultsStack, kits: dict[str, dict[str, bytes]]
) -> None:
    c, sid = mine.client, mine.sid
    root = mine.store.scenario_dir(sid)
    before = scenario_state(root)
    r = post_zip(c, sid, "ventsim", _vent(kits, 202.0))
    assert r.status_code == 201, r.text
    rid = r.json()["result"]["resultId"]
    base = f"/api/v1/scenarios/{sid}/results"
    assert c.get(base).status_code == 200
    assert c.get(f"{base}/{rid}").status_code == 200
    assert c.get(f"{base}/{rid}/geometry").status_code == 200
    assert c.get(f"{base}/{rid}/ventilation", params={"metric": "airflowM3s"}).status_code == 200
    assert c.get(f"{base}/{rid}/export").status_code == 200
    assert scenario_state(root) == before  # scenario.json, arrays.npz, derived/* untouched
    derived_names = sorted(p.name for p in mine.derived.iterdir())
    assert not any("result" in n for n in derived_names)  # no derived artifact exists
    assert (root / "results" / rid).is_dir() and not (mine.derived / "results").exists()
    # the MineExchange bundle and the adapter packages never carry results (no feedback loop)
    r = c.post(f"/api/v1/scenarios/{sid}/export/mine-exchange")
    assert r.status_code == 200
    names = list(unzip(r.content))
    assert not any("result" in n.lower() for n in names)
    for target in ("ventsim", "anylogic", "unity", "unreal"):
        r = c.post(f"/api/v1/scenarios/{sid}/export/{target}")
        assert r.status_code == 200
        assert not any(rid in n or "normalized" in n for n in unzip(r.content))
    # importing does not change the export snapshot (results are not a snapshot input)
    kit_after = export_kit(c, sid, "ventsim")
    assert (
        manifest_of(kit_after)["sourceSnapshot"] == manifest_of(kits["ventsim"])["sourceSnapshot"]
    )
    assert scenario_state(root) == before
    assert c.delete(f"{base}/{rid}").status_code == 204
    assert scenario_state(root) == before


def test_results_are_scenario_scoped(mine: ResultsStack, kits: dict[str, dict[str, bytes]]) -> None:
    c, sid = mine.client, mine.sid
    r = post_zip(c, sid, "ventsim", _vent(kits, 303.0))
    assert r.status_code == 201, r.text
    rid = r.json()["result"]["resultId"]
    other = _create(c)
    assert c.get(f"/api/v1/scenarios/{other}/results").json()["results"] == []
    r = c.get(f"/api/v1/scenarios/{other}/results/{rid}")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "RESULT_NOT_FOUND"
    assert c.delete(f"/api/v1/scenarios/{other}/results/{rid}").status_code == 404
    assert c.delete(f"/api/v1/scenarios/{sid}/results/{rid}").status_code == 204


# -- export --------------------------------------------------------------------------- #


def test_export_is_byte_identical_and_re_imports_to_the_same_identity(
    mine: ResultsStack, kits: dict[str, dict[str, bytes]]
) -> None:
    c, sid = mine.client, mine.sid
    r = post_zip(
        c,
        sid,
        "anylogic",
        anylogic_package(
            kits["anylogic"],
            [
                [0, "X1", "TRUCK", "RAMP:L02", 0.0, "GO", 2.5],
                [9, "X1", "TRUCK", "RAMP:L02", 0.9, "GO", None],
            ],
            edge_rows=[[0, "RAMP:L02", 0.25, 1]],
            summary_rows=[["vehicleCount", 1, "count"]],
        ),
    )
    assert r.status_code == 201, r.text
    detail = r.json()["result"]
    rid = detail["resultId"]
    base = f"/api/v1/scenarios/{sid}/results"
    a = c.get(f"{base}/{rid}/export")
    b = c.get(f"{base}/{rid}/export")
    assert a.status_code == 200 and a.content == b.content
    assert a.headers["content-type"] == "application/zip"
    assert a.headers["content-disposition"] == (
        f'attachment; filename="minegen_{sid}_mineresult_operations_{rid}.zip"'
    )
    files = unzip(a.content)
    assert sorted(files) == [
        "mine_result/README.txt",
        "mine_result/edge_metrics.csv",
        "mine_result/manifest.json",
        "mine_result/result_manifest.json",
        "mine_result/summary_metrics.csv",
        "mine_result/vehicle_samples.csv",
    ]
    stored = json.loads(files["mine_result/manifest.json"])
    assert stored["resultId"] == rid and stored["normalizedSha256"] == detail["normalizedSha256"]
    assert files["mine_result/vehicle_samples.csv"].decode().splitlines() == [
        "time,agentId,agentKind,edgeId,chainageFraction,status,loadTonnes",
        "0.0,X1,TRUCK,RAMP:L02,0.0,GO,2.5",
        "9.0,X1,TRUCK,RAMP:L02,0.9,GO,",
    ]
    assert files["mine_result/edge_metrics.csv"].decode().splitlines() == [
        "time,edgeId,utilization,queueCount",
        "0.0,RAMP:L02,0.25,1",
    ]
    with zipfile.ZipFile(io.BytesIO(a.content)) as zf:
        assert {i.date_time for i in zf.infolist()} == {(1980, 1, 1, 0, 0, 0)}
    # the export IS an importable package: same identity, nothing new stored
    r = post_zip(c, sid, "anylogic", a.content)
    assert r.status_code == 200 and r.json()["created"] is False, r.text
    assert r.json()["result"]["resultId"] == rid
    assert c.delete(f"{base}/{rid}").status_code == 204
    r = post_zip(c, sid, "anylogic", a.content)
    assert r.status_code == 201 and r.json()["result"]["resultId"] == rid
    # the re-imported result carries the SAME canonical data files; only the stored
    # manifest's provenance (the source ZIP it was imported from) differs
    again = unzip(c.get(f"{base}/{rid}/export").content)
    assert {k: v for k, v in again.items() if k != "mine_result/manifest.json"} == {
        k: v for k, v in files.items() if k != "mine_result/manifest.json"
    }
    re_stored = json.loads(again["mine_result/manifest.json"])
    assert re_stored["normalizedSha256"] == stored["normalizedSha256"]
    assert re_stored["importSourceSha256"] == hashlib.sha256(a.content).hexdigest()
    assert c.delete(f"{base}/{rid}").status_code == 204


# -- race protection ------------------------------------------------------------------ #


def test_import_refuses_a_mine_that_moves_during_the_import(
    mine: ResultsStack, kits: dict[str, dict[str, bytes]], monkeypatch: pytest.MonkeyPatch
) -> None:
    c, sid = mine.client, mine.sid
    original = ResultService.import_result
    calls = {"n": 0}
    exchange = mine.client.app.dependency_overrides  # type: ignore[attr-defined]
    assert exchange  # the overrides exist
    from minegen.services.exchange_service import ExchangeService

    real = ExchangeService.observe_source_snapshot

    def moved(self: ExchangeService, scenario_id: str) -> SourceSnapshot:
        snap = real(self, scenario_id)
        calls["n"] += 1
        return snap.model_copy(update={"arrays_revision": "moved-" + snap.arrays_revision})

    monkeypatch.setattr(ExchangeService, "observe_source_snapshot", moved)
    before = {x["resultId"] for x in _list(mine)} if False else None
    monkeypatch.setattr(ExchangeService, "observe_source_snapshot", real)
    before = {x["resultId"] for x in _list(mine)}
    monkeypatch.setattr(ExchangeService, "observe_source_snapshot", moved)
    r = post_zip(c, sid, "ventsim", _vent(kits, 404.0))
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "READ_SNAPSHOT_CHANGED"
    assert calls["n"] == 1 and original is ResultService.import_result
    monkeypatch.setattr(ExchangeService, "observe_source_snapshot", real)
    assert {x["resultId"] for x in _list(mine)} == before  # nothing published
    results_dir = mine.store.scenario_dir(sid) / "results"
    assert not any(p.name.startswith(".tmp") for p in results_dir.iterdir())


# -- stored-folder READ ≠ TRUST at the API ------------------------------------------ #


def test_corrupt_stored_result_is_a_typed_refusal(
    mine: ResultsStack, kits: dict[str, dict[str, bytes]]
) -> None:
    c, sid = mine.client, mine.sid
    r = post_zip(c, sid, "ventsim", _vent(kits, 505.0))
    assert r.status_code == 201, r.text
    rid = r.json()["result"]["resultId"]
    folder = mine.store.scenario_dir(sid) / "results" / rid
    npz = folder / "normalized.npz"
    good = npz.read_bytes()
    npz.write_bytes(good[:-8] + b"\x00" * 8)
    r = c.get(f"/api/v1/scenarios/{sid}/results/{rid}/ventilation", params={"metric": "airflowM3s"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "RESULT_PACKAGE_INVALID"
    npz.write_bytes(good)
    (folder / "manifest.json").write_text("{", encoding="utf-8")
    r = c.get(f"/api/v1/scenarios/{sid}/results")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "RESULT_PACKAGE_INVALID"
    r = c.get(f"/api/v1/scenarios/{sid}/results/{rid}")
    assert r.status_code == 422
    assert c.delete(f"/api/v1/scenarios/{sid}/results/{rid}").status_code == 204
    assert not folder.exists()


def test_result_folder_layout_and_source_evidence(
    mine: ResultsStack, kits: dict[str, dict[str, bytes]]
) -> None:
    c, sid = mine.client, mine.sid
    data = _vent(kits, 606.0)
    r = post_zip(c, sid, "ventsim", data)
    assert r.status_code == 201, r.text
    detail = r.json()["result"]
    rid = detail["resultId"]
    folder: Path = mine.store.scenario_dir(sid) / "results" / rid
    assert sorted(p.name for p in folder.iterdir()) == [
        "manifest.json",
        "normalized.npz",
        "source.zip",
    ]
    assert (folder / "source.zip").read_bytes() == data  # the original ZIP, byte for byte
    assert detail["importSourceSha256"] == hashlib.sha256(data).hexdigest()
    stored = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert stored["resultId"] == rid and stored["sourceScenarioId"] == sid
    assert stored["sourceSnapshot"] == manifest_of(kits["ventsim"])["sourceSnapshot"]
    assert c.delete(f"/api/v1/scenarios/{sid}/results/{rid}").status_code == 204


# -- B3 (PR #51 review): the upload limit is a MEMORY budget ----------------------- #


def test_upload_without_content_length_is_refused_while_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A chunked / undeclared-length upload is refused the moment the received
    bytes exceed MAX_UPLOAD_BYTES — the body is never buffered first."""
    import asyncio

    from starlette.requests import Request

    from minegen.api import results as results_api
    from minegen.results.errors import ResultLimitExceededError

    limit = 10 * 1024
    chunk = b"x" * 1024
    monkeypatch.setattr(results_api, "MAX_UPLOAD_BYTES", limit)
    delivered = 0

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        delivered += len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": True}  # endless body

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/x",
        "headers": [(b"content-type", b"application/zip")],  # no content-length
        "query_string": b"",
    }
    with pytest.raises(ResultLimitExceededError):
        asyncio.run(results_api._upload(Request(scope, receive)))
    assert delivered <= limit + len(chunk), delivered  # aborted at the boundary


def test_unsupported_zip_compression_is_a_typed_package_refusal(
    mine: ResultsStack, kits: dict[str, dict[str, bytes]]
) -> None:
    """A member with an unsupported compression method (zipfile raises
    NotImplementedError) is RESULT_PACKAGE_INVALID, never a bare 500."""
    data = bytearray(zip_bytes({"result_manifest.json": kits["ventsim"]["result_manifest.json"]}))
    data[8:10] = (99).to_bytes(2, "little")  # local header compression method
    cd = data.find(b"PK\x01\x02")
    data[cd + 10 : cd + 12] = (99).to_bytes(2, "little")  # central directory
    r = post_zip(mine.client, mine.sid, "ventsim", bytes(data))
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "RESULT_PACKAGE_INVALID"
    assert "compression" in r.json()["detail"]["message"]
