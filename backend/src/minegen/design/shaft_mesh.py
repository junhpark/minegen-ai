"""Shaft excavation meshes (hardening PR-2 H2-SH) — the SEPARATE
``shaft_mesh.json`` / ``shaft_mesh.glb`` artifact derived from ``shafts.json``.

A declared vertical shaft (Phase 20C.2B, rules 182–184) is swept into three
excavation primitives on its AUTHORITATIVE ``shafts.json`` centerlines —
never re-planned, moved or re-sampled:

* the BARREL: a circular cross-section (``diameter`` from the shaft profile,
  ``K = 2 × arch_segments`` ring vertices) swept along the vertical axis
  segments ``collar → STN₁ → … → STNₙ → bottom`` with ONE CONSTANT frame
  (``right = +X``, ``up = +Y``, ``forward = −Z`` — a right-handed
  ``(right, forward, up)`` triple, so the shared logical-mesh winding stays
  outward). The rule-26 gravity-aligned frame is undefined for a vertical
  tangent (``core.coordinates.gravity_aligned_frame`` refuses it) and a
  parallel-transport frame is pointless for a straight axis, so the barrel
  carries its own fixed frame — rule 26 reserves the transported frame for
  inclined raises / winzes, which are deferred;
* the COLLAR CAP (the surface end) and the SUMP CAP (the bottom end) —
  closed, so the barrel is a CAP–CAP solid (manifold, watertight, outward,
  positive signed volume — the Phase 06 closed-solid QA);
* one STATION ACCESS DRIVE per station — the straight horizontal-ish line
  from the axis station to the EXISTING level node, swept with the
  secondary horseshoe profile of the development mesh (rule 166 tessellation)
  and judged as an OPEN–OPEN manifold with boundary (K boundary edges at the
  shaft end, K at the level end).

No CSG: the drive's open start ring sits inside the barrel and its open end
inside the level development, exactly as the Phase 20B turnouts leave the
neighbouring shell visible (the recorded Phase 20D limitation). Every tube is
validated against the shared ``DesignCostEvaluator`` envelope gates — the
barrel under ``DesignContext.shaft`` (orebody buffer hard, restricted zones
hard, world bounds hard, terrain break-through permitted only inside the
collar zone of one diameter below the collar — the SAME zone the planner
accepts), the drives under the level-development context. Failure is
explicit: an invalid tube fails the artifact, nothing is clamped and no GLB
is published for a FAILED report.

Render contract (frontend visualization only, rule 173 analogue): the GLB is
batched like the development mesh — one tube primitive per kind
(``SHAFT`` barrels, ``SHAFT_STATION_ACCESS`` drives) whose ``ranges`` extras
map index ranges back to the owning centerline ids with the per-piece
progressive-reveal metadata (``indexStride`` / ``ringIntervalCount`` /
``ringChainageFractions`` / ``ringIntervalIndexOffsets``), plus two cap
primitives ``SHAFT_COLLAR_CAP`` and ``SHAFT_SUMP_CAP``. Piece ids ARE the
``shafts.json`` centerline ids (``SHAFT:<shaftId>:SEG<kk>``,
``SHAFT_STATION_ACCESS:<shaftId>:<levelId>``) — the MineNetwork edge ids and
therefore the ids every ``timeline.json`` RAMP-style ``geometryRef`` resolves
to, so the 4D reveal maps timeline → owning artifact → piece and fails closed
per piece. The shaft is NOT a walkthrough space (no cage physics); the
walkthrough contract (rules 187, 103) is untouched.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.core.artifacts import SHAFTS_ARTIFACT
from minegen.core.models import RampConstraints, TunnelProfile
from minegen.design.cost_field import DesignCostEvaluator
from minegen.design.development_mesh import (
    DevelopmentEnvelopeReport,
    DevelopmentSpec,
    DevelopmentTopologyReport,
    chain_segments,
    closed_sweep,
    strip_caps,
    validate_development_envelope,
    validate_development_topology,
)
from minegen.design.profile import ProfileShape, build_profile, secondary_profile
from minegen.design.tunnel_mesh import (
    VOLUME_QA_TOLERANCE_PCT,
    LogicalMesh,
    RenderMesh,
    RenderPrimitive,
    RingChain,
    TopologyReport,
    build_render_mesh,
    build_ring_chain,
    logical_mesh_from_rings,
    validate_topology,
)

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]

SHAFT_KIND = "SHAFT"
STATION_ACCESS_KIND = "SHAFT_STATION_ACCESS"
SHAFT_MESH_KINDS: tuple[str, str] = (SHAFT_KIND, STATION_ACCESS_KIND)
COLLAR_CAP_ROLE = "SHAFT_COLLAR_CAP"
SUMP_CAP_ROLE = "SHAFT_SUMP_CAP"
#: barrel ring vertices = this factor × ``tunnel_profile.arch_segments``
BARREL_SEGMENT_FACTOR = 2
BARREL_SEGMENTS_MIN = 8
#: the collar zone in which an above-terrain barrel vertex is NOT a
#: break-through — one diameter below the collar, the planner's own zone
#: (``shafts/planner.py::_validate_axis``: ``depth <= 2 × radius``)
COLLAR_ZONE_DIAMETERS = 1.0
GLB_GENERATOR = "minegen-pr2-shaft-mesh"


# --------------------------------------------------------------------------- #
# 1. Circular profile + vertical sweep
# --------------------------------------------------------------------------- #


def circular_profile(diameter: float, segments: int) -> ProfileShape:
    """Closed circular cross-section centred on the AXIS (local origin),
    ``segments`` vertices counter-clockwise starting at ``+right``.
    ``analytic_area`` is the exact circle; the inscribed polygon area is the
    tessellated ``mesh_area`` (rule 67: nominal volume never depends on the
    tessellation). ``crown_radius`` is the radius and ``centroid`` the axis."""
    if diameter <= 0.0:
        raise ValueError("shaft diameter must be positive")
    if segments < 3:
        raise ValueError("a circular profile needs at least 3 segments")
    r = diameter / 2.0
    theta = np.linspace(0.0, 2.0 * math.pi, segments, endpoint=False)
    pts = np.column_stack([r * np.cos(theta), r * np.sin(theta)])
    x, y = pts[:, 0], pts[:, 1]
    xn, yn = np.roll(x, -1), np.roll(y, -1)
    mesh_area = 0.5 * float(np.sum(x * yn - xn * y))
    edges = np.linalg.norm(np.diff(np.vstack([pts, pts[:1]]), axis=0), axis=1)
    perim = float(edges.sum())
    u = np.concatenate([[0.0], np.cumsum(edges)]) / perim
    return ProfileShape(
        points=pts,
        mesh_area=mesh_area,
        analytic_area=math.pi * r * r,
        perimeter_u=u,
        crown_radius=r,
        crown_center_y=0.0,
        centroid=np.zeros(2),
    )


#: the barrel's constant sweep frame — a right-handed ``(right, forward, up)``
#: triple for a DOWNWARD axis: ``right × forward = X × (−Z) = +Y = up``
BARREL_RIGHT: FloatArray = np.array([1.0, 0.0, 0.0])
BARREL_UP: FloatArray = np.array([0.0, 1.0, 0.0])
BARREL_FORWARD: FloatArray = np.array([0.0, 0.0, -1.0])
#: a barrel axis must be vertical within this cosine tolerance
VERTICAL_COS_TOLERANCE = 1e-9


def barrel_rings(chain: RingChain, shape: ProfileShape) -> FloatArray:
    """Profile vertices swept along the vertical axis with the constant barrel
    frame → ``(R, K, 3)``. Refuses a non-vertical chain explicitly: this
    frame is the barrel's and nothing else's."""
    if np.any(np.abs(chain.tangents @ BARREL_FORWARD - 1.0) > VERTICAL_COS_TOLERANCE):
        raise ValueError("the shaft barrel sweep needs a vertical, downward axis")
    x = shape.points[:, 0]
    y = shape.points[:, 1]
    return (
        chain.centers[:, None, :]
        + x[None, :, None] * BARREL_RIGHT[None, None, :]
        + y[None, :, None] * BARREL_UP[None, None, :]
    )


def build_barrel_logical_mesh(chain: RingChain, shape: ProfileShape) -> LogicalMesh:
    """The closed barrel: rings on the axis + collar cap apex (ring 0 centre,
    the collar) + sump cap apex (last ring centre, the bottom). The shared
    ``logical_mesh_from_rings`` loop gives the Phase 06 winding; with the
    right-handed barrel frame the normals point outward (rule 66 — checked by
    the signed volume)."""
    rings = barrel_rings(chain, shape)
    return logical_mesh_from_rings(chain, rings, chain.centers[0], chain.centers[-1])


# --------------------------------------------------------------------------- #
# 2. Barrel envelope (collar-zone aware)
# --------------------------------------------------------------------------- #


@dataclass
class BarrelEnvelopeReport:
    hard_violations: int = 0
    #: above-terrain barrel vertices DEEPER than the collar zone (fatal)
    above_terrain_below_collar_zone: int = 0
    #: above-terrain barrel vertices inside the collar zone (permitted — the
    #: shaft breaks the surface by definition, rule 183)
    collar_zone_above_terrain: int = 0
    collar_zone_depth: float = 0.0

    @property
    def valid(self) -> bool:
        return self.hard_violations == 0 and self.above_terrain_below_collar_zone == 0


def validate_barrel_envelope(
    evaluator: DesignCostEvaluator,
    mesh: LogicalMesh,
    chain: RingChain,
    diameter: float,
) -> BarrelEnvelopeReport:
    """Every barrel ring vertex through the SHARED envelope gates
    (``envelope_masks`` under ``DesignContext.shaft``: world XY / bottom,
    orebody exclusion buffer, restricted zones are hard). Terrain
    break-through is permitted only inside the collar zone — ``depth below
    the collar <= COLLAR_ZONE_DIAMETERS × diameter`` — the planner's zone."""
    r, k = mesh.ring_count, mesh.k
    pts = mesh.positions[: r * k]
    hard, above = evaluator.envelope_masks(pts)
    depth = np.repeat(float(chain.centers[0][2]) - chain.centers[:, 2], k)
    zone = COLLAR_ZONE_DIAMETERS * diameter
    in_zone = depth <= zone + 1e-9
    return BarrelEnvelopeReport(
        hard_violations=int(hard.sum()),
        above_terrain_below_collar_zone=int((above & ~in_zone).sum()),
        collar_zone_above_terrain=int((above & in_zone).sum()),
        collar_zone_depth=zone,
    )


