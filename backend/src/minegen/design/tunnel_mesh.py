"""Tunnel mesh: gravity-aligned sweep of the Phase 05 effective centerline
(CLAUDE.md rules 65–67).

The centerline is the tunnel FLOOR centerline. Every ring uses the existing
``core.coordinates.gravity_aligned_frame`` (rule 26); the profile plane is
perpendicular to the 3D tangent, so nominal excavation volume is
``profileArea × 3D length`` with NO grade cosine correction (rule 67).

Phase 06 may linearly subdivide the validated polyline but never smooths,
spline-fits, moves, or otherwise redesigns it (rule 65). The logical mesh
(tube + removable portal/terminal caps) must be manifold, watertight,
non-degenerate and consistently outward-oriented, and the full excavation
envelope is checked against hard spatial exclusions with a portal
profile-burial transition (rule 66). Failures are explicit — invalid
geometry is never persisted silently.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.core.coordinates import gravity_aligned_frame
from minegen.core.models import RampConstraints, TunnelProfile
from minegen.design.constraints import RejectionReason
from minegen.design.cost_field import DesignCostEvaluator
from minegen.design.profile import (
    ProfileShape,
    boundary_points,
    build_profile,
)

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

VOLUME_QA_TOLERANCE_PCT = 1.0  # |mesh − nominal| / nominal acceptance (rule 67)


# --------------------------------------------------------------------------- #
# 1. Profile (rule 67: crown radius is derived, dimensions from RampConstraints)
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# 2. Ring sampling (rule 65: linear subdivision only, never redesign)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RingChain:
    """Ring centers + unit tangents along the whole decline. Segment boundary
    rings are shared (one logical ring, rule 66) and use the Phase 05 shared
    boundary tangent."""

    centers: FloatArray  # (R, 3) on the effective centerline, exactly
    tangents: FloatArray  # (R, 3) unit
    chainage: FloatArray  # (R,) cumulative 3D arc length
    segment_of_interval: IntArray  # (R-1,) segment index owning ring gap i..i+1
    boundary_rings: IntArray  # ring index of each segment boundary (incl. ends)
    max_local_turn_deg: float


def build_ring_chain(segments: list[dict[str, Any]], max_spacing: float) -> RingChain:
    """Rings on the effective centerlines: every polyline vertex is a ring and
    long edges are split linearly. Consecutive segments share their boundary
    ring. Tangents: boundary rings use the persisted shared boundary tangent;
    interior polyline vertices use the normalized mean of adjacent chord
    directions; subdivision rings use the chord direction. All ring centers
    lie EXACTLY on the validated polyline (rule 65)."""
    centers: list[FloatArray] = []
    tangents: list[FloatArray] = []
    seg_of_interval: list[int] = []
    boundary_rings = [0]
    for si, seg in enumerate(segments):
        pts = np.asarray(seg["effectiveCenterline"]["points"], dtype=np.float64).reshape(-1, 3)
        t_start = np.asarray(seg["boundaryTangents"]["start"], dtype=np.float64)
        t_end = np.asarray(seg["boundaryTangents"]["end"], dtype=np.float64)
        chords = np.diff(pts, axis=0)
        lens = np.linalg.norm(chords, axis=1)
        dirs = chords / np.maximum(lens, 1e-12)[:, None]
        seg_centers: list[FloatArray] = []
        seg_tangents: list[FloatArray] = []
        for j in range(len(pts) - 1):
            # vertex ring j
            if j == 0:
                tan = t_start
            else:
                tan = dirs[j - 1] + dirs[j]
                tan = tan / max(float(np.linalg.norm(tan)), 1e-12)
            seg_centers.append(pts[j])
            seg_tangents.append(tan)
            # linear subdivision of the edge (rule 65: on the polyline exactly)
            n_sub = max(1, math.ceil(lens[j] / max_spacing))
            for k in range(1, n_sub):
                f = k / n_sub
                seg_centers.append(pts[j] * (1.0 - f) + pts[j + 1] * f)
                seg_tangents.append(dirs[j])
        seg_centers.append(pts[-1])
        seg_tangents.append(t_end)
        if si == 0:
            centers.extend(seg_centers)
            tangents.extend(seg_tangents)
        else:
            # shared boundary ring: the previous segment already emitted it;
            # its tangent is the shared boundary tangent on both sides
            centers.extend(seg_centers[1:])
            tangents.extend(seg_tangents[1:])
        seg_of_interval.extend([si] * (len(seg_centers) - 1))
        boundary_rings.append(len(centers) - 1)
    c = np.asarray(centers)
    t = np.asarray(tangents)
    t = t / np.linalg.norm(t, axis=1, keepdims=True)
    steps = np.linalg.norm(np.diff(c, axis=0), axis=1)
    chainage = np.concatenate([[0.0], np.cumsum(steps)])
    # local turn between consecutive chords (the faceting bound, rule 65)
    d = np.diff(c, axis=0)
    d = d / np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-12)
    cosines = np.clip(np.einsum("ij,ij->i", d[:-1], d[1:]), -1.0, 1.0)
    max_turn = float(np.degrees(np.arccos(cosines).max())) if len(cosines) else 0.0
    return RingChain(
        centers=c,
        tangents=t,
        chainage=chainage,
        segment_of_interval=np.asarray(seg_of_interval, dtype=np.int64),
        boundary_rings=np.asarray(boundary_rings, dtype=np.int64),
        max_local_turn_deg=max_turn,
    )


# --------------------------------------------------------------------------- #
# 3. Sweep + logical mesh (rule 66)
# --------------------------------------------------------------------------- #


@dataclass
class LogicalMesh:
    """Closed logical topology: tube rings + two cap fan centers. Vertex
    layout: ring r vertex j → r*K + j; then portal cap center, terminal cap
    center. Triangles carry a group id: segment index for tube faces,
    ``n_segments`` = PORTAL_CAP, ``n_segments + 1`` = TERMINAL_CAP."""

    positions: FloatArray  # (R*K + 2, 3)
    triangles: IntArray  # (T, 3)
    tri_group: IntArray  # (T,)
    k: int
    ring_count: int
    n_segments: int


def sweep_rings(chain: RingChain, shape: ProfileShape) -> FloatArray:
    """Profile vertices in world space via the SHARED envelope geometry
    (``design.profile.boundary_points``): the mesh sweeps exactly the
    boundary the Phase 04 feasibility check validated (rules 65–66)."""
    return boundary_points(chain.centers, chain.tangents, shape)


def build_logical_mesh(chain: RingChain, shape: ProfileShape) -> LogicalMesh:
    rings = sweep_rings(chain, shape)
    r, k, _ = rings.shape
    n_seg = int(chain.segment_of_interval.max()) + 1 if r > 1 else 1
    # cap fan apex at the profile CENTROID (the floor centerline point lies on
    # the closing floor edge and would make the two floor fan tris degenerate)
    f0 = gravity_aligned_frame(chain.tangents[0])
    f1 = gravity_aligned_frame(chain.tangents[-1])
    cap0 = chain.centers[0] + shape.centroid[0] * f0.right + shape.centroid[1] * f0.up
    cap1 = chain.centers[-1] + shape.centroid[0] * f1.right + shape.centroid[1] * f1.up
    positions = np.vstack([rings.reshape(-1, 3), cap0, cap1])
    portal_center = r * k
    terminal_center = r * k + 1
    tris: list[tuple[int, int, int]] = []
    groups: list[int] = []
    for i in range(r - 1):
        seg = int(chain.segment_of_interval[i])
        base0, base1 = i * k, (i + 1) * k
        for j in range(k):
            jn = (j + 1) % k
            a, b = base0 + j, base0 + jn
            c, d = base1 + j, base1 + jn
            # winding chosen for outward normals (validated by signed volume)
            tris.append((a, c, b))
            groups.append(seg)
            tris.append((b, c, d))
            groups.append(seg)
    # portal cap fan (faces −forward): group n_seg
    for j in range(k):
        jn = (j + 1) % k
        tris.append((portal_center, j, jn))
        groups.append(n_seg)
    # terminal cap fan (faces +forward): group n_seg + 1
    last = (r - 1) * k
    for j in range(k):
        jn = (j + 1) % k
        tris.append((terminal_center, last + jn, last + j))
        groups.append(n_seg + 1)
    return LogicalMesh(
        positions=positions,
        triangles=np.asarray(tris, dtype=np.int64),
        tri_group=np.asarray(groups, dtype=np.int64),
        k=k,
        ring_count=r,
        n_segments=n_seg,
    )


# --------------------------------------------------------------------------- #
# 4. Topology validation + engineering quantities (rules 66–67)
# --------------------------------------------------------------------------- #


@dataclass
class TopologyReport:
    manifold: bool = False
    watertight: bool = False
    degenerate_triangles: int = 0
    outward_orientation: bool = False
    signed_volume: float = 0.0
    surface_area_total: float = 0.0
    surface_area_tube: float = 0.0
    problems: list[str] = field(default_factory=list)


def validate_topology(mesh: LogicalMesh, cap_groups: tuple[int, int]) -> TopologyReport:
    rep = TopologyReport()
    tris = mesh.triangles
    pos = mesh.positions
    # manifold + watertight: every undirected edge in exactly 2 triangles,
    # every directed edge exactly once (consistent orientation)
    directed: dict[tuple[int, int], int] = {}
    undirected: dict[tuple[int, int], int] = {}
    for a, b, c in tris:
        for u, v in ((a, b), (b, c), (c, a)):
            directed[(int(u), int(v))] = directed.get((int(u), int(v)), 0) + 1
            key = (int(min(u, v)), int(max(u, v)))
            undirected[key] = undirected.get(key, 0) + 1
    bad_dir = sum(1 for n in directed.values() if n != 1)
    bad_und = sum(1 for n in undirected.values() if n != 2)
    rep.manifold = bad_dir == 0
    rep.watertight = bad_und == 0
    if bad_dir:
        rep.problems.append(f"{bad_dir} directed edges with inconsistent orientation")
    if bad_und:
        rep.problems.append(f"{bad_und} undirected edges not shared by exactly 2 faces")
    v0 = pos[tris[:, 0]]
    v1 = pos[tris[:, 1]]
    v2 = pos[tris[:, 2]]
    cross = np.cross(v1 - v0, v2 - v0)
    areas = 0.5 * np.linalg.norm(cross, axis=1)
    rep.degenerate_triangles = int((areas < 1e-9).sum())
    if rep.degenerate_triangles:
        rep.problems.append(f"{rep.degenerate_triangles} degenerate triangles")
    rep.signed_volume = float(np.einsum("ij,ij->i", v0, np.cross(v1, v2)).sum() / 6.0)
    rep.outward_orientation = rep.signed_volume > 0.0
    if not rep.outward_orientation:
        rep.problems.append(f"signed volume {rep.signed_volume:.3f} not positive")
    rep.surface_area_total = float(areas.sum())
    is_cap = np.isin(mesh.tri_group, cap_groups)
    rep.surface_area_tube = float(areas[~is_cap].sum())
    return rep


@dataclass
class EnvelopeReport:
    violations: int = 0
    reason_counts: dict[str, int] = field(default_factory=dict)
    burial_ring: int = -1  # first ring with the full profile below terrain


HARD_ENVELOPE_REASONS = (
    RejectionReason.OUTSIDE_WORLD,
    RejectionReason.INSIDE_OREBODY,
    RejectionReason.OREBODY_BUFFER,
    RejectionReason.RESTRICTED_ZONE,
)


def validate_envelope(evaluator: DesignCostEvaluator, mesh: LogicalMesh) -> EnvelopeReport:
    """Excavation envelope against hard spatial exclusions (rule 66). The
    portal profile-burial transition mirrors rule 52: terrain intersection is
    permitted only until the complete profile first becomes buried; afterwards
    any above-terrain profile point is a violation. ``minimum_surface_cover``
    is a centerline constraint and is NOT re-applied to the roof."""
    rep = EnvelopeReport()
    r, k = mesh.ring_count, mesh.k
    pts = mesh.positions[: r * k]
    ev = evaluator.evaluate_points(pts)
    # a portal roof above terrain usually also exceeds the world TOP; that is
    # the same portal case, so OUTSIDE_WORLD caused only by z > grid top is
    # governed by the burial transition rather than counted as a hard
    # violation. XY exits and below-bottom exits stay hard.
    gmin, gmax = np.asarray(evaluator.grid_min), np.asarray(evaluator.grid_max)
    xy_in = np.all((pts[:, :2] >= gmin[:2]) & (pts[:, :2] <= gmax[:2]), axis=1)
    above_top_only = xy_in & (pts[:, 2] > gmax[2])
    above = np.zeros(r * k, dtype=bool)
    hard = np.zeros(r * k, dtype=bool)
    for i in range(r * k):
        for reason in ev.rejection_reasons[i]:
            if reason is RejectionReason.ABOVE_TERRAIN:
                above[i] = True
            elif reason is RejectionReason.OUTSIDE_WORLD and above_top_only[i]:
                above[i] = True  # portal-roof case: burial transition governs
            elif reason in HARD_ENVELOPE_REASONS:
                hard[i] = True
                rep.reason_counts[reason.value] = rep.reason_counts.get(reason.value, 0) + 1
    rep.violations = int(hard.sum())
    ring_above = above.reshape(r, k).any(axis=1)
    buried = np.nonzero(~ring_above)[0]
    rep.burial_ring = int(buried[0]) if buried.size else -1
    if rep.burial_ring >= 0:
        breakthrough = int(ring_above[rep.burial_ring :].sum())
        if breakthrough:
            # count above-terrain PROFILE POINTS after burial
            pts_after = int(above.reshape(r, k)[rep.burial_ring :].sum())
            rep.violations += pts_after
            rep.reason_counts[RejectionReason.ABOVE_TERRAIN.value] = pts_after
    return rep


# --------------------------------------------------------------------------- #
# 5. Render mesh: crease-split vertices, geometry-based normals, UV (rule 66)
# --------------------------------------------------------------------------- #


@dataclass
class RenderPrimitive:
    name: str
    extras: dict[str, Any]
    indices: npt.NDArray[np.uint32]


@dataclass
class RenderMesh:
    positions: npt.NDArray[np.float32]  # (N, 3)
    normals: npt.NDArray[np.float32]  # (N, 3)
    uvs: npt.NDArray[np.float32]  # (N, 2)
    primitives: list[RenderPrimitive]
    geometrically_closed: bool
    render_vertex_count: int


def _profile_groups(
    shape: ProfileShape, crease_angle_deg: float
) -> tuple[IntArray, npt.NDArray[np.bool_]]:
    """Smoothing group per profile EDGE and crease flag per profile VERTEX.
    Vertex 0 is always split: it carries the UV seam (u=0 vs u=1)."""
    pts = shape.points
    k = shape.k
    closed = np.vstack([pts, pts[:1]])
    dirs = np.diff(closed, axis=0)
    dirs = dirs / np.linalg.norm(dirs, axis=1, keepdims=True)
    cos_crease = math.cos(math.radians(crease_angle_deg))
    crease = np.zeros(k, dtype=bool)
    for j in range(k):
        d_prev = dirs[(j - 1) % k]
        d_next = dirs[j]
        crease[j] = float(np.dot(d_prev, d_next)) < cos_crease
    crease[0] = True  # forced UV seam
    groups = np.zeros(k, dtype=np.int64)
    g = 0
    for j in range(k):
        if j > 0 and crease[j]:
            g += 1
        groups[j] = g
    return groups, crease


def build_render_mesh(
    mesh: LogicalMesh,
    chain: RingChain,
    shape: ProfileShape,
    crease_angle_deg: float,
    segments_meta: list[dict[str, Any]],
) -> RenderMesh:
    """Render-vertex split of the logical tube + caps. Normals come from the
    ACTUAL generated triangle geometry: per-triangle geometric normals are
    angle-weighted into each render vertex, so curved sweeps get true surface
    normals; crease splits keep the floor/wall (and any non-tangent
    wall–crown) edges hard. UV: u = perimeter fraction, v = 3D chainage in
    meters."""
    r, k = mesh.ring_count, mesh.k
    ring_pos = mesh.positions[: r * k].reshape(r, k, 3)
    _edge_group, crease = _profile_groups(shape, crease_angle_deg)

    # render vertex ids: per ring, per profile vertex, side A (start corner of
    # edge j) and side B (end corner of edge j-1); merged when not a crease
    n_split = int(crease.sum())
    per_ring = k + n_split  # each crease adds one duplicate
    vid_a = np.zeros((r, k), dtype=np.int64)
    vid_b = np.zeros((r, k), dtype=np.int64)
    positions = np.zeros((r * per_ring + 2 * (k + 1), 3))
    uvs = np.zeros((positions.shape[0], 2))
    cursor = 0
    for i in range(r):
        v = chain.chainage[i]
        for j in range(k):
            if crease[j]:
                vid_b[i, j] = cursor
                positions[cursor] = ring_pos[i, j]
                # side B ends edge j-1: at the seam vertex 0 this is u = 1.0
                uvs[cursor] = (shape.perimeter_u[k] if j == 0 else shape.perimeter_u[j], v)
                cursor += 1
                vid_a[i, j] = cursor
                positions[cursor] = ring_pos[i, j]
                uvs[cursor] = (shape.perimeter_u[j], v)
                cursor += 1
            else:
                vid_a[i, j] = cursor
                vid_b[i, j] = cursor
                positions[cursor] = ring_pos[i, j]
                uvs[cursor] = (shape.perimeter_u[j], v)
                cursor += 1

    # tube triangles per segment, normals accumulated angle-weighted
    normals = np.zeros_like(positions)
    seg_tris: list[list[tuple[int, int, int]]] = [[] for _ in segments_meta]
    for i in range(r - 1):
        seg = int(chain.segment_of_interval[i])
        for j in range(k):
            jn = (j + 1) % k
            a = vid_a[i, j]
            b = vid_b[i, jn]
            c = vid_a[i + 1, j]
            d = vid_b[i + 1, jn]
            seg_tris[seg].append((a, c, b))
            seg_tris[seg].append((b, c, d))
    for tris in seg_tris:
        for t in tris:
            _accumulate_normal(positions, normals, t)

    # caps: own flat-shaded vertices (removable primitives, rule 66)
    cap_prims: list[RenderPrimitive] = []
    for cap_name, ring_i, apex_logical in (
        ("PORTAL_CAP", 0, r * k),
        ("TERMINAL_CAP", r - 1, r * k + 1),
    ):
        base = cursor
        for j in range(k):
            positions[cursor] = ring_pos[ring_i, j]
            uvs[cursor] = (
                shape.points[j, 0] / (2.0 * abs(shape.points[0, 0])) + 0.5,
                shape.points[j, 1] / max(shape.points[:, 1].max(), 1e-9),
            )
            cursor += 1
        apex = cursor
        positions[cursor] = mesh.positions[apex_logical]
        uvs[cursor] = (0.5, shape.centroid[1] / max(shape.points[:, 1].max(), 1e-9))
        cursor += 1
        tris_c: list[tuple[int, int, int]] = []
        for j in range(k):
            jn = (j + 1) % k
            if cap_name == "PORTAL_CAP":
                tris_c.append((apex, base + j, base + jn))
            else:
                tris_c.append((apex, base + jn, base + j))
        for t in tris_c:
            _accumulate_normal(positions, normals, t)
        cap_prims.append(
            RenderPrimitive(
                name=cap_name,
                extras={"role": cap_name},
                indices=np.asarray(tris_c, dtype=np.uint32).ravel(),
            )
        )

    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = normals / np.maximum(lengths, 1e-12)

    prims = [
        RenderPrimitive(
            name=str(meta["levelId"]),
            extras={
                "role": "SEGMENT",
                "segmentId": meta["levelId"],
                "effectiveSource": meta["effectiveSource"],
            },
            indices=np.asarray(seg_tris[s], dtype=np.uint32).ravel(),
        )
        for s, meta in enumerate(segments_meta)
    ] + cap_prims

    closed = _geometrically_closed(positions[:cursor], prims)
    return RenderMesh(
        positions=positions[:cursor].astype(np.float32),
        normals=normals[:cursor].astype(np.float32),
        uvs=uvs[:cursor].astype(np.float32),
        primitives=prims,
        geometrically_closed=closed,
        render_vertex_count=cursor,
    )


def _accumulate_normal(
    positions: FloatArray, normals: FloatArray, tri: tuple[int, int, int]
) -> None:
    a, b, c = tri
    va, vb, vc = positions[a], positions[b], positions[c]
    n = np.cross(vb - va, vc - va)
    norm = float(np.linalg.norm(n))
    if norm < 1e-12:
        return
    n = n / norm
    for idx, p, q in ((a, vb, vc), (b, vc, va), (c, va, vb)):
        e1 = p - positions[idx]
        e2 = q - positions[idx]
        denom = float(np.linalg.norm(e1) * np.linalg.norm(e2))
        angle = math.acos(max(-1.0, min(1.0, float(np.dot(e1, e2)) / max(denom, 1e-12))))
        normals[idx] += n * angle


def _geometrically_closed(positions: FloatArray, prims: list[RenderPrimitive]) -> bool:
    """Position-weld closedness of the render mesh (rule 66): after welding
    identical positions, every edge must bound exactly two faces."""
    key = np.round(positions * 1e6).astype(np.int64)
    weld: dict[tuple[int, int, int], int] = {}
    remap = np.zeros(len(positions), dtype=np.int64)
    for i, kx in enumerate(map(tuple, key)):
        remap[i] = weld.setdefault(kx, len(weld))
    edges: dict[tuple[int, int], int] = {}
    for prim in prims:
        tris = prim.indices.reshape(-1, 3)
        for a, b, c in tris:
            for u, v in ((a, b), (b, c), (c, a)):
                wu, wv = int(remap[u]), int(remap[v])
                keye = (min(wu, wv), max(wu, wv))
                edges[keye] = edges.get(keye, 0) + 1
    return all(n == 2 for n in edges.values())


# --------------------------------------------------------------------------- #
# 6. Orchestration (rules 65–67)
# --------------------------------------------------------------------------- #


@dataclass
class TunnelMeshResult:
    status: str  # SUCCESS | FAILED
    report: dict[str, Any]
    glb: bytes | None


class TunnelMeshBuilder:
    """Builds the excavation mesh from the Phase 05 artifact ONLY (rule 64/65)."""

    def __init__(
        self,
        evaluator: DesignCostEvaluator,
        ramp: RampConstraints,
        profile: TunnelProfile,
    ) -> None:
        self.ev = evaluator
        self.ramp = ramp
        self.profile = profile

    def build(self, smoothed_payload: dict[str, Any], on_progress: Any = None) -> TunnelMeshResult:
        from minegen.design.glb_writer import write_glb

        def progress(i: int, n: int, label: str, stage: str) -> None:
            if on_progress is not None:
                on_progress(i, n, label, stage)

        if smoothed_payload.get("status") == "FAILED":
            return self._failed("Phase 05 artifact status is FAILED", {})
        segments = smoothed_payload["segments"]
        if not segments:
            return self._failed("Phase 05 artifact has no segments", {})
        shape = build_profile(self.ramp, self.profile)
        progress(0, len(segments), "", "SEGMENT_STARTED")
        chain = build_ring_chain(segments, self.profile.ring_max_spacing)
        if chain.max_local_turn_deg > self.profile.ring_max_turn_deg + 1e-9:
            return self._failed(
                f"local turn {chain.max_local_turn_deg:.2f}° exceeds "
                f"ringMaxTurnDeg {self.profile.ring_max_turn_deg:g}°",
                {"maxLocalTurnDeg": chain.max_local_turn_deg},
            )
        mesh = build_logical_mesh(chain, shape)
        cap_groups = (mesh.n_segments, mesh.n_segments + 1)
        topo = validate_topology(mesh, cap_groups)
        envelope = validate_envelope(self.ev, mesh)
        progress(len(segments) // 2, len(segments), "", "SEGMENT_COMPLETED")

        length_3d = float(chain.chainage[-1])
        # rule 67 (blocker 2): engineering nominal volume uses the EXACT
        # analytic D-profile area — invariant under arch_segments; the
        # tessellated mesh area is reported separately
        nominal = shape.analytic_area * length_3d
        volume_diff_pct = (
            abs(topo.signed_volume - nominal) / nominal * 100.0 if nominal > 0 else None
        )
        junction_gap = 0.0  # boundary rings are shared by construction (rule 66)

        problems = list(topo.problems)
        if envelope.violations:
            reasons = ", ".join(f"{k} x{v}" for k, v in sorted(envelope.reason_counts.items()))
            problems.append(f"{envelope.violations} envelope violations ({reasons})")
        if volume_diff_pct is not None and volume_diff_pct > VOLUME_QA_TOLERANCE_PCT:
            problems.append(
                f"mesh/nominal volume difference {volume_diff_pct:.2f}% exceeds "
                f"{VOLUME_QA_TOLERANCE_PCT:g}%"
            )

        segments_meta = [
            {"levelId": s["levelId"], "effectiveSource": s["effectiveSource"]} for s in segments
        ]
        report: dict[str, Any] = {
            "length3d": length_3d,
            "analyticProfileArea": shape.analytic_area,
            "meshProfileArea": shape.mesh_area,
            "tessellationBiasPct": shape.tessellation_bias_pct,
            "crownRadius": shape.crown_radius,
            "profileEnvelopeReach": float(np.linalg.norm(shape.points, axis=1).max()),
            "nominalExcavationVolume": nominal,
            "meshEnclosedVolume": topo.signed_volume,
            "volumeDifferencePct": volume_diff_pct,
            "excavationSurfaceArea": topo.surface_area_tube,
            "closedMeshSurfaceArea": topo.surface_area_total,
            "ringCount": mesh.ring_count,
            "logicalVertexCount": int(mesh.positions.shape[0]),
            "renderVertexCount": 0,
            "triangleCount": int(mesh.triangles.shape[0]),
            "watertight": topo.watertight,
            "manifold": topo.manifold,
            "geometricallyClosed": False,
            "degenerateTriangles": topo.degenerate_triangles,
            "outwardOrientation": topo.outward_orientation,
            "junctionGapMax": junction_gap,
            "maxLocalTurnDeg": chain.max_local_turn_deg,
            "envelopeViolations": envelope.violations,
            "envelopeReasonCounts": envelope.reason_counts,
            "burialRing": envelope.burial_ring,
            "selfIntersectionCheck": "NOT_IMPLEMENTED",  # technical debt (rule 66 note)
            "segments": [
                {
                    "segmentId": meta["levelId"],
                    "effectiveSource": meta["effectiveSource"],
                    "ringIntervals": int((chain.segment_of_interval == s).sum()),
                }
                for s, meta in enumerate(segments_meta)
            ],
        }
        if problems:
            report["status"] = "FAILED"
            report["failureReason"] = "; ".join(problems)
            progress(len(segments), len(segments), "", "MESH_COMPLETED")
            return TunnelMeshResult(status="FAILED", report=report, glb=None)

        render = build_render_mesh(mesh, chain, shape, self.profile.crease_angle_deg, segments_meta)
        report["renderVertexCount"] = render.render_vertex_count
        report["geometricallyClosed"] = render.geometrically_closed
        if not render.geometrically_closed:
            report["status"] = "FAILED"
            report["failureReason"] = "render mesh is not geometrically closed after weld"
            return TunnelMeshResult(status="FAILED", report=report, glb=None)
        glb = write_glb(render)
        report["status"] = "SUCCESS"
        report["failureReason"] = None
        progress(len(segments), len(segments), "", "MESH_COMPLETED")
        return TunnelMeshResult(status="SUCCESS", report=report, glb=glb)

    def _failed(self, reason: str, extra: dict[str, Any]) -> TunnelMeshResult:
        report = {"status": "FAILED", "failureReason": reason, **extra}
        return TunnelMeshResult(status="FAILED", report=report, glb=None)
