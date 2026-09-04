"""Phase 20B closeout v3 §4 — development excavation meshes (LEVEL_ACCESS /
DRIFT / CROSSCUT): CAP / OPEN endpoint policy, OPEN-topology QA, coverage
of every development, batched render primitives, artifact / API chain."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from minegen.core.models import Scenario
from minegen.design.constraints import DesignContext
from minegen.design.cost_field import DesignCostEvaluator
from minegen.design.development_mesh import (
    DevelopmentMeshBuilder,
    DevelopmentSpec,
    chain_segments,
    secondary_profile,
    specs_from_artifacts,
    strip_caps,
    validate_development_topology,
)
from minegen.design.glb_writer import read_glb
from minegen.design.profile import build_profile
from minegen.design.tunnel_mesh import build_logical_mesh, build_ring_chain, validate_topology
from minegen.layout.search import (
    LayoutV2Search,
    materialize_effective_ramp,
    materialize_level_accesses,
)
from minegen.levels.builder import LevelDevelopmentBuilder, entries_from_level_accesses
from minegen.world.synthetic_world import SyntheticWorld, generate_world

from .conftest import small_scenario


@pytest.fixture(scope="module")
def tabular() -> tuple[Scenario, SyntheticWorld]:
    sc = small_scenario()
    return sc, generate_world(sc)


@pytest.fixture(scope="module")
def artifacts(tabular: tuple[Scenario, SyntheticWorld]):  # type: ignore[no-untyped-def]
    sc, world = tabular
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
    return accesses, levels.model_dump(mode="json", by_alias=True), drift, cross


def _straight_spec(policy: tuple[str, str], length: float = 40.0) -> DevelopmentSpec:
    pts = np.array([[0.0, t, -50.0] for t in np.linspace(0.0, length, 11)])
    return DevelopmentSpec(
        development_id="X",
        kind="DRIFT",
        level_id="L01",
        pieces=(("X", pts),),
        start=policy[0],  # type: ignore[arg-type]
        end=policy[1],  # type: ignore[arg-type]
        geometry_ref={"artifact": "levels.json"},
    )


def test_cap_cap_keeps_the_closed_solid_contract_and_open_ends_leave_k_boundary_edges(
    tabular: tuple[Scenario, SyntheticWorld],
) -> None:
    sc, _ = tabular
    profile = secondary_profile(sc.tunnel_profile)
    shape = build_profile(sc.ramp, profile)
    for policy, open_ends in ((("CAP", "CAP"), 0), (("OPEN", "CAP"), 1), (("OPEN", "OPEN"), 2)):
        spec = _straight_spec(policy)  # type: ignore[arg-type]
        chain = build_ring_chain(chain_segments(spec), profile.ring_max_spacing)
        closed = build_logical_mesh(chain, shape)
        mesh = strip_caps(closed, spec.start, spec.end)
        rep = validate_development_topology(mesh, chain, spec)
        assert rep.valid, rep.problems
        assert rep.boundary_edges == rep.expected_boundary_edges == open_ends * shape.k
        assert rep.orientation_consistent and rep.non_manifold_edges == 0
        assert rep.degenerate_triangles == 0 and rep.finite and rep.rings_on_centerline
        if open_ends == 0:
            # the existing closed-topology regression still holds for CAP-CAP
            legacy = validate_topology(mesh, (mesh.n_segments, mesh.n_segments + 1))
            assert legacy.watertight and legacy.manifold and legacy.outward_orientation
            assert rep.watertight and rep.signed_volume is not None
            assert math.isclose(rep.signed_volume, legacy.signed_volume)
            assert rep.signed_volume == pytest.approx(shape.mesh_area * 40.0, rel=1e-6)
        else:
            assert rep.watertight is None and rep.signed_volume is None
            assert mesh.triangles.shape[0] == closed.triangles.shape[0] - open_ends * shape.k


def test_open_qa_detects_a_missing_or_extra_boundary(
    tabular: tuple[Scenario, SyntheticWorld],
) -> None:
    sc, _ = tabular
    profile = secondary_profile(sc.tunnel_profile)
    shape = build_profile(sc.ramp, profile)
    spec = _straight_spec(("OPEN", "CAP"))
    chain = build_ring_chain(chain_segments(spec), profile.ring_max_spacing)
    closed = build_logical_mesh(chain, shape)
    # declared OPEN-CAP but the terminal cap is missing too → wrong boundary count
    wrong = strip_caps(closed, "OPEN", "OPEN")
    rep = validate_development_topology(wrong, chain, spec)
    assert not rep.valid and rep.boundary_edges == 2 * shape.k
    # a hole punched in the tube wall → boundary away from the end rings
    mesh = strip_caps(closed, "OPEN", "CAP")
    keep = np.ones(mesh.triangles.shape[0], dtype=bool)
    keep[shape.k * 2 + 3] = False  # a wall triangle between ring 1 and 2
    holed = strip_caps(closed, "OPEN", "CAP")
    holed.triangles = mesh.triangles[keep]
    holed.tri_group = mesh.tri_group[keep]
    rep = validate_development_topology(holed, chain, spec)
    assert not rep.valid and not rep.boundary_loops_on_end_rings


def test_secondary_tessellation_is_coarser_but_the_centerline_is_untouched(
    tabular: tuple[Scenario, SyntheticWorld],
) -> None:
    sc, _ = tabular
    sec = secondary_profile(sc.tunnel_profile)
    assert sec.arch_segments == max(4, sc.tunnel_profile.arch_segments // 2)
    assert sec.ring_max_spacing == 2.0 * sc.tunnel_profile.ring_max_spacing
    # dimensions come from RampConstraints only: the profile width/height are equal
    a = build_profile(sc.ramp, sc.tunnel_profile)
    b = build_profile(sc.ramp, sec)
    assert math.isclose(a.analytic_area, b.analytic_area)
    assert b.k < a.k
    spec = _straight_spec(("CAP", "CAP"), length=40.0)
    chain = build_ring_chain(chain_segments(spec), sec.ring_max_spacing)
    # every authoritative vertex is a ring, and rings lie exactly on the polyline
    pts = spec.pieces[0][1]
    for v in pts:
        assert np.min(np.linalg.norm(chain.centers - v, axis=1)) < 1e-9


def test_every_development_receives_a_mesh_with_the_declared_endpoint_policy(
    tabular: tuple[Scenario, SyntheticWorld],
    artifacts,  # type: ignore[no-untyped-def]
) -> None:
    sc, _ = tabular
    accesses, levels, drift, cross = artifacts
    specs = specs_from_artifacts(accesses, levels)
    n_access = sum(1 for a in accesses["accesses"] if a["status"] == "OK")
    n_levels = len({d["levelId"] for d in levels["developments"] if d["kind"] == "DRIFT"})
    n_cross = sum(1 for d in levels["developments"] if d["kind"] == "CROSSCUT")
    kinds = [s.kind for s in specs]
    assert kinds.count("LEVEL_ACCESS") == n_access > 0
    assert kinds.count("DRIFT") == n_levels > 0
    assert kinds.count("CROSSCUT") == n_cross > 0
    for s in specs:
        if s.kind == "LEVEL_ACCESS":
            assert (s.start, s.end) == ("OPEN", "OPEN")
        elif s.kind == "DRIFT":
            assert (s.start, s.end) == ("CAP", "CAP") and len(s.pieces) >= 1
        else:
            assert (s.start, s.end) == ("OPEN", "CAP")
    builder = DevelopmentMeshBuilder(drift, cross, sc.ramp, sc.tunnel_profile)
    result = builder.build(accesses, levels)
    assert result.status == "SUCCESS", result.report.get("failureReason")
    rep = result.report
    assert rep["developmentCount"] == len(specs)
    assert all(d["topology"]["valid"] for d in rep["developments"])
    assert all(
        d["envelope"]["hardViolations"] == 0 and d["envelope"]["aboveTerrain"] == 0
        for d in rep["developments"]
    )
    by_id = {d["developmentId"]: d for d in rep["developments"]}
    # drift pieces of a level form ONE continuous tube: piece ids preserved
    drift_ids = [d["id"] for d in levels["developments"] if d["kind"] == "DRIFT"]
    assert sorted(
        pid for d in rep["developments"] if d["kind"] == "DRIFT" for pid in d["pieceIds"]
    ) == sorted(drift_ids)
    # ownership references, never duplicated polylines
    for d in rep["developments"]:
        assert d["geometryRef"]["artifact"] in ("levels.json", "level_accesses.json")
        assert "centerline" not in d
    # per-kind batching: one tube primitive per kind (+ caps where CAP ends exist)
    names = [p["name"] for p in rep["primitives"]]
    assert names == ["LEVEL_ACCESS", "DRIFT", "DRIFT_CAP", "CROSSCUT", "CROSSCUT_CAP"]
    assert rep["primitiveCount"] == 5
    assert rep["profile"]["archSegments"] < rep["profile"]["mainRampArchSegments"]
    # nominal volume = analytic profile area × 3-D length per development (rule 67)
    for d in rep["developments"]:
        assert d["nominalExcavationVolume"] == pytest.approx(
            rep["profile"]["analyticProfileArea"] * d["length3d"]
        )
    assert (
        by_id["LEVEL_ACCESS:" + accesses["accesses"][0]["levelId"]]["topology"]["boundaryEdges"] > 0
    )
    # GLB: finite buffers, valid indices, ranges map back to development ids
    doc, binary = read_glb(result.glb or b"")
    prims = doc["meshes"][0]["primitives"]  # type: ignore[index]
    assert [p["extras"]["role"] for p in prims] == [  # type: ignore[index]
        "DEVELOPMENT",
        "DEVELOPMENT",
        "DRIFT_CAP",
        "DEVELOPMENT",
        "CROSSCUT_CAP",
    ]
    ranges = prims[1]["extras"]["ranges"]  # type: ignore[index]
    assert {r["developmentId"] for r in ranges} == {
        d["developmentId"] for d in rep["developments"] if d["kind"] == "DRIFT"
    }
    offsets = [r["indexOffset"] for r in ranges]
    assert offsets == sorted(offsets) and offsets[0] == 0
    n_vertices = doc["accessors"][0]["count"]  # type: ignore[index]
    positions = np.frombuffer(binary[: n_vertices * 12], dtype=np.float32)
    assert np.all(np.isfinite(positions))
    json.dumps(rep, allow_nan=False)


def test_builder_is_deterministic_and_fails_without_developments(
    tabular: tuple[Scenario, SyntheticWorld],
    artifacts,  # type: ignore[no-untyped-def]
) -> None:
    sc, _ = tabular
    accesses, levels, drift, cross = artifacts
    builder = DevelopmentMeshBuilder(drift, cross, sc.ramp, sc.tunnel_profile)
    a = builder.build(accesses, levels)
    b = builder.build(accesses, levels)
    assert a.glb == b.glb and a.report == b.report
    none = builder.build(None, {"status": "FAILED", "developments": []})
    assert none.status == "FAILED" and "NO_DEVELOPMENTS" in none.report["failureReason"]
    # LEGACY ramps have no level-access artifact: drifts + crosscuts only
    legacy_only = builder.build(None, levels)
    assert legacy_only.status == "SUCCESS"
    assert legacy_only.report["byKind"]["LEVEL_ACCESS"]["developmentCount"] == 0
    assert legacy_only.report["byKind"]["DRIFT"]["developmentCount"] > 0
