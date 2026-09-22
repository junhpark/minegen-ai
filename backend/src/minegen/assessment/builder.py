"""Design-assessment projection (Phase 20D.3, rule 189).

Pure functions over ALREADY-VALIDATED documents: the layout-v2 catalogue
(raw ``layout_v2.json`` dict — ranking, statuses, scores are read verbatim),
the selection (raw ``layout_v2_selected.json`` dict or ``None``), the typed
``CapabilityGraphPayload`` (or ``None`` when absent) and the provenance
``DesignAssessmentSources``. Nothing here touches the file system, runs a
search, evaluates geometry or applies a graph algorithm; every number in
the output is copied from an input field or is a plain subtraction of two
copied numbers (score deltas, directive §13).

The comparison is the catalogue's ``ranking`` list (rule 148 order),
bounded to ``max_comparison_rows`` with the ranking winner and the selected
candidate always present; a ranking entry that is not FEASIBLE is a
catalogue inconsistency and is refused (``ValueError``), never shown as an
alternative (directive §10).
"""

from __future__ import annotations

from typing import Any

from minegen.assessment.models import (
    AssessmentAuthority,
    AssessmentCheck,
    AssessmentScope,
    AssessmentStatus,
    CandidateComparisonRow,
    ComparisonAccessSummary,
    ComparisonClearance,
    ComparisonScores,
    DesignAssessmentPayload,
    DesignAssessmentSources,
    EgressAdvisoryProjection,
    EvidenceValue,
    LayoutScope,
    RequiredPathProjection,
    ScoreDeltas,
)
from minegen.capability.models import CapabilityGraphPayload
from minegen.core.artifacts import (
    CAPABILITY_GRAPH_ARTIFACT,
    LAYOUT_V2_ARTIFACT,
    LAYOUT_V2_SELECTED_ARTIFACT,
    RAMP_SOURCE_FILE,
)

__all__ = ["DEFAULT_MAX_COMPARISON_ROWS", "build_design_assessment"]

#: winner + top FEASIBLE alternatives (directive §10); the selected candidate
#: is always a row even beyond this bound
DEFAULT_MAX_COMPARISON_ROWS = 5

FEASIBLE = "FEASIBLE"
SATISFIED: AssessmentStatus = "SATISFIED"
NOT_SATISFIED: AssessmentStatus = "NOT_SATISFIED"
NOT_EVALUATED: AssessmentStatus = "NOT_EVALUATED"
NOT_APPLICABLE: AssessmentStatus = "NOT_APPLICABLE"
ACTIVE: AssessmentScope = "ACTIVE_DESIGN"
INACTIVE: AssessmentScope = "INACTIVE_LAYOUT_V2"
_INACTIVE_PREFIX = "inactive layout-v2 selection: "

_ADVISORY_DISCLAIMER = "This is a design advisory, not a statutory compliance determination."


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #


