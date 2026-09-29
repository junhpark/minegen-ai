"""Shared importer pieces: the imported-result carrier, the edge index the
identities resolve against, and the common geometry arrays every
normalized result stores (the SOURCE snapshot's edge centerlines)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from minegen.results.errors import ResultIdentityUnresolvedError
from minegen.results.geometry import EdgeGeometry, pack_polylines
from minegen.results.models import (
    ResultCounts,
    ResultMetricAvailability,
    ResultSummaryMetric,
    ResultTimeAxis,
)
from minegen.results.normalization import NormalizedResult, str_array


@dataclass(frozen=True)
class EdgeIndex:
    """The current mine's edges with geometry, sorted by id (the ONLY
    identity space a result may bind to — never a coordinate)."""

    edges: list[EdgeGeometry]

    def __post_init__(self) -> None:
        object.__setattr__(self, "edges", sorted(self.edges, key=lambda e: e.edge_id))

    @property
    def ids(self) -> list[str]:
        return [e.edge_id for e in self.edges]

    def index_of(self, edge_id: str, *, subject: str, row: int) -> int:
        ids = self.ids
        k = _bisect(ids, edge_id)
        if k is None:
            raise ResultIdentityUnresolvedError(
                f"row {row}: edgeId {edge_id!r} is not an edge with geometry of the current "
                "MineNetwork",
                subject=subject,
            )
        return k


def _bisect(ids: list[str], value: str) -> int | None:
    lo, hi = 0, len(ids)
    while lo < hi:
        mid = (lo + hi) // 2
        if ids[mid] < value:
            lo = mid + 1
        else:
            hi = mid
    return lo if lo < len(ids) and ids[lo] == value else None


def geometry_arrays(index: EdgeIndex) -> NormalizedResult:
    points, offsets = pack_polylines(index.edges)
    return {
        "edge_ids": str_array(index.ids),
        "edge_types": str_array([e.edge_type for e in index.edges]),
        "edge_source_nodes": str_array([e.source_node_id for e in index.edges]),
        "edge_target_nodes": str_array([e.target_node_id for e in index.edges]),
        "edge_entity_ids": str_array([e.geometry_entity_id for e in index.edges]),
        "geom_points": np.asarray(points, dtype=np.float64),
        "geom_offsets": np.asarray(offsets, dtype=np.int64),
    }


@dataclass
class ImportedResult:
    arrays: NormalizedResult
    time_axis: ResultTimeAxis
    metrics: list[ResultMetricAvailability]
    counts: ResultCounts
    summary_metrics: list[ResultSummaryMetric] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    imported_file_names: list[str] = field(default_factory=list)
    sign_convention: str | None = None
