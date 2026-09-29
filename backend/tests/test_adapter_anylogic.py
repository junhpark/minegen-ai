"""Phase 23B AnyLogic operational data adapter (directive §29–§41, §66).

FAST over the synthetic consistent bundle (development-only timeline):
referential integrity of every table, progress / states copied verbatim,
blank simulation template, no invented fleet / dispatch value, typed
refusals for a 1.2-shaped bundle and an unsupported version.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from minegen.adapters import build_package
from minegen.adapters.anylogic.adapter import (
    CAPABILITIES_PATH,
    EDGES_PATH,
    NODES_PATH,
    PACKAGE_ROOT,
    POINTS_PATH,
    PRODUCTION_PATH,
    PROGRESS_PATH,
    SIMULATION_INPUT_COLUMNS,
    STATES_PATH,
    TASKS_PATH,
    TEMPLATE_PATH,
)
from minegen.adapters.errors import (
    MineExchangeBundleInvalidError,
    MineExchangeVersionUnsupportedError,
    RequiredSourceAbsentError,
)
from tests.adapter_support import (
    bundle_files,
    manifest,
    package_root,
    rehashed,
    table,
    unzip,
)
from tests.exchange_fixtures import synthetic_bundle
from tests.test_exchange_corrections import SyntheticMine

FLEET_WORDS = ("fleet", "speed", "dispatch", "truck", "lhd", "cycle", "shift", "crusher")


@pytest.fixture(scope="module")
def mine() -> SyntheticMine:
    return SyntheticMine()


@pytest.fixture(scope="module")
def bundle(mine: SyntheticMine) -> bytes:
    return synthetic_bundle(mine)


@pytest.fixture(scope="module")
def package(bundle: bytes) -> dict[str, bytes]:
    pkg = build_package("ANYLOGIC", bundle)
    assert package_root(pkg.zip_bytes) == PACKAGE_ROOT
    return unzip(pkg.zip_bytes)


def _doc(bundle: bytes, path: str) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(bundle_files(bundle)[path])
    return doc


def test_a1_tables_are_referentially_complete(bundle: bytes, package: dict[str, bytes]) -> None:
    net = _doc(bundle, "topology/network.json")
    _, nodes = table(package, NODES_PATH)
    _, edges = table(package, EDGES_PATH)
    node_ids = {n["nodeId"] for n in nodes}
    assert node_ids == {n["id"] for n in net["nodes"]}
    assert [e["edgeId"] for e in edges] == [e["id"] for e in net["edges"]]
    for e in edges:
        assert e["sourceNodeId"] in node_ids and e["targetNodeId"] in node_ids
    _, points = table(package, POINTS_PATH)
    owned = {e["geometryEntityId"] for e in edges if e["geometryEntityId"]}
    assert {p["geometryEntityId"] for p in points} == owned
    # the RAISE edge has no path shape and is a typed omission, never invented
    raise_edge = next(e for e in edges if e["edgeType"] == "RAISE")
    assert raise_edge["geometryEntityId"] == "" and raise_edge["geometryContract"] == "NONE"
    om = {o["subject"]: o["reasonCode"] for o in manifest(package)["omissions"]}
    assert om[f"edge:{raise_edge['edgeId']}"] == "NO_GEOMETRY_CONTRACT"
    _, caps = table(package, CAPABILITIES_PATH)
    edge_ids = {e["edgeId"] for e in edges}
    assert caps and all(c["edgeId"] in edge_ids for c in caps)
    assert {c["allowed"] for c in caps} <= {"true", "false"}
    _, tasks = table(package, TASKS_PATH)
    task_ids = {t["taskId"] for t in tasks}
    for t in tasks:
        assert t["targetReferenceKind"] == "NETWORK_EDGE" and t["targetReferenceId"] in edge_ids
        assert all(d in task_ids for d in json.loads(t["dependencies"]))
        assert float(t["endDay"]) >= float(t["startDay"])
    # edge direction semantics are stated, never one-way traffic
    assert manifest(package)["details"]["directionSemantics"]
    readme = package["README.txt"].decode()
    assert "NOT" in readme and "one-way" in readme


def test_a2_progress_and_states_are_copied_verbatim(
    bundle: bytes, package: dict[str, bytes]
) -> None:
    tl = _doc(bundle, "operations/timeline.json")
    _, progress = table(package, PROGRESS_PATH)
    assert [p["edgeId"] for p in progress] == [d["edgeId"] for d in tl["developments"]]
    for row, dev in zip(progress, tl["developments"], strict=True):
        assert json.loads(row["pointChainageFractions"]) == dev["pointChainageFractions"]
        assert row["excavationStartNode"] == dev["excavationStartNode"]
        assert int(row["progressDirection"]) == dev["progressDirection"]
        assert row["initialState"] == dev["initialState"]
        assert float(row["progressStartDay"]) == dev["progressStartDay"]
        assert float(row["progressEndDay"]) == dev["progressEndDay"]
        assert row["taskId"] == dev["taskId"]
    _, states = table(package, STATES_PATH)
    expected = [
        (s["entityId"], s["targetKind"], s["initialState"], str(i), x["state"])
        for s in tl["productionStates"]
        for i, x in enumerate(s["transitions"])
    ]
    got = [
        (r["entityId"], r["targetKind"], r["initialState"], r["transitionIndex"], r["state"])
        for r in states
    ]
    assert got == expected  # development-only timeline → empty, but the table exists
    d = manifest(package)["details"]
    assert d["taskCount"] == len(tl["tasks"]) and d["developmentProgressCount"] == len(progress)
    assert d["timelineStartDay"] == tl["startDay"] and d["timelineEndDay"] == tl["endDay"]


def test_a3_template_is_columns_only_and_no_fleet_value_exists(package: dict[str, bytes]) -> None:
    header, rows = table(package, TEMPLATE_PATH)
    assert header == [c for c, _ in SIMULATION_INPUT_COLUMNS]
    assert rows == [dict.fromkeys(header, "")]
    m = manifest(package)
    kinds = {a["kind"]: a for a in m["assumptions"]}
    assert set(header) <= set(kinds)
    for a in kinds.values():
        assert a["state"] == "NOT_PROVIDED" and a["value"] is None
    assert not any(a["state"] == "ADAPTER_DEFAULT_EXPLICIT" for a in m["assumptions"])
    # no fleet / speed / dispatch number anywhere in a data table
    for path in (NODES_PATH, EDGES_PATH, TASKS_PATH, PROGRESS_PATH, PRODUCTION_PATH):
        header, _ = table(package, path)
        for column in header:
            assert not any(w in column.lower() for w in FLEET_WORDS), (path, column)
    assert ".alp" in package["README.txt"].decode()


def test_a4_production_table_is_empty_without_production_and_states_say_why(
    package: dict[str, bytes],
) -> None:
    header, rows = table(package, PRODUCTION_PATH)
    assert header[:2] == ["entityId", "productionKind"] and rows == []
    states = {s["group"]: s for s in manifest(package)["sourceStates"]}
    assert states["STOPES"]["state"] == "ARTIFACT_ABSENT"
    assert states["TIMELINE"]["state"] == "AVAILABLE"
    assert states["NETWORK"]["state"] == "AVAILABLE"
    assert states["CAPABILITY"]["state"] == "AVAILABLE"
    assert states["RENDER_GLB"]["state"] == "ARTIFACT_ABSENT"
    assert states["FIELD_LATTICE"]["state"] == "NOT_EXPORTED_BY_VERSION"
    assert manifest(package)["details"]["productionKind"] is None


def test_a5_a_1_2_shaped_bundle_is_required_source_absent(mine: SyntheticMine) -> None:
    with pytest.raises(RequiredSourceAbsentError) as exc:
        build_package("ANYLOGIC", synthetic_bundle(mine, with_timeline=False))
    assert exc.value.source_group == "TIMELINE" and "ARTIFACT_ABSENT" in exc.value.detail


def test_a6_mine_exchange_below_1_3_is_version_unsupported(bundle: bytes) -> None:
    def downgrade(doc: dict[str, Any]) -> None:
        doc["mineExchangeVersion"] = "1.2.0"

    with pytest.raises(MineExchangeVersionUnsupportedError) as exc:
        build_package("ANYLOGIC", rehashed(bundle, {}, manifest_edit=downgrade))
    assert exc.value.adapter == "ANYLOGIC" and ">=1.3.0" in exc.value.reason


def test_a7_dangling_timeline_reference_is_a_typed_bundle_refusal(bundle: bytes) -> None:
    tl = _doc(bundle, "operations/timeline.json")
    tl["tasks"][0]["targetReference"]["id"] = "EDGE:NOPE"
    data = rehashed(bundle, {"operations/timeline.json": json.dumps(tl).encode("utf-8")})
    with pytest.raises(MineExchangeBundleInvalidError, match="not in the network") as exc:
        build_package("ANYLOGIC", data)
    assert exc.value.source_group == "TIMELINE" and exc.value.subject == tl["tasks"][0]["taskId"]


def test_a8_deterministic(bundle: bytes) -> None:
    a = build_package("ANYLOGIC", bundle)
    assert a.zip_bytes == build_package("ANYLOGIC", bundle).zip_bytes
    assert a.manifest.coordinate_mapping.transform is None
