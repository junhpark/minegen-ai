"""Typed DTOs of the design assessment read model (Phase 20D.3, rule 189).

Every check names the AUTHORITY of what it states:

    HARD_DESIGN_RULE    a hard engineering gate the layout-v2 search / access
                        planner already enforced (FEASIBLE status, level
                        access, clearance certification)
    DERIVED_VALIDATION  a recorded validation result of a derived artifact
                        (delivered-centerline sample validation, capability
                        graph validation, required capability paths)
    ADVISORY            a design advisory with no compliance meaning (the
                        dual-egress route count of ``capability_graph.json``)
    INFORMATIONAL       a fact about the selection (active source, whether
                        the selection is the ranking winner)

and a STATUS from the closed set SATISFIED / NOT_SATISFIED / NOT_APPLICABLE /
NOT_EVALUATED. ``NOT_EVALUATED`` is the honest answer whenever the artifact or
field that would prove a check is absent — nothing is inferred (directive
§7 / §17). Evidence carries machine-verifiable numbers and node / candidate /
level ids only; the wording of a check is a fixed template, never persisted
reasoning.
"""

from __future__ import annotations

from typing import Literal

from minegen.core.enums import Capability
from minegen.core.models import ApiModel

__all__ = [
    "AssessmentAuthority",
    "AssessmentCheck",
    "AssessmentStatus",
    "CandidateComparisonRow",
    "CandidateStatusLiteral",
    "ComparisonAccessSummary",
    "ComparisonClearance",
    "ComparisonScores",
    "DesignAssessmentPayload",
    "DesignAssessmentSources",
    "EgressAdvisoryProjection",
    "EvidenceValue",
    "RequiredPathProjection",
    "ScoreDeltas",
]

CandidateStatusLiteral = Literal["FEASIBLE", "INFEASIBLE", "NOT_VALIDATED"]
AssessmentStatus = Literal["SATISFIED", "NOT_SATISFIED", "NOT_APPLICABLE", "NOT_EVALUATED"]
AssessmentAuthority = Literal["HARD_DESIGN_RULE", "DERIVED_VALIDATION", "ADVISORY", "INFORMATIONAL"]
#: evidence is numbers, flags, ids and lists of ids — never free text
EvidenceValue = int | float | bool | str | list[str] | None


class AssessmentCheck(ApiModel):
    id: str
    title: str
    category: Literal["LAYOUT", "ACCESS", "CLEARANCE", "GEOMETRY", "CAPABILITY", "EGRESS"]
    status: AssessmentStatus
    authority: AssessmentAuthority
    summary: str
    evidence: dict[str, EvidenceValue]
    source_artifact: str
    source_field: str


class ComparisonScores(ApiModel):
    """The three group scores and the total, copied verbatim from
    ``layout_v2.json`` ``candidates[].scores`` (rule 148: planning
    comparators, never recomputed here)."""

    development: float
    geology: float
    geometry: float
    total: float


class ScoreDeltas(ApiModel):
    """Plain subtraction against the ranking winner's scores (directive
    §13): ``candidate − winner`` per group — no weighting, no re-selection."""

    total_score_delta_from_winner: float
    development_score_delta: float
    geology_score_delta: float
    geometry_score_delta: float


class ComparisonClearance(ApiModel):
    clearance_basis: str
    required_clearance: float
    conservative_minimum_clearance: float
    clearance_error_bound: float | None
    satisfied: bool


class ComparisonAccessSummary(ApiModel):
    level_count: int
    accessible_level_count: int
    total_access_length: float
    worst_access_length: float
    max_access_gradient: float
    min_access_plan_radius: float | None


class CandidateComparisonRow(ApiModel):
    candidate_id: str
    family: str
    rank: int | None
    selected: bool
    winner: bool
    status: CandidateStatusLiteral
    stage_reached: str
    scores: ComparisonScores | None
    deltas: ScoreDeltas | None
    accessible_levels: int | None
    required_levels: int
    clearance: ComparisonClearance | None
    access: ComparisonAccessSummary | None
    failure_reasons: list[str]
    failure_detail: str | None


class RequiredPathProjection(ApiModel):
    """``capability_graph.json`` ``requiredPaths[]`` as recorded: physical
    and capability reachability stay two separate facts (rule 185)."""

    id: str
    capability: Capability
    source_node_id: str
    target_node_id: str
    rule: str
    physical_reachable: bool
    capability_reachable: bool
    satisfied: bool


class EgressAdvisoryProjection(ApiModel):
    """Summary of ``capability_graph.json`` ``egressAdvisory`` — a design
    advisory (``advisoryOnly`` is always the recorded flag), never a
    statutory compliance determination."""

    criterion: str
    required_routes: int
    advisory_only: bool
    surface_node_ids: list[str]
    underground_node_count: int
    meeting_node_count: int
    failing_node_count: int
    failing_node_ids: list[str]
    minimum_independent_routes: int | None


class DesignAssessmentSources(ApiModel):
    """Provenance of the projection: the ACTIVE ramp source and the file
    revisions of every artifact the snapshot observed (``None`` = absent),
    with the validated reader's own revision meaning (directive §16)."""

    active_source: Literal["LEGACY", "LAYOUT_V2"]
    layout_v2_revision: str | None
    selected_layout_revision: str | None
    level_accesses_revision: str | None
    network_revision: str | None
    capability_graph_revision: str | None


class DesignAssessmentPayload(ApiModel):
    """``GET …/design/assessment``. ``status`` is the assessment's own
    generation status (a read model computed from VALID artifacts), never a
    design feasibility verdict (directive §15)."""

    status: Literal["SUCCESS"]
    active_source: Literal["LEGACY", "LAYOUT_V2"]
    winner_id: str | None
    selected_candidate_id: str | None
    selected_candidate: CandidateComparisonRow | None
    checks: list[AssessmentCheck]
    candidate_comparison: list[CandidateComparisonRow]
    required_paths: list[RequiredPathProjection]
    egress_advisory: EgressAdvisoryProjection | None
    summary: str
    sources: DesignAssessmentSources
