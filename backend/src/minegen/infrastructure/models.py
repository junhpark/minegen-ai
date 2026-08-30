"""Phase 11 infrastructure placement contract (rules 87–92).

``derived/communication.json`` owns communication PLANNING state only —
candidate sites, demand points, selected assets, coverage assignments,
logical backhaul relations and metrics. Mine geometry and topology remain
owned by the centerline artifacts and the MineNetwork (rule 87); the
communication artifact never patches them.

``CandidateSite`` / ``DemandPoint`` / ``PlacementProblem`` /
``PlacementSolution`` are deliberately generic so the Phase 12 sensor OSP
can reuse the same candidate/demand/placement pattern — no
communication-specific UI concepts live inside them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from minegen.core.enums import AssetType
from minegen.core.models import ApiModel

COVERAGE_MODEL_ID = "NETWORK_DISTANCE_THRESHOLD_V0_1"
SOLVER_ID = "CONNECTED_GREEDY_PATH_SET_COVER_V0_1"


class NetworkLocation(ApiModel):
    """A planning reference point on the MineNetwork (rule 89).

    Either a NODE location (``node_id`` set) or an EDGE location
    (``edge_id`` + ``chainage_m`` measured from the canonical fromNode end,
    strictly inside the edge). ``position`` is backend ENU Z-up interpolated
    on the OWNING centerline — a tunnel-centerline planning reference, NOT
    an exact wall/roof mounting coordinate.
    """

    location_kind: Literal["NODE", "EDGE"]
    node_id: str | None = None
    edge_id: str | None = None
    chainage_m: float | None = None
    position: tuple[float, float, float]


class CandidateSite(NetworkLocation):
    id: str
    eligible: bool = True


class DemandPoint(NetworkLocation):
    id: str
    weight: float = 1.0  # Phase 11 uses UNIFORM demand weights only


class PlacementProblem(ApiModel):
    """Generic connected-placement problem (reusable for Phase 12).

    ``candidate_coverage_sets`` maps candidate id -> sorted demand ids it
    covers; ``candidate_backhaul_graph`` maps candidate id -> sorted
    neighbouring candidate ids within backhaul range. Both are LOGICAL
    planning relations, never MineNetwork mutations.
    """

    candidates: list[CandidateSite]
    demands: list[DemandPoint]
    candidate_coverage_sets: dict[str, list[str]]
    candidate_backhaul_graph: dict[str, list[str]]
    required_coverage_fraction: float
    mandatory_candidate_ids: list[str]


class PlacementSolution(ApiModel):
    status: Literal["SUCCESS", "FAILED"]
    failure_reason: str | None
    selected_candidate_ids: list[str]
    covered_demand_ids: list[str]


class CommunicationAsset(ApiModel):
    id: str
    asset_type: AssetType
    candidate_id: str
    position: tuple[float, float, float]
    backhaul_parent_asset_id: str | None
    hop_count: int


class DemandCoverage(ApiModel):
    demand_id: str
    covered: bool
    serving_asset_id: str | None
    network_distance_m: float | None


class CommunicationModelSummary(ApiModel):
    asset_type: AssetType
    coverage_model: str = COVERAGE_MODEL_ID
    solver: str = SOLVER_ID
    # deterministic connected-greedy baseline — never a global-optimality claim
    optimality_claim: bool = False
    coverage_range_m: float
    backhaul_range_m: float
    required_coverage_fraction: float


class CommunicationMetrics(ApiModel):
    candidate_count: int
    demand_count: int
    selected_asset_count: int  # connected-greedy baseline router count
    covered_demand_count: int
    uncovered_demand_count: int
    coverage_fraction: float
    mean_serving_distance_m: float | None
    max_serving_distance_m: float | None
    backhaul_link_count: int
    max_backhaul_hop_count: int
    total_network_length3d: float = Field(alias="totalNetworkLength3d")


class CommunicationPayload(ApiModel):
    status: Literal["SUCCESS", "FAILED"]
    failure_reason: str | None
    source_revision: str
    model: CommunicationModelSummary | None
    candidates: list[CandidateSite]
    demands: list[DemandPoint]
    selected_assets: list[CommunicationAsset]
    demand_coverage: list[DemandCoverage]
    metrics: CommunicationMetrics | None