def build_design_assessment(
    *,
    catalogue: dict[str, Any] | None,
    selected: dict[str, Any] | None,
    capability: CapabilityGraphPayload | None,
    sources: DesignAssessmentSources,
    max_comparison_rows: int = DEFAULT_MAX_COMPARISON_ROWS,
) -> DesignAssessmentPayload:
    if max_comparison_rows < 1:
        raise ValueError("max_comparison_rows must be >= 1")
    active = sources.active_source
    if catalogue is None and active == "LAYOUT_V2":
        raise ValueError("a LAYOUT_V2 active source requires the layout-v2 catalogue")
    layout_scope: LayoutScope = (
        "ACTIVE_DESIGN"
        if active == "LAYOUT_V2"
        else "NONE"
        if catalogue is None
        else "INACTIVE_LAYOUT_V2"
    )
    scope: AssessmentScope = ACTIVE if active == "LAYOUT_V2" else INACTIVE
    by_id = _candidates_by_id(catalogue) if catalogue is not None else {}
    ranking = _ranking(catalogue, by_id) if catalogue is not None else []
    winner_id = catalogue.get("winnerId") if catalogue is not None else None
    winner_id = str(winner_id) if winner_id is not None else None
    selected_id = None if selected is None else str(selected["candidateId"])
    winner_scores = by_id[winner_id].get("scores") if winner_id in by_id else None

    rows = [
        _row(by_id[cid], selected_id=selected_id, winner_id=winner_id, winner_scores=winner_scores)
        for cid in _comparison_ids(ranking, winner_id, selected_id, max_comparison_rows)
    ]
    selected_row = (
        _row(
            by_id[selected_id],
            selected_id=selected_id,
            winner_id=winner_id,
            winner_scores=winner_scores,
        )
        if selected_id is not None and selected_id in by_id
        else None
    )
    selected_cand = by_id.get(selected_id) if selected_id is not None else None

    checks = [
        _check_layout_selected(selected, selected_id),
        _check_active_source(sources, selected_id),
        _check_selected_is_winner(selected_id, winner_id, selected_cand),
        _check_candidate_feasible(selected_id, selected_cand),
        _check_levels_accessible(selected_id, selected_cand),
        _check_clearance(selected_id, selected_cand),
        _check_geometry(selected_id, selected_cand),
    ]
    checks = [_scoped(c, scope, catalogue is None) for c in checks]
    checks += [
        _check_capability_valid(capability),
        _check_required_paths(capability),
        _check_egress(capability),
    ]
    required_paths = [] if capability is None else _required_paths(capability)
    egress = None if capability is None else _egress_projection(capability)
    return DesignAssessmentPayload(
        status="SUCCESS",
        active_source=active,
        layout_scope=layout_scope,
        active_design_candidate_id=selected_id if active == "LAYOUT_V2" else None,
        winner_id=winner_id,
        selected_candidate_id=selected_id,
        selected_candidate=selected_row,
        checks=checks,
        candidate_comparison=rows,
        required_paths=required_paths,
        egress_advisory=egress,
        summary=_summary(
            catalogue,
            ranking,
            by_id,
            active_source=active,
            winner_id=winner_id,
            selected_id=selected_id,
            selected_cand=selected_cand,
            egress=egress,
            capability=capability,
        ),
        sources=sources,
    )


def _scoped(check: AssessmentCheck, scope: AssessmentScope, no_catalogue: bool) -> AssessmentCheck:
    """Layout-v2 checks under a LEGACY active source describe a DORMANT
    layout-v2 selection, never the active design: they keep their recorded
    status but carry the INACTIVE scope and a summary prefix; with no
    catalogue at all they are NOT_APPLICABLE. ``ACTIVE_RAMP_SOURCE`` is a
    fact about the active design and keeps the active scope."""
    if scope == ACTIVE or check.id == "ACTIVE_RAMP_SOURCE":
        return check
    if no_catalogue:
        return check.model_copy(
            update={
                "scope": INACTIVE,
                "status": NOT_APPLICABLE,
                "summary": "not applicable: the active design is the LEGACY ramp and no "
                "layout-v2 catalogue exists",
                "evidence": {},
            }
        )
    return check.model_copy(update={"scope": INACTIVE, "summary": _INACTIVE_PREFIX + check.summary})


# --------------------------------------------------------------------------- #
# catalogue access (verbatim, never recomputed)
# --------------------------------------------------------------------------- #