# --------------------------------------------------------------------------- #
# 3. Specs from shafts.json
# --------------------------------------------------------------------------- #


def _pts(flat: list[float]) -> FloatArray:
    return np.asarray(flat, dtype=np.float64).reshape(-1, 3)


@dataclass(frozen=True)
class ShaftMeshSpecs:
    shaft_id: str
    diameter: float
    barrel: DevelopmentSpec
    drives: tuple[DevelopmentSpec, ...]


def specs_from_shafts(shafts_payload: dict[str, Any]) -> tuple[list[ShaftMeshSpecs], list[str]]:
    """One barrel spec (axis segments chained collar → bottom, CAP–CAP) and
    one OPEN–OPEN drive spec per OK station for every OK shaft. FAILED shafts
    own no geometry and are reported as skipped — never invented."""
    centerlines: list[dict[str, Any]] = list(shafts_payload.get("centerlines") or [])
    specs: list[ShaftMeshSpecs] = []
    skipped: list[str] = []
    for sh in shafts_payload.get("shafts") or []:
        sid = str(sh.get("shaftId"))
        if sh.get("status") != "OK":
            skipped.append(f"{sid}: {sh.get('failureCode') or 'FAILED'}")
            continue
        pieces: list[tuple[str, FloatArray]] = []
        for index in sh.get("segmentIndices") or []:
            cl = centerlines[int(index)]
            if cl.get("kind") != "SHAFT_SEGMENT" or cl.get("shaftId") != sid:
                raise ValueError(f"{sid}: segmentIndices[{index}] is not an axis segment of it")
            pieces.append((str(cl["id"]), _pts(cl["centerline"]["points"])))
        if not pieces:
            raise ValueError(f"{sid}: an OK shaft has no axis segment")
        barrel = DevelopmentSpec(
            development_id=sid,
            kind=SHAFT_KIND,  # type: ignore[arg-type]
            level_id="",
            pieces=tuple(pieces),
            start="CAP",
            end="CAP",
            geometry_ref={
                "artifact": SHAFTS_ARTIFACT,
                "segmentIndices": list(sh["segmentIndices"]),
            },
        )
        drives: list[DevelopmentSpec] = []
        for st in sh.get("stations") or []:
            index = st.get("accessCenterlineIndex")
            if st.get("status") != "OK" or index is None:
                raise ValueError(
                    f"{sid}: OK shaft carries a station without a validated drive "
                    f"({st.get('stationId')})"
                )
            cl = centerlines[int(index)]
            if cl.get("kind") != "STATION_ACCESS" or cl.get("shaftId") != sid:
                raise ValueError(f"{sid}: accessCenterlineIndex {index} is not a station drive")
            drives.append(
                DevelopmentSpec(
                    development_id=str(cl["id"]),
                    kind=STATION_ACCESS_KIND,  # type: ignore[arg-type]
                    level_id=str(st.get("levelId")),
                    pieces=((str(cl["id"]), _pts(cl["centerline"]["points"])),),
                    start="OPEN",
                    end="OPEN",
                    geometry_ref={"artifact": SHAFTS_ARTIFACT, "segmentIndex": int(index)},
                )
            )
        specs.append(
            ShaftMeshSpecs(
                shaft_id=sid,
                diameter=float(sh["profile"]["diameter"]),
                barrel=barrel,
                drives=tuple(drives),
            )
        )
    return specs, skipped


