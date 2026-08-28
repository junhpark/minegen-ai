"""Phase 06 gate tests: gravity-aligned tunnel sweep (rules 65–67)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from minegen.core.coordinates import gravity_aligned_frame
from minegen.core.models import Point3D, RampConstraints, RestrictedZone, TunnelProfile
from minegen.design.cost_field import DesignCostEvaluator
from minegen.design.glb_writer import read_glb, write_glb
from minegen.design.tunnel_mesh import (
    TunnelMeshBuilder,
    build_logical_mesh,
    build_profile,
    build_render_mesh,
    build_ring_chain,
    validate_topology,
)
from tests.test_smoothing import _flat_cover_setup


def _seg(
    points: np.ndarray, t0: np.ndarray, t1: np.ndarray, level: str = "L01", source: str = "SMOOTHED"
) -> dict:  # type: ignore[type-arg]
    return {
        "levelId": level,
        "effectiveSource": source,
        "effectiveCenterline": {"points": points.ravel().tolist(), "pointCount": len(points)},
        "boundaryTangents": {"start": t0.tolist(), "end": t1.tolist()},
    }


def _straight(start: np.ndarray, heading: float, grade: float, length_3d: float, n: int = 41):  # type: ignore[no-untyped-def]
    t = np.array([math.sin(heading), math.cos(heading), grade])
    t = t / np.linalg.norm(t)
    ts = np.linspace(0.0, length_3d, n)
    return start[None, :] + ts[:, None] * t[None, :], t


# -- 1. profile geometry (rule 67: derived crown radius) -----------------------


def test_profile_dimensions_and_derived_crown() -> None:
    ramp = RampConstraints()
    shape = build_profile(ramp, TunnelProfile())
    pts = shape.points
    # width between floor corners; height at crown top; floor at y=0
    assert float(pts[0, 0] - pts[-1, 0]) == pytest.approx(ramp.tunnel_width, abs=1e-12)
    assert float(pts[:, 1].max()) == pytest.approx(ramp.tunnel_height, abs=1e-12)
    assert float(pts[0, 1]) == 0.0 and float(pts[-1, 1]) == 0.0
    # default 5×5 with wall 2.5 → semicircular crown R = 2.5
    assert shape.crown_radius == pytest.approx(2.5, abs=1e-12)
    # arch points lie exactly on the derived circle
    arch = pts[1:-1]
    r = np.linalg.norm(arch - np.array([0.0, shape.crown_center_y]), axis=1)
    assert np.allclose(r, shape.crown_radius, atol=1e-12)
    # non-semicircular case: W=5, H=5, Hw=3 → Rc = (2.5² + 2²)/(2·2) = 2.5625
    shape2 = build_profile(ramp, TunnelProfile(wallHeight=3.0))
    assert shape2.crown_radius == pytest.approx(2.5625, abs=1e-12)
    assert float(shape2.points[:, 1].max()) == pytest.approx(5.0, abs=1e-9)
    with pytest.raises(ValueError):
        build_profile(ramp, TunnelProfile(wallHeight=5.0))


# -- 2/3. frame reuse + floor-centerline semantics (rule 65) -------------------


def test_frame_properties_and_floor_semantics() -> None:
    g = 0.12
    t = np.array([0.0, 1.0, -g])
    t = t / np.linalg.norm(t)
    f = gravity_aligned_frame(t)  # the ONE frame Phase 06 uses (rule 65)
    # north-facing ramp: right = East exactly
    assert np.allclose(f.right, [1.0, 0.0, 0.0], atol=1e-12)
    # orthonormal, right-handed
    for a, b in ((f.right, f.forward), (f.right, f.up), (f.forward, f.up)):
        assert abs(float(np.dot(a, b))) < 1e-12
    assert float(np.dot(np.cross(f.right, f.forward), f.up)) == pytest.approx(1.0, abs=1e-12)
    # profile plane ⊥ 3D tangent (NOT the global-Z vertical section)
    assert abs(float(np.dot(f.up, t))) < 1e-12

    ramp = RampConstraints()
    shape = build_profile(ramp, TunnelProfile())
    pts, tan = _straight(np.array([10.0, -20.0, -30.0]), 0.3, -g, 60.0)
    chain = build_ring_chain([_seg(pts, tan, tan)], 2.0)
    mesh = build_logical_mesh(chain, shape)
    rings = mesh.positions[: chain.centers.shape[0] * shape.k].reshape(-1, shape.k, 3)
    # floor centerline: the floor edge midpoint is exactly the centerline point
    floor_mid = (rings[:, 0, :] + rings[:, -1, :]) / 2.0
    assert np.abs(floor_mid - chain.centers).max() < 1e-9
    # floor cross-slope zero on a 12 % ramp (gravity-aligned up, no roll)
    assert np.abs(rings[:, 0, 2] - rings[:, -1, 2]).max() < 1e-9


# -- 4/5. ring sampling: linear subdivision only (rule 65) ---------------------


def test_rings_lie_exactly_on_the_polyline_and_spacing() -> None:
    pts, tan = _straight(np.array([0.0, 0.0, -50.0]), 1.1, -0.06, 97.3, n=14)
    chain = build_ring_chain([_seg(pts, tan, tan)], 2.0)
    assert float(np.diff(chain.chainage).max()) <= 2.0 + 1e-9
    # every ring center is ON the input polyline (never moved, rule 65)
    from minegen.design.smoothing import distance_to_polyline

    assert float(distance_to_polyline(chain.centers, pts).max()) < 1e-9
    # original vertices are preserved verbatim
    for p in pts:
        assert np.min(np.linalg.norm(chain.centers - p[None, :], axis=1)) < 1e-12


def test_excessive_local_turn_fails() -> None:
    sc, ev = _flat_cover_setup(min_cover=0.0)
    builder = TunnelMeshBuilder(ev, sc.ramp, sc.tunnel_profile)
    # a 20° corner in the polyline: FAILED, never silently meshed (rule 66)
    a = np.array([0.0, 0.0, -50.0])
    b = a + 20.0 * np.array([0.0, 1.0, 0.0])
    d2 = np.array([math.sin(0.35), math.cos(0.35), 0.0])
    pts = np.vstack([a, b, b + 20.0 * d2])
    payload = {"status": "SUCCESS", "segments": [_seg(pts, np.array([0.0, 1.0, 0.0]), d2)]}
    res = builder.build(payload)
    assert res.status == "FAILED" and res.glb is None
    assert "ringMaxTurnDeg" in res.report["failureReason"]


# -- 6. junction weld (rule 66) ------------------------------------------------


def test_junction_ring_is_shared_exactly_once() -> None:
    ramp = RampConstraints()
    shape = build_profile(ramp, TunnelProfile())
    start = np.array([0.0, 0.0, -50.0])
    pts1, t1 = _straight(start, 0.0, -0.06, 60.0, n=16)
    pts2, t2 = _straight(pts1[-1], 0.0, -0.06, 60.0, n=16)
    seg1 = _seg(pts1, t1, t1, "L01")
    seg2 = _seg(pts2, t2, t2, "L02")
    chain = build_ring_chain([seg1, seg2], 2.0)
    # one logical boundary ring: total rings = rings(seg1) + rings(seg2) − 1
    c1 = build_ring_chain([seg1], 2.0)
    c2 = build_ring_chain([seg2], 2.0)
    assert len(chain.centers) == len(c1.centers) + len(c2.centers) - 1
    j = int(chain.boundary_rings[1])
    assert np.allclose(chain.centers[j], pts1[-1], atol=1e-12)
    assert np.allclose(chain.centers[j], pts2[0], atol=1e-12)
    # the shared ring's tangent is the persisted shared boundary tangent
    assert np.allclose(chain.tangents[j], t1, atol=1e-12)
    mesh = build_logical_mesh(chain, shape)
    top = validate_topology(mesh, (mesh.n_segments, mesh.n_segments + 1))
    assert top.watertight and top.manifold and top.degenerate_triangles == 0


# -- 7/8. topology, removable caps, volumes (rules 66–67) ----------------------


def test_topology_volumes_and_removable_caps() -> None:
    ramp = RampConstraints()
    profile = TunnelProfile()
    shape = build_profile(ramp, profile)
    length = 120.0
    pts, tan = _straight(np.array([5.0, 5.0, -60.0]), 0.7, -0.12, length)
    seg = _seg(pts, tan, tan)
    chain = build_ring_chain([seg], 2.0)
    mesh = build_logical_mesh(chain, shape)
    top = validate_topology(mesh, (mesh.n_segments, mesh.n_segments + 1))
    assert top.watertight and top.manifold and top.outward_orientation
    assert top.degenerate_triangles == 0
    # rule 67: nominal volume = profile area × 3D length, NO cosine correction
    nominal = shape.mesh_area * length
    assert top.signed_volume == pytest.approx(nominal, rel=1e-9)
    # caps are separate removable primitives; without them the tube is open
    render = build_render_mesh(
        mesh,
        chain,
        shape,
        profile.crease_angle_deg,
        [{"levelId": "L01", "effectiveSource": "SMOOTHED"}],
    )
    names = [p.name for p in render.primitives]
    assert names[-2:] == ["PORTAL_CAP", "TERMINAL_CAP"]
    assert render.primitives[-1].extras["role"] == "TERMINAL_CAP"
    assert render.geometrically_closed
    from minegen.design.tunnel_mesh import _geometrically_closed

    tube_only = [p for p in render.primitives if p.extras.get("role") == "SEGMENT"]
    assert not _geometrically_closed(render.positions.astype(np.float64), tube_only)


# -- 9/10. excavation envelope + burial transition (rule 66) -------------------


def test_envelope_catches_wall_violation_with_valid_centerline() -> None:
    sc, ev0 = _flat_cover_setup(min_cover=0.0)
    design = sc.design.model_copy(deep=True)
    pts, tan = _straight(np.array([-80.0, -150.0, -50.0]), 0.0, 0.0, 120.0)
    mid = pts[len(pts) // 2]
    # a box beside the centerline: ≥1.5 m east of it (centerline valid) but
    # inside the excavation envelope — it clips the upper-wall arch vertices
    # (x ≈ ±2.31 m, z ≈ +3.46 m for the default profile)
    design.restricted_zones = [
        RestrictedZone(
            min=Point3D(x=float(mid[0]) + 1.5, y=float(mid[1]) - 10.0, z=float(mid[2]) + 1.0),
            max=Point3D(x=float(mid[0]) + 2.4, y=float(mid[1]) + 10.0, z=float(mid[2]) + 5.0),
        )
    ]
    ev = DesignCostEvaluator(ev0.world, design)
    centerline_eval = ev.evaluate_points(pts)
    assert bool(centerline_eval.valid.all())  # the CENTERLINE alone passes
    builder = TunnelMeshBuilder(ev, sc.ramp, sc.tunnel_profile)
    res = builder.build({"status": "SUCCESS", "segments": [_seg(pts, tan, tan)]})
    assert res.status == "FAILED" and res.glb is None
    assert res.report["envelopeViolations"] > 0
    assert "RESTRICTED_ZONE" in res.report["envelopeReasonCounts"]


def test_portal_burial_transition() -> None:
    sc, ev = _flat_cover_setup(min_cover=0.0)  # flat terrain at 100 m
    builder = TunnelMeshBuilder(ev, sc.ramp, sc.tunnel_profile)
    # descend from the surface: roof above terrain near the portal is ALLOWED
    pts, tan = _straight(np.array([-80.0, -150.0, 99.0]), 0.0, -0.12, 200.0)
    res = builder.build({"status": "SUCCESS", "segments": [_seg(pts, tan, tan)]})
    assert res.status == "SUCCESS", res.report.get("failureReason")
    assert res.report["burialRing"] > 0
    assert res.report["envelopeViolations"] == 0
    # dive then GENTLY resurface (each vertex turn ≤ 4.6° < 7°): terrain
    # breakthrough AFTER burial is a violation (rule 66)
    grades = [-0.12, -0.12, -0.04, 0.04, 0.12, 0.12, 0.12]
    p0 = np.array([-80.0, -150.0, 99.0])
    verts = [p0]
    for g in grades:
        d = np.array([0.0, 1.0, g])
        d = d / np.linalg.norm(d)
        verts.append(verts[-1] + 40.0 * d)
    poly = np.asarray(verts)
    t0 = np.array([0.0, 1.0, grades[0]])
    t0 = t0 / np.linalg.norm(t0)
    t1 = np.array([0.0, 1.0, grades[-1]])
    t1 = t1 / np.linalg.norm(t1)
    res2 = builder.build({"status": "SUCCESS", "segments": [_seg(poly, t0, t1)]})
    assert res2.status == "FAILED"
    assert "envelope" in res2.report["failureReason"]
    assert res2.report["envelopeReasonCounts"].get("ABOVE_TERRAIN", 0) > 0


# -- 12. GLB container validity (rule 67) --------------------------------------


def test_glb_roundtrip_and_determinism() -> None:
    ramp = RampConstraints()
    profile = TunnelProfile()
    shape = build_profile(ramp, profile)
    pts, tan = _straight(np.array([0.0, 0.0, -40.0]), 2.0, -0.1, 80.0)
    chain = build_ring_chain([_seg(pts, tan, tan)], 2.0)
    mesh = build_logical_mesh(chain, shape)
    render = build_render_mesh(
        mesh,
        chain,
        shape,
        profile.crease_angle_deg,
        [{"levelId": "L01", "effectiveSource": "SMOOTHED"}],
    )
    glb = write_glb(render)
    assert glb == write_glb(render)  # byte-deterministic
    assert len(glb) % 4 == 0
    doc, binary = read_glb(glb)
    assert doc["asset"]["version"] == "2.0"  # type: ignore[index]
    assert doc["buffers"][0]["byteLength"] == len(binary)  # type: ignore[index]
    accessors = doc["accessors"]  # type: ignore[assignment]
    pos_acc = accessors[0]  # type: ignore[index]
    assert pos_acc["count"] == render.render_vertex_count
    assert all(math.isfinite(v) for v in pos_acc["min"] + pos_acc["max"])
    prims = doc["meshes"][0]["primitives"]  # type: ignore[index]
    assert [p["extras"].get("segmentId", p["extras"]["role"]) for p in prims] == [
        "L01",
        "PORTAL_CAP",
        "TERMINAL_CAP",
    ]
    # every index in range
    n = render.render_vertex_count
    for prim in render.primitives:
        assert int(prim.indices.max()) < n


def test_profile_envelope_reach() -> None:
    """The maximal profile offset from the floor centerline — the standoff a
    centerline needs on top of a hard buffer to guarantee the excavation
    envelope clears it (1-Lipschitz sdf). Crown apex dominates: 5.0 m for
    any default-height profile."""
    from minegen.design.profile import profile_envelope_reach

    ramp = RampConstraints()
    assert profile_envelope_reach(ramp, TunnelProfile()) == pytest.approx(5.0, abs=1e-12)
    assert profile_envelope_reach(ramp, TunnelProfile(wallHeight=3.0)) == pytest.approx(
        5.0, abs=1e-9
    )


def test_nominal_volume_invariant_under_arch_segments() -> None:
    """Blocker 2 regression: nominalExcavationVolume uses the ANALYTIC
    D-profile area, so it must be identical for any tessellation density,
    while the mesh area converges from below (~1/n²)."""
    from minegen.design.profile import build_profile as bp

    ramp = RampConstraints()
    sc, ev = _flat_cover_setup(min_cover=0.0)
    pts, tan = _straight(np.array([-80.0, -150.0, -50.0]), 0.0, -0.1, 90.0)
    payload = {"status": "SUCCESS", "segments": [_seg(pts, tan, tan)]}
    nominals, mesh_areas, statuses = [], [], []
    for n in (8, 16, 32):
        builder = TunnelMeshBuilder(
            ev, sc.ramp, sc.tunnel_profile.model_copy(update={"arch_segments": n})
        )
        rep = builder.build(payload).report
        nominals.append(rep["nominalExcavationVolume"])
        mesh_areas.append(rep["meshProfileArea"])
        statuses.append(rep["status"])
        assert rep["analyticProfileArea"] == pytest.approx(
            bp(ramp, TunnelProfile()).analytic_area, rel=1e-15
        )
        assert rep["tessellationBiasPct"] < 0.0
    assert nominals[0] == nominals[1] == nominals[2]
    assert mesh_areas[0] < mesh_areas[1] < mesh_areas[2] < nominals[0] / 90.0
    # coarse 8-segment tessellation legitimately FAILS the 1 % volume QA
    # against the analytic nominal (bias −1.12 %) — the reason the default
    # arch_segments moved to 16, where the gate is comfortably green
    assert statuses == ["FAILED", "SUCCESS", "SUCCESS"]
    # default 16 segments keeps the 1 % volume QA comfortably green
    default_rep = TunnelMeshBuilder(ev, sc.ramp, sc.tunnel_profile).build(payload).report
    assert abs(default_rep["volumeDifferencePct"]) < 0.5


def test_search_rejects_wall_clipping_primitive() -> None:
    """Blocker 1 regression: a primitive whose CENTERLINE is valid but whose
    swept wall/roof clips a restricted zone is rejected by the Hybrid-A*
    feasibility contract itself (direction-aware envelope), not first caught
    by the Phase 06 gate."""
    from minegen.core.models import Point3D, RestrictedZone
    from minegen.design.astar_3d import HybridAStar
    from minegen.design.motion_primitives import Pose, Steering

    sc, ev0 = _flat_cover_setup(min_cover=0.0)
    design = sc.design.model_copy(deep=True)
    start = Pose(-80.0, -150.0, -50.0, 0.0)  # heading north, deep, buried
    # box east of the path: ≥1.5 m from the centerline, clips the upper wall
    design.restricted_zones = [
        RestrictedZone(
            min=Point3D(x=-78.5, y=-145.0, z=-49.0),
            max=Point3D(x=-77.6, y=-135.0, z=-45.0),
        )
    ]
    from minegen.design.cost_field import DesignCostEvaluator

    ev = DesignCostEvaluator(ev0.world, design)
    a = HybridAStar(ev, sc.ramp, sc.design.search)
    prims = a.prims.expand(start)
    straight = next(p for p in prims if p.steering is Steering.STRAIGHT and p.grade == 0.0)
    centerline = ev.evaluate_points(straight.samples)
    assert bool(centerline.valid.all())  # the centerline alone is fine
    assert a.evaluate_primitives([straight], True, True)[0] is None  # envelope says no
    # without the zone the same primitive is accepted
    a0 = HybridAStar(ev0, sc.ramp, sc.design.search)
    assert a0.evaluate_primitives([straight], True, True)[0] is not None


def test_launchability_rejects_trapped_terminal_pose() -> None:
    """Blocker 1 regression: a terminal pose walled in ahead has no legal
    successor primitive under the envelope-aware contract — the designer must
    treat such an arrival as unusable for a non-final level."""
    from minegen.core.models import Point3D, RestrictedZone
    from minegen.design.astar_3d import HybridAStar
    from minegen.design.cost_field import DesignCostEvaluator
    from minegen.design.motion_primitives import Pose

    sc, ev0 = _flat_cover_setup(min_cover=0.0)
    design = sc.design.model_copy(deep=True)
    end = Pose(-80.0, -150.0, -50.0, 0.0)  # heading north
    # a wide wall just ahead: every forward/downward successor clips it
    design.restricted_zones = [
        RestrictedZone(
            min=Point3D(x=-140.0, y=-146.0, z=-75.0),
            max=Point3D(x=-20.0, y=-140.0, z=-25.0),
        )
    ]
    ev = DesignCostEvaluator(ev0.world, design)
    a = HybridAStar(ev, sc.ramp, sc.design.search)
    prims = a.prims.expand(end)
    evals = a.evaluate_primitives(prims, True, True)
    assert all(e is None for e in evals)  # trapped: not launchable
    a0 = HybridAStar(ev0, sc.ramp, sc.design.search)
    assert any(e is not None for e in a0.evaluate_primitives(prims, True, True))
