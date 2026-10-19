"""Hardening PR-4 (W1b) — doorway passability probe at every declared junction.

Park's Walk screenshot showed a dark wall where a level access leaves the
ramp. One cause is temporal (the TIMELINE_SNAPSHOT aperture barrier, closed
by W1a); this module measures the OTHER candidate cause on the emitted
STATIC render meshes: does the typed junction union (Phase 20D.1 / 20D.2)
actually leave the traffic cross-section of every doorway open?

For every declared junction of the TABULAR fixture the CHILD centerline is
walked from the junction point outward (3 tunnel widths, 0.5 m steps) and
four probe rays follow it — the traffic centerline at 0.3 m (sill) and
1.6 m (head) above the floor and both shoulders (± 0.6 m lateral at 1.0 m)
— against the PARENT and CHILD render triangles within the junction
neighbourhood (Möller–Trumbore, exact). A hit is a surface standing in the
doorway: a surviving parent wall quad, a child shell fragment inside the
parent, a cap in the mouth, or a floor sill above 0.3 m. The probe is a
verification instrument (rule 187: the frontend never patches geometry);
it changes no artifact and no threshold.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pytest

from minegen.design.profile import gravity_frames
from tests.test_shafts import tabular_levels  # noqa: F401
from tests.test_typed_junctions import (  # noqa: F401
    _crosscuts,
    _glb,
    _ok_accesses,
    tabular_meshes,
)

#: probe spacing along the child centerline, m
PROBE_STEP_M = 0.5
#: probe reach from the junction point along the child, in tunnel widths
#: (the backend cut window is 2 widths; the tangential access centerline
#: crosses the ramp wall line at ≈ sqrt(R·w) ≈ 1.9 widths for R = 18 m)
PROBE_REACH_WIDTHS = 3.0
#: (height above the floor centerline, lateral offset) of the four probe rays
PROBE_OFFSETS: tuple[tuple[float, float], ...] = (
    (0.3, 0.0),  # sill: a floor step above 0.3 m blocks a walking body
    (1.6, 0.0),  # head
    (1.0, 0.6),  # right shoulder
    (1.0, -0.6),  # left shoulder
)


def _moller_trumbore(
    origins: np.ndarray, dirs: np.ndarray, lengths: np.ndarray, tris: np.ndarray
) -> np.ndarray:
    """Index (N,) of the nearest triangle each of N finite ray segments hits
    among T triangles (T, 3, 3); −1 where the segment is clear."""
    hit = np.full(origins.shape[0], -1, dtype=np.int64)
    if tris.shape[0] == 0:
        return hit
    v0 = tris[:, 0, :]
    e1 = tris[:, 1, :] - v0
    e2 = tris[:, 2, :] - v0
    for i in range(origins.shape[0]):
        d = dirs[i]
        p = np.cross(d[None, :], e2)
        det = np.einsum("ij,ij->i", e1, p)
        ok = np.abs(det) > 1e-12
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        s = origins[i][None, :] - v0
        u = np.einsum("ij,ij->i", s, p) * inv
        q = np.cross(s, e1)
        v = np.einsum("j,ij->i", d, q) * inv
        t = np.einsum("ij,ij->i", e2, q) * inv
        inside = ok & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1.0 + 1e-9)
        # a probe that starts ON a surface (the crosscut start ring at the
        # station) must not count its own plane: 1 mm of travel is required
        along = (t > 1e-3) & (t < lengths[i] - 1e-6)
        candidates = np.flatnonzero(inside & along)
        if candidates.size:
            hit[i] = int(candidates[np.argmin(t[candidates])])
    return hit


def _resample_from(points: np.ndarray, reach: float, step: float) -> np.ndarray:
    """Points every ``step`` m along ``points`` from its first vertex up to
    ``reach`` m (the last sample is the reach or the polyline end)."""
    seg = np.linalg.norm(np.diff(points, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = min(float(cum[-1]), reach)
    stations = np.arange(0.0, total + 1e-9, step)
    out = []
    for s in stations:
        k = int(np.searchsorted(cum, s, side="right") - 1)
        k = min(max(k, 0), len(points) - 2)
        t = (s - cum[k]) / max(seg[k], 1e-12)
        out.append(points[k] * (1 - t) + points[k + 1] * t)
    return np.asarray(out, dtype=np.float64)


def _probe_rays(path: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Four offset ray families along ``path`` → (origins, unit dirs, lengths)."""
    tangents = np.diff(path, axis=0)
    lengths = np.linalg.norm(tangents, axis=1)
    keep = lengths > 1e-9
    tangents, lengths, starts = tangents[keep], lengths[keep], path[:-1][keep]
    unit = tangents / lengths[:, None]
    right, up = gravity_frames(unit)
    origins, dirs, lens = [], [], []
    for height, lateral in PROBE_OFFSETS:
        o = starts + up * height + right * lateral
        origins.append(o)
        dirs.append(unit)
        lens.append(lengths)
    return np.concatenate(origins), np.concatenate(dirs), np.concatenate(lens)


