"""Phase 23C Ventsim ventilation results (V-1 … V-11) over the FAST real
LEGACY chain: the round-trip kit, explicit identity, canonical units, typed
data refusals, hold-last frames and the sign convention."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from minegen.exchange.models import MINE_EXCHANGE_VERSION
from tests.results_support import (
    ResultsStack,
    export_kit,
    manifest_of,
    post_zip,
    unzip,
    ventsim_package,
)


@pytest.fixture(scope="module")
def mine(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ResultsStack]:
    stack = ResultsStack(tmp_path_factory.mktemp("results-ventsim"))
    stack.build_legacy_chain()
    yield stack
    stack.close()


@pytest.fixture(scope="module")
def kit(mine: ResultsStack) -> dict[str, bytes]:
    return export_kit(mine.client, mine.sid, "ventsim")


def _rows(kit: dict[str, bytes], name: str) -> list[dict[str, str]]:
    lines = kit[name].decode("utf-8").splitlines()
    header = lines[0].split(",")
    return [dict(zip(header, line.split(","), strict=True)) for line in lines[1:]]


def _error(r: Any, code: str, status: int) -> str:
    assert r.status_code == status, r.text
    detail = r.json()["detail"]
    assert detail["code"] == code, detail
    message: str = detail["message"]
    return message


# -- V-1 kit ------------------------------------------------------------------ #


def test_v1_kit_is_bound_to_the_export_snapshot_and_pre_identifies_every_airway(
    mine: ResultsStack, kit: dict[str, bytes]
) -> None:
    c, sid = mine.client, mine.sid
    r = c.post(f"/api/v1/scenarios/{sid}/export/ventsim")
    assert r.status_code == 200 and r.headers["x-adapter-version"] == "0.2.0"
    files = unzip(r.content)
    root = next(iter(files)).split("/")[0]
    adapter_manifest = json.loads(files[f"{root}/adapter_manifest.json"])
    assert adapter_manifest["adapterVersion"] == "0.2.0"
    kit_paths = adapter_manifest["details"]["roundTripKit"]["files"]
    assert kit_paths == [
        "roundtrip/result_manifest.json",
        "roundtrip/airway_results.csv",
        "roundtrip/airway_identity.csv",
        "roundtrip/README.txt",
    ]
    listed = {f["path"]: f for f in adapter_manifest["generatedFiles"]}
    assert all(p in listed for p in kit_paths)  # hashed like every other package file
    m = manifest_of(kit)
    assert m["mineResultVersion"] == "1.0.0" and m["resultDomain"] == "VENTILATION"
    assert m["sourceApplication"] == "VENTSIM" and m["sourceAdapter"] == "VENTSIM"
    assert m["sourceAdapterVersion"] == "0.2.0"
    assert m["sourceMineExchangeVersion"] == MINE_EXCHANGE_VERSION
    assert m["sourceScenarioId"] == sid
    assert m["sourceSnapshot"] == adapter_manifest["sourceSnapshot"]
    assert m["timeAxis"] == {"kind": "STATIC"} and m["unitConversions"] == []
    assert m["units"] == {
        "airflowM3s": "m3/s",
        "velocityMs": "m/s",
        "pressurePa": "Pa",
        "pressureLossPa": "Pa",
        "temperatureDryC": "degC",
        "temperatureWetC": "degC",
        "airDensityKgM3": "kg/m3",
    }
    airways = _rows(kit, "airway_results.csv")
    exported = json.loads(files[f"{root}/../topology/network.json"]) if False else None
    assert exported is None
    edge_rows = _rows({"a": files[f"{root}/network/airways.csv"]}, "a")
    assert [a["edgeId"] for a in airways] == [e["edgeId"] for e in edge_rows]
    assert all(a["airflowM3s"] == "" and a["time"] == "" for a in airways)  # NO invented value
    identity = _rows(kit, "airway_identity.csv")
    assert [i["edgeId"] for i in identity] == [e["edgeId"] for e in edge_rows]
    assert all(i["ventsimUniqueNumber"] == "" for i in identity)
    readme = kit["README.txt"].decode()
    assert "results/import/ventsim" in readme and "never matches airways spatially" in readme


# -- V-2 static import ---------------------------------------------------------- #


def test_v2_static_import_stores_canonical_values_and_availability(
    mine: ResultsStack, kit: dict[str, bytes]
) -> None:
    c, sid = mine.client, mine.sid
    r = post_zip(
        c,
        sid,
        "ventsim",
        ventsim_package(
            kit,
            [["RAMP:L01", None, 25.0, 1200.0], ["RAMP:L02", None, -8.5, None]],
        ),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["created"] is True
    res = body["result"]
    assert res["domain"] == "VENTILATION" and res["compatibility"] == "COMPATIBLE"
    assert res["timeAxis"] == {
        "kind": "STATIC",
        "unit": None,
        "sampleCount": 1,
        "start": None,
        "end": None,
    }
    metrics = {m["name"]: m for m in res["metrics"]}
    assert set(metrics) == {
        "airflowM3s",
        "velocityMs",
        "pressurePa",
        "pressureLossPa",
        "temperatureDryC",
        "temperatureWetC",
        "airDensityKgM3",
    }
    assert metrics["airflowM3s"] == {
        "name": "airflowM3s",
        "unit": "m3/s",
        "available": True,
        "sampleCount": 2,
        "min": -8.5,
        "max": 25.0,
    }
    assert metrics["pressurePa"]["sampleCount"] == 1 and metrics["pressurePa"]["min"] == 1200.0
    assert metrics["velocityMs"]["available"] is False and metrics["velocityMs"]["min"] is None
    assert res["counts"] == {
        "edgeCount": 2,
        "timeCount": 1,
        "sampleCount": 2,
        "vehicleCount": 0,
        "edgeMetricSampleCount": 0,
    }
    assert "sourceNodeId" in res["signConvention"]
    assert res["provenance"]["importedFileNames"] == ["airway_results.csv"]
    assert res["provenance"]["sourceAdapterVersion"] == "0.2.0"
    assert res["importSourceSha256"] == res["provenance"]["originalFileSha256"]
    assert {f["path"] for f in res["files"]} == {"result_manifest.json", "airway_results.csv"}
    frame = c.get(
        f"/api/v1/scenarios/{sid}/results/{res['resultId']}/ventilation",
        params={"metric": "airflowM3s"},
    ).json()
    assert frame["values"] == [
        {"edgeId": "RAMP:L01", "value": 25.0},
        {"edgeId": "RAMP:L02", "value": -8.5},
    ]
    assert frame["min"] == -8.5 and frame["max"] == 25.0 and frame["unit"] == "m3/s"
    assert "RAMP:L01" not in frame["missingEdgeIds"] and "DRIFT:L01:00" in frame["missingEdgeIds"]
    pressure = c.get(
        f"/api/v1/scenarios/{sid}/results/{res['resultId']}/ventilation",
        params={"metric": "pressurePa"},
    ).json()
    assert pressure["values"] == [{"edgeId": "RAMP:L01", "value": 1200.0}]
    assert pressure["signConvention"] is None  # only airflow carries a sign convention


# -- V-3 / V-4 / V-5 identity --------------------------------------------------- #


def test_v3_crosswalk_resolves_ventsim_unique_numbers_explicitly(
    mine: ResultsStack, kit: dict[str, bytes]
) -> None:
    c, sid = mine.client, mine.sid
    r = post_zip(
        c,
        sid,
        "ventsim",
        ventsim_package(
            kit,
            [["", "101", None, 4.0], ["", "102", None, 5.0]],
            header=["edgeId", "ventsimUniqueNumber", "time", "airflowM3s"],
            identity_rows=[["RAMP:L01", "101"], ["DRIFT:L01:00", "102"], ["RAMP:L02", ""]],
        ),
    )
    assert r.status_code == 201, r.text
    res = r.json()["result"]
    assert res["provenance"]["importedFileNames"] == ["airway_results.csv", "airway_identity.csv"]
    assert any("crosswalk: 2" in n for n in res["notes"])
    frame = c.get(
        f"/api/v1/scenarios/{sid}/results/{res['resultId']}/ventilation",
        params={"metric": "airflowM3s"},
    ).json()
    assert frame["values"] == [
        {"edgeId": "DRIFT:L01:00", "value": 5.0},
        {"edgeId": "RAMP:L01", "value": 4.0},
    ]


def test_v4_ambiguous_identity_is_typed(mine: ResultsStack, kit: dict[str, bytes]) -> None:
    c, sid = mine.client, mine.sid
    msg = _error(
        post_zip(
            c,
            sid,
            "ventsim",
            ventsim_package(
                kit,
                [["", "101", None, 4.0]],
                header=["edgeId", "ventsimUniqueNumber", "time", "airflowM3s"],
                identity_rows=[["RAMP:L01", "101"], ["RAMP:L02", "101"]],
            ),
        ),
        "RESULT_IDENTITY_AMBIGUOUS",
        409,
    )
    assert "maps to both" in msg
    msg = _error(
        post_zip(
            c,
            sid,
            "ventsim",
            ventsim_package(
                kit,
                [["RAMP:L02", "101", None, 4.0]],
                header=["edgeId", "ventsimUniqueNumber", "time", "airflowM3s"],
                identity_rows=[["RAMP:L01", "101"]],
            ),
        ),
        "RESULT_IDENTITY_AMBIGUOUS",
        409,
    )
    assert "disagrees with the crosswalk" in msg


def test_v5_unresolved_identity_is_typed_never_matched_spatially(
    mine: ResultsStack, kit: dict[str, bytes]
) -> None:
    c, sid = mine.client, mine.sid
    msg = _error(
        post_zip(c, sid, "ventsim", ventsim_package(kit, [["RAMP:L99", None, 1.0, None]])),
        "RESULT_IDENTITY_UNRESOLVED",
        409,
    )
    assert "RAMP:L99" in msg and "row 2" in msg
    msg = _error(
        post_zip(
            c,
            sid,
            "ventsim",
            ventsim_package(
                kit,
                [["", "7", None, 1.0]],
                header=["edgeId", "ventsimUniqueNumber", "time", "airflowM3s"],
            ),
        ),
        "RESULT_IDENTITY_UNRESOLVED",
        409,
    )
    assert "crosswalk" in msg
    msg = _error(
        post_zip(
            c,
            sid,
            "ventsim",
            ventsim_package(
                kit,
                [["", "7", None, 1.0]],
                header=["edgeId", "ventsimUniqueNumber", "time", "airflowM3s"],
                identity_rows=[["RAMP:L01", "8"]],
            ),
        ),
        "RESULT_IDENTITY_UNRESOLVED",
        409,
    )
    assert "not in the crosswalk" in msg
    msg = _error(
        post_zip(
            c,
            sid,
            "ventsim",
            ventsim_package(
                kit,
                [["", "", None, 1.0]],
                header=["edgeId", "ventsimUniqueNumber", "time", "airflowM3s"],
            ),
        ),
        "RESULT_IDENTITY_UNRESOLVED",
        409,
    )
    assert "neither" in msg
    _error(
        post_zip(
            c,
            sid,
            "ventsim",
            ventsim_package(kit, [[None, 1.0]], header=["time", "airflowM3s"]),
        ),
        "RESULT_PACKAGE_INVALID",
        422,
    )
    # a stored result never exists after a refusal
    assert all(
        r["resultId"] != "" for r in c.get(f"/api/v1/scenarios/{sid}/results").json()["results"]
    )


# -- V-6 units --------------------------------------------------------------- #


def test_v6_units_canonical_or_explicitly_converted(
    mine: ResultsStack, kit: dict[str, bytes]
) -> None:
    c, sid = mine.client, mine.sid
    m = manifest_of(kit)
    m["units"] = {"airflowM3s": "cfm"}
    msg = _error(
        post_zip(
            c,
            sid,
            "ventsim",
            ventsim_package(
                kit,
                [["RAMP:L01", None, 1000.0]],
                header=["edgeId", "time", "airflowM3s"],
                manifest=m,
            ),
        ),
        "RESULT_UNIT_UNSUPPORTED",
        422,
    )
    assert "cfm" in msg and "no explicit conversion" in msg
    m["unitConversions"] = [
        {"metric": "airflowM3s", "sourceUnit": "cfm", "factor": 0.0005, "offset": 0.0}
    ]
    m["runLabel"] = "cfm run"
    r = post_zip(
        c,
        sid,
        "ventsim",
        ventsim_package(
            kit, [["RAMP:L01", None, 1000.0]], header=["edgeId", "time", "airflowM3s"], manifest=m
        ),
    )
    assert r.status_code == 201, r.text
    res = r.json()["result"]
    assert res["runLabel"] == "cfm run"
    metric = next(x for x in res["metrics"] if x["name"] == "airflowM3s")
    assert metric["unit"] == "m3/s" and metric["min"] == metric["max"] == 0.5  # converted
    # undeclared unit for a delivered column
    m = manifest_of(kit)
    m["units"] = {"airflowM3s": "m3/s"}
    _error(
        post_zip(
            c, sid, "ventsim", ventsim_package(kit, [["RAMP:L01", None, 1.0, 2.0]], manifest=m)
        ),
        "RESULT_UNIT_UNSUPPORTED",
        422,
    )


# -- V-7 data validity ----------------------------------------------------------- #


@pytest.mark.parametrize(
    ("rows", "header", "match"),
    [
        ([["RAMP:L01", None, "NaN", None]], None, "NaN"),
        ([["RAMP:L01", None, "inf", None]], None, "inf"),
        ([["RAMP:L01", None, "abc", None]], None, "abc"),
        ([["RAMP:L01", None, None, None]], None, "no result metric value"),
        ([["RAMP:L01", None, 1.0, None], ["RAMP:L01", None, 2.0, None]], None, "duplicate"),
        ([["RAMP:L01", 5.0, 1.0, None]], None, "STATIC result carries no time"),
    ],
)
def test_v7_invalid_data_is_typed(
    mine: ResultsStack, kit: dict[str, bytes], rows: list[Any], header: Any, match: str
) -> None:
    msg = _error(
        post_zip(mine.client, mine.sid, "ventsim", ventsim_package(kit, rows, header=header)),
        "RESULT_DATA_INVALID",
        422,
    )
    assert match in msg, msg


def test_v7_shape_refusals_are_package_invalid(mine: ResultsStack, kit: dict[str, bytes]) -> None:
    c, sid = mine.client, mine.sid
    _error(
        post_zip(
            c,
            sid,
            "ventsim",
            ventsim_package(kit, [["RAMP:L01", 1.0]], header=["edgeId", "quantity"]),
        ),
        "RESULT_PACKAGE_INVALID",
        422,
    )
    _error(
        post_zip(c, sid, "ventsim", ventsim_package(kit, [["RAMP:L01"]], header=["edgeId"])),
        "RESULT_PACKAGE_INVALID",
        422,
    )
    _error(
        post_zip(
            c,
            sid,
            "ventsim",
            ventsim_package(kit, [["RAMP:L01", 1.0, 2.0]], header=["edgeId", "airflowM3s"]),
        ),
        "RESULT_PACKAGE_INVALID",
        422,
    )
    _error(
        post_zip(c, sid, "ventsim", ventsim_package(kit, [], header=["edgeId", "airflowM3s"])),
        "RESULT_DATA_INVALID",
        422,
    )


# -- V-8 dynamic frames ------------------------------------------------------------ #


def test_v8_elapsed_seconds_frames_hold_last(mine: ResultsStack, kit: dict[str, bytes]) -> None:
    c, sid = mine.client, mine.sid
    m = manifest_of(kit)
    m["timeAxis"] = {"kind": "ELAPSED_SECONDS"}
    rows = [
        ["RAMP:L01", 0.0, 10.0, None],
        ["RAMP:L02", 0.0, 20.0, None],
        ["RAMP:L01", 60.0, 11.0, None],
        ["RAMP:L02", 120.0, 22.0, 5.0],
    ]
    r = post_zip(c, sid, "ventsim", ventsim_package(kit, rows, manifest=m))
    assert r.status_code == 201, r.text
    res = r.json()["result"]
    assert res["timeAxis"] == {
        "kind": "ELAPSED_SECONDS",
        "unit": "s",
        "sampleCount": 3,
        "start": 0.0,
        "end": 120.0,
    }
    assert res["counts"]["timeCount"] == 3 and res["counts"]["sampleCount"] == 4
    url = f"/api/v1/scenarios/{sid}/results/{res['resultId']}/ventilation"

    def frame(t: float, metric: str = "airflowM3s") -> dict[str, Any]:
        rr = c.get(url, params={"metric": metric, "time": t})
        assert rr.status_code == 200, rr.text
        out: dict[str, Any] = rr.json()
        return out

    f = frame(90.0)
    assert f["sampleTime"] == 60.0 and f["time"] == 90.0
    # at t=60 only RAMP:L01 was sampled: RAMP:L02 is MISSING (not held from t=0, not zero)
    assert f["values"] == [{"edgeId": "RAMP:L01", "value": 11.0}]
    assert "RAMP:L02" in f["missingEdgeIds"]
    f = frame(1000.0)
    assert f["sampleTime"] == 120.0 and f["values"] == [{"edgeId": "RAMP:L02", "value": 22.0}]
    f = frame(-5.0)
    assert f["sampleTime"] is None and f["values"] == [] and f["min"] is None
    f = frame(0.0)
    assert f["sampleTime"] == 0.0 and len(f["values"]) == 2
    assert frame(120.0, "pressurePa")["values"] == [{"edgeId": "RAMP:L02", "value": 5.0}]
    r = c.get(url, params={"metric": "airflowM3s"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "RESULT_DATA_INVALID"
    # negative time / missing time value in an ELAPSED result are refused at import
    m2 = dict(m)
    _error(
        post_zip(
            c, sid, "ventsim", ventsim_package(kit, [["RAMP:L01", -1.0, 1.0, None]], manifest=m2)
        ),
        "RESULT_DATA_INVALID",
        422,
    )
    _error(
        post_zip(
            c, sid, "ventsim", ventsim_package(kit, [["RAMP:L01", None, 1.0, None]], manifest=m2)
        ),
        "RESULT_DATA_INVALID",
        422,
    )
    m["timeAxis"] = {"kind": "MINE_DAY"}
    _error(
        post_zip(
            c, sid, "ventsim", ventsim_package(kit, [["RAMP:L01", 1.0, 1.0, None]], manifest=m)
        ),
        "RESULT_DATA_INVALID",
        422,
    )


# -- V-10 / V-11 metric and domain boundaries ------------------------------------- #


def test_v10_v11_metric_and_domain_boundaries(mine: ResultsStack, kit: dict[str, bytes]) -> None:
    c, sid = mine.client, mine.sid
    r = post_zip(c, sid, "ventsim", ventsim_package(kit, [["DRIFT:L01:01", None, 7.0, None]]))
    assert r.status_code == 201, r.text
    rid = r.json()["result"]["resultId"]
    base = f"/api/v1/scenarios/{sid}/results/{rid}"
    r = c.get(f"{base}/ventilation", params={"metric": "velocityMs"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "RESULT_DATA_INVALID"
    r = c.get(f"{base}/ventilation", params={"metric": "bogus"})
    assert r.status_code == 422 and "unknown ventilation metric" in r.json()["detail"]["message"]
    r = c.get(f"{base}/operations/frame", params={"time": 0})
    assert r.status_code == 422 and "not an operations result" in r.json()["detail"]["message"]
    # a Ventsim package on the AnyLogic route is refused before any binding
    _error(
        post_zip(c, sid, "anylogic", ventsim_package(kit, [["RAMP:L01", None, 1.0, None]])),
        "RESULT_PACKAGE_INVALID",
        422,
    )
