"""MineExchange 1.3.0 — operations / timeline projection (Phase 23B, rule 208).

FAST, builder-level over the synthetic consistent mine (``tests/exchange_fixtures``)
and the pure ``project_timeline`` function:

MX13-4  no timeline → TIMELINE ARTIFACT_ABSENT, no operations/ files
MX13-5  FAILED timeline → TIMELINE SOURCE_NOT_SUCCESS with the failure reason
MX13-6  every dependency resolves (a dangling one is a typed refusal)
MX13-7  every development target / development edge / geometryRef / start node
        resolves to the exported network (typed refusals otherwise)
MX13-8  production targets and states resolve to exported production entities
        (typed refusal on a dangling one) — pure-function level; the real
        Longhole / Cut & Fill / Room & Pillar chains are in
        ``test_exchange_timeline_e2e.py`` (MX13-1..3, 9, 10, 14)
MX13-11 geometry binaries and every non-operations file are byte-identical
        with and without a timeline
MX13-12 1.2 semantic content is unchanged: the timeline is purely additive
        (files, omissions and hashes differ ONLY by operations/* + TIMELINE)
MX13-13 determinism (same inputs → identical bytes)
plus the DTO contract (semantic types, target references, chainage copy, CSV
table = document) and the FIELD_LATTICE NOT_IN_V1 omission kept as is.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from typing import Any

import pytest

from minegen.core.artifacts import LEGACY_RAMP_ARTIFACT
from minegen.exchange.builder import (
    ArtifactInput,
    ExchangeExportError,
    ProductionExport,
    build_exchange,
    project_network,
    project_timeline,
)
from minegen.exchange.bundle import BUNDLE_ROOT, write_bundle
from minegen.exchange.formats.csv_table import read_csv
from minegen.exchange.geometry.centerlines import (
    level_centerlines,
    ramp_centerlines,
    shaft_centerlines,
)
from minegen.exchange.models import MINE_EXCHANGE_VERSION, ExchangeTimeline
from tests.exchange_fixtures import consistent_network, development_timeline, synthetic_bundle
from tests.test_exchange_corrections import (
    SyntheticMine,
    levels_doc,
    ramp_doc,
    shafts_doc,
)


def _entries(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return {n[len(BUNDLE_ROOT) + 1 :]: zf.read(n) for n in zf.namelist()}


def _manifest(entries: dict[str, bytes]) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(entries["manifest.json"])
    return doc


def _omissions(entries: dict[str, bytes]) -> dict[str, str]:
    return {o["group"]: o["reasonCode"] for o in _manifest(entries)["omissions"]}


@pytest.fixture(scope="module")
def mine() -> SyntheticMine:
    return SyntheticMine()


@pytest.fixture(scope="module")
def with_timeline(mine: SyntheticMine) -> dict[str, bytes]:
    return _entries(synthetic_bundle(mine))


@pytest.fixture(scope="module")
def without_timeline(mine: SyntheticMine) -> dict[str, bytes]:
    return _entries(synthetic_bundle(mine, with_timeline=False))


# --------------------------------------------------------------------------- #
# contract
# --------------------------------------------------------------------------- #


def test_timeline_document_and_task_table_contract(with_timeline: dict[str, bytes]) -> None:
    e = with_timeline
    m = _manifest(e)
    assert m["mineExchangeVersion"] == MINE_EXCHANGE_VERSION == "1.3.0"
    files = {f["path"]: f for f in m["files"]}
    assert files["operations/timeline.json"]["semanticType"] == "MINE_TIMELINE"
    assert files["operations/timeline.json"]["representation"] == "DOCUMENT"
    assert files["operations/timeline.json"]["sourceArtifact"] == "timeline.json"
    assert files["operations/timeline.json"]["sourceRevision"] == "r-tl"
    assert files["operations/tasks.csv"]["semanticType"] == "MINE_TIMELINE_TASKS"
    assert "TIMELINE" not in _omissions(e)
    assert _omissions(e)["FIELD_LATTICE"] == "NOT_IN_V1"
    doc = ExchangeTimeline.model_validate(json.loads(e["operations/timeline.json"]))
    assert doc.semantic_type == "MINE_TIMELINE" and doc.mine_exchange_version == "1.3.0"
    assert "never a production forecast" in doc.timeline_semantics
    assert "day <= day" in doc.timeline_semantics
    src = development_timeline(consistent_network())
    net = json.loads(e["topology/network.json"])
    edges = {x["id"]: x for x in net["edges"]}
    # tasks: copied verbatim, external references to exported edges
    assert [t.task_id for t in doc.tasks] == [t["id"] for t in src["tasks"]]
    for t, s in zip(doc.tasks, src["tasks"], strict=True):
        assert t.target_reference.kind == "NETWORK_EDGE" and t.target_reference.id in edges
        assert t.target_id == s["targetId"] and t.task_type == s["taskType"]
        assert (t.start_day, t.end_day, t.duration_days) == (
            s["startDay"],
            s["endDay"],
            s["durationDays"],
        )
        assert t.dependencies == s["dependencies"]
        assert t.basis.quantity == s["basis"]["quantity"] and t.basis.rate_unit == "m/day"
    # developments: chainage / start node / direction copied, entity bound to the edge
    assert [d.edge_id for d in doc.developments] == [d["edgeId"] for d in src["developments"]]
    for d, s in zip(doc.developments, src["developments"], strict=True):
        assert d.geometry_entity_id == edges[d.edge_id]["geometryEntityId"]
        assert d.point_chainage_fractions == s["pointChainageFractions"]
        assert (
            d.excavation_start_node == s["excavationStartNode"] == edges[d.edge_id]["sourceNodeId"]
        )
        assert d.progress_direction == 1 and d.initial_state == "NOT_BUILT"
        assert [(x.day, x.state) for x in d.transitions] == [
            (x["day"], x["state"]) for x in s["transitions"]
        ]
    assert doc.production_states == []
    assert doc.metrics is not None and doc.metrics.task_count == len(src["tasks"])
    assert doc.metrics.total_development_length3d == src["metrics"]["totalDevelopmentLength3d"]
    # the CSV is the document's task list
    header, rows = read_csv(e["operations/tasks.csv"].decode("utf-8"))
    assert header[:5] == [
        "taskId",
        "taskType",
        "targetKind",
        "targetReferenceKind",
        "targetReferenceId",
    ]
    assert [r[0] for r in rows] == [t.task_id for t in doc.tasks]
    assert rows[1][8] == doc.tasks[1].dependencies[0]
    # the RAISE edge (no geometry) has no task and no progress entry
    assert "RAISE:L01:X" not in {t.target_reference.id for t in doc.tasks}


# --------------------------------------------------------------------------- #
# MX13-4 / MX13-5 — absence semantics
# --------------------------------------------------------------------------- #


def test_mx13_4_absent_timeline_is_artifact_absent(without_timeline: dict[str, bytes]) -> None:
    assert _omissions(without_timeline)["TIMELINE"] == "ARTIFACT_ABSENT"
    assert not any(p.startswith("operations/") for p in without_timeline)
    om = next(o for o in _manifest(without_timeline)["omissions"] if o["group"] == "TIMELINE")
    assert om["sourceArtifact"] == "timeline.json"


def test_mx13_5_failed_timeline_is_source_not_success(mine: SyntheticMine) -> None:
    failed = {**development_timeline(consistent_network()), "status": "FAILED"}
    failed["failureReason"] = "UNREACHABLE_DEVELOPMENT: DRIFT:L01:01"
    e = _entries(synthetic_bundle(mine, timeline=ArtifactInput(failed, "r-tl-failed")))
    om = next(o for o in _manifest(e)["omissions"] if o["group"] == "TIMELINE")
    assert om["reasonCode"] == "SOURCE_NOT_SUCCESS"
    assert "FAILED" in om["detail"] and "UNREACHABLE_DEVELOPMENT" in om["detail"]
    assert not any(p.startswith("operations/") for p in e)


# --------------------------------------------------------------------------- #
# MX13-6 / MX13-7 — every reference resolves (typed refusals)
# --------------------------------------------------------------------------- #


def _refused(mine: SyntheticMine, timeline: dict[str, Any], match: str) -> None:
    with pytest.raises(ExchangeExportError, match=match):
        synthetic_bundle(mine, timeline=ArtifactInput(timeline, "r-bad"))


def test_mx13_6_dangling_dependency_is_refused(mine: SyntheticMine) -> None:
    tl = development_timeline(consistent_network())
    tl["tasks"][2]["dependencies"] = ["TASK:DEVELOP:NOPE"]
    _refused(mine, tl, "dependency 'TASK:DEVELOP:NOPE' is not a task")


def test_mx13_6_duplicate_task_id_is_refused(mine: SyntheticMine) -> None:
    tl = development_timeline(consistent_network())
    tl["tasks"][1]["id"] = tl["tasks"][0]["id"]
    _refused(mine, tl, "duplicate task id")


def test_mx13_7_development_target_must_be_an_exported_edge(mine: SyntheticMine) -> None:
    tl = development_timeline(consistent_network())
    tl["tasks"][0]["targetId"] = "RAMP:S99"
    _refused(mine, tl, "development target 'RAMP:S99' is not an exported network edge")


def test_mx13_7_development_entry_edge_geometry_and_start_node_resolve(
    mine: SyntheticMine,
) -> None:
    tl = development_timeline(consistent_network())
    tl["developments"][0]["edgeId"] = "RAMP:S99"
    _refused(mine, tl, "development 'RAMP:S99': not an exported network edge")
    tl = development_timeline(consistent_network())
    tl["developments"][0]["geometryRef"] = {"artifact": LEGACY_RAMP_ARTIFACT, "segmentIndex": 1}
    _refused(mine, tl, "geometryRef resolves to 'ramp:main:S02' but the exported edge owns")
    tl = development_timeline(consistent_network())
    tl["developments"][0]["geometryRef"] = {"artifact": LEGACY_RAMP_ARTIFACT, "segmentIndex": 7}
    _refused(mine, tl, "out of range")
    tl = development_timeline(consistent_network())
    tl["developments"][0]["excavationStartNode"] = "JUNCTION:L01:C"
    _refused(mine, tl, "excavationStartNode 'JUNCTION:L01:C' is not an end node")
    tl = development_timeline(consistent_network())
    tl["developments"][0]["taskId"] = "TASK:NOPE"
    _refused(mine, tl, "task 'TASK:NOPE' is not a task")


def test_mx13_7_malformed_timeline_is_a_typed_refusal(mine: SyntheticMine) -> None:
    tl = development_timeline(consistent_network())
    tl["tasks"][0]["basis"] = {"quantity": "many"}
    _refused(mine, tl, "does not match the MineTimeline contract")


# --------------------------------------------------------------------------- #
# MX13-8 — production references (pure projection)
# --------------------------------------------------------------------------- #


def _projection_inputs() -> dict[str, Any]:
    net = consistent_network()
    centerlines = (
        ramp_centerlines(ramp_doc(), LEGACY_RAMP_ARTIFACT)
        + level_centerlines(levels_doc())
        + shaft_centerlines(shafts_doc())
    )
    network = project_network(
        net,
        "r-net",
        centerlines,
        ramp_doc=ramp_doc(),
        ramp_artifact=LEGACY_RAMP_ARTIFACT,
        accesses_doc=None,
        levels_doc=levels_doc(),
        shafts_doc=shafts_doc(),
    )
    return {
        "network": network,
        "centerlines": centerlines,
        "ramp_doc": ramp_doc(),
        "accesses_doc": None,
        "levels_doc": levels_doc(),
        "shafts_doc": shafts_doc(),
    }


def _stope_task(stope_id: str) -> dict[str, Any]:
    return {
        "id": f"TASK:STOPING:{stope_id}",
        "taskType": "STOPING",
        "targetKind": "STOPE",
        "targetId": stope_id,
        "durationDays": 2.0,
        "startDay": 10.0,
        "endDay": 12.0,
        "dependencies": [],
        "basis": {"quantity": 3000.0, "quantityUnit": "t", "rate": 1500.0, "rateUnit": "t/day"},
    }


def test_mx13_8_production_targets_and_states_resolve_to_exported_entities() -> None:
    inputs = _projection_inputs()
    tl = development_timeline(consistent_network())
    tl["tasks"].append(_stope_task("STOPE:L01-L02:S+00"))
    tl["stopes"] = [
        {
            "stopeId": "STOPE:L01-L02:S+00",
            "initialState": "PLANNED",
            "transitions": [{"day": 10.0, "state": "ACTIVE"}, {"day": 12.0, "state": "MINED"}],
        }
    ]
    exported = ProductionExport("STOPES", ["stope:STOPE:L01-L02:S+00"], 1, 1)
    doc = project_timeline(tl, "r-tl", production=exported, **inputs)
    stoping = doc.tasks[-1]
    assert stoping.target_reference.kind == "ENTITY"
    assert stoping.target_reference.id == "stope:STOPE:L01-L02:S+00"
    assert [s.entity_id for s in doc.production_states] == ["stope:STOPE:L01-L02:S+00"]
    assert doc.production_states[0].target_kind == "STOPE"
    assert doc.production_states[0].source_id == "STOPE:L01-L02:S+00"
    assert [(x.day, x.state) for x in doc.production_states[0].transitions] == [
        (10.0, "ACTIVE"),
        (12.0, "MINED"),
    ]
    # a target the bundle did not export (e.g. the production artifact is
    # absent or the id is foreign) is a typed refusal, never a dangling id
    absent = ProductionExport("STOPES", [], 0, 0)
    with pytest.raises(ExchangeExportError, match="not an exported production entity"):
        project_timeline(tl, "r-tl", production=absent, **inputs)
    # cut / room-extraction kinds map to cut:<id> / bench:<unitId>
    tl2 = development_timeline(consistent_network())
    tl2["production"] = {
        "method": "CUT_AND_FILL",
        "targetKind": "CUT",
        "units": [{"unitId": "CUT:L01-L02:LF00:C00", "initialState": "PLANNED", "transitions": []}],
    }
    doc2 = project_timeline(
        tl2,
        "r",
        production=ProductionExport("CUT_FILL", ["cut:CUT:L01-L02:LF00:C00"], 1, 0),
        **inputs,
    )
    assert doc2.production_states[0].entity_id == "cut:CUT:L01-L02:LF00:C00"
    tl3 = development_timeline(consistent_network())
    tl3["production"] = {
        "method": "ROOM_AND_PILLAR",
        "targetKind": "ROOM_EXTRACTION",
        "units": [
            {"unitId": "ROOM:R000:C000:HEADING", "initialState": "PLANNED", "transitions": []}
        ],
    }
    doc3 = project_timeline(
        tl3,
        "r",
        production=ProductionExport(
            "ROOM_PILLAR", ["bench:ROOM:R000:C000:HEADING", "pillar:PILLAR:R000:C001"], 1, 0
        ),
        **inputs,
    )
    assert doc3.production_states[0].entity_id == "bench:ROOM:R000:C000:HEADING"
    assert not any(s.entity_id.startswith("pillar:") for s in doc3.production_states)


def test_mx13_7_timeline_without_an_exported_network_is_refused() -> None:
    inputs = _projection_inputs()
    inputs["network"] = None
    with pytest.raises(ExchangeExportError, match="no MineNetwork is exported"):
        project_timeline(
            development_timeline(consistent_network()),
            "r",
            production=ProductionExport("STOPES", [], 0, 0),
            **inputs,
        )


# --------------------------------------------------------------------------- #
# MX13-11 / 12 / 13 — additive, byte-identical, deterministic
# --------------------------------------------------------------------------- #


def test_mx13_11_12_timeline_is_purely_additive(
    with_timeline: dict[str, bytes], without_timeline: dict[str, bytes]
) -> None:
    extra = set(with_timeline) - set(without_timeline)
    assert extra == {"operations/timeline.json", "operations/tasks.csv"}
    assert set(without_timeline) - set(with_timeline) == set()
    # every 1.2 file — geometry binaries included — is byte-identical
    for path in without_timeline:
        if path in ("manifest.json", "README.txt"):
            continue
        assert (
            hashlib.sha256(with_timeline[path]).digest()
            == hashlib.sha256(without_timeline[path]).digest()
        ), path
    assert any(p.endswith(".stl") for p in without_timeline)
    assert any(p.endswith(".dxf") for p in without_timeline)
    # the manifests differ only by the two files, the TIMELINE omission and the
    # artifact revision of the timeline source
    a, b = _manifest(with_timeline), _manifest(without_timeline)
    a_files = {f["path"]: f for f in a["files"] if not f["path"].startswith("operations/")}
    b_files = {f["path"]: f for f in b["files"]}
    a_files.pop("README.txt")
    b_files.pop("README.txt")
    assert a_files == b_files
    assert a["entities"] == b["entities"]
    assert [o for o in b["omissions"] if o["group"] != "TIMELINE"] == a["omissions"]
    assert a["mineExchangeVersion"] == b["mineExchangeVersion"] == "1.3.0"


def test_mx13_13_export_is_deterministic(mine: SyntheticMine) -> None:
    assert synthetic_bundle(mine) == synthetic_bundle(mine)
    spec_a = build_exchange(
        mine.inputs(
            network=ArtifactInput(consistent_network(), "r-net"),
            timeline=ArtifactInput(development_timeline(consistent_network()), "r-tl"),
        )
    )
    assert write_bundle(spec_a)[0] == synthetic_bundle(mine)
