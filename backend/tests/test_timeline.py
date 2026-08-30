"""Phase 10 timeline tests (rules 81–86): prerequisite gates, deterministic
DAG, physical-access precedence, stope chains, exact state semantics,
chainage contract, default acceptance counts."""

from __future__ import annotations

import json
from itertools import pairwise

import numpy as np
import pytest

from minegen.core.enums import ObjectState, TaskType
from minegen.design.constraints import DesignContext
from minegen.design.cost_field import DesignCostEvaluator
from minegen.mining.methods.longhole import LongholeOpenStopingStrategy
from minegen.network.builder import MineNetworkBuilder
from minegen.scheduling.builder import MineTimelineBuilder, solve_earliest_start
from minegen.scheduling.models import state_at
from tests.test_levels import _entry_segment, _setup, _smoothed


def _chain(tmp_path, entry_us_zs):  # type: ignore[no-untyped-def]
    """Full synthetic Phase 05→09 artifact chain without Hybrid-A*. The RAMP
    segments are welded portal→L01→…→LNN so the network rule-68 weld gate
    holds: each segment runs straight from the previous entry to its own."""
    sc, world, lv_builder = _setup(tmp_path)
    entries = []
    metas = []
    for i, (u_entry, z) in enumerate(entry_us_zs, start=1):
        seg = json.loads(json.dumps(_entry_segment(world, sc, u_entry=u_entry, level_z=z)))
        entries.append(np.asarray(seg["effectiveCenterline"]["points"]).reshape(-1, 3)[-1])
        metas.append((f"L{i:02d}", seg))
    segs = []
    prev = entries[0] + np.array([0.0, -60.0, 6.0])  # portal above the first entry
    for (level_id, seg), entry in zip(metas, entries, strict=True):
        pts = np.linspace(prev, entry, 31)
        seg["levelId"] = level_id
        seg["candidateId"] = f"{level_id}-C01"
        seg["effectiveCenterline"] = {"points": pts.ravel().tolist()}
        segs.append(seg)
        prev = entry
    smoothed = _smoothed(*segs)
    levels = lv_builder.build(smoothed, "rev")
    assert levels.status == "SUCCESS", levels.failure_reason
    levels_d = levels.model_dump(mode="json", by_alias=True)
    network = MineNetworkBuilder(sc).build(smoothed, "rev", levels_payload=levels_d)
    assert network.success, network.payload.failure_reason
    network_d = network.payload.model_dump(mode="json", by_alias=True)
    hard_ev = DesignCostEvaluator(world, sc.design, DesignContext.crosscut(sc.design))
    stopes = LongholeOpenStopingStrategy().generate(sc, world, levels_d, hard_ev, "rev")
    assert stopes.status == "SUCCESS", stopes.failure_reason
    stopes_d = stopes.model_dump(mode="json", by_alias=True)
    return sc, smoothed, levels_d, network_d, stopes_d


def _small(tmp_path):  # type: ignore[no-untyped-def]
    return _chain(tmp_path, [(25.0, 60.0), (25.0, 35.0), (25.0, 10.0)])


def _build(sc, smoothed, levels_d, network_d, stopes_d):  # type: ignore[no-untyped-def]
    return MineTimelineBuilder(sc).build(network_d, stopes_d, smoothed, levels_d, "rev")