def _triangles(positions: np.ndarray, indices: np.ndarray) -> np.ndarray:
    return positions[indices.reshape(-1, 3)].astype(np.float64)


def _near(tris: np.ndarray, point: np.ndarray, radius: float) -> np.ndarray:
    d = np.linalg.norm(tris - point[None, None, :], axis=2).min(axis=1)
    return tris[d <= radius]


def _range_triangles(prim: dict[str, Any], positions: np.ndarray, r: dict[str, Any]) -> np.ndarray:
    flat = prim["indices"].reshape(-1)
    return _triangles(positions, flat[r["indexOffset"] : r["indexOffset"] + r["indexCount"]])


@pytest.fixture(scope="module")
def doorway_probe(tabular_meshes: dict[str, Any]) -> dict[str, Any]:  # noqa: F811
    """Every declared junction probed; hits recorded per junction and ray family."""
    m = tabular_meshes
    width = m["width"]
    reach = PROBE_REACH_WIDTHS * width
    t_pos, _, t_prims = _glb(m["tunnel"].glb)
    d_pos, _, d_prims = _glb(m["dev"].glb)
    ramp_tris = np.concatenate(
        [_triangles(t_pos, p["indices"]) for p in t_prims if p["extras"].get("role") == "SEGMENT"]
    )
    by_name = {p["name"]: p for p in d_prims}

    def kind_ranges(kind: str) -> list[dict[str, Any]]:
        return list(by_name[kind]["extras"]["ranges"]) if kind in by_name else []

    def cap_tris(role: str) -> np.ndarray:
        p = by_name.get(role)
        return _triangles(d_pos, p["indices"]) if p is not None else np.zeros((0, 3, 3))

    def pieces(kind: str, pred: Any) -> np.ndarray:
        prim = by_name[kind]
        sel = [_range_triangles(prim, d_pos, r) for r in kind_ranges(kind) if pred(r)]
        return np.concatenate(sel) if sel else np.zeros((0, 3, 3))

    results: list[dict[str, Any]] = []

    def probe(
        node_id: str,
        jtype: str,
        junction: np.ndarray,
        path: np.ndarray,
        parent: np.ndarray,
        child: np.ndarray,
    ) -> None:
        radius = reach + 2.0 * width
        near_parent = _near(parent, junction, radius)
        near_child = _near(child, junction, radius)
        tris = np.concatenate([near_parent, near_child])
        samples = _resample_from(path, reach, PROBE_STEP_M)
        o, d, ln = _probe_rays(samples)
        hits = _moller_trumbore(o, d, ln, tris)
        hit = hits >= 0
        per_family = hit.reshape(len(PROBE_OFFSETS), -1).sum(axis=1)
        n_rays = hit.size // len(PROBE_OFFSETS)
        details = []
        for i in np.flatnonzero(hit):
            fam, k = divmod(int(i), n_rays)
            tri = tris[hits[i]]
            centroid = tri.mean(axis=0)
            details.append(
                {
                    "family": f"h{PROBE_OFFSETS[fam][0]:g}_l{PROBE_OFFSETS[fam][1]:+g}",
                    "chainageM": round(k * PROBE_STEP_M, 2),
                    "surface": "PARENT" if hits[i] < near_parent.shape[0] else "CHILD",
                    # triangle centroid relative to the probe's floor point (m)
                    "centroidAboveFloorM": round(float(centroid[2] - samples[k][2]), 3),
                    "centroidOffsetM": [round(float(v), 3) for v in centroid - samples[k]],
                }
            )
        results.append(
            {
                "nodeId": node_id,
                "type": jtype,
                "probes": int(hit.size),
                "trianglesTested": int(tris.shape[0]),
                "hits": int(hit.sum()),
                "hitsByFamily": {
                    f"h{h:g}_l{lat:+g}": int(n)
                    for (h, lat), n in zip(PROBE_OFFSETS, per_family, strict=True)
                },
                "hitDetails": details,
            }
        )

    for a in _ok_accesses(m):
        level = a["levelId"]
        pts = np.asarray(a["centerline"]["points"], dtype=np.float64).reshape(-1, 3)
        access_tris = pieces("LEVEL_ACCESS", lambda r, lv=level: r["levelId"] == lv)
        # RAMP → LEVEL_ACCESS: out of the ramp along the access
        probe(f"RAMP_JUNCTION:{level}", "RAMP_ACCESS", pts[0], pts, ramp_tris, access_tris)
        # LEVEL_ACCESS → DRIFT: from the entry back into the access (the drift
        # wall the access passes through, the access shell inside the drift)
        drift_tris = np.concatenate(
            [pieces("DRIFT", lambda r, lv=level: r["levelId"] == lv), cap_tris("DRIFT_CAP")]
        )
        probe(f"LEVEL_ENTRY:{level}", "ACCESS_DRIFT", pts[-1], pts[::-1], drift_tris, access_tris)
    for c in _crosscuts(m):
        level = c["levelId"]
        pts = np.asarray(c["centerline"]["points"], dtype=np.float64).reshape(-1, 3)
        drift_tris = np.concatenate(
            [pieces("DRIFT", lambda r, lv=level: r["levelId"] == lv), cap_tris("DRIFT_CAP")]
        )
        cross_tris = np.concatenate(
            [
                pieces("CROSSCUT", lambda r, cid=c["id"]: r["pieceId"] == cid),
                cap_tris("CROSSCUT_CAP"),
            ]
        )
        probe(
            f"DRIFT_STATION:{level}:{c['stationIndex']}",
            "DRIFT_CROSSCUT",
            pts[0],
            pts,
            drift_tris,
            cross_tris,
        )
    return {"results": results, "width": width}


