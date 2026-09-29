"""Phase 23C MineResult 1.0 contract units (MR-1 … MR-9): package reader
security and budgets, normalization / identity, chainage projection, units,
the atomic result store, the typed error table, the frame builders and the
canonical export — no design chain, no API."""

from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from minegen.exchange.models import MINE_EXCHANGE_VERSION, SourceSnapshot
from minegen.results import package as package_module
from minegen.results.errors import (
    ResultDataInvalidError,
    ResultError,
    ResultIdentityAmbiguousError,
    ResultIdentityUnresolvedError,
    ResultLimitExceededError,
    ResultNotFoundError,
    ResultPackageInvalidError,
    ResultPublicationFailedError,
    ResultSourceScenarioMismatchError,
    ResultSourceSnapshotMismatchError,
    ResultStaleError,
    ResultUnitUnsupportedError,
    ResultVersionUnsupportedError,
)
from minegen.results.export import export_result
from minegen.results.frames import operations_frame, ventilation_frame
from minegen.results.geometry import EdgeGeometry, chainage_to_xyz, pack_polylines
from minegen.results.importers import VENTSIM_MEMBERS
from minegen.results.importers.common import EdgeIndex, geometry_arrays
from minegen.results.models import (
    MINE_RESULT_VERSION,
    MineResultManifest,
    ResultCounts,
    ResultMetricAvailability,
    ResultPackageManifest,
    ResultProvenance,
    ResultTimeAxis,
)
from minegen.results.normalization import (
    content_sha256,
    load_npz,
    npz_bytes,
    result_id_for,
    str_array,
)
from minegen.results.package import read_result_package
from minegen.results.store import ResultStore
from minegen.results.units import require_canonical_unit, resolve_unit
from minegen.services.scenario_service import ScenarioStore

SNAPSHOT = SourceSnapshot(
    scenario_revision="s1",
    arrays_revision="a1",
    active_ramp_source="LEGACY",
    artifact_revisions={"network.json": "n1"},
)


def _manifest_doc(**over: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "mineResultVersion": MINE_RESULT_VERSION,
        "resultDomain": "VENTILATION",
        "sourceApplication": "VENTSIM",
        "sourceAdapter": "VENTSIM",
        "sourceAdapterVersion": "0.2.0",
        "sourceMineExchangeVersion": MINE_EXCHANGE_VERSION,
        "sourceScenarioId": "scn",
        "sourceSnapshot": SNAPSHOT.model_dump(mode="json", by_alias=True),
        "timeAxis": {"kind": "STATIC"},
        "units": {"airflowM3s": "m3/s"},
    }
    doc.update(over)
    return doc


