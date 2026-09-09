"""Phase 20C.2B — capability graph builder + path queries (rule 185).

The builder assigns a typed capability set to every MineNetwork edge from
EXPLICIT sources only: the declared (or module-default) set per physical
edge type, or the owning shaft's declared set for SHAFT /
SHAFT_STATION_ACCESS edges. Node ``supports`` are derived from incident
edges. It then validates references / duplicates / revision synchronization,
evaluates the required capability paths and reports the EMERGENCY_EGRESS
redundancy advisory (edge-disjoint routes to any surface node on the
capability-filtered subgraph).

Capability ≠ capacity: everything here is a may / may-not tag. Queries are
deterministic BFS (neighbours in edge-id order) on the UNDIRECTED physical
projection (rule 69), filtered to edges carrying the capability.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

import networkx as nx

from minegen.capability.models import (
    CapabilityEdge,
    CapabilityGraphPayload,
    CapabilityMetrics,
    CapabilityNode,
    CapabilityPathQuery,
    CapabilitySource,
    CapabilityValidation,
    EgressAdvisory,
    EgressAdvisoryEntry,
    RequiredPathCheck,
)
from minegen.core.artifacts import SHAFTS_ARTIFACT
from minegen.core.enums import Capability, EdgeType, NodeType
from minegen.core.models import EDGE_TYPE_DEFAULT_CAPABILITIES, Scenario

SURFACE_NODE_TYPES = (NodeType.PORTAL, NodeType.SHAFT_COLLAR)
EGRESS_CRITERION = "TWO_EDGE_DISJOINT_EGRESS_ROUTES"
EGRESS_REQUIRED_ROUTES = 2  # advisory criterion only (rule 70 analogue)
SHAFT_EDGE_TYPES = (EdgeType.SHAFT, EdgeType.SHAFT_STATION_ACCESS)


def _failed(
    source_revision: str,
    network_revision: str,
    network_source_revision: str,
    reason: str,
    t0: float,
) -> CapabilityGraphPayload:
    return CapabilityGraphPayload(
        status="FAILED",
        failure_reason=reason,
        source_revision=source_revision,
        network_revision=network_revision,
        network_source_revision=network_source_revision,
        capabilities=list(Capability),
        nodes=[],
        edges=[],
        surface_node_ids=[],
        required_paths=[],
        egress_advisory=None,
        validation=None,
        metrics=CapabilityMetrics(
            node_count=0,
            edge_count=0,
            surface_node_count=0,
            edges_per_capability={},
            required_path_count=0,
            required_paths_satisfied_count=0,
            build_seconds=time.perf_counter() - t0,
        ),
    )


# --------------------------------------------------------------------------- #
# graph queries
# --------------------------------------------------------------------------- #


class CapabilityQueryGraph:
    """Undirected adjacency over a capability-graph payload (or the raw
    edge list) for deterministic reachability queries."""

    def __init__(
        self,
        node_ids: list[str],
        edges: list[tuple[str, str, str, frozenset[Capability]]],
    ) -> None:
        self.node_ids = set(node_ids)
        # node → [(neighbour, edge id, capabilities)] sorted by edge id
        self.adj: dict[str, list[tuple[str, str, frozenset[Capability]]]] = {
            n: [] for n in node_ids
        }
        for eid, a, b, caps in sorted(edges, key=lambda t: t[0]):
            self.adj[a].append((b, eid, caps))
            self.adj[b].append((a, eid, caps))
        for lst in self.adj.values():
            lst.sort(key=lambda t: (t[1], t[0]))

    def bfs(
        self, source: str, target: str, capability: Capability | None
    ) -> tuple[list[str], list[str]] | None:
        """Shortest (fewest edges) path source → target using only edges
        carrying ``capability`` (``None`` = physical). Deterministic:
        neighbours are visited in (edge id, node id) order."""
        if source not in self.node_ids or target not in self.node_ids:
            return None
        if source == target:
            return [source], []
        prev: dict[str, tuple[str, str]] = {}
        seen = {source}
        queue: deque[str] = deque([source])
        while queue:
            u = queue.popleft()
            for v, eid, caps in self.adj[u]:
                if capability is not None and capability not in caps:
                    continue
                if v in seen:
                    continue
                seen.add(v)
                prev[v] = (u, eid)
                if v == target:
                    nodes = [v]
                    edges: list[str] = []
                    cur = v
                    while cur != source:
                        p, e = prev[cur]
                        edges.append(e)
                        nodes.append(p)
                        cur = p
                    return nodes[::-1], edges[::-1]
                queue.append(v)
        return None


def _query_graph(
    nodes: list[CapabilityNode], edges: list[CapabilityEdge], endpoints: dict[str, tuple[str, str]]
) -> CapabilityQueryGraph:
    return CapabilityQueryGraph(
        [n.node_id for n in nodes],
        [(e.edge_id, *endpoints[e.edge_id], frozenset(e.capabilities)) for e in edges],
    )


def query_graph_from(
    network_payload: dict[str, Any], capability_payload: dict[str, Any]
) -> CapabilityQueryGraph:
    """Query graph for a persisted (network, capability) pair: the capability
    artifact references network edge ids; endpoints come from the network."""
    endpoints = {e["id"]: (str(e["fromNode"]), str(e["toNode"])) for e in network_payload["edges"]}
    edges: list[tuple[str, str, str, frozenset[Capability]]] = []
    for ce in capability_payload["edges"]:
        a, b = endpoints[ce["edgeId"]]
        edges.append((ce["edgeId"], a, b, frozenset(Capability(c) for c in ce["capabilities"])))
    return CapabilityQueryGraph([n["nodeId"] for n in capability_payload["nodes"]], edges)


def can_reach(
    graph: CapabilityQueryGraph, source: str, target: str, capability: Capability
) -> CapabilityPathQuery:
    physical = graph.bfs(source, target, None)
    cap_path = graph.bfs(source, target, capability)
    return CapabilityPathQuery(
        source_node_id=source,
        target_node_id=target,
        capability=capability,
        physical_reachable=physical is not None,
        capability_reachable=cap_path is not None,
        path_node_ids=cap_path[0] if cap_path else [],
        path_edge_ids=cap_path[1] if cap_path else [],
    )


def _egress_route_counts(
    nodes: list[CapabilityNode],
    edges: list[CapabilityEdge],
    endpoints: dict[str, tuple[str, str]],
    surface_ids: list[str],
) -> dict[str, int]:
    """Edge-disjoint EMERGENCY_EGRESS routes to ANY surface node (max-flow
    on the capability-filtered undirected capacity graph)."""
    cap: nx.Graph[str] = nx.Graph()
    cap.add_nodes_from(n.node_id for n in nodes)
    for e in edges:
        if Capability.EMERGENCY_EGRESS not in e.capabilities:
            continue
        a, b = endpoints[e.edge_id]
        if cap.has_edge(a, b):
            cap[a][b]["capacity"] += 1
        else:
            cap.add_edge(a, b, capacity=1)
    super_surface = "__SURFACE__"
    cap.add_node(super_surface)
    for sid in surface_ids:
        cap.add_edge(super_surface, sid, capacity=len(edges) + 1)
    out: dict[str, int] = {}
    for n in nodes:
        if n.surface:
            continue
        if not nx.has_path(cap, n.node_id, super_surface):
            out[n.node_id] = 0
            continue
        flow, _ = nx.maximum_flow(cap, n.node_id, super_surface, capacity="capacity")
        out[n.node_id] = int(flow)
    return out


# --------------------------------------------------------------------------- #
# builder
# --------------------------------------------------------------------------- #


class CapabilityGraphBuilder:
    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario

    def _edge_type_capabilities(self, etype: EdgeType) -> tuple[list[Capability], CapabilitySource]:
        declared = self.scenario.capability.edge_type_capabilities
        if declared is not None and etype in declared:
            return list(declared[etype]), CapabilitySource.EDGE_TYPE_DECLARED
        default = EDGE_TYPE_DEFAULT_CAPABILITIES.get(etype)
        if default is None:
            raise KeyError(etype.value)
        return list(default), CapabilitySource.EDGE_TYPE_DEFAULT

    def build(
        self,
        network_payload: dict[str, Any],
        shafts_payload: dict[str, Any] | None,
        source_revision: str,
        network_revision: str,
    ) -> CapabilityGraphPayload:
        t0 = time.perf_counter()
        net_src_rev = str(network_payload.get("sourceRevision") or "")

        def fail(reason: str) -> CapabilityGraphPayload:
            return _failed(source_revision, network_revision, net_src_rev, reason, t0)

        if network_payload.get("status") != "SUCCESS":
            return fail(
                f"prerequisite network artifact status {network_payload.get('status')!r} is "
                "not consumable — a capability graph never overlays partial topology"
            )
        node_list = network_payload.get("nodes") or []
        edge_list = network_payload.get("edges") or []
        node_ids = [str(n["id"]) for n in node_list]
        edge_ids = [str(e["id"]) for e in edge_list]
        dup_nodes = len(set(node_ids)) != len(node_ids)
        dup_edges = len(set(edge_ids)) != len(edge_ids)
        node_by_id = {str(n["id"]): n for n in node_list}
        missing_refs = [
            e["id"]
            for e in edge_list
            if e["fromNode"] not in node_by_id or e["toNode"] not in node_by_id
        ]
        if dup_nodes or dup_edges or missing_refs:
            return fail(
                "network integrity: "
                + ", ".join(
                    s
                    for s, flag in (
                        ("duplicate node ids", dup_nodes),
                        ("duplicate edge ids", dup_edges),
                        (f"edges with missing endpoints {missing_refs[:3]}", bool(missing_refs)),
                    )
                    if flag
                )
            )

        # -- shaft ownership lookup (declared capability per shaft) -------- #
        shaft_caps: dict[str, list[Capability]] = {}
        centerline_shaft: dict[int, str] = {}
        if shafts_payload is not None:
            for sh in shafts_payload.get("shafts", []):
                shaft_caps[str(sh["shaftId"])] = [Capability(c) for c in sh.get("capabilities", [])]
            for i, cl in enumerate(shafts_payload.get("centerlines", [])):
                centerline_shaft[i] = str(cl["shaftId"])

        # -- edge capability assignment (explicit sources only) ------------ #
        edges: list[CapabilityEdge] = []
        endpoints: dict[str, tuple[str, str]] = {}
        for e in edge_list:
            eid = str(e["id"])
            etype = EdgeType(e["type"])
            endpoints[eid] = (str(e["fromNode"]), str(e["toNode"]))
            shaft_id: str | None = None
            if etype in SHAFT_EDGE_TYPES:
                ref = e.get("geometryRef") or {}
                if ref.get("artifact") != SHAFTS_ARTIFACT or shafts_payload is None:
                    return fail(
                        f"edge {eid} of type {etype.value} needs the shaft artifact that owns "
                        "it to declare its capabilities (rule 185)"
                    )
                shaft_id = centerline_shaft.get(int(ref.get("segmentIndex", -1)))
                if shaft_id is None or shaft_id not in shaft_caps:
                    return fail(f"edge {eid}: geometryRef does not resolve to a shaft")
                caps, source = list(shaft_caps[shaft_id]), CapabilitySource.SHAFT_DECLARED
            else:
                try:
                    caps, source = self._edge_type_capabilities(etype)
                except KeyError:
                    return fail(
                        f"edge {eid}: no capability rule exists for edge type {etype.value} "
                        "(RAISE is reserved)"
                    )
            caps = [c for c in Capability if c in caps]  # canonical order
            edges.append(
                CapabilityEdge(
                    edge_id=eid,
                    edge_type=etype,
                    capabilities=caps,
                    restrictions=[c for c in Capability if c not in caps],
                    source=source,
                    shaft_id=shaft_id,
                )
            )
        edge_by_id = {e.edge_id: e for e in edges}

        # -- node supports derived from incident edges ---------------------- #
        incident: dict[str, set[Capability]] = {nid: set() for nid in node_ids}
        for e in edges:
            a, b = endpoints[e.edge_id]
            incident[a].update(e.capabilities)
            incident[b].update(e.capabilities)
        nodes: list[CapabilityNode] = []
        for n in node_list:
            ntype = NodeType(n["type"])
            nodes.append(
                CapabilityNode(
                    node_id=str(n["id"]),
                    node_type=ntype,
                    supports=[c for c in Capability if c in incident[str(n["id"])]],
                    surface=ntype in SURFACE_NODE_TYPES,
                    level_id=n.get("levelId"),
                )
            )
        surface_ids = [n.node_id for n in nodes if n.surface]
        graph = _query_graph(nodes, edges, endpoints)

        # -- required capability paths (directive §36) ----------------------- #
        checks: list[RequiredPathCheck] = []
        portal_ids = [n.node_id for n in nodes if n.node_type is NodeType.PORTAL]

        def check(cid: str, cap: Capability, src: str, dst: str, rule: str) -> None:
            q = can_reach(graph, src, dst, cap)
            checks.append(
                RequiredPathCheck(
                    id=cid,
                    capability=cap,
                    source_node_id=src,
                    target_node_id=dst,
                    rule=rule,
                    physical_reachable=q.physical_reachable,
                    capability_reachable=q.capability_reachable,
                    path_edge_ids=q.path_edge_ids if q.capability_reachable else None,
                    satisfied=q.capability_reachable,
                )
            )

        entries = sorted(n.node_id for n in nodes if n.node_type is NodeType.LEVEL_ENTRY)
        for pid in portal_ids:
            for lid in entries:
                check(
                    f"PERSONNEL_ACCESS:{pid}->{lid}",
                    Capability.PERSONNEL_ACCESS,
                    pid,
                    lid,
                    "portal → required level entry: a PERSONNEL_ACCESS path must exist",
                )
        stations_by_shaft: dict[str, list[str]] = {}
        for n in nodes:
            if n.node_type is NodeType.SHAFT_STATION:
                sid = n.node_id.split(":")[1] if n.node_id.count(":") >= 2 else ""
                stations_by_shaft.setdefault(sid, []).append(n.node_id)
        for sid, caps in sorted(shaft_caps.items()):
            collar = f"{NodeType.SHAFT_COLLAR.value}:{sid}"
            if collar not in node_by_id:
                continue
            for cap in (Capability.PERSONNEL_ACCESS, Capability.MATERIAL_HAULAGE):
                if cap not in caps:
                    continue
                for st in sorted(stations_by_shaft.get(sid, [])):
                    check(
                        f"{cap.value}:{collar}->{st}",
                        cap,
                        collar,
                        st,
                        f"shaft {sid} declares {cap.value}: collar → served station path",
                    )
        underground = [n for n in nodes if not n.surface]
        route_counts = _egress_route_counts(nodes, edges, endpoints, surface_ids)
        for n in underground:
            # an egress route is REQUIRED only where personnel can be: a node
            # no PERSONNEL_ACCESS edge reaches (e.g. a ventilation shaft's
            # stations / bottom) is unoccupied infrastructure. Existence is
            # the requirement; the route COUNT is the advisory below.
            if Capability.PERSONNEL_ACCESS not in n.supports:
                continue
            reachable = route_counts.get(n.node_id, 0) > 0
            checks.append(
                RequiredPathCheck(
                    id=f"EMERGENCY_EGRESS:{n.node_id}->SURFACE",
                    capability=Capability.EMERGENCY_EGRESS,
                    source_node_id=n.node_id,
                    target_node_id="SURFACE",
                    rule=(
                        "every underground node needs one EMERGENCY_EGRESS route to a surface node"
                    ),
                    physical_reachable=any(graph.bfs(n.node_id, s, None) for s in surface_ids),
                    capability_reachable=reachable,
                    path_edge_ids=None,
                    satisfied=reachable,
                )
            )
        advisory = EgressAdvisory(
            criterion=EGRESS_CRITERION,
            required_routes=EGRESS_REQUIRED_ROUTES,
            advisory_only=True,
            surface_node_ids=surface_ids,
            per_node=[
                EgressAdvisoryEntry(
                    node_id=n.node_id,
                    level_id=n.level_id,
                    independent_egress_routes=route_counts.get(n.node_id, 0),
                    meets_criterion=route_counts.get(n.node_id, 0) >= EGRESS_REQUIRED_ROUTES,
                )
                for n in underground
            ],
        )

        unsatisfied = [c.id for c in checks if not c.satisfied]
        revision_ok = bool(network_revision)
        validation = CapabilityValidation(
            referenced_nodes_exist=True,
            referenced_edges_exist=all(e.edge_id in edge_by_id for e in edges),
            no_duplicate_node_ids=True,
            no_duplicate_edge_ids=True,
            network_revision_matches=revision_ok,
            required_paths_satisfied=not unsatisfied,
            valid=revision_ok and not unsatisfied,
            failure_reason=(
                f"required capability paths unsatisfied: {unsatisfied[:5]}"
                if unsatisfied
                else (None if revision_ok else "network revision is empty")
            ),
        )
        per_cap = {c.value: sum(1 for e in edges if c in e.capabilities) for c in Capability}
        metrics = CapabilityMetrics(
            node_count=len(nodes),
            edge_count=len(edges),
            surface_node_count=len(surface_ids),
            edges_per_capability=per_cap,
            required_path_count=len(checks),
            required_paths_satisfied_count=sum(1 for c in checks if c.satisfied),
            build_seconds=time.perf_counter() - t0,
        )
        return CapabilityGraphPayload(
            status="SUCCESS" if validation.valid else "FAILED",
            failure_reason=validation.failure_reason,
            source_revision=source_revision,
            network_revision=network_revision,
            network_source_revision=net_src_rev,
            capabilities=list(Capability),
            nodes=nodes,
            edges=edges,
            surface_node_ids=surface_ids,
            required_paths=checks,
            egress_advisory=advisory,
            validation=validation,
            metrics=metrics,
        )
