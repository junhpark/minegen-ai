"""MineExchange 1.3.0 operations / timeline over the REAL method chains
(Phase 23B, rule 208) — e2e (three module-scoped stacks: layout search →
levels → production → network → timeline, minutes).

MX13-1  Longhole timeline exports and every reference resolves in the bundle
MX13-2  Cut & Fill timeline exports; BACKFILL / CURE tasks target the CUT
        entity (MX13-10: backfill is never a production target / tonnes)
MX13-3  Room & Pillar timeline exports; retained pillars never appear as
        targets or states (MX13-9)
MX13-14 a timeline republished during the export is READ_SNAPSHOT_CHANGED
The adapter e2e checks over the same stacks live in ``test_adapters_e2e.py``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest

from minegen.core.artifacts import TIMELINE_ARTIFACT
from minegen.exchange.bundle import write_bundle
from tests.test_analysis_api import _full_stack
from tests.test_exchange_bundle import EXPORT, Bundle, TabularStack, assert_integrity, export


@pytest.fixture(scope="module")
def longhole(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TabularStack]:
    stack = _full_stack(tmp_path_factory.mktemp("mx13-longhole"), "LONGHOLE_OPEN_STOPING")
    yield stack
    stack.close()


@pytest.fixture(scope="module")
def cut_fill(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TabularStack]:
    stack = _full_stack(tmp_path_factory.mktemp("mx13-cut-fill"), "CUT_AND_FILL")
    yield stack
    stack.close()


@pytest.fixture(scope="module")
def room_pillar(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TabularStack]:
    stack = _full_stack(
        tmp_path_factory.mktemp("mx13-room-pillar"),
        "ROOM_AND_PILLAR",
        {"kind": "ROOM_AND_PILLAR", "roomWidthM": 12.0, "pillarWidthM": 8.0, "benchCount": 1},
    )
    yield stack
    stack.close()


def _check_timeline_bundle(stack: TabularStack, b: Bundle, method: str) -> dict[str, Any]:
    """Every timeline reference resolves inside the bundle and the projection
    is a copy of the artifact (never recomputed)."""
    assert_integrity(b)
    om = b.omissions()
    assert "TIMELINE" not in om and om["FIELD_LATTICE"] == "NOT_IN_V1"
    assert TIMELINE_ARTIFACT in b.manifest["sourceSnapshot"]["artifactRevisions"]
    doc = b.json("operations/timeline.json")
    src = stack.artifact(TIMELINE_ARTIFACT)
    assert doc["semanticType"] == "MINE_TIMELINE" and doc["mineExchangeVersion"] == "1.3.0"
    assert doc["sourceArtifact"] == TIMELINE_ARTIFACT
    assert doc["startDay"] == src["startDay"] and doc["endDay"] == src["endDay"]
    net = b.json("topology/network.json")
    edges = {e["id"]: e for e in net["edges"]}
    entities = b.entities
    task_ids = {t["taskId"] for t in doc["tasks"]}
    assert len(task_ids) == len(doc["tasks"]) == len(src["tasks"])
    for t, s in zip(doc["tasks"], src["tasks"], strict=True):
        assert t["taskId"] == s["id"] and t["targetId"] == s["targetId"]
        assert (t["startDay"], t["endDay"]) == (s["startDay"], s["endDay"])
        assert set(t["dependencies"]) <= task_ids
        ref = t["targetReference"]
        if t["targetKind"] == "DEVELOPMENT":
            assert ref["kind"] == "NETWORK_EDGE" and ref["id"] in edges
        else:
            assert ref["kind"] == "ENTITY" and ref["id"] in entities, ref
            kind = entities[ref["id"]]["kind"]
            assert kind in ("STOPE", "CUT", "BENCH"), (t["taskId"], kind)
    # developments: one per network edge with geometry, chainage copied
    assert [d["edgeId"] for d in doc["developments"]] == [d["edgeId"] for d in src["developments"]]
    for d, s in zip(doc["developments"], src["developments"], strict=True):
        assert d["geometryEntityId"] == edges[d["edgeId"]]["geometryEntityId"]
        assert d["pointChainageFractions"] == s["pointChainageFractions"]
        assert d["excavationStartNode"] == s["excavationStartNode"]
        assert d["progressDirection"] == s["progressDirection"]
        assert d["excavationStartNode"] in (
            edges[d["edgeId"]]["sourceNodeId"],
            edges[d["edgeId"]]["targetNodeId"],
        )
    states = {s["entityId"]: s for s in doc["productionStates"]}
    assert len(states) == len(doc["productionStates"])
    for entity_id in states:
        assert entities[entity_id]["kind"] in ("STOPE", "CUT", "BENCH")
    mm = b.json("semantics/mining_method.json")
    assert mm["requestedMethod"] == method
    # metrics are the artifact's metrics (verbatim)
    assert doc["metrics"]["taskCount"] == src["metrics"]["taskCount"]
    assert doc["metrics"]["endDay"] == src["metrics"]["endDay"]
    # the task table is the document
    rows = b.text("operations/tasks.csv").splitlines()
    assert len(rows) - 1 == len(doc["tasks"])
    return doc


def test_mx13_1_longhole_timeline_exports_and_resolves(longhole: TabularStack) -> None:
    b = export(longhole.client, longhole.sid)
    doc = _check_timeline_bundle(longhole, b, "LONGHOLE_OPEN_STOPING")
    src = longhole.artifact(TIMELINE_ARTIFACT)
    stope_ids = {f"stope:{s['stopeId']}" for s in src["stopes"]}
    assert stope_ids and {s["entityId"] for s in doc["productionStates"]} == stope_ids
    stope_tasks = [t for t in doc["tasks"] if t["targetKind"] == "STOPE"]
    assert stope_tasks and {t["targetReference"]["id"] for t in stope_tasks} == stope_ids
    # determinism on the real chain
    assert export(longhole.client, longhole.sid).data == b.data


def test_mx13_2_10_cut_fill_backfill_targets_the_cut_never_a_production_tonne(
    cut_fill: TabularStack,
) -> None:
    b = export(cut_fill.client, cut_fill.sid)
    doc = _check_timeline_bundle(cut_fill, b, "CUT_AND_FILL")
    src = cut_fill.artifact(TIMELINE_ARTIFACT)
    cut_ids = {f"cut:{u['unitId']}" for u in src["production"]["units"]}
    assert cut_ids and {s["entityId"] for s in doc["productionStates"]} == cut_ids
    backfill_tasks = [t for t in doc["tasks"] if t["taskType"] in ("BACKFILL", "CURE_BACKFILL")]
    assert backfill_tasks
    for t in backfill_tasks:
        # the CUT is the target (the backfill IS the cut void); never a
        # backfill:<id> entity and never a tonnes basis
        assert t["targetReference"]["id"].startswith("cut:")
        assert t["basis"]["quantityUnit"] != "t"
    assert not any(t["targetReference"]["id"].startswith("backfill:") for t in doc["tasks"])
    assert not any(s["entityId"].startswith("backfill:") for s in doc["productionStates"])
    assert any(
        s["state"] == "BACKFILLED" for st in doc["productionStates"] for s in st["transitions"]
    )


def test_mx13_3_9_room_pillar_pillars_are_never_timeline_targets(room_pillar: TabularStack) -> None:
    b = export(room_pillar.client, room_pillar.sid)
    doc = _check_timeline_bundle(room_pillar, b, "ROOM_AND_PILLAR")
    src = room_pillar.artifact(TIMELINE_ARTIFACT)
    unit_ids = {f"bench:{u['unitId']}" for u in src["production"]["units"]}
    assert unit_ids and {s["entityId"] for s in doc["productionStates"]} == unit_ids
    pillars = {e["entityId"] for e in b.manifest["entities"] if e["kind"] == "PILLAR"}
    assert pillars  # the bundle exports retained pillars as geometry …
    targets = {t["targetReference"]["id"] for t in doc["tasks"]}
    assert not (targets & pillars)  # … but they are never a task target
    assert not ({s["entityId"] for s in doc["productionStates"]} & pillars)
    rooms = {e["entityId"] for e in b.manifest["entities"] if e["kind"] == "ROOM"}
    assert not (targets & rooms)  # semantic parents are not targets either


def test_mx13_14_timeline_republished_during_export_is_refused(
    longhole: TabularStack, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = write_bundle
    target = longhole.derived / TIMELINE_ARTIFACT
    original = target.read_bytes()
    st0 = target.stat()

    def racing(spec: Any) -> Any:
        target.write_bytes(original)
        os.utime(target, ns=(st0.st_atime_ns, st0.st_mtime_ns + 1_000_000))
        return real(spec)

    monkeypatch.setattr("minegen.services.exchange_service.write_bundle", racing)
    r = longhole.client.post(f"/api/v1/scenarios/{longhole.sid}{EXPORT}")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "READ_SNAPSHOT_CHANGED"
    monkeypatch.undo()
    os.utime(target, ns=(st0.st_atime_ns, st0.st_mtime_ns))
    assert export(longhole.client, longhole.sid).files
