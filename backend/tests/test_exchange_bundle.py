"""Phase 23A — MineExchange bundle over REAL authoritative artifacts.

Tiers (tests/conftest.py tables):
- FAST: world-only exports (TABULAR small world, ELLIPSOID realized world),
  refusals (no world, no scenario) and the export's read-only contract.
- e2e (``TabularStack``, module-scoped): the real LAYOUT_V2 chain
  (layout-v2 → activate → tunnel → levels → development mesh → network →
  capability graph) exported through the API — O/E/L/N/P/M on real data,
  snapshot-changed / STALE / MALFORMED refusals, and the LEGACY chain.
- slow: WARPED_VEIN-301 on the shared session fixture (builder-level).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from minegen.api.deps import (
    get_design_service,
    get_exchange_service,
    get_infrastructure_service,
    get_job_service,
    get_scenario_store,
    get_world_service,
)
from minegen.core.artifacts import (
    CAPABILITY_GRAPH_ARTIFACT,
    LAYOUT_V2_SELECTED_ARTIFACT,
    LEGACY_RAMP_ARTIFACT,
    LEVEL_ACCESSES_ARTIFACT,
    LEVELS_ARTIFACT,
    NETWORK_ARTIFACT,
)
from minegen.core.enums import ScenarioPreset
from minegen.core.models import Scenario
from minegen.design.constraints import DesignContext
from minegen.design.cost_field import DesignCostEvaluator, clearance_policy_for
from minegen.design.development_mesh import DevelopmentMeshBuilder, specs_from_artifacts
from minegen.design.glb_writer import read_glb
from minegen.design.junctions import find_junctions
from minegen.design.profile import build_profile, secondary_profile
from minegen.exchange.builder import ArtifactInput, ExchangeInputs, build_exchange
from minegen.exchange.bundle import BUNDLE_ROOT, write_bundle
from minegen.exchange.formats.dxf import read_dxf_entities
from minegen.exchange.formats.stl import read_binary_stl
from minegen.exchange.geometry.centerlines import development_entity_id
from minegen.exchange.geometry.qa import MeshQa, mesh_qa
from minegen.exchange.models import MINE_EXCHANGE_VERSION
from minegen.main import create_app
from minegen.services.design_service import DesignService
from minegen.services.exchange_service import ExchangeService
from minegen.services.infrastructure_service import InfrastructureService
from minegen.services.job_service import JobService
from minegen.services.scenario_realizer import realize_scenario
from minegen.services.scenario_service import ScenarioStore
from minegen.services.world_service import WorldService
from minegen.world.synthetic_world import SyntheticWorld
from tests.test_layout_v2_api import _generate_layout, _winner
from tests.test_smoothing_api import _decline, _prepare
from tests.test_world_api import _create

EXPORT = "/export/mine-exchange"
ROOT = f"{BUNDLE_ROOT}/"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


class Bundle:
    """An unzipped export with its parsed manifest."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            self.entries: dict[str, bytes] = {
                n[len(ROOT) :]: zf.read(n) for n in zf.namelist() if n.startswith(ROOT)
            }
            assert len(self.entries) == len(zf.namelist())
        self.manifest: dict[str, Any] = json.loads(self.entries["manifest.json"])
        self.files: dict[str, dict[str, Any]] = {f["path"]: f for f in self.manifest["files"]}
        self.entities: dict[str, dict[str, Any]] = {
            e["entityId"]: e for e in self.manifest["entities"]
        }

    def json(self, path: str) -> Any:
        return json.loads(self.entries[path])

    def text(self, path: str) -> str:
        return self.entries[path].decode("utf-8")

    def stl(self, path: str) -> tuple[np.ndarray, np.ndarray]:
        """Binary STL → welded (positions, triangles) for topology QA."""
        tris, _ = read_binary_stl(self.entries[path])
        flat = tris.reshape(-1, 3)
        uniq, inverse = np.unique(flat, axis=0, return_inverse=True)
        return uniq.astype(np.float64), inverse.reshape(-1, 3).astype(np.int64)

    def stl_qa(self, path: str) -> MeshQa:
        p, t = self.stl(path)
        return mesh_qa(p, t)

    def omissions(self) -> dict[str, str]:
        return {o["group"]: o["reasonCode"] for o in self.manifest["omissions"]}


def export(client: TestClient, sid: str) -> Bundle:
    r = client.post(f"/api/v1/scenarios/{sid}{EXPORT}")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"] == (
        f'attachment; filename="minegen_{sid}_mineexchange_v1.zip"'
    )
    assert r.headers["x-mineexchange-version"] == MINE_EXCHANGE_VERSION
    return Bundle(r.content)


