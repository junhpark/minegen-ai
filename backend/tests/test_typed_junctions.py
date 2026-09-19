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
    return [
        0.5 * (fr[i] + fr[i + 1]) * length for i, c in enumerate(counts) if c < entry["indexStride"]
    ]


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
        cut = [i for i, c in enumerate(counts) if c < p["extras"]["indexStride"]]
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
        assert counts[0] < r["indexStride"], r["pieceId"]


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
        assert counts[-1] < r["indexStride"], r["pieceId"]
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
        assert counts[0] < r["indexStride"], r["pieceId"]
        assert counts[-1] == r["indexStride"], r["pieceId"]


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
    # drift extremities: two caps per level; crosscut face: one cap each
    assert by_name["DRIFT_CAP"]["indices"].shape[0] == 2 * n_levels * k_dev
    assert by_name["CROSSCUT_CAP"]["indices"].shape[0] == len(_crosscuts(m)) * k_dev
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
    return {"tunnel": tunnel, "dev": dev, "accesses": accesses, "levels": levels}


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