# --------------------------------------------------------------------------- #
# 4. Builder
# --------------------------------------------------------------------------- #


@dataclass
class ShaftMeshResult:
    status: str  # SUCCESS | FAILED
    report: dict[str, Any]
    glb: bytes | None


@dataclass
class _SweptBarrel:
    spec: DevelopmentSpec
    chain: RingChain
    shape: ProfileShape
    render: RenderMesh
    topology: TopologyReport
    envelope: BarrelEnvelopeReport
    length3d: float
    nominal_volume: float
    triangle_count: int
    #: |mesh − analytic nominal| / nominal × 100 (reported, rule 67)
    volume_difference_pct: float
    problems: list[str] = field(default_factory=list)


@dataclass
class _SweptDrive:
    shaft_id: str
    spec: DevelopmentSpec
    chain: RingChain
    render: RenderMesh
    topology: DevelopmentTopologyReport
    envelope: DevelopmentEnvelopeReport
    length3d: float
    nominal_volume: float


class ShaftMeshBuilder:
    """Sweeps every OK shaft of a SUCCESS ``shafts.json`` into the batched
    shaft excavation GLB + typed report. ``axis_evaluator`` carries
    ``DesignContext.shaft`` (the planner's own barrel gates),
    ``access_evaluator`` the level-development context under the ACTIVE
    clearance policy (rule 172) — the same pair ``ShaftPlanner`` plans with."""

    def __init__(
        self,
        axis_evaluator: DesignCostEvaluator,
        access_evaluator: DesignCostEvaluator,
        ramp: RampConstraints,
        profile: TunnelProfile,
    ) -> None:
        self.axis_ev = axis_evaluator
        self.access_ev = access_evaluator
        self.ramp = ramp
        self.profile = profile
        self.drive_profile = secondary_profile(profile)
        self.drive_shape = build_profile(ramp, self.drive_profile)
        self.barrel_segments = max(
            BARREL_SEGMENTS_MIN, BARREL_SEGMENT_FACTOR * int(profile.arch_segments)
        )

    # -- sweeps ------------------------------------------------------------- #

    def sweep_barrel(self, spec: DevelopmentSpec, diameter: float) -> _SweptBarrel:
        shape = circular_profile(diameter, self.barrel_segments)
        chain = build_ring_chain(chain_segments(spec), self.profile.ring_max_spacing)
        mesh = build_barrel_logical_mesh(chain, shape)
        topology = validate_topology(mesh, (mesh.n_segments, mesh.n_segments + 1))
        envelope = validate_barrel_envelope(self.axis_ev, mesh, chain, diameter)
        length = float(chain.chainage[-1])
        nominal = shape.analytic_area * length
        problems: list[str] = list(topology.problems)
        if not (topology.manifold and topology.watertight and topology.outward_orientation):
            problems.append("barrel is not a closed outward solid")
        if nominal > 0.0:
            diff_pct = abs(topology.signed_volume - nominal) / nominal * 100.0
            # the inscribed polygon is smaller than the circle by the
            # tessellation bias; the QA tolerance is judged against the
            # TESSELLATED volume, exactly as the ramp tunnel does (rule 67)
            mesh_nominal = shape.mesh_area * length
            if abs(topology.signed_volume - mesh_nominal) / mesh_nominal * 100.0 > (
                VOLUME_QA_TOLERANCE_PCT
            ):
                problems.append(
                    f"barrel signed volume {topology.signed_volume:.3f} differs from the swept "
                    f"volume {mesh_nominal:.3f} by more than {VOLUME_QA_TOLERANCE_PCT:g} %"
                )
        else:
            diff_pct = 0.0
            problems.append("barrel has no length")
        if not envelope.valid:
            problems.append(
                f"barrel envelope: {envelope.hard_violations} hard violations, "
                f"{envelope.above_terrain_below_collar_zone} vertices above terrain below the "
                f"collar zone"
            )
        meta = [
            {"segmentId": pid, "levelId": spec.development_id, "effectiveSource": SHAFT_KIND}
            for pid, _ in spec.pieces
        ]
        render = build_render_mesh(
            mesh, chain, shape, self.profile.crease_angle_deg, meta, caps=(True, True)
        )
        return _SweptBarrel(
            spec,
            chain,
            shape,
            render,
            topology,
            envelope,
            length,
            nominal,
            int(mesh.triangles.shape[0]),
            diff_pct,
            problems,
        )

    def sweep_drive(self, shaft_id: str, spec: DevelopmentSpec) -> _SweptDrive:
        chain, closed = closed_sweep(
            spec, self.drive_shape, self.drive_profile, float(self.ramp.tunnel_width), None
        )
        logical = strip_caps(closed, spec.start, spec.end)
        topology = validate_development_topology(logical, chain, spec)
        envelope = validate_development_envelope(self.access_ev, logical)
        length = float(chain.chainage[-1])
        meta = [
            {"segmentId": pid, "levelId": spec.level_id, "effectiveSource": STATION_ACCESS_KIND}
            for pid, _ in spec.pieces
        ]
        render = build_render_mesh(
            closed,
            chain,
            self.drive_shape,
            self.drive_profile.crease_angle_deg,
            meta,
            caps=(False, False),
        )
        return _SweptDrive(
            shaft_id,
            spec,
            chain,
            render,
            topology,
            envelope,
            length,
            self.drive_shape.analytic_area * length,
        )

    # -- orchestration ------------------------------------------------------ #

    def build(self, shafts_payload: dict[str, Any], shafts_revision: str) -> ShaftMeshResult:
        from minegen.design.glb_writer import write_glb

        t0 = time.perf_counter()
        base: dict[str, Any] = {
            "shaftsRevision": shafts_revision,
            "booleanUnion": "NONE",
            "limitations": [
                "no CSG: a station drive's open rings sit inside the barrel and the level "
                "development (Phase 20D unified-mesh scope)",
                "the shaft is not a walkthrough space (no cage physics, rule 187 unchanged)",
            ],
        }
        if shafts_payload.get("status") != "SUCCESS":
            return ShaftMeshResult(
                "FAILED",
                {
                    **base,
                    "status": "FAILED",
                    "failureReason": (
                        "SHAFTS_NOT_SUCCESS: the shaft artifact status is "
                        f"{shafts_payload.get('status')!r}; the mesh sweeps validated shafts only"
                    ),
                },
                None,
            )
        try:
            specs, skipped = specs_from_shafts(shafts_payload)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            return ShaftMeshResult(
                "FAILED",
                {**base, "status": "FAILED", "failureReason": f"SHAFTS_MALFORMED: {exc}"},
                None,
            )
        if not specs:
            return ShaftMeshResult(
                "FAILED",
                {
                    **base,
                    "status": "FAILED",
                    "failureReason": "NO_SHAFTS: the shaft artifact declares no OK shaft",
                    "skippedShafts": skipped,
                },
                None,
            )
        barrels: list[_SweptBarrel] = []
        drives: list[_SweptDrive] = []
        problems: list[str] = []
        for sp in specs:
            try:
                barrel = self.sweep_barrel(sp.barrel, sp.diameter)
            except ValueError as exc:
                problems.append(f"{sp.shaft_id}: {exc}")
                continue
            problems.extend(f"{sp.shaft_id}: {p}" for p in barrel.problems)
            barrels.append(barrel)
            for d in sp.drives:
                try:
                    drive = self.sweep_drive(sp.shaft_id, d)
                except ValueError as exc:
                    problems.append(f"{d.development_id}: {exc}")
                    continue
                if not drive.topology.valid:
                    problems.append(f"{d.development_id}: " + "; ".join(drive.topology.problems))
                if drive.envelope.hard_violations or drive.envelope.above_terrain:
                    problems.append(
                        f"{d.development_id}: envelope {drive.envelope.hard_violations} hard, "
                        f"{drive.envelope.above_terrain} above terrain"
                    )
                drives.append(drive)
        report = {**base, **self._report(specs, barrels, drives, skipped)}
        if problems:
            report["status"] = "FAILED"
            report["failureReason"] = "; ".join(problems[:20]) + (
                f" (+{len(problems) - 20} more)" if len(problems) > 20 else ""
            )
            report["generationSeconds"] = time.perf_counter() - t0
            return ShaftMeshResult("FAILED", report, None)
        render = batch_shaft_render(barrels, drives)
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
        glb = write_glb(render, generator=GLB_GENERATOR, name="shafts")
        report["status"] = "SUCCESS"
        report["failureReason"] = None
        report["generationSeconds"] = time.perf_counter() - t0
        return ShaftMeshResult("SUCCESS", report, glb)

    def _report(
        self,
        specs: list[ShaftMeshSpecs],
        barrels: list[_SweptBarrel],
        drives: list[_SweptDrive],
        skipped: list[str],
    ) -> dict[str, Any]:
        by_shaft = {b.spec.development_id: b for b in barrels}
        shafts_report = []
        for sp in specs:
            b = by_shaft.get(sp.shaft_id)
            own_drives = [d for d in drives if d.shaft_id == sp.shaft_id]
            shafts_report.append(
                {
                    "shaftId": sp.shaft_id,
                    "diameter": sp.diameter,
                    "barrel": None
                    if b is None
                    else {
                        "pieceIds": [pid for pid, _ in b.spec.pieces],
                        "ringCount": int(b.chain.centers.shape[0]),
                        "ringVertices": b.shape.k,
                        "triangleCount": b.triangle_count,
                        "length3d": b.length3d,
                        "nominalExcavationVolume": b.nominal_volume,
                        "meshVolume": b.topology.signed_volume,
                        "volumeDifferencePct": b.volume_difference_pct,
                        "tessellationBiasPct": b.shape.tessellation_bias_pct,
                        "surfaceArea": b.topology.surface_area_total,
                        "topology": {
                            "policy": "CAP-CAP",
                            "manifold": b.topology.manifold,
                            "watertight": b.topology.watertight,
                            "outwardOrientation": b.topology.outward_orientation,
                            "degenerateTriangles": b.topology.degenerate_triangles,
                            "signedVolume": b.topology.signed_volume,
                            "valid": not b.problems,
                            "problems": list(b.problems),
                        },
                        "envelope": {
                            "hardViolations": b.envelope.hard_violations,
                            "aboveTerrainBelowCollarZone": (
                                b.envelope.above_terrain_below_collar_zone
                            ),
                            "collarZoneAboveTerrain": b.envelope.collar_zone_above_terrain,
                            "collarZoneDepth": b.envelope.collar_zone_depth,
                        },
                    },
                    "stationAccesses": [
                        {
                            "pieceId": d.spec.development_id,
                            "levelId": d.spec.level_id,
                            "geometryRef": d.spec.geometry_ref,
                            "endpointPolicy": {"start": "OPEN", "end": "OPEN"},
                            "ringCount": int(d.chain.centers.shape[0]),
                            "triangleCount": d.topology.triangle_count,
                            "length3d": d.length3d,
                            "nominalExcavationVolume": d.nominal_volume,
                            "maxLocalTurnDeg": d.chain.max_local_turn_deg,
                            "topology": {
                                "policy": d.topology.policy,
                                "boundaryEdges": d.topology.boundary_edges,
                                "expectedBoundaryEdges": d.topology.expected_boundary_edges,
                                "boundaryOnEndRings": d.topology.boundary_loops_on_end_rings,
                                "orientationConsistent": d.topology.orientation_consistent,
                                "nonManifoldEdges": d.topology.non_manifold_edges,
                                "ringsOnCenterline": d.topology.rings_on_centerline,
                                "valid": d.topology.valid,
                                "problems": list(d.topology.problems),
                            },
                            "envelope": {
                                "hardViolations": d.envelope.hard_violations,
                                "aboveTerrain": d.envelope.above_terrain,
                            },
                        }
                        for d in own_drives
                    ],
                }
            )
        return {
            "profile": {
                "barrelSegments": self.barrel_segments,
                "barrelRingMaxSpacing": self.profile.ring_max_spacing,
                "driveArchSegments": self.drive_profile.arch_segments,
                "driveRingMaxSpacing": self.drive_profile.ring_max_spacing,
                "driveAnalyticProfileArea": self.drive_shape.analytic_area,
                "collarZoneDiameters": COLLAR_ZONE_DIAMETERS,
            },
            "shaftCount": len(barrels),
            "stationAccessCount": len(drives),
            "skippedShafts": skipped,
            "ringCount": sum(int(b.chain.centers.shape[0]) for b in barrels)
            + sum(int(d.chain.centers.shape[0]) for d in drives),
            "length3d": sum(b.length3d for b in barrels) + sum(d.length3d for d in drives),
            "nominalExcavationVolume": sum(b.nominal_volume for b in barrels)
            + sum(d.nominal_volume for d in drives),
            "byKind": {
                SHAFT_KIND: {
                    "count": len(barrels),
                    "length3d": sum(b.length3d for b in barrels),
                    "nominalExcavationVolume": sum(b.nominal_volume for b in barrels),
                    "endpointPolicies": ["CAP-CAP"] if barrels else [],
                },
                STATION_ACCESS_KIND: {
                    "count": len(drives),
                    "length3d": sum(d.length3d for d in drives),
                    "nominalExcavationVolume": sum(d.nominal_volume for d in drives),
                    "endpointPolicies": ["OPEN-OPEN"] if drives else [],
                },
            },
            "shafts": shafts_report,
        }


