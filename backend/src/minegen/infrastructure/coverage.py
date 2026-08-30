"""Phase 11 communication coverage-model strategy (rule 88).

``CommunicationCoverageModel`` is the replaceable evaluation contract: it
owns the conversion from precomputed PHYSICAL network-geodesic distances to
candidate coverage sets and the candidate backhaul graph. The builder owns
network/geometry validation, sampling, the geodesic distance computation and
problem assembly — but delegates coverage/backhaul evaluation here, so a
calibrated propagation model can replace ``NetworkDistanceThresholdModel``
later without touching the builder.

``NETWORK_DISTANCE_THRESHOLD_V0_1`` is deliberately a planning proxy: pure
distance thresholds with a documented 1e-6 m numerical tolerance. No
RSSI/dBm/frequency/antenna/Fresnel/ray-tracing is computed here or claimed.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

DISTANCE_TOLERANCE = 1e-6  # m — documented coverage/backhaul comparison slack


class CommunicationCoverageModel(Protocol):
    """Strategy contract consumed by ``CommunicationBuilder``.

    Distance matrices are network-geodesic (metres through the MineNetwork,
    never Euclidean); rows/columns follow the given id orderings.
    """

    model_id: str

    def coverage_sets(
        self,
        candidate_ids: list[str],
        demand_ids: list[str],
        candidate_demand_distance: np.ndarray,
    ) -> dict[str, list[str]]:
        """candidate id -> sorted demand ids it covers."""
        ...

    def backhaul_graph(
        self,
        candidate_ids: list[str],
        candidate_candidate_distance: np.ndarray,
    ) -> dict[str, list[str]]:
        """candidate id -> sorted neighbouring candidate ids (no self-loops)."""
        ...


class NetworkDistanceThresholdModel:
    """``NETWORK_DISTANCE_THRESHOLD_V0_1``: a candidate covers a demand iff
    geodesic <= coverageRangeM + 1e-6; two candidates form a backhaul
    relation iff geodesic <= backhaulRangeM + 1e-6."""

    model_id = "NETWORK_DISTANCE_THRESHOLD_V0_1"

    def __init__(self, coverage_range_m: float, backhaul_range_m: float) -> None:
        self.coverage_range_m = float(coverage_range_m)
        self.backhaul_range_m = float(backhaul_range_m)

    def coverage_sets(
        self,
        candidate_ids: list[str],
        demand_ids: list[str],
        candidate_demand_distance: np.ndarray,
    ) -> dict[str, list[str]]:
        threshold = self.coverage_range_m + DISTANCE_TOLERANCE
        return {
            candidate_ids[i]: sorted(
                demand_ids[j] for j in np.flatnonzero(candidate_demand_distance[i] <= threshold)
            )
            for i in range(len(candidate_ids))
        }

    def backhaul_graph(
        self,
        candidate_ids: list[str],
        candidate_candidate_distance: np.ndarray,
    ) -> dict[str, list[str]]:
        threshold = self.backhaul_range_m + DISTANCE_TOLERANCE
        mask = candidate_candidate_distance <= threshold
        np.fill_diagonal(mask, False)
        return {
            candidate_ids[i]: sorted(candidate_ids[j] for j in np.flatnonzero(mask[i]))
            for i in range(len(candidate_ids))
        }