def test_failed_prerequisites_never_schedule(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sc, smoothed, levels_d, network_d, stopes_d = _small(tmp_path)
    bad_net = json.loads(json.dumps(network_d))
    bad_net["status"] = "FAILED"
    p = _build(sc, smoothed, levels_d, bad_net, stopes_d)
    assert p.status == "FAILED" and p.tasks == [] and "network" in (p.failure_reason or "")
    bad_st = json.loads(json.dumps(stopes_d))
    bad_st["status"] = "FAILED"
    p = _build(sc, smoothed, levels_d, network_d, bad_st)
    assert p.status == "FAILED" and "stopes" in (p.failure_reason or "")


def test_deterministic_serialization(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sc, smoothed, levels_d, network_d, stopes_d = _small(tmp_path)
    a = _build(sc, smoothed, levels_d, network_d, stopes_d)
    b = _build(
        sc,
        json.loads(json.dumps(smoothed)),
        json.loads(json.dumps(levels_d)),
        json.loads(json.dumps(network_d)),
        json.loads(json.dumps(stopes_d)),
    )
    assert a.status == "SUCCESS", a.failure_reason
    assert json.dumps(a.model_dump(mode="json", by_alias=True)) == json.dumps(
        b.model_dump(mode="json", by_alias=True)
    )


def test_ramp_sequential_and_access_precedence(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sc, smoothed, levels_d, network_d, stopes_d = _small(tmp_path)
    p = _build(sc, smoothed, levels_d, network_d, stopes_d)
    assert p.status == "SUCCESS", p.failure_reason
    by_id = {t.id: t for t in p.tasks}
    # §6: sequential portal→deeper decline chain, validated from topology
    assert by_id["TASK:DEVELOP:RAMP:L01"].dependencies == []
    assert by_id["TASK:DEVELOP:RAMP:L02"].dependencies == ["TASK:DEVELOP:RAMP:L01"]
    assert by_id["TASK:DEVELOP:RAMP:L03"].dependencies == ["TASK:DEVELOP:RAMP:L02"]
    # §7: every L01 development is rooted (transitively) at the L01 ramp task
    ramp = "TASK:DEVELOP:RAMP:L01"
    l01 = [t for t in p.tasks if t.target_kind == "DEVELOPMENT" and ":L01:" in t.id]
    assert l01, "expected L01 developments"
    for t in l01:
        assert len(t.dependencies) == 1
        # walk up the single-dependency chain to the ramp
        cur = t
        seen = set()
        while cur.id != ramp:
            assert cur.id not in seen
            seen.add(cur.id)
            (dep,) = cur.dependencies
            cur = by_id[dep]
        assert cur.id == ramp
    # earliest start: every task starts exactly at max dependency end
    for t in p.tasks:
        expect = max((by_id[d].end_day for d in t.dependencies), default=0.0)
        assert t.start_day == pytest.approx(expect, abs=1e-9)
        assert t.end_day == pytest.approx(t.start_day + t.duration_days, abs=1e-9)
        assert t.duration_days > 0


def test_stope_prep_requires_both_access_crosscuts(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sc, smoothed, levels_d, network_d, stopes_d = _small(tmp_path)
    p = _build(sc, smoothed, levels_d, network_d, stopes_d)
    assert p.status == "SUCCESS", p.failure_reason
    by_id = {t.id: t for t in p.tasks}
    s0 = stopes_d["stopes"][0]
    prep = by_id[f"TASK:PREP:{s0['id']}"]
    upper = f"TASK:DEVELOP:CROSSCUT:{s0['upperLevelId']}:S{s0['stationIndex']:+03d}"
    lower = f"TASK:DEVELOP:CROSSCUT:{s0['lowerLevelId']}:S{s0['stationIndex']:+03d}"
    assert sorted(prep.dependencies) == sorted([upper, lower])
    assert prep.start_day == pytest.approx(
        max(by_id[upper].end_day, by_id[lower].end_day), abs=1e-9
    )
    # full five-task chain with exact ids and linear precedence
    sid = s0["id"]
    chain = [
        f"TASK:PREP:{sid}",
        f"TASK:STOPING:{sid}",
        f"TASK:MUCKING:{sid}",
        f"TASK:BACKFILL:{sid}",
        f"TASK:CURE:{sid}",
    ]
    for a, b in pairwise(chain):
        assert by_id[b].dependencies == [a]
    stoping = by_id[chain[1]]
    assert stoping.duration_days == pytest.approx(s0["tonnes"] / sc.schedule.stoping_tonnes_per_day)
    assert stoping.basis.quantity_unit == "t" and stoping.basis.rate_unit == "t/day"


def test_missing_and_duplicate_access_anchor_fail(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sc, smoothed, levels_d, network_d, stopes_d = _small(tmp_path)
    missing = json.loads(json.dumps(stopes_d))
    missing["stopes"][0]["upperAccessNodeId"] = "STOPE_ACCESS:L01:S+99"
    p = _build(sc, smoothed, levels_d, network_d, missing)
    assert p.status == "FAILED" and "does not exist" in (p.failure_reason or "")
    dup_net = json.loads(json.dumps(network_d))
    cc = next(e for e in dup_net["edges"] if e["type"] == "CROSSCUT")
    twin = json.loads(json.dumps(cc))
    twin["id"] = cc["id"] + ":DUP"
    dup_net["edges"].append(twin)
    p = _build(sc, smoothed, levels_d, dup_net, stopes_d)
    assert p.status == "FAILED" and "exactly one CROSSCUT" in (p.failure_reason or "")


def test_dag_cycle_detection() -> None:
    """§16: an explicit cycle in the task graph fails deterministically."""
    from minegen.scheduling.models import TaskBasis, TimelineTask

    def task(tid, deps):  # type: ignore[no-untyped-def]
        return TimelineTask(
            id=tid,
            task_type=TaskType.DEVELOP_RAMP,
            target_kind="DEVELOPMENT",
            target_id=tid,
            duration_days=1.0,
            start_day=0.0,
            end_day=0.0,
            dependencies=deps,
            basis=TaskBasis(quantity=1.0, quantity_unit="m", rate=1.0, rate_unit="m/day"),
        )

    tasks = {"A": task("A", ["B"]), "B": task("B", ["A"])}
    reason = solve_earliest_start(tasks)
    assert reason is not None and "cycle" in reason
    tasks = {"A": task("A", []), "B": task("B", ["A"]), "C": task("C", ["A", "B"])}
    assert solve_earliest_start(tasks) is None
    assert (tasks["A"].end_day, tasks["B"].end_day, tasks["C"].end_day) == (1.0, 2.0, 3.0)
    tasks = {"A": task("A", ["A"])}
    reason = solve_earliest_start(tasks)
    assert reason is not None and "itself" in reason


def test_ramp_topology_corruption_and_unsupported_type_fail(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sc, smoothed, levels_d, network_d, stopes_d = _small(tmp_path)
    loop = json.loads(json.dumps(network_d))
    back = json.loads(json.dumps(loop["edges"][0]))
    back["id"] = "RAMP:BACK"
    back["fromNode"], back["toNode"] = back["toNode"], "PORTAL"
    # a second RAMP leaving LEVEL_ENTRY:L01 is a branch: explicit failure
    loop["edges"].append(back)
    p = _build(sc, smoothed, levels_d, loop, stopes_d)
    assert p.status == "FAILED" and "ramp chain" in (p.failure_reason or "")
    raise_net = json.loads(json.dumps(network_d))
    r = json.loads(json.dumps(raise_net["edges"][0]))
    r["id"] = "RAISE:X"
    r["type"] = "RAISE"
    raise_net["edges"].append(r)
    p = _build(sc, smoothed, levels_d, raise_net, stopes_d)
    assert p.status == "FAILED"
    assert "UNSUPPORTED_DEVELOPMENT_TYPE" in (p.failure_reason or "")


def test_exact_state_transition_boundaries(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Rule 84: state(day) = latest transition with day <= day, exactly."""
    sc, smoothed, levels_d, network_d, stopes_d = _small(tmp_path)
    p = _build(sc, smoothed, levels_d, network_d, stopes_d)
    assert p.status == "SUCCESS", p.failure_reason
    dev = p.developments[0]
    s, e = dev.progress_start_day, dev.progress_end_day
    assert state_at(dev.initial_state, dev.transitions, s - 1e-9) is ObjectState.NOT_BUILT
    assert state_at(dev.initial_state, dev.transitions, s) is ObjectState.DEVELOPING
    assert state_at(dev.initial_state, dev.transitions, e - 1e-9) is ObjectState.DEVELOPING
    assert state_at(dev.initial_state, dev.transitions, e) is ObjectState.ACTIVE
    st = p.stopes[0]
    by_id = {t.id: t for t in p.tasks}
    prep = by_id[f"TASK:PREP:{st.stope_id}"]
    stoping = by_id[f"TASK:STOPING:{st.stope_id}"]
    cure = by_id[f"TASK:CURE:{st.stope_id}"]
    assert state_at(st.initial_state, st.transitions, 0.0) is ObjectState.PLANNED
    assert state_at(st.initial_state, st.transitions, prep.start_day) is ObjectState.DEVELOPING
    assert state_at(st.initial_state, st.transitions, stoping.start_day) is ObjectState.ACTIVE
    assert state_at(st.initial_state, st.transitions, stoping.end_day) is ObjectState.MINED
    assert state_at(st.initial_state, st.transitions, cure.end_day) is ObjectState.CLOSED
    assert state_at(st.initial_state, st.transitions, cure.end_day + 1) is ObjectState.CLOSED
    # transitions are chronologically ordered
    days = [t.day for t in st.transitions]
    assert days == sorted(days)


def test_chainage_contract_and_length_sync(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sc, smoothed, levels_d, network_d, stopes_d = _small(tmp_path)
    p = _build(sc, smoothed, levels_d, network_d, stopes_d)
    assert p.status == "SUCCESS", p.failure_reason
    for dev in p.developments:
        f = dev.point_chainage_fractions
        assert len(f) >= 2
        assert f[0] == 0.0 and f[-1] == 1.0
        assert all(b >= a for a, b in pairwise(f))
    # corrupted declared edge length => rule 83 sync failure
    bad = json.loads(json.dumps(network_d))
    bad["edges"][0]["length3d"] = float(bad["edges"][0]["length3d"]) + 1.0
    p = _build(sc, smoothed, levels_d, bad, stopes_d)
    assert p.status == "FAILED" and "rule 83" in (p.failure_reason or "")


def test_default_thirteen_level_acceptance_counts(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """§15 pinned counts without Hybrid-A*: one entry on-station (16 drift
    pieces) + twelve off-station entries (17 pieces) reproduces the accepted
    default topology: 13 + 220 + 221 = 454 development tasks, 204 stopes ×
    5 = 1020 stope tasks, 1474 total."""
    zs = [60.0 - i * (200.0 / 12.0) for i in range(13)]
    pairs = [(0.0 if i == 0 else 25.0, z) for i, z in enumerate(zs)]
    sc, smoothed, levels_d, network_d, stopes_d = _chain(tmp_path, pairs)
    p = _build(sc, smoothed, levels_d, network_d, stopes_d)
    assert p.status == "SUCCESS", p.failure_reason
    m = p.metrics
    assert m is not None
    assert m.development_task_count == 454
    assert m.stope_task_count == 1020
    assert m.task_count == 1474
    assert m.development_object_count == 454
    assert m.stope_object_count == 204
    assert m.first_stoping_day is not None and 0 < m.first_stoping_day < m.end_day
    assert m.ramp_completion_day <= m.end_day
    assert p.start_day == 0.0 and p.end_day == pytest.approx(m.end_day)


def _stopes_api(client, sid: str) -> dict:  # type: ignore[type-arg,no-untyped-def]
    r = client.post(f"/api/v1/scenarios/{sid}/design/stopes")
    assert r.status_code == 200, r.text
    body: dict = r.json()  # type: ignore[type-arg]
    assert body["status"] == "SUCCESS", body["failureReason"]
    return body


def test_timeline_api_lifecycle_and_invalidation(client, design_service) -> None:  # type: ignore[no-untyped-def]
    """§17–18: prerequisite 409s, rule-86 invalidation chain, and timeline
    regeneration leaving every upstream artifact byte-identical."""
    from tests.test_network_api import _levels, _network
    from tests.test_smoothing_api import _decline, _prepare
    from tests.test_tunnel_api import _smooth, _tunnel

    sid = _prepare(client)
    _decline(client, sid)
    _smooth(client, sid)
    _levels(client, sid)
    # network missing → 409 NETWORK_NOT_GENERATED
    r = client.post(f"/api/v1/scenarios/{sid}/design/timeline")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NETWORK_NOT_GENERATED"
    _network(client, sid)
    # stopes missing → 409 STOPES_NOT_GENERATED
    r = client.post(f"/api/v1/scenarios/{sid}/design/timeline")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "STOPES_NOT_GENERATED"
    r = client.get(f"/api/v1/scenarios/{sid}/design/timeline")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "TIMELINE_NOT_GENERATED"
    _stopes_api(client, sid)
    _tunnel(client, sid)

    r = client.post(f"/api/v1/scenarios/{sid}/design/timeline")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "SUCCESS", body["failureReason"]
    m = body["metrics"]
    assert m["taskCount"] == m["developmentTaskCount"] + m["stopeTaskCount"]
    assert m["stopeTaskCount"] == 5 * m["stopeObjectCount"]
    got = client.get(f"/api/v1/scenarios/{sid}/design/timeline")
    assert got.status_code == 200 and got.json() == body

    paths = {
        "tunnel": design_service.tunnel_report_path(sid),
        "levels": design_service.levels_path(sid),
        "network": design_service.network_path(sid),
        "stopes": design_service.stopes_path(sid),
    }
    before = {k: p.read_bytes() for k, p in paths.items()}
    tpath = design_service.timeline_path(sid)

    # timeline regeneration touches NOTHING upstream (byte-identical)
    r = client.post(f"/api/v1/scenarios/{sid}/design/timeline")
    assert r.status_code == 200
    for k, p in paths.items():
        assert p.read_bytes() == before[k], k

    # network regeneration deletes the timeline only
    _network(client, sid)
    assert not tpath.exists()
    client.post(f"/api/v1/scenarios/{sid}/design/timeline")
    # stopes regeneration deletes the timeline only
    _stopes_api(client, sid)
    assert not tpath.exists()
    client.post(f"/api/v1/scenarios/{sid}/design/timeline")
    assert tpath.is_file()
    # levels regeneration clears network + stopes + timeline (tunnel kept)
    _levels(client, sid)
    assert not tpath.exists()
    assert paths["tunnel"].read_bytes() == before["tunnel"]
    r = client.get(f"/api/v1/scenarios/{sid}/design/timeline")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "TIMELINE_NOT_GENERATED"