def assert_integrity(b: Bundle) -> None:
    """M2 + M3 + M4 on a real bundle."""
    listed = set(b.files)
    assert "README.txt" in listed and "manifest.json" not in listed
    for path, f in b.files.items():
        assert path in b.entries, f"listed but missing: {path}"
        assert hashlib.sha256(b.entries[path]).hexdigest() == f["sha256"], path
        assert not path.startswith("/") and ".." not in path.split("/") and "\\" not in path
    assert set(b.entries) - listed == {"manifest.json"}
    m = b.manifest
    assert m["mineExchangeVersion"] == "1.0.0"
    assert m["coordinateSystem"]["name"] == "LOCAL_ENU_Z_UP"
    assert m["coordinateSystem"]["crs"] == "LOCAL_SYNTHETIC"
    assert m["units"]["length"] == "metre"
    for f in b.files.values():
        assert f["coordinateFrame"] == "LOCAL_ENU_Z_UP"
        if f["path"].endswith(".glb"):
            g = f["glb"]
            assert g["storedVertexFrame"] == "LOCAL_ENU_Z_UP"
            if f["representation"] == "RENDER_SURFACE":
                # verbatim source bytes: canonical vertices, no root transform
                assert g["sceneFrame"] == "LOCAL_ENU_Z_UP" and g["transformMatrix"] is None
            else:
                assert g["sceneFrame"] == "GLTF_Y_UP" and len(g["transformMatrix"]) == 16
    text = json.dumps(m)
    assert "generatedAt" not in text and "EPSG" not in text and "/home/" not in text


