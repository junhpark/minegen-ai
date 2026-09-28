"""Phase 23B.1 — Ventsim geometry / network SEED adapter.

FAST, adapter-level: a small synthetic world plus hand-written owning
artifacts (two straight ramp segments, a two-piece drift, one crosscut, a
two-segment shaft with one station drive, one RAISE edge without geometry)
are exported through the REAL MineExchange exporter (``build_exchange`` /
``write_bundle``) and the resulting ZIP BYTES are handed to the adapter —
exactly the boundary an offline user has. The API refusals ride the FAST
world-only scenario. The real LAYOUT_V2 chain is covered by
``test_exchange_bundle.py::test_v1_ventsim_seed_over_the_real_layout_v2_chain``
(e2e).

Contract under test (docs/external-adapters.md §4–§11):
- V1 one 3-D DXF POLYLINE per network edge, layer = edge type, deterministic
  handle ↔ edge id identity, shared end vertices at every topology node
- V2 the authoritative polyline is delivered verbatim at tolerance 0 and
  Douglas-Peucker simplified (end points kept, deviation ≤ tolerance) at the
  documented default 0.5 m, which the report records as
  ADAPTER_DEFAULT_EXPLICIT with userOverride
- V3 the attribute table carries the bundle's authoritative length and
  cross-section (width / height / shape); no ventilation number anywhere
- V4 four-state source mapping; every Ventsim-only property NOT_PROVIDED
- V5 RAISE (no owning centerline) is a typed omission, never invented
- V6 explicit origin offset translates every coordinate and is recorded
- V7 typed refusals: REQUIRED_SOURCE_ABSENT (world-only), bundle integrity,
  version range, end point weld, length consistency, config validation
- V8 determinism: same bundle + config → identical bytes; no wall-clock
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from minegen.adapters.bundle_reader import read_mine_exchange_bundle
from minegen.adapters.errors import (
    AdapterConversionFailedError,
    MineExchangeBundleInvalidError,
    MineExchangeVersionUnsupportedError,
    RequiredSourceAbsentError,
)
from minegen.adapters.polyline import polyline_length, simplify_polyline
from minegen.adapters.ventsim import ADAPTER_NAME, ADAPTER_VERSION, VentsimSeedConfig
from minegen.adapters.ventsim.config import DEFAULT_SIMPLIFICATION_TOLERANCE_M
from minegen.adapters.ventsim.seed import (
    ENDPOINT_WELD_TOLERANCE_M,
    NOT_PROVIDED_PROPERTIES,
    PACKAGE_ROOT,
    build_ventsim_seed,
    build_ventsim_seed_from_bundle_bytes,
)
from minegen.core.artifacts import LEGACY_RAMP_ARTIFACT, LEVELS_ARTIFACT, SHAFTS_ARTIFACT
from minegen.exchange.builder import ArtifactInput, build_exchange
from minegen.exchange.bundle import BUNDLE_ROOT, write_bundle
from minegen.exchange.formats.csv_table import read_csv
from minegen.exchange.formats.dxf import read_dxf_entities
from tests.test_exchange_corrections import SyntheticMine, levels_doc, ramp_doc, shafts_doc
from tests.test_world_api import _create

SEED = "/export/ventsim-seed"
ROOT = f"{PACKAGE_ROOT}/"


# --------------------------------------------------------------------------- #
# a TOPOLOGICALLY CONSISTENT synthetic network (nodes at the polyline ends)
# --------------------------------------------------------------------------- #


def _pts(flat: list[float]) -> np.ndarray:
    return np.asarray(flat, dtype=np.float64).reshape(-1, 3)


def _node(node_id: str, node_type: str, pos: np.ndarray, level: str | None) -> dict[str, Any]:
    return {"id": node_id, "type": node_type, "position": [float(v) for v in pos], "levelId": level}


def _edge(
    edge_id: str,
    edge_type: str,
    artifact: str | None,
    index: int | None,
    a: str,
    b: str,
    points: np.ndarray | None,
    *,
    orientation: str = "DEVELOPMENT",
    cross_section: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if cross_section is None:
        cross_section = {"width": 5.0, "height": 5.5, "analyticArea": 24.0, "shape": "HORSESHOE"}
    return {
        "id": edge_id,
        "type": edge_type,
        "fromNode": a,
        "toNode": b,
        "geometryRef": None if artifact is None else {"artifact": artifact, "segmentIndex": index},
        "length3d": polyline_length(points) if points is not None else 12.0,
        "orientation": orientation,
        "crossSection": cross_section,
    }


def consistent_network() -> dict[str, Any]:
    ramp = [_pts(s["effectiveCenterline"]["points"]) for s in ramp_doc()["segments"]]
    devs = [_pts(d["centerline"]["points"]) for d in levels_doc()["developments"]]
    shafts = [_pts(c["centerline"]["points"]) for c in shafts_doc()["centerlines"]]
    circular = {"width": 5.0, "height": 5.0, "analyticArea": 19.6, "shape": "CIRCULAR"}
    nodes = [
        _node("PORTAL", "PORTAL", ramp[0][0], None),
        _node("LEVEL_ENTRY:L01", "LEVEL_ENTRY", ramp[0][-1], "L01"),
        _node("LEVEL_ENTRY:L02", "LEVEL_ENTRY", ramp[1][-1], "L02"),
        _node("JUNCTION:L01:A", "JUNCTION", devs[0][0], "L01"),
        _node("JUNCTION:L01:B", "JUNCTION", devs[0][-1], "L01"),
        _node("JUNCTION:L01:C", "JUNCTION", devs[1][-1], "L01"),
        _node("JUNCTION:L01:S+00", "JUNCTION", devs[2][0], "L01"),
        _node("STOPE_ACCESS:L01:S+00", "STOPE_ACCESS", devs[2][-1], "L01"),
        _node("SHAFT_COLLAR:SHAFT-01", "SHAFT_COLLAR", shafts[0][0], None),
        _node("SHAFT_STATION:SHAFT-01:L01", "SHAFT_STATION", shafts[0][-1], "L01"),
        _node("SHAFT_BOTTOM:SHAFT-01", "SHAFT_BOTTOM", shafts[1][-1], None),
    ]
    edges = [
        _edge("RAMP:S01", "RAMP", LEGACY_RAMP_ARTIFACT, 0, "PORTAL", "LEVEL_ENTRY:L01", ramp[0]),
        _edge(
            "RAMP:S02",
            "RAMP",
            LEGACY_RAMP_ARTIFACT,
            1,
            "LEVEL_ENTRY:L01",
            "LEVEL_ENTRY:L02",
            ramp[1],
        ),
        _edge(
            "DRIFT:L01:00", "DRIFT", LEVELS_ARTIFACT, 0, "JUNCTION:L01:A", "JUNCTION:L01:B", devs[0]
        ),
        _edge(
            "DRIFT:L01:01", "DRIFT", LEVELS_ARTIFACT, 1, "JUNCTION:L01:B", "JUNCTION:L01:C", devs[1]
        ),
        _edge(
            "CROSSCUT:L01:S+00",
            "CROSSCUT",
            LEVELS_ARTIFACT,
            2,
            "JUNCTION:L01:S+00",
            "STOPE_ACCESS:L01:S+00",
            devs[2],
        ),
        _edge(
            "SHAFT:SHAFT-01:SEG00",
            "SHAFT",
            SHAFTS_ARTIFACT,
            0,
            "SHAFT_COLLAR:SHAFT-01",
            "SHAFT_STATION:SHAFT-01:L01",
            shafts[0],
            orientation="VERTICAL",
            cross_section=circular,
        ),
        _edge(
            "SHAFT:SHAFT-01:SEG01",
            "SHAFT",
            SHAFTS_ARTIFACT,
            1,
            "SHAFT_STATION:SHAFT-01:L01",
            "SHAFT_BOTTOM:SHAFT-01",
            shafts[1],
            orientation="VERTICAL",
            cross_section=circular,
        ),
        _edge(
            "SHAFT_STATION_ACCESS:SHAFT-01:L01",
            "SHAFT_STATION_ACCESS",
            SHAFTS_ARTIFACT,
            2,
            "SHAFT_STATION:SHAFT-01:L01",
            "STOPE_ACCESS:L01:S+00",
            shafts[2],
        ),
        # the ONE edge type without an owning centerline (rule 184)
        _edge("RAISE:L01:X", "RAISE", None, None, "JUNCTION:L01:C", "LEVEL_ENTRY:L02", None),
    ]
    return {"status": "SUCCESS", "failureReason": None, "nodes": nodes, "edges": edges}


def bundle_bytes(mine: SyntheticMine, **overrides: Any) -> bytes:
    inputs = mine.inputs(network=ArtifactInput(consistent_network(), "r-net"), **overrides)
    data, _ = write_bundle(build_exchange(inputs))
    return data


class Package:
    def __init__(self, data: bytes) -> None:
        self.data = data
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            assert all(n.startswith(ROOT) for n in names), names
            self.files: dict[str, bytes] = {n[len(ROOT) :]: zf.read(n) for n in names}
        self.report: dict[str, Any] = json.loads(self.files["adapter_report.json"])
        self.identity: dict[str, Any] = json.loads(self.files["identity_map.json"])

    def table(self, path: str) -> list[dict[str, str]]:
        header, rows = read_csv(self.files[path].decode("utf-8"))
        return [dict(zip(header, r, strict=True)) for r in rows]

    def dxf(self) -> list[dict[str, Any]]:
        return read_dxf_entities(self.files["airways.dxf"].decode("ascii"))


@pytest.fixture(scope="module")
def mine() -> SyntheticMine:
    return SyntheticMine()


@pytest.fixture(scope="module")
def bundle(mine: SyntheticMine) -> bytes:
    return bundle_bytes(mine)


@pytest.fixture(scope="module")
def faithful(bundle: bytes) -> Package:
    cfg = VentsimSeedConfig(simplification_tolerance_m=0.0)
    return Package(build_ventsim_seed_from_bundle_bytes(bundle, cfg).zip_bytes)


@pytest.fixture(scope="module")
def default_seed(bundle: bytes) -> Package:
    return Package(build_ventsim_seed_from_bundle_bytes(bundle).zip_bytes)


def _centerline_points(bundle: bytes) -> dict[str, np.ndarray]:
    b = read_mine_exchange_bundle(bundle)
    _header, rows = read_csv(b.text("excavations/centerlines.csv"))
    out: dict[str, list[list[float]]] = {}
    for r in rows:
        out.setdefault(r[0], []).append([float(r[4]), float(r[5]), float(r[6])])
    return {k: np.asarray(v) for k, v in out.items()}


# --------------------------------------------------------------------------- #
# V1 / V8 — package structure, identity, shared end vertices, determinism
# --------------------------------------------------------------------------- #


def test_v1_v8_package_structure_identity_and_determinism(bundle: bytes, faithful: Package) -> None:
    assert set(faithful.files) == {
        "airways.dxf",
        "airways.csv",
        "nodes.csv",
        "identity_map.json",
        "adapter_report.json",
        "README.txt",
    }
    r = faithful.report
    assert r["adapterName"] == ADAPTER_NAME == "VENTSIM_SEED"
    assert r["adapterVersion"] == ADAPTER_VERSION and r["targetApplication"] == "VENTSIM"
    assert r["supportedMineExchangeVersions"] == ">=1.2.0,<2.0.0"
    assert r["sourceMineExchangeVersion"] == "1.2.0"
    assert r["sourceSnapshot"]["scenarioRevision"] == "s1"
    assert r["identityMapFile"] == "identity_map.json"
    # every generated file (except the report) is hashed
    listed = {f["path"]: f["sha256"] for f in r["generatedFiles"]}
    assert set(listed) == set(faithful.files) - {"adapter_report.json"}
    import hashlib

    for path, digest in listed.items():
        assert hashlib.sha256(faithful.files[path]).hexdigest() == digest, path
    # no wall-clock value anywhere in the semantic files
    text = faithful.files["adapter_report.json"].decode() + faithful.files["README.txt"].decode()
    assert "generatedAt" not in text and "/home/" not in text
    # V8 determinism
    cfg = VentsimSeedConfig(simplification_tolerance_m=0.0)
    assert build_ventsim_seed_from_bundle_bytes(bundle, cfg).zip_bytes == faithful.data

    # V1: one POLYLINE per network edge WITH geometry (8 of 9 edges; LEGACY has
    # no level access)
    net = read_mine_exchange_bundle(bundle).json("topology/network.json")
    with_geometry = [e for e in net["edges"] if e["geometryEntityId"] is not None]
    assert len(with_geometry) == 8 and len(net["edges"]) == 9
    entities = faithful.dxf()
    assert [e["type"] for e in entities] == ["POLYLINE"] * 8
    handles = {a["dxfHandle"]: a for a in faithful.identity["airways"]}
    assert len(handles) == 8
    nodes = {n["id"]: np.asarray(n["position"]) for n in net["nodes"]}
    edges = {e["id"]: e for e in with_geometry}
    for ent in entities:
        m = handles[ent["handle"]]
        e = edges[m["airwayId"]]
        assert ent["layer"] == e["type"] == m["layer"]
        assert m["bundleEntityId"] == e["geometryEntityId"]
        # shared end vertices: the polyline starts / ends ON its topology nodes
        np.testing.assert_allclose(ent["points"][0], nodes[e["sourceNodeId"]], atol=1e-9)
        np.testing.assert_allclose(ent["points"][-1], nodes[e["targetNodeId"]], atol=1e-9)
    assert {ent["layer"] for ent in entities} == {
        "RAMP",
        "DRIFT",
        "CROSSCUT",
        "SHAFT",
        "SHAFT_STATION_ACCESS",
    }
    # nodes table = every network node, offset-free
    rows = faithful.table("nodes.csv")
    assert [r["nodeId"] for r in rows] == [n["id"] for n in net["nodes"]]
    assert {r["surface"] for r in rows} == {"true", "false"}
    assert sum(r["surface"] == "true" for r in rows) == 2  # PORTAL + SHAFT_COLLAR


# --------------------------------------------------------------------------- #
# V2 — faithful vs simplified, recorded as an explicit assumption
# --------------------------------------------------------------------------- #


def test_v2_tolerance_zero_delivers_the_authoritative_polyline_verbatim(
    bundle: bytes, faithful: Package
) -> None:
    csv_pts = _centerline_points(bundle)
    handles = {a["dxfHandle"]: a for a in faithful.identity["airways"]}
    for ent in faithful.dxf():
        entity_id = handles[ent["handle"]]["bundleEntityId"]
        np.testing.assert_array_equal(ent["points"], csv_pts[entity_id])
    m = faithful.report["airwayMetrics"]
    assert m["vertexCountDelivered"] == m["vertexCountAuthoritative"]
    assert m["maxLengthDeviationM"] == 0.0 and m["maxSimplificationDeviationM"] == 0.0
    assert faithful.report["effectiveSimplificationToleranceM"] == 0.0
    a = next(x for x in faithful.report["assumptions"] if x["kind"] == "SIMPLIFICATION_TOLERANCE")
    assert a["state"] == "ADAPTER_DEFAULT_EXPLICIT" and a["value"] == 0.0 and a["userOverride"]


def test_v2_default_simplification_is_documented_and_measured(default_seed: Package) -> None:
    r = default_seed.report
    assert r["config"]["simplificationToleranceM"] is None
    assert r["effectiveSimplificationToleranceM"] == DEFAULT_SIMPLIFICATION_TOLERANCE_M == 0.5
    a = next(x for x in r["assumptions"] if x["kind"] == "SIMPLIFICATION_TOLERANCE")
    assert a["state"] == "ADAPTER_DEFAULT_EXPLICIT" and a["value"] == 0.5 and a["unit"] == "m"
    assert a["userOverride"] is False and "external-adapters.md" in a["source"]
    # straight synthetic developments collapse to their two end points, at
    # zero deviation and zero length change (collinear)
    m = r["airwayMetrics"]
    assert m["vertexCountDelivered"] == 2 * m["airwayCount"] < m["vertexCountAuthoritative"]
    assert m["maxSimplificationDeviationM"] <= 0.5
    assert m["maxLengthDeviationM"] < 1e-9
    for row in default_seed.table("airways.csv"):
        assert row["vertexCountDelivered"] == "2"
        assert float(row["lengthDeviationM"]) < 1e-9


def test_v2_douglas_peucker_keeps_authoritative_points_within_tolerance() -> None:
    t = np.linspace(0.0, 2.0 * np.pi, 400)
    arc = np.c_[30.0 * np.cos(t), 30.0 * np.sin(t), -3.0 * t]  # one spiral turn, 2 m-ish steps
    kept, deviation = simplify_polyline(arc, 0.5)
    assert 2 < kept.shape[0] < arc.shape[0]
    np.testing.assert_array_equal(kept[0], arc[0])
    np.testing.assert_array_equal(kept[-1], arc[-1])
    # every kept vertex IS an authoritative point (no new geometry)
    assert all(any(np.array_equal(k, p) for p in arc) for k in kept)
    assert 0.0 < deviation <= 0.5
    # every removed point lies within the tolerance of the delivered polyline
    from minegen.adapters.polyline import _segment_distances

    for p in arc:
        d = min(
            float(_segment_distances(p[None, :], kept[i], kept[i + 1])[0])
            for i in range(kept.shape[0] - 1)
        )
        assert d <= 0.5 + 1e-12
    same, zero = simplify_polyline(arc, 0.0)
    np.testing.assert_array_equal(same, arc)
    assert zero == 0.0


# --------------------------------------------------------------------------- #
# V3 / V4 — attribute table, source states, NOT_PROVIDED policy
# --------------------------------------------------------------------------- #


def test_v3_attribute_table_carries_bundle_lengths_and_cross_sections(
    bundle: bytes, faithful: Package
) -> None:
    net = read_mine_exchange_bundle(bundle).json("topology/network.json")
    edges = {e["id"]: e for e in net["edges"]}
    rows = faithful.table("airways.csv")
    assert [r["airwayId"] for r in rows] == [
        e["id"] for e in net["edges"] if e["geometryEntityId"] is not None
    ]
    for r in rows:
        e = edges[r["airwayId"]]
        assert float(r["authoritativeLengthM"]) == e["length"]
        assert float(r["deliveredLengthM"]) == pytest.approx(e["length"], abs=1e-9)
        assert float(r["widthM"]) == e["crossSection"]["width"]
        assert float(r["heightM"]) == e["crossSection"]["height"]
        assert r["profileShape"] == e["crossSection"]["shape"]
        assert r["sourceNodeId"] == e["sourceNodeId"] and r["targetNodeId"] == e["targetNodeId"]
        assert r["orientation"] == e["orientation"]
    shaft_rows = [r for r in rows if r["edgeType"] == "SHAFT"]
    assert len(shaft_rows) == 2 and {r["profileShape"] for r in shaft_rows} == {"CIRCULAR"}
    assert {r["orientation"] for r in shaft_rows} == {"VERTICAL"}
    # no ventilation quantity is invented anywhere in the table
    header = set(rows[0])
    assert not any(k.lower().startswith(("resist", "friction", "fan", "airflow")) for k in header)
    assert faithful.report["airwayMetrics"]["airwayCountByType"] == {
        "CROSSCUT": 1,
        "DRIFT": 2,
        "RAMP": 2,
        "SHAFT": 2,
        "SHAFT_STATION_ACCESS": 1,
    }


def test_v4_source_states_and_not_provided_assumptions(faithful: Package) -> None:
    states = {s["group"]: s for s in faithful.report["sourceStates"]}
    assert states["EXCAVATIONS"]["state"] == "AVAILABLE"
    assert states["NETWORK"]["state"] == "AVAILABLE"
    for group in ("TERRAIN", "OREBODY", "FAULTS", "CAPABILITY", "MINING_METHOD", "PRODUCTION"):
        assert states[group]["state"] == "UNSUPPORTED_BY_ADAPTER", group
    assert states["TIMELINE"]["state"] == "ABSENT"
    assert states["TIMELINE"]["bundleReasonCode"] == "NOT_IN_V1"
    assert "SHAFTS" not in states  # shafts are in the bundle → part of NETWORK, no omission
    not_provided = {
        a["kind"] for a in faithful.report["assumptions"] if a["state"] == "NOT_PROVIDED"
    }
    assert not_provided == {kind for kind, _ in NOT_PROVIDED_PROPERTIES}
    assert {"AIRWAY_RESISTANCE", "FANS", "REGULATORS_AND_DOORS", "HEAT_SOURCES"} <= not_provided
    for a in faithful.report["assumptions"]:
        if a["state"] == "NOT_PROVIDED":
            assert a["value"] is None and a["unit"] is None
    assumptions = faithful.report["assumptions"]
    policy = next(a for a in assumptions if a["kind"] == "DIMENSION_DELIVERY_POLICY")
    assert policy["value"] == "ATTRIBUTE_TABLE" and policy["state"] == "ADAPTER_DEFAULT_EXPLICIT"
    cm = faithful.report["coordinateMapping"]
    assert cm["sourceFrame"] == cm["targetFrame"] == "LOCAL_ENU_Z_UP"
    assert cm["unit"] == "metre" and cm["unitFactor"] == 1.0 and cm["translation"] == [0, 0, 0]
    assert "metric" in cm["note"]
    readme = faithful.files["README.txt"].decode()
    assert "not a ventilation model" in readme and "NOT PROVIDED" in readme


# --------------------------------------------------------------------------- #
# V5 / V6 — RAISE omission, origin offset
# --------------------------------------------------------------------------- #


def test_v5_raise_without_owning_centerline_is_a_typed_omission(faithful: Package) -> None:
    om = faithful.report["omissions"]
    assert om == [
        {
            "subject": "edge:RAISE:L01:X",
            "reasonCode": "NO_GEOMETRY_CONTRACT",
            "detail": om[0]["detail"],
        }
    ]
    assert "RAISE" in om[0]["detail"] and "invented" in om[0]["detail"]
    assert not any(a["airwayId"] == "RAISE:L01:X" for a in faithful.identity["airways"])
    assert faithful.report["airwayMetrics"]["airwayCount"] == 8
    assert faithful.report["airwayMetrics"]["nodeCount"] == 11


def test_v6_origin_offset_translates_every_coordinate_and_is_recorded(
    bundle: bytes, faithful: Package
) -> None:
    cfg = VentsimSeedConfig(simplification_tolerance_m=0.0, origin_offset=(1000.0, -250.0, 5.5))
    shifted = Package(build_ventsim_seed_from_bundle_bytes(bundle, cfg).zip_bytes)
    off = np.asarray([1000.0, -250.0, 5.5])
    base = {e["handle"]: e["points"] for e in faithful.dxf()}
    for ent in shifted.dxf():
        np.testing.assert_allclose(ent["points"], base[ent["handle"]] + off, atol=1e-9)
    for a, b in zip(shifted.table("nodes.csv"), faithful.table("nodes.csv"), strict=True):
        assert a["nodeId"] == b["nodeId"]
        np.testing.assert_allclose(
            [float(a["x"]), float(a["y"]), float(a["z"])],
            np.asarray([float(b["x"]), float(b["y"]), float(b["z"])]) + off,
            atol=1e-9,
        )
    for a, b in zip(shifted.identity["nodes"], faithful.identity["nodes"], strict=True):
        np.testing.assert_allclose(a["position"], np.asarray(b["position"]) + off, atol=1e-9)
    assert shifted.report["coordinateMapping"]["translation"] == [1000.0, -250.0, 5.5]
    assert shifted.report["config"]["originOffset"] == [1000.0, -250.0, 5.5]
    # lengths are translation-invariant; the attribute table is unchanged
    assert shifted.files["airways.csv"] == faithful.files["airways.csv"]


# --------------------------------------------------------------------------- #
# V7 — typed refusals
# --------------------------------------------------------------------------- #


def test_v7_world_only_bundle_is_required_source_absent(mine: SyntheticMine) -> None:
    inputs = mine.inputs(ramp=None, levels=None, shafts=None, network=None, capability=None)
    data, _ = write_bundle(build_exchange(inputs))
    with pytest.raises(RequiredSourceAbsentError) as exc:
        build_ventsim_seed_from_bundle_bytes(data)
    assert exc.value.code == "REQUIRED_SOURCE_ABSENT" and "ARTIFACT_ABSENT" in str(exc.value)


def _rezip(data: bytes, mutate: dict[str, bytes]) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        entries = {n: zf.read(n) for n in zf.namelist()}
    for path, content in mutate.items():
        entries[f"{BUNDLE_ROOT}/{path}"] = content
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n in sorted(entries):
            zf.writestr(n, entries[n])
    return buf.getvalue()


def _manifest_of(bundle: bytes) -> dict[str, Any]:
    with zipfile.ZipFile(io.BytesIO(bundle)) as zf:
        doc: dict[str, Any] = json.loads(zf.read(f"{BUNDLE_ROOT}/manifest.json"))
    return doc


def test_v7_bundle_integrity_refusals(bundle: bytes) -> None:
    # a payload byte changed under its manifest hash
    tampered = _rezip(bundle, {"excavations/centerlines.csv": b"entityId,kind\n"})
    with pytest.raises(MineExchangeBundleInvalidError, match="SHA-256"):
        build_ventsim_seed_from_bundle_bytes(tampered)
    # an unlisted entry
    with pytest.raises(MineExchangeBundleInvalidError, match="not listed"):
        build_ventsim_seed_from_bundle_bytes(_rezip(bundle, {"extra.txt": b"x"}))
    # not a ZIP
    with pytest.raises(MineExchangeBundleInvalidError, match="ZIP"):
        build_ventsim_seed_from_bundle_bytes(b"not a zip")
    # a manifest that does not validate against the DTO
    broken = dict(_manifest_of(bundle))
    broken.pop("entities")
    with pytest.raises(MineExchangeBundleInvalidError, match="malformed"):
        build_ventsim_seed_from_bundle_bytes(
            _rezip(bundle, {"manifest.json": json.dumps(broken).encode()})
        )


@pytest.mark.parametrize("version", ["1.1.0", "2.0.0", "0.9.9", "1.2"])
def test_v7_mine_exchange_version_outside_the_supported_range_is_refused(
    bundle: bytes, version: str
) -> None:
    manifest = _manifest_of(bundle)
    manifest["mineExchangeVersion"] = version
    data = _rezip(bundle, {"manifest.json": json.dumps(manifest).encode()})
    with pytest.raises(MineExchangeVersionUnsupportedError) as exc:
        build_ventsim_seed_from_bundle_bytes(data)
    assert exc.value.code == "MINEEXCHANGE_VERSION_UNSUPPORTED"


def test_v7_detached_end_point_and_inconsistent_length_are_refused(mine: SyntheticMine) -> None:
    net = consistent_network()
    net["nodes"][1]["position"][0] += 10.0 * ENDPOINT_WELD_TOLERANCE_M  # LEVEL_ENTRY:L01 moved
    data, _ = write_bundle(build_exchange(mine.inputs(network=ArtifactInput(net, "r-net"))))
    with pytest.raises(AdapterConversionFailedError, match="RAMP:S01") as exc:
        build_ventsim_seed_from_bundle_bytes(data)
    assert exc.value.code == "ADAPTER_CONVERSION_FAILED"
    net = consistent_network()
    net["edges"][2]["length3d"] += 0.5  # DRIFT:L01:00 declares a length its polyline is not
    data, _ = write_bundle(build_exchange(mine.inputs(network=ArtifactInput(net, "r-net"))))
    with pytest.raises(MineExchangeBundleInvalidError, match="DRIFT:L01:00"):
        build_ventsim_seed_from_bundle_bytes(data)


def test_v7_missing_cross_section_is_blank_and_warned_never_invented(mine: SyntheticMine) -> None:
    net = consistent_network()
    net["edges"][0]["crossSection"] = None
    data, _ = write_bundle(build_exchange(mine.inputs(network=ArtifactInput(net, "r-net"))))
    pkg = Package(build_ventsim_seed_from_bundle_bytes(data).zip_bytes)
    row = next(r for r in pkg.table("airways.csv") if r["airwayId"] == "RAMP:S01")
    assert row["widthM"] == "" and row["heightM"] == "" and row["profileShape"] == ""
    assert pkg.report["airwayMetrics"]["airwaysWithoutCrossSection"] == 1
    assert any("RAMP:S01" in w and "NOT_PROVIDED" in w for w in pkg.report["warnings"])


def test_v7_config_is_validated_never_clamped() -> None:
    with pytest.raises(ValueError):
        VentsimSeedConfig(simplification_tolerance_m=-0.1)
    with pytest.raises(ValueError):
        VentsimSeedConfig(simplification_tolerance_m=5.1)
    with pytest.raises(ValueError):
        VentsimSeedConfig(dimension_delivery_policy="SPREADSHEET_IMPORT")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        VentsimSeedConfig(origin_offset=(float("inf"), 0.0, 0.0))


def test_adapter_object_entry_matches_the_bytes_entry(bundle: bytes, faithful: Package) -> None:
    b = read_mine_exchange_bundle(bundle)
    pkg = build_ventsim_seed(b, VentsimSeedConfig(simplification_tolerance_m=0.0))
    assert pkg.zip_bytes == faithful.data
    assert pkg.report.airway_metrics.airway_count == 8


# --------------------------------------------------------------------------- #
# API — refusals on the FAST world-only scenario
# --------------------------------------------------------------------------- #


def test_api_refusals_without_a_world_and_without_a_design(client: TestClient) -> None:
    sid = _create(client)
    r = client.post(f"/api/v1/scenarios/{sid}{SEED}")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "WORLD_NOT_GENERATED"
    assert client.post(f"/api/v1/scenarios/nope{SEED}").status_code == 404
    assert client.post(f"/api/v1/scenarios/{sid}/world/generate").status_code == 200
    r = client.post(f"/api/v1/scenarios/{sid}{SEED}")
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "REQUIRED_SOURCE_ABSENT"
    assert "ARTIFACT_ABSENT" in r.json()["detail"]["message"]
    # an out-of-range explicit parameter is a 422 (validated, never clamped)
    r = client.post(f"/api/v1/scenarios/{sid}{SEED}", json={"simplificationToleranceM": 9.0})
    assert r.status_code == 422, r.text
    r = client.post(f"/api/v1/scenarios/{sid}{SEED}", json={"targetFormat": "VSM"})
    assert r.status_code == 422, r.text
