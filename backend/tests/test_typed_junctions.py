"""Phase 20D.1 — typed junction contracts (T1–T7).

Three junction types exist in MineGen's development topology, all three
declared by the artifacts the mesh builders already consume and welded at
≤ 1e-6 m by the network builder:

    J1 RAMP → LEVEL_ACCESS   at the RAMP_JUNCTION (a shared ramp boundary ring)
    J2 LEVEL_ACCESS → DRIFT  at the LEVEL_ENTRY   (a DRIFT piece breakpoint)
    J3 DRIFT → CROSSCUT      at the station       (a DRIFT piece breakpoint)

Before Phase 20D.1 every tube was swept independently, so the parent's wall
quads ran straight through the child's mouth and the child's open end sat
inside the parent as a visible inner shell. These tests pin the typed local
union: the parent's blocking quads and the child's intruding quads are
omitted ONLY inside the junction window, unrelated endpoints keep their
CAP / OPEN contract, every emitted primitive stays a valid oriented
triangle set, and the TABULAR / WARPED planners' outputs are untouched.

Commit 1 of the phase carried the junction-aware assertions as STRICT
xfails; commit 2 (the typed junction geometry) turned them green.
"""

from __future__ import annotations

import json
from itertools import pairwise
from typing import Any

import numpy as np
import pytest

from minegen.design.constraints import DesignContext
from minegen.design.cost_field import DesignCostEvaluator
from minegen.design.development_mesh import DevelopmentMeshBuilder
from minegen.design.glb_writer import read_glb
from minegen.design.tunnel_mesh import TunnelMeshBuilder
from tests.test_curved_levels import warped, warped_levels, warped_search  # noqa: F401
from tests.test_shafts import tabular_levels  # noqa: F401
from tests.verification_support import load_fixture

JUNCTION_TYPES = ("RAMP_ACCESS", "ACCESS_DRIFT", "DRIFT_CROSSCUT")


# --------------------------------------------------------------------------- #
# GLB helpers (no glTF dependency: accessor → numpy through the raw chunk)
# --------------------------------------------------------------------------- #


def _accessor(doc: dict[str, Any], binary: bytes, index: int) -> np.ndarray:
    acc = doc["accessors"][index]
    view = doc["bufferViews"][acc["bufferView"]]
    dtype = {5126: np.float32, 5125: np.uint32, 5123: np.uint16}[acc["componentType"]]
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}[acc["type"]]
    start = int(view["byteOffset"]) + int(acc.get("byteOffset", 0))
    count = int(acc["count"]) * width
    arr = np.frombuffer(binary, dtype=dtype, count=count, offset=start)
    return arr.reshape(-1, width) if width > 1 else arr


def _glb(glb: bytes | None) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    """(positions, normals, primitives[{name, extras, indices(T,3)}])."""
    assert glb, "GLB missing"
    doc, binary = read_glb(glb)
    mesh = doc["meshes"][0]  # type: ignore[index]
    prims = []
    for p in mesh["primitives"]:
        idx = _accessor(doc, binary, p["indices"]).astype(np.int64)  # type: ignore[arg-type]
        extras = p.get("extras", {})
        role = extras.get("role")
        # identity lives in extras: a ramp SEGMENT is its segmentId, a batched
        # development tube is its kind, every cap is its role
        name = extras.get("segmentId") or (extras.get("kind") if role == "DEVELOPMENT" else role)
        prims.append(
            {
                "name": name,
                "extras": extras,
                "indices": idx.reshape(-1, 3),
                "position": p["attributes"]["POSITION"],
            }
        )
    positions = _accessor(doc, binary, prims[0]["position"])  # type: ignore[arg-type]
    normals = _accessor(doc, binary, mesh["primitives"][0]["attributes"]["NORMAL"])  # type: ignore[arg-type]
    return positions, normals, prims


def _assert_valid_triangle_set(positions: np.ndarray, tris: np.ndarray, label: str) -> None:
    """T5: finite, valid indices, non-degenerate, consistently oriented."""
    assert tris.size, label
    assert tris.min() >= 0 and tris.max() < positions.shape[0], label
    v0, v1, v2 = positions[tris[:, 0]], positions[tris[:, 1]], positions[tris[:, 2]]
    assert np.all(np.isfinite(v0)) and np.all(np.isfinite(v1)) and np.all(np.isfinite(v2)), label
    areas = 0.5 * np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1)
    assert int((areas < 1e-9).sum()) == 0, f"{label}: degenerate triangles"
    directed: dict[tuple[int, int], int] = {}
    for a, b, c in tris:
        for u, v in ((a, b), (b, c), (c, a)):
            directed[(int(u), int(v))] = directed.get((int(u), int(v)), 0) + 1
    assert all(n == 1 for n in directed.values()), f"{label}: inconsistent orientation"


# --------------------------------------------------------------------------- #
# TABULAR fixture: the cached selected layout + built levels (FAST tier)
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tabular_meshes(tabular_levels: tuple[Any, Any, dict[str, Any]]) -> dict[str, Any]:  # noqa: F811
    sc, world, levels = tabular_levels
    fx = load_fixture("tabular_small_selected")
    ramp, accesses = fx["effectiveRamp"], fx["levelAccesses"]
    before = json.dumps([ramp, accesses, levels], sort_keys=True)
    ev = DesignCostEvaluator(world, sc.design)
    cross = DesignCostEvaluator(world, sc.design, DesignContext.crosscut(sc.design))
    tunnel = TunnelMeshBuilder(ev, sc.ramp, sc.tunnel_profile).build(
        ramp, accesses_payload=accesses
    )
    dev = DevelopmentMeshBuilder(ev, cross, sc.ramp, sc.tunnel_profile).build(
        accesses, levels, ramp_payload=ramp
    )
    assert tunnel.status == "SUCCESS", tunnel.report.get("failureReason")
    assert dev.status == "SUCCESS", dev.report.get("failureReason")
    # T6 (part): the sweeps never touch their inputs — centerlines are authority
    assert json.dumps([ramp, accesses, levels], sort_keys=True) == before
    return {
        "sc": sc,
        "evaluator": ev,
        "ramp": ramp,
        "accesses": accesses,
        "levels": levels,
        "tunnel": tunnel,
        "dev": dev,
        "width": float(sc.ramp.tunnel_width),
    }


def _ok_accesses(m: dict[str, Any]) -> list[dict[str, Any]]:
    return [a for a in m["accesses"]["accesses"] if a["status"] == "OK"]


def _crosscuts(m: dict[str, Any]) -> list[dict[str, Any]]:
    return [d for d in m["levels"]["developments"] if d["kind"] == "CROSSCUT"]


def _ranges(m: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    _, _, prims = _glb(m["dev"].glb)
    prim = next(p for p in prims if p["name"] == kind)
    return list(prim["extras"]["ranges"])


def _interval_counts(entry: dict[str, Any]) -> list[int]:
    """Indices per ring interval of a SEGMENT primitive / batched range."""
    offsets = entry["ringIntervalIndexOffsets"]
    assert len(offsets) == entry["ringIntervalCount"] + 1 and offsets[0] == 0
    if "indexCount" in entry:  # batched ranges carry it; SEGMENT extras do not
        assert offsets[-1] == entry["indexCount"]
    return [int(b - a) for a, b in pairwise(offsets)]


def _cut_chainages(entry: dict[str, Any], length: float) -> list[float]:
    """Chainage (m from the piece start) of every ring interval that lost quads."""
    counts = _interval_counts(entry)
    fr = entry["ringChainageFractions"]
    nominal = _nominal_stride(entry)
    return [0.5 * (fr[i] + fr[i + 1]) * length for i, c in enumerate(counts) if c != nominal]


def _nominal_stride(entry: dict[str, Any]) -> int:
    """Indices of an UNCUT ring interval (6 × K). Phase 20D.1.2 raises
    ``indexStride`` above it when a clipped interval emits replacement
    triangles, so the nominal count — not the stride — identifies cut
    intervals."""
    return int(entry.get("nominalIndexStride", entry["indexStride"]))


def _piece_length(points: list[float]) -> float:
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    return float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())


# --------------------------------------------------------------------------- #
# T1 — RAMP → LEVEL_ACCESS
# --------------------------------------------------------------------------- #


def test_t1_ramp_to_access_junction_opens_the_turnout(tabular_meshes: dict[str, Any]) -> None:
    m = tabular_meshes
    accesses = _ok_accesses(m)
    tunnel_rep, dev_rep = m["tunnel"].report, m["dev"].report
    # identified from the declared RAMP_JUNCTION, once per OK access, on BOTH owners
    assert tunnel_rep["junctions"]["byType"] == {"RAMP_ACCESS": len(accesses)}
    assert {o["nodeId"] for o in tunnel_rep["junctions"]["openings"]} == {
        f"RAMP_JUNCTION:{a['levelId']}" for a in accesses
    }
    assert dev_rep["junctions"]["byType"]["RAMP_ACCESS"] == len(accesses)
    assert all(o["removedTriangles"] > 0 for o in tunnel_rep["junctions"]["openings"])
    # parent blocking surface removed, only inside the junction window
    _, _, prims = _glb(m["tunnel"].glb)
    segments = m["ramp"]["segments"]
    by_seg = {s["segmentId"]: s for s in segments}
    junction_chainage = {
        s["rampJunction"]["levelId"]: s["rampJunction"]["chainage"]
        for s in segments
        if s["rampJunction"]
    }
    # cumulative ramp chainage at which each segment starts (junction
    # chainages are measured along the whole ramp)
    start_of: dict[str, float] = {}
    running = 0.0
    for s in segments:
        start_of[s["segmentId"]] = running
        running += _piece_length(s["effectiveCenterline"]["points"])
    cut_segments = 0
    for p in prims:
        if p["extras"].get("role") != "SEGMENT":
            continue
        seg = by_seg[p["extras"]["segmentId"]]
        counts = _interval_counts(p["extras"])
        assert sum(counts) == p["indices"].size
        cut = [i for i, c in enumerate(counts) if c != _nominal_stride(p["extras"])]
        if not cut:
            continue
        cut_segments += 1
        # every cut interval lies within the window of a declared junction
        length = _piece_length(seg["effectiveCenterline"]["points"])
        fr = p["extras"]["ringChainageFractions"]
        start_chainage = start_of[seg["segmentId"]]
        for i in cut:
            s = start_chainage + 0.5 * (fr[i] + fr[i + 1]) * length
            assert any(abs(s - sj) <= 3.0 * m["width"] for sj in junction_chainage.values()), (
                p["name"],
                s,
            )
    assert cut_segments >= 1
    # child end open: the access's own start intervals lost their intruding quads
    for r in _ranges(m, "LEVEL_ACCESS"):
        counts = _interval_counts(r)
        assert counts[0] < _nominal_stride(r), r["pieceId"]