def _derived_state(derived: Path) -> dict[str, tuple[int, int]]:
    return {
        p.name: (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(derived.iterdir())
        if p.is_file()
    }


def _world_only_checks(b: Bundle, orebody_type: str) -> None:
    assert_integrity(b)
    groups = {p.split("/", 1)[0] for p in b.files}
    assert groups == {"README.txt", "terrain", "orebody", "geology"}
    om = b.omissions()
    assert om["EXCAVATIONS"] == "ARTIFACT_ABSENT"
    assert om["NETWORK"] == "ARTIFACT_ABSENT"
    assert om["CAPABILITY"] == "ARTIFACT_ABSENT"
    assert om["STOPES"] == "NOT_IN_V1"
    assert not any(p.startswith("excavations/") for p in b.entries)
    assert "terrain:surface" in b.entities and "orebody:primary" in b.entities
    assert not any(k in b.entities for k in ("ramp:main",))
    # T5 + terrain semantics
    ts = b.files["terrain/terrain_surface.stl"]
    assert ts["semanticType"] == "TERRAIN_SURFACE" and ts["representation"] == "SURFACE_MESH"
    assert ts["geometry"]["closed"] is False and ts["geometry"]["watertight"] is False
    assert ts["derived"] is True
    assert "terrain_solid" not in " ".join(b.files)
    # O1–O6
    ob = b.json("orebody/orebody.json")
    assert ob["semanticType"] == "OREBODY_MODEL" and ob["model"]["type"] == orebody_type
    for key in ("volumeM3", "volumeMethod", "distanceContract", "bboxMin", "bboxMax"):
        assert key in ob["model"], key
    for path in ("orebody/orebody.stl", "orebody/orebody.obj", "orebody/orebody.glb"):
        f = b.files[path]
        assert f["semanticType"] == "OREBODY"
        assert f["representation"] == "DERIVED_SURFACE_OF_SOLID"
        assert f["derived"] is True and f["geometry"]["closed"] is True
        assert f["geometry"]["watertight"] is True and f["geometry"]["manifold"] is True
    qa = b.stl_qa("orebody/orebody.stl")
    assert qa.finite and qa.valid_indices and qa.degenerate_triangles == 0
    assert qa.manifold and qa.watertight and qa.consistent_orientation and qa.signed_volume > 0
    # faults
    fj = b.json("geology/faults.json")
    assert fj["faults"] and all(k in fj["faults"][0] for k in ("entityId", "origin", "normal"))
    assert b.files["geology/faults.dxf"]["geometry"]["closed"] is False
    assert b.files["geology/faults.glb"]["semanticType"] == "FAULT_SURFACE"


# --------------------------------------------------------------------------- #
# FAST — world-only exports, refusals, read-only contract
# --------------------------------------------------------------------------- #


def test_export_requires_a_world_and_a_scenario(client: TestClient) -> None:
    sid = _create(client)
    r = client.post(f"/api/v1/scenarios/{sid}{EXPORT}")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "WORLD_NOT_GENERATED"
    r = client.post(f"/api/v1/scenarios/nope{EXPORT}")
    assert r.status_code == 404


def test_world_only_export_tabular(client: TestClient, store: ScenarioStore) -> None:
    sid = _create(client)
    assert client.post(f"/api/v1/scenarios/{sid}/world/generate").status_code == 200
    derived = store.derived_dir(sid)
    before = _derived_state(derived)
    b = export(client, sid)
    _world_only_checks(b, "TABULAR")
    # read-only: nothing persisted, nothing touched, no mine_exchange.zip anywhere
    assert _derived_state(derived) == before
    assert not list(Path(store.root).rglob("*.zip"))
    # O5: STL bbox == backend-authored mesh bbox
    world = WorldService(store).load(sid)[1]
    v, _ = world.orebody.mesh()
    p, _t = b.stl("orebody/orebody.stl")
    np.testing.assert_allclose(p.min(axis=0), v.min(axis=0), atol=1e-4)
    np.testing.assert_allclose(p.max(axis=0), v.max(axis=0), atol=1e-4)
    # T1/T4 against the authority
    t = world.terrain
    rows = [ln.split(",") for ln in b.text("terrain/terrain_grid.csv").splitlines()[1:]]
    assert len(rows) == t.z.size
    z = np.zeros_like(t.z)
    for i, j, x, y, zz in rows:
        assert float(x) == t.x0 + int(i) * t.spacing and float(y) == t.y0 + int(j) * t.spacing
        z[int(i), int(j)] = float(zz)
    np.testing.assert_array_equal(z, t.z)
    # M1: a second export is byte-identical
    assert export(client, sid).data == b.data


def test_world_only_export_ellipsoid(client: TestClient) -> None:
    sc = realize_scenario(ScenarioPreset.RANDOM_ELLIPSOID, 777, fault_count=1)
    r = client.post("/api/v1/scenarios", json=sc.model_dump(by_alias=True, mode="json"))
    assert r.status_code == 201, r.text
    sid = str(r.json()["id"])
    assert client.post(f"/api/v1/scenarios/{sid}/world/generate").status_code == 200
    b = export(client, sid)
    _world_only_checks(b, "ELLIPSOID")
    assert "semiAxes" in b.json("orebody/orebody.json")["model"]


# --------------------------------------------------------------------------- #
# e2e — the real LAYOUT_V2 chain, module-scoped
# --------------------------------------------------------------------------- #


class TabularStack:
    def __init__(self, root: Path) -> None:
        self.store = ScenarioStore(root / "scenarios")
        self.worlds = WorldService(self.store)
        self.design = DesignService(self.store, self.worlds)
        self.jobs = JobService(max_workers=2)
        app = create_app()
        app.dependency_overrides[get_scenario_store] = lambda: self.store
        app.dependency_overrides[get_world_service] = lambda: self.worlds
        app.dependency_overrides[get_design_service] = lambda: self.design
        app.dependency_overrides[get_infrastructure_service] = lambda: InfrastructureService(
            self.store, self.design
        )
        app.dependency_overrides[get_job_service] = lambda: self.jobs
        app.dependency_overrides[get_exchange_service] = lambda: ExchangeService(
            self.store, self.worlds
        )
        self.client = TestClient(app)
        self.client.__enter__()
        self.sid = ""

    def build_layout_chain(self) -> None:
        c = self.client
        self.sid = _prepare(c)
        base = f"/api/v1/scenarios/{self.sid}/design"
        cat = _generate_layout(c, self.sid)
        r = c.post(f"{base}/layout-v2/activate", json={"candidateId": _winner(cat)})
        assert r.status_code == 200, r.text
        r = c.post(f"{base}/tunnel", params={"sync": "true"})
        assert r.status_code == 200 and r.json()["status"] == "SUCCESS", r.text
        r = c.post(f"{base}/levels")
        assert r.status_code == 200 and r.json()["status"] == "SUCCESS", r.text
        r = c.post(f"{base}/development-mesh", params={"sync": "true"})
        assert r.status_code == 200 and r.json()["status"] == "SUCCESS", r.text
        r = c.post(f"/api/v1/scenarios/{self.sid}/network/generate")
        assert r.status_code == 200 and r.json()["status"] == "SUCCESS", r.text
        r = c.post(f"{base}/capability-graph")
        assert r.status_code == 200 and r.json()["status"] == "SUCCESS", r.text

    @property
    def derived(self) -> Path:
        return self.store.derived_dir(self.sid)

    def artifact(self, name: str) -> dict[str, Any]:
        doc: dict[str, Any] = json.loads((self.derived / name).read_text(encoding="utf-8"))
        return doc

    def close(self) -> None:
        self.client.__exit__(None, None, None)
        self.jobs.shutdown()


@pytest.fixture(scope="module")
def tabular(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TabularStack]:
    stack = TabularStack(tmp_path_factory.mktemp("exchange-tabular"))
    stack.build_layout_chain()
    yield stack
    stack.close()


@pytest.fixture(scope="module")
def tabular_bundle(tabular: TabularStack) -> Bundle:
    return export(tabular.client, tabular.sid)


def test_e2e_full_bundle_is_deterministic_and_read_only(
    tabular: TabularStack, tabular_bundle: Bundle
) -> None:
    before = _derived_state(tabular.derived)
    again = export(tabular.client, tabular.sid)
    assert again.data == tabular_bundle.data  # M1 on real data (byte-identical ZIP)
    assert _derived_state(tabular.derived) == before  # no side effect, no new file
    assert_integrity(tabular_bundle)
    assert tabular_bundle.omissions() == {
        "STOPES": "NOT_IN_V1",
        "TIMELINE": "NOT_IN_V1",
        "FIELD_LATTICE": "NOT_IN_V1",
    }
    ss = tabular_bundle.manifest["sourceSnapshot"]
    assert ss["activeRampSource"] == "LAYOUT_V2"
    for name in (
        LAYOUT_V2_SELECTED_ARTIFACT,
        LEVEL_ACCESSES_ARTIFACT,
        LEVELS_ARTIFACT,
        NETWORK_ARTIFACT,
        CAPABILITY_GRAPH_ARTIFACT,
    ):
        assert name in ss["artifactRevisions"], name


def test_e2e_orebody_and_terrain_on_the_full_bundle(tabular_bundle: Bundle) -> None:
    b = tabular_bundle
    assert b.files["orebody/orebody.stl"]["geometry"]["closed"] is True
    assert b.stl_qa("orebody/orebody.stl").closed_solid
    assert b.files["terrain/terrain_surface.stl"]["geometry"]["closed"] is False


# -- E1–E8 ------------------------------------------------------------------ #


def _solids(b: Bundle) -> dict[str, dict[str, Any]]:
    return {p: f for p, f in b.files.items() if f["semanticType"] == "EXCAVATION_SOLID"}


@pytest.mark.parametrize("kind", ["RAMP", "LEVEL_ACCESS", "DRIFT", "CROSSCUT"])
def test_e1_e4_every_excavation_kind_is_an_individually_closed_solid(
    tabular_bundle: Bundle, kind: str
) -> None:
    b = tabular_bundle
    prefix = {
        "RAMP": "ramp_main",
        "LEVEL_ACCESS": "level-access_",
        "DRIFT": "drift_",
        "CROSSCUT": "crosscut_",
    }[kind]
    paths = [p for p in _solids(b) if p.split("/")[-1].startswith(prefix)]
    assert paths, kind
    for path in paths:
        f = b.files[path]
        assert f["representation"] == "CLOSED_LOGICAL_SWEEP" and f["derived"] is True
        g = f["geometry"]
        assert g["closed"] and g["watertight"] and g["manifold"]
        assert g["unioned"] is False and g["overlappingAtJunctions"] is True
        assert g["signedVolumeM3"] > 0
        qa = b.stl_qa(path)
        assert qa.closed_solid, (path, qa.problems)
        assert qa.signed_volume > 0 and qa.triangle_count == g["triangleCount"]
        ent = b.entities[f["sourceEntityIds"][0]]
        assert ent["kind"] == kind and path in ent["files"]


def test_e5_export_solids_are_the_production_base_logical_sweep(tabular: TabularStack) -> None:
    """Numeric vertex identity against the PRODUCTION sweep objects:
    ``DevelopmentMeshBuilder.sweep`` (the closed mesh it keeps until the
    junction cuts) and the persisted ramp / development GLB vertex sets."""
    sc, world, _, _ = tabular.worlds.load_bound(tabular.sid)
    ramp_doc = tabular.artifact(LAYOUT_V2_SELECTED_ARTIFACT)
    accesses = tabular.artifact(LEVEL_ACCESSES_ARTIFACT)
    levels = tabular.artifact(LEVELS_ARTIFACT)
    b = export(tabular.client, tabular.sid)
    # (a) developments: production builder sweep == exported STL vertices
    policy = clearance_policy_for(world.orebody)
    drift_ev = DesignCostEvaluator(world, sc.design, clearance=policy)
    xc_ev = DesignCostEvaluator(
        world, sc.design, DesignContext.crosscut(sc.design), clearance=policy
    )
    builder = DevelopmentMeshBuilder(drift_ev, xc_ev, sc.ramp, sc.tunnel_profile)
    shape = build_profile(sc.ramp, secondary_profile(sc.tunnel_profile))
    junction_points: dict[str, list[np.ndarray]] = {}
    for j in find_junctions(ramp_doc, accesses, levels):
        junction_points.setdefault(j.parent_id, []).append(j.point)
        junction_points.setdefault(j.child_id, []).append(j.point)
    specs = specs_from_artifacts(accesses, levels)
    picked: dict[str, Any] = {}
    for spec in specs:
        picked.setdefault(str(spec.kind), spec)
    assert set(picked) == {"LEVEL_ACCESS", "DRIFT", "CROSSCUT"}
    for spec in picked.values():
        near = junction_points.get(spec.development_id)
        swept = builder.sweep(spec, shape, np.asarray(near) if near else None)
        assert swept.closed is not None
        stem = spec.development_id.replace(":", "_")
        stem = {"LEVEL_ACCESS": "level-access", "DRIFT": "drift", "CROSSCUT": "crosscut"}[
            str(spec.kind)
        ] + stem[len(str(spec.kind)) :]
        p, t = b.stl(f"excavations/solids/{stem}.stl")
        prod = np.unique(np.asarray(swept.closed.positions, dtype=np.float32), axis=0)
        np.testing.assert_array_equal(p.astype(np.float32), prod)
        assert t.shape[0] == swept.closed.triangles.shape[0]

    # (b) every exported solid vertex is a vertex of the production render GLB
    def glb_vertices(path: str) -> np.ndarray:
        doc, blob = read_glb(b.entries[path])
        d: dict[str, Any] = doc
        out = []
        for mesh in d["meshes"]:
            for prim in mesh["primitives"]:
                acc = d["accessors"][prim["attributes"]["POSITION"]]
                view = d["bufferViews"][acc["bufferView"]]
                off = view["byteOffset"] + acc.get("byteOffset", 0)
                out.append(
                    np.frombuffer(blob[off : off + acc["count"] * 12], dtype=np.float32).reshape(
                        -1, 3
                    )
                )
        return np.unique(np.vstack(out), axis=0)

    ramp_glb = glb_vertices("excavations/render/tunnel.glb")
    p, _ = b.stl("excavations/solids/ramp_main.stl")
    ramp_set = {tuple(v) for v in ramp_glb.tolist()}
    assert all(tuple(v) in ramp_set for v in p.astype(np.float32).tolist())


def test_e6_junction_connected_solids_stay_closed_and_overlap(tabular_bundle: Bundle) -> None:
    b = tabular_bundle
    levels = b.json("excavations/entities.json")
    drift = next(e for e in levels["centerlines"] if e["kind"] == "DRIFT_PIECE")
    level = drift["levelId"]
    d_path = f"excavations/solids/drift_{level}.stl"
    x_path = next(p for p in _solids(b) if p.startswith(f"excavations/solids/crosscut_{level}_"))
    dp, dt = b.stl(d_path)
    xp, xt = b.stl(x_path)
    assert mesh_qa(dp, dt).closed_solid and mesh_qa(xp, xt).closed_solid
    # the crosscut starts on the drift centerline: their bounding boxes overlap
    lo = np.maximum(dp.min(axis=0), xp.min(axis=0))
    hi = np.minimum(dp.max(axis=0), xp.max(axis=0))
    assert np.all(hi > lo)
    for path in (d_path, x_path):
        assert b.files[path]["geometry"]["overlappingAtJunctions"] is True


def test_e7_e8_multibody_is_a_concatenation_never_a_union(tabular_bundle: Bundle) -> None:
    b = tabular_bundle
    f = b.files["excavations/mine_multibody.stl"]
    assert f["semanticType"] == "EXCAVATION_MULTI_BODY"
    assert f["representation"] == "MULTI_BODY_CONCATENATION"
    g = f["geometry"]
    assert g["closedComponents"] is True and g["unioned"] is False
    assert g["overlappingAtJunctions"] is True
    assert g["printabilityGuaranteed"] is False and g["engineeringSolidReady"] is False
    comps = f["components"]
    solids = _solids(b)
    assert len(comps) == len(solids)
    tris, _ = read_binary_stl(b.entries["excavations/mine_multibody.stl"])
    assert tris.shape[0] == g["triangleCount"] == sum(c["triangleCount"] for c in comps)
    assert sum(s["geometry"]["triangleCount"] for s in solids.values()) == g["triangleCount"]
    first = 0
    for c in comps:
        assert c["firstTriangle"] == first
        stem = c["entityId"].replace(":", "_")
        comp_tris, _ = read_binary_stl(b.entries[f"excavations/solids/{stem}.stl"])
        np.testing.assert_array_equal(tris[first : first + c["triangleCount"]], comp_tris)
        first += c["triangleCount"]
    for bad in ("excavation.stl", "mine_solid.stl", "watertight_mine.stl"):
        assert not any(p.endswith(bad) for p in b.entries)


def test_render_glbs_are_verbatim_source_bytes(
    tabular: TabularStack, tabular_bundle: Bundle
) -> None:
    b = tabular_bundle
    for path, src in (
        ("excavations/render/tunnel.glb", "tunnel_mesh.glb"),
        ("excavations/render/development.glb", "development_mesh.glb"),
    ):
        assert b.entries[path] == (tabular.derived / src).read_bytes()
        f = b.files[path]
        assert f["representation"] == "RENDER_SURFACE"
        assert f["geometry"]["junctionApertures"] is True and f["geometry"]["unioned"] is False
    tunnel_report = tabular.artifact("tunnel_mesh.json")
    assert b.files["excavations/render/tunnel.glb"]["geometry"]["closed"] == bool(
        tunnel_report["geometricallyClosed"]
    )


# -- L1–L4 ------------------------------------------------------------------ #


def _authoritative_polylines(stack: TabularStack) -> dict[str, list[list[float]]]:
    ramp = stack.artifact(LAYOUT_V2_SELECTED_ARTIFACT)
    accesses = stack.artifact(LEVEL_ACCESSES_ARTIFACT)
    levels = stack.artifact(LEVELS_ARTIFACT)
    out: dict[str, list[list[float]]] = {}
    for s in ramp["segments"]:
        pts = s["effectiveCenterline"]["points"]
        out[f"ramp:main:{s['segmentId']}"] = [pts[i : i + 3] for i in range(0, len(pts), 3)]
    for a in accesses["accesses"]:
        if a["status"] == "OK":
            pts = a["centerline"]["points"]
            out[f"level-access:{a['levelId']}"] = [pts[i : i + 3] for i in range(0, len(pts), 3)]
    for d in levels["developments"]:
        pts = d["centerline"]["points"]
        out[development_entity_id(d["id"])] = [pts[i : i + 3] for i in range(0, len(pts), 3)]
    return out


def test_l1_l4_centerlines_csv_matches_the_authoritative_polylines(
    tabular: TabularStack, tabular_bundle: Bundle
) -> None:
    b = tabular_bundle
    auth = _authoritative_polylines(tabular)
    rows = [ln.split(",") for ln in b.text("excavations/centerlines.csv").splitlines()]
    assert rows[0] == ["entityId", "kind", "levelId", "sequence", "x", "y", "z"]
    by_entity: dict[str, list[list[float]]] = {}
    seq: dict[str, int] = {}
    for eid, _kind, _lvl, s, x, y, z in rows[1:]:
        assert int(s) == seq.get(eid, 0)  # point order preserved
        seq[eid] = int(s) + 1
        by_entity.setdefault(eid, []).append([float(x), float(y), float(z)])
    for eid, pts in auth.items():
        assert eid in by_entity, eid
        assert by_entity[eid] == pts  # exact floats (repr) — L4: never synthesized from a mesh
    assert set(by_entity) == set(auth)


def test_l2_l3_centerlines_dxf_round_trips_with_stable_identity(tabular_bundle: Bundle) -> None:
    b = tabular_bundle
    f = b.files["excavations/centerlines.dxf"]
    ents = read_dxf_entities(b.text("excavations/centerlines.dxf"))
    polys = [e for e in ents if e["type"] == "POLYLINE"]
    mapping = {m["handle"]: m for m in f["dxfEntities"]}
    assert len(polys) == len(mapping) == len(f["sourceEntityIds"])
    rows = [ln.split(",") for ln in b.text("excavations/centerlines.csv").splitlines()[1:]]
    csv_pts: dict[str, list[list[float]]] = {}
    for eid, _k, _l, _s, x, y, z in rows:
        csv_pts.setdefault(eid, []).append([float(x), float(y), float(z)])
    layers = set()
    for e in polys:
        m = mapping[e["handle"]]
        assert e["layer"] == m["layer"]
        layers.add(e["layer"])
        np.testing.assert_array_equal(e["points"], np.asarray(csv_pts[m["entityId"]]))
    assert {"RAMP", "LEVEL_ACCESS", "DRIFT", "CROSSCUT"} <= layers


# -- N1–N5 ------------------------------------------------------------------ #


def test_n1_n5_network_projection(tabular: TabularStack, tabular_bundle: Bundle) -> None:
    b = tabular_bundle
    src = tabular.artifact(NETWORK_ARTIFACT)
    net = b.json("topology/network.json")
    assert net["semanticType"] == "MINE_NETWORK"
    assert [n["id"] for n in net["nodes"]] == [n["id"] for n in src["nodes"]]
    assert [e["id"] for e in net["edges"]] == [e["id"] for e in src["edges"]]
    ents = b.json("excavations/entities.json")
    cl_ids = {c["entityId"] for c in ents["centerlines"]}
    for e in net["edges"]:
        assert e["geometryEntityId"] in cl_ids, e["id"]
        assert "oneWay" not in e and "oneWayTraffic" not in e and "direction" not in e
    assert "one-way" in net["directionSemantics"].lower()
    for n in net["nodes"]:
        assert n["surface"] == (n["type"] in {"PORTAL", "SHAFT_COLLAR"})
    nodes_csv = b.text("topology/nodes.csv").splitlines()
    edges_csv = b.text("topology/edges.csv").splitlines()
    assert len(nodes_csv) - 1 == len(net["nodes"]) and len(edges_csv) - 1 == len(net["edges"])
    assert [ln.split(",")[0] for ln in nodes_csv[1:]] == [n["id"] for n in net["nodes"]]
    assert [ln.split(",")[0] for ln in edges_csv[1:]] == [e["id"] for e in net["edges"]]


# -- P1–P4 ------------------------------------------------------------------ #


def test_p1_p4_capability_projection(tabular: TabularStack, tabular_bundle: Bundle) -> None:
    b = tabular_bundle
    src = tabular.artifact(CAPABILITY_GRAPH_ARTIFACT)
    cap = b.json("semantics/capability.json")
    assert cap["semanticType"] == "CAPABILITY"
    assert {e["edgeId"]: e["capabilities"] for e in cap["edges"]} == {
        e["edgeId"]: e["capabilities"] for e in src["edges"]
    }
    assert cap["capabilities"] == src["capabilities"]
    assert cap["surfaceNodeIds"] == src["surfaceNodeIds"]
    assert len(cap["requiredPaths"]) == len(src["requiredPaths"]) > 0
    for out, inp in zip(cap["requiredPaths"], src["requiredPaths"], strict=True):
        assert out["id"] == inp["id"] and out["satisfied"] == inp["satisfied"]
        assert out["physicalReachable"] == inp["physicalReachable"]
        assert out["capabilityReachable"] == inp["capabilityReachable"]
    adv = cap["egressAdvisory"]
    assert adv["advisoryOnly"] is True and "advisory" in adv["note"]
    text = json.dumps(cap).lower()
    for banned in ("statutory compliance", "certified", "regulatory compliance"):
        assert f'"{banned}"' not in text
    assert cap["validation"] == src["validation"]
    # topology ≠ capability: the network file never carries capabilities
    assert "capabilit" not in b.text("topology/network.json").lower()


# -- refusals and lifecycle (mutating; run LAST in this module) -------------- #


def test_snapshot_change_during_export_is_refused(
    tabular: TabularStack, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = write_bundle
    target = tabular.derived / NETWORK_ARTIFACT
    original = target.read_bytes()
    st0 = target.stat()

    def racing(spec: Any) -> Any:
        # a writer republishes network.json while the bundle is being built
        target.write_bytes(original)
        os.utime(target, ns=(st0.st_atime_ns, st0.st_mtime_ns + 1_000_000))
        return real(spec)

    monkeypatch.setattr("minegen.services.exchange_service.write_bundle", racing)
    r = tabular.client.post(f"/api/v1/scenarios/{tabular.sid}{EXPORT}")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "READ_SNAPSHOT_CHANGED"
    monkeypatch.undo()
    # put the original revision back (the capability graph is bound to it)
    os.utime(target, ns=(st0.st_atime_ns, st0.st_mtime_ns))
    assert export(tabular.client, tabular.sid).files  # healthy again


def test_p5_p6_capability_absent_stale_and_malformed(tabular: TabularStack) -> None:
    cap_path = tabular.derived / CAPABILITY_GRAPH_ARTIFACT
    good = cap_path.read_text(encoding="utf-8")
    # MALFORMED
    cap_path.write_text('{"status": "SUCCESS", "edges": 5}', encoding="utf-8")
    r = tabular.client.post(f"/api/v1/scenarios/{tabular.sid}{EXPORT}")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ARTIFACT_MALFORMED", r.text
    # STALE (bound to a network revision that no longer exists)
    doc = json.loads(good)
    doc["networkRevision"] = "0000000000000000"
    cap_path.write_text(json.dumps(doc), encoding="utf-8")
    r = tabular.client.post(f"/api/v1/scenarios/{tabular.sid}{EXPORT}")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "CAPABILITY_GRAPH_STALE", r.text
    # ABSENT → omission, everything else still exported
    cap_path.unlink()
    b = export(tabular.client, tabular.sid)
    assert b.omissions()["CAPABILITY"] == "ARTIFACT_ABSENT"
    assert "semantics/capability.json" not in b.entries
    assert "topology/network.json" in b.entries
    # a real re-generation restores it
    r = tabular.client.post(f"/api/v1/scenarios/{tabular.sid}/design/capability-graph")
    assert r.status_code == 200
    assert "semantics/capability.json" in export(tabular.client, tabular.sid).entries


# --------------------------------------------------------------------------- #
# e2e — LEGACY active ramp
# --------------------------------------------------------------------------- #


def test_legacy_ramp_export(client: TestClient, store: ScenarioStore) -> None:
    sid = _prepare(client)
    _decline(client, sid, max_levels=2)
    r = client.post(f"/api/v1/scenarios/{sid}/design/decline/smooth", params={"sync": "true"})
    assert r.status_code == 200 and r.json()["status"] == "SUCCESS", r.text
    b = export(client, sid)
    assert_integrity(b)
    assert b.manifest["sourceSnapshot"]["activeRampSource"] == "LEGACY"
    ramp = b.entities["ramp:main"]
    assert ramp["sourceArtifact"] == LEGACY_RAMP_ARTIFACT
    assert b.stl_qa("excavations/solids/ramp_main.stl").closed_solid
    assert "excavations/render/tunnel.glb" not in b.entries
    om = b.omissions()
    assert om["RENDER_GLB"] == "ARTIFACT_ABSENT" and om["NETWORK"] == "ARTIFACT_ABSENT"
    doc = json.loads((store.derived_dir(sid) / LEGACY_RAMP_ARTIFACT).read_text())
    rows = [ln.split(",") for ln in b.text("excavations/centerlines.csv").splitlines()[1:]]
    n_pts = sum(s["effectiveCenterline"]["pointCount"] for s in doc["segments"])
    assert len(rows) == n_pts


# --------------------------------------------------------------------------- #
# slow — WARPED_VEIN-301 (shared session fixture, builder level)
# --------------------------------------------------------------------------- #


def test_warped_301_export(
    warped_301: tuple[Scenario, SyntheticWorld], warped_301_search: Any
) -> None:
    from tests.test_curved_levels import _build_levels

    sc, world = warped_301
    search, res = warped_301_search
    payload, ramp_doc, accesses = _build_levels(sc, world, search, res)
    assert payload.status == "SUCCESS"
    levels_doc = payload.model_dump(mode="json", by_alias=True)

    def inputs() -> ExchangeInputs:
        return ExchangeInputs(
            scenario=sc,
            world=world,
            scenario_revision="s",
            arrays_revision="a",
            active_source="LAYOUT_V2",
            ramp=ArtifactInput(ramp_doc, "r1"),
            ramp_artifact=LAYOUT_V2_SELECTED_ARTIFACT,
            accesses=ArtifactInput(accesses, "r2"),
            levels=ArtifactInput(levels_doc, "r3"),
        )

    z1, _ = write_bundle(build_exchange(inputs()))
    z2, _ = write_bundle(build_exchange(inputs()))
    assert z1 == z2  # M1
    b = Bundle(z1)
    assert_integrity(b)
    ob = b.json("orebody/orebody.json")
    assert ob["authority"] == "IMPLICIT_SOLID" and ob["model"]["type"] == "WARPED_VEIN"
    assert ob["model"]["distanceContract"] == "DERIVED_APPROXIMATE_CLEARANCE"
    assert ob["sourceParameters"]["warpedVein"]["shapeModelVersion"] == 1
    for key in ("shapeModelVersion", "geometryLattice", "morphology"):
        assert key in ob["model"], key
    qa = b.stl_qa("orebody/orebody.stl")
    assert qa.closed_solid and qa.signed_volume > 0
    v, _t = world.orebody.mesh()
    p, _ = b.stl("orebody/orebody.stl")
    np.testing.assert_allclose(p.min(axis=0), v.min(axis=0), atol=1e-3)
    np.testing.assert_allclose(p.max(axis=0), v.max(axis=0), atol=1e-3)
    solids = _solids(b)
    kinds = {b.entities[f["sourceEntityIds"][0]]["kind"] for f in solids.values()}
    assert kinds == {"RAMP", "LEVEL_ACCESS", "DRIFT", "CROSSCUT"}
    for path, f in solids.items():
        assert f["geometry"]["closed"] and f["geometry"]["unioned"] is False
        assert b.stl_qa(path).closed_solid, path
    assert b.omissions()["NETWORK"] == "ARTIFACT_ABSENT"
    assert b.omissions()["RENDER_GLB"] == "ARTIFACT_ABSENT"
    assert "excavations/centerlines.dxf" in b.entries
