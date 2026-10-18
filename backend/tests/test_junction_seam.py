"""Hardening PR-5 — the junction SEAM measured on the emitted render meshes.

Park's second Walk screenshot (a level entry seen from inside the access)
showed two things at the rim of the doorway: wedge-shaped fragments of the
DRIFT wall standing into the access, and black slivers where the two tubes
meet. ``test_junction_passability`` proves the TRAFFIC section open; this
module measures the rim itself, so the fix (the exact parent-side clip) is
judged on numbers, not on a screenshot:

* WEDGE — a parent render triangle whose centroid lies INSIDE the child's
  swept envelope deeper than the union's one tolerance surface: with the
  pre-PR-5 whole-quad rule a parent quad with fewer than
  ``PARENT_QUAD_OVERLAP_MIN`` surface samples inside the child was kept
  whole, so up to a third of a quad stood in the mouth;
* HOLE — a ray cast from an eye point inside the excavation reaches ROCK:
  before its first FRONT-face hit (a surface struck from the void side; the
  mesh normals point into the rock) or its length cap, a sample every
  ``ROCK_SAMPLE_STEP_M`` along it lies more than the tolerance outside
  EVERY nearby excavation's swept envelope. The ray left the union through
  a gap in the seam. A back-face hit alone is not a hole: the parent's
  rim legitimately protrudes one tolerance into the child void (it is cut
  at ``−tol``), and a ray can strike that lip from behind while still in
  the void — the back-face count is recorded as a diagnostic.

Both are verification instruments (rule 187: the frontend never patches a
seam); they change no artifact and no threshold.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pytest

from minegen.design.junctions import (
    JUNCTION_RING_SPACING_FRACTION,
    JUNCTION_SURFACE_TOLERANCE_FRACTION,
    JUNCTION_WINDOW_WIDTHS,
    TubeEnvelope,
)
from minegen.design.profile import build_profile, secondary_profile
from minegen.design.tunnel_mesh import _envelope_segment, build_ring_chain
from tests.test_junction_passability import (  # noqa: F401
    _near,
    _range_triangles,
    _resample_from,
    _triangles,
    doorway_probe,
)
from tests.test_shafts import tabular_levels  # noqa: F401
from tests.test_typed_junctions import (  # noqa: F401
    _crosscuts,
    _glb,
    _ok_accesses,
    tabular_meshes,
)

#: eye points along the child (from the junction outward) and along the
#: parent (both ways from the junction), in tunnel widths, 1 m apart
EYE_REACH_WIDTHS = 1.5
EYE_STEP_M = 1.0
#: eye heights above the floor centerline (m): a walking head and a cab
EYE_HEIGHTS_M: tuple[float, ...] = (1.0, 1.6)
#: directions per eye point (Fibonacci sphere)
RAY_DIRECTIONS = 64
#: ray length cap, in tunnel widths: a ray still clear at this length is
#: travelling along a drive and tells nothing about the seam
RAY_CAP_WIDTHS = 3.0
#: spacing of the rock samples along each ray (m)
ROCK_SAMPLE_STEP_M = 0.25
#: chunk of sample points per envelope query (memory bound of the (P, M, 3)
#: intermediate)
ROCK_QUERY_CHUNK = 20000


def _fibonacci_sphere(n: int) -> np.ndarray:
    i = np.arange(n, dtype=np.float64) + 0.5
    phi = np.arccos(1.0 - 2.0 * i / n)
    theta = np.pi * (1.0 + 5.0**0.5) * i
    return np.stack([np.cos(theta) * np.sin(phi), np.sin(theta) * np.sin(phi), np.cos(phi)], axis=1)


def _nearest_hits(
    origins: np.ndarray, dirs: np.ndarray, cap: float, tris: np.ndarray, normals: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """For every ray (Möller–Trumbore, exact, 1 mm minimum travel): the nearest
    FRONT-face hit (struck from the void side: ``dot(dir, normal) > 0`` with
    normals into the rock) and the nearest hit of any facing — each as
    (triangle index, −1 = none within ``cap``; distance)."""
    n = origins.shape[0]
    hit_f = np.full(n, -1, dtype=np.int64)
    dist_f = np.full(n, np.inf)
    hit_a = np.full(n, -1, dtype=np.int64)
    dist_a = np.full(n, np.inf)
    if tris.shape[0] == 0:
        return hit_f, dist_f, hit_a, dist_a
    v0 = tris[:, 0, :]
    e1 = tris[:, 1, :] - v0
    e2 = tris[:, 2, :] - v0
    for i in range(n):
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
        along = (t > 1e-3) & (t < cap)
        cand = np.flatnonzero(inside & along)
        if cand.size:
            j = int(cand[np.argmin(t[cand])])
            hit_a[i] = j
            dist_a[i] = float(t[j])
            front = cand[normals[cand] @ d > 0.0]
            if front.size:
                j = int(front[np.argmin(t[front])])
                hit_f[i] = j
                dist_f[i] = float(t[j])
    return hit_f, dist_f, hit_a, dist_a


def _dedupe_consecutive(points: np.ndarray) -> np.ndarray:
    keep = np.concatenate([[True], np.linalg.norm(np.diff(points, axis=0), axis=1) > 1e-9])
    return np.asarray(points[keep], dtype=np.float64)


def _outward_normals(tris: np.ndarray) -> np.ndarray:
    n = np.cross(tris[:, 1, :] - tris[:, 0, :], tris[:, 2, :] - tris[:, 0, :])
    return np.asarray(n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-18))


def _points_near(poly: np.ndarray, point: np.ndarray, reach: float, step: float) -> np.ndarray:
    """``poly`` resampled every ``step`` m, keeping the samples within
    ``reach`` of ``point`` (the parent's eye points around a junction)."""
    seg = np.linalg.norm(np.diff(poly, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    stations = np.arange(0.0, float(cum[-1]) + 1e-9, step)
    out = []
    for s in stations:
        k = int(np.searchsorted(cum, s, side="right") - 1)
        k = min(max(k, 0), len(poly) - 2)
        t = (s - cum[k]) / max(seg[k], 1e-12)
        p = poly[k] * (1 - t) + poly[k + 1] * t
        if float(np.linalg.norm(p - point)) <= reach:
            out.append(p)
    return np.asarray(out, dtype=np.float64).reshape(-1, 3)


@pytest.fixture(scope="module")
def seam_probe(tabular_meshes: dict[str, Any]) -> dict[str, Any]:  # noqa: F811
    """Every declared junction: back-face escapes from eye points inside the
    excavation and the deepest parent intrusion into the child envelope."""
    m = tabular_meshes
    sc = m["sc"]
    width = m["width"]
    tol = JUNCTION_SURFACE_TOLERANCE_FRACTION * width
    reach = EYE_REACH_WIDTHS * width
    cap = RAY_CAP_WIDTHS * width
    dirs = _fibonacci_sphere(RAY_DIRECTIONS)
    t_pos, _, t_prims = _glb(m["tunnel"].glb)
    d_pos, _, d_prims = _glb(m["dev"].glb)
    ramp_roles_ok = ("SEGMENT", "PORTAL_CAP", "TERMINAL_CAP")
    ramp_tris = np.concatenate(
        [
            _triangles(t_pos, p["indices"])
            for p in t_prims
            if p["extras"].get("role") in ramp_roles_ok
        ]
    )
    ramp_roles = np.concatenate(
        [
            np.full(p["indices"].shape[0], str(p["extras"].get("role")))
            for p in t_prims
            if p["extras"].get("role") in ramp_roles_ok
        ]
    )
    tunnel_all = np.concatenate([_triangles(t_pos, p["indices"]) for p in t_prims])
    dev_all = np.concatenate([_triangles(d_pos, p["indices"]) for p in d_prims])
    # the surface each triangle belongs to (tube kind / segment role / cap role)
    tunnel_roles = np.concatenate(
        [np.full(p["indices"].shape[0], str(p["extras"].get("role"))) for p in t_prims]
    )
    dev_roles = np.concatenate([np.full(p["indices"].shape[0], str(p["name"])) for p in d_prims])
    all_tris = np.concatenate([tunnel_all, dev_all])
    all_roles = np.concatenate([tunnel_roles, dev_roles])
    by_name = {p["name"]: p for p in d_prims}

    def pieces(kind: str, pred: Any) -> np.ndarray:
        prim = by_name[kind]
        sel = [_range_triangles(prim, d_pos, r) for r in prim["extras"]["ranges"] if pred(r)]
        return np.concatenate(sel) if sel else np.zeros((0, 3, 3))

    def cap_tris(role: str) -> np.ndarray:
        p = by_name.get(role)
        return _triangles(d_pos, p["indices"]) if p is not None else np.zeros((0, 3, 3))

    def drift_surface(level: str) -> tuple[np.ndarray, np.ndarray]:
        """The DRIFT tube pieces of ``level`` plus every DRIFT_CAP, with roles."""
        tube = pieces("DRIFT", lambda r, lv=level: r["levelId"] == lv)
        caps = cap_tris("DRIFT_CAP")
        roles = np.concatenate(
            [np.full(tube.shape[0], "DRIFT"), np.full(caps.shape[0], "DRIFT_CAP")]
        )
        return np.concatenate([tube, caps]), roles

    ramp_poly = np.concatenate(
        [
            np.asarray(seg["effectiveCenterline"]["points"], dtype=np.float64).reshape(-1, 3)
            for seg in m["ramp"]["segments"]
        ]
    )
    drifts: dict[str, np.ndarray] = {}
    for d in m["levels"]["developments"]:
        if d["kind"] == "DRIFT":
            pts = np.asarray(d["centerline"]["points"], dtype=np.float64).reshape(-1, 3)
            drifts[d["levelId"]] = (
                np.concatenate([drifts[d["levelId"]], pts]) if d["levelId"] in drifts else pts
            )
    child_shape = build_profile(sc.ramp, secondary_profile(sc.tunnel_profile))
    spacing = secondary_profile(sc.tunnel_profile).ring_max_spacing
    ramp_shape = build_profile(sc.ramp, sc.tunnel_profile)

    def envelope(points: np.ndarray, shape: Any, step: float) -> TubeEnvelope:
        pts = _dedupe_consecutive(points)
        chain = build_ring_chain([_envelope_segment(pts.ravel().tolist())], step)
        return TubeEnvelope.build(chain.centers, chain.tangents, shape)

    # every excavation of the two GLBs as a swept envelope — a ray sample is
    # in ROCK only when it is more than tol outside ALL of them (a ray running
    # from a drift into a crosscut mouth is in a void, not in rock)
    excavations: list[tuple[str, TubeEnvelope]] = [
        ("RAMP", envelope(ramp_poly, ramp_shape, sc.tunnel_profile.ring_max_spacing))
    ]
    for a in _ok_accesses(m):
        pts = np.asarray(a["centerline"]["points"], dtype=np.float64).reshape(-1, 3)
        excavations.append((f"LEVEL_ACCESS:{a['levelId']}", envelope(pts, child_shape, spacing)))
    for d in m["levels"]["developments"]:
        if d["kind"] in ("DRIFT", "CROSSCUT"):
            pts = np.asarray(d["centerline"]["points"], dtype=np.float64).reshape(-1, 3)
            excavations.append((str(d["id"]), envelope(pts, child_shape, spacing)))
    env_radius = reach + cap + 2.0 * width
    rock_steps = np.arange(1, int(np.ceil(cap / ROCK_SAMPLE_STEP_M)) + 1) * ROCK_SAMPLE_STEP_M

    def child_envelope(points: np.ndarray, junction: np.ndarray) -> tuple[TubeEnvelope, Any]:
        chain = build_ring_chain(
            [_envelope_segment(points.ravel().tolist())],
            spacing,
            refine_near=junction[None, :],
            refine_radius=JUNCTION_WINDOW_WIDTHS * width,
            refine_spacing=JUNCTION_RING_SPACING_FRACTION * width,
        )
        env = TubeEnvelope.build(chain.centers, chain.tangents, child_shape)
        return env, env.ring_window(junction, (JUNCTION_WINDOW_WIDTHS + 1.0) * width)

    results: list[dict[str, Any]] = []

    def probe(
        node_id: str,
        jtype: str,
        junction: np.ndarray,
        child_pts: np.ndarray,
        parent_poly: np.ndarray,
        parent_tris: np.ndarray,
        parent_roles: np.ndarray,
    ) -> None:
        radius = reach + cap + width
        keep = np.linalg.norm(all_tris - junction[None, None, :], axis=2).min(axis=1) <= radius
        near_all = all_tris[keep]
        near_roles = all_roles[keep]
        normals = _outward_normals(near_all)
        eyes = np.concatenate(
            [
                _resample_from(child_pts, reach, EYE_STEP_M),
                _points_near(parent_poly, junction, reach, EYE_STEP_M),
            ]
        )
        # the junction point itself is the CORNER of an L-junction (a drift
        # extremity station): an eye there stands ON the drift's end cap and
        # the crosscut's mouth cap, so a ray into the rock quadrant starts on
        # both surfaces and hits neither (1 mm minimum travel) — a probe
        # artefact, not a seam. Eyes closer than half a step to the junction
        # are dropped; the eyes one step along the child and the parent still
        # look at the corner from both sides.
        eyes = eyes[np.linalg.norm(eyes - junction[None, :], axis=1) >= 0.5 * EYE_STEP_M]
        origins = np.concatenate([eyes + np.array([0.0, 0.0, h]) for h in EYE_HEIGHTS_M])
        o = np.repeat(origins, dirs.shape[0], axis=0)
        d = np.tile(dirs, (origins.shape[0], 1))
        hit_f, dist_f, hit_a, dist_a = _nearest_hits(o, d, cap, near_all, normals)
        has = hit_a >= 0
        facing = np.zeros(hit_a.shape[0])
        facing[has] = np.einsum("ij,ij->i", d[has], normals[hit_a[has]])
        back_face = has & (facing < 0.0)
        # ROCK REACH: samples along each ray up to its first front-face hit
        # (or the cap), judged against every excavation envelope near the
        # junction
        stop = np.where(hit_f >= 0, dist_f, cap)
        valid = rock_steps[None, :] < stop[:, None]
        pts = (o[:, None, :] + rock_steps[None, :, None] * d[:, None, :])[valid]
        sd_min = np.full(pts.shape[0], np.inf)
        for _, env in excavations:
            # only excavations a ray can reach: a tube whose nearest ring
            # center is farther than the envelope radius contributes +inf
            if float(np.linalg.norm(env.centers - junction[None, :], axis=1).min()) > env_radius:
                continue
            window = env.ring_window(junction, env_radius)
            if window[1] - window[0] < 2:
                continue
            for c0 in range(0, pts.shape[0], ROCK_QUERY_CHUNK):
                c1 = c0 + ROCK_QUERY_CHUNK
                sd_min[c0:c1] = np.minimum(sd_min[c0:c1], env.signed_distance(pts[c0:c1], window))
        rock = np.zeros(valid.shape, dtype=bool)
        rock[valid] = sd_min > tol
        escaped = rock.any(axis=1)
        first_rock = np.where(escaped, rock_steps[np.argmax(rock, axis=1)], np.inf)

        def role_of(index: int) -> str:
            return str(near_roles[index]) if index >= 0 else "CLEAR"

        details = [
            {
                "eye": [round(float(v), 2) for v in o[i]],
                "dir": [round(float(v), 3) for v in d[i]],
                "firstRockM": round(float(first_rock[i]), 3),
                "frontHitM": round(float(dist_f[i]), 3) if hit_f[i] >= 0 else None,
                "frontHitRole": role_of(int(hit_f[i])),
                "nearestHitM": round(float(dist_a[i]), 3) if hit_a[i] >= 0 else None,
                "nearestHitRole": role_of(int(hit_a[i])),
                "nearestHitBackFace": bool(back_face[i]),
            }
            for i in np.flatnonzero(escaped)[:8]
        ]
        by_role: dict[str, int] = {}
        for i in np.flatnonzero(escaped):
            by_role[role_of(int(hit_f[i]))] = by_role.get(role_of(int(hit_f[i])), 0) + 1
        back_by_role: dict[str, int] = {}
        for i in np.flatnonzero(back_face):
            back_by_role[role_of(int(hit_a[i]))] = back_by_role.get(role_of(int(hit_a[i])), 0) + 1
        # WEDGE: parent triangles whose centroid lies inside the child envelope
        env, window = child_envelope(child_pts, junction)
        near_mask = (
            np.linalg.norm(parent_tris - junction[None, None, :], axis=2).min(axis=1)
            <= (JUNCTION_WINDOW_WIDTHS + 1.0) * width
        )
        near_parent = parent_tris[near_mask]
        near_parent_roles = parent_roles[near_mask]
        centroids = near_parent.mean(axis=1)
        sd = env.signed_distance(centroids, window)
        finite = np.isfinite(sd)
        intrusion = np.where(finite, np.maximum(-sd, 0.0), 0.0)
        intrusion_details = [
            {
                "intrusionM": round(float(intrusion[i]), 4),
                "role": str(near_parent_roles[i]),
                "centroid": [round(float(v), 2) for v in centroids[i]],
                "aboveJunctionM": round(float(centroids[i][2] - junction[2]), 3),
                "vertices": [[round(float(v), 3) for v in q] for q in near_parent[i]],
            }
            for i in np.argsort(-intrusion)[:3]
            if intrusion[i] > tol
        ]
        results.append(
            {
                "nodeId": node_id,
                "type": jtype,
                "eyePoints": int(origins.shape[0]),
                "rays": int(o.shape[0]),
                "hits": int(has.sum()),
                "escapes": int(escaped.sum()),
                "escapesByFrontHitRole": by_role,
                "escapeDetails": details,
                "backFaceHits": int(back_face.sum()),
                "backFaceHitsByRole": back_by_role,
                "parentTriangles": int(near_parent.shape[0]),
                "parentTrianglesBeyondTolerance": int((intrusion > tol).sum()),
                "parentMaxIntrusionM": round(float(intrusion.max()) if intrusion.size else 0.0, 4),
                "intrusionDetails": intrusion_details,
            }
        )

    for a in _ok_accesses(m):
        level = a["levelId"]
        pts = np.asarray(a["centerline"]["points"], dtype=np.float64).reshape(-1, 3)
        probe(
            f"RAMP_JUNCTION:{level}", "RAMP_ACCESS", pts[0], pts, ramp_poly, ramp_tris, ramp_roles
        )
        drift_tris, drift_roles = drift_surface(level)
        probe(
            f"LEVEL_ENTRY:{level}",
            "ACCESS_DRIFT",
            pts[-1],
            pts[::-1],
            drifts[level],
            drift_tris,
            drift_roles,
        )
    for c in _crosscuts(m):
        level = c["levelId"]
        pts = np.asarray(c["centerline"]["points"], dtype=np.float64).reshape(-1, 3)
        drift_tris, drift_roles = drift_surface(level)
        probe(
            f"DRIFT_STATION:{level}:{c['stationIndex']}",
            "DRIFT_CROSSCUT",
            pts[0],
            pts,
            drifts[level],
            drift_tris,
            drift_roles,
        )
    return {"results": results, "width": width, "tolM": tol}


def test_every_declared_junction_is_seam_probed(seam_probe: dict[str, Any]) -> None:
    by_type: dict[str, int] = {}
    for r in seam_probe["results"]:
        by_type[r["type"]] = by_type.get(r["type"], 0) + 1
    assert by_type["RAMP_ACCESS"] >= 1
    assert by_type["ACCESS_DRIFT"] == by_type["RAMP_ACCESS"]
    assert by_type["DRIFT_CROSSCUT"] >= 1
    assert all(r["rays"] > 0 and r["hits"] > 0 for r in seam_probe["results"])


def test_no_ray_escapes_the_excavation_at_any_junction(
    seam_probe: dict[str, Any], record_property: Any
) -> None:
    """HOLE: no ray from an eye point inside the union reaches rock before its
    first front-face hit — measured on the emitted render triangles (tubes,
    caps, clip remainders and sills alike) against every nearby excavation
    envelope. The back-face count travels as a diagnostic (the parent's
    −tol rim is struck from behind legitimately)."""
    summary = [
        {
            k: r[k]
            for k in (
                "nodeId",
                "type",
                "rays",
                "hits",
                "escapes",
                "escapesByFrontHitRole",
                "backFaceHits",
                "backFaceHitsByRole",
            )
        }
        for r in seam_probe["results"]
    ]
    record_property("pr5_seam_escapes", summary)
    holes = [r for r in seam_probe["results"] if r["escapes"] > 0]
    assert holes == [], json.dumps(
        [{k: r[k] for k in ("nodeId", "escapes", "escapeDetails")} for r in holes], indent=1
    )


def test_no_parent_surface_stands_in_the_mouth_beyond_the_tolerance(
    seam_probe: dict[str, Any], record_property: Any
) -> None:
    """WEDGE: no parent render triangle keeps its centroid inside the child
    envelope deeper than the exact parent clip's construction bound: the clip
    cuts at ``−tol`` and accepts a remainder edge whose samples stay within
    the band of two tolerances below that level (``_edges_stay``), so a
    centroid can sit at most ``3 × tol`` inside the child (measured: the
    bulk at ``tol`` + millimetres of chord sag at the crown). Triangles
    beyond ONE tolerance are recorded, never asserted: they are the lip plus
    sag, not a wedge."""
    tol = seam_probe["tolM"]
    bound = 3.0 * tol
    summary = [
        {
            k: r[k]
            for k in (
                "nodeId",
                "type",
                "parentTriangles",
                "parentTrianglesBeyondTolerance",
                "parentMaxIntrusionM",
                "intrusionDetails",
            )
        }
        for r in seam_probe["results"]
    ]
    record_property("pr5_seam_intrusion", summary)
    record_property(
        "pr5_seam_intrusion_max",
        max(r["parentMaxIntrusionM"] for r in seam_probe["results"]),
    )
    wedges = [r for r in seam_probe["results"] if r["parentMaxIntrusionM"] > bound + 1e-6]
    assert wedges == [], (
        json.dumps(
            [
                {
                    k: r[k]
                    for k in ("nodeId", "parentTrianglesBeyondTolerance", "parentMaxIntrusionM")
                }
                for r in wedges
            ],
            indent=1,
        )
        + f"\ntolerance {tol:.3f} m, bound {bound:.3f} m"
    )