# --------------------------------------------------------------------------- #
# T2 — LEVEL_ACCESS → DRIFT
# --------------------------------------------------------------------------- #


def test_t2_access_to_drift_junction_opens_the_entry(tabular_meshes: dict[str, Any]) -> None:
    m = tabular_meshes
    accesses = _ok_accesses(m)
    rep = m["dev"].report
    assert rep["junctions"]["byType"]["ACCESS_DRIFT"] == len(accesses)
    assert {o["nodeId"] for o in rep["junctions"]["openings"] if o["type"] == "ACCESS_DRIFT"} == {
        f"LEVEL_ENTRY:{a['levelId']}" for a in accesses
    }
    # the access's END intervals are open (its tube inside the drift is gone)
    for r in _ranges(m, "LEVEL_ACCESS"):
        counts = _interval_counts(r)
        assert counts[-1] < _nominal_stride(r), r["pieceId"]
    # the drift lost quads only next to the entry
    entries = {a["levelId"]: np.asarray(a["levelEntry"], dtype=np.float64) for a in accesses}
    drift_pieces = {d["id"]: d for d in m["levels"]["developments"] if d["kind"] == "DRIFT"}
    cut_pieces = 0
    for r in _ranges(m, "DRIFT"):
        piece = drift_pieces[r["pieceId"]]
        pts = np.asarray(piece["centerline"]["points"], dtype=np.float64).reshape(-1, 3)
        length = _piece_length(piece["centerline"]["points"])
        for s in _cut_chainages(r, length):
            # nearest point on the piece to the cut chainage vs the entry / stations
            cut_pieces += 1
            seg_len = np.linalg.norm(np.diff(pts, axis=0), axis=1)
            cum = np.concatenate([[0.0], np.cumsum(seg_len)])
            k = int(np.searchsorted(cum, s, side="right") - 1)
            k = min(max(k, 0), len(pts) - 2)
            t = (s - cum[k]) / max(seg_len[k], 1e-12)
            at = pts[k] * (1 - t) + pts[k + 1] * t
            entry = entries[r["levelId"]]
            stations = [
                np.asarray(d["centerline"]["points"][:3], dtype=np.float64)
                for d in _crosscuts(m)
                if d["levelId"] == r["levelId"]
            ]
            near = [float(np.linalg.norm(at - q)) for q in [entry, *stations]]
            assert min(near) <= 3.0 * m["width"], (r["pieceId"], s, min(near))
    assert cut_pieces >= len(accesses)


# --------------------------------------------------------------------------- #
# T3 — DRIFT → CROSSCUT
# --------------------------------------------------------------------------- #


def test_t3_drift_to_crosscut_junction_opens_the_station(tabular_meshes: dict[str, Any]) -> None:
    m = tabular_meshes
    crosscuts = _crosscuts(m)
    rep = m["dev"].report
    assert rep["junctions"]["byType"]["DRIFT_CROSSCUT"] == len(crosscuts) > 0
    assert {
        o["childId"] for o in rep["junctions"]["openings"] if o["type"] == "DRIFT_CROSSCUT"
    } == {d["id"] for d in crosscuts}
    # every crosscut START is open into the drift; its FACE stays a cap (T4)
    for r in _ranges(m, "CROSSCUT"):
        counts = _interval_counts(r)
        assert counts[0] < _nominal_stride(r), r["pieceId"]
        assert counts[-1] == _nominal_stride(r), r["pieceId"]
        assert max(counts) <= r["indexStride"], r["pieceId"]


# --------------------------------------------------------------------------- #
# T4 — non-junction endpoints keep their CAP / OPEN contract
# --------------------------------------------------------------------------- #


def test_t4_unrelated_endpoints_keep_their_cap_contract(tabular_meshes: dict[str, Any]) -> None:
    m = tabular_meshes
    _, _, tprims = _glb(m["tunnel"].glb)
    names = [p["name"] for p in tprims]
    k_main = int(m["sc"].tunnel_profile.arch_segments) + 3
    assert names[-2:] == ["PORTAL_CAP", "TERMINAL_CAP"]
    assert tprims[-2]["indices"].shape[0] == k_main and tprims[-1]["indices"].shape[0] == k_main
    _, _, dprims = _glb(m["dev"].glb)
    by_name = {p["name"]: p for p in dprims}
    k_dev = int(m["dev"].report["profile"]["archSegments"]) + 3
    n_levels = len({d["levelId"] for d in m["levels"]["developments"] if d["kind"] == "DRIFT"})
    # drift extremities: two caps per level; crosscut face: one cap each.
    # Phase 20D.2: a drift cap that a declared crosscut junction occupies is
    # cut (omitted / clipped fans + their remainders); every other cap keeps
    # its K fan triangles, so the batched count is the K-fan total corrected
    # by the report's cap accounting
    devs = m["dev"].report["developments"]
    cap_delta = sum(
        int(d.get("renderCapReplacementTriangles", 0))
        - int(d.get("renderCapOmittedTriangles", 0))
        - int(d.get("renderCapClippedTriangles", 0))
        for d in devs
    )
    assert by_name["DRIFT_CAP"]["indices"].shape[0] == 2 * n_levels * k_dev + cap_delta
    # Phase 20D.2.1: a crosscut on a drift extremity adds its rock-facing
    # MOUTH cap to the CROSSCUT_CAP primitive; every face keeps its K fans
    mouth_total = sum(int(d.get("renderMouthCapTriangles", 0)) for d in devs)
    assert by_name["CROSSCUT_CAP"]["indices"].shape[0] == len(_crosscuts(m)) * k_dev + mouth_total
    assert "LEVEL_ACCESS_CAP" not in by_name


# --------------------------------------------------------------------------- #
# T5 — every emitted primitive is a valid oriented triangle set
# --------------------------------------------------------------------------- #


def test_t5_every_primitive_is_finite_valid_and_oriented(tabular_meshes: dict[str, Any]) -> None:
    m = tabular_meshes
    for label, result in (("tunnel", m["tunnel"]), ("development", m["dev"])):
        positions, normals, prims = _glb(result.glb)
        assert np.all(np.isfinite(positions)) and np.all(np.isfinite(normals))
        assert np.allclose(np.linalg.norm(normals, axis=1), 1.0, atol=1e-3)
        for p in prims:
            _assert_valid_triangle_set(positions, p["indices"], f"{label}:{p['name']}")


# --------------------------------------------------------------------------- #
# T6 — TABULAR regression: centerline topology / counts unchanged
# --------------------------------------------------------------------------- #


def test_t6_tabular_topology_and_counts_are_unchanged(tabular_meshes: dict[str, Any]) -> None:
    m = tabular_meshes
    accesses, crosscuts = _ok_accesses(m), _crosscuts(m)
    drift_ids = sorted(d["id"] for d in m["levels"]["developments"] if d["kind"] == "DRIFT")
    n_levels = len({d["levelId"] for d in m["levels"]["developments"] if d["kind"] == "DRIFT"})
    # one SEGMENT primitive per ramp segment, in order, caps last
    _, _, tprims = _glb(m["tunnel"].glb)
    assert [p["name"] for p in tprims[:-2]] == [s["segmentId"] for s in m["ramp"]["segments"]]
    assert len(m["tunnel"].report["segments"]) == len(m["ramp"]["segments"])
    # the development batch: kinds, counts and piece ids exactly as declared
    rep = m["dev"].report
    assert [p["name"] for p in rep["primitives"]] == [
        "LEVEL_ACCESS",
        "DRIFT",
        "DRIFT_CAP",
        "CROSSCUT",
        "CROSSCUT_CAP",
    ]
    assert rep["developmentCount"] == len(accesses) + n_levels + len(crosscuts)
    assert sorted(r["pieceId"] for r in _ranges(m, "DRIFT")) == drift_ids
    assert sorted(r["pieceId"] for r in _ranges(m, "CROSSCUT")) == sorted(
        d["id"] for d in crosscuts
    )
    assert sorted(r["pieceId"] for r in _ranges(m, "LEVEL_ACCESS")) == sorted(
        f"LEVEL_ACCESS:{a['levelId']}" for a in accesses
    )
    assert all(d["topology"]["valid"] for d in rep["developments"])
    assert all(d["envelope"]["hardViolations"] == 0 for d in rep["developments"])
    # the ramp's engineering (logical) solid stays the closed, watertight tube
    assert m["tunnel"].report["watertight"] and m["tunnel"].report["manifold"]
    # Phase 20D.1 review (public QA contract): the EMITTED render mesh is open
    # exactly because the typed apertures removed triangles, while the base
    # sweep before the cut is still closed
    trep = m["tunnel"].report
    assert trep["junctions"]["removedTriangles"] > 0
    assert trep["geometricallyClosed"] is False
    assert trep["baseSweepGeometricallyClosed"] is True
    assert rep["topologyContract"] == "LOGICAL_MESH_BEFORE_JUNCTION_APERTURES"
    cut_devs = [d for d in rep["developments"] if d["renderOmittedTriangles"] > 0]
    assert cut_devs and all(d["topology"]["valid"] for d in cut_devs)
    # Phase 20D.2: ``removedTriangles`` counts every original triangle not
    # emitted as-is — tube quads AND the end-cap fans a declared junction
    # occupies (omitted + clipped)
    assert (
        sum(
            d["renderOmittedTriangles"]
            + d["renderCapOmittedTriangles"]
            + d["renderCapClippedTriangles"]
            for d in rep["developments"]
        )
        == (rep["junctions"]["removedTriangles"])
    )


