"""Phase 23C over the REAL layout-v2 Longhole chain (e2e): the Ventsim and
AnyLogic kits of a LAYOUT_V2-active mine (ramp junctions, level accesses,
drifts, crosscuts) import, overlay and go STALE on a downstream regeneration
exactly as on the LEGACY chain."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from minegen.api.deps import get_result_service
from minegen.services.result_service import ResultService
from tests.results_support import (
    anylogic_package,
    export_kit,
    manifest_of,
    post_zip,
    ventsim_package,
)
from tests.test_adapters_e2e import _longhole_chain
from tests.test_exchange_bundle import TabularStack


@pytest.fixture(scope="module")
def longhole(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TabularStack]:
    stack = _longhole_chain(tmp_path_factory.mktemp("results-longhole"))
    yield stack
    stack.close()


def test_layout_v2_results_round_trip(longhole: TabularStack) -> None:
    c, sid = longhole.client, longhole.sid
    assert get_result_service in c.app.dependency_overrides  # type: ignore[attr-defined]
    assert isinstance(c.app.dependency_overrides[get_result_service](), ResultService)  # type: ignore[attr-defined]
    kit = export_kit(c, sid, "ventsim")
    m = manifest_of(kit)
    assert m["sourceSnapshot"]["activeRampSource"] == "LAYOUT_V2"
    airways = kit["airway_results.csv"].decode().splitlines()[1:]
    ids = [line.split(",")[0] for line in airways]
    assert any(i.startswith("LEVEL_ACCESS:") for i in ids)
    assert any(i.startswith("RAMP:") for i in ids) and any(i.startswith("CROSSCUT:") for i in ids)
    access = next(i for i in ids if i.startswith("LEVEL_ACCESS:"))
    ramp = next(i for i in ids if i.startswith("RAMP:"))
    r = post_zip(
        c,
        sid,
        "ventsim",
        ventsim_package(kit, [[ramp, None, 40.0, None], [access, None, 12.0, 80.0]]),
    )
    assert r.status_code == 201, r.text
    vid = r.json()["result"]["resultId"]
    assert r.json()["result"]["counts"]["edgeCount"] == 2
    frame = c.get(
        f"/api/v1/scenarios/{sid}/results/{vid}/ventilation", params={"metric": "airflowM3s"}
    ).json()
    assert {v["edgeId"]: v["value"] for v in frame["values"]} == {ramp: 40.0, access: 12.0}
    geometry = c.get(f"/api/v1/scenarios/{sid}/results/{vid}/geometry").json()
    assert {e["edgeId"] for e in geometry["edges"]} == set(ids)
    akit = export_kit(c, sid, "anylogic")
    r = post_zip(
        c,
        sid,
        "anylogic",
        anylogic_package(
            akit,
            [
                [0, "T1", "TRUCK", ramp, 0.0, "HAUL", 40],
                [30, "T1", "TRUCK", ramp, 1.0, "HAUL", 40],
                [60, "T1", "TRUCK", access, 0.5, "HAUL", 40],
            ],
            edge_rows=[[0, access, 0.5, 0]],
        ),
    )
    assert r.status_code == 201, r.text
    oid = r.json()["result"]["resultId"]
    f = c.get(f"/api/v1/scenarios/{sid}/results/{oid}/operations/frame", params={"time": 15}).json()
    assert f["vehicles"][0]["placement"] == "INTERPOLATED" and f["vehicles"][0]["edgeId"] == ramp
    # regenerating the timeline (a snapshot input) makes both results STALE and keeps them
    r = c.post(f"/api/v1/scenarios/{sid}/design/timeline")
    assert r.status_code == 200 and r.json()["status"] == "SUCCESS"
    listed = {
        x["resultId"]: x["compatibility"]
        for x in c.get(f"/api/v1/scenarios/{sid}/results").json()["results"]
    }
    assert listed == {vid: "STALE", oid: "STALE"}
    r = c.get(f"/api/v1/scenarios/{sid}/results/{oid}/operations/frame", params={"time": 15})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "RESULT_STALE"