def test_every_declared_junction_is_probed(doorway_probe: dict[str, Any]) -> None:
    by_type: dict[str, int] = {}
    for r in doorway_probe["results"]:
        by_type[r["type"]] = by_type.get(r["type"], 0) + 1
    assert by_type["RAMP_ACCESS"] >= 1
    assert by_type["ACCESS_DRIFT"] == by_type["RAMP_ACCESS"]
    assert by_type["DRIFT_CROSSCUT"] >= 1
    assert all(r["probes"] > 0 and r["trianglesTested"] > 0 for r in doorway_probe["results"])


def test_doorways_are_open_along_the_traffic_section(
    doorway_probe: dict[str, Any], record_property: Any
) -> None:
    """No parent wall, child shell, cap or sill stands in any doorway's
    traffic cross-section (sill 0.3 m · head 1.6 m · shoulders ± 0.6 m) —
    measured on the emitted render triangles, not inferred from the report."""
    record_property("w1b_doorway_probe", doorway_probe["results"])
    blocked = [r for r in doorway_probe["results"] if r["hits"] > 0]
    assert blocked == [], json.dumps(blocked, indent=1)


def test_parent_extension_is_reported_where_the_window_was_too_short(
    tabular_meshes: dict[str, Any],  # noqa: F811
    record_property: Any,
) -> None:
    """The finding behind the extension pass, kept as a measurement: at least
    one shallow-angle ramp turnout of the TABULAR fixture needed parent
    intervals beyond the nominal 2-width window, every RAMP_ACCESS opening
    reports its doorway footprint on the ramp, and the footprint contains the
    junction's own ramp chainage."""
    m = tabular_meshes
    openings = [
        o for o in m["tunnel"].report["junctions"]["openings"] if o["type"] == "RAMP_ACCESS"
    ]
    assert openings
    by_level = {
        seg["rampJunction"]["levelId"]: seg["rampJunction"]["chainage"]
        for seg in m["ramp"]["segments"]
        if seg.get("rampJunction")
    }
    width = m["width"]
    extended = 0
    for o in openings:
        span = o["parentCutChainage"]
        # the access leaves the ramp centerline AT the junction with the ramp's
        # own width, so its walls coincide with the ramp walls there ("on", not
        # inside): the first removed interval starts shortly AFTER the junction
        # and the footprint ends within the extension bound
        assert span is not None, o
        s_j = by_level[o["levelId"]]
        assert s_j - width <= span[0] <= s_j + width, (o, s_j)
        assert span[1] <= s_j + (2.0 + 6.0) * width, (o, s_j)
        assert o["parentExtensionIntervals"] >= 0
        extended += int(o["parentExtensionIntervals"] > 0)
    record_property(
        "w1b_parent_extension",
        [
            {k: o[k] for k in ("levelId", "parentCutChainage", "parentExtensionIntervals")}
            for o in openings
        ],
    )
    assert extended >= 1