def test_t6b_no_junction_build_keeps_the_closed_contract(tabular_meshes: dict[str, Any]) -> None:
    """Without level accesses the tunnel builder cuts nothing: the emitted mesh
    IS the closed sweep and both flags agree (pre-20D.1 semantics unchanged)."""
    m = tabular_meshes
    sc = m["sc"]
    plain = TunnelMeshBuilder(m["evaluator"], sc.ramp, sc.tunnel_profile).build(m["ramp"])
    assert plain.status == "SUCCESS"
    assert plain.report["junctions"]["count"] == 0
    assert plain.report["junctions"]["removedTriangles"] == 0
    assert plain.report["geometricallyClosed"] is True
    assert plain.report["baseSweepGeometricallyClosed"] is True


# --------------------------------------------------------------------------- #
# T7 — WARPED regression (slow tier through the expensive fixture)
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def warped_meshes(warped, warped_levels) -> dict[str, Any]:  # type: ignore[no-untyped-def] # noqa: F811
    sc, world = warped
    payload, ramp, accesses = warped_levels
    assert payload.status == "SUCCESS", payload.failure_reason
    levels = payload.model_dump(mode="json", by_alias=True)
    from minegen.design.cost_field import clearance_policy_for

    policy = clearance_policy_for(world.orebody)
    ev = DesignCostEvaluator(world, sc.design, clearance=policy)
    cross = DesignCostEvaluator(
        world, sc.design, DesignContext.crosscut(sc.design), clearance=policy
    )
    tunnel = TunnelMeshBuilder(ev, sc.ramp, sc.tunnel_profile).build(
        ramp, accesses_payload=accesses
    )
    dev = DevelopmentMeshBuilder(ev, cross, sc.ramp, sc.tunnel_profile).build(
        accesses, levels, ramp_payload=ramp
    )
    return {
        "sc": sc,
        "ramp": ramp,
        "tunnel": tunnel,
        "dev": dev,
        "accesses": accesses,
        "levels": levels,
    }


def test_t7_warped_levels_and_meshes_still_succeed(warped_meshes: dict[str, Any]) -> None:
    assert warped_meshes["tunnel"].status == "SUCCESS", warped_meshes["tunnel"].report
    assert warped_meshes["dev"].status == "SUCCESS", warped_meshes["dev"].report.get(
        "failureReason"
    )
    rep = warped_meshes["dev"].report
    assert all(d["topology"]["valid"] for d in rep["developments"])
    for label, result in (("tunnel", warped_meshes["tunnel"]), ("dev", warped_meshes["dev"])):
        positions, _, prims = _glb(result.glb)
        for p in prims:
            _assert_valid_triangle_set(positions, p["indices"], f"warped {label}:{p['name']}")


def test_t7_warped_junctions_generate_on_the_curved_drift(warped_meshes: dict[str, Any]) -> None:
    rep = warped_meshes["dev"].report
    accesses = [a for a in warped_meshes["accesses"]["accesses"] if a["status"] == "OK"]
    crosscuts = [d for d in warped_meshes["levels"]["developments"] if d["kind"] == "CROSSCUT"]
    assert rep["junctions"]["byType"] == {
        "RAMP_ACCESS": len(accesses),
        "ACCESS_DRIFT": len(accesses),
        "DRIFT_CROSSCUT": len(crosscuts),
    }
    assert all(o["removedTriangles"] > 0 for o in rep["junctions"]["openings"])


# --------------------------------------------------------------------------- #
# 20D.1.1 — traversable mouth contract (hotfix). removedTriangles > 0 proved
# nothing about walkability: 20D.1's parent rule ("all four quad vertices
# strictly inside the child") never removed a VERTICAL wall quad, because a
# wall quad's bottom edge lies on the parent floor and the child floor is
# welded at (or above) that height — so every declared mouth was an arch
# window over an intact 2.5 m wall. These tests pin the real contract: the
# parent's blocking wall opens where the child passes through it, the
# parent FLOOR is never removed (it is the doorway's supporting floor), on
# EITHER side of the parent, and nothing outside the junction window moves.
# --------------------------------------------------------------------------- #
from minegen.core.models import RampConstraints, TunnelProfile  # noqa: E402
from minegen.design import development_mesh as dev_mod  # noqa: E402
from minegen.design import junctions as junction_mod  # noqa: E402
from minegen.design.junctions import Junction, JunctionCut, TubeEnvelope, cut_tube  # noqa: E402
from minegen.design.profile import ProfileShape, secondary_profile  # noqa: E402
from minegen.design.tunnel_mesh import (  # noqa: E402
    _envelope_segment,
    build_logical_mesh,
    build_profile,
    build_ring_chain,
)


def _edge_roles(shape: ProfileShape) -> tuple[int, tuple[int, int]]:
    """(floor edge, the two vertical wall edges) of a horseshoe profile, read
    from the polygon geometry: the floor edge is the unique edge whose both
    endpoints lie on the floor line (local up = 0); the walls are the two
    edges sharing exactly one floor vertex."""
    y = shape.points[:, 1]
    k = shape.k
    on_floor = np.isclose(y, 0.0, atol=1e-9)
    floor = [j for j in range(k) if on_floor[j] and on_floor[(j + 1) % k]]
    assert len(floor) == 1, floor
    f = floor[0]
    return f, ((f - 1) % k, (f + 1) % k)


def _wall_edge_on_side(shape: ProfileShape, sign: float) -> int:
    """The vertical wall edge whose floor vertex lies on the +right (sign > 0)
    or −right (sign < 0) side of the profile."""
    _, walls = _edge_roles(shape)
    for j in walls:
        xs = shape.points[[j, (j + 1) % shape.k], 0]
        if np.all(xs * sign > 0):
            return j
    raise AssertionError("no wall edge on that side")


def _parent_mouth(cut: JunctionCut, shape: ProfileShape) -> tuple[int, int, int]:
    """(wall quads removed, floor quads removed, quads removed) of a PARENT cut."""
    f, walls = _edge_roles(shape)
    return int(cut.mask[:, list(walls)].sum()), int(cut.mask[:, f].sum()), cut.removed_quads


def _capture(run: Any) -> list[JunctionCut]:
    """Run a builder with ``cut_tube`` spied on (both import sites) and return
    every JunctionCut it produced, in call order."""
    cuts: list[JunctionCut] = []
    orig = junction_mod.cut_tube

    def spy(*a: Any, **k: Any) -> JunctionCut:
        c = orig(*a, **k)
        cuts.append(c)
        return c

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(junction_mod, "cut_tube", spy)
        mp.setattr(dev_mod, "cut_tube", spy)
        run()
    return cuts


@pytest.fixture(scope="module")
def tabular_cuts(tabular_levels: tuple[Any, Any, dict[str, Any]]) -> dict[str, Any]:  # noqa: F811
    sc, world, levels = tabular_levels
    fx = load_fixture("tabular_small_selected")
    ramp, accesses = fx["effectiveRamp"], fx["levelAccesses"]
    ev = DesignCostEvaluator(world, sc.design)
    cross = DesignCostEvaluator(world, sc.design, DesignContext.crosscut(sc.design))
    tunnel_cuts = _capture(
        lambda: TunnelMeshBuilder(ev, sc.ramp, sc.tunnel_profile).build(
            ramp, accesses_payload=accesses
        )
    )
    dev_cuts = _capture(
        lambda: DevelopmentMeshBuilder(ev, cross, sc.ramp, sc.tunnel_profile).build(
            accesses, levels, ramp_payload=ramp
        )
    )
    return {
        "sc": sc,
        "accesses": accesses,
        "levels": levels,
        "tunnel_cuts": tunnel_cuts,
        "dev_cuts": dev_cuts,
        "main_shape": build_profile(sc.ramp, sc.tunnel_profile),
        "dev_shape": build_profile(sc.ramp, secondary_profile(sc.tunnel_profile)),
    }


def _parent_cuts(cuts: list[JunctionCut], jtype: str) -> list[JunctionCut]:
    return [c for c in cuts if c.junction.type == jtype and c.side == "PARENT"]


def test_t1b_every_ramp_access_opens_the_ramp_wall_and_keeps_the_ramp_floor(
    tabular_cuts: dict[str, Any],
) -> None:
    m = tabular_cuts
    cuts = _parent_cuts(m["tunnel_cuts"], "RAMP_ACCESS")
    n_ok = sum(1 for a in m["accesses"]["accesses"] if a["status"] == "OK")
    assert len(cuts) == n_ok > 0
    for c in cuts:
        wall, floor, total = _parent_mouth(c, m["main_shape"])
        assert total > 0, c.junction.node_id
        assert wall > 0, f"{c.junction.node_id}: ramp wall still blocks the access mouth"
        assert floor == 0, f"{c.junction.node_id}: ramp floor removed ({floor} quads)"


def test_t2b_every_access_drift_opens_the_drift_wall_and_keeps_the_drift_floor(
    tabular_cuts: dict[str, Any],
) -> None:
    m = tabular_cuts
    cuts = _parent_cuts(m["dev_cuts"], "ACCESS_DRIFT")
    n_ok = sum(1 for a in m["accesses"]["accesses"] if a["status"] == "OK")
    assert len(cuts) == n_ok > 0
    for c in cuts:
        wall, floor, _ = _parent_mouth(c, m["dev_shape"])
        assert wall > 0, f"{c.junction.node_id}: drift wall still blocks the access mouth"
        assert floor == 0, f"{c.junction.node_id}: drift floor removed ({floor} quads)"


