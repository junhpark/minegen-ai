"""Phase 23B adapters over the REAL design chains (directive §65–§68, e2e).

Longhole (layout-v2 → tunnel → levels → development mesh → production →
network → capability → timeline), Cut & Fill and Room & Pillar (layout →
levels → production → network → timeline). Every package is requested
through the API, built from the scenario's live MineExchange bundle, and
checked against that bundle's own files — never against ``derived/*``.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from minegen.adapters.engine.glb import ROOT_NODE_NAME, add_root_transform, split_glb
from tests.adapter_support import table
from tests.test_analysis_api import _full_stack
from tests.test_exchange_bundle import TabularStack, export
from tests.test_exchange_mining_method import _post


def _longhole_chain(root: Path) -> TabularStack:
    stack = TabularStack(root)
    stack.build_layout_chain()
    c = stack.client
    prod = _post(c, f"/api/v1/scenarios/{stack.sid}/design/production")
    assert prod["status"] == "SUCCESS", prod.get("failureReason")
    tl = _post(c, f"/api/v1/scenarios/{stack.sid}/design/timeline")
    assert tl["status"] == "SUCCESS", tl.get("failureReason")
    return stack


@pytest.fixture(scope="module")
def longhole(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TabularStack]:
    stack = _longhole_chain(tmp_path_factory.mktemp("adapters-longhole"))
    yield stack
    stack.close()


@pytest.fixture(scope="module")
def cut_fill(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TabularStack]:
    stack = _full_stack(tmp_path_factory.mktemp("adapters-cut-fill"), "CUT_AND_FILL")
    yield stack
    stack.close()


@pytest.fixture(scope="module")
def room_pillar(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TabularStack]:
    stack = _full_stack(
        tmp_path_factory.mktemp("adapters-room-pillar"),
        "ROOM_AND_PILLAR",
        {"kind": "ROOM_AND_PILLAR", "roomWidthM": 12.0, "pillarWidthM": 8.0, "benchCount": 1},
    )
    yield stack
    stack.close()


class Package:
    def __init__(self, data: bytes, target: str) -> None:
        self.data = data
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            root = f"{target.lower()}_package/"
            assert all(n.startswith(root) for n in names), names[:3]
            self.files = {n[len(root) :]: zf.read(n) for n in names}
        self.manifest: dict[str, Any] = json.loads(self.files["adapter_manifest.json"])

    def table(self, path: str) -> list[dict[str, str]]:
        return table(self.files, path)[1]

    def json(self, path: str) -> Any:
        return json.loads(self.files[path])


def _package(client: TestClient, sid: str, target: str) -> Package:
    r = client.post(f"/api/v1/scenarios/{sid}/export/{target.lower()}")
    assert r.status_code == 200, r.text
    assert r.headers["x-adapter-name"] == target
    return Package(r.content, target)


def _refused(client: TestClient, sid: str, target: str, code: str) -> str:
    r = client.post(f"/api/v1/scenarios/{sid}/export/{target.lower()}")
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == code, r.text
    return str(r.json()["detail"]["message"])


def _scenario_state(stack: TabularStack) -> dict[str, tuple[int, int, str]]:
    root = Path(stack.store.root) / stack.sid
    return {
        str(p.relative_to(root)): (
            p.stat().st_size,
            p.stat().st_mtime_ns,
            hashlib.sha256(p.read_bytes()).hexdigest(),
        )
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# --------------------------------------------------------------------------- #
# Ventsim on the real Longhole chain
# --------------------------------------------------------------------------- #


def test_e2e_ventsim_seed_over_the_real_chain(longhole: TabularStack) -> None:
    b = export(longhole.client, longhole.sid)
    pkg = _package(longhole.client, longhole.sid, "VENTSIM")
    assert pkg.files["geometry/mine_centerlines.dxf"] == b.entries["excavations/centerlines.dxf"]
    net = b.json("topology/network.json")
    with_geometry = [e for e in net["edges"] if e["geometryEntityId"] is not None]
    airways = pkg.table("network/airways.csv")
    assert [a["edgeId"] for a in airways] == [e["id"] for e in with_geometry]
    assert {a["edgeType"] for a in airways} == {"RAMP", "LEVEL_ACCESS", "DRIFT", "CROSSCUT"}
    handles = {
        row["entityId"]: row["handle"]
        for row in b.files["excavations/centerlines.dxf"]["dxfEntities"]
    }
    for a in airways:
        assert a["dxfHandle"] == handles[a["geometryEntityId"]]
        assert float(a["widthM"]) > 0 and float(a["heightM"]) > 0 and a["shape"]
    m = pkg.manifest
    assert m["details"]["airwayCount"] == len(with_geometry)
    assert m["details"]["maxEndpointWeldM"] <= 1e-4
    assert m["omissions"] == []  # no RAISE in the real chain: nothing omitted
    states = {s["group"]: s["state"] for s in m["sourceStates"]}
    assert states["EXCAVATIONS"] == "AVAILABLE" and states["NETWORK"] == "AVAILABLE"
    assert states["SHAFTS"] == "ARTIFACT_ABSENT" and states["TIMELINE"] == "UNSUPPORTED_BY_ADAPTER"
    assert states["STOPES"] == "UNSUPPORTED_BY_ADAPTER"
    assert _package(longhole.client, longhole.sid, "VENTSIM").data == pkg.data


# --------------------------------------------------------------------------- #
# AnyLogic on the three methods
# --------------------------------------------------------------------------- #


def _anylogic_integrity(pkg: Package, b: Any) -> None:
    edges = {e["edgeId"] for e in pkg.table("data/edges.csv")}
    units = {u["entityId"]: u for u in pkg.table("data/production_units.csv")}
    tasks = pkg.table("data/tasks.csv")
    tl = b.json("operations/timeline.json")
    assert len(tasks) == len(tl["tasks"])
    for t in tasks:
        if t["targetReferenceKind"] == "NETWORK_EDGE":
            assert t["targetReferenceId"] in edges, t["taskId"]
        else:
            assert t["targetReferenceKind"] == "ENTITY"
            u = units[t["targetReferenceId"]]
            assert u["retained"] == "false", t["taskId"]  # a pillar is never a target
    for s in pkg.table("data/production_states.csv"):
        assert s["entityId"] in units
    progress = pkg.table("data/development_progress.csv")
    assert {p["edgeId"] for p in progress} <= edges
    assert len(progress) == len(tl["developments"])
    assert pkg.table("templates/simulation_inputs.csv") == [
        dict.fromkeys(pkg.table("templates/simulation_inputs.csv")[0], "")
    ]


def test_e2e_anylogic_longhole_stopes(longhole: TabularStack) -> None:
    b = export(longhole.client, longhole.sid)
    pkg = _package(longhole.client, longhole.sid, "ANYLOGIC")
    _anylogic_integrity(pkg, b)
    stopes = b.json("production/stopes.json")["stopes"]
    units = pkg.table("data/production_units.csv")
    assert [u["entityId"] for u in units] == [s["entityId"] for s in stopes]
    for u, s in zip(units, stopes, strict=True):
        assert u["productionKind"] == "STOPE" and float(u["plannedTonnes"]) == s["tonnes"]
        assert u["levelId"] == s["lowerLevelId"] and u["retained"] == "false"
    assert pkg.manifest["details"]["productionKind"] == "STOPES"
    assert pkg.manifest["details"]["miningMethod"] == "LONGHOLE_OPEN_STOPING"
    targets = {t["targetReferenceId"] for t in pkg.table("data/tasks.csv")}
    assert {s["entityId"] for s in stopes} <= targets


def test_e2e_anylogic_cut_fill_backfill_is_never_tonnes(cut_fill: TabularStack) -> None:
    b = export(cut_fill.client, cut_fill.sid)
    pkg = _package(cut_fill.client, cut_fill.sid, "ANYLOGIC")
    _anylogic_integrity(pkg, b)
    cf = b.json("production/cut_fill.json")
    units = {u["entityId"]: u for u in pkg.table("data/production_units.csv")}
    cuts = {c["entityId"]: c for c in cf["cuts"]}
    for bf in cf["backfills"]:
        u = units[bf["entityId"]]
        assert u["productionKind"] == "BACKFILL" and u["backfill"] == "true"
        assert u["plannedTonnes"] == "" and u["parentEntityId"] == bf["sourceCutEntityId"]
        assert float(u["geometricVolumeM3"]) == bf["volumeM3"]
        # 1.3.1: the cemented sill-mat flag travels with the backfill row
        assert u["cemented"] == ("true" if bf["cemented"] else "false")
    for c in cuts.values():
        u = units[c["entityId"]]
        assert u["productionKind"] == "CUT" and float(u["plannedTonnes"]) == c["tonnes"]
        assert u["cemented"] == ""  # only a backfill row carries the flag
    d = pkg.manifest["details"]
    assert d["productionKind"] == "CUT_FILL" and d["backfillRecordCount"] == len(cf["backfills"])
    assert d["cementedBackfillCount"] == sum(1 for bf in cf["backfills"] if bf["cemented"]) > 0
    # rib pillars (none at the default width) would be PILLAR rows, retained
    assert d["retainedPillarCount"] == len(cf["ribPillars"]) == 0
    # BACKFILL / CURE tasks target the CUT, never the backfill record
    for t in pkg.table("data/tasks.csv"):
        if t["taskType"] in ("BACKFILL", "CURE"):
            assert t["targetReferenceId"] in cuts


def test_e2e_anylogic_room_pillar_pillars_are_retained(room_pillar: TabularStack) -> None:
    b = export(room_pillar.client, room_pillar.sid)
    pkg = _package(room_pillar.client, room_pillar.sid, "ANYLOGIC")
    _anylogic_integrity(pkg, b)
    rp = b.json("production/room_pillar.json")
    units = {u["entityId"]: u for u in pkg.table("data/production_units.csv")}
    for p in rp["pillars"]:
        u = units[p["entityId"]]
        assert u["productionKind"] == "PILLAR" and u["retained"] == "true"
        assert u["plannedTonnes"] == "" and float(u["geometricVolumeM3"]) == p["geometricVolumeM3"]
        assert u["cemented"] == ""
    rooms = {r["entityId"] for r in rp["rooms"]}
    for x in rp["extractionUnits"]:
        u = units[x["entityId"]]
        assert u["productionKind"] == "BENCH" and u["parentEntityId"] in rooms
        assert float(u["plannedTonnes"]) == x["tonnes"]
    d = pkg.manifest["details"]
    assert d["retainedPillarCount"] == len(rp["pillars"]) and d["productionKind"] == "ROOM_PILLAR"
    targets = {t["targetReferenceId"] for t in pkg.table("data/tasks.csv")}
    assert not ({p["entityId"] for p in rp["pillars"]} & targets)


# --------------------------------------------------------------------------- #
# Unity / Unreal on the real chain: both render GLBs re-framed exactly once
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("target", ["UNITY", "UNREAL"])
def test_e2e_engine_package_reframes_render_glbs_once(longhole: TabularStack, target: str) -> None:
    b = export(longhole.client, longhole.sid)
    pkg = _package(longhole.client, longhole.sid, target)
    glbs = {f["path"]: f for f in b.manifest["files"] if f["mediaType"] == "model/gltf-binary"}
    render = [p for p, f in glbs.items() if f["semanticType"] == "EXCAVATION_RENDER_SURFACE"]
    assert sorted(render) == ["excavations/render/development.glb", "excavations/render/tunnel.glb"]
    facts = {a["sourceFile"]: a for a in pkg.json("scene/import_settings.json")["assets"]}
    assert set(facts) == set(glbs)
    for path, f in glbs.items():
        asset = pkg.files[f"scene/assets/{path.replace('/', '_')}"]
        src = b.entries[path]
        if path in render:
            assert (
                f["glb"]["sceneFrame"] == "LOCAL_ENU_Z_UP" and f["glb"]["transformMatrix"] is None
            )
            assert asset == add_root_transform(src)
            assert split_glb(asset)[1] == split_glb(src)[1]  # binary chunk byte-identical
            assert (
                sum(1 for n in split_glb(asset)[0]["nodes"] if n.get("name") == ROOT_NODE_NAME) == 1
            )
            assert facts[path]["rootTransformAdded"] is True
        else:
            assert f["glb"]["sceneFrame"] == "GLTF_Y_UP"
            assert asset == src
            assert facts[path]["rootTransformAdded"] is False
    d = pkg.manifest["details"]
    assert d["rootTransformsAdded"] == 2 and d["assetsAlreadyYUp"] == len(glbs) - 2
    entities = {e["entityId"]: e for e in pkg.json("scene/entities.json")["entities"]}
    assert entities["ramp:main"]["assetPath"] == "scene/assets/excavations_render_tunnel.glb"
    net = b.json("topology/network.json")
    for e in net["edges"]:
        if e["geometryEntityId"]:
            assert e["id"] in entities[e["geometryEntityId"]]["networkEdgeIds"]
    assert pkg.files["scene/network.json"] == b.entries["topology/network.json"]
    assert pkg.files["scene/timeline.json"] == b.entries["operations/timeline.json"]
    assert pkg.files["scene/capability.json"] == b.entries["semantics/capability.json"]
    states = {s["group"]: s["state"] for s in pkg.manifest["sourceStates"]}
    assert states["RENDER_GLB"] == "AVAILABLE" and states["TIMELINE"] == "AVAILABLE"
    assert states["STOPES"] == "AVAILABLE"
    assert _package(longhole.client, longhole.sid, target).data == pkg.data


# --------------------------------------------------------------------------- #
# read-only + no generation, every target
# --------------------------------------------------------------------------- #


def test_e2e_every_export_is_read_only_and_generates_nothing(longhole: TabularStack) -> None:
    before = _scenario_state(longhole)
    for target in ("VENTSIM", "ANYLOGIC", "UNITY", "UNREAL"):
        _package(longhole.client, longhole.sid, target)
    assert _scenario_state(longhole) == before
    assert not list(Path(longhole.store.root).rglob("*.zip"))


def test_e2e_partial_chain_refusals_are_typed(cut_fill: TabularStack) -> None:
    """The Cut & Fill stack has no tunnel mesh / capability graph: the engine
    package is partial (no capability document, render GLB absent) while the
    Ventsim and AnyLogic packages still build from the network + timeline."""
    pkg = _package(cut_fill.client, cut_fill.sid, "UNITY")
    states = {s["group"]: s for s in pkg.manifest["sourceStates"]}
    assert states["RENDER_GLB"]["state"] == "ARTIFACT_ABSENT"
    assert states["CAPABILITY"]["state"] == "ARTIFACT_ABSENT"
    assert "scene/capability.json" not in pkg.files
    assert pkg.manifest["details"]["timelineIncluded"] is True
    v = _package(cut_fill.client, cut_fill.sid, "VENTSIM")
    assert v.manifest["details"]["airwayCount"] > 0


# --------------------------------------------------------------------------- #
# B1: production group provenance per method — active group only
# --------------------------------------------------------------------------- #

PRODUCTION_GROUPS = ("STOPES", "CUT_FILL", "ROOM_PILLAR")


def _production_states(pkg: Package) -> dict[str, str]:
    states = pkg.manifest["sourceStates"]
    return {s["group"]: s["state"] for s in states if s["group"] in PRODUCTION_GROUPS}


@pytest.mark.parametrize(
    ("stack_name", "active"),
    [("longhole", "STOPES"), ("cut_fill", "CUT_FILL"), ("room_pillar", "ROOM_PILLAR")],
)
def test_e2e_only_the_active_production_group_is_a_source(
    request: pytest.FixtureRequest, stack_name: str, active: str
) -> None:
    stack: TabularStack = request.getfixturevalue(stack_name)
    b = export(stack.client, stack.sid)
    listed = {o["group"] for o in b.manifest["omissions"]} | {
        f"{g}" for g in PRODUCTION_GROUPS if f"production/{g.lower()}.json" in b.entries
    }
    assert set(PRODUCTION_GROUPS) & listed == {active}  # the bundle itself lists ONE group
    for target, expected in (
        ("VENTSIM", "UNSUPPORTED_BY_ADAPTER"),
        ("ANYLOGIC", "AVAILABLE"),
        ("UNITY", "AVAILABLE"),
        ("UNREAL", "AVAILABLE"),
    ):
        states = _production_states(_package(stack.client, stack.sid, target))
        assert states == {active: expected}, (target, states)
