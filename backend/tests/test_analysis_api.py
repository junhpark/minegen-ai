"""Phase 22A/B — ``GET …/analysis`` and ``…/analysis/economics-config`` over
REAL layout-v2 chains (levels → production → network → timeline) for the
three implemented methods (directive §60–64 API cases: A-5, A-6, A-9, A-10,
A-11, A-12, B-1…B-5, cross-method acceptance).

Module-scoped stacks (minutes): registered ``e2e`` in ``conftest``."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import minegen.services.analysis_service as analysis_service_module
from minegen.core.artifacts import NETWORK_ARTIFACT, STOPES_ARTIFACT, TIMELINE_ARTIFACT
from tests import analysis_support as fx
from tests.test_exchange_bundle import TabularStack
from tests.test_exchange_mining_method import _post
from tests.test_exchange_production_methods import _method_stack
from tests.test_world_api import _create

ANALYSIS = "/analysis"
CONFIG = "/analysis/economics-config"


def _full_stack(root: Path, method: str, params: dict[str, Any] | None = None) -> TabularStack:
    stack = _method_stack(root, method, params)
    c = stack.client
    _post(c, f"/api/v1/scenarios/{stack.sid}/network/generate")
    tl = _post(c, f"/api/v1/scenarios/{stack.sid}/design/timeline")
    assert tl["status"] == "SUCCESS", tl.get("failureReason")
    return stack


@pytest.fixture(scope="module")
def longhole(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TabularStack]:
    stack = _full_stack(tmp_path_factory.mktemp("analysis-longhole"), "LONGHOLE_OPEN_STOPING")
    yield stack
    stack.close()


@pytest.fixture(scope="module")
def cut_fill(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TabularStack]:
    stack = _full_stack(tmp_path_factory.mktemp("analysis-cut-fill"), "CUT_AND_FILL")
    yield stack
    stack.close()


@pytest.fixture(scope="module")
def room_pillar(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TabularStack]:
    stack = _full_stack(
        tmp_path_factory.mktemp("analysis-room-pillar"),
        "ROOM_AND_PILLAR",
        {"kind": "ROOM_AND_PILLAR", "roomWidthM": 12.0, "pillarWidthM": 8.0, "benchCount": 1},
    )
    yield stack
    stack.close()


def _analysis(stack: TabularStack) -> dict[str, Any]:
    r = stack.client.get(f"/api/v1/scenarios/{stack.sid}{ANALYSIS}")
    assert r.status_code == 200, r.text
    doc: dict[str, Any] = r.json()
    return doc


def _refused(stack: TabularStack, code: str) -> str:
    r = stack.client.get(f"/api/v1/scenarios/{stack.sid}{ANALYSIS}")
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == code, r.text
    return str(r.json()["detail"]["message"])


def _file_state(derived: Path) -> dict[str, tuple[int, int, str]]:
    return {
        p.name: (p.stat().st_size, p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
        for p in sorted(derived.iterdir())
        if p.is_file()
    }


def _put_config(stack: TabularStack, doc: dict[str, Any]) -> dict[str, Any]:
    r = stack.client.put(f"/api/v1/scenarios/{stack.sid}{CONFIG}", json=doc)
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


# --------------------------------------------------------------------------- #
# partial analysis (A-9) and the config document (B-1…B-5)
# --------------------------------------------------------------------------- #


def test_a9_fresh_scenario_is_a_partial_analysis_never_a_refusal(client: TestClient) -> None:
    sid = _create(client)
    r = client.get(f"/api/v1/scenarios/{sid}{ANALYSIS}")
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["status"] == "SUCCESS"
    for key in ("development", "production", "schedule", "ratios"):
        assert doc[key]["availability"] == "NOT_AVAILABLE", key
    assert doc["development"]["reason"].startswith("world not generated")
    assert doc["economics"]["availability"] == "NOT_CONFIGURED"
    assert doc["sources"]["networkRevision"] is None
    assert doc["sources"]["economicsRevision"] is None
    # a world alone: derived sections still honestly absent
    assert client.post(f"/api/v1/scenarios/{sid}/world/generate").status_code == 200
    doc = client.get(f"/api/v1/scenarios/{sid}{ANALYSIS}").json()
    assert doc["development"]["reason"] == "network.json not generated"
    assert doc["production"]["reason"] == "stopes.json not generated"
    assert doc["schedule"]["reason"] == "timeline.json not generated"
    # unknown scenario: 404, not 500
    r = client.get(f"/api/v1/scenarios/NOPE{ANALYSIS}")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "SCENARIO_NOT_FOUND"
    r = client.get(f"/api/v1/scenarios/NOPE{CONFIG}")
    assert r.status_code == 404


def test_b1_b4_economics_config_roundtrip_revision_and_validation(client: TestClient) -> None:
    sid = _create(client)
    r = client.get(f"/api/v1/scenarios/{sid}{CONFIG}")
    assert r.status_code == 200
    assert r.json() == {"configured": False, "revision": None, "config": None}
    doc = fx.config_doc()
    r = client.put(f"/api/v1/scenarios/{sid}{CONFIG}", json=doc)
    assert r.status_code == 200, r.text
    put = r.json()
    assert put["configured"] is True and len(put["revision"]) == 64
    assert put["config"] == doc
    got = client.get(f"/api/v1/scenarios/{sid}{CONFIG}").json()
    assert got == put  # B-1 roundtrip
    # B-2: the same content → the same revision (no timestamp); a change → another
    again = client.put(f"/api/v1/scenarios/{sid}{CONFIG}", json=doc).json()
    assert again["revision"] == put["revision"]
    changed = dict(doc, grossRevenuePerMinedTonne=6.0)
    other = client.put(f"/api/v1/scenarios/{sid}{CONFIG}", json=changed).json()
    assert other["revision"] != put["revision"]
    # the analysis reports the config revision as a source
    analysis = client.get(f"/api/v1/scenarios/{sid}{ANALYSIS}").json()
    assert analysis["sources"]["economicsRevision"] == other["revision"]
    assert analysis["economics"]["availability"] == "NOT_AVAILABLE"  # sources missing
    assert analysis["economics"]["currencyCode"] == "USD"
    # B-3 / B-4: typed 422 at the boundary, the stored document untouched
    for bad in (
        dict(doc, currencyCode="usd"),
        dict(doc, currencyCode="US"),
        dict(doc, processingCostPerTonne=-1.0),
        dict(doc, cashflowBucketDays=0),
        dict(doc, metalPrice=1500.0),
    ):
        r = client.put(f"/api/v1/scenarios/{sid}{CONFIG}", json=bad)
        assert r.status_code == 422, r.text
    raw = json.dumps(dict(doc, initialCapitalCost="NaN"))
    r = client.put(
        f"/api/v1/scenarios/{sid}{CONFIG}",
        content=raw.replace('"NaN"', "NaN"),
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 422, r.text
    assert client.get(f"/api/v1/scenarios/{sid}{CONFIG}").json() == other
    # the document lives beside scenario.json, never under derived/
    store = client.app.dependency_overrides  # type: ignore[attr-defined]
    assert store  # the fixture wires the store; the path contract is checked on the stack below


def test_economics_json_lives_beside_the_scenario_and_malformed_is_typed(
    longhole: TabularStack,
) -> None:
    put = _put_config(longhole, fx.config_doc())
    path = longhole.store.scenario_dir(longhole.sid) / "economics.json"
    assert path.exists() and not (longhole.derived / "economics.json").exists()
    assert json.loads(path.read_text()) == fx.config_doc()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == put["revision"]
    original = path.read_bytes()
    try:
        path.write_text("{not json")
        _refused(longhole, "ARTIFACT_MALFORMED")
        r = longhole.client.get(f"/api/v1/scenarios/{longhole.sid}{CONFIG}")
        assert r.status_code == 409 and r.json()["detail"]["code"] == "ARTIFACT_MALFORMED"
        path.write_text(json.dumps(dict(fx.config_doc(), currencyCode="x")))
        _refused(longhole, "ARTIFACT_MALFORMED")
    finally:
        path.write_bytes(original)
    assert _analysis(longhole)["economics"]["availability"] == "AVAILABLE"


def test_b5_put_config_leaves_every_mine_artifact_untouched(longhole: TabularStack) -> None:
    before = _file_state(longhole.derived)
    scenario_before = _file_state(longhole.store.scenario_dir(longhole.sid))
    _put_config(longhole, dict(fx.config_doc(), initialCapitalCost=999.0))
    _put_config(longhole, fx.config_doc())
    after = _file_state(longhole.derived)
    assert after == before  # sizes, mtimes AND content hashes of every derived file
    scenario_after = _file_state(longhole.store.scenario_dir(longhole.sid))
    changed = {
        k
        for k in scenario_before | scenario_after
        if scenario_before.get(k) != scenario_after.get(k)
    }
    assert changed == {"economics.json"}
    for name in (NETWORK_ARTIFACT, STOPES_ARTIFACT, TIMELINE_ARTIFACT):
        assert (longhole.derived / name).exists()
    # the scene still serves every artifact (no invalidation happened)
    scene = longhole.client.get(f"/api/v1/scenarios/{longhole.sid}/scene").json()
    assert scene["network"]["status"] == "SUCCESS" and scene["timeline"]["status"] == "SUCCESS"


# --------------------------------------------------------------------------- #
# real chains: Longhole / Cut & Fill / Room & Pillar (A-4…A-6, A-8, cross-method)
# --------------------------------------------------------------------------- #


def _check_common(stack: TabularStack, doc: dict[str, Any], method: str) -> None:
    network = stack.artifact(NETWORK_ARTIFACT)
    dev = doc["development"]
    assert dev["availability"] == "AVAILABLE"
    m = network["metrics"]
    t = dev["totals"]
    assert math.isclose(t["rampLengthM"], m["totalRampLength3d"])
    assert math.isclose(t["levelAccessLengthM"], m["totalLevelAccessLength3d"])
    assert math.isclose(t["driftLengthM"], m["totalDriftLength3d"])
    assert math.isclose(t["crosscutLengthM"], m["totalCrosscutLength3d"])
    edges = network["edges"]
    assert math.isclose(t["totalDevelopmentLengthM"], sum(e["length3d"] for e in edges))
    assert math.isclose(
        t["grossDevelopmentVolumeM3"],
        sum(e["length3d"] * e["crossSection"]["analyticArea"] for e in edges),
    )
    assert sum(c["edgeCount"] for c in dev["categories"]) == len(edges) == m["edgeCount"]
    prod = doc["production"]
    assert prod["availability"] == "AVAILABLE" and prod["method"] == method
    assert prod["totalPlannedMinedTonnes"] > 0 and prod["totalProductionVolumeM3"] > 0
    sched = doc["schedule"]
    timeline = stack.artifact(TIMELINE_ARTIFACT)
    assert sched["availability"] == "AVAILABLE"
    assert sched["taskCount"] == len(timeline["tasks"]) == timeline["metrics"]["taskCount"]
    assert sched["endDay"] == timeline["endDay"]
    assert sched["mineDurationDays"] == timeline["endDay"] - timeline["startDay"]
    assert sched["rampCompletionDay"] == timeline["metrics"]["rampCompletionDay"]
    assert sched["firstProductionDay"] == timeline["metrics"]["firstStopingDay"]
    ratios = doc["ratios"]
    assert math.isclose(
        ratios["developmentMetresPerKt"],
        t["totalDevelopmentLengthM"] / (prod["totalPlannedMinedTonnes"] / 1000.0),
    )
    assert doc["sources"]["networkRevision"] and doc["sources"]["timelineRevision"]


def _check_economics(doc: dict[str, Any], rate_per_tonne: float) -> None:
    e = doc["economics"]
    assert e["availability"] == "AVAILABLE", e["reason"]
    s = e["summary"]
    tonnes = doc["production"]["totalPlannedMinedTonnes"]
    assert math.isclose(s["productionMiningCost"], tonnes * rate_per_tonne)
    assert math.isclose(s["processingCost"], tonnes * fx.config_doc()["processingCostPerTonne"])
    assert math.isclose(s["totalRevenue"], tonnes * fx.config_doc()["grossRevenuePerMinedTonne"])
    assert math.isclose(
        s["fixedOperatingCost"],
        doc["schedule"]["mineDurationDays"] * fx.config_doc()["fixedOperatingCostPerDay"],
    )
    total = (
        s["developmentCost"]
        + s["productionMiningCost"]
        + s["processingCost"]
        + s["backfillCost"]
        + s["fixedOperatingCost"]
        + s["initialCapitalCost"]
    )
    assert math.isclose(s["totalCost"], total)
    assert math.isclose(s["undiscountedNetCashflow"], s["totalRevenue"] - s["totalCost"])
    buckets = e["cashflow"]
    assert [b["index"] for b in buckets] == list(range(len(buckets)))
    assert buckets[-1]["endDay"] >= doc["schedule"]["endDay"]
    for col, key in (
        ("developmentCost", "developmentCost"),
        ("productionMiningCost", "productionMiningCost"),
        ("processingCost", "processingCost"),
        ("backfillCost", "backfillCost"),
        ("fixedOperatingCost", "fixedOperatingCost"),
        ("initialCapitalCost", "initialCapitalCost"),
        ("revenue", "totalRevenue"),
    ):
        assert math.isclose(sum(b[col] for b in buckets), s[key], abs_tol=1e-6), col
    assert math.isclose(
        buckets[-1]["cumulativeCashflow"], s["undiscountedNetCashflow"], abs_tol=1e-6
    )
    assert buckets[0]["initialCapitalCost"] == s["initialCapitalCost"]
    assert math.isclose(sum(b["discountedNetCashflow"] for b in buckets), s["npv"], abs_tol=1e-6)


def test_longhole_chain_analysis_and_economics(longhole: TabularStack) -> None:
    _put_config(longhole, fx.config_doc())
    doc = _analysis(longhole)
    _check_common(longhole, doc, "LONGHOLE_OPEN_STOPING")
    stopes = longhole.artifact(STOPES_ARTIFACT)
    prod = doc["production"]
    assert prod["productionObjectCount"] == len(stopes["stopes"]) == prod["detail"]["stopeCount"]
    assert math.isclose(prod["totalPlannedMinedTonnes"], sum(s["tonnes"] for s in stopes["stopes"]))
    assert prod["detail"]["kind"] == "LONGHOLE_OPEN_STOPING"
    _check_economics(doc, 2.0)
    assert doc["economics"]["summary"]["backfillCost"] == 0.0  # Longhole: no backfill cost


def test_a5_cut_fill_chain_backfill_is_separate(cut_fill: TabularStack) -> None:
    _put_config(cut_fill, fx.config_doc())
    doc = _analysis(cut_fill)
    _check_common(cut_fill, doc, "CUT_AND_FILL")
    payload = cut_fill.artifact(STOPES_ARTIFACT)
    prod = doc["production"]
    d = prod["detail"]
    assert d["kind"] == "CUT_AND_FILL"
    assert prod["productionObjectCount"] == len(payload["cuts"]) == d["cutCount"]
    assert d["liftCount"] == len(payload["lifts"]) and d["backfillCount"] == len(
        payload["backfills"]
    )
    backfill = sum(b["volumeM3"] for b in payload["backfills"])
    assert math.isclose(d["totalBackfillVolumeM3"], backfill)
    assert math.isclose(
        prod["totalProductionVolumeM3"], sum(c["geometricVolumeM3"] for c in payload["cuts"])
    )
    _check_economics(doc, 3.0)
    assert math.isclose(doc["economics"]["summary"]["backfillCost"], backfill * 0.5)


def test_a6_room_pillar_chain_excludes_retained_pillars(room_pillar: TabularStack) -> None:
    _put_config(room_pillar, fx.config_doc())
    doc = _analysis(room_pillar)
    _check_common(room_pillar, doc, "ROOM_AND_PILLAR")
    payload = room_pillar.artifact(STOPES_ARTIFACT)
    prod = doc["production"]
    d = prod["detail"]
    assert d["kind"] == "ROOM_AND_PILLAR"
    assert (
        prod["productionObjectCount"] == len(payload["extractionUnits"]) == d["extractionUnitCount"]
    )
    assert d["roomCount"] == len(payload["rooms"]) and d["pillarCount"] == len(payload["pillars"])
    assert d["headingCount"] + d["benchCount"] == d["extractionUnitCount"]
    mined = sum(u["tonnes"] for u in payload["extractionUnits"])
    assert math.isclose(prod["totalPlannedMinedTonnes"], mined)
    assert math.isclose(
        d["retainedPillarVolumeM3"], sum(p["geometricVolumeM3"] for p in payload["pillars"])
    )
    assert math.isclose(
        d["retainedPillarTonnesEquivalent"], sum(p["tonnesEquivalent"] for p in payload["pillars"])
    )
    assert d["retainedPillarVolumeM3"] > 0  # retained, reported separately, never mined
    _check_economics(doc, 4.0)
    assert doc["economics"]["summary"]["backfillCost"] == 0.0


# --------------------------------------------------------------------------- #
# determinism, read-only, corruption, snapshot race (A-10…A-12)
# --------------------------------------------------------------------------- #


def test_a11_analysis_is_deterministic_and_read_only(cut_fill: TabularStack) -> None:
    before = _file_state(cut_fill.derived)
    a = cut_fill.client.get(f"/api/v1/scenarios/{cut_fill.sid}{ANALYSIS}").text
    b = cut_fill.client.get(f"/api/v1/scenarios/{cut_fill.sid}{ANALYSIS}").text
    assert a == b
    assert _file_state(cut_fill.derived) == before
    assert not (cut_fill.derived / "analysis.json").exists()
    assert not (cut_fill.derived / "economics.json").exists()


def test_a10_corrupt_sources_are_typed_409_never_500(room_pillar: TabularStack) -> None:
    net_path = room_pillar.derived / NETWORK_ARTIFACT
    original = net_path.read_bytes()
    try:
        doc = json.loads(original)
        doc["metrics"]["totalDriftLength3d"] += 1.0
        net_path.write_text(json.dumps(doc))
        msg = _refused(room_pillar, "ANALYSIS_SOURCE_INCONSISTENT")
        assert "totalDriftLength3d" in msg
        net_path.write_text("{")
        _refused(room_pillar, "ARTIFACT_MALFORMED")
    finally:
        net_path.write_bytes(original)
    tl_path = room_pillar.derived / TIMELINE_ARTIFACT
    original = tl_path.read_bytes()
    try:
        doc = json.loads(original)
        stoping = next(t for t in doc["tasks"] if t["taskType"] == "STOPING")
        stoping["basis"]["quantity"] *= 1.5
        tl_path.write_text(json.dumps(doc))
        msg = _refused(room_pillar, "ANALYSIS_SOURCE_INCONSISTENT")
        assert "production tonnes" in msg
    finally:
        tl_path.write_bytes(original)
    st_path = room_pillar.derived / STOPES_ARTIFACT
    original = st_path.read_bytes()
    try:
        doc = json.loads(original)
        doc["extractionUnits"][0]["id"] = doc["extractionUnits"][1]["id"]
        st_path.write_text(json.dumps(doc))
        _refused(room_pillar, "ANALYSIS_SOURCE_INCONSISTENT")
    finally:
        st_path.write_bytes(original)
    assert _analysis(room_pillar)["production"]["availability"] == "AVAILABLE"


def test_a12_snapshot_race_is_read_snapshot_changed(
    longhole: TabularStack, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = analysis_service_module.build_analysis
    path = longhole.store.scenario_dir(longhole.sid) / "economics.json"
    tick = {"n": 0}

    def racing(inputs: Any) -> Any:
        out = real(inputs)
        if tick["n"] == 0:
            tick["n"] += 1
            # the assumptions move while the projection runs
            path.write_text(json.dumps(dict(fx.config_doc(), initialCapitalCost=1.0)))
        return out

    monkeypatch.setattr(analysis_service_module, "build_analysis", racing)
    _refused(longhole, "READ_SNAPSHOT_CHANGED")
    monkeypatch.setattr(analysis_service_module, "build_analysis", real)
    _put_config(longhole, fx.config_doc())
    assert _analysis(longhole)["economics"]["availability"] == "AVAILABLE"


def test_cross_method_one_config_three_methods(
    longhole: TabularStack, cut_fill: TabularStack, room_pillar: TabularStack
) -> None:
    rates = {"LONGHOLE_OPEN_STOPING": 2.0, "CUT_AND_FILL": 3.0, "ROOM_AND_PILLAR": 4.0}
    for stack, method in (
        (longhole, "LONGHOLE_OPEN_STOPING"),
        (cut_fill, "CUT_AND_FILL"),
        (room_pillar, "ROOM_AND_PILLAR"),
    ):
        _put_config(stack, fx.config_doc())
        doc = _analysis(stack)
        assert doc["production"]["method"] == method
        _check_economics(doc, rates[method])
        assert doc["economics"]["disclaimer"] == (
            "Synthetic planning economics. Not a resource/reserve estimate or feasibility study."
        )