def test_t3b_every_drift_crosscut_opens_the_drift_wall_and_keeps_the_drift_floor(
    tabular_cuts: dict[str, Any],
) -> None:
    m = tabular_cuts
    cuts = _parent_cuts(m["dev_cuts"], "DRIFT_CROSSCUT")
    n_cc = sum(1 for d in m["levels"]["developments"] if d["kind"] == "CROSSCUT")
    assert len(cuts) == n_cc > 0
    for c in cuts:
        wall, floor, _ = _parent_mouth(c, m["dev_shape"])
        assert wall > 0, f"{c.junction.node_id}: drift wall still blocks the crosscut mouth"
        assert floor == 0, f"{c.junction.node_id}: drift floor removed ({floor} quads)"


def test_child_side_semantics_unchanged(tabular_cuts: dict[str, Any]) -> None:
    """The child still loses its intruding shell INCLUDING its floor and both
    walls inside the parent (inside-or-on rule); the hotfix touches the
    parent side only."""
    m = tabular_cuts
    f, walls = _edge_roles(m["dev_shape"])
    for c in [x for x in m["dev_cuts"] if x.side == "CHILD" and x.junction.type == "RAMP_ACCESS"]:
        assert c.mask[:, f].any(), c.junction.node_id
        assert c.mask[:, list(walls)].any(), c.junction.node_id


def _straight_tube(
    p0: tuple[float, float, float], p1: tuple[float, float, float], shape: ProfileShape
) -> tuple[TubeEnvelope, np.ndarray, Any]:
    chain = build_ring_chain([_envelope_segment([*p0, *p1])], 0.5)
    mesh = build_logical_mesh(chain, shape)
    rings = mesh.positions[: mesh.ring_count * mesh.k].reshape(mesh.ring_count, mesh.k, 3)
    return TubeEnvelope.build(chain.centers, chain.tangents, shape), rings, chain


@pytest.mark.parametrize(
    ("side_sign", "floor_lift", "expect_open"),
    [
        (+1.0, 0.0, True),  # T-junction, coincident floors, child to the right
        (-1.0, 0.0, True),  # …and to the left (no hard-coded wall edge)
        (+1.0, 0.3, True),  # child floor a sill above the parent floor (turnout case)
        (-1.0, 0.6, True),  # bottom sample row below the child floor: 2/3 of the wall still inside
        (+1.0, 2.0, False),  # child floor at chest height: no meaningful wall overlap → wall kept
    ],
)
def test_synthetic_parent_wall_opens_on_the_child_side_floor_stays(
    side_sign: float, floor_lift: float, expect_open: bool
) -> None:
    shape = build_profile(RampConstraints(), TunnelProfile())
    width = float(RampConstraints().tunnel_width)
    parent_env, parent_rings, chain = _straight_tube((0.0, -30.0, 0.0), (0.0, 30.0, 0.0), shape)
    child_env, _, _ = _straight_tube(
        (0.0, 0.0, floor_lift), (side_sign * 30.0, 0.0, floor_lift), shape
    )
    j = Junction(
        type="DRIFT_CROSSCUT",
        node_id="JUNCTION:L:S+00",
        parent_id="DRIFT:L",
        child_id="CROSSCUT:L:S+00",
        point=np.array([0.0, 0.0, floor_lift]),
        child_end="start",
        level_id="L",
    )
    cut = cut_tube(parent_env, parent_rings, child_env, j, "PARENT", width)
    f, _ = _edge_roles(shape)
    near = _wall_edge_on_side(shape, side_sign)
    far = _wall_edge_on_side(shape, -side_sign)
    assert bool(cut.mask[:, near].any()) is expect_open
    assert not cut.mask[:, far].any()  # the opposite wall is never touched
    assert not cut.mask[:, f].any()  # the parent floor is never removed
    # locality (M5): only intervals under the child's footprint (± one ring)
    rows = np.where(cut.mask.any(axis=1))[0]
    ys = chain.centers[:, 1]
    if rows.size:
        assert np.all(np.abs(ys[rows]) <= width / 2 + 1.0)
        assert rows.min() >= cut.window_rings[0] and rows.max() < cut.window_rings[1]


@pytest.fixture(scope="module")
def warped_cuts(warped, warped_levels) -> dict[str, Any]:  # type: ignore[no-untyped-def] # noqa: F811
    sc, world = warped
    payload, ramp, accesses = warped_levels
    assert payload.status == "SUCCESS", payload.failure_reason
    levels = payload.model_dump(mode="json", by_alias=True)
    from minegen.design.cost_field import clearance_policy_for

    policy = clearance_policy_for(world.orebody)
    ev = DesignCostEvaluator(world, sc.design, clearance=policy)
    cross = DesignCostEvaluator(
        world, sc.design, DesignContext.crosscut(sc.design), clearance=policy
    )
    tunnel_cuts = _capture(
        lambda: TunnelMeshBuilder(ev, sc.ramp, sc.tunnel_profile).build(
            ramp, accesses_payload=accesses
        )
    )
    dev_cuts = _capture(
        lambda: DevelopmentMeshBuilder(ev, cross, sc.ramp, sc.tunnel_profile).build(
            accesses, levels, ramp_payload=ramp
        )
    )
    return {
        "tunnel_cuts": tunnel_cuts,
        "dev_cuts": dev_cuts,
        "main_shape": build_profile(sc.ramp, sc.tunnel_profile),
        "dev_shape": build_profile(sc.ramp, secondary_profile(sc.tunnel_profile)),
    }


def test_t7c_warped_every_parent_wall_opens_and_every_parent_floor_stays(
    warped_cuts: dict[str, Any],
) -> None:
    """The mouth contract is not a TABULAR special case: on the curved
    WARPED-301 development every declared junction of every type opens the
    parent's vertical wall and keeps the parent floor."""
    m = warped_cuts
    ramp_cuts = _parent_cuts(m["tunnel_cuts"], "RAMP_ACCESS")
    assert ramp_cuts
    for c in ramp_cuts:
        wall, floor, _ = _parent_mouth(c, m["main_shape"])
        assert wall > 0 and floor == 0, (c.junction.node_id, wall, floor)
    for jtype in ("ACCESS_DRIFT", "DRIFT_CROSSCUT"):
        cuts = _parent_cuts(m["dev_cuts"], jtype)
        assert cuts, jtype
        for c in cuts:
            wall, floor, _ = _parent_mouth(c, m["dev_shape"])
            assert wall > 0 and floor == 0, (jtype, c.junction.node_id, wall, floor)


# --------------------------------------------------------------------------- #
# Phase 20D.1.2 — child-floor boundary clipping (contracts A–D)
# --------------------------------------------------------------------------- #
#
# The 20D.1 CHILD rule decided every quad whole (four vertices inside-or-on
# the parent → omit, else keep). The child profile floor is ONE edge across
# the tunnel width, so at a shallow RAMP_ACCESS turnout a floor quad that
# straddles the parent wall was kept whole and its inside part formed a
# floating slab across the ramp (0.7–1.6 m above the descending floor at
# its far edge). These contracts inspect the EMITTED geometry, never the mask.

from minegen.design.development_mesh import (  # noqa: E402
    chain_segments,
    specs_from_artifacts,
)
from minegen.design.junctions import (  # noqa: E402
    JUNCTION_RING_SPACING_FRACTION,
    JUNCTION_SURFACE_TOLERANCE_FRACTION,
    JUNCTION_WINDOW_WIDTHS,
    find_junctions,
)
from minegen.design.tunnel_mesh import build_render_mesh  # noqa: E402

FLOOR_NORMAL_Z_MAX = -0.9  # outward normal of a floor triangle points down