# --------------------------------------------------------------------------- #
# 5. Batched render — one tube primitive per kind + two cap primitives
# --------------------------------------------------------------------------- #


def _piece_range(
    development_id: str, level_id: str, prim: RenderPrimitive, cursor: int, count: int
) -> dict[str, Any]:
    return {
        "developmentId": development_id,
        "pieceId": prim.extras.get("segmentId"),
        "levelId": level_id,
        "indexOffset": cursor,
        "indexCount": count,
        "indexStride": prim.extras["indexStride"],
        "nominalIndexStride": prim.extras.get("nominalIndexStride", prim.extras["indexStride"]),
        "ringIntervalCount": prim.extras["ringIntervalCount"],
        "ringChainageFractions": prim.extras["ringChainageFractions"],
        "ringIntervalIndexOffsets": prim.extras["ringIntervalIndexOffsets"],
        "omittedTriangles": prim.extras["omittedTriangles"],
        "clippedQuads": prim.extras.get("clippedQuads", 0),
        "replacementTriangles": prim.extras.get("replacementTriangles", 0),
    }


def batch_shaft_render(barrels: list[_SweptBarrel], drives: list[_SweptDrive]) -> RenderMesh:
    """One vertex buffer; ``SHAFT`` tube primitive (ranges = axis segments of
    every barrel), ``SHAFT_STATION_ACCESS`` tube primitive (ranges = drives),
    ``SHAFT_COLLAR_CAP`` (every barrel's portal-side cap) and ``SHAFT_SUMP_CAP``
    (every barrel's terminal cap). Same ``ranges`` grammar as the development
    mesh so ONE frontend reader serves both GLBs."""
    positions: list[npt.NDArray[np.float32]] = []
    normals: list[npt.NDArray[np.float32]] = []
    uvs: list[npt.NDArray[np.float32]] = []
    tube_idx: dict[str, list[npt.NDArray[np.uint32]]] = {k: [] for k in SHAFT_MESH_KINDS}
    ranges: dict[str, list[dict[str, Any]]] = {k: [] for k in SHAFT_MESH_KINDS}
    collar_idx: list[npt.NDArray[np.uint32]] = []
    sump_idx: list[npt.NDArray[np.uint32]] = []
    offset = 0

    def consume(
        kind: str, development_id: str, level_id: str, render: RenderMesh, caps: bool
    ) -> None:
        nonlocal offset
        positions.append(render.positions)
        normals.append(render.normals)
        uvs.append(render.uvs)
        cursor = sum(int(x.shape[0]) for x in tube_idx[kind])
        for prim in render.primitives:
            idx = (prim.indices.astype(np.uint32) + np.uint32(offset)).astype(np.uint32)
            role = prim.extras.get("role")
            if role == "SEGMENT":
                ranges[kind].append(
                    _piece_range(development_id, level_id, prim, cursor, int(idx.shape[0]))
                )
                tube_idx[kind].append(idx)
                cursor += int(idx.shape[0])
            elif role == "PORTAL_CAP" and caps:
                collar_idx.append(idx)
            elif role == "TERMINAL_CAP" and caps:
                sump_idx.append(idx)
        offset += int(render.positions.shape[0])

    for b in barrels:
        consume(SHAFT_KIND, b.spec.development_id, b.spec.development_id, b.render, True)
    for d in drives:
        consume(STATION_ACCESS_KIND, d.spec.development_id, d.spec.level_id, d.render, False)
    prims: list[RenderPrimitive] = []
    for kind in SHAFT_MESH_KINDS:
        if tube_idx[kind]:
            prims.append(
                RenderPrimitive(
                    name=kind,
                    extras={"role": "DEVELOPMENT", "kind": kind, "ranges": ranges[kind]},
                    indices=np.concatenate(tube_idx[kind]),
                )
            )
    if collar_idx:
        prims.append(
            RenderPrimitive(
                name=COLLAR_CAP_ROLE,
                extras={"role": COLLAR_CAP_ROLE, "kind": SHAFT_KIND},
                indices=np.concatenate(collar_idx),
            )
        )
    if sump_idx:
        prims.append(
            RenderPrimitive(
                name=SUMP_CAP_ROLE,
                extras={"role": SUMP_CAP_ROLE, "kind": SHAFT_KIND},
                indices=np.concatenate(sump_idx),
            )
        )
    all_pos = np.vstack(positions) if positions else np.zeros((0, 3), dtype=np.float32)
    return RenderMesh(
        positions=all_pos,
        normals=np.vstack(normals) if normals else np.zeros((0, 3), dtype=np.float32),
        uvs=np.vstack(uvs) if uvs else np.zeros((0, 2), dtype=np.float32),
        primitives=prims,
        geometrically_closed=False,
        render_vertex_count=int(all_pos.shape[0]),
        base_sweep_geometrically_closed=False,
    )
