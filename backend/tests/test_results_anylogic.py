"""Phase 23C AnyLogic operations results (A-1 … A-11) over the FAST real
LEGACY chain: the kit, declared time axes, vehicle sample validation,
same-edge interpolation, edge metrics, summary metrics and units."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import numpy as np
import pytest

from minegen.results.geometry import chainage_to_xyz
from tests.results_support import (
    ResultsStack,
    anylogic_package,
    export_kit,
    manifest_of,
    post_zip,
    unzip,
)


@pytest.fixture(scope="module")
def mine(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ResultsStack]:
    stack = ResultsStack(tmp_path_factory.mktemp("results-anylogic"))
    stack.build_legacy_chain()
    yield stack
    stack.close()


@pytest.fixture(scope="module")
def kit(mine: ResultsStack) -> dict[str, bytes]:
    return export_kit(mine.client, mine.sid, "anylogic")


def _error(r: Any, code: str, status: int) -> str:
    assert r.status_code == status, r.text
    detail = r.json()["detail"]
    assert detail["code"] == code, detail
    message: str = detail["message"]
    return message


def _frame(mine: ResultsStack, rid: str, t: float) -> dict[str, Any]:
    r = mine.client.get(
        f"/api/v1/scenarios/{mine.sid}/results/{rid}/operations/frame", params={"time": t}
    )
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


# -- A-1 kit ---------------------------------------------------------------------- #


def test_a1_kit_declares_axis_units_and_empty_tables(
    mine: ResultsStack, kit: dict[str, bytes]
) -> None:
    c, sid = mine.client, mine.sid
    r = c.post(f"/api/v1/scenarios/{sid}/export/anylogic")
    assert r.status_code == 200 and r.headers["x-adapter-version"] == "0.2.0"
    files = unzip(r.content)
    root = next(iter(files)).split("/")[0]
    adapter_manifest = json.loads(files[f"{root}/adapter_manifest.json"])
    assert adapter_manifest["details"]["roundTripKit"]["files"] == [
        "roundtrip/result_manifest.json",
        "roundtrip/vehicle_samples.csv",
        "roundtrip/edge_metrics.csv",
        "roundtrip/summary_metrics.csv",
        "roundtrip/README.txt",
    ]
    m = manifest_of(kit)
    assert m["resultDomain"] == "OPERATIONS" and m["sourceApplication"] == "ANYLOGIC"
    assert m["sourceScenarioId"] == sid
    assert m["sourceSnapshot"] == adapter_manifest["sourceSnapshot"]
    assert m["timeAxis"] == {"kind": "ELAPSED_SECONDS"}
    assert m["units"] == {
        "loadTonnes": "t",
        "utilization": "fraction",
        "queueCount": "count",
        "haulageTonnesPerHour": "t/h",
        "travelTimeSeconds": "s",
        "totalHauledTonnes": "t",
        "meanCycleTimeSeconds": "s",
        "meanUtilization": "fraction",
        "simulatedDurationSeconds": "s",
        "vehicleCount": "count",
    }
    assert kit["vehicle_samples.csv"].decode().splitlines() == [
        "time,agentId,agentKind,edgeId,chainageFraction,status,loadTonnes"
    ]
    assert kit["edge_metrics.csv"].decode().splitlines() == [
        "time,edgeId,utilization,queueCount,haulageTonnesPerHour,travelTimeSeconds"
    ]
    assert kit["summary_metrics.csv"].decode().splitlines() == ["metric,value,unit"]
    assert "MINE_DAY" in kit["README.txt"].decode()


# -- A-2 import -------------------------------------------------------------------- #


def test_a2_import_stores_samples_metrics_and_summaries(
    mine: ResultsStack, kit: dict[str, bytes]
) -> None:
    c, sid = mine.client, mine.sid
    r = post_zip(
        c,
        sid,
        "anylogic",
        anylogic_package(
            kit,
            [
                [0, "T2", "TRUCK", "RAMP:L01", 0.0, "EMPTY", 0],
                [0, "T1", "TRUCK", "RAMP:L01", 0.0, "LOADED", 30],
                [100, "T1", "TRUCK", "RAMP:L01", 1.0, "LOADED", 30],
                [200, "T1", "TRUCK", "DRIFT:L01:00", 0.25, "LOADED", None],
                [50, "T2", "TRUCK", "RAMP:L01", 0.5, "EMPTY", 0],
            ],
            edge_rows=[[0, "RAMP:L01", 0.4, 1], [100, "RAMP:L01", 0.9, None]],
            edge_header=["time", "edgeId", "utilization", "queueCount"],
            summary_rows=[
                ["totalHauledTonnes", 3200.0, "t"],
                ["fleetName", 1.0, "?"],
                ["meanUtilization", 0.73, "fraction"],
            ],
        ),
    )
    assert r.status_code == 201, r.text
    res = r.json()["result"]
    assert res["domain"] == "OPERATIONS" and res["compatibility"] == "COMPATIBLE"
    assert res["timeAxis"] == {
        "kind": "ELAPSED_SECONDS",
        "unit": "s",
        "sampleCount": 4,
        "start": 0.0,
        "end": 200.0,
    }
    assert res["counts"] == {
        "edgeCount": 2,
        "timeCount": 4,
        "sampleCount": 5,
        "vehicleCount": 2,
        "edgeMetricSampleCount": 2,
    }
    metrics = {m["name"]: m for m in res["metrics"]}
    assert metrics["utilization"]["available"] and metrics["utilization"]["max"] == 0.9
    assert metrics["queueCount"]["sampleCount"] == 1
    assert metrics["haulageTonnesPerHour"]["available"] is False
    summaries = {s["name"]: s for s in res["summaryMetrics"]}
    assert summaries["totalHauledTonnes"] == {
        "name": "totalHauledTonnes",
        "value": 3200.0,
        "unit": "t",
    }
    assert summaries["meanUtilization"]["value"] == 0.73
    assert "fleetName" not in summaries and any("fleetName" in n for n in res["notes"])
    assert res["provenance"]["importedFileNames"] == [
        "vehicle_samples.csv",
        "edge_metrics.csv",
        "summary_metrics.csv",
    ]
    assert res["signConvention"] is None
    f = _frame(mine, res["resultId"], 0.0)
    assert [v["agentId"] for v in f["vehicles"]] == ["T1", "T2"]  # sorted (time, agentId)
    assert f["vehicles"][0]["loadTonnes"] == 30.0 and f["vehicles"][1]["loadTonnes"] == 0.0
    assert f["edgeMetrics"] == [
        {
            "edgeId": "RAMP:L01",
            "sampleTime": 0.0,
            "utilization": 0.4,
            "queueCount": 1,
            "haulageTonnesPerHour": None,
            "travelTimeSeconds": None,
        }
    ]


# -- A-3 declared time axis ------------------------------------------------------------ #


def test_a3_mine_day_axis_is_declared_never_inferred(
    mine: ResultsStack, kit: dict[str, bytes]
) -> None:
    c, sid = mine.client, mine.sid
    m = manifest_of(kit)
    m["timeAxis"] = {"kind": "MINE_DAY"}
    r = post_zip(
        c,
        sid,
        "anylogic",
        anylogic_package(kit, [[12.5, "L1", "LHD", "RAMP:L02", 0.1, None, None]], manifest=m),
    )
    assert r.status_code == 201, r.text
    res = r.json()["result"]
    assert res["timeAxis"]["kind"] == "MINE_DAY" and res["timeAxis"]["unit"] == "day"
    f = _frame(mine, res["resultId"], 12.5)
    assert f["timeAxisKind"] == "MINE_DAY" and f["vehicles"][0]["agentKind"] == "LHD"
    assert f["vehicles"][0]["status"] is None and f["vehicles"][0]["loadTonnes"] is None
    m["timeAxis"] = {"kind": "STATIC"}
    msg = _error(
        post_zip(
            c,
            sid,
            "anylogic",
            anylogic_package(kit, [[0, "L1", "LHD", "RAMP:L02", 0.1, None, None]], manifest=m),
        ),
        "RESULT_DATA_INVALID",
        422,
    )
    assert "declared, never inferred" in msg


# -- A-4 … A-6 vehicle validation ------------------------------------------------------- #


def test_a4_a5_a6_vehicle_sample_refusals(mine: ResultsStack, kit: dict[str, bytes]) -> None:
    c, sid = mine.client, mine.sid
    _error(
        post_zip(
            c,
            sid,
            "anylogic",
            anylogic_package(
                kit, [[0, "T1", "RAMP:L01"]], vehicle_header=["time", "agentId", "edgeId"]
            ),
        ),
        "RESULT_PACKAGE_INVALID",
        422,
    )
    _error(
        post_zip(
            c,
            sid,
            "anylogic",
            anylogic_package(
                kit,
                [[0, "T1", "RAMP:L01", 0.5, "x"]],
                vehicle_header=["time", "agentId", "edgeId", "chainageFraction", "speed"],
            ),
        ),
        "RESULT_PACKAGE_INVALID",
        422,
    )
    for chain in (1.5, -0.1, "NaN", ""):
        msg = _error(
            post_zip(
                c,
                sid,
                "anylogic",
                anylogic_package(kit, [[0, "T1", "TRUCK", "RAMP:L01", chain, "", 1]]),
            ),
            "RESULT_DATA_INVALID",
            422,
        )
        assert "chainageFraction" in msg or "NaN" in msg
    _error(
        post_zip(
            c, sid, "anylogic", anylogic_package(kit, [[0, "T1", "TRUCK", "RAMP:L01", 0.5, "", -1]])
        ),
        "RESULT_DATA_INVALID",
        422,
    )
    _error(
        post_zip(
            c, sid, "anylogic", anylogic_package(kit, [[-1, "T1", "TRUCK", "RAMP:L01", 0.5, "", 1]])
        ),
        "RESULT_DATA_INVALID",
        422,
    )
    _error(
        post_zip(
            c, sid, "anylogic", anylogic_package(kit, [[0, "", "TRUCK", "RAMP:L01", 0.5, "", 1]])
        ),
        "RESULT_DATA_INVALID",
        422,
    )
    _error(
        post_zip(
            c, sid, "anylogic", anylogic_package(kit, [[0, "T1", "TRUCK", "RAMP:L99", 0.5, "", 1]])
        ),
        "RESULT_IDENTITY_UNRESOLVED",
        409,
    )
    msg = _error(
        post_zip(
            c,
            sid,
            "anylogic",
            anylogic_package(
                kit,
                [
                    [0, "T1", "TRUCK", "RAMP:L01", 0.5, "", 1],
                    [0, "T1", "TRUCK", "RAMP:L02", 0.5, "", 1],
                ],
            ),
        ),
        "RESULT_IDENTITY_AMBIGUOUS",
        409,
    )
    assert "two samples at time" in msg
    msg = _error(
        post_zip(
            c,
            sid,
            "anylogic",
            anylogic_package(
                kit,
                [
                    [0, "T1", "TRUCK", "RAMP:L01", 0.5, "", 1],
                    [1, "T1", "LHD", "RAMP:L01", 0.6, "", 1],
                ],
            ),
        ),
        "RESULT_DATA_INVALID",
        422,
    )
    assert "changes agentKind" in msg
    _error(
        post_zip(c, sid, "anylogic", anylogic_package(kit, [])),
        "RESULT_DATA_INVALID",
        422,
    )


# -- A-7 / A-10 frames and projection ------------------------------------------------------ #


def test_a7_a10_same_edge_interpolation_on_the_source_centerline(
    mine: ResultsStack, kit: dict[str, bytes]
) -> None:
    c, sid = mine.client, mine.sid
    r = post_zip(
        c,
        sid,
        "anylogic",
        anylogic_package(
            kit,
            [
                [10, "H1", "TRUCK", "RAMP:L01", 0.2, "UP", 5],
                [20, "H1", "TRUCK", "RAMP:L01", 0.6, "UP", 5],
                [30, "H1", "TRUCK", "RAMP:L02", 0.1, "UP", 5],
                [40, "H1", "TRUCK", "RAMP:L02", 0.3, "UP", 5],
            ],
        ),
    )
    assert r.status_code == 201, r.text
    rid = r.json()["result"]["resultId"]
    geometry = c.get(f"/api/v1/scenarios/{sid}/results/{rid}/geometry").json()
    assert geometry["coordinateFrame"] == "LOCAL_ENU_Z_UP"
    edges = {e["edgeId"]: e for e in geometry["edges"]}
    assert sorted(edges) == sorted(e["edgeId"] for e in geometry["edges"])
    ramp = np.asarray(edges["RAMP:L01"]["points"], dtype=np.float64)
    assert ramp.shape[1] == 3 and ramp.shape[0] >= 2
    v = _frame(mine, rid, 15.0)["vehicles"][0]
    assert v["placement"] == "INTERPOLATED" and abs(v["chainageFraction"] - 0.4) < 1e-12
    assert np.allclose([v["x"], v["y"], v["z"]], chainage_to_xyz(ramp, 0.4))
    v = _frame(mine, rid, 20.0)["vehicles"][0]
    assert v["placement"] == "SAMPLE" and np.allclose(
        [v["x"], v["y"], v["z"]], chainage_to_xyz(ramp, 0.6)
    )
    v = _frame(mine, rid, 25.0)["vehicles"][0]  # edge change ahead: previous sample HELD
    assert v["placement"] == "SAMPLE" and v["edgeId"] == "RAMP:L01" and v["chainageFraction"] == 0.6
    v = _frame(mine, rid, 35.0)["vehicles"][0]
    assert v["placement"] == "INTERPOLATED" and v["edgeId"] == "RAMP:L02"
    assert abs(v["chainageFraction"] - 0.2) < 1e-12
    assert _frame(mine, rid, 9.9)["vehicles"] == [] and _frame(mine, rid, 40.1)["vehicles"] == []
    # geometry endpoints = network node positions (chainage axis: sourceNode → targetNode)
    net = c.get(f"/api/v1/scenarios/{sid}/network").json()
    pos = {n["id"]: n["position"] for n in net["nodes"]}
    for eid, e in edges.items():
        assert np.allclose(e["points"][0], pos[e["sourceNodeId"]], atol=1e-6), eid
        assert np.allclose(e["points"][-1], pos[e["targetNodeId"]], atol=1e-6), eid


# -- A-8 edge metrics ------------------------------------------------------------------- #


def test_a8_edge_metrics_bounds_and_hold_last(mine: ResultsStack, kit: dict[str, bytes]) -> None:
    c, sid = mine.client, mine.sid
    veh = [[0, "T1", "TRUCK", "RAMP:L01", 0.0, "", 1]]
    for rows, header, match in (
        ([[0, "RAMP:L01", 1.5, 0]], None, "utilization"),
        ([[0, "RAMP:L01", 0.5, -1]], None, "queueCount"),
        ([[0, "RAMP:L01", 0.5, 1.5]], None, "queueCount"),
        (
            [[0, "RAMP:L01", -1.0]],
            ["time", "edgeId", "haulageTonnesPerHour"],
            "haulageTonnesPerHour",
        ),
        ([[0, "RAMP:L01", -1.0]], ["time", "edgeId", "travelTimeSeconds"], "travelTimeSeconds"),
        ([[0, "RAMP:L01", 0.5, 1], [0, "RAMP:L01", 0.6, 1]], None, "duplicate"),
        ([[0, "RAMP:L01", None, None]], None, "no metric value"),
    ):
        msg = _error(
            post_zip(
                c, sid, "anylogic", anylogic_package(kit, veh, edge_rows=rows, edge_header=header)
            ),
            "RESULT_DATA_INVALID",
            422,
        )
        assert match in msg, msg
    _error(
        post_zip(
            c,
            sid,
            "anylogic",
            anylogic_package(
                kit, veh, edge_rows=[[0, "RAMP:L01", 1]], edge_header=["time", "edgeId", "speedKmh"]
            ),
        ),
        "RESULT_PACKAGE_INVALID",
        422,
    )
    _error(
        post_zip(
            c, sid, "anylogic", anylogic_package(kit, veh, edge_rows=[[0, "RAMP:L99", 0.5, 1]])
        ),
        "RESULT_IDENTITY_UNRESOLVED",
        409,
    )
    r = post_zip(
        c,
        sid,
        "anylogic",
        anylogic_package(
            kit,
            [*veh, [300, "T1", "TRUCK", "RAMP:L01", 1.0, "", 1]],
            edge_rows=[
                [0, "RAMP:L01", 0.1, 0],
                [100, "RAMP:L02", 0.2, 3],
                [200, "RAMP:L01", 0.3, None],
            ],
        ),
    )
    assert r.status_code == 201, r.text
    rid = r.json()["result"]["resultId"]
    assert [(m["edgeId"], m["sampleTime"]) for m in _frame(mine, rid, 150.0)["edgeMetrics"]] == [
        ("RAMP:L01", 0.0),
        ("RAMP:L02", 100.0),
    ]
    late = {m["edgeId"]: m for m in _frame(mine, rid, 500.0)["edgeMetrics"]}
    assert late["RAMP:L01"]["utilization"] == 0.3 and late["RAMP:L01"]["queueCount"] is None
    assert late["RAMP:L02"]["queueCount"] == 3
    assert _frame(mine, rid, -1.0)["edgeMetrics"] == []


# -- A-9 / A-11 units and summaries --------------------------------------------------- #


def test_a9_a11_units_and_summary_metrics(mine: ResultsStack, kit: dict[str, bytes]) -> None:
    c, sid = mine.client, mine.sid
    veh = [[0, "T1", "TRUCK", "RAMP:L01", 0.0, "", 1]]
    m = manifest_of(kit)
    m["units"]["loadTonnes"] = "kg"
    msg = _error(
        post_zip(c, sid, "anylogic", anylogic_package(kit, veh, manifest=m)),
        "RESULT_UNIT_UNSUPPORTED",
        422,
    )
    assert "loadTonnes" in msg
    m = manifest_of(kit)
    m["units"]["utilization"] = "percent"
    _error(
        post_zip(
            c,
            sid,
            "anylogic",
            anylogic_package(kit, veh, edge_rows=[[0, "RAMP:L01", 50, 0]], manifest=m),
        ),
        "RESULT_UNIT_UNSUPPORTED",
        422,
    )
    m = manifest_of(kit)
    del m["units"]["queueCount"]
    _error(
        post_zip(
            c,
            sid,
            "anylogic",
            anylogic_package(kit, veh, edge_rows=[[0, "RAMP:L01", 0.5, 0]], manifest=m),
        ),
        "RESULT_UNIT_UNSUPPORTED",
        422,
    )
    for rows, match in (
        ([["totalHauledTonnes", "inf", "t"]], "inf"),
        ([["totalHauledTonnes", 1.0, "kg"]], "totalHauledTonnes"),
        ([["totalHauledTonnes", 1.0, "t"], ["totalHauledTonnes", 2.0, "t"]], "repeated"),
        ([["", 1.0, "t"]], "metric"),
    ):
        msg = _error(
            post_zip(c, sid, "anylogic", anylogic_package(kit, veh, summary_rows=rows)),
            "RESULT_DATA_INVALID",
            422,
        )
        assert match in msg, msg


# -- B1 (PR #51 review): loadTonnes is never inferred as tonnes ------------------- #


def test_b1_load_tonnes_value_requires_an_explicit_unit_declaration(
    mine: ResultsStack, kit: dict[str, bytes]
) -> None:
    """A delivered loadTonnes VALUE without ``units.loadTonnes`` is refused
    (RESULT_UNIT_UNSUPPORTED, 422) — explicit units only, never inferred; the
    column with blank cells and no declaration carries no value and imports."""
    c, sid = mine.client, mine.sid
    m = manifest_of(kit)
    assert m["units"].get("loadTonnes") == "t"  # the kit declares it
    del m["units"]["loadTonnes"]
    veh = [[0, "T1", "TRUCK", "RAMP:L01", 0.0, "", 3000]]
    msg = _error(
        post_zip(c, sid, "anylogic", anylogic_package(kit, veh, manifest=m)),
        "RESULT_UNIT_UNSUPPORTED",
        422,
    )
    assert "loadTonnes" in msg and "no declared unit" in msg
    # the same package with the unit declared imports (identity differs from every
    # other test package through the value); blank cells need no declaration
    r = post_zip(c, sid, "anylogic", anylogic_package(kit, veh))
    assert r.status_code in (200, 201), r.text
    blank = [
        [0, "T1", "TRUCK", "RAMP:L01", 0.0, "", ""],
        [5, "T1", "TRUCK", "RAMP:L01", 0.5, "", ""],
    ]
    r = post_zip(c, sid, "anylogic", anylogic_package(kit, blank, manifest=m))
    assert r.status_code in (200, 201), r.text
    assert all(
        v["loadTonnes"] is None for v in _frame(mine, r.json()["result"]["resultId"], 0)["vehicles"]
    )
