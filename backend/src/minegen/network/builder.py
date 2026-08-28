"""Phase 07 — MineNetwork builder (rules 13, 68–70).

The MineNetwork is derived from the Phase 05 EFFECTIVE centerline — never
from the mesh — and is a sibling derivation next to the Phase 06 tunnel mesh
(rule 68). Edges store a geometry REFERENCE plus scalar attributes only; the
polyline lives solely in the smoothed artifact.

``networkx.MultiDiGraph`` is the in-memory topology/metric engine only: the
persisted/API contract is the typed ``NetworkPayload`` built here, never a
raw NetworkX serialization. Edge direction is the canonical centerline
orientation (portal → deeper) and does NOT imply one-way physical travel;
connectivity and surface-path redundancy are evaluated on the undirected
physical projection (rule 69). The surface-path advisory reports edge-disjoint
path counts without any statutory or regulatory compliance claim (rule 70).

A FAILED prerequisite artifact is never consumable: it may contain
already-completed partial geometry, and a partial network built from an
invalid prerequisite would silently launder that failure. Only SUCCESS and
SUCCESS_WITH_FALLBACK smoothing artifacts (and a SUCCESS levels artifact)
yield a network.

Phase 08 (rule 73): the network is REBUILT deterministically from the
Phase 05 RAMP centerlines plus the Phase 08 level-development centerlines —
never patched from a stale network artifact. DRIFT edges are split at every
graph node; a crosscut station coincident with a LEVEL_ENTRY reuses that
node; crosscut terminals are STOPE_ACCESS anchors for Phase 09 (they do not
imply an existing stope). Surface-path redundancy covers EVERY underground
physical node.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import networkx as nx
import numpy as np
import numpy.typing as npt

from minegen.core.models import Scenario
from minegen.design.profile import build_profile
from minegen.network.models import (
    CrossSection,
    EdgeType,
    GeometryRef,
    NetworkEdge,
    NetworkMetrics,
    NetworkNode,
    NetworkPayload,
    NetworkValidation,
    NodeType,
    SimulationSlots,
    SurfacePathAdvisory,
    SurfacePathEntry,
)

FloatArray = npt.NDArray[np.float64]

SYNC_TOLERANCE = 1e-6  # m — node/edge vs centerline synchronization gate
REQUIRED_SURFACE_PATHS = 2  # advisory criterion only (rule 70)
ADVISORY_CRITERION = "TWO_EDGE_DISJOINT_SURFACE_PATHS"
GEOMETRY_ARTIFACT = "decline_smoothed.json"
LEVELS_ARTIFACT = "levels.json"
STATION_MERGE_TOLERANCE = 1e-6  # m — co-located LEVEL_ENTRY/JUNCTION reuse
CONSUMABLE_SMOOTHED_STATUSES = ("SUCCESS", "SUCCESS_WITH_FALLBACK")


@dataclass(frozen=True)
class NetworkBuildResult:
    graph: nx.MultiDiGraph[str]
    payload: NetworkPayload

    @property
    def success(self) -> bool:
        return self.payload.status == "SUCCESS"


def _failed(source_revision: str, reason: str) -> NetworkBuildResult:
    """Structured failure: zero physical nodes/edges, no metrics/validation."""
    return NetworkBuildResult(
        nx.MultiDiGraph(),
        NetworkPayload(
            status="FAILED",
            failure_reason=reason,
            source_revision=source_revision,
            nodes=[],
            edges=[],
            metrics=None,
            validation=None,
            surface_path_advisory=[],
        ),
    )


def _polyline_metrics(points: FloatArray) -> tuple[float, float, float]:
    """(length3d, meanGradientSigned, maxAbsGradient) of a centerline.

    meanGradientSigned = total Δz / total horizontal length in the canonical
    (portal → deeper) direction — negative means descending. maxAbsGradient =
    max |local Δz/Δh| over polyline steps, always ≥ 0."""
    d = np.diff(points, axis=0)
    seg3d = np.linalg.norm(d, axis=1)
    dh = np.linalg.norm(d[:, :2], axis=1)
    dz = d[:, 2]
    length_3d = float(seg3d.sum())
    total_h = float(dh.sum())
    if total_h <= 0.0:
        raise ValueError("degenerate centerline: zero horizontal length")
    mean_signed = float(dz.sum()) / total_h
    mask = dh > 1e-9
    max_abs = float(np.max(np.abs(dz[mask] / dh[mask]))) if bool(mask.any()) else 0.0
    return length_3d, mean_signed, max_abs


def _surface_path_counts(
    graph: nx.MultiDiGraph[str], portal_ids: list[str], targets: list[str]
) -> dict[str, int]:
    """Edge-disjoint physical path count from each target node to ANY
    PORTAL-type surface node, on the UNDIRECTED projection (rule 69).
    Parallel physical edges legitimately count as parallel capacity, so the
    multigraph collapses to a capacity graph and the count is a max-flow."""
    cap: nx.Graph[str] = nx.Graph()
    cap.add_nodes_from(graph.nodes())
    for u, v in graph.edges():  # undirected capacity accumulation
        if cap.has_edge(u, v):
            cap[u][v]["capacity"] += 1
        else:
            cap.add_edge(u, v, capacity=1)
    super_surface = "__SURFACE__"
    cap.add_node(super_surface)
    for pid in portal_ids:
        cap.add_edge(super_surface, pid, capacity=len(graph.edges()) + 1)
    out: dict[str, int] = {}
    for node in targets:
        if not nx.has_path(cap, node, super_surface):
            out[node] = 0
            continue
        flow, _ = nx.maximum_flow(cap, node, super_surface, capacity="capacity")
        out[node] = int(flow)
    return out


class MineNetworkBuilder:
    """Builds the MineNetwork from its owning centerline artifacts: the
    Phase 05 RAMP centerlines plus (when provided) the Phase 08
    level-development centerlines (rule 73).

    Nodes carry deterministic namespaced IDs (``PORTAL``,
    ``LEVEL_ENTRY:L01``, ``JUNCTION:L01:S+03``, ``STOPE_ACCESS:L01:S+03``).
    Coordinates come from the artifact centerline endpoints — Phase 05
    endpoint preservation makes the ramp arrival the exact selected access
    target, keeping rule 13 clean (never re-read from targets.json). Edge
    scalars are always RECOMPUTED from the owning centerline; declared
    development scalars are cross-checked, never trusted."""

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        self._shape = build_profile(scenario.ramp, scenario.tunnel_profile)

    def build(
        self,
        smoothed_payload: dict[str, Any],
        source_revision: str,
        levels_payload: dict[str, Any] | None = None,
    ) -> NetworkBuildResult:
        # prerequisite gates: FAILED artifacts may contain already-completed
        # partial geometry — they never yield a network (rules 68/74)
        smoothed_status = smoothed_payload.get("status")
        if smoothed_status not in CONSUMABLE_SMOOTHED_STATUSES:
            return _failed(
                source_revision,
                f"prerequisite smoothed artifact status {smoothed_status!r} is not "
                f"consumable (rule 68): only {', '.join(CONSUMABLE_SMOOTHED_STATUSES)} "
                "yield a MineNetwork; partial segments of a FAILED artifact are ignored",
            )
        if levels_payload is not None and levels_payload.get("status") != "SUCCESS":
            return _failed(
                source_revision,
                "prerequisite levels artifact status "
                f"{levels_payload.get('status')!r} is not consumable (rule 74)",
            )

        segments = smoothed_payload["segments"]
        if not segments:
            return _failed(source_revision, "smoothed artifact has no effective segments")

        polylines: list[FloatArray] = [
            np.asarray(seg["effectiveCenterline"]["points"], dtype=np.float64).reshape(-1, 3)
            for seg in segments
        ]

        graph: nx.MultiDiGraph[str] = nx.MultiDiGraph()
        nodes: list[NetworkNode] = []
        edges: list[NetworkEdge] = []
        failure: str | None = None

        # -- nodes: PORTAL + LEVEL_ENTRY per completed level ---------------- #
        portal_pos = polylines[0][0]
        portal = NetworkNode(
            id="PORTAL",
            type=NodeType.PORTAL,
            position=(float(portal_pos[0]), float(portal_pos[1]), float(portal_pos[2])),
        )
        nodes.append(portal)
        graph.add_node(portal.id, **portal.model_dump(mode="json", by_alias=True))

        cross_section = CrossSection(
            width=self.scenario.ramp.tunnel_width,
            height=self.scenario.ramp.tunnel_height,
            analytic_area=self._shape.analytic_area,
        )

        max_weld = 0.0
        prev_node = portal.id
        prev_end = portal_pos
        for idx, (seg, pts) in enumerate(zip(segments, polylines, strict=True)):
            level_id = seg["levelId"]
            end = pts[-1]
            # rule 68 synchronization: this segment must start where the chain
            # currently ends (weld across consecutive effective centerlines)
            weld = float(np.linalg.norm(pts[0] - prev_end))
            max_weld = max(max_weld, weld)
            node = NetworkNode(
                id=f"{NodeType.LEVEL_ENTRY.value}:{level_id}",
                type=NodeType.LEVEL_ENTRY,
                position=(float(end[0]), float(end[1]), float(end[2])),
                level_id=level_id,
                candidate_id=seg["candidateId"],
                elevation=float(end[2]),
            )
            nodes.append(node)
            graph.add_node(node.id, **node.model_dump(mode="json", by_alias=True))

            length_3d, mean_signed, max_abs = _polyline_metrics(pts)
            report = seg["report"]
            source = seg["effectiveSource"]
            field_cost = (
                report["fieldCostSmoothed"] if source == "SMOOTHED" else report["fieldCostRaw"]
            )
            edge = NetworkEdge(
                id=f"{EdgeType.RAMP.value}:{level_id}",
                type=EdgeType.RAMP,
                from_node=prev_node,
                to_node=node.id,
                length3d=length_3d,
                mean_gradient_signed=mean_signed,
                max_abs_gradient=max_abs,
                cross_section=cross_section,
                effective_source=source,
                field_cost=float(field_cost),
                geometry_ref=GeometryRef(artifact=GEOMETRY_ARTIFACT, segment_index=idx),
                simulation=SimulationSlots(),
            )
            edges.append(edge)
            graph.add_edge(
                prev_node, node.id, key=edge.id, **edge.model_dump(mode="json", by_alias=True)
            )
            prev_node = node.id
            prev_end = end

        # -- Phase 08 level developments (rule 73) --------------------------- #
        if levels_payload is not None:
            entry_by_level = {n.level_id: n for n in nodes if n.type is NodeType.LEVEL_ENTRY}
            developments = levels_payload["developments"]
            # station index lookup per level (crosscuts carry u AND k), so
            # JUNCTION ids are station-index based — stable under any pitch
            station_index: dict[tuple[str, float], int] = {
                (d["levelId"], float(d["stationU"])): int(d["stationIndex"])
                for d in developments
                if d["kind"] == "CROSSCUT"
            }
            # per level: register a node for every breakpoint u (stations +
            # entry); a station within tolerance of the LEVEL_ENTRY reuses it
            node_by_key: dict[tuple[str, float], NetworkNode] = {}
            max_edge_len_err = 0.0

            def dev_pts(dev: dict[str, Any]) -> FloatArray:
                return np.asarray(dev["centerline"]["points"], dtype=np.float64).reshape(-1, 3)

            def breakpoint_node(level_id: str, u: float, pos: FloatArray) -> NetworkNode:
                nonlocal max_weld
                entry = entry_by_level[level_id]
                entry_weld = float(np.linalg.norm(np.asarray(entry.position) - pos))
                if entry_weld <= STATION_MERGE_TOLERANCE:
                    max_weld = max(max_weld, entry_weld)
                    return entry  # coincident station reuses LEVEL_ENTRY (rule 73)
                for (lvl, uu), existing in node_by_key.items():
                    if lvl == level_id and abs(uu - u) <= STATION_MERGE_TOLERANCE:
                        max_weld = max(
                            max_weld,
                            float(np.linalg.norm(np.asarray(existing.position) - pos)),
                        )
                        return existing
                k: int | None = None
                for (lvl, su), idx_k in station_index.items():
                    if lvl == level_id and abs(su - u) <= STATION_MERGE_TOLERANCE:
                        k = idx_k
                        break
                node_id = (
                    f"{NodeType.JUNCTION.value}:{level_id}:S{k:+03d}"
                    if k is not None
                    else f"{NodeType.JUNCTION.value}:{level_id}:U{u:+08.1f}"
                )
                node = NetworkNode(
                    id=node_id,
                    type=NodeType.JUNCTION,
                    position=(float(pos[0]), float(pos[1]), float(pos[2])),
                    level_id=level_id,
                    elevation=float(pos[2]),
                    station_index=k,
                    station_u=u,
                )
                node_by_key[(level_id, u)] = node
                nodes.append(node)
                graph.add_node(node.id, **node.model_dump(mode="json", by_alias=True))
                return node

            for idx, dev in enumerate(developments):
                pts = dev_pts(dev)
                level_id = dev["levelId"]
                # rule 13 (blocker 2): edge scalars are RECOMPUTED from the
                # owning centerline; the declared development scalar is only
                # cross-checked, never trusted
                length_3d, mean_signed, max_abs = _polyline_metrics(pts)
                max_edge_len_err = max(max_edge_len_err, abs(length_3d - float(dev["length3d"])))
                if dev["kind"] == "DRIFT":
                    a = breakpoint_node(level_id, float(dev["fromU"]), pts[0])
                    b = breakpoint_node(level_id, float(dev["toU"]), pts[-1])
                    edge = NetworkEdge(
                        id=dev["id"],
                        type=EdgeType.DRIFT,
                        from_node=a.id,
                        to_node=b.id,
                        length3d=length_3d,
                        mean_gradient_signed=mean_signed,
                        max_abs_gradient=max_abs,
                        cross_section=cross_section,
                        effective_source="ANALYTIC",
                        field_cost=float(dev["report"]["fieldCost"]),
                        geometry_ref=GeometryRef(artifact=LEVELS_ARTIFACT, segment_index=idx),
                        simulation=SimulationSlots(),
                    )
                else:  # CROSSCUT
                    a = breakpoint_node(level_id, float(dev["stationU"]), pts[0])
                    weld = float(np.linalg.norm(np.asarray(a.position) - pts[0]))
                    max_weld = max(max_weld, weld)
                    k = int(dev["stationIndex"])
                    terminal = NetworkNode(
                        id=f"{NodeType.STOPE_ACCESS.value}:{level_id}:S{k:+03d}",
                        type=NodeType.STOPE_ACCESS,
                        position=(float(pts[-1][0]), float(pts[-1][1]), float(pts[-1][2])),
                        level_id=level_id,
                        elevation=float(pts[-1][2]),
                        station_index=k,
                        station_u=float(dev["stationU"]),
                    )
                    nodes.append(terminal)
                    graph.add_node(terminal.id, **terminal.model_dump(mode="json", by_alias=True))
                    edge = NetworkEdge(
                        id=dev["id"],
                        type=EdgeType.CROSSCUT,
                        from_node=a.id,
                        to_node=terminal.id,
                        length3d=length_3d,
                        mean_gradient_signed=mean_signed,
                        max_abs_gradient=max_abs,
                        cross_section=cross_section,
                        effective_source="ANALYTIC",
                        field_cost=float(dev["report"]["fieldCost"]),
                        geometry_ref=GeometryRef(artifact=LEVELS_ARTIFACT, segment_index=idx),
                        simulation=SimulationSlots(),
                    )
                edges.append(edge)
                graph.add_edge(
                    edge.from_node,
                    edge.to_node,
                    key=edge.id,
                    **edge.model_dump(mode="json", by_alias=True),
                )

        # -- validation on the undirected physical projection (rule 69) ----- #
        undirected = graph.to_undirected(as_view=True)
        components = nx.number_connected_components(undirected)
        connected = components == 1
        edge_len_err = max_edge_len_err if levels_payload is not None else 0.0
        validation = NetworkValidation(
            max_node_sync_error=max_weld,
            max_edge_length_sync_error=edge_len_err,
            sync_tolerance=SYNC_TOLERANCE,
            synchronized=max_weld <= SYNC_TOLERANCE and edge_len_err <= SYNC_TOLERANCE,
            connected=connected,
            connected_components=components,
        )
        if max_weld > SYNC_TOLERANCE:
            failure = (
                f"centerline weld error {max_weld:.3e} m exceeds {SYNC_TOLERANCE:.0e} (rule 68)"
            )
        elif edge_len_err > SYNC_TOLERANCE:
            failure = (
                f"declared development length diverges from its owning centerline by "
                f"{edge_len_err:.3e} m (> {SYNC_TOLERANCE:.0e}, rule 13)"
            )
        elif not connected:
            failure = f"network is not a single physical component ({components})"

        # -- surface-path redundancy advisory (rule 70, no legal claim) ----- #
        # rule 73: the advisory covers EVERY underground physical node, not
        # only level entries (JUNCTION and STOPE_ACCESS included)
        underground = [n for n in nodes if n.type is not NodeType.PORTAL]
        counts = _surface_path_counts(graph, [portal.id], [n.id for n in underground])
        advisory = SurfacePathAdvisory(
            criterion=ADVISORY_CRITERION,
            required_paths=REQUIRED_SURFACE_PATHS,
            advisory_only=True,
            per_node=[
                SurfacePathEntry(
                    node_id=n.id,
                    level_id=n.level_id or "",
                    independent_surface_paths=counts[n.id],
                    meets_criterion=counts[n.id] >= REQUIRED_SURFACE_PATHS,
                )
                for n in underground
            ],
        )

        elevations = [n.position[2] for n in nodes]
        ramp_edges = [e for e in edges if e.type is EdgeType.RAMP]
        drift_edges = [e for e in edges if e.type is EdgeType.DRIFT]
        crosscut_edges = [e for e in edges if e.type is EdgeType.CROSSCUT]
        metrics = NetworkMetrics(
            node_count=len(nodes),
            edge_count=len(edges),
            level_count=sum(1 for n in nodes if n.type is NodeType.LEVEL_ENTRY),
            junction_count=sum(1 for n in nodes if n.type is NodeType.JUNCTION),
            stope_access_count=sum(1 for n in nodes if n.type is NodeType.STOPE_ACCESS),
            drift_edge_count=len(drift_edges),
            crosscut_edge_count=len(crosscut_edges),
            total_ramp_length3d=float(math.fsum(e.length3d for e in ramp_edges)),
            total_drift_length3d=float(math.fsum(e.length3d for e in drift_edges)),
            total_crosscut_length3d=float(math.fsum(e.length3d for e in crosscut_edges)),
            minimum_elevation=float(min(elevations)),
            vertical_drop_from_portal=float(portal.position[2] - min(elevations)),
        )
        payload = NetworkPayload(
            status="SUCCESS" if failure is None else "FAILED",
            failure_reason=failure,
            source_revision=source_revision,
            nodes=nodes,
            edges=edges,
            metrics=metrics,
            validation=validation,
            surface_path_advisory=[advisory],
        )
        return NetworkBuildResult(graph, payload)