def _zip(files: dict[str, bytes], *, names: list[str] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name in names or sorted(files):
            zf.writestr(name, files[name])
    return buf.getvalue()


def _package(**over: Any) -> dict[str, bytes]:
    return {
        "result_manifest.json": json.dumps(_manifest_doc(**over)).encode(),
        "airway_results.csv": b"edgeId,airflowM3s\nE1,1.0\n",
    }


# -- MR-1 versions ----------------------------------------------------------- #


def test_mr1_versions_are_pinned() -> None:
    assert MINE_RESULT_VERSION == "1.0.0"
    assert MINE_EXCHANGE_VERSION == "1.3.0"  # MineExchange is NOT bumped by results


# -- MR-2 package reader security / budgets ---------------------------------- #


def test_mr2_bad_zip_and_empty_archive_are_typed() -> None:
    with pytest.raises(ResultPackageInvalidError, match="not a ZIP"):
        read_result_package(b"not a zip", allowed_members=VENTSIM_MEMBERS)
    with pytest.raises(ResultPackageInvalidError, match="no file"):
        read_result_package(_zip({}), allowed_members=VENTSIM_MEMBERS)


@pytest.mark.parametrize("bad", ["../result_manifest.json", "/abs/result_manifest.json"])
def test_mr2_traversal_and_absolute_members_are_refused(bad: str) -> None:
    files = {bad: b"{}", "airway_results.csv": b"edgeId\n"}
    with pytest.raises(ResultPackageInvalidError):
        read_result_package(_zip(files), allowed_members=VENTSIM_MEMBERS)


def test_mr2_nested_directories_and_duplicates_are_refused() -> None:
    files = {"a/result_manifest.json": b"{}", "b/airway_results.csv": b"edgeId\n"}
    with pytest.raises(ResultPackageInvalidError, match="flat files"):
        read_result_package(_zip(files), allowed_members=VENTSIM_MEMBERS)
    files = {"kit/x/result_manifest.json": b"{}", "kit/airway_results.csv": b"edgeId\n"}
    with pytest.raises(ResultPackageInvalidError, match="flat files"):
        read_result_package(_zip(files), allowed_members=VENTSIM_MEMBERS)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("result_manifest.json", b"{}")
        zf.writestr("result_manifest.json", b"{}")
    with pytest.raises(ResultPackageInvalidError, match="duplicate member"):
        read_result_package(buf.getvalue(), allowed_members=VENTSIM_MEMBERS)


def test_mr2_one_top_level_directory_is_stripped() -> None:
    files = {f"roundtrip/{k}": v for k, v in _package().items()}
    pkg = read_result_package(_zip(files), allowed_members=VENTSIM_MEMBERS)
    assert pkg.prefix == "roundtrip/" and set(pkg.files) == set(_package())


def test_mr2_unknown_members_missing_manifest_and_bad_manifest_are_typed() -> None:
    files = _package()
    files["extra.bin"] = b"\x00"
    with pytest.raises(ResultPackageInvalidError, match="unknown members"):
        read_result_package(_zip(files), allowed_members=VENTSIM_MEMBERS)
    files = _package()
    del files["result_manifest.json"]
    with pytest.raises(ResultPackageInvalidError, match="missing required file"):
        read_result_package(_zip(files), allowed_members=VENTSIM_MEMBERS)
    files = _package()
    files["result_manifest.json"] = b"[1, 2]"
    with pytest.raises(ResultPackageInvalidError, match="not an object"):
        read_result_package(_zip(files), allowed_members=VENTSIM_MEMBERS)
    files["result_manifest.json"] = b"\xff\xfe not json"
    with pytest.raises(ResultPackageInvalidError, match="not a JSON"):
        read_result_package(_zip(files), allowed_members=VENTSIM_MEMBERS)
    files = _package(sourceApplication="EXCEL")
    with pytest.raises(ResultPackageInvalidError, match="does not validate"):
        read_result_package(_zip(files), allowed_members=VENTSIM_MEMBERS)


def test_mr2_unsupported_version_is_typed_before_validation() -> None:
    files = _package(mineResultVersion="0.9.0", resultDomain="NOPE")
    with pytest.raises(ResultVersionUnsupportedError, match=re.escape("0.9.0")):
        read_result_package(_zip(files), allowed_members=VENTSIM_MEMBERS)


def test_mr2_budgets_are_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(package_module, "MAX_UPLOAD_BYTES", 10)
    with pytest.raises(ResultLimitExceededError, match="limit is 10"):
        read_result_package(_zip(_package()), allowed_members=VENTSIM_MEMBERS)
    monkeypatch.setattr(package_module, "MAX_UPLOAD_BYTES", 64 * 1024 * 1024)
    monkeypatch.setattr(package_module, "MAX_ZIP_MEMBERS", 1)
    with pytest.raises(ResultLimitExceededError, match="members"):
        read_result_package(_zip(_package()), allowed_members=VENTSIM_MEMBERS)
    monkeypatch.setattr(package_module, "MAX_ZIP_MEMBERS", 32)
    monkeypatch.setattr(package_module, "MAX_UNCOMPRESSED_BYTES", 20)
    with pytest.raises(ResultLimitExceededError, match="uncompressed"):
        read_result_package(_zip(_package()), allowed_members=VENTSIM_MEMBERS)
    monkeypatch.setattr(package_module, "MAX_UNCOMPRESSED_BYTES", 256 * 1024 * 1024)
    monkeypatch.setattr(package_module, "MAX_MEMBER_BYTES", 20)
    with pytest.raises(ResultLimitExceededError, match="member declares"):
        read_result_package(_zip(_package()), allowed_members=VENTSIM_MEMBERS)


def test_mr2_zip_bomb_declaration_mismatch_is_refused() -> None:
    data = _zip(_package())
    # a member whose central-directory size lies about its payload
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        info = zf.getinfo("airway_results.csv")
        offset = info.header_offset
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.getinfo("airway_results.csv").header_offset == offset
    # patch the central directory file_size of the CSV to a bigger value
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        infos = zf.infolist()
    cd_start = data.find(b"PK\x01\x02")
    assert cd_start > 0
    patched = bytearray(data)
    for idx in range(cd_start, len(data) - 4):
        if patched[idx : idx + 4] == b"PK\x01\x02":
            name_len = int.from_bytes(patched[idx + 28 : idx + 30], "little")
            name = bytes(patched[idx + 46 : idx + 46 + name_len])
            if name == b"airway_results.csv":
                patched[idx + 24 : idx + 28] = (10_000).to_bytes(4, "little")  # uncompressed size
    assert len(infos) == 2
    with pytest.raises((ResultLimitExceededError, ResultPackageInvalidError)):
        read_result_package(bytes(patched), allowed_members=VENTSIM_MEMBERS)


def test_mr2_non_utf8_text_member_is_typed() -> None:
    files = _package()
    files["airway_results.csv"] = b"edgeId,airflowM3s\n\xff\xfe,1\n"
    pkg = read_result_package(_zip(files), allowed_members=VENTSIM_MEMBERS)
    with pytest.raises(ResultPackageInvalidError, match="UTF-8"):
        pkg.text("airway_results.csv")


# -- MR-3 normalization / identity ------------------------------------------ #


def _arrays(**over: np.ndarray) -> dict[str, np.ndarray]:
    base: dict[str, np.ndarray] = {
        "edge_ids": str_array(["E1", "E2"]),
        "times": np.asarray([0.0], dtype=np.float64),
        "vent_airflowM3s": np.asarray([[1.0, np.nan]], dtype=np.float64),
    }
    base.update(over)
    return base


def test_mr3_digest_is_canonical_and_content_sensitive() -> None:
    a = _arrays()
    b = dict(reversed(list(a.items())))  # different insertion order, same content
    assert content_sha256(a) == content_sha256(b)
    c = _arrays(vent_airflowM3s=np.asarray([[1.0000001, np.nan]]))
    assert content_sha256(a) != content_sha256(c)
    # NaN placement is part of the content (missing != zero)
    d = _arrays(vent_airflowM3s=np.asarray([[1.0, 0.0]]))
    assert content_sha256(a) != content_sha256(d)


def test_mr3_result_id_binds_content_snapshot_domain_and_application() -> None:
    digest = content_sha256(_arrays())
    rid = result_id_for(digest, SNAPSHOT, "VENTILATION", "VENTSIM")
    assert len(rid) == 16 and rid == result_id_for(digest, SNAPSHOT, "VENTILATION", "VENTSIM")
    other = SNAPSHOT.model_copy(update={"arrays_revision": "a2"})
    assert rid != result_id_for(digest, other, "VENTILATION", "VENTSIM")
    assert rid != result_id_for(digest, SNAPSHOT, "OPERATIONS", "VENTSIM")
    assert rid != result_id_for(digest, SNAPSHOT, "VENTILATION", "ANYLOGIC")


def test_mr3_npz_round_trip_and_read_not_trust() -> None:
    a = _arrays()
    data = npz_bytes(a)
    assert npz_bytes(a) == data
    loaded = load_npz(data, expected_sha256=content_sha256(a))
    assert content_sha256(loaded) == content_sha256(a)
    with pytest.raises(ResultPackageInvalidError, match="normalizedSha256"):
        load_npz(data, expected_sha256="0" * 64)
    with pytest.raises(ResultPackageInvalidError, match="not readable"):
        load_npz(b"junk", expected_sha256=content_sha256(a))


# -- MR-4 chainage projection ------------------------------------------------- #


def test_mr4_chainage_is_arc_length_on_the_source_polyline() -> None:
    pts = np.asarray([[0, 0, 0], [3, 0, 0], [3, 4, 0]], dtype=np.float64)  # 3 + 4 = 7 m
    assert np.allclose(chainage_to_xyz(pts, 0.0), [0, 0, 0])
    assert np.allclose(chainage_to_xyz(pts, 1.0), [3, 4, 0])
    assert np.allclose(chainage_to_xyz(pts, 3.0 / 7.0), [3, 0, 0])
    assert np.allclose(chainage_to_xyz(pts, 5.0 / 7.0), [3, 2, 0])
    assert np.allclose(chainage_to_xyz(pts[:1], 0.5), [0, 0, 0])
    points, offsets = pack_polylines(
        [
            EdgeGeometry("A", "RAMP", "n0", "n1", "e:A", pts),
            EdgeGeometry("B", "DRIFT", "n1", "n2", "e:B", pts[:2]),
        ]
    )
    assert points.shape == (5, 3) and offsets.tolist() == [0, 3, 5]


# -- MR-5 units ---------------------------------------------------------------- #


def test_mr5_units_are_explicit_never_inferred() -> None:
    m = ResultPackageManifest.model_validate(_manifest_doc())
    assert resolve_unit(m, "airflowM3s", "m3/s", subject="x") == (1.0, 0.0)
    with pytest.raises(ResultUnitUnsupportedError, match="no declared unit"):
        resolve_unit(m, "pressurePa", "Pa", subject="x")
    m = ResultPackageManifest.model_validate(_manifest_doc(units={"airflowM3s": "cfm"}))
    with pytest.raises(ResultUnitUnsupportedError, match="no explicit conversion"):
        resolve_unit(m, "airflowM3s", "m3/s", subject="x")
    m = ResultPackageManifest.model_validate(
        _manifest_doc(
            units={"airflowM3s": "cfm"},
            unitConversions=[
                {"metric": "airflowM3s", "sourceUnit": "cfm", "factor": 0.000471947, "offset": 0.0}
            ],
        )
    )
    assert resolve_unit(m, "airflowM3s", "m3/s", subject="x") == (0.000471947, 0.0)
    m = ResultPackageManifest.model_validate(
        _manifest_doc(
            units={"airflowM3s": "cfm"},
            unitConversions=[{"metric": "airflowM3s", "sourceUnit": "cfm", "factor": 0.0}],
        )
    )
    with pytest.raises(ResultUnitUnsupportedError, match="zero factor"):
        resolve_unit(m, "airflowM3s", "m3/s", subject="x")
    m = ResultPackageManifest.model_validate(_manifest_doc(units={"loadTonnes": "kg"}))
    with pytest.raises(ResultUnitUnsupportedError, match="canonical unit 't'"):
        require_canonical_unit(m, "loadTonnes", "t", subject="x")
    with pytest.raises(ResultUnitUnsupportedError, match="no declared unit"):
        require_canonical_unit(m, "utilization", "fraction", subject="x")


# -- MR-6 store --------------------------------------------------------------- #


def _stored_manifest(result_id: str, arrays: dict[str, np.ndarray]) -> MineResultManifest:
    return MineResultManifest(
        mine_result_version=MINE_RESULT_VERSION,
        result_id=result_id,
        result_domain="VENTILATION",
        source_application="VENTSIM",
        source_adapter="VENTSIM",
        source_adapter_version="0.2.0",
        source_mine_exchange_version=MINE_EXCHANGE_VERSION,
        source_scenario_id="scn",
        source_snapshot=SNAPSHOT,
        run_label="",
        description="",
        time_axis=ResultTimeAxis(kind="STATIC", unit=None, sample_count=1, start=None, end=None),
        files=[],
        metrics=[
            ResultMetricAvailability(
                name="airflowM3s", unit="m3/s", available=True, sample_count=1, min=1.0, max=1.0
            )
        ],
        summary_metrics=[],
        counts=ResultCounts(edge_count=1, time_count=1, sample_count=1),
        provenance=ResultProvenance(
            source_application="VENTSIM",
            source_application_version="",
            source_adapter_name="VENTSIM",
            source_adapter_version="0.2.0",
            source_mine_exchange_version=MINE_EXCHANGE_VERSION,
            source_scenario_id="scn",
            original_file_sha256="0" * 64,
            imported_file_names=["airway_results.csv"],
        ),
        import_source_sha256="0" * 64,
        normalized_sha256=content_sha256(arrays),
        sign_convention=None,
        notes=[],
    )


def test_mr6_store_publishes_atomically_idempotently_and_reads_untrusted(
    tmp_path: Path,
) -> None:
    scenarios = ScenarioStore(tmp_path / "scenarios")
    (tmp_path / "scenarios" / "scn").mkdir(parents=True)
    store = ResultStore(scenarios)
    arrays = _arrays()
    rid = result_id_for(content_sha256(arrays), SNAPSHOT, "VENTILATION", "VENTSIM")
    manifest = _stored_manifest(rid, arrays)
    manifest_bytes = json.dumps(manifest.model_dump(mode="json", by_alias=True)).encode()
    assert store.list_ids("scn") == []
    assert store.publish(
        "scn",
        rid,
        manifest_bytes=manifest_bytes,
        normalized_bytes=npz_bytes(arrays),
        source_bytes=b"zip",
    )
    root = store.results_dir("scn")
    assert sorted(p.name for p in root.iterdir()) == [rid]  # no temp sibling left behind
    assert sorted(p.name for p in (root / rid).iterdir()) == [
        "manifest.json",
        "normalized.npz",
        "source.zip",
    ]
    # results live OUTSIDE derived/
    assert not (scenarios.derived_dir("scn") / rid).exists()
    assert root.parent == scenarios.scenario_dir("scn")
    # identical id again: kept untouched, this call did not install
    before = (root / rid / "manifest.json").stat().st_mtime_ns
    assert not store.publish(
        "scn", rid, manifest_bytes=b"other", normalized_bytes=b"x", source_bytes=b"y"
    )
    assert (root / rid / "manifest.json").stat().st_mtime_ns == before
    assert (root / rid / "source.zip").read_bytes() == b"zip"
    # a temp / trash directory is never listed
    (root / ".tmp-junk").mkdir()
    assert store.list_ids("scn") == [rid]
    stored = store.read_manifest("scn", rid)
    assert stored.manifest.result_id == rid and store.read_source(stored) == b"zip"
    assert content_sha256(store.read_normalized(stored)) == content_sha256(arrays)
    # READ ≠ TRUST
    with pytest.raises(ResultNotFoundError):
        store.read_manifest("scn", "not-a-result-id")
    with pytest.raises(ResultNotFoundError):
        store.read_manifest("scn", "0" * 16)
    (root / rid / "manifest.json").write_text("{", encoding="utf-8")
    with pytest.raises(ResultPackageInvalidError, match="not readable"):
        store.read_manifest("scn", rid)
    wrong = manifest.model_copy(update={"result_id": "1" * 16})
    (root / rid / "manifest.json").write_text(
        json.dumps(wrong.model_dump(mode="json", by_alias=True)), encoding="utf-8"
    )
    with pytest.raises(ResultPackageInvalidError, match="in folder"):
        store.read_manifest("scn", rid)
    (root / rid / "manifest.json").write_bytes(manifest_bytes)
    (root / rid / "normalized.npz").unlink()
    with pytest.raises(ResultPackageInvalidError, match=re.escape("normalized.npz")):
        store.read_normalized(store.read_manifest("scn", rid))
    store.delete("scn", rid)
    assert store.list_ids("scn") == [] and not (root / rid).exists()
    with pytest.raises(ResultNotFoundError):
        store.delete("scn", rid)


# -- MR-7 error table ---------------------------------------------------------- #


def test_mr7_every_result_error_carries_its_wire_code_and_status() -> None:
    table = {
        ResultPackageInvalidError: ("RESULT_PACKAGE_INVALID", 422),
        ResultVersionUnsupportedError: ("RESULT_VERSION_UNSUPPORTED", 422),
        ResultSourceScenarioMismatchError: ("RESULT_SOURCE_SCENARIO_MISMATCH", 409),
        ResultSourceSnapshotMismatchError: ("RESULT_SOURCE_SNAPSHOT_MISMATCH", 409),
        ResultIdentityUnresolvedError: ("RESULT_IDENTITY_UNRESOLVED", 409),
        ResultIdentityAmbiguousError: ("RESULT_IDENTITY_AMBIGUOUS", 409),
        ResultUnitUnsupportedError: ("RESULT_UNIT_UNSUPPORTED", 422),
        ResultDataInvalidError: ("RESULT_DATA_INVALID", 422),
        ResultLimitExceededError: ("RESULT_LIMIT_EXCEEDED", 413),
        ResultNotFoundError: ("RESULT_NOT_FOUND", 404),
        ResultStaleError: ("RESULT_STALE", 409),
        ResultPublicationFailedError: ("RESULT_PUBLICATION_FAILED", 500),
    }
    for cls, (code, status) in table.items():
        assert issubclass(cls, ResultError)
        assert (cls.code, cls.http_status) == (code, status), cls
        err = cls("why", subject="what")
        assert str(err) == f"{code}: what: why" and err.reason == "why"
    assert {c.code for c in table} == {c for c, _ in table.values()}  # distinct codes


# -- MR-8 frames ------------------------------------------------------------- #


def _index() -> EdgeIndex:
    a = np.asarray([[0, 0, 0], [10, 0, 0]], dtype=np.float64)
    b = np.asarray([[10, 0, 0], [10, 0, -10]], dtype=np.float64)
    return EdgeIndex(
        [
            EdgeGeometry("B", "DRIFT", "n1", "n2", "e:B", b),
            EdgeGeometry("A", "RAMP", "n0", "n1", "e:A", a),
        ]
    )


def test_mr8_ventilation_frame_holds_last_and_omits_missing() -> None:
    index = _index()
    arrays = geometry_arrays(index)
    assert arrays["edge_ids"].tolist() == ["A", "B"]  # sorted identity space
    arrays["times"] = np.asarray([10.0, 20.0])
    arrays["vent_airflowM3s"] = np.asarray([[1.0, np.nan], [2.0, 5.0]])
    f = ventilation_frame("r", arrays, kind="ELAPSED_SECONDS", metric="airflowM3s", time=15.0)
    assert f.sample_time == 10.0 and [v.model_dump() for v in f.values] == [
        {"edge_id": "A", "value": 1.0}
    ]
    assert f.missing_edge_ids == ["B"] and f.min == f.max == 1.0
    assert f.sign_convention is not None and "sourceNodeId" in f.sign_convention
    f = ventilation_frame("r", arrays, kind="ELAPSED_SECONDS", metric="airflowM3s", time=99.0)
    assert f.sample_time == 20.0 and len(f.values) == 2 and f.missing_edge_ids == []
    f = ventilation_frame("r", arrays, kind="ELAPSED_SECONDS", metric="airflowM3s", time=5.0)
    assert f.sample_time is None and f.values == [] and f.missing_edge_ids == ["A", "B"]
    assert f.min is None and f.max is None
    with pytest.raises(ResultDataInvalidError, match="unknown ventilation metric"):
        ventilation_frame("r", arrays, kind="ELAPSED_SECONDS", metric="nope", time=1.0)
    with pytest.raises(ResultDataInvalidError, match="not available"):
        ventilation_frame("r", arrays, kind="ELAPSED_SECONDS", metric="pressurePa", time=1.0)
    with pytest.raises(ResultDataInvalidError, match="time is required"):
        ventilation_frame("r", arrays, kind="ELAPSED_SECONDS", metric="airflowM3s", time=None)
    s = ventilation_frame("r", arrays, kind="STATIC", metric="airflowM3s", time=None)
    assert s.time is None and s.sample_time is None and len(s.values) == 1


def test_mr8_operations_frame_interpolates_same_edge_only() -> None:
    index = _index()
    arrays = geometry_arrays(index)
    # T1: A@0 (t=0) → A@1 (t=10) → B@0.5 (t=20); T2: single sample at t=5
    samples = [
        (0.0, "T1", "A", 0.0),
        (5.0, "T2", "B", 0.5),
        (10.0, "T1", "A", 1.0),
        (20.0, "T1", "B", 0.5),
    ]
    agents = ["T1", "T2"]
    arrays["agent_ids"] = str_array(agents)
    arrays["agent_kinds"] = str_array(["TRUCK", ""])
    arrays["sample_time"] = np.asarray([s[0] for s in samples])
    arrays["sample_agent"] = np.asarray([agents.index(s[1]) for s in samples])
    arrays["sample_edge"] = np.asarray([index.ids.index(s[2]) for s in samples])
    arrays["sample_chainage"] = np.asarray([s[3] for s in samples])
    arrays["sample_status"] = str_array(["", "", "", ""])
    arrays["sample_load"] = np.asarray([np.nan, 3.0, np.nan, np.nan])
    arrays["sample_xyz"] = np.asarray(
        [chainage_to_xyz(index.edges[index.ids.index(s[2])].points, s[3]) for s in samples]
    )
    arrays["em_time"] = np.asarray([0.0, 10.0])
    arrays["em_edge"] = np.asarray([0, 0])
    arrays["em_utilization"] = np.asarray([0.2, 0.8])
    arrays["em_queueCount"] = np.asarray([1.0, np.nan])
    arrays["em_haulageTonnesPerHour"] = np.asarray([np.nan, np.nan])
    arrays["em_travelTimeSeconds"] = np.asarray([np.nan, np.nan])

    f = operations_frame("r", arrays, kind="ELAPSED_SECONDS", time=5.0)
    by = {v.agent_id: v for v in f.vehicles}
    assert by["T1"].placement == "INTERPOLATED" and by["T1"].chainage_fraction == 0.5
    assert (by["T1"].x, by["T1"].y, by["T1"].z) == (5.0, 0.0, 0.0)
    assert by["T2"].placement == "SAMPLE" and by["T2"].load_tonnes == 3.0
    assert by["T2"].agent_kind is None and by["T1"].agent_kind == "TRUCK"
    assert [m.model_dump() for m in f.edge_metrics] == [
        {
            "edge_id": "A",
            "sample_time": 0.0,
            "utilization": 0.2,
            "queue_count": 1,
            "haulage_tonnes_per_hour": None,
            "travel_time_seconds": None,
        }
    ]
    # across an edge change (A@1 at t=10 → B@0.5 at t=20) the previous sample is HELD
    f = operations_frame("r", arrays, kind="ELAPSED_SECONDS", time=15.0)
    by = {v.agent_id: v for v in f.vehicles}
    assert list(by) == ["T1"]  # T2 exists only at its single sample time
    assert by["T1"].placement == "SAMPLE" and by["T1"].edge_id == "A"
    assert by["T1"].chainage_fraction == 1.0 and (by["T1"].x, by["T1"].y) == (10.0, 0.0)
    assert f.edge_metrics[0].sample_time == 10.0 and f.edge_metrics[0].queue_count is None
    # outside [first, last] a vehicle does not exist; before the first metric sample nothing
    f = operations_frame("r", arrays, kind="ELAPSED_SECONDS", time=-1.0)
    assert f.vehicles == [] and f.edge_metrics == []
    f = operations_frame("r", arrays, kind="ELAPSED_SECONDS", time=20.0)
    assert {v.agent_id for v in f.vehicles} == {"T1"} and f.vehicles[0].edge_id == "B"
    assert operations_frame("r", arrays, kind="ELAPSED_SECONDS", time=21.0).vehicles == []
    with pytest.raises(ResultDataInvalidError, match="finite"):
        operations_frame("r", arrays, kind="ELAPSED_SECONDS", time=float("nan"))


# -- MR-9 canonical export ----------------------------------------------------- #


def test_mr9_export_is_deterministic_and_reads_back_as_a_package() -> None:
    index = _index()
    arrays = geometry_arrays(index)
    arrays["times"] = np.asarray([0.0])
    arrays["metric_names"] = str_array(["airflowM3s"])
    arrays["vent_airflowM3s"] = np.asarray([[1.5, np.nan]])
    rid = result_id_for(content_sha256(arrays), SNAPSHOT, "VENTILATION", "VENTSIM")
    manifest = _stored_manifest(rid, arrays)
    data = export_result(manifest, arrays)
    assert export_result(manifest, arrays) == data
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        assert names == sorted(names) and all(n.startswith("mine_result/") for n in names)
        assert {i.date_time for i in zf.infolist()} == {(1980, 1, 1, 0, 0, 0)}
        csv = zf.read("mine_result/airway_results.csv").decode()
    assert csv.splitlines() == ["edgeId,time,airflowM3s", "A,,1.5"]  # missing row omitted
    pkg = read_result_package(data, allowed_members=VENTSIM_MEMBERS)
    assert pkg.prefix == "mine_result/" and pkg.manifest.source_snapshot == SNAPSHOT
    assert pkg.manifest.units == {"airflowM3s": "m3/s"} and pkg.manifest.time_axis.kind == "STATIC"
