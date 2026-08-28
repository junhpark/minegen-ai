"""Phase 07 — MineNetwork builder (rules 13, 68–70).

The MineNetwork is derived from the Phase 05 EFFECTIVE centerline — never
from the mesh — and is a sibling derivation next to the Phase 06 tunnel mesh
(rule 68). Edges store a geometry REFERENCE plus scalar attributes only; the
polyline lives solely in the smoothed artifact.

``networkx.MultiDiGraph`` is the in-memory topology/metric engine only: the
persisted/API contract is the typed deterministic payload built here, never a
raw NetworkX serialization. Edge direction is the canonical centerline
orientation (portal → deeper) and does NOT imply one-way physical travel;
connectivity and surface-path redundancy are evaluated on the undirected
physical projection (rule 69). The surface-path advisory reports edge-disjoint
path counts without any statutory or regulatory compliance claim (rule 70).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import networkx as nx
import numpy as np
import numpy.typing as npt

from minegen.core.models import Scenario
from minegen.design.profile import build_profile

FloatArray = npt.NDArray[np.float64]

SYNC_TOLERANCE = 1e-6  # m — node/edge vs centerline synchronization gate
REQUIRED_SURFACE_PATHS = 2  # advisory criterion only (rule 70)
ADVISORY_CRITERION = "TWO_EDGE_DISJOINT_SURFACE_PATHS"
GEOMETRY_ARTIFACT = "decline_smoothed.json"


class NodeType(StrEnum):
    PORTAL = "PORTAL"
    LEVEL_ENTRY = "LEVEL_ENTRY"
    JUNCTION = "JUNCTION"  # reserved (Phase 08+)
    STOPE_ACCESS = "STOPE_ACCESS"  # reserved (Phase 09+)


class EdgeType(StrEnum):
    RAMP = "RAMP"
    DRIFT = "DRIFT"  # reserved (Phase 08+)
    CROSSCUT = "CROSSCUT"  # reserved (Phase 08+)
    RAISE = "RAISE"  # reserved
    SHAFT = "SHAFT"  # reserved


# typed reserved simulation attributes (rule 68 / architecture §4); models
# fill these in later phases — reserved keys, not an open-ended dict
RESERVED_SIMULATION: dict[str, None] = {
    "haulage": None,
    "ventilation": None,
    "communication": None,
    "rockRisk": None,
}


@dataclass(frozen=True)
class NetworkBuildResult:
    graph: nx.MultiDiGraph[str]
    payload: dict[str, Any]

    @property
    def success(self) -> bool:
        return bool(self.payload["status"] == "SUCCESS")


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
    """Builds the Phase 07 RAMP subgraph from the smoothed decline payload.

    Nodes: one PORTAL plus one LEVEL_ENTRY per completed level, with
    deterministic namespaced IDs (``PORTAL``, ``LEVEL_ENTRY:L01``, …).
    Coordinates come from the effective centerline endpoints — Phase 05
    endpoint preservation makes the last point the exact selected access
    target, keeping rule 13 clean (never re-read from targets.json)."""

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        self._shape = build_profile(scenario.ramp, scenario.tunnel_profile)

    def build(self, smoothed_payload: dict[str, Any], source_revision: str) -> NetworkBuildResult:
        segments = smoothed_payload["segments"]
        graph: nx.MultiDiGraph[str] = nx.MultiDiGraph()
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        failure: str | None = None

        polylines: list[FloatArray] = [
            np.asarray(seg["effectiveCenterline"]["points"], dtype=np.float64).reshape(-1, 3)
            for seg in segments
        ]
        if not polylines:
            return NetworkBuildResult(
                graph,
                self._payload(
                    "FAILED", source_revision, [], [], {}, {}, [], "no effective segments"
                ),
            )

        # -- nodes: PORTAL + LEVEL_ENTRY per completed level ---------------- #
        portal_pos = polylines[0][0]
        portal_id = "PORTAL"
        nodes.append(
            {
                "id": portal_id,
                "type": NodeType.PORTAL.value,
                "position": [float(v) for v in portal_pos],
            }
        )
        graph.add_node(portal_id, **nodes[-1])

        max_weld = 0.0
        prev_node = portal_id
        prev_end = portal_pos
        for idx, (seg, pts) in enumerate(zip(segments, polylines, strict=True)):
            level_id = seg["levelId"]
            node_id = f"{NodeType.LEVEL_ENTRY.value}:{level_id}"
            end = pts[-1]
            # rule 68 synchronization: this segment must start where the chain
            # currently ends (weld across consecutive effective centerlines)
            weld = float(np.linalg.norm(pts[0] - prev_end))
            max_weld = max(max_weld, weld)
            node = {
                "id": node_id,
                "type": NodeType.LEVEL_ENTRY.value,
                "position": [float(v) for v in end],
                "levelId": level_id,
                "candidateId": seg["candidateId"],
                "elevation": float(end[2]),
            }
            nodes.append(node)
            graph.add_node(node_id, **node)

            length_3d, mean_signed, max_abs = _polyline_metrics(pts)
            report = seg["report"]
            source = seg["effectiveSource"]
            field_cost = (
                report["fieldCostSmoothed"] if source == "SMOOTHED" else report["fieldCostRaw"]
            )
            edge = {
                "id": f"{EdgeType.RAMP.value}:{level_id}",
                "type": EdgeType.RAMP.value,
                "fromNode": prev_node,
                "toNode": node_id,
                "length3d": length_3d,
                "meanGradientSigned": mean_signed,
                "maxAbsGradient": max_abs,
                "crossSection": {
                    "width": self.scenario.ramp.tunnel_width,
                    "height": self.scenario.ramp.tunnel_height,
                    "analyticArea": self._shape.analytic_area,
                },
                "effectiveSource": source,
                "fieldCost": float(field_cost),
                "geometryRef": {"artifact": GEOMETRY_ARTIFACT, "segmentIndex": idx},
                "simulation": dict(RESERVED_SIMULATION),
            }
            edges.append(edge)
            graph.add_edge(prev_node, node_id, key=edge["id"], **edge)
            prev_node = node_id
            prev_end = end

        # -- validation on the undirected physical projection (rule 69) ----- #
        undirected = graph.to_undirected(as_view=True)
        components = nx.number_connected_components(undirected)
        connected = components == 1
        validation = {
            "maxNodeSyncError": max_weld,
            "syncTolerance": SYNC_TOLERANCE,
            "synchronized": max_weld <= SYNC_TOLERANCE,
            "connected": connected,
            "connectedComponents": components,
        }
        if not validation["synchronized"]:
            failure = (
                f"centerline weld error {max_weld:.3e} m exceeds {SYNC_TOLERANCE:.0e} (rule 68)"
            )
        elif not connected:
            failure = f"network is not a single physical component ({components})"

        # -- surface-path redundancy advisory (rule 70, no legal claim) ----- #
        level_ids = [n["id"] for n in nodes if n["type"] == NodeType.LEVEL_ENTRY.value]
        counts = _surface_path_counts(graph, [portal_id], level_ids)
        advisory = {
            "criterion": ADVISORY_CRITERION,
            "requiredPaths": REQUIRED_SURFACE_PATHS,
            "advisoryOnly": True,
            "perNode": [
                {
                    "nodeId": nid,
                    "levelId": graph.nodes[nid]["levelId"],
                    "independentSurfacePaths": counts[nid],
                    "meetsCriterion": counts[nid] >= REQUIRED_SURFACE_PATHS,
                }
                for nid in level_ids
            ],
        }

        lengths = [e["length3d"] for e in edges]
        elevations = [n["position"][2] for n in nodes]
        metrics = {
            "nodeCount": len(nodes),
            "edgeCount": len(edges),
            "levelCount": len(level_ids),
            "totalRampLength3d": float(math.fsum(lengths)),
            "minimumElevation": float(min(elevations)),
            "verticalDropFromPortal": float(portal_pos[2] - min(elevations)),
        }
        status = "SUCCESS" if failure is None else "FAILED"
        return NetworkBuildResult(
            graph,
            self._payload(
                status, source_revision, nodes, edges, metrics, validation, [advisory], failure
            ),
        )

    @staticmethod
    def _payload(
        status: str,
        source_revision: str,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        metrics: dict[str, Any],
        validation: dict[str, Any],
        advisories: list[dict[str, Any]],
        failure: str | None,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "failureReason": failure,
            "sourceRevision": source_revision,
            "nodes": nodes,
            "edges": edges,
            "metrics": metrics,
            "validation": validation,
            "surfacePathAdvisory": advisories,
        }
