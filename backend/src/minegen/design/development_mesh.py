"""Development excavation meshes — LEVEL_ACCESS / DRIFT / CROSSCUT (Phase 20B
closeout v3 §4).

A thin generic entry point over the Phase 06 sweep machinery
(``tunnel_mesh.build_ring_chain`` / ``build_logical_mesh`` /
``build_render_mesh``): every development is swept with the SAME gravity-
aligned profile frame as the main ramp (rules 26/65), on its authoritative
centerline (``level_accesses.json`` branches, ``levels.json`` drift pieces
and crosscuts) — never re-designed, never moved, never simplified. Only the
RENDER tessellation of these secondary developments is coarser than the
main ramp (fewer arch segments, wider subdivision spacing).

Endpoint policy (§4.B): ``CAP`` closes an isolated tunnel end (drift
extremities, the crosscut face at the orebody contact); ``OPEN`` leaves the
ring boundary open where the development joins another excavation (the
access branch at the ramp turnout and at the drift entry, the crosscut start
on the drift). QA is split accordingly (§4.C): CAP-CAP tubes keep the full
closed-solid contract; OPEN tubes are validated as manifolds WITH boundary
(finite, valid indices, non-degenerate, orientation-consistent, the expected
open boundary edge count, ring/centerline correspondence, envelope).

Out of scope (§4.D, Phase 20D "Unified Development Mesh"): boolean wall
openings, exact junction CSG, an all-development watertight union.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import numpy.typing as npt

from minegen.core.artifacts import LEVEL_ACCESSES_ARTIFACT
from minegen.core.models import RampConstraints, TunnelProfile
from minegen.design.cost_field import DesignCostEvaluator
from minegen.design.profile import ProfileShape, build_profile
from minegen.design.tunnel_mesh import (
    LogicalMesh,
    RenderMesh,
    RenderPrimitive,
    RingChain,
    build_logical_mesh,
    build_render_mesh,
    build_ring_chain,
)

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

EndpointPolicy = Literal["CAP", "OPEN"]
DevelopmentMeshKind = Literal["LEVEL_ACCESS", "DRIFT", "CROSSCUT"]
KIND_ORDER: tuple[DevelopmentMeshKind, ...] = ("LEVEL_ACCESS", "DRIFT", "CROSSCUT")
LEVELS_ARTIFACT = "levels.json"

#: secondary-development RENDER tessellation relative to the main ramp
#: (§4.F): arch segments halved (floor ≥ 4), subdivision spacing doubled.
#: The engineering polyline vertices are always rings — nothing is dropped.
SECONDARY_ARCH_DIVISOR = 2
SECONDARY_ARCH_MIN = 4
SECONDARY_SPACING_FACTOR = 2.0
RING_ON_POLYLINE_TOLERANCE = 1e-6  # m


# --------------------------------------------------------------------------- #
# 1. Specs from the owning artifacts
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DevelopmentSpec:
    """One swept development: an ordered chain of consecutive polylines
    (``pieces``) that share their boundary vertices (drift pieces of one
    level), or a single polyline (an access branch, a crosscut)."""

    development_id: str
    kind: DevelopmentMeshKind
    level_id: str
    pieces: tuple[tuple[str, FloatArray], ...]  # (piece id, (N,3)) in chain order
    start: EndpointPolicy
    end: EndpointPolicy
    geometry_ref: dict[str, Any]

    @property
    def point_count(self) -> int:
        return int(sum(int(p.shape[0]) for _, p in self.pieces) - (len(self.pieces) - 1))


def _pts(flat: list[float]) -> FloatArray:
    return np.asarray(flat, dtype=np.float64).reshape(-1, 3)


def specs_from_artifacts(
    accesses_payload: dict[str, Any] | None, levels_payload: dict[str, Any] | None
) -> list[DevelopmentSpec]:
    """Deterministic development list from the owning artifacts (rule 155:
    no polyline is duplicated — every spec references its owner)."""
    specs: list[DevelopmentSpec] = []
    if accesses_payload is not None and accesses_payload.get("status") == "SUCCESS":
        for i, a in enumerate(accesses_payload.get("accesses", [])):
            if a.get("status") != "OK" or not a.get("centerline"):
                continue
            specs.append(
                DevelopmentSpec(
                    development_id=f"LEVEL_ACCESS:{a['levelId']}",
                    kind="LEVEL_ACCESS",
                    level_id=str(a["levelId"]),
                    pieces=((f"LEVEL_ACCESS:{a['levelId']}", _pts(a["centerline"]["points"])),),
                    start="OPEN",  # welded to the ramp at the turnout
                    end="OPEN",  # welded to the drift at the level entry
                    geometry_ref={"artifact": LEVEL_ACCESSES_ARTIFACT, "segmentIndex": i},
                )
            )
    if levels_payload is not None and levels_payload.get("status") == "SUCCESS":
        by_level: dict[str, list[dict[str, Any]]] = {}
        for d in levels_payload.get("developments", []):
            if d.get("kind") == "DRIFT":
                by_level.setdefault(str(d["levelId"]), []).append(d)
        for level_id, pieces in by_level.items():
            ordered = sorted(pieces, key=lambda d: float(d["fromU"]))
            specs.append(
                DevelopmentSpec(
                    development_id=f"DRIFT:{level_id}",
                    kind="DRIFT",
                    level_id=level_id,
                    pieces=tuple((str(d["id"]), _pts(d["centerline"]["points"])) for d in ordered),
                    start="CAP",
                    end="CAP",
                    geometry_ref={
                        "artifact": LEVELS_ARTIFACT,
                        "developmentIds": [str(d["id"]) for d in ordered],
                    },
                )
            )
        for d in levels_payload.get("developments", []):
            if d.get("kind") != "CROSSCUT":
                continue
            specs.append(
                DevelopmentSpec(
                    development_id=str(d["id"]),
                    kind="CROSSCUT",
                    level_id=str(d["levelId"]),
                    pieces=((str(d["id"]), _pts(d["centerline"]["points"])),),
                    start="OPEN",  # leaves the footwall drift
                    end="CAP",  # face at the orebody contact
                    geometry_ref={"artifact": LEVELS_ARTIFACT, "developmentId": str(d["id"])},
                )
            )
    return specs


# --------------------------------------------------------------------------- #
# 2. Ring chain from a piece chain (tangents from the polyline itself)
# --------------------------------------------------------------------------- #


def _unit(v: FloatArray) -> FloatArray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else v


def chain_segments(spec: DevelopmentSpec) -> list[dict[str, Any]]:
    """Phase 06 segment dicts for ``build_ring_chain``: consecutive pieces
    share a boundary vertex and a boundary tangent (mean of the adjacent
    chord directions); free ends use the terminal chord direction."""
    segs: list[dict[str, Any]] = []
    n = len(spec.pieces)
    for i, (pid, pts) in enumerate(spec.pieces):
        if pts.shape[0] < 2:
            raise ValueError(f"{pid}: a development needs at least two vertices")
        d_first = _unit(pts[1] - pts[0])
        d_last = _unit(pts[-1] - pts[-2])
        if i > 0:
            prev = spec.pieces[i - 1][1]
            if float(np.linalg.norm(prev[-1] - pts[0])) > RING_ON_POLYLINE_TOLERANCE:
                raise ValueError(f"{pid}: piece chain is not welded to {spec.pieces[i - 1][0]}")
            t_start = _unit(_unit(prev[-1] - prev[-2]) + d_first)
        else:
            t_start = d_first
        if i < n - 1:
            nxt = spec.pieces[i + 1][1]
            t_end = _unit(d_last + _unit(nxt[1] - nxt[0]))
        else:
            t_end = d_last
        segs.append(
            {
                "levelId": spec.level_id,
                "segmentId": pid,
                "effectiveSource": spec.kind,
                "effectiveCenterline": {"points": pts.ravel().tolist(), "pointCount": len(pts)},
                "boundaryTangents": {"start": t_start.tolist(), "end": t_end.tolist()},
            }
        )
    return segs


def secondary_profile(profile: TunnelProfile) -> TunnelProfile:
    """Coarser RENDER tessellation for secondary developments (§4.F); the
    engineering dimensions (from ``RampConstraints``) are untouched."""
    return profile.model_copy(
        update={
            "arch_segments": max(
                SECONDARY_ARCH_MIN, profile.arch_segments // SECONDARY_ARCH_DIVISOR
            ),
            "ring_max_spacing": profile.ring_max_spacing * SECONDARY_SPACING_FACTOR,
        }
    )


# --------------------------------------------------------------------------- #
# 3. QA — CAP (closed solid) vs OPEN (manifold with boundary)
# --------------------------------------------------------------------------- #


@dataclass
class DevelopmentTopologyReport:
    policy: str  # "CAP-CAP" | "OPEN-CAP" | "CAP-OPEN" | "OPEN-OPEN"
    finite: bool = True
    valid_indices: bool = True
    degenerate_triangles: int = 0
    orientation_consistent: bool = True
    boundary_edges: int = 0
    expected_boundary_edges: int = 0
    boundary_loops_on_end_rings: bool = True
    non_manifold_edges: int = 0
    watertight: bool | None = None  # CAP-CAP only
    signed_volume: float | None = None  # CAP-CAP only
    surface_area: float = 0.0
    rings_on_centerline: bool = True
    ring_count: int = 0
    triangle_count: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.problems


def strip_caps(mesh: LogicalMesh, start: EndpointPolicy, end: EndpointPolicy) -> LogicalMesh:
    """Remove the cap fans of OPEN ends from the closed logical mesh built by
    ``build_logical_mesh`` (tube triangles are untouched)."""
    drop: list[int] = []
    if start == "OPEN":
        drop.append(mesh.n_segments)
    if end == "OPEN":
        drop.append(mesh.n_segments + 1)
    keep = ~np.isin(mesh.tri_group, drop) if drop else np.ones(len(mesh.tri_group), dtype=bool)
    return LogicalMesh(
        positions=mesh.positions,
        triangles=mesh.triangles[keep],
        tri_group=mesh.tri_group[keep],
        k=mesh.k,
        ring_count=mesh.ring_count,
        n_segments=mesh.n_segments,
    )


def validate_development_topology(
    mesh: LogicalMesh,
    chain: RingChain,
    spec: DevelopmentSpec,
) -> DevelopmentTopologyReport:
    rep = DevelopmentTopologyReport(policy=f"{spec.start}-{spec.end}")
    tris = mesh.triangles
    pos = mesh.positions
    r, k = mesh.ring_count, mesh.k
    rep.ring_count = r
    rep.triangle_count = int(tris.shape[0])
    rep.finite = bool(np.all(np.isfinite(pos)))
    if not rep.finite:
        rep.problems.append("non-finite vertex positions")
    rep.valid_indices = bool(tris.min() >= 0 and tris.max() < pos.shape[0]) if tris.size else True
    if not rep.valid_indices:
        rep.problems.append("triangle index out of range")
        return rep
    v0, v1, v2 = pos[tris[:, 0]], pos[tris[:, 1]], pos[tris[:, 2]]
    cross = np.cross(v1 - v0, v2 - v0)
    areas = 0.5 * np.linalg.norm(cross, axis=1)
    rep.degenerate_triangles = int((areas < 1e-9).sum())
    if rep.degenerate_triangles:
        rep.problems.append(f"{rep.degenerate_triangles} degenerate triangles")
    rep.surface_area = float(areas.sum())
    directed: dict[tuple[int, int], int] = {}
    undirected: dict[tuple[int, int], int] = {}
    for a, b, c in tris:
        for u, v in ((a, b), (b, c), (c, a)):
            directed[(int(u), int(v))] = directed.get((int(u), int(v)), 0) + 1
            key = (int(min(u, v)), int(max(u, v)))
            undirected[key] = undirected.get(key, 0) + 1
    bad_dir = sum(1 for n in directed.values() if n != 1)
    rep.orientation_consistent = bad_dir == 0
    if bad_dir:
        rep.problems.append(f"{bad_dir} directed edges used more than once (orientation)")
    rep.non_manifold_edges = sum(1 for n in undirected.values() if n > 2)
    if rep.non_manifold_edges:
        rep.problems.append(f"{rep.non_manifold_edges} non-manifold edges")
    boundary = [e for e, n in undirected.items() if n == 1]
    rep.boundary_edges = len(boundary)
    open_ends = int(spec.start == "OPEN") + int(spec.end == "OPEN")
    rep.expected_boundary_edges = open_ends * k
    if rep.boundary_edges != rep.expected_boundary_edges:
        rep.problems.append(
            f"{rep.boundary_edges} boundary edges, expected {rep.expected_boundary_edges} "
            f"({open_ends} open end(s) x K={k})"
        )
    # every boundary edge must lie on an OPEN end ring
    end_rings: set[int] = set()
    if spec.start == "OPEN":
        end_rings.update(range(0, k))
    if spec.end == "OPEN":
        end_rings.update(range((r - 1) * k, r * k))
    rep.boundary_loops_on_end_rings = all(u in end_rings and v in end_rings for u, v in boundary)
    if not rep.boundary_loops_on_end_rings:
        rep.problems.append("a boundary edge lies away from the open end rings")
    if open_ends == 0:
        rep.watertight = all(n == 2 for n in undirected.values())
        rep.signed_volume = float(np.einsum("ij,ij->i", v0, np.cross(v1, v2)).sum() / 6.0)
        if not rep.watertight:
            rep.problems.append("closed development is not watertight")
        if rep.signed_volume <= 0.0:
            rep.problems.append(f"signed volume {rep.signed_volume:.3f} not positive")
    # ring / centerline correspondence: every authoritative vertex is a ring
    # center and every ring center lies on the polyline (rule 65)
    poly = np.vstack([p if i == 0 else p[1:] for i, (_, p) in enumerate(spec.pieces)])
    centers = chain.centers
    on_poly = _points_on_polyline(centers, poly, RING_ON_POLYLINE_TOLERANCE)
    vertices_present = all(
        float(np.min(np.linalg.norm(centers - v, axis=1))) <= RING_ON_POLYLINE_TOLERANCE
        for v in poly
    )
    rep.rings_on_centerline = bool(on_poly and vertices_present)
    if not rep.rings_on_centerline:
        rep.problems.append("ring centers do not correspond to the authoritative centerline")
    return rep


def _points_on_polyline(points: FloatArray, poly: FloatArray, tol: float) -> bool:
    a = poly[:-1]
    b = poly[1:]
    ab = b - a
    ab2 = np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-24)
    for p in points:
        # projection parameter per edge
        t = np.clip(np.einsum("ij,ij->i", p[None, :] - a, ab) / ab2, 0.0, 1.0)
        q = a + t[:, None] * ab
        if float(np.min(np.linalg.norm(q - p[None, :], axis=1))) > tol:
            return False
    return True


@dataclass
class DevelopmentEnvelopeReport:
    hard_violations: int = 0
    above_terrain: int = 0


def validate_development_envelope(
    evaluator: DesignCostEvaluator, mesh: LogicalMesh
) -> DevelopmentEnvelopeReport:
    """Excavation envelope of an UNDERGROUND development: every ring vertex
    must be inside the world, outside restricted zones, clear of the
    orebody exclusion (unless the context permits it — crosscuts) and below
    the terrain. No portal transition exists for developments."""
    r, k = mesh.ring_count, mesh.k
    hard, above = evaluator.envelope_masks(mesh.positions[: r * k])
    return DevelopmentEnvelopeReport(int(hard.sum()), int(above.sum()))


# --------------------------------------------------------------------------- #
# 4. Orchestration — one batched render mesh per development kind
# --------------------------------------------------------------------------- #


@dataclass
class DevelopmentMeshResult:
    status: str  # SUCCESS | FAILED
    report: dict[str, Any]
    glb: bytes | None


@dataclass
class _Swept:
    spec: DevelopmentSpec
    chain: RingChain
    render: RenderMesh
    topology: DevelopmentTopologyReport
    envelope: DevelopmentEnvelopeReport
    length3d: float
    nominal_volume: float


class DevelopmentMeshBuilder:
    """Sweeps every development of the owning artifacts with the shared
    profile frame; batches the render geometry per kind (one primitive per
    kind plus one cap primitive per kind) so draw calls stay bounded while
    ``developmentId`` correspondence is preserved in primitive extras."""

    def __init__(
        self,
        drift_evaluator: DesignCostEvaluator,
        crosscut_evaluator: DesignCostEvaluator,
        ramp: RampConstraints,
        profile: TunnelProfile,
    ) -> None:
        self.drift_ev = drift_evaluator
        self.crosscut_ev = crosscut_evaluator
        self.ramp = ramp
        self.profile = secondary_profile(profile)
        self.main_profile = profile

    def _evaluator_for(self, kind: DevelopmentMeshKind) -> DesignCostEvaluator:
        return self.crosscut_ev if kind == "CROSSCUT" else self.drift_ev

    def sweep(self, spec: DevelopmentSpec, shape: ProfileShape) -> _Swept:
        segs = chain_segments(spec)
        chain = build_ring_chain(segs, self.profile.ring_max_spacing)
        if chain.max_local_turn_deg > self.profile.ring_max_turn_deg + 1e-9:
            raise ValueError(
                f"{spec.development_id}: local turn {chain.max_local_turn_deg:.2f}° exceeds "
                f"ringMaxTurnDeg {self.profile.ring_max_turn_deg:g}°"
            )
        closed = build_logical_mesh(chain, shape)
        logical = strip_caps(closed, spec.start, spec.end)
        topology = validate_development_topology(logical, chain, spec)
        envelope = validate_development_envelope(self._evaluator_for(spec.kind), logical)
        meta = [
            {"segmentId": s["segmentId"], "levelId": spec.level_id, "effectiveSource": spec.kind}
            for s in segs
        ]
        render = build_render_mesh(
            closed,
            chain,
            shape,
            self.profile.crease_angle_deg,
            meta,
            caps=(spec.start == "CAP", spec.end == "CAP"),
        )
        length = float(chain.chainage[-1])
        return _Swept(spec, chain, render, topology, envelope, length, shape.analytic_area * length)

    def build(
        self,
        accesses_payload: dict[str, Any] | None,
        levels_payload: dict[str, Any] | None,
        on_progress: Any = None,
    ) -> DevelopmentMeshResult:
        from minegen.design.glb_writer import write_glb

        specs = specs_from_artifacts(accesses_payload, levels_payload)
        if not specs:
            return DevelopmentMeshResult(
                "FAILED",
                {
                    "status": "FAILED",
                    "failureReason": (
                        "NO_DEVELOPMENTS: neither a SUCCESS level-access artifact nor a "
                        "SUCCESS levels artifact with developments is available"
                    ),
                },
                None,
            )
        shape = build_profile(self.ramp, self.profile)
        swept: list[_Swept] = []
        problems: list[str] = []
        n = len(specs)
        for i, spec in enumerate(specs):
            if on_progress is not None:
                on_progress(i, n, spec.development_id, "SEGMENT_STARTED")
            try:
                sw = self.sweep(spec, shape)
            except ValueError as exc:
                problems.append(str(exc))
                continue
            if not sw.topology.valid:
                problems.append(f"{spec.development_id}: " + "; ".join(sw.topology.problems))
            if sw.envelope.hard_violations or sw.envelope.above_terrain:
                problems.append(
                    f"{spec.development_id}: envelope {sw.envelope.hard_violations} hard, "
                    f"{sw.envelope.above_terrain} above terrain"
                )
            swept.append(sw)
        report = self._report(swept, shape)
        if problems:
            report["status"] = "FAILED"
            report["failureReason"] = "; ".join(problems[:20]) + (
                f" (+{len(problems) - 20} more)" if len(problems) > 20 else ""
            )
            return DevelopmentMeshResult("FAILED", report, None)
        render = batch_render(swept)
        report["renderVertexCount"] = render.render_vertex_count
        report["primitiveCount"] = len(render.primitives)
        report["primitives"] = [
            {
                "name": p.name,
                "role": p.extras.get("role"),
                "kind": p.extras.get("kind"),
                "triangleCount": int(p.indices.shape[0] // 3),
            }
            for p in render.primitives
        ]
        glb = write_glb(render, generator="minegen-phase20b-development", name="developments")
        report["status"] = "SUCCESS"
        report["failureReason"] = None
        if on_progress is not None:
            on_progress(n, n, "", "MESH_COMPLETED")
        return DevelopmentMeshResult("SUCCESS", report, glb)

    def _report(self, swept: list[_Swept], shape: ProfileShape) -> dict[str, Any]:
        per_kind: dict[str, dict[str, Any]] = {}
        for kind in KIND_ORDER:
            items = [s for s in swept if s.spec.kind == kind]
            per_kind[kind] = {
                "developmentCount": len(items),
                "ringCount": sum(s.chain.centers.shape[0] for s in items),
                "triangleCount": sum(s.topology.triangle_count for s in items),
                "length3d": sum(s.length3d for s in items),
                "nominalExcavationVolume": sum(s.nominal_volume for s in items),
                "surfaceArea": sum(s.topology.surface_area for s in items),
                "endpointPolicies": sorted({s.topology.policy for s in items}),
            }
        return {
            "profile": {
                "archSegments": self.profile.arch_segments,
                "mainRampArchSegments": self.main_profile.arch_segments,
                "ringMaxSpacing": self.profile.ring_max_spacing,
                "mainRampRingMaxSpacing": self.main_profile.ring_max_spacing,
                "analyticProfileArea": shape.analytic_area,
                "meshProfileArea": shape.mesh_area,
                "tessellationBiasPct": shape.tessellation_bias_pct,
            },
            "developmentCount": len(swept),
            "ringCount": sum(s.chain.centers.shape[0] for s in swept),
            "triangleCount": sum(s.topology.triangle_count for s in swept),
            "length3d": sum(s.length3d for s in swept),
            "nominalExcavationVolume": sum(s.nominal_volume for s in swept),
            "byKind": per_kind,
            "developments": [
                {
                    "developmentId": s.spec.development_id,
                    "kind": s.spec.kind,
                    "levelId": s.spec.level_id,
                    "geometryRef": s.spec.geometry_ref,
                    "pieceIds": [pid for pid, _ in s.spec.pieces],
                    "endpointPolicy": {"start": s.spec.start, "end": s.spec.end},
                    "length3d": s.length3d,
                    "nominalExcavationVolume": s.nominal_volume,
                    "ringCount": int(s.chain.centers.shape[0]),
                    "triangleCount": s.topology.triangle_count,
                    "maxLocalTurnDeg": s.chain.max_local_turn_deg,
                    "topology": {
                        "policy": s.topology.policy,
                        "finite": s.topology.finite,
                        "validIndices": s.topology.valid_indices,
                        "degenerateTriangles": s.topology.degenerate_triangles,
                        "orientationConsistent": s.topology.orientation_consistent,
                        "boundaryEdges": s.topology.boundary_edges,
                        "expectedBoundaryEdges": s.topology.expected_boundary_edges,
                        "boundaryOnEndRings": s.topology.boundary_loops_on_end_rings,
                        "nonManifoldEdges": s.topology.non_manifold_edges,
                        "watertight": s.topology.watertight,
                        "signedVolume": s.topology.signed_volume,
                        "ringsOnCenterline": s.topology.rings_on_centerline,
                        "valid": s.topology.valid,
                        "problems": list(s.topology.problems),
                    },
                    "envelope": {
                        "hardViolations": s.envelope.hard_violations,
                        "aboveTerrain": s.envelope.above_terrain,
                    },
                }
                for s in swept
            ],
            "booleanUnion": "NOT_IMPLEMENTED",  # Phase 20D scope (§4.D)
        }


def batch_render(swept: list[_Swept]) -> RenderMesh:
    """One vertex buffer; per development KIND one tube primitive (extras
    ``ranges`` map index ranges back to development / piece ids) and, where
    any CAP end exists, one cap primitive. Materials are shared by role on
    the client; draw calls = primitives ≤ 2 × kinds."""
    positions: list[npt.NDArray[np.float32]] = []
    normals: list[npt.NDArray[np.float32]] = []
    uvs: list[npt.NDArray[np.float32]] = []
    tube_idx: dict[str, list[npt.NDArray[np.uint32]]] = {k: [] for k in KIND_ORDER}
    cap_idx: dict[str, list[npt.NDArray[np.uint32]]] = {k: [] for k in KIND_ORDER}
    ranges: dict[str, list[dict[str, Any]]] = {k: [] for k in KIND_ORDER}
    offset = 0
    for s in swept:
        kind = s.spec.kind
        positions.append(s.render.positions)
        normals.append(s.render.normals)
        uvs.append(s.render.uvs)
        cursor = sum(int(x.shape[0]) for x in tube_idx[kind])
        for prim in s.render.primitives:
            idx = (prim.indices.astype(np.uint32) + np.uint32(offset)).astype(np.uint32)
            if prim.extras.get("role") == "SEGMENT":
                ranges[kind].append(
                    {
                        "developmentId": s.spec.development_id,
                        "pieceId": prim.extras.get("segmentId"),
                        "levelId": s.spec.level_id,
                        "indexOffset": cursor,
                        "indexCount": int(idx.shape[0]),
                    }
                )
                tube_idx[kind].append(idx)
                cursor += int(idx.shape[0])
            else:
                cap_idx[kind].append(idx)
        offset += int(s.render.positions.shape[0])
    prims: list[RenderPrimitive] = []
    for kind in KIND_ORDER:
        if tube_idx[kind]:
            prims.append(
                RenderPrimitive(
                    name=kind,
                    extras={"role": "DEVELOPMENT", "kind": kind, "ranges": ranges[kind]},
                    indices=np.concatenate(tube_idx[kind]).astype(np.uint32),
                )
            )
        if cap_idx[kind]:
            prims.append(
                RenderPrimitive(
                    name=f"{kind}_CAP",
                    extras={"role": f"{kind}_CAP", "kind": kind},
                    indices=np.concatenate(cap_idx[kind]).astype(np.uint32),
                )
            )
    pos = np.vstack(positions).astype(np.float32)
    return RenderMesh(
        positions=pos,
        normals=np.vstack(normals).astype(np.float32),
        uvs=np.vstack(uvs).astype(np.float32),
        primitives=prims,
        geometrically_closed=False,
        render_vertex_count=int(pos.shape[0]),
    )


__all__ = [
    "DevelopmentMeshBuilder",
    "DevelopmentMeshResult",
    "DevelopmentSpec",
    "EndpointPolicy",
    "chain_segments",
    "secondary_profile",
    "specs_from_artifacts",
    "strip_caps",
    "validate_development_envelope",
    "validate_development_topology",
]
