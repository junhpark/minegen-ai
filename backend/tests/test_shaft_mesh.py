"""Hardening PR-2 H2-SH — the shaft excavation mesh (``shaft_mesh.json`` /
``shaft_mesh.glb``): circular barrel sweep with a constant vertical frame,
CAP–CAP closed-solid QA, OPEN–OPEN station drives, batched render ranges with
reveal metadata, the typed failure paths, and the artifact / API chain
(shafts → shaft mesh, a leaf that invalidates nothing)."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from minegen.core.artifacts import SHAFT_MESH_ARTIFACT, SHAFT_MESH_GLB, SHAFTS_ARTIFACT
from minegen.core.models import Scenario, ShaftPlanningConfig, ShaftSpec
from minegen.design.constraints import DesignContext
from minegen.design.cost_field import DesignCostEvaluator
from minegen.design.development_mesh import DevelopmentSpec, chain_segments
from minegen.design.glb_writer import read_glb
from minegen.design.shaft_mesh import (
    BARREL_SEGMENT_FACTOR,
    COLLAR_CAP_ROLE,
    SHAFT_KIND,
    STATION_ACCESS_KIND,
    SUMP_CAP_ROLE,
    ShaftMeshBuilder,
    barrel_rings,
    build_barrel_logical_mesh,
    circular_profile,
    specs_from_shafts,
)
from minegen.design.tunnel_mesh import build_ring_chain, validate_topology
from minegen.layout.search import (
    LayoutV2Search,
    materialize_effective_ramp,
    materialize_level_accesses,
)
from minegen.levels.builder import LevelDevelopmentBuilder, entries_from_level_accesses
from minegen.services.design_service import DesignService
from minegen.shafts.planner import ShaftPlanner
from minegen.world.synthetic_world import SyntheticWorld, generate_world

from .conftest import small_scenario
from .test_network_api import _levels, _network
from .test_shafts_api import _prepare_with_shaft, _shafts
from .test_smoothing_api import _decline
from .test_tunnel_api import _smooth

# --------------------------------------------------------------------------- #
# unit — profile and vertical sweep
# --------------------------------------------------------------------------- #


def test_circular_profile_is_a_ccw_circle_about_the_axis() -> None:
    shape = circular_profile(6.0, 32)
    assert shape.k == 32
    assert math.isclose(shape.analytic_area, math.pi * 9.0)
    # inscribed polygon: exactly ½·K·r²·sin(2π/K), smaller than the circle
    assert math.isclose(shape.mesh_area, 0.5 * 32 * 9.0 * math.sin(2 * math.pi / 32))
    assert shape.mesh_area < shape.analytic_area
    assert shape.tessellation_bias_pct < 0.0
    assert np.allclose(np.linalg.norm(shape.points, axis=1), 3.0)
    assert np.allclose(shape.centroid, 0.0)
    assert shape.perimeter_u[0] == 0.0 and math.isclose(shape.perimeter_u[-1], 1.0)
    coarse = circular_profile(6.0, 8)
    assert coarse.tessellation_bias_pct < shape.tessellation_bias_pct
    with pytest.raises(ValueError):
        circular_profile(0.0, 8)
    with pytest.raises(ValueError):
        circular_profile(6.0, 2)


def _axis_spec(points: list[list[float]], pieces: int = 1) -> DevelopmentSpec:
    pts = np.asarray(points, dtype=np.float64)
    chain: tuple[tuple[str, np.ndarray], ...]  # type: ignore[type-arg]
    if pieces == 1:
        chain = (("SHAFT:T:SEG00", pts),)
    else:
        mid = pts[len(pts) // 2 : len(pts) // 2 + 1]
        chain = (
            ("SHAFT:T:SEG00", np.vstack([pts[:1], mid])),
            ("SHAFT:T:SEG01", np.vstack([mid, pts[-1:]])),
        )
    return DevelopmentSpec(
        development_id="T",
        kind=SHAFT_KIND,  # type: ignore[arg-type]
        level_id="",
        pieces=chain,
        start="CAP",
        end="CAP",
        geometry_ref={"artifact": SHAFTS_ARTIFACT},
    )


def test_vertical_barrel_is_a_closed_outward_solid_with_the_circle_volume() -> None:
    spec = _axis_spec([[10.0, 20.0, 300.0], [10.0, 20.0, 250.0], [10.0, 20.0, 200.0]], pieces=2)
    chain = build_ring_chain(chain_segments(spec), 2.0)
    assert chain.max_local_turn_deg == 0.0
    shape = circular_profile(6.0, 32)
    mesh = build_barrel_logical_mesh(chain, shape)
    rep = validate_topology(mesh, (mesh.n_segments, mesh.n_segments + 1))
    assert rep.manifold and rep.watertight and rep.outward_orientation, rep.problems
    assert rep.degenerate_triangles == 0
    # signed volume = tessellated area × depth (exactly, for a straight axis)
    assert math.isclose(rep.signed_volume, shape.mesh_area * 100.0, rel_tol=1e-9)
    # rings sit on the axis with the constant frame (x = right, y = up)
    rings = barrel_rings(chain, shape)
    assert rings.shape == (chain.centers.shape[0], 32, 3)
    assert np.allclose(rings[:, 0, :2], chain.centers[:, :2] + [3.0, 0.0])
    assert np.allclose(rings[:, 8, :2], chain.centers[:, :2] + [0.0, 3.0])
    assert np.allclose(rings[:, :, 2], chain.centers[:, None, 2])
    # cap apices are the collar and the bottom themselves (axis = centroid)
    assert np.allclose(mesh.positions[-2], chain.centers[0])
    assert np.allclose(mesh.positions[-1], chain.centers[-1])


def test_barrel_frame_refuses_a_non_vertical_or_upward_axis() -> None:
    inclined = _axis_spec([[0.0, 0.0, 100.0], [10.0, 0.0, 0.0]])
    with pytest.raises(ValueError, match="vertical"):
        barrel_rings(build_ring_chain(chain_segments(inclined), 2.0), circular_profile(6.0, 8))
    upward = _axis_spec([[0.0, 0.0, 0.0], [0.0, 0.0, 100.0]])
    with pytest.raises(ValueError, match="vertical"):
        barrel_rings(build_ring_chain(chain_segments(upward), 2.0), circular_profile(6.0, 8))


# --------------------------------------------------------------------------- #
# integration — the small scenario with one declared shaft
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def shaft_stack() -> dict:  # type: ignore[type-arg]
    sc = small_scenario()
    sc = sc.model_copy(
        update={"shafts": ShaftPlanningConfig(specs=[ShaftSpec(shaft_id="SHAFT-01")])}
    )
    world = generate_world(sc)
    s = LayoutV2Search(sc, world)
    res = s.run()
    assert res.winner_id is not None
    w = res.candidate(res.winner_id)
    assert w is not None
    ramp = materialize_effective_ramp(res, w, s.evaluator, "r")
    accesses = materialize_level_accesses(res, w, "r", sc.mining.method.value)
    drift = DesignCostEvaluator(world, sc.design)
    cross = DesignCostEvaluator(world, sc.design, DesignContext.crosscut(sc.design))
    levels = LevelDevelopmentBuilder(sc, world.orebody, drift, cross).build(
        ramp, "r", entries=entries_from_level_accesses(accesses)
    )
    assert levels.status == "SUCCESS", levels.failure_reason
    axis = DesignCostEvaluator(world, sc.design, DesignContext.shaft(sc.design))
    shafts = ShaftPlanner(sc, world, axis, drift).build(
        levels.model_dump(mode="json", by_alias=True), "src", "lv"
    )
    assert shafts.status == "SUCCESS", shafts.failure_reason
    payload = shafts.model_dump(mode="json", by_alias=True)
    builder = ShaftMeshBuilder(axis, drift, sc.ramp, sc.tunnel_profile)
    result = builder.build(payload, "shrev")
    return {
        "sc": sc,
        "world": world,
        "shafts": payload,
        "builder": builder,
        "result": result,
        "axis": axis,
        "drift": drift,
    }


def test_builder_sweeps_every_ok_shaft_into_a_success_report(shaft_stack: dict) -> None:  # type: ignore[type-arg]
    result = shaft_stack["result"]
    assert result.status == "SUCCESS", result.report.get("failureReason")
    rep = result.report
    assert rep["shaftsRevision"] == "shrev"
    assert rep["booleanUnion"] == "NONE"
    assert rep["shaftCount"] == 1 and rep["skippedShafts"] == []
    shafts = shaft_stack["shafts"]
    stations = shafts["shafts"][0]["stations"]
    assert rep["stationAccessCount"] == len(stations) > 0
    sc: Scenario = shaft_stack["sc"]
    assert (
        rep["profile"]["barrelSegments"] == BARREL_SEGMENT_FACTOR * sc.tunnel_profile.arch_segments
    )
    barrel = rep["shafts"][0]["barrel"]
    # the barrel pieces ARE the shafts.json axis centerline ids, in order
    expected_ids = [shafts["centerlines"][i]["id"] for i in shafts["shafts"][0]["segmentIndices"]]
    assert barrel["pieceIds"] == expected_ids
    assert barrel["topology"]["policy"] == "CAP-CAP"
    assert barrel["topology"]["manifold"] and barrel["topology"]["watertight"]
    assert barrel["topology"]["outwardOrientation"] and barrel["topology"]["valid"]
    # rule 67: nominal = analytic circle × depth; the mesh differs by the
    # tessellation bias only
    depth = shafts["shafts"][0]["metrics"]["depth"]
    assert math.isclose(barrel["length3d"], depth, rel_tol=1e-9)
    assert math.isclose(
        barrel["nominalExcavationVolume"],
        shafts["shafts"][0]["metrics"]["nominalExcavationVolume"],
        rel_tol=1e-9,
    )
    assert math.isclose(barrel["volumeDifferencePct"], -barrel["tessellationBiasPct"], abs_tol=1e-6)
    # the collar breaks the surface INSIDE the collar zone only (rule 183)
    env = barrel["envelope"]
    assert env["hardViolations"] == 0 and env["aboveTerrainBelowCollarZone"] == 0
    assert env["collarZoneAboveTerrain"] > 0
    assert math.isclose(env["collarZoneDepth"], shafts["shafts"][0]["profile"]["diameter"])
    # every station drive is an OPEN–OPEN manifold with boundary (2 × K edges)
    for d, st in zip(rep["shafts"][0]["stationAccesses"], stations, strict=True):
        assert d["pieceId"] == shafts["centerlines"][st["accessCenterlineIndex"]]["id"]
        assert d["levelId"] == st["levelId"]
        assert d["topology"]["policy"] == "OPEN-OPEN" and d["topology"]["valid"]
        assert d["topology"]["boundaryEdges"] == d["topology"]["expectedBoundaryEdges"] > 0
        assert d["envelope"] == {"hardViolations": 0, "aboveTerrain": 0}
        assert math.isclose(d["length3d"], st["report"]["length3d"], rel_tol=1e-9)


def test_render_is_batched_per_kind_with_reveal_ranges_on_shaft_ids(shaft_stack: dict) -> None:  # type: ignore[type-arg]
    result = shaft_stack["result"]
    assert result.glb is not None
    doc, _bin = read_glb(result.glb)
    prims = doc["meshes"][0]["primitives"]  # type: ignore[index]
    roles = [p["extras"]["role"] for p in prims]
    kinds = [p["extras"]["kind"] for p in prims]
    assert roles == ["DEVELOPMENT", "DEVELOPMENT", COLLAR_CAP_ROLE, SUMP_CAP_ROLE]
    assert kinds == [SHAFT_KIND, STATION_ACCESS_KIND, SHAFT_KIND, SHAFT_KIND]
    shafts = shaft_stack["shafts"]
    ids = {c["id"] for c in shafts["centerlines"]}
    for p in prims[:2]:
        ranges = p["extras"]["ranges"]
        assert ranges, p["extras"]["kind"]
        cursor = 0
        for r in ranges:
            assert r["pieceId"] in ids
            assert r["indexOffset"] == cursor and r["indexCount"] > 0
            cursor += r["indexCount"]
            offsets = r["ringIntervalIndexOffsets"]
            assert offsets[0] == 0 and offsets[-1] == r["indexCount"]
            assert len(offsets) == r["ringIntervalCount"] + 1
            fr = r["ringChainageFractions"]
            assert fr[0] == 0.0 and fr[-1] == 1.0 and len(fr) == r["ringIntervalCount"] + 1
            assert r["omittedTriangles"] == 0 and r["clippedQuads"] == 0
    axis_ranges = prims[0]["extras"]["ranges"]
    assert [r["pieceId"] for r in axis_ranges] == [
        shafts["centerlines"][i]["id"] for i in shafts["shafts"][0]["segmentIndices"]
    ]
    assert {r["pieceId"] for r in prims[1]["extras"]["ranges"]} == {
        shafts["centerlines"][st["accessCenterlineIndex"]]["id"]
        for st in shafts["shafts"][0]["stations"]
    }
    report_prims = result.report["primitives"]
    assert [p["role"] for p in report_prims] == roles
    k = result.report["profile"]["barrelSegments"]
    assert report_prims[2]["triangleCount"] == k and report_prims[3]["triangleCount"] == k


def test_typed_failures_never_produce_a_glb(shaft_stack: dict) -> None:  # type: ignore[type-arg]
    builder: ShaftMeshBuilder = shaft_stack["builder"]
    shafts = shaft_stack["shafts"]
    failed = builder.build({**shafts, "status": "FAILED"}, "x")
    assert failed.status == "FAILED" and failed.glb is None
    assert failed.report["failureReason"].startswith("SHAFTS_NOT_SUCCESS")
    assert failed.report["shaftsRevision"] == "x"
    empty = builder.build({**shafts, "shafts": [], "centerlines": []}, "x")
    assert empty.status == "FAILED" and empty.glb is None
    assert empty.report["failureReason"].startswith("NO_SHAFTS")
    # a FAILED shaft owns no geometry and is reported as skipped, never swept
    one_failed = json.loads(json.dumps(shafts))
    one_failed["shafts"][0]["status"] = "FAILED"
    one_failed["shafts"][0]["failureCode"] = "SHAFT_GEOMETRY_INVALID"
    skipped = builder.build(one_failed, "x")
    assert skipped.status == "FAILED"
    assert skipped.report["skippedShafts"] == ["SHAFT-01: SHAFT_GEOMETRY_INVALID"]
    # a segment index that does not point at an axis segment is malformed
    bad = json.loads(json.dumps(shafts))
    bad["shafts"][0]["segmentIndices"][0] = bad["shafts"][0]["stations"][0]["accessCenterlineIndex"]
    malformed = builder.build(bad, "x")
    assert malformed.status == "FAILED" and malformed.glb is None
    assert malformed.report["failureReason"].startswith("SHAFTS_MALFORMED")
    with pytest.raises(ValueError):
        specs_from_shafts(bad)


def test_an_envelope_violation_fails_the_barrel_explicitly(shaft_stack: dict) -> None:  # type: ignore[type-arg]
    """Nothing is clamped: a barrel pushed below the model floor (OUTSIDE_WORLD
    on its lowest rings) is a typed FAILED report, never a trimmed mesh."""
    builder: ShaftMeshBuilder = shaft_stack["builder"]
    shafts = json.loads(json.dumps(shaft_stack["shafts"]))
    world: SyntheticWorld = shaft_stack["world"]
    floor = float(np.asarray(world.orebody.bounding_box()[0])[2]) - 10_000.0
    last = shafts["shafts"][0]["segmentIndices"][-1]
    pts = shafts["centerlines"][last]["centerline"]["points"]
    pts[5] = floor  # the bottom point z
    shafts["shafts"][0]["bottom"][2] = floor
    result = builder.build(shafts, "x")
    assert result.status == "FAILED" and result.glb is None
    assert "barrel envelope" in result.report["failureReason"]
    barrel = result.report["shafts"][0]["barrel"]
    assert barrel["envelope"]["hardViolations"] > 0
    assert barrel["topology"]["valid"] is False


# --------------------------------------------------------------------------- #
# artifact + API chain
# --------------------------------------------------------------------------- #


def test_shaft_mesh_api_lifecycle(client: TestClient, design_service: DesignService) -> None:
    sid = _prepare_with_shaft(client)
    base = f"/api/v1/scenarios/{sid}"
    # typed prerequisites
    r = client.post(f"{base}/design/shaft-mesh")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "SHAFTS_NOT_GENERATED"
    r = client.get(f"{base}/design/shaft-mesh")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SHAFT_MESH_NOT_GENERATED"
    r = client.get(f"{base}/design/shaft-mesh/mesh.glb")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SHAFT_MESH_NOT_GENERATED"
    spec = {"shaftId": "SHAFT-01", "role": "PRODUCTION"}
    r = client.post(f"{base}/design/shafts/suggest-collar", json=spec)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "LEVELS_NOT_GENERATED"

    _decline(client, sid)
    _smooth(client, sid)
    lv = _levels(client, sid)
    assert lv["status"] == "SUCCESS", lv["failureReason"]

    # the collar suggestion IS the planner's default placement (rule 182)
    r = client.post(f"{base}/design/shafts/suggest-collar", json=spec)
    assert r.status_code == 200, r.text
    suggestion = r.json()
    assert suggestion["status"] == "OK" and suggestion["collarSource"] == "DEFAULT_DERIVED"
    assert suggestion["levelIds"] == [lvl["levelId"] for lvl in lv["levels"]]
    shafts = _shafts(client, sid)
    assert shafts["status"] == "SUCCESS", shafts["failureReason"]
    assert shafts["shafts"][0]["collarSource"] == "DEFAULT_DERIVED"
    assert suggestion["collar"] == pytest.approx(shafts["shafts"][0]["collar"], abs=1e-9)
    # nothing was persisted by the suggestion
    assert not design_service.shaft_mesh_report_path(sid).exists()

    r = client.post(f"{base}/design/shaft-mesh")
    assert r.status_code == 200, r.text
    mesh = r.json()
    assert mesh["status"] == "SUCCESS", mesh["failureReason"]
    assert mesh["shaftCount"] == 1 and mesh["stationAccessCount"] == len(
        shafts["shafts"][0]["stations"]
    )
    assert mesh["meshUrl"].startswith(f"/api/v1/scenarios/{sid}/design/shaft-mesh/mesh.glb?v=")
    assert mesh["sources"] == {"shafts": True, "rampSource": "LEGACY"}
    assert client.get(f"{base}/design/shaft-mesh").json() == mesh
    glb = client.get(f"{base}/design/shaft-mesh/mesh.glb")
    assert glb.status_code == 200 and glb.headers["content-type"] == "model/gltf-binary"
    assert len(glb.content) == mesh["glbBytes"]
    scene = client.get(f"{base}/scene").json()
    assert scene["shaftMesh"]["artifactRevision"] == mesh["artifactRevision"]
    assert scene["shafts"]["status"] == "SUCCESS"

    # the mesh is a LEAF: generating it changed nothing else, and the network
    # / capability chain leaves it untouched
    assert client.get(f"{base}/design/shafts").json() == shafts
    net = _network(client, sid)
    assert net["status"] == "SUCCESS", net["failureReason"]
    assert client.get(f"{base}/design/shaft-mesh").json() == mesh
    # the reset preview of the SHAFTS stage owns both artifacts
    plan = client.get(f"{base}/design/reset-plan", params={"from": "SHAFTS"}).json()
    assert plan["stageArtifacts"] == [SHAFTS_ARTIFACT, SHAFT_MESH_ARTIFACT]
    assert SHAFT_MESH_ARTIFACT in plan["willDelete"] and SHAFT_MESH_GLB in plan["willDelete"]

    # stale: the shafts document moved (a stat identity change suffices,
    # rule 60) → the mesh is refused everywhere, the shafts stay valid
    shafts_path = design_service.shafts_path(sid)
    shafts_path.write_text(shafts_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    r = client.get(f"{base}/design/shaft-mesh")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SHAFT_MESH_STALE"
    r = client.get(f"{base}/design/shaft-mesh/mesh.glb")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SHAFT_MESH_STALE"
    r = client.get(f"{base}/scene")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SCENE_ARTIFACT_INVALID"
    assert client.get(f"{base}/design/shafts").status_code == 200
    # regenerating the mesh repairs it
    assert client.post(f"{base}/design/shaft-mesh").status_code == 200
    assert client.get(f"{base}/design/shaft-mesh").status_code == 200

    # shafts → shaft mesh: re-planning the shafts deletes the mesh pair
    _shafts(client, sid)
    r = client.get(f"{base}/design/shaft-mesh")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SHAFT_MESH_NOT_GENERATED"
    assert not design_service.shaft_mesh_glb_path(sid).exists()
    # … and so does a level regeneration (levels → shafts → shaft mesh)
    assert client.post(f"{base}/design/shaft-mesh").status_code == 200
    _levels(client, sid)
    assert client.get(f"{base}/design/shafts").status_code == 404
    assert client.get(f"{base}/design/shaft-mesh").status_code == 409