def _tri_geometry(
    positions: np.ndarray, tris: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(centroids (T,3), areas (T,), unit normals (T,3)) of triangle rows."""
    v0, v1, v2 = positions[tris[:, 0]], positions[tris[:, 1]], positions[tris[:, 2]]
    n = np.cross(v1 - v0, v2 - v0)
    area = 0.5 * np.linalg.norm(n, axis=1)
    unit = n / np.maximum(2.0 * area[:, None], 1e-18)
    return (v0 + v1 + v2) / 3.0, area, unit


def _builder_envelopes(m: dict[str, Any]) -> tuple[dict[str, TubeEnvelope], list[Junction]]:
    """The SAME envelopes the development builder judges against (its own
    construction: refined ring chains near the declared junction points, main
    profile for the ramp, secondary profile for developments)."""
    sc = m["sc"]
    width = float(sc.ramp.tunnel_width)
    junctions = find_junctions(m["ramp"], m["accesses"], m["levels"])
    near: dict[str, list[np.ndarray]] = {}
    for j in junctions:
        near.setdefault(j.parent_id, []).append(j.point)
        near.setdefault(j.child_id, []).append(j.point)
    dev_profile = secondary_profile(sc.tunnel_profile)
    dev_shape = build_profile(sc.ramp, dev_profile)
    envs: dict[str, TubeEnvelope] = {}
    for spec in specs_from_artifacts(m["accesses"], m["levels"]):
        pts = near.get(spec.development_id)
        chain = build_ring_chain(
            chain_segments(spec),
            dev_profile.ring_max_spacing,
            refine_near=np.asarray(pts, dtype=np.float64) if pts else None,
            refine_radius=JUNCTION_WINDOW_WIDTHS * width,
            refine_spacing=JUNCTION_RING_SPACING_FRACTION * width,
        )
        envs[spec.development_id] = TubeEnvelope.build(chain.centers, chain.tangents, dev_shape)
    main_shape = build_profile(sc.ramp, sc.tunnel_profile)
    pts = near.get("RAMP")
    ramp_chain = build_ring_chain(
        m["ramp"]["segments"],
        sc.tunnel_profile.ring_max_spacing,
        refine_near=np.asarray(pts, dtype=np.float64) if pts else None,
        refine_radius=JUNCTION_WINDOW_WIDTHS * width,
        refine_spacing=JUNCTION_RING_SPACING_FRACTION * width,
    )
    envs["RAMP"] = TubeEnvelope.build(ramp_chain.centers, ramp_chain.tangents, main_shape)
    return envs, junctions


def _child_floor_tris(m: dict[str, Any], child_id: str) -> tuple[np.ndarray, np.ndarray]:
    """(positions, floor triangle rows) of ONE development in the emitted GLB."""
    positions, _, prims = _glb(m["dev"].glb)
    kind = child_id.split(":")[0]
    prim = next(p for p in prims if p["name"] == kind)
    rows = []
    for r in prim["extras"]["ranges"]:
        if r["developmentId"] != child_id:
            continue
        a = int(r["indexOffset"]) // 3
        b = (int(r["indexOffset"]) + int(r["indexCount"])) // 3
        rows.append(prim["indices"][a:b])
    tris = np.concatenate(rows)
    _, _, normal = _tri_geometry(positions, tris)
    return positions, tris[normal[:, 2] < FLOOR_NORMAL_Z_MAX]


def tol_of(m: dict[str, Any]) -> float:
    return JUNCTION_SURFACE_TOLERANCE_FRACTION * float(m["sc"].ramp.tunnel_width)


def _child_floor_audit(
    m: dict[str, Any], j: Junction, envs: dict[str, TubeEnvelope]
) -> dict[str, float]:
    """Contract A metric on the EMITTED child floor near one junction: the
    area of child floor triangles whose centroid lies strictly inside the
    parent envelope (beyond the union tolerance), the deepest such vertex,
    and the retained floor area outside the parent, all within the window."""
    width = float(m["sc"].ramp.tunnel_width)
    tol = JUNCTION_SURFACE_TOLERANCE_FRACTION * width
    radius = JUNCTION_WINDOW_WIDTHS * width
    parent = envs[j.parent_id]
    window = parent.ring_window(j.point, radius + width)
    positions, floor = _child_floor_tris(m, j.child_id)
    centroids, areas, _ = _tri_geometry(positions, floor)
    local = np.linalg.norm(centroids - j.point[None, :], axis=1) <= radius + width
    centroids, areas, floor = centroids[local], areas[local], floor[local]
    sd = parent.signed_distance(centroids, window)
    inside = sd < -tol
    # depth of the emitted SURFACE: interior samples (centroid + edge midpoints)
    # — polygon vertices legitimately sit ON the boundary (the tolerance
    # surface, or the parent's terminal plane where its rings end)
    v = positions[floor].astype(np.float64)  # (T, 3, 3)
    mids = [0.5 * (v[:, a] + v[:, b]) for a, b in ((0, 1), (1, 2), (2, 0))]
    # strictly interior: edge midpoints pulled 10 % toward the centroid, so a
    # sample never lies ON a boundary edge of the triangle
    interior = np.concatenate([centroids, *[0.9 * mid + 0.1 * centroids for mid in mids]])
    sdi = parent.signed_distance(interior, window) if interior.size else np.zeros(0)
    return {
        "insideArea": float(areas[inside].sum()),
        "insideTriangles": int(inside.sum()),
        "maxDepth": float(max(0.0, -sdi.min())) if sdi.size else 0.0,
        "outsideArea": float(areas[sd > tol].sum()),
        "localTriangles": int(floor.shape[0]),
    }


@pytest.fixture(scope="module")
def tabular_envelopes(
    tabular_meshes: dict[str, Any],
) -> tuple[dict[str, TubeEnvelope], list[Junction]]:
    return _builder_envelopes(tabular_meshes)


def test_p20d12_a_no_child_floor_remains_inside_the_parent_tabular(
    tabular_meshes: dict[str, Any],
    tabular_envelopes: tuple[dict[str, TubeEnvelope], list[Junction]],
) -> None:
    """Contract A (RED on the 20D.1.1 base): at every declared junction of
    every type, the emitted CHILD floor keeps no surface strictly inside the
    parent excavation — the false slab is gone — while the floor OUTSIDE the
    parent is still present (M2 / M6 kill: deleting the whole straddling quad
    would empty the outside area at the mouth)."""
    m = tabular_meshes
    envs, junctions = tabular_envelopes
    assert junctions
    seen_types: set[str] = set()
    for j in junctions:
        audit = _child_floor_audit(m, j, envs)
        seen_types.add(j.type)
        assert audit["insideArea"] == 0.0, (j.type, j.node_id, audit)
        assert audit["maxDepth"] <= tol_of(m), (j.type, j.node_id, audit)
        if j.type == "RAMP_ACCESS":
            assert audit["outsideArea"] > 0.0, (j.node_id, audit)
    assert seen_types == set(JUNCTION_TYPES)


def test_p20d12_a_report_and_reveal_accounting_tabular(tabular_meshes: dict[str, Any]) -> None:
    """Every RAMP_ACCESS junction clips at least one child floor quad; the
    parent floor is never removed; per-range reveal metadata stays exact
    (offsets sum to the emitted count, every delta ≤ indexStride,
    indexStride ≥ the nominal 6 × K) and the omitted / replacement
    accounting balances the emitted index counts (M8)."""
    m = tabular_meshes
    rep = m["dev"].report
    ramp_openings = [o for o in rep["junctions"]["openings"] if o["type"] == "RAMP_ACCESS"]
    assert ramp_openings
    for o in ramp_openings:
        assert o["childClippedFloorQuads"] > 0, o["nodeId"]
        assert o["childReplacementTriangles"] > 0, o["nodeId"]
        assert o["childClippedFloorTriangles"] == 2 * o["childClippedFloorQuads"]
    for o in rep["junctions"]["openings"]:
        assert o["parentFloorTriangles"] == 0, o["nodeId"]
    clipped_devs = [d for d in rep["developments"] if d["renderClippedFloorQuads"] > 0]
    assert clipped_devs
    for d in rep["developments"]:
        assert d["renderOmittedTriangles"] >= 2 * d["renderClippedFloorQuads"]
    for kind in ("LEVEL_ACCESS", "DRIFT", "CROSSCUT"):
        for r in _ranges(m, kind):
            counts = _interval_counts(r)
            nominal = _nominal_stride(r)
            assert r["indexStride"] >= nominal
            assert max(counts) <= r["indexStride"], r["pieceId"]
            assert sum(nominal - c for c in counts) == 3 * (
                r["omittedTriangles"] - r["replacementTriangles"]
            ), r["pieceId"]
            if r["clippedQuads"]:
                assert r["replacementTriangles"] >= r["clippedQuads"]


def _raycast_first(
    tris: np.ndarray, labels: np.ndarray, origin: np.ndarray, direction: np.ndarray, far: float
) -> tuple[float, str] | None:
    """Nearest Möller–Trumbore hit of a ray against (T,3,3) triangles."""
    v0, v1, v2 = tris[:, 0], tris[:, 1], tris[:, 2]
    e1, e2 = v1 - v0, v2 - v0
    p = np.cross(direction, e2)
    det = np.einsum("ij,ij->i", e1, p)
    ok = np.abs(det) > 1e-12
    inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    tv = origin - v0
    u = np.einsum("ij,ij->i", tv, p) * inv
    q = np.cross(tv, e1)
    v = np.einsum("j,ij->i", direction, q) * inv
    t = np.einsum("ij,ij->i", e2, q) * inv
    hit = ok & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & (t > 1e-6) & (t < far)
    if not hit.any():
        return None
    k = int(np.flatnonzero(hit)[np.argmin(t[hit])])
    return float(t[k]), str(labels[k])


def _emitted_triangles(m: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """All emitted triangles (T,3,3) of the tunnel + development GLBs with a
    provenance label per triangle (SEGMENT / DEVELOPMENT:<kind> / caps)."""
    tri_sets: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    for result in (m["tunnel"], m["dev"]):
        positions, _, prims = _glb(result.glb)
        for p in prims:
            role = p["extras"].get("role")
            label = f"{role}:{p['extras'].get('kind') or p['extras'].get('segmentId') or ''}"
            tri_sets.append(positions[p["indices"]].astype(np.float64))
            labels.append(np.full(p["indices"].shape[0], label))
    return np.concatenate(tri_sets), np.concatenate(labels)


def _ramp_corridor_probe(m: dict[str, Any], level_id: str) -> list[dict[str, Any]]:
    """Contract C: downward rays along the parent ramp travel surface through
    and beyond the RAMP_ACCESS turnout (−2 … +16 m from the junction along
    the ramp centerline, at five lateral offsets inside the ramp). Returns
    the first-hit provenance of every probe."""
    tris, labels = _emitted_triangles(m)
    width = float(m["sc"].ramp.tunnel_width)
    access = next(a for a in _ok_accesses(m) if a["levelId"] == level_id)
    junction = np.asarray(access["rampJunction"], dtype=np.float64)
    rp: list[np.ndarray] = []
    for seg in m["ramp"]["segments"]:
        pts = np.asarray(seg["effectiveCenterline"]["points"], dtype=np.float64).reshape(-1, 3)
        rp.extend(pts if not rp else pts[1:])
    ramp = np.asarray(rp)
    seg_len = np.linalg.norm(np.diff(ramp, axis=0), axis=1)
    chainage = np.concatenate([[0.0], np.cumsum(seg_len)])
    i_j = int(np.argmin(np.linalg.norm(ramp - junction[None, :], axis=1)))
    out: list[dict[str, Any]] = []
    for s in np.arange(-2.0, 16.01, 1.0):
        target = chainage[i_j] + s
        i = int(np.clip(np.searchsorted(chainage, target), 1, len(ramp) - 1))
        t = (target - chainage[i - 1]) / max(chainage[i] - chainage[i - 1], 1e-9)
        center = ramp[i - 1] + t * (ramp[i] - ramp[i - 1])
        d = ramp[i] - ramp[i - 1]
        d[2] = 0.0
        d /= np.linalg.norm(d)
        left = np.array([-d[1], d[0], 0.0])
        for lat in (-0.4 * width, -0.2 * width, 0.0, 0.2 * width, 0.4 * width):
            origin = center + lat * left + np.array([0.0, 0.0, 2.5])
            hit = _raycast_first(tris, labels, origin, np.array([0.0, 0.0, -1.0]), 10.0)
            out.append(
                {
                    "chainageFromJunction": float(s),
                    "lateral": float(lat),
                    "hit": hit[1] if hit else None,
                    "floorZ": float(origin[2] - hit[0]) if hit else None,
                    "rampZ": float(center[2]),
                }
            )
    return out


@pytest.mark.parametrize("level_id", ["L01", "L02"])
def test_p20d12_c_parent_ramp_travel_surface_is_never_a_child_floor_tabular(
    tabular_meshes: dict[str, Any], level_id: str
) -> None:
    """Contract C (RED on the base): along the ramp corridor through and past
    the turnout, the first surface under every probe is the RAMP's own floor
    — never a retained LEVEL_ACCESS floor (the slab), never nothing."""
    probes = _ramp_corridor_probe(tabular_meshes, level_id)
    assert probes
    bad = [p for p in probes if p["hit"] is None or not p["hit"].startswith("SEGMENT:")]
    assert not bad, bad[:6]


def _straight_tube_mesh(
    p0: tuple[float, float, float],
    p1: tuple[float, float, float],
    shape: ProfileShape,
    spacing: float = 0.5,
) -> tuple[TubeEnvelope, np.ndarray, Any, Any]:
    chain = build_ring_chain([_envelope_segment([*p0, *p1])], spacing)
    mesh = build_logical_mesh(chain, shape)
    rings = mesh.positions[: mesh.ring_count * mesh.k].reshape(mesh.ring_count, mesh.k, 3)
    return TubeEnvelope.build(chain.centers, chain.tangents, shape), rings, chain, mesh


def _polygon_area(poly: np.ndarray) -> float:
    c = poly.mean(axis=0)
    n = np.zeros(3)
    for a, b in zip(poly, np.roll(poly, -1, axis=0), strict=True):
        n += np.cross(a - c, b - c)
    return 0.5 * float(np.linalg.norm(n))


@pytest.mark.parametrize(
    ("side_sign", "floor_lift"),
    [(+1.0, 0.0), (-1.0, 0.0), (+1.0, 0.3), (-1.0, 0.45)],
)
def test_p20d12_b_straddling_child_floor_quad_is_clipped_not_decided_whole(
    side_sign: float, floor_lift: float
) -> None:
    """Contract B: a child (along ±X, rings at |x| = 0.2 + 0.5 n) crosses the
    parent wall (|x| = w/2) so the floor quad between |x| = 2.2 and 2.7
    straddles the tolerance boundary |x| = w/2 + tol = 2.6. Required: the
    inside portion is absent and ONLY the outside remainder (0.1 m × w) is
    emitted — M1 (keep whole → a slab inside) and M2 (drop whole → a hole
    outside) both fail this test; the far side and the window bounds are
    untouched (M4 / M5)."""
    shape = build_profile(RampConstraints(), TunnelProfile())
    width = float(RampConstraints().tunnel_width)
    tol = JUNCTION_SURFACE_TOLERANCE_FRACTION * width
    parent_env, _, _, _ = _straight_tube_mesh((0.0, -30.0, 0.0), (0.0, 30.0, 0.0), shape)
    child_env, child_rings, child_chain, child_mesh = _straight_tube_mesh(
        (side_sign * 0.2, 0.0, floor_lift), (side_sign * 30.2, 0.0, floor_lift), shape
    )
    j = Junction(
        type="DRIFT_CROSSCUT",
        node_id="JUNCTION:L:S+00",
        parent_id="DRIFT:L",
        child_id="CROSSCUT:L:S+00",
        point=np.array([side_sign * 0.2, 0.0, floor_lift]),
        child_end="start",
        level_id="L",
    )
    cut = cut_tube(child_env, child_rings, parent_env, j, "CHILD", width)
    f, _ = _edge_roles(shape)
    boundary = width / 2 + tol  # |x| of the tolerance surface
    xs = np.abs(child_chain.centers[:, 0])
    # both ends inside-or-on: omitted; both ends outside: kept; straddling: clipped
    for i in range(child_rings.shape[0] - 1):
        lo, hi = xs[i], xs[i + 1]
        if hi <= boundary + 1e-9:
            assert cut.mask[i, f], (i, lo, hi)
        elif lo >= boundary - 1e-9:
            assert not cut.mask[i, f], (i, lo, hi)
    straddle = [c for c in cut.floor_clips if c.edge == f]
    assert len(straddle) == 1, [(c.interval, c.edge) for c in cut.floor_clips]
    clip = straddle[0]
    assert xs[clip.interval] < boundary < xs[clip.interval + 1]
    assert not cut.mask[clip.interval, f]
    assert len(clip.polygons) == 1
    poly = clip.polygons[0]
    window = parent_env.ring_window(j.point, JUNCTION_WINDOW_WIDTHS * width + width)
    sd = parent_env.signed_distance(poly, window)
    assert np.all(sd >= tol - 1e-6), sd  # nothing of the remainder inside the parent
    expected = (xs[clip.interval + 1] - boundary) * width
    assert abs(_polygon_area(poly) - expected) < 1e-3, (_polygon_area(poly), expected)
    # the remainder is emitted: replacement triangles, exact reveal offsets,
    # no degenerate triangle, orientation consistent with the tube
    render = build_render_mesh(
        child_mesh,
        child_chain,
        shape,
        TunnelProfile().crease_angle_deg,
        [{"segmentId": "CROSSCUT:L:S+00", "effectiveSource": "CROSSCUT"}],
        caps=(False, True),
        quad_mask=cut.mask,
        floor_clips={(c.interval, c.edge): c for c in cut.floor_clips},
    )
    seg = render.primitives[0]
    assert seg.extras["clippedQuads"] == 1 and seg.extras["replacementTriangles"] >= 1
    assert seg.extras["omittedTriangles"] == 2 * int(cut.mask.sum()) + 2
    counts = [b - a for a, b in pairwise(seg.extras["ringIntervalIndexOffsets"])]
    assert sum(counts) == seg.indices.size
    assert max(counts) <= seg.extras["indexStride"]
    assert seg.extras["indexStride"] >= seg.extras["nominalIndexStride"] == 6 * shape.k
    tris = seg.indices.reshape(-1, 3)
    _assert_valid_triangle_set(render.positions.astype(np.float64), tris, "clipped child")
    centroids, areas, normal = _tri_geometry(render.positions.astype(np.float64), tris)
    floor = normal[:, 2] < FLOOR_NORMAL_Z_MAX
    sd_c = parent_env.signed_distance(centroids[floor], window)
    assert not np.any(sd_c < -tol), "child floor emitted inside the parent"
    # legitimate child floor outside the parent: whole outside quads + the remainder
    outside_expected = (
        sum(
            (xs[i + 1] - xs[i]) * width
            for i in range(child_rings.shape[0] - 1)
            if xs[i] >= boundary - 1e-9
        )
        + expected
    )
    assert abs(float(areas[floor][sd_c > tol].sum()) - outside_expected) < 1e-2


def test_p20d12_b_uncut_render_is_bit_identical_without_clips() -> None:
    """``floor_clips`` absent (None or empty) leaves every pre-existing caller
    bit-for-bit unaffected."""
    shape = build_profile(RampConstraints(), TunnelProfile())
    _, _, chain, mesh = _straight_tube_mesh((0.0, 0.0, 0.0), (12.0, 0.0, 0.0), shape)
    meta = [{"segmentId": "S", "effectiveSource": "DRIFT"}]
    a = build_render_mesh(mesh, chain, shape, 30.0, meta)
    b = build_render_mesh(mesh, chain, shape, 30.0, meta, floor_clips={})
    assert np.array_equal(a.positions, b.positions)
    assert all(
        np.array_equal(x.indices, y.indices) and x.extras == y.extras
        for x, y in zip(a.primitives, b.primitives, strict=True)
    )
    assert a.primitives[0].extras["indexStride"] == a.primitives[0].extras["nominalIndexStride"]
    assert a.primitives[0].extras["clippedQuads"] == 0


def test_p20d12_clip_never_leaves_the_window_or_touches_non_floor_edges_tabular(
    tabular_cuts: dict[str, Any],
) -> None:
    """M5 / scope: clips exist only on the floor edge; inside the junction
    window or on the contiguous floor pass beyond it on the junction's away
    side (never on the far end of the child, never on a non-floor edge);
    every clip's polygons are finite loops of ≥ 3 vertices with positive
    area; PARENT cuts never clip."""
    m = tabular_cuts
    f, _ = _edge_roles(m["dev_shape"])
    child_cuts = [c for c in m["dev_cuts"] if c.side == "CHILD"]
    assert any(c.floor_clips for c in child_cuts)
    for c in child_cuts:
        lo, hi = c.window_rings
        rows = c.mask.shape[0]
        for clip in c.floor_clips:
            assert clip.edge == f
            assert 0 <= clip.interval < rows
            if not (lo <= clip.interval < hi - 1):
                # beyond the window only in the direction the child continues
                if c.junction.child_end == "start":
                    assert clip.interval >= hi - 1, (
                        c.junction.node_id,
                        clip.interval,
                        c.window_rings,
                    )
                else:
                    assert clip.interval < lo, (c.junction.node_id, clip.interval, c.window_rings)
            assert not c.mask[clip.interval, clip.edge]
            for poly in clip.polygons:
                assert poly.shape[0] >= 3 and np.all(np.isfinite(poly))
                assert _polygon_area(poly) > 1e-9
        # non-floor edges are never touched outside the window
        outside = np.ones(rows, dtype=bool)
        outside[lo : max(hi - 1, lo)] = False
        assert not c.mask[outside][:, [e for e in range(c.mask.shape[1]) if e != f]].any()
    for c in [x for x in m["dev_cuts"] if x.side == "PARENT"]:
        assert not c.floor_clips


@pytest.fixture(scope="module")
def warped_meshes_env(
    warped_meshes: dict[str, Any],
) -> tuple[dict[str, TubeEnvelope], list[Junction]]:
    return _builder_envelopes(warped_meshes)


def test_p20d12_d_warped_child_floor_and_ramp_corridor(
    warped_meshes: dict[str, Any],
    warped_meshes_env: tuple[dict[str, TubeEnvelope], list[Junction]],
) -> None:
    """Contract D: the same child-floor and ramp-corridor contracts on the
    curved WARPED-301 development (RAMP_ACCESS L03 / L04 included)."""
    m = warped_meshes
    envs, junctions = warped_meshes_env
    ramp_levels = {j.level_id for j in junctions if j.type == "RAMP_ACCESS"}
    assert {"L03", "L04"} <= ramp_levels
    for j in junctions:
        audit = _child_floor_audit(m, j, envs)
        assert audit["insideArea"] == 0.0, (j.type, j.node_id, audit)
        assert audit["maxDepth"] <= tol_of(m), (j.type, j.node_id, audit)
        if j.type == "RAMP_ACCESS":
            assert audit["outsideArea"] > 0.0, (j.node_id, audit)
    for level_id in ("L03", "L04"):
        probes = _ramp_corridor_probe(m, level_id)
        bad = [p for p in probes if p["hit"] is None or not p["hit"].startswith("SEGMENT:")]
        assert not bad, (level_id, bad[:6])


# --------------------------------------------------------------------------- #
# Phase 20D.2 §10 — a DRIFT_CAP never stands inside a declared crosscut mouth
# --------------------------------------------------------------------------- #


def _extremity_crosscut_junctions(
    m: dict[str, Any], envs: dict[str, TubeEnvelope], junctions: list[Junction]
) -> list[Junction]:
    """DRIFT_CROSSCUT junctions whose point lies within one tunnel width of a
    drift END ring (the TABULAR station lattice reaches the drift ends)."""
    width = m["width"]
    out: list[Junction] = []
    for j in junctions:
        if j.type != "DRIFT_CROSSCUT":
            continue
        env = envs[j.parent_id]
        d = min(
            float(np.linalg.norm(env.centers[0] - j.point)),
            float(np.linalg.norm(env.centers[-1] - j.point)),
        )
        if d <= width:
            out.append(j)
    return out


def _triangle_area(tris: np.ndarray) -> float:
    return float(
        0.5
        * np.linalg.norm(np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]), axis=1).sum()
    )


def test_p20d2_drift_cap_never_stands_inside_a_declared_crosscut_junction_tabular(
    tabular_meshes: dict[str, Any],
) -> None:
    """§10 endpoint-cap audit, pinned: at a station on the drift EXTREMITY the
    crosscut's axis lies in the DRIFT_CAP plane, so the cap's crosscut-side
    half stood inside the crosscut mouth (measured: every extremity station of
    the acceptance fixtures hit DRIFT_CAP at 0.4–1.4 m on the drift↔crosscut
    path). The emitted cap must keep the end wall OUTSIDE the crosscut and
    nothing INSIDE it — a typed local cut at the declared junction, never a
    blanket cap omission."""
    m = tabular_meshes
    envs, junctions = _builder_envelopes(m)
    tris, labels = _emitted_triangles(m)
    caps = tris[labels == "DRIFT_CAP:DRIFT"]
    width, tol = m["width"], tol_of(m)
    full_cap_area = float(m["dev"].report["profile"]["meshProfileArea"])
    ext = _extremity_crosscut_junctions(m, envs, junctions)
    assert ext, "the TABULAR station lattice reaches the drift ends"
    for j in ext:
        child = envs[j.child_id]
        window = child.ring_window(j.point, (JUNCTION_WINDOW_WIDTHS + 1.0) * width)
        near = caps[np.linalg.norm(caps.mean(axis=1) - j.point[None, :], axis=1) < 2.0 * width]
        # the end wall still exists on the rock side: no blanket cap removal
        assert _triangle_area(near) >= 0.4 * full_cap_area, j.node_id
        # (1) no emitted cap surface inside the crosscut excavation: centroids
        # and edge midpoints inset 5 % toward the centroid — the remainder's
        # chord lies ON the crosscut's open start plane (a measure-zero
        # boundary where the envelope distance is discontinuous), which is
        # the end wall meeting the mouth, not surface inside it
        centroid = near.mean(axis=1)
        samples = np.concatenate(
            [
                centroid,
                0.95 * 0.5 * (near[:, 0] + near[:, 1]) + 0.05 * centroid,
                0.95 * 0.5 * (near[:, 1] + near[:, 2]) + 0.05 * centroid,
                0.95 * 0.5 * (near[:, 2] + near[:, 0]) + 0.05 * centroid,
            ]
        )
        sd = child.signed_distance(samples, window)
        assert not np.any(sd < -tol), (
            f"{j.node_id}: {int((sd < -tol).sum())} DRIFT_CAP samples inside the crosscut"
        )
        # (2) the drift → crosscut traffic line is not obstructed by the cap
        cc = next(d for d in m["levels"]["developments"] if d["id"] == j.child_id)
        pts = np.asarray(cc["centerline"]["points"], dtype=np.float64).reshape(-1, 3)
        axis = pts[1] - pts[0]
        axis[2] = 0.0
        axis /= np.linalg.norm(axis)
        for h in (0.4, 0.9, 1.4):
            origin = j.point + np.array([0.0, 0.0, h]) - 0.5 * axis
            hit = _raycast_first(tris, labels, origin, axis, width)
            assert hit is None or not hit[1].startswith("DRIFT_CAP"), (j.node_id, h, hit)


def test_p20d2_interior_caps_and_crosscut_faces_are_untouched_tabular(
    tabular_meshes: dict[str, Any],
) -> None:
    """Only a cap that a declared junction actually occupies is cut: crosscut
    faces (no junction ever touches a face) keep exactly K fan triangles each
    and the development report accounts for every cap triangle."""
    m = tabular_meshes
    _, _, dprims = _glb(m["dev"].glb)
    by_name = {p["name"]: p for p in dprims}
    k_dev = int(m["dev"].report["profile"]["archSegments"]) + 3
    n_levels = len({d["levelId"] for d in m["levels"]["developments"] if d["kind"] == "DRIFT"})
    devs = m["dev"].report["developments"]
    # Phase 20D.2.1: the CROSSCUT_CAP primitive = K fans per face (never cut)
    # + the mouth caps of the extremity crosscuts
    mouth_total = sum(int(d.get("renderMouthCapTriangles", 0)) for d in devs)
    assert by_name["CROSSCUT_CAP"]["indices"].shape[0] == len(_crosscuts(m)) * k_dev + mouth_total
    omitted = sum(int(d.get("renderCapOmittedTriangles", 0)) for d in devs)
    clipped = sum(int(d.get("renderCapClippedTriangles", 0)) for d in devs)
    replacement = sum(int(d.get("renderCapReplacementTriangles", 0)) for d in devs)
    assert omitted > 0 and clipped > 0 and replacement > 0
    assert by_name["DRIFT_CAP"]["indices"].shape[0] == (
        2 * n_levels * k_dev - omitted - clipped + replacement
    )
    # a crosscut face is never cut
    for d in devs:
        if d["kind"] == "CROSSCUT":
            assert d.get("renderCapOmittedTriangles", 0) == 0
            assert d.get("renderCapClippedTriangles", 0) == 0


# --------------------------------------------------------------------------- #
# Phase 20D.2.1 — child MOUTH CAP at a drift-extremity DRIFT_CROSSCUT junction
# (PR #42 review blocker): the half of the crosscut's OPEN start ring that
# lies beyond the drift end faces unexcavated rock and must carry a boundary
# surface; the half inside the drift stays OPEN; an interior T-junction gets
# nothing and stays bit-identical.
# --------------------------------------------------------------------------- #


def _mouth_cap_remainder(corners: np.ndarray, cut: Any) -> list[np.ndarray]:
    """Polygons the render emits for a mouth cap: whole kept fans + clip remainders."""
    polys: list[np.ndarray] = []
    for t in range(int(corners.shape[0])):
        if bool(cut.omit[t]):
            continue
        clip = cut.clips.get(t)
        if clip is None:
            polys.append(corners[t])
        else:
            polys.extend(clip.polygons)
    return polys


def _l_junction(parent_end_y: float) -> tuple[Any, Any, Any, Any, Any, float, Junction]:
    """Straight parent along +y ending at ``parent_end_y`` (0 → an L-junction:
    the child leaves from the parent's END; 30 → an interior T-junction) and a
    child along +x starting at the origin."""
    shape = build_profile(RampConstraints(), TunnelProfile())
    width = float(RampConstraints().tunnel_width)
    parent_env, _, _, _ = _straight_tube_mesh((0.0, -30.0, 0.0), (0.0, parent_end_y, 0.0), shape)
    _child_env, child_rings, child_chain, child_mesh = _straight_tube_mesh(
        (0.0, 0.0, 0.0), (30.0, 0.0, 0.0), shape
    )
    j = Junction(
        type="DRIFT_CROSSCUT",
        node_id="JUNCTION:L:S+00",
        parent_id="DRIFT:L",
        child_id="CROSSCUT:L:S+00",
        point=np.array([0.0, 0.0, 0.0]),
        child_end="start",
        level_id="L",
    )
    return shape, parent_env, child_rings, child_chain, child_mesh, width, j


def test_p20d21_a_synthetic_l_junction_mouth_cap_is_the_rock_facing_half() -> None:
    """RED-first contract A: at an L-junction the child's start-ring cap fan
    cut against the PARENT envelope keeps exactly the part beyond the parent
    end (y > 0, rock) and omits the part inside the parent (y < 0, open into
    the drift); the emitted triangles are finite, valid, non-degenerate and
    wound outward (a start cap faces −axis)."""
    from minegen.design.junctions import cut_mouth_cap
    from minegen.design.tunnel_mesh import cap_fan_corners

    shape, parent_env, rings, chain, mesh, width, j = _l_junction(0.0)
    tol = JUNCTION_SURFACE_TOLERANCE_FRACTION * width
    k = int(rings.shape[1])
    corners = cap_fan_corners(rings[0], mesh.positions[mesh.ring_count * k], True)
    cut = cut_mouth_cap(corners, parent_env, j, "start", width)
    assert cut is not None
    assert cut.omitted_triangles > 0 and cut.clipped_triangles > 0
    polys = _mouth_cap_remainder(corners, cut)
    assert polys
    # every emitted vertex lies on the rock side of the parent end plane
    for poly in polys:
        assert np.all(poly[:, 1] >= -tol), poly
        assert np.all(np.isfinite(poly))
    # the remainder is the parent-outside half of the cap (area within 3 %)
    full_area = sum(_polygon_area(corners[t]) for t in range(k))
    kept_area = sum(_polygon_area(p) for p in polys)
    assert abs(kept_area - 0.5 * full_area) <= 0.03 * full_area, (kept_area, full_area)
    # nothing inside the parent excavation: fan centroids with y < -tol are omitted
    for t in range(k):
        if corners[t].mean(axis=0)[1] < -tol and np.all(corners[t][:, 1] < tol):
            assert bool(cut.omit[t]), t
    # the render emits it as a start-cap primitive of the child, outward-wound
    meta = [{"segmentId": "S", "effectiveSource": "CROSSCUT"}]
    render = build_render_mesh(
        mesh, chain, shape, 30.0, meta, caps=(False, True), mouth_caps={"start": cut}
    )
    mouth = [p for p in render.primitives if p.extras.get("role") == "PORTAL_CAP"]
    assert len(mouth) == 1 and mouth[0].extras.get("junctionMouthCap") is True
    tris = mouth[0].indices.reshape(-1, 3)
    assert tris.shape[0] == (k - cut.omitted_triangles - cut.clipped_triangles) + (
        cut.replacement_triangles
    )
    pos = render.positions.astype(np.float64)
    _assert_valid_triangle_set(pos, tris, "mouth cap")
    centroids, areas, normals = _tri_geometry(pos, tris)
    assert np.all(areas > 1e-6)
    assert np.all(normals[:, 0] < -0.99), "a start cap faces -axis (outward of the child)"
    assert np.all(centroids[:, 1] >= -tol)
    assert render.mouth_cap_triangles == tris.shape[0]
    # the crosscut FACE (end cap) is untouched
    face = [p for p in render.primitives if p.extras.get("role") == "TERMINAL_CAP"]
    assert len(face) == 1 and face[0].indices.shape[0] == 3 * k
    assert "junctionMouthCap" not in face[0].extras


def test_p20d21_b_interior_t_junction_gets_no_mouth_cap_and_stays_bit_identical() -> None:
    """RED-first contract B: a child start ring wholly inside its parent (an
    interior T-junction) yields no mouth cap, and the render is bit-for-bit
    the Phase 20D.2 render."""
    from minegen.design.junctions import cut_mouth_cap
    from minegen.design.tunnel_mesh import cap_fan_corners

    shape, parent_env, rings, chain, mesh, width, j = _l_junction(30.0)
    k = int(rings.shape[1])
    corners = cap_fan_corners(rings[0], mesh.positions[mesh.ring_count * k], True)
    assert cut_mouth_cap(corners, parent_env, j, "start", width) is None
    meta = [{"segmentId": "S", "effectiveSource": "CROSSCUT"}]
    a = build_render_mesh(mesh, chain, shape, 30.0, meta, caps=(False, True))
    b = build_render_mesh(mesh, chain, shape, 30.0, meta, caps=(False, True), mouth_caps={})
    assert np.array_equal(a.positions, b.positions) and np.array_equal(a.normals, b.normals)
    assert len(a.primitives) == len(b.primitives)
    assert all(
        np.array_equal(x.indices, y.indices) and x.extras == y.extras
        for x, y in zip(a.primitives, b.primitives, strict=True)
    )
    assert a.mouth_cap_triangles == 0 and b.mouth_cap_triangles == 0


def _mouth_hole_audit(m: dict[str, Any]) -> list[dict[str, Any]]:
    """Per extremity DRIFT_CROSSCUT junction: rays cast from INSIDE the
    crosscut mouth back through its start plane (direction −axis), on the
    half beyond the drift end (rock side: a surface must stand there within
    a width) and on the half inside the drift (must stay OPEN into the
    drift: no cap within the drift's half width)."""
    m = dict(m)
    m.setdefault("width", float(m["sc"].ramp.tunnel_width))
    width = m["width"]
    envs, junctions = _builder_envelopes(m)
    tris, labels = _emitted_triangles(m)
    rows: list[dict[str, Any]] = []
    for j in _extremity_crosscut_junctions(m, envs, junctions):
        cc = next(d for d in m["levels"]["developments"] if d["id"] == j.child_id)
        pts = np.asarray(cc["centerline"]["points"], dtype=np.float64).reshape(-1, 3)
        axis = pts[1] - pts[0]
        axis[2] = 0.0
        axis /= np.linalg.norm(axis)
        lat = np.array([-axis[1], axis[0], 0.0])
        parent = envs[j.parent_id]
        end_i = (
            0
            if np.linalg.norm(parent.centers[0] - j.point)
            < np.linalg.norm(parent.centers[-1] - j.point)
            else -1
        )
        inward = parent.centers[end_i + 1 if end_i == 0 else end_i - 1] - parent.centers[end_i]
        drift_side = 1.0 if float(inward @ lat) >= 0 else -1.0
        beyond: list[tuple[float, str] | None] = []
        inside: list[tuple[float, str] | None] = []
        for frac in (0.3, 0.6, 0.9):
            for h in (0.5, 1.5, 3.0):
                origin_rock = j.point + 1.0 * axis - drift_side * frac * (width / 2) * lat
                origin_rock = origin_rock + np.array([0.0, 0.0, h])
                beyond.append(_raycast_first(tris, labels, origin_rock, -axis, 1.0 + width))
                origin_open = j.point + 1.0 * axis + drift_side * frac * (width / 2) * lat
                origin_open = origin_open + np.array([0.0, 0.0, h])
                inside.append(_raycast_first(tris, labels, origin_open, -axis, 1.0 + width / 2))
        rows.append({"junction": j, "beyond": beyond, "inside": inside})
    return rows


def _assert_mouth_contract(m: dict[str, Any]) -> None:
    rows = _mouth_hole_audit(m)
    assert rows, "the station lattice reaches the drift ends"
    for row in rows:
        j = row["junction"]
        holes = [r for r in row["beyond"] if r is None]
        assert not holes, f"{j.node_id}: {len(holes)}/{len(row['beyond'])} rock-facing rays escape"
        for hit in row["beyond"]:
            assert hit is not None and hit[1].startswith("CROSSCUT_CAP"), (j.node_id, hit)
            # ON the start plane (float32 render geometry: millimetre tolerance)
            assert hit[0] <= 1.0 + 1e-3, (j.node_id, hit)
        caps_in_drift = [r for r in row["inside"] if r is not None and "_CAP" in r[1]]
        assert not caps_in_drift, f"{j.node_id}: drift-side half no longer open {caps_in_drift}"


def test_p20d21_c_tabular_extremity_junctions_have_no_rock_facing_hole(
    tabular_meshes: dict[str, Any],
) -> None:
    """RED-first contract C (TABULAR-REFERENCE): every extremity
    DRIFT_CROSSCUT junction carries the mouth cap on its rock-facing half
    only, interior junctions carry none, the face caps keep exactly K fans and
    the report accounts for every emitted mouth-cap triangle."""
    m = tabular_meshes
    _assert_mouth_contract(m)
    envs, junctions = _builder_envelopes(m)
    ext = {j.child_id for j in _extremity_crosscut_junctions(m, envs, junctions)}
    devs = {d["developmentId"]: d for d in m["dev"].report["developments"]}
    mouth_total = 0
    for cc in _crosscuts(m):
        d = devs[cc["id"]]
        n = int(d.get("renderMouthCapTriangles", 0))
        if cc["id"] in ext:
            assert n > 0, cc["id"]
        else:
            assert n == 0, cc["id"]
        mouth_total += n
    _, _, dprims = _glb(m["dev"].glb)
    by_name = {p["name"]: p for p in dprims}
    k_dev = int(m["dev"].report["profile"]["archSegments"]) + 3
    assert by_name["CROSSCUT_CAP"]["indices"].shape[0] == len(_crosscuts(m)) * k_dev + mouth_total
    openings = m["dev"].report["junctions"]["openings"]
    assert sum(int(o.get("childMouthCapTriangles", 0)) for o in openings) == mouth_total
    assert all(
        int(o.get("childMouthCapTriangles", 0)) == 0
        for o in openings
        if o["type"] != "DRIFT_CROSSCUT" or o["childId"] not in ext
    )


def test_p20d21_d_warped_extremity_junctions_have_no_rock_facing_hole(
    warped_meshes: dict[str, Any],
) -> None:
    """RED-first contract D (WARPED-301, curved drifts): the same mouth
    contract; the parent-cap cut and its graze contract are unchanged."""
    m = warped_meshes
    assert m["dev"].status == "SUCCESS", m["dev"].report.get("failureReason")
    _assert_mouth_contract(m)
    mm = dict(m)
    mm["width"] = float(m["sc"].ramp.tunnel_width)
    envs, junctions = _builder_envelopes(mm)
    ext = {j.child_id for j in _extremity_crosscut_junctions(mm, envs, junctions)}
    devs = {d["developmentId"]: d for d in m["dev"].report["developments"]}
    for cc in [d for d in m["levels"]["developments"] if d["kind"] == "CROSSCUT"]:
        n = int(devs[cc["id"]].get("renderMouthCapTriangles", 0))
        assert (n > 0) == (cc["id"] in ext), (cc["id"], n)
