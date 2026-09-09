"""Phase 20C.2B capability-graph contract (rule 185).

``derived/capability_graph.json`` is a SEMANTIC layer over the MineNetwork:
it says WHAT each physical connection may be used for (typed capability
tags), never how much (no capacity, throughput, airflow or hoist cycle —
those belong to later simulation phases). It references MineNetwork node
and edge ids only; it owns no geometry and no topology.

GEOMETRY ≠ TOPOLOGY ≠ CAPABILITY:

* geometry lives in the owning centerline / shaft artifacts,
* topology (what connects to what) is ``network.json``,
* capability (who may use it for what) is this artifact.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from minegen.core.enums import Capability, EdgeType, NodeType
from minegen.core.models import ApiModel


class CapabilitySource(StrEnum):
    """Where an edge's capability set came from — always explicit (rule
    185): never inferred from geometry alone."""

    EDGE_TYPE_DEFAULT = "EDGE_TYPE_DEFAULT"  # module default per edge type
    EDGE_TYPE_DECLARED = "EDGE_TYPE_DECLARED"  # scenario.capability override
    SHAFT_DECLARED = "SHAFT_DECLARED"  # ShaftSpec.capabilities of the owning shaft
    DERIVED_FROM_INCIDENT_EDGES = "DERIVED_FROM_INCIDENT_EDGES"  # node supports


class CapabilityEdge(ApiModel):
    edge_id: str
    edge_type: EdgeType
    capabilities: list[Capability]
    #: the complement — capabilities this edge may NOT be used for
    restrictions: list[Capability]
    source: CapabilitySource
    shaft_id: str | None = None


class CapabilityNode(ApiModel):
    node_id: str
    node_type: NodeType
    #: union of the incident edges' capabilities (a node is traversable for a
    #: capability only through edges carrying it — this is informational)
    supports: list[Capability]
    source: Literal[CapabilitySource.DERIVED_FROM_INCIDENT_EDGES] = (
        CapabilitySource.DERIVED_FROM_INCIDENT_EDGES
    )
    surface: bool
    level_id: str | None = None


class RequiredPathCheck(ApiModel):
    """One required capability path (directive §36): a physical path may
    exist while the capability-compatible path does not — both are
    reported, and only the capability path decides ``satisfied``."""

    id: str
    capability: Capability
    source_node_id: str
    target_node_id: str
    rule: str
    physical_reachable: bool
    capability_reachable: bool
    path_edge_ids: list[str] | None
    satisfied: bool


class EgressAdvisoryEntry(ApiModel):
    node_id: str
    level_id: str | None
    independent_egress_routes: int
    meets_criterion: bool


class EgressAdvisory(ApiModel):
    """Edge-disjoint EMERGENCY_EGRESS routes from every underground node to
    any surface node (PORTAL / SHAFT_COLLAR) on the capability-filtered
    subgraph. Design advisory only — no statutory or regulatory claim, no
    dual-egress compliance (that is Phase 20D)."""

    capability: Literal[Capability.EMERGENCY_EGRESS] = Capability.EMERGENCY_EGRESS
    criterion: str
    required_routes: int
    advisory_only: bool
    surface_node_ids: list[str]
    per_node: list[EgressAdvisoryEntry]


class CapabilityValidation(ApiModel):
    referenced_nodes_exist: bool
    referenced_edges_exist: bool
    no_duplicate_node_ids: bool
    no_duplicate_edge_ids: bool
    network_revision_matches: bool
    required_paths_satisfied: bool
    valid: bool
    failure_reason: str | None = None


class CapabilityMetrics(ApiModel):
    node_count: int
    edge_count: int
    surface_node_count: int
    edges_per_capability: dict[str, int]
    required_path_count: int
    required_paths_satisfied_count: int
    build_seconds: float


class CapabilityGraphPayload(ApiModel):
    status: Literal["SUCCESS", "FAILED"]
    failure_reason: str | None
    source_revision: str
    #: file revision of the ``network.json`` this graph was built over (rule
    #: 185 synchronization): a different revision on disk makes it stale
    network_revision: str
    #: the network payload's own ``sourceRevision`` (recorded, cross-checked)
    network_source_revision: str
    capabilities: list[Capability]
    nodes: list[CapabilityNode]
    edges: list[CapabilityEdge]
    surface_node_ids: list[str]
    required_paths: list[RequiredPathCheck]
    egress_advisory: EgressAdvisory | None
    validation: CapabilityValidation | None
    metrics: CapabilityMetrics | None


class CapabilityPathQuery(ApiModel):
    """``can_reach(source, target, capability)`` result: the physical answer
    and the capability-filtered answer are distinct (directive §35)."""

    source_node_id: str
    target_node_id: str
    capability: Capability
    physical_reachable: bool
    capability_reachable: bool
    path_node_ids: list[str] = Field(default_factory=list)
    path_edge_ids: list[str] = Field(default_factory=list)
