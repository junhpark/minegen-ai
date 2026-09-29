"""Phase 23B Ventsim seed adapter (directive §21–§28, §65).

FAST over the synthetic consistent bundle: verbatim DXF authority, one airway
per network edge with geometry, manifest-sourced DXF handles, copied
dimensions, no invented ventilation physics, typed refusals, determinism.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pytest

from minegen.adapters import build_package
from minegen.adapters.errors import (
    AdapterConversionFailedError,
    MineExchangeBundleInvalidError,
    RequiredSourceAbsentError,
    RequiredSourceNotSuccessError,
)
from minegen.adapters.ventsim.adapter import (
    AIRWAYS_PATH,
    DXF_PATH,
    ENTITY_MAP_PATH,
    NODES_PATH,
    NOT_PROVIDED_PROPERTIES,
    PACKAGE_ROOT,
)
from minegen.exchange.builder import ArtifactInput
from tests.adapter_support import (
    bundle_files,
    bundle_manifest,
    edited_network,
    manifest,
    package_root,
    table,
    unzip,
)
from tests.exchange_fixtures import consistent_network, synthetic_bundle
from tests.test_exchange_corrections import SyntheticMine

PHYSICS_WORDS = (
    "friction",
    "resistance",
    "fan",
    "regulator",
    "door",
    "leakage",
    "heat",
    "diesel",
    "airflow",
    "pressure",
    "density",
)


@pytest.fixture(scope="module")
def mine() -> SyntheticMine:
    return SyntheticMine()


@pytest.fixture(scope="module")
def bundle(mine: SyntheticMine) -> bytes:
    return synthetic_bundle(mine)


@pytest.fixture(scope="module")
def package(bundle: bytes) -> dict[str, bytes]:
    pkg = build_package("VENTSIM", bundle)
    assert package_root(pkg.zip_bytes) == PACKAGE_ROOT
    return unzip(pkg.zip_bytes)


def _network(bundle: bytes) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(bundle_files(bundle)["topology/network.json"])
    return doc


def test_v1_dxf_is_the_bundle_dxf_byte_for_byte(bundle: bytes, package: dict[str, bytes]) -> None:
    assert package[DXF_PATH] == bundle_files(bundle)["excavations/centerlines.dxf"]
    gen = {f["path"]: f for f in manifest(package)["generatedFiles"]}
    assert gen[DXF_PATH]["sourceFiles"] == ["excavations/centerlines.dxf"]
    assert gen[DXF_PATH]["targetSemantic"] == "VENTSIM_CENTERLINES_FOR_CONVERT"
    assert manifest(package)["details"]["geometryFidelity"].startswith("FULL")


def test_v2_one_airway_per_edge_with_geometry_and_raise_is_a_typed_omission(
    bundle: bytes, package: dict[str, bytes]
) -> None:
    net = _network(bundle)
    with_geometry = [e for e in net["edges"] if e["geometryEntityId"] is not None]
    without = [e for e in net["edges"] if e["geometryEntityId"] is None]
    assert len(without) == 1 and without[0]["type"] == "RAISE"
    header, rows = table(package, AIRWAYS_PATH)
    assert header == [
        "edgeId",
        "geometryEntityId",
        "sourceNodeId",
        "targetNodeId",
        "edgeType",
        "lengthM",
        "widthM",
        "heightM",
        "shape",
        "orientation",
        "dxfHandle",
        "levelId",
        "vertexCount",
    ]
    assert [r["edgeId"] for r in rows] == [e["id"] for e in with_geometry]
    assert {r["geometryEntityId"] for r in rows} == {e["geometryEntityId"] for e in with_geometry}
    m = manifest(package)
    om = {o["subject"]: o for o in m["omissions"]}
    assert om[f"edge:{without[0]['id']}"]["reasonCode"] == "NO_GEOMETRY_CONTRACT"
    assert m["details"]["airwayCount"] == len(with_geometry)
    assert m["details"]["airwayCountByType"]["SHAFT"] == 2
    assert m["details"]["airwayCountByType"]["SHAFT_STATION_ACCESS"] == 1
    # every node
    _, nodes = table(package, NODES_PATH)
    assert [n["nodeId"] for n in nodes] == [n["id"] for n in net["nodes"]]
    assert sum(1 for n in nodes if n["surface"] == "true") == m["details"]["surfaceNodeCount"]


def test_v3_dxf_handles_come_from_the_manifest_and_every_entity_row_links_its_edge(
    bundle: bytes, package: dict[str, bytes]
) -> None:
    dxf_entry = next(
        f for f in bundle_manifest(bundle)["files"] if f["path"] == "excavations/centerlines.dxf"
    )
    handle_of = {row["entityId"]: row["handle"] for row in dxf_entry["dxfEntities"]}
    _, airways = table(package, AIRWAYS_PATH)
    for r in airways:
        assert r["dxfHandle"] == handle_of[r["geometryEntityId"]], r["edgeId"]
    _, ident = table(package, ENTITY_MAP_PATH)
    assert {r["dxfHandle"] for r in ident} == set(handle_of.values())
    edge_of = {r["geometryEntityId"]: r["edgeId"] for r in airways}
    bundle_entities = {e["entityId"]: e for e in bundle_manifest(bundle)["entities"]}
    for r in ident:
        assert r["entityKind"] == bundle_entities[r["entityId"]]["kind"]
        assert r["dxfEntityType"] == "POLYLINE" and r["layer"]
        assert r["edgeId"] == edge_of.get(r["entityId"], "")
    m = manifest(package)
    assert {e["targetId"] for e in m["identityMap"]} == set(handle_of.values())
    assert all(e["targetKind"] == "DXF_HANDLE" and e["file"] == DXF_PATH for e in m["identityMap"])


def test_v4_dimensions_length_and_shape_are_copied_from_the_bundle(
    bundle: bytes, package: dict[str, bytes]
) -> None:
    net = _network(bundle)
    edges = {e["id"]: e for e in net["edges"]}
    _, airways = table(package, AIRWAYS_PATH)
    for r in airways:
        e = edges[r["edgeId"]]
        cs = e["crossSection"]
        assert float(r["lengthM"]) == e["length"]
        assert float(r["widthM"]) == cs["width"] and float(r["heightM"]) == cs["height"]
        assert r["shape"] == cs["shape"] and r["orientation"] == e["orientation"]
        assert r["sourceNodeId"] == e["sourceNodeId"] and r["targetNodeId"] == e["targetNodeId"]
    shafts = [r for r in airways if r["edgeType"] == "SHAFT"]
    assert shafts
    assert all(r["shape"] == "CIRCULAR" and r["orientation"] == "VERTICAL" for r in shafts)
    assert all(r["levelId"] == "" for r in shafts)
    assert all(r["levelId"] == "L01" for r in airways if r["edgeType"] in ("DRIFT", "CROSSCUT"))


def test_v5_no_ventilation_physics_is_invented(package: dict[str, bytes]) -> None:
    header, _ = table(package, AIRWAYS_PATH)
    for column in header:
        assert not any(w in column.lower() for w in PHYSICS_WORDS), column
    m = manifest(package)
    kinds = {a["kind"]: a for a in m["assumptions"]}
    assert set(kinds) == {k for k, _ in NOT_PROVIDED_PROPERTIES}
    for a in kinds.values():
        assert a["state"] == "NOT_PROVIDED" and a["value"] is None and a["unit"] is None
    assert m["coordinateMapping"]["transform"] is None
    assert m["coordinateMapping"]["unitFactor"] == 1.0 and m["coordinateMapping"]["upAxis"] == "Z"
    readme = package["README.txt"].decode()
    assert "NOT PROVIDED" in readme and "not a ventilation model" in readme
    assert "no official" in readme and "automated attribute import" in readme
    assert ".vsm" in readme


def test_v6_source_states_are_the_five_state_contract(package: dict[str, bytes]) -> None:
    states = {s["group"]: s for s in manifest(package)["sourceStates"]}
    assert states["EXCAVATIONS"]["state"] == "AVAILABLE"
    assert states["NETWORK"]["state"] == "AVAILABLE"
    assert states["SHAFTS"]["state"] == "AVAILABLE"
    assert states["TIMELINE"]["state"] == "UNSUPPORTED_BY_ADAPTER"
    assert states["CAPABILITY"]["state"] == "UNSUPPORTED_BY_ADAPTER"
    assert states["STOPES"]["state"] == "ARTIFACT_ABSENT"
    assert states["STOPES"]["bundleReasonCode"] == "ARTIFACT_ABSENT"
    assert states["FIELD_LATTICE"]["state"] == "NOT_EXPORTED_BY_VERSION"
    assert states["FIELD_LATTICE"]["bundleReasonCode"] == "NOT_IN_V1"


def test_v7_detached_end_point_is_a_typed_conversion_refusal_never_a_snap(bundle: bytes) -> None:
    def move_node(net: dict[str, Any]) -> None:
        node = next(n for n in net["nodes"] if n["id"] == "LEVEL_ENTRY:L01")
        node["position"][2] += 0.01  # 1 cm above the weld tolerance

    with pytest.raises(AdapterConversionFailedError, match="end points") as exc:
        build_package("VENTSIM", edited_network(bundle, move_node))
    assert exc.value.code == "ADAPTER_CONVERSION_FAILED"
    assert exc.value.source_group == "NETWORK" and exc.value.subject == "RAMP:S01"
    assert "never snapped" in exc.value.detail


def test_v8_declared_length_disagreeing_with_the_polyline_is_refused(bundle: bytes) -> None:
    def stretch(net: dict[str, Any]) -> None:
        net["edges"][0]["length"] += 1.0

    with pytest.raises(MineExchangeBundleInvalidError, match="declared length") as exc:
        build_package("VENTSIM", edited_network(bundle, stretch))
    assert exc.value.subject == "RAMP:S01"


def test_v9_missing_required_groups_are_typed(mine: SyntheticMine) -> None:
    no_network = synthetic_bundle(mine, with_timeline=False, network=None)
    with pytest.raises(RequiredSourceAbsentError) as absent:
        build_package("VENTSIM", no_network)
    assert absent.value.source_group == "NETWORK" and absent.value.adapter == "VENTSIM"
    failed = {**consistent_network(), "status": "FAILED", "failureReason": "network failed"}
    with pytest.raises(RequiredSourceNotSuccessError) as bad:
        build_package(
            "VENTSIM",
            synthetic_bundle(
                mine, with_timeline=False, network=ArtifactInput(failed, "r-net-failed")
            ),
        )
    assert bad.value.code == "ADAPTER_SOURCE_NOT_SUCCESS" and "network failed" in bad.value.detail
    world_only = synthetic_bundle(
        mine,
        with_timeline=False,
        ramp=None,
        ramp_artifact=None,
        levels=None,
        shafts=None,
        network=None,
        capability=None,
    )
    with pytest.raises(RequiredSourceAbsentError) as excav:
        build_package("VENTSIM", world_only)
    assert excav.value.source_group == "EXCAVATIONS"


def test_v10_polyline_vertices_match_the_bundle_centerlines_exactly(
    bundle: bytes, package: dict[str, bytes]
) -> None:
    """The airway vertexCount is the authoritative point count (no
    simplification) and the DXF polyline count equals the entity count."""
    _, rows = table({"c": bundle_files(bundle)["excavations/centerlines.csv"]}, "c")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["entityId"]] = counts.get(r["entityId"], 0) + 1
    _, airways = table(package, AIRWAYS_PATH)
    for a in airways:
        assert int(a["vertexCount"]) == counts[a["geometryEntityId"]], a["edgeId"]
    m = manifest(package)
    assert m["details"]["dxfPolylineCount"] == len(counts)
    assert m["details"]["maxEndpointWeldM"] <= 1e-4
    assert np.isfinite(m["details"]["maxEndpointWeldM"])


def test_v11_deterministic(bundle: bytes) -> None:
    assert build_package("VENTSIM", bundle).zip_bytes == build_package("VENTSIM", bundle).zip_bytes