def _candidates_by_id(catalogue: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for cand in catalogue.get("candidates", []):
        cid = str(cand["candidateId"])
        if cid in by_id:
            raise ValueError(f"{LAYOUT_V2_ARTIFACT}: duplicate candidate id {cid!r}")
        by_id[cid] = cand
    return by_id


def _ranking(catalogue: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> list[str]:
    """The authoritative ranking, checked for internal consistency only: an
    entry must exist and be FEASIBLE with a rank (rule 148 ranks feasible
    candidates only). Anything else is a catalogue defect, refused."""
    ranking = [str(cid) for cid in catalogue.get("ranking", [])]
    for cid in ranking:
        cand = by_id.get(cid)
        if cand is None:
            raise ValueError(f"{LAYOUT_V2_ARTIFACT}: ranking names unknown candidate {cid!r}")
        if cand.get("status") != FEASIBLE or cand.get("rank") is None:
            raise ValueError(
                f"{LAYOUT_V2_ARTIFACT}: ranking entry {cid!r} is {cand.get('status')} "
                f"(rank {cand.get('rank')}) — only FEASIBLE ranked candidates are alternatives"
            )
    return ranking


def _comparison_ids(
    ranking: list[str], winner_id: str | None, selected_id: str | None, max_rows: int
) -> list[str]:
    """Top ``max_rows`` of the ranking, plus the winner and the FEASIBLE
    selection when they fall outside; order stays the ranking order."""
    keep = set(ranking[:max_rows])
    if winner_id in ranking:
        keep.add(winner_id)
    if selected_id in ranking:
        keep.add(selected_id)
    return [cid for cid in ranking if cid in keep]


def _row(
    cand: dict[str, Any],
    *,
    selected_id: str | None,
    winner_id: str | None,
    winner_scores: dict[str, Any] | None,
) -> CandidateComparisonRow:
    cid = str(cand["candidateId"])
    scores = _scores(cand.get("scores"))
    deltas = None
    if scores is not None and winner_scores is not None:
        deltas = ScoreDeltas(
            total_score_delta_from_winner=scores.total - float(winner_scores["total"]),
            development_score_delta=scores.development - float(winner_scores["development"]),
            geology_score_delta=scores.geology - float(winner_scores["geology"]),
            geometry_score_delta=scores.geometry - float(winner_scores["geometry"]),
        )
    return CandidateComparisonRow(
        candidate_id=cid,
        family=str(cand["family"]),
        rank=cand.get("rank"),
        selected=cid == selected_id,
        winner=cid == winner_id,
        status=cand["status"],
        stage_reached=str(cand.get("stageReached")),
        scores=scores,
        deltas=deltas,
        accessible_levels=cand.get("accessibleLevels"),
        required_levels=int(cand["requiredLevels"]),
        clearance=_clearance(cand.get("clearance")),
        access=_access(cand.get("access")),
        failure_reasons=[str(r) for r in cand.get("failureReasons", [])],
        failure_detail=cand.get("failureDetail"),
    )


def _scores(scores: dict[str, Any] | None) -> ComparisonScores | None:
    if scores is None:
        return None
    return ComparisonScores(
        development=scores["development"],
        geology=scores["geology"],
        geometry=scores["geometry"],
        total=scores["total"],
    )


def _clearance(clearance: dict[str, Any] | None) -> ComparisonClearance | None:
    if clearance is None:
        return None
    return ComparisonClearance(
        clearance_basis=str(clearance["clearanceBasis"]),
        required_clearance=clearance["requiredClearance"],
        conservative_minimum_clearance=clearance["conservativeMinimumClearance"],
        clearance_error_bound=clearance.get("clearanceErrorBound"),
        satisfied=bool(clearance["satisfied"]),
    )


def _access(access: dict[str, Any] | None) -> ComparisonAccessSummary | None:
    if access is None:
        return None
    return ComparisonAccessSummary(
        level_count=access["levelCount"],
        accessible_level_count=access["accessibleLevelCount"],
        total_access_length=access["totalAccessLength"],
        worst_access_length=access["worstAccessLength"],
        max_access_gradient=access["maxAccessGradient"],
        min_access_plan_radius=access.get("minAccessPlanRadius"),
    )


# --------------------------------------------------------------------------- #
# checks — each reads ONE recorded field set; absent → NOT_EVALUATED
# --------------------------------------------------------------------------- #


def _check(
    check_id: str,
    title: str,
    category: str,
    authority: AssessmentAuthority,
    status: AssessmentStatus,
    summary: str,
    evidence: dict[str, EvidenceValue],
    source_artifact: str,
    source_field: str,
) -> AssessmentCheck:
    return AssessmentCheck(
        id=check_id,
        title=title,
        category=category,
        status=status,
        authority=authority,
        scope=ACTIVE,
        summary=summary,
        evidence=evidence,
        source_artifact=source_artifact,
        source_field=source_field,
    )


def _no_selection(
    check_id: str, title: str, category: str, authority: AssessmentAuthority, source_field: str
) -> AssessmentCheck:
    return _check(
        check_id,
        title,
        category,
        authority,
        NOT_EVALUATED,
        f"not evaluated: no layout candidate is selected ({LAYOUT_V2_SELECTED_ARTIFACT} absent)",
        {},
        LAYOUT_V2_ARTIFACT,
        source_field,
    )


def _not_in_catalogue(
    check_id: str,
    title: str,
    category: str,
    authority: AssessmentAuthority,
    source_field: str,
    selected_id: str,
) -> AssessmentCheck:
    return _check(
        check_id,
        title,
        category,
        authority,
        NOT_EVALUATED,
        f"not evaluated: selected candidate {selected_id} is not in the catalogue",
        {},
        LAYOUT_V2_ARTIFACT,
        source_field,
    )


def _check_layout_selected(
    selected: dict[str, Any] | None, selected_id: str | None
) -> AssessmentCheck:
    title = "Layout candidate selected"
    if selected is None or selected_id is None:
        return _check(
            "LAYOUT_SELECTED",
            title,
            "LAYOUT",
            "DERIVED_VALIDATION",
            NOT_SATISFIED,
            "no layout-v2 candidate has been selected",
            {},
            LAYOUT_V2_SELECTED_ARTIFACT,
            "candidateId",
        )
    return _check(
        "LAYOUT_SELECTED",
        title,
        "LAYOUT",
        "DERIVED_VALIDATION",
        SATISFIED,
        f"selected candidate {selected_id}",
        {"candidateId": selected_id, "layoutRevision": _opt_str(selected.get("layoutRevision"))},
        LAYOUT_V2_SELECTED_ARTIFACT,
        "candidateId",
    )


def _check_active_source(
    sources: DesignAssessmentSources, selected_id: str | None
) -> AssessmentCheck:
    active = sources.active_source
    return _check(
        "ACTIVE_RAMP_SOURCE",
        "Active ramp source is Layout v2",
        "LAYOUT",
        "INFORMATIONAL",
        SATISFIED if active == "LAYOUT_V2" else NOT_SATISFIED,
        (
            "the active Effective Ramp is the layout-v2 selection"
            if active == "LAYOUT_V2"
            else "the active ramp source is LEGACY (Hybrid-A* ramp); network and capability "
            "checks describe that design, layout-v2 checks describe a dormant selection"
        ),
        {
            "activeSource": active,
            "selectedCandidateId": selected_id,
            "inactiveLayoutSelectionId": None if active == "LAYOUT_V2" else selected_id,
        },
        RAMP_SOURCE_FILE,
        "activeSource",
    )


def _check_selected_is_winner(
    selected_id: str | None, winner_id: str | None, cand: dict[str, Any] | None
) -> AssessmentCheck:
    title = "Selected candidate is the ranking winner"
    if selected_id is None:
        return _no_selection(
            "SELECTED_IS_RANKING_WINNER", title, "LAYOUT", "INFORMATIONAL", "winnerId"
        )
    is_winner = selected_id == winner_id
    return _check(
        "SELECTED_IS_RANKING_WINNER",
        title,
        "LAYOUT",
        "INFORMATIONAL",
        SATISFIED if is_winner else NOT_SATISFIED,
        (
            f"{selected_id} is the ranking winner"
            if is_winner
            else f"{selected_id} is not the ranking winner ({winner_id})"
        ),
        {
            "winnerId": winner_id,
            "selectedCandidateId": selected_id,
            "selectedRank": None if cand is None else cand.get("rank"),
        },
        LAYOUT_V2_ARTIFACT,
        "winnerId",
    )


def _check_candidate_feasible(
    selected_id: str | None, cand: dict[str, Any] | None
) -> AssessmentCheck:
    title = "Selected candidate feasible"
    field = "candidates[].status"
    if selected_id is None:
        return _no_selection("CANDIDATE_FEASIBLE", title, "LAYOUT", "HARD_DESIGN_RULE", field)
    if cand is None:
        return _not_in_catalogue(
            "CANDIDATE_FEASIBLE", title, "LAYOUT", "HARD_DESIGN_RULE", field, selected_id
        )
    status = str(cand.get("status"))
    reasons = [str(r) for r in cand.get("failureReasons", [])]
    return _check(
        "CANDIDATE_FEASIBLE",
        title,
        "LAYOUT",
        "HARD_DESIGN_RULE",
        SATISFIED if status == FEASIBLE else NOT_SATISFIED,
        f"candidate status {status} at stage {cand.get('stageReached')}"
        + (f"; failure reasons: {', '.join(reasons)}" if reasons else ""),
        {
            "status": status,
            "stageReached": _opt_str(cand.get("stageReached")),
            "rank": cand.get("rank"),
            "failureReasons": reasons,
        },
        LAYOUT_V2_ARTIFACT,
        field,
    )


def _check_levels_accessible(
    selected_id: str | None, cand: dict[str, Any] | None
) -> AssessmentCheck:
    title = "All required levels accessible"
    field = "candidates[].accessibleLevels / requiredLevels"
    if selected_id is None:
        return _no_selection(
            "ALL_REQUIRED_LEVELS_ACCESSIBLE", title, "ACCESS", "HARD_DESIGN_RULE", field
        )
    if cand is None:
        return _not_in_catalogue(
            "ALL_REQUIRED_LEVELS_ACCESSIBLE",
            title,
            "ACCESS",
            "HARD_DESIGN_RULE",
            field,
            selected_id,
        )
    accessible = cand.get("accessibleLevels")
    required = cand.get("requiredLevels")
    if accessible is None or required is None:
        return _check(
            "ALL_REQUIRED_LEVELS_ACCESSIBLE",
            title,
            "ACCESS",
            "HARD_DESIGN_RULE",
            NOT_EVALUATED,
            "not evaluated: level access was not validated for this candidate "
            f"(stage {cand.get('stageReached')})",
            {},
            LAYOUT_V2_ARTIFACT,
            field,
        )
    access = cand.get("access") or {}
    failures = access.get("failures") if isinstance(access, dict) else None
    unserved = sorted(str(k) for k in failures) if isinstance(failures, dict) else []
    ok = int(accessible) == int(required)
    return _check(
        "ALL_REQUIRED_LEVELS_ACCESSIBLE",
        title,
        "ACCESS",
        "HARD_DESIGN_RULE",
        SATISFIED if ok else NOT_SATISFIED,
        f"{int(accessible)} / {int(required)} required levels have a validated level access"
        + (f"; unserved: {', '.join(unserved)}" if unserved else ""),
        {
            "accessibleLevels": int(accessible),
            "requiredLevels": int(required),
            "unservedLevelIds": unserved,
        },
        LAYOUT_V2_ARTIFACT,
        field,
    )


def _check_clearance(selected_id: str | None, cand: dict[str, Any] | None) -> AssessmentCheck:
    title = "Orebody clearance validated"
    field = "candidates[].clearance"
    if selected_id is None:
        return _no_selection("CLEARANCE_VALIDATED", title, "CLEARANCE", "HARD_DESIGN_RULE", field)
    if cand is None:
        return _not_in_catalogue(
            "CLEARANCE_VALIDATED", title, "CLEARANCE", "HARD_DESIGN_RULE", field, selected_id
        )
    clearance = cand.get("clearance")
    if not isinstance(clearance, dict):
        return _check(
            "CLEARANCE_VALIDATED",
            title,
            "CLEARANCE",
            "HARD_DESIGN_RULE",
            NOT_EVALUATED,
            "not evaluated: no clearance report was recorded for this candidate",
            {},
            LAYOUT_V2_ARTIFACT,
            field,
        )
    satisfied = bool(clearance.get("satisfied"))
    basis = _opt_str(clearance.get("clearanceBasis"))
    return _check(
        "CLEARANCE_VALIDATED",
        title,
        "CLEARANCE",
        "HARD_DESIGN_RULE",
        SATISFIED if satisfied else NOT_SATISFIED,
        f"{basis} basis: minimum clearance {_num(clearance.get('conservativeMinimumClearance'))} m "
        f"vs required {_num(clearance.get('requiredClearance'))} m",
        {
            "clearanceBasis": basis,
            "requiredClearance": clearance.get("requiredClearance"),
            "conservativeMinimumClearance": clearance.get("conservativeMinimumClearance"),
            "clearanceErrorBound": clearance.get("clearanceErrorBound"),
            "satisfied": satisfied,
        },
        LAYOUT_V2_ARTIFACT,
        field,
    )


def _check_geometry(selected_id: str | None, cand: dict[str, Any] | None) -> AssessmentCheck:
    title = "Delivered centerline validated"
    field = "candidates[].validation"
    if selected_id is None:
        return _no_selection("GEOMETRY_VALIDATED", title, "GEOMETRY", "DERIVED_VALIDATION", field)
    if cand is None:
        return _not_in_catalogue(
            "GEOMETRY_VALIDATED", title, "GEOMETRY", "DERIVED_VALIDATION", field, selected_id
        )
    validation = cand.get("validation")
    if not isinstance(validation, dict) or "invalidSampleCount" not in validation:
        return _check(
            "GEOMETRY_VALIDATED",
            title,
            "GEOMETRY",
            "DERIVED_VALIDATION",
            NOT_EVALUATED,
            "not evaluated: no sample validation was recorded for this candidate",
            {},
            LAYOUT_V2_ARTIFACT,
            field,
        )
    invalid = int(validation["invalidSampleCount"])
    samples = int(validation.get("sampleCount", 0))
    reasons = validation.get("rejectionReasonCounts")
    reason_ids = sorted(str(k) for k in reasons) if isinstance(reasons, dict) else []
    ok = invalid == 0 and samples > 0
    return _check(
        "GEOMETRY_VALIDATED",
        title,
        "GEOMETRY",
        "DERIVED_VALIDATION",
        SATISFIED if ok else NOT_SATISFIED,
        f"{invalid} invalid of {samples} validated centerline samples"
        + (f"; rejections: {', '.join(reason_ids)}" if reason_ids else ""),
        {
            "sampleCount": samples,
            "invalidSampleCount": invalid,
            "rejectionReasons": reason_ids,
            "minimumOrebodyDistance": validation.get("minimumOrebodyDistance"),
            "minimumCover": validation.get("minimumCover"),
        },
        LAYOUT_V2_ARTIFACT,
        field,
    )


def _no_capability(
    check_id: str, title: str, category: str, authority: AssessmentAuthority, source_field: str
) -> AssessmentCheck:
    return _check(
        check_id,
        title,
        category,
        authority,
        NOT_EVALUATED,
        f"not evaluated: {CAPABILITY_GRAPH_ARTIFACT} is not generated",
        {},
        CAPABILITY_GRAPH_ARTIFACT,
        source_field,
    )


def _check_capability_valid(capability: CapabilityGraphPayload | None) -> AssessmentCheck:
    title = "Capability graph valid"
    if capability is None:
        return _no_capability(
            "CAPABILITY_GRAPH_VALID", title, "CAPABILITY", "DERIVED_VALIDATION", "validation"
        )
    validation = capability.validation
    valid = capability.status == "SUCCESS" and validation is not None and validation.valid
    failure = capability.failure_reason if validation is None else validation.failure_reason
    return _check(
        "CAPABILITY_GRAPH_VALID",
        title,
        "CAPABILITY",
        "DERIVED_VALIDATION",
        SATISFIED if valid else NOT_SATISFIED,
        f"capability graph {capability.status}, validation "
        + ("valid" if valid else f"invalid ({failure})"),
        {
            "status": capability.status,
            "valid": valid,
            "failureReason": failure,
            "networkRevision": capability.network_revision,
        },
        CAPABILITY_GRAPH_ARTIFACT,
        "validation",
    )


def _required_paths(capability: CapabilityGraphPayload) -> list[RequiredPathProjection]:
    return [
        RequiredPathProjection(
            id=p.id,
            capability=p.capability,
            source_node_id=p.source_node_id,
            target_node_id=p.target_node_id,
            rule=p.rule,
            physical_reachable=p.physical_reachable,
            capability_reachable=p.capability_reachable,
            satisfied=p.satisfied,
        )
        for p in capability.required_paths
    ]


def _check_required_paths(capability: CapabilityGraphPayload | None) -> AssessmentCheck:
    title = "Required capability paths"
    if capability is None:
        return _no_capability(
            "REQUIRED_CAPABILITY_PATHS", title, "CAPABILITY", "DERIVED_VALIDATION", "requiredPaths"
        )
    paths = capability.required_paths
    satisfied = [p.id for p in paths if p.satisfied]
    unsatisfied = [p.id for p in paths if not p.satisfied]
    physical_only = [p.id for p in paths if p.physical_reachable and not p.capability_reachable]
    return _check(
        "REQUIRED_CAPABILITY_PATHS",
        title,
        "CAPABILITY",
        "DERIVED_VALIDATION",
        SATISFIED if not unsatisfied else NOT_SATISFIED,
        f"{len(satisfied)} / {len(paths)} required capability paths satisfied"
        + (f"; unsatisfied: {', '.join(unsatisfied)}" if unsatisfied else ""),
        {
            "requiredPathCount": len(paths),
            "satisfiedPathCount": len(satisfied),
            "unsatisfiedPathIds": unsatisfied,
            "physicalOnlyPathIds": physical_only,
        },
        CAPABILITY_GRAPH_ARTIFACT,
        "requiredPaths",
    )


def _egress_projection(capability: CapabilityGraphPayload) -> EgressAdvisoryProjection | None:
    advisory = capability.egress_advisory
    if advisory is None:
        return None
    failing = [e.node_id for e in advisory.per_node if not e.meets_criterion]
    routes = [e.independent_egress_routes for e in advisory.per_node]
    return EgressAdvisoryProjection(
        criterion=advisory.criterion,
        required_routes=advisory.required_routes,
        advisory_only=advisory.advisory_only,
        surface_node_ids=list(advisory.surface_node_ids),
        underground_node_count=len(advisory.per_node),
        meeting_node_count=len(advisory.per_node) - len(failing),
        failing_node_count=len(failing),
        failing_node_ids=failing,
        minimum_independent_routes=min(routes) if routes else None,
    )


def _check_egress(capability: CapabilityGraphPayload | None) -> AssessmentCheck:
    title = "Dual-egress design advisory"
    if capability is None:
        return _no_capability("DUAL_EGRESS_ADVISORY", title, "EGRESS", "ADVISORY", "egressAdvisory")
    egress = _egress_projection(capability)
    if egress is None:
        return _check(
            "DUAL_EGRESS_ADVISORY",
            title,
            "EGRESS",
            "ADVISORY",
            NOT_EVALUATED,
            f"not evaluated: {CAPABILITY_GRAPH_ARTIFACT} carries no egress advisory",
            {},
            CAPABILITY_GRAPH_ARTIFACT,
            "egressAdvisory",
        )
    return _check(
        "DUAL_EGRESS_ADVISORY",
        title,
        "EGRESS",
        "ADVISORY",
        SATISFIED if egress.failing_node_count == 0 else NOT_SATISFIED,
        f"{egress.meeting_node_count} / {egress.underground_node_count} underground nodes meet the "
        f"{egress.required_routes}-route design criterion. {_ADVISORY_DISCLAIMER}",
        {
            "requiredRoutes": egress.required_routes,
            "surfaceNodeIds": egress.surface_node_ids,
            "undergroundNodeCount": egress.underground_node_count,
            "meetingNodeCount": egress.meeting_node_count,
            "failingNodeCount": egress.failing_node_count,
            "failingNodeIds": egress.failing_node_ids,
            "minimumIndependentRoutes": egress.minimum_independent_routes,
            "advisoryOnly": egress.advisory_only,
        },
        CAPABILITY_GRAPH_ARTIFACT,
        "egressAdvisory",
    )


# --------------------------------------------------------------------------- #
# templated summary (directive §14) — fixed sentences over recorded numbers
# --------------------------------------------------------------------------- #


def _summary(
    catalogue: dict[str, Any] | None,
    ranking: list[str],
    by_id: dict[str, dict[str, Any]],
    *,
    active_source: str,
    winner_id: str | None,
    selected_id: str | None,
    selected_cand: dict[str, Any] | None,
    egress: EgressAdvisoryProjection | None,
    capability: CapabilityGraphPayload | None,
) -> str:
    lines: list[str] = []
    feasible = len(ranking)
    if active_source == "LEGACY":
        lines.append("Active design: LEGACY (Hybrid-A*) ramp — not a layout-v2 candidate.")
        if catalogue is None:
            lines.append("Layout-v2 catalogue: none.")
        else:
            dormant = selected_id if selected_id is not None else "none"
            winner = winner_id if winner_id is not None else "none"
            lines.append(
                f"Inactive layout-v2 selection: {dormant} "
                f"(catalogue winner {winner}, {feasible} feasible)."
            )
    elif winner_id is None or not ranking:
        cat = catalogue if catalogue is not None else {}
        lines.append(
            "No feasible layout candidate: catalogue status "
            f"{cat.get('status')} ({cat.get('candidateCount')} enumerated)."
        )
    elif selected_id is None or selected_cand is None:
        who = (
            "No layout candidate is selected"
            if selected_id is None
            else (f"Selected {selected_id} is not in the catalogue")
        )
        lines.append(f"{who}. Ranking winner: {winner_id} (rank 1 of {feasible} feasible).")
    else:
        rank = selected_cand.get("rank")
        lines.append(
            f"Selected {selected_id} ({selected_cand.get('family')}). "
            f"Rank: {'—' if rank is None else rank} of {feasible} feasible. "
            f"Status: {selected_cand.get('status')}."
        )
        other = _comparison_reference(ranking, selected_id)
        if other is not None:
            other_cand = by_id[other]
            lines.append(f"Compared with rank {other_cand.get('rank')} ({other}):")
            s_sel = selected_cand.get("scores")
            s_oth = other_cand.get("scores")
            if isinstance(s_sel, dict) and isinstance(s_oth, dict):
                delta = float(s_oth["total"]) - float(s_sel["total"])
                word = "lower" if delta >= 0 else "higher"
                lines.append(
                    f"- total score {word} by {abs(delta):.4f} (ranking is the selection authority)"
                )
            accessible = selected_cand.get("accessibleLevels")
            required = selected_cand.get("requiredLevels")
            if accessible is not None and required is not None:
                if int(accessible) == int(required):
                    lines.append(f"- all {int(required)} required levels remain accessible")
                else:
                    lines.append(
                        f"- {int(accessible)} of {int(required)} required levels accessible"
                    )
            clearance = selected_cand.get("clearance")
            if isinstance(clearance, dict):
                lines.append(
                    "- clearance validation "
                    + ("satisfied" if clearance.get("satisfied") else "NOT satisfied")
                    + f" ({clearance.get('clearanceBasis')} basis)"
                )
    if capability is None:
        lines.append(
            f"Capability checks not evaluated ({CAPABILITY_GRAPH_ARTIFACT} not generated)."
        )
    else:
        if egress is not None:
            lines.append(
                f"Dual-egress design advisory: {egress.meeting_node_count} / "
                f"{egress.underground_node_count} underground nodes meet the "
                f"{egress.required_routes}-route criterion."
            )
        paths = capability.required_paths
        n_ok = sum(1 for p in paths if p.satisfied)
        lines.append(f"Required capability paths: {n_ok} / {len(paths)} satisfied.")
    return "\n".join(lines)


def _comparison_reference(ranking: list[str], selected_id: str) -> str | None:
    """The candidate the selection is explained against: rank 2 for the
    winner, otherwise the winner (rank 1)."""
    if selected_id not in ranking:
        return None
    if ranking[0] == selected_id:
        return ranking[1] if len(ranking) > 1 else None
    return ranking[0]


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _num(value: Any) -> str:
    return "—" if value is None else f"{float(value):.2f}"
