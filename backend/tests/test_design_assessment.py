"""Phase 20D.3 — Design Assessment & Candidate Comparison (rule 189).

The assessment is a READ-ONLY projection of existing authoritative results:
``layout_v2.json`` (ranking, scores, statuses), ``layout_v2_selected.json``
(the selection), ``ramp_source.json`` (the active source) and
``capability_graph.json`` (required capability paths, egress advisory). It
never recomputes a score, re-ranks a candidate, infers a missing fact or
makes a statutory claim.

RED-first (directive §22): the pure builder is tested on a HAND-WRITTEN
catalogue whose ranking is deliberately NOT sorted by total score, so a
re-ranking projection would be caught; the service / API contract is
tested on a real world with hand-written derived documents (FAST), and the
real chain (search → activate → levels → network → capability graph →
assessment) once, in the e2e tier.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from minegen.assessment.builder import (
    DEFAULT_MAX_COMPARISON_ROWS,
    build_design_assessment,
)
from minegen.assessment.models import (
    AssessmentCheck,
    DesignAssessmentPayload,
    DesignAssessmentSources,
)
from minegen.capability.models import (
    CapabilityGraphPayload,
    CapabilityMetrics,
    CapabilityValidation,
    EgressAdvisory,
    EgressAdvisoryEntry,
    RequiredPathCheck,
)
from minegen.core.artifacts import (
    CAPABILITY_GRAPH_ARTIFACT,
    LAYOUT_V2_ARTIFACT,
    LAYOUT_V2_SELECTED_ARTIFACT,
    NETWORK_ARTIFACT,
)
from minegen.core.enums import Capability
from minegen.services.design_service import DesignService
from tests.test_layout_v2_api import _generate_layout, _winner
from tests.test_network_api import _levels, _network
from tests.test_smoothing_api import _prepare

# --------------------------------------------------------------------------- #
# hand-written authoritative documents
# --------------------------------------------------------------------------- #

WINNER = "SWITCHBACK-k1-p+20-CW-g0.120"
RANK2 = "SWITCHBACK-k1-p+0-CW-g0.120"
RANK3 = "SPIRAL-n1-CW-e+0-g0.120"
RANK4 = "SWITCHBACK-k2-p+0-CCW-g0.120"
RANK5 = "LONGITUDINAL-STRIKE_POSITIVE-FOOTWALL-g0.120"
RANK6 = "SPIRAL-n1-CCW-e+0-g0.100"
INFEASIBLE = "SWITCHBACK-k1-p+40-CW-g0.120"
NOT_VALIDATED = "LONGITUDINAL-STRIKE_NEGATIVE-FOOTWALL-g0.100"
RANKING = [WINNER, RANK2, RANK3, RANK4, RANK5, RANK6]

#: totals deliberately NOT monotone in rank (rank 3 beats rank 2 on total):
#: the assessment must reproduce the AUTHORITATIVE ranking, never re-sort
TOTALS = {
    WINNER: 4.520685616859209,
    RANK2: 4.6277,
    RANK3: 4.55,
    RANK4: 5.1,
    RANK5: 6.02,
    RANK6: 7.3,
}


def _scores(total: float) -> dict[str, Any]:
    return {
        "development": round(total * 0.4, 6),
        "geology": 0.0,
        "geometry": round(total * 0.6, 6),
        "total": total,
        "components": {"lengthRatio": 1.15, "turningFraction": 0.35},
    }


def _clearance(satisfied: bool = True) -> dict[str, Any]:
    return {
        "clearanceBasis": "EXACT",
        "requiredClearance": 10.590169943749475,
        "conservativeMinimumClearance": 19.64800649007038 if satisfied else 8.2,
        "approximateMinimumClearance": None,
        "clearanceErrorBound": None,
        "satisfied": satisfied,
        "refinement": {"applied": False, "factor": 2, "reason": "NOT_APPLICABLE_EXACT_BASIS"},
    }


def _validation(invalid: int = 0) -> dict[str, Any]:
    return {
        "sampleCount": 749,
        "invalidSampleCount": invalid,
        "rejectionReasonCounts": {} if invalid == 0 else {"OREBODY_BUFFER": invalid},
        "coverEstablished": False,
        "fieldCost": 2669.89,
        "minimumOrebodyDistance": 19.648,
        "minimumCover": 0.0,
    }


def _access(accessible: int = 4, failures: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "feasible": not failures,
        "levelCount": 4,
        "accessibleLevelCount": accessible,
        "totalAccessLength": 224.18,
        "worstAccessLength": 71.2,
        "maxAccessGradient": 0.12,
        "minAccessPlanRadius": 18.0,
        "perLevelLength": {"L01": 30.1, "L02": 41.0, "L03": 71.2, "L04": 81.9},
        "failures": failures or {},
    }


def _cand(candidate_id: str, **over: Any) -> dict[str, Any]:
    family = candidate_id.split("-", 1)[0]
    rank = RANKING.index(candidate_id) + 1 if candidate_id in RANKING else None
    base: dict[str, Any] = {
        "candidateId": candidate_id,
        "family": family,
        "parameters": {"gradient": 0.12},
        "status": "FEASIBLE",
        "stageReached": "DETAILED",
        "failureReasons": [],
        "failureDetail": None,
        "shortlisted": True,
        "rank": rank,
        "screenedLevels": 4,
        "accessibleLevels": 4,
        "requiredLevels": 4,
        "rampLevelReferences": [],
        "access": _access(),
        "levelAccesses": None,
        "diagnostics": {"length3d": 1485.86, "maxAbsGradient": 0.12, "minPlanRadius": 18.0},
        "scores": _scores(TOTALS[candidate_id]) if candidate_id in TOTALS else None,
        "clearance": _clearance(),
        "exposure": None,
        "validation": _validation(),
        "derived": {},
        "cheapProxy": 1.0,
        "accessScreen": None,
    }
    base.update(over)
    return base


def catalogue() -> dict[str, Any]:
    cands = [_cand(c) for c in RANKING]
    cands.append(
        _cand(
            INFEASIBLE,
            status="INFEASIBLE",
            failureReasons=["LEVEL_ACCESS_INFEASIBLE"],
            failureDetail="L03: GRADE_LIMIT",
            rank=None,
            scores=None,
            accessibleLevels=3,
            access=_access(3, {"L03": {"reason": "GRADE_LIMIT"}}),
        )
    )
    cands.append(
        _cand(
            NOT_VALIDATED,
            status="NOT_VALIDATED",
            stageReached="CHEAP",
            shortlisted=False,
            rank=None,
            scores=None,
            accessibleLevels=None,
            access=None,
            clearance=None,
            validation=None,
        )
    )
    return {
        "layoutVersion": 2,
        "status": "SUCCESS",
        "portal": [10.0, 20.0, 305.0],
        "requiredLevels": [
            {
                "levelId": f"L0{i}",
                "index": i - 1,
                "elevation": 300 - 25 * i,
                "hasOrebodySection": True,
            }
            for i in range(1, 5)
        ],
        "serviceableLevelCount": 4,
        "candidateCount": len(cands),
        "feasibleCount": len(RANKING),
        "shortlist": [*RANKING, INFEASIBLE],
        "ranking": list(RANKING),
        "winnerId": WINNER,
        "clearanceBasis": "EXACT",
        "clearanceErrorBound": 0.0,
        "requiredClearance": 10.590169943749475,
        "accessReach": 60.0,
        "footwallStandoff": 50.0,
        "performance": {"totalSeconds": 4.2},
        "searchConfig": {},
        "candidates": cands,
    }


def selection(candidate_id: str = WINNER) -> dict[str, Any]:
    return {
        "status": "SUCCESS",
        "sourceKind": "PARAMETRIC_V2",
        "sourceRevision": "48fba70cf648cb20",
        "candidateId": candidate_id,
        "family": candidate_id.split("-", 1)[0],
        "failureReason": None,
        "segments": [],
        "layoutRevision": "884dde85ed89a762",
        "owningArtifact": LAYOUT_V2_SELECTED_ARTIFACT,
    }


UNDERGROUND = ("L01:ENTRY", "L02:ENTRY", "L03:ENTRY", "L04:ENTRY", "RAMP_END")


def capability_graph(
    *, network_revision: str = "netrev", network_source_revision: str = "src-net"
) -> CapabilityGraphPayload:
    routes = {"L01:ENTRY": 2, "L02:ENTRY": 2, "L03:ENTRY": 1, "L04:ENTRY": 2, "RAMP_END": 1}
    return CapabilityGraphPayload(
        status="SUCCESS",
        failure_reason=None,
        source_revision="capsrc",
        network_revision=network_revision,
        network_source_revision=network_source_revision,
        capabilities=list(Capability),
        nodes=[],
        edges=[],
        surface_node_ids=["PORTAL", "S1:COLLAR"],
        required_paths=[
            RequiredPathCheck(
                id="PERSONNEL_ACCESS:PORTAL->L01:ENTRY",
                capability=Capability.PERSONNEL_ACCESS,
                source_node_id="PORTAL",
                target_node_id="L01:ENTRY",
                rule="PORTAL_TO_LEVEL_ENTRY",
                physical_reachable=True,
                capability_reachable=True,
                path_edge_ids=["RAMP:0", "ACCESS:L01"],
                satisfied=True,
            ),
            # rule 185: a PHYSICAL path exists while the capability path does not
            RequiredPathCheck(
                id="MATERIAL_HAULAGE:S1:COLLAR->S1:L02",
                capability=Capability.MATERIAL_HAULAGE,
                source_node_id="S1:COLLAR",
                target_node_id="S1:L02",
                rule="COLLAR_TO_STATION",
                physical_reachable=True,
                capability_reachable=False,
                path_edge_ids=None,
                satisfied=False,
            ),
            RequiredPathCheck(
                id="EMERGENCY_EGRESS:L04:ENTRY->SURFACE",
                capability=Capability.EMERGENCY_EGRESS,
                source_node_id="L04:ENTRY",
                target_node_id="PORTAL",
                rule="EGRESS_ROUTE",
                physical_reachable=True,
                capability_reachable=True,
                path_edge_ids=["ACCESS:L04", "RAMP:3"],
                satisfied=True,
            ),
        ],
        egress_advisory=EgressAdvisory(
            criterion="edge-disjoint EMERGENCY_EGRESS routes to any surface node",
            required_routes=2,
            advisory_only=True,
            surface_node_ids=["PORTAL", "S1:COLLAR"],
            per_node=[
                EgressAdvisoryEntry(
                    node_id=n,
                    level_id=n.split(":")[0] if n.startswith("L") else None,
                    independent_egress_routes=routes[n],
                    meets_criterion=routes[n] >= 2,
                )
                for n in UNDERGROUND
            ],
        ),
        validation=CapabilityValidation(
            referenced_nodes_exist=True,
            referenced_edges_exist=True,
            no_duplicate_node_ids=True,
            no_duplicate_edge_ids=True,
            network_revision_matches=True,
            required_paths_satisfied=False,
            valid=True,
            failure_reason=None,
        ),
        metrics=CapabilityMetrics(
            node_count=7,
            edge_count=9,
            surface_node_count=2,
            edges_per_capability={},
            required_path_count=3,
            required_paths_satisfied_count=2,
            build_seconds=0.01,
        ),
    )


def sources(**over: Any) -> DesignAssessmentSources:
    base: dict[str, Any] = {
        "active_source": "LAYOUT_V2",
        "layout_v2_revision": "884dde85ed89a762",
        "selected_layout_revision": "48fba70cf648cb20",
        "level_accesses_revision": "aaaa000011112222",
        "network_revision": "netrev",
        "capability_graph_revision": "caprev",
    }
    base.update(over)
    return DesignAssessmentSources(**base)


def build(
    cat: dict[str, Any] | None = None,
    sel: dict[str, Any] | None = None,
    cap: CapabilityGraphPayload | None = None,
    *,
    active_source: str = "LAYOUT_V2",
    max_rows: int = DEFAULT_MAX_COMPARISON_ROWS,
) -> DesignAssessmentPayload:
    return build_design_assessment(
        catalogue=catalogue() if cat is None else cat,
        selected=sel,
        capability=cap,
        sources=sources(
            active_source=active_source,
            selected_layout_revision=None if sel is None else "48fba70cf648cb20",
            capability_graph_revision=None if cap is None else "caprev",
        ),
        max_comparison_rows=max_rows,
    )


def check(payload: DesignAssessmentPayload, check_id: str) -> AssessmentCheck:
    found = [c for c in payload.checks if c.id == check_id]
    assert len(found) == 1, (check_id, [c.id for c in payload.checks])
    return found[0]


# --------------------------------------------------------------------------- #
# T1 — winner projection, never a recomputation
# --------------------------------------------------------------------------- #


def test_t1_selected_and_winner_are_projected_from_the_authoritative_artifacts() -> None:
    payload = build(sel=selection(WINNER), cap=capability_graph())
    assert payload.status == "SUCCESS"
    assert payload.winner_id == WINNER
    assert payload.selected_candidate_id == WINNER
    assert payload.selected_candidate is not None
    assert payload.selected_candidate.candidate_id == WINNER
    assert payload.selected_candidate.rank == 1
    assert payload.selected_candidate.selected and payload.selected_candidate.winner
    assert check(payload, "SELECTED_IS_RANKING_WINNER").status == "SATISFIED"
    # the row is the catalogue row: same rank, same status, same stage
    row = payload.candidate_comparison[0]
    assert (row.candidate_id, row.rank, row.status, row.stage_reached) == (
        WINNER,
        1,
        "FEASIBLE",
        "DETAILED",
    )


def test_t1_a_non_winner_selection_is_reported_not_re_ranked() -> None:
    payload = build(sel=selection(RANK3), cap=capability_graph())
    assert payload.winner_id == WINNER  # the ranking authority is untouched
    assert payload.selected_candidate_id == RANK3
    assert payload.selected_candidate is not None and payload.selected_candidate.rank == 3
    assert check(payload, "SELECTED_IS_RANKING_WINNER").status == "NOT_SATISFIED"
    ids = [r.candidate_id for r in payload.candidate_comparison]
    assert ids == RANKING[:DEFAULT_MAX_COMPARISON_ROWS]
    assert [r.selected for r in payload.candidate_comparison] == [False, False, True, False, False]
    assert [r.winner for r in payload.candidate_comparison] == [True, False, False, False, False]


# --------------------------------------------------------------------------- #
# T2 — comparison order is the authoritative ranking (not the score)
# --------------------------------------------------------------------------- #


def test_t2_comparison_follows_the_stored_ranking_even_where_totals_disagree() -> None:
    assert TOTALS[RANK3] < TOTALS[RANK2]  # the trap: sorting by total would swap them
    payload = build(sel=selection(WINNER))
    ids = [r.candidate_id for r in payload.candidate_comparison]
    assert ids == RANKING[:DEFAULT_MAX_COMPARISON_ROWS]
    assert [r.rank for r in payload.candidate_comparison] == [1, 2, 3, 4, 5]
    assert DEFAULT_MAX_COMPARISON_ROWS == 5


def test_t2_winner_and_selection_are_always_rows_and_the_bound_is_respected() -> None:
    # selection outside the top rows: it is appended in ranking order, the
    # winner keeps its row and nothing is re-sorted
    payload = build(sel=selection(RANK6))
    ids = [r.candidate_id for r in payload.candidate_comparison]
    assert ids == [*RANKING[:5], RANK6]
    payload = build(sel=selection(WINNER), max_rows=1)
    assert [r.candidate_id for r in payload.candidate_comparison] == [WINNER]
    payload = build(sel=selection(RANK2), max_rows=1)
    assert [r.candidate_id for r in payload.candidate_comparison] == [WINNER, RANK2]


# --------------------------------------------------------------------------- #
# T3 — FEASIBLE / INFEASIBLE / NOT_VALIDATED are never confused
# --------------------------------------------------------------------------- #


def test_t3_only_feasible_ranked_candidates_are_alternatives() -> None:
    payload = build(sel=selection(WINNER))
    statuses = {r.status for r in payload.candidate_comparison}
    assert statuses == {"FEASIBLE"}
    ids = {r.candidate_id for r in payload.candidate_comparison}
    assert INFEASIBLE not in ids and NOT_VALIDATED not in ids
    assert all(r.rank is not None for r in payload.candidate_comparison)


def test_t3_a_ranking_entry_that_is_not_feasible_is_refused_not_shown() -> None:
    # a catalogue whose ranking names a NOT_VALIDATED candidate is internally
    # inconsistent: the projection must not present it as a feasible
    # alternative (and must not silently drop the inconsistency either)
    cat = catalogue()
    cat["ranking"] = [WINNER, NOT_VALIDATED]
    with pytest.raises(ValueError, match="NOT_VALIDATED"):
        build(cat=cat, sel=selection(WINNER))


def test_t3_selected_status_is_projected_verbatim() -> None:
    cat = catalogue()
    for cid, status in ((INFEASIBLE, "INFEASIBLE"), (NOT_VALIDATED, "NOT_VALIDATED")):
        payload = build(cat=cat, sel=selection(cid))
        assert payload.selected_candidate is not None
        assert payload.selected_candidate.status == status
        feasible = check(payload, "CANDIDATE_FEASIBLE")
        assert feasible.status == "NOT_SATISFIED"
        assert feasible.evidence["status"] == status
        assert cid not in {r.candidate_id for r in payload.candidate_comparison}
    # a NOT_VALIDATED selection has no validation / clearance fields: the
    # dependent checks are NOT_EVALUATED, never inferred
    payload = build(cat=cat, sel=selection(NOT_VALIDATED))
    assert check(payload, "CLEARANCE_VALIDATED").status == "NOT_EVALUATED"
    assert check(payload, "GEOMETRY_VALIDATED").status == "NOT_EVALUATED"
    assert check(payload, "ALL_REQUIRED_LEVELS_ACCESSIBLE").status == "NOT_EVALUATED"


# --------------------------------------------------------------------------- #
# T4 — score identity and subtraction-only deltas
# --------------------------------------------------------------------------- #


def test_t4_scores_are_the_catalogue_scores_and_deltas_are_plain_subtraction() -> None:
    cat = catalogue()
    payload = build(cat=cat, sel=selection(WINNER))
    by_id = {c["candidateId"]: c for c in cat["candidates"]}
    winner_scores = by_id[WINNER]["scores"]
    for row in payload.candidate_comparison:
        cand = by_id[row.candidate_id]
        src = cand["scores"]
        assert row.scores is not None and row.deltas is not None
        assert row.scores.total == src["total"]
        assert row.scores.development == src["development"]
        assert row.scores.geology == src["geology"]
        assert row.scores.geometry == src["geometry"]
        assert row.deltas.total_score_delta_from_winner == src["total"] - winner_scores["total"]
        assert row.deltas.development_score_delta == (
            src["development"] - winner_scores["development"]
        )
        assert row.deltas.geology_score_delta == src["geology"] - winner_scores["geology"]
        assert row.deltas.geometry_score_delta == src["geometry"] - winner_scores["geometry"]
        assert row.accessible_levels == cand["accessibleLevels"]
        assert row.required_levels == cand["requiredLevels"]
        assert row.failure_reasons == cand["failureReasons"]
    winner_row = payload.candidate_comparison[0]
    assert winner_row.deltas is not None
    assert winner_row.deltas.total_score_delta_from_winner == 0.0


def test_t4_the_catalogue_is_not_mutated_by_the_projection() -> None:
    cat = catalogue()
    frozen = json.dumps(cat, sort_keys=True)
    build(cat=cat, sel=selection(RANK2), cap=capability_graph())
    assert json.dumps(cat, sort_keys=True) == frozen


# --------------------------------------------------------------------------- #
# T5 / T6 — dual-egress advisory: a projection, and only an advisory
# --------------------------------------------------------------------------- #


def test_t5_egress_projection_matches_the_capability_graph() -> None:
    cap = capability_graph()
    payload = build(sel=selection(WINNER), cap=cap)
    assert cap.egress_advisory is not None
    per_node = cap.egress_advisory.per_node
    failing = [e.node_id for e in per_node if not e.meets_criterion]
    adv = check(payload, "DUAL_EGRESS_ADVISORY")
    assert adv.status == "NOT_SATISFIED"  # 3 / 5 meet the criterion
    assert adv.evidence["requiredRoutes"] == 2
    assert adv.evidence["undergroundNodeCount"] == len(per_node)
    assert adv.evidence["meetingNodeCount"] == len(per_node) - len(failing)
    assert adv.evidence["failingNodeCount"] == len(failing)
    assert adv.evidence["failingNodeIds"] == failing
    assert adv.evidence["surfaceNodeIds"] == cap.egress_advisory.surface_node_ids
    assert adv.evidence["minimumIndependentRoutes"] == min(
        e.independent_egress_routes for e in per_node
    )
    assert adv.source_artifact == CAPABILITY_GRAPH_ARTIFACT
    assert adv.source_field == "egressAdvisory"
    assert payload.egress_advisory is not None
    assert payload.egress_advisory.failing_node_ids == failing
    assert payload.egress_advisory.required_routes == 2
    assert payload.egress_advisory.advisory_only is True
    assert "3 / 5" in adv.summary and "design advisory" in adv.summary


def test_t5_egress_advisory_is_satisfied_only_when_no_node_fails() -> None:
    cap = capability_graph()
    assert cap.egress_advisory is not None
    for entry in cap.egress_advisory.per_node:
        entry.independent_egress_routes = 2
        entry.meets_criterion = True
    payload = build(sel=selection(WINNER), cap=cap)
    adv = check(payload, "DUAL_EGRESS_ADVISORY")
    assert adv.status == "SATISFIED" and adv.evidence["failingNodeIds"] == []


FORBIDDEN = re.compile(
    r"LEGAL(LY)?[ _]COMPLIANT|REGULATOR(Y|ILY)[ _]COMPLIANT|STATUTORY[ _]COMPLIANCE[ _]CERTIFIED"
    r"|\bUNSAFE\b|\bSAFE\b|\bCERTIFIED\b",
    re.IGNORECASE,
)


def test_t6_the_advisory_carries_the_advisory_authority_and_no_statutory_claim() -> None:
    payload = build(sel=selection(WINNER), cap=capability_graph())
    adv = check(payload, "DUAL_EGRESS_ADVISORY")
    assert adv.authority == "ADVISORY"
    assert "not a statutory compliance determination" in adv.summary
    text = json.dumps(payload.model_dump(mode="json", by_alias=True))
    assert FORBIDDEN.search(text) is None, FORBIDDEN.search(text)
    keys: set[str] = set()

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                keys.add(str(k))
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(payload.model_dump(mode="json", by_alias=True))
    assert not {k for k in keys if re.search(r"statutory|legal|complian|regulator", k, re.I)}
    # every check names its authority from the closed set
    assert {c.authority for c in payload.checks} <= {
        "HARD_DESIGN_RULE",
        "DERIVED_VALIDATION",
        "ADVISORY",
        "INFORMATIONAL",
    }
    # hard-rule checks and the advisory are distinguishable by authority
    assert check(payload, "CANDIDATE_FEASIBLE").authority == "HARD_DESIGN_RULE"
    assert check(payload, "ALL_REQUIRED_LEVELS_ACCESSIBLE").authority == "HARD_DESIGN_RULE"
    assert check(payload, "CLEARANCE_VALIDATED").authority == "HARD_DESIGN_RULE"
    assert check(payload, "GEOMETRY_VALIDATED").authority == "DERIVED_VALIDATION"
    assert check(payload, "REQUIRED_CAPABILITY_PATHS").authority == "DERIVED_VALIDATION"


# --------------------------------------------------------------------------- #
# T7 — missing capability graph is NOT_EVALUATED, never a pass
# --------------------------------------------------------------------------- #


def test_t7_missing_capability_graph_is_not_evaluated() -> None:
    payload = build(sel=selection(WINNER), cap=None)
    for cid in ("DUAL_EGRESS_ADVISORY", "REQUIRED_CAPABILITY_PATHS", "CAPABILITY_GRAPH_VALID"):
        c = check(payload, cid)
        assert c.status == "NOT_EVALUATED", cid
        assert c.evidence == {}
        assert CAPABILITY_GRAPH_ARTIFACT in c.summary
    assert payload.egress_advisory is None
    assert payload.required_paths == []
    assert payload.sources.capability_graph_revision is None
    # the layout half is unaffected
    assert check(payload, "CANDIDATE_FEASIBLE").status == "SATISFIED"
    assert check(payload, "ALL_REQUIRED_LEVELS_ACCESSIBLE").status == "SATISFIED"
    assert check(payload, "CLEARANCE_VALIDATED").status == "SATISFIED"
    assert check(payload, "GEOMETRY_VALIDATED").status == "SATISFIED"


def test_t7_missing_selection_is_not_satisfied_and_dependents_are_not_evaluated() -> None:
    payload = build(sel=None, cap=capability_graph())
    assert payload.selected_candidate_id is None and payload.selected_candidate is None
    assert check(payload, "LAYOUT_SELECTED").status == "NOT_SATISFIED"
    for cid in (
        "CANDIDATE_FEASIBLE",
        "ALL_REQUIRED_LEVELS_ACCESSIBLE",
        "CLEARANCE_VALIDATED",
        "GEOMETRY_VALIDATED",
        "SELECTED_IS_RANKING_WINNER",
    ):
        assert check(payload, cid).status == "NOT_EVALUATED", cid
    # the comparison still exists (winner first) — it is a catalogue fact
    assert [r.candidate_id for r in payload.candidate_comparison] == RANKING[:5]
    assert payload.summary.startswith("No layout candidate is selected")


# --------------------------------------------------------------------------- #
# T9 — required paths keep physical and capability reachability apart
# --------------------------------------------------------------------------- #


def test_t9_required_paths_are_projected_with_both_reachabilities() -> None:
    cap = capability_graph()
    payload = build(sel=selection(WINNER), cap=cap)
    assert [p.id for p in payload.required_paths] == [p.id for p in cap.required_paths]
    for got, src in zip(payload.required_paths, cap.required_paths, strict=True):
        assert got.physical_reachable == src.physical_reachable
        assert got.capability_reachable == src.capability_reachable
        assert got.satisfied == src.satisfied
        assert got.capability == src.capability
        assert (got.source_node_id, got.target_node_id, got.rule) == (
            src.source_node_id,
            src.target_node_id,
            src.rule,
        )
    physical_only = payload.required_paths[1]
    assert physical_only.physical_reachable and not physical_only.capability_reachable
    assert not physical_only.satisfied
    c = check(payload, "REQUIRED_CAPABILITY_PATHS")
    assert c.status == "NOT_SATISFIED"
    assert c.evidence["requiredPathCount"] == 3
    assert c.evidence["satisfiedPathCount"] == 2
    assert c.evidence["unsatisfiedPathIds"] == [physical_only.id]
    assert c.evidence["physicalOnlyPathIds"] == [physical_only.id]
    assert "2 / 3" in c.summary


# --------------------------------------------------------------------------- #
# checks on the selected layout — only where a field proves it
# --------------------------------------------------------------------------- #


def test_layout_checks_read_the_selected_candidate_fields_verbatim() -> None:
    cat = catalogue()
    payload = build(cat=cat, sel=selection(WINNER))
    sel = check(payload, "LAYOUT_SELECTED")
    assert sel.status == "SATISFIED"
    assert sel.evidence == {"candidateId": WINNER, "layoutRevision": "884dde85ed89a762"}
    assert sel.source_artifact == LAYOUT_V2_SELECTED_ARTIFACT
    feasible = check(payload, "CANDIDATE_FEASIBLE")
    assert feasible.evidence == {
        "status": "FEASIBLE",
        "stageReached": "DETAILED",
        "rank": 1,
        "failureReasons": [],
    }
    assert feasible.source_artifact == LAYOUT_V2_ARTIFACT
    assert feasible.source_field == "candidates[].status"
    levels = check(payload, "ALL_REQUIRED_LEVELS_ACCESSIBLE")
    assert levels.status == "SATISFIED"
    assert levels.evidence == {"accessibleLevels": 4, "requiredLevels": 4, "unservedLevelIds": []}
    clearance = check(payload, "CLEARANCE_VALIDATED")
    assert clearance.status == "SATISFIED"
    assert clearance.evidence["clearanceBasis"] == "EXACT"
    assert clearance.evidence["requiredClearance"] == 10.590169943749475
    assert clearance.evidence["conservativeMinimumClearance"] == 19.64800649007038
    assert clearance.evidence["clearanceErrorBound"] is None
    geometry = check(payload, "GEOMETRY_VALIDATED")
    assert geometry.status == "SATISFIED"
    assert geometry.evidence["sampleCount"] == 749
    assert geometry.evidence["invalidSampleCount"] == 0
    assert geometry.evidence["rejectionReasons"] == []


def test_layout_checks_fail_on_the_recorded_fields_not_on_inference() -> None:
    cat = catalogue()
    by_id = {c["candidateId"]: c for c in cat["candidates"]}
    payload = build(cat=cat, sel=selection(INFEASIBLE))
    levels = check(payload, "ALL_REQUIRED_LEVELS_ACCESSIBLE")
    assert levels.status == "NOT_SATISFIED"
    assert levels.evidence == {
        "accessibleLevels": 3,
        "requiredLevels": 4,
        "unservedLevelIds": ["L03"],
    }
    by_id[WINNER]["clearance"] = _clearance(satisfied=False)
    by_id[WINNER]["validation"] = _validation(invalid=3)
    payload = build(cat=cat, sel=selection(WINNER))
    assert check(payload, "CLEARANCE_VALIDATED").status == "NOT_SATISFIED"
    geometry = check(payload, "GEOMETRY_VALIDATED")
    assert geometry.status == "NOT_SATISFIED"
    assert geometry.evidence["invalidSampleCount"] == 3
    assert geometry.evidence["rejectionReasons"] == ["OREBODY_BUFFER"]
    # a selection naming a candidate the catalogue does not carry is reported
    # (LAYOUT_SELECTED stays a fact about the selection artifact), never
    # completed from another row
    payload = build(cat=cat, sel=selection("SPIRAL-n9-CW-e+0-g0.120"))
    assert payload.selected_candidate_id == "SPIRAL-n9-CW-e+0-g0.120"
    assert payload.selected_candidate is None
    assert check(payload, "LAYOUT_SELECTED").status == "SATISFIED"
    assert check(payload, "CANDIDATE_FEASIBLE").status == "NOT_EVALUATED"
    assert "not in the catalogue" in check(payload, "CANDIDATE_FEASIBLE").summary


def test_active_source_is_an_informational_check() -> None:
    payload = build(sel=selection(WINNER), active_source="LEGACY")
    c = check(payload, "ACTIVE_RAMP_SOURCE")
    assert c.authority == "INFORMATIONAL"
    assert c.status == "NOT_SATISFIED"
    assert c.evidence == {
        "activeSource": "LEGACY",
        "selectedCandidateId": WINNER,
        "inactiveLayoutSelectionId": WINNER,
    }
    assert c.scope == "ACTIVE_DESIGN"  # a fact about the active design itself
    assert payload.active_source == "LEGACY"
    payload = build(sel=selection(WINNER), active_source="LAYOUT_V2")
    c = check(payload, "ACTIVE_RAMP_SOURCE")
    assert c.status == "SATISFIED" and c.evidence["inactiveLayoutSelectionId"] is None


def test_capability_graph_validity_check_reads_the_recorded_validation() -> None:
    cap = capability_graph()
    payload = build(sel=selection(WINNER), cap=cap)
    c = check(payload, "CAPABILITY_GRAPH_VALID")
    assert c.status == "SATISFIED" and c.authority == "DERIVED_VALIDATION"
    assert c.evidence["status"] == "SUCCESS" and c.evidence["valid"] is True
    assert cap.validation is not None
    cap.validation.valid = False
    cap.validation.failure_reason = "REQUIRED_PATH_UNSATISFIED"
    payload = build(sel=selection(WINNER), cap=cap)
    c = check(payload, "CAPABILITY_GRAPH_VALID")
    assert c.status == "NOT_SATISFIED"
    assert c.evidence["failureReason"] == "REQUIRED_PATH_UNSATISFIED"


# --------------------------------------------------------------------------- #
# summary template and determinism
# --------------------------------------------------------------------------- #


def test_summary_is_a_deterministic_template_over_existing_numbers() -> None:
    a = build(sel=selection(WINNER), cap=capability_graph())
    b = build(sel=selection(WINNER), cap=capability_graph())
    assert a.model_dump(mode="json", by_alias=True) == b.model_dump(mode="json", by_alias=True)
    lines = a.summary.splitlines()
    assert lines[0] == f"Selected {WINNER} (SWITCHBACK). Rank: 1 of 6 feasible. Status: FEASIBLE."
    assert lines[1] == f"Compared with rank 2 ({RANK2}):"
    delta = TOTALS[RANK2] - TOTALS[WINNER]
    assert lines[2] == f"- total score lower by {delta:.4f} (ranking is the selection authority)"
    assert lines[3] == "- all 4 required levels remain accessible"
    assert lines[4] == "- clearance validation satisfied (EXACT basis)"
    assert (
        lines[5]
        == "Dual-egress design advisory: 3 / 5 underground nodes meet the 2-route criterion."
    )
    assert lines[6] == "Required capability paths: 2 / 3 satisfied."
    # every check id is unique and the order is fixed
    ids = [c.id for c in a.checks]
    assert len(ids) == len(set(ids))
    assert ids == [
        "LAYOUT_SELECTED",
        "ACTIVE_RAMP_SOURCE",
        "SELECTED_IS_RANKING_WINNER",
        "CANDIDATE_FEASIBLE",
        "ALL_REQUIRED_LEVELS_ACCESSIBLE",
        "CLEARANCE_VALIDATED",
        "GEOMETRY_VALIDATED",
        "CAPABILITY_GRAPH_VALID",
        "REQUIRED_CAPABILITY_PATHS",
        "DUAL_EGRESS_ADVISORY",
    ]


def test_no_feasible_candidate_catalogue_projects_an_empty_comparison() -> None:
    cat = catalogue()
    cat["status"] = "NO_FEASIBLE_CANDIDATE"
    cat["ranking"] = []
    cat["winnerId"] = None
    cat["feasibleCount"] = 0
    for c in cat["candidates"]:
        c["status"] = "INFEASIBLE" if c["status"] == "FEASIBLE" else c["status"]
        c["rank"] = None
        c["scores"] = None
    payload = build(cat=cat, sel=None, cap=None)
    assert payload.winner_id is None
    assert payload.candidate_comparison == []
    assert payload.summary.startswith("No feasible layout candidate")


# --------------------------------------------------------------------------- #
# service / API — validated read, fail-closed, no new persisted artifact
# --------------------------------------------------------------------------- #


def _rev(path: Path) -> str:
    """Independent revision oracle (tests/test_artifact_reader.py §29)."""
    st = os.stat(path)
    return hashlib.sha256(f"{path.name}:{st.st_size}:{st.st_mtime_ns}".encode()).hexdigest()[:16]


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _network_doc() -> dict[str, Any]:
    return {
        "status": "SUCCESS",
        "failureReason": None,
        "sourceRevision": "src-net",
        "nodes": [],
        "edges": [],
        "metrics": None,
        "validation": None,
        "surfacePathAdvisory": [],
    }


def _stack(
    client: TestClient, design_service: DesignService, *, with_capability: bool = True
) -> str:
    sid = _prepare(client)
    derived = design_service.store.derived_dir(sid)
    _write(derived / LAYOUT_V2_ARTIFACT, catalogue())
    _write(derived / NETWORK_ARTIFACT, _network_doc())
    if with_capability:
        cap = capability_graph(network_revision=_rev(derived / NETWORK_ARTIFACT))
        _write(derived / CAPABILITY_GRAPH_ARTIFACT, cap.model_dump(mode="json", by_alias=True))
    return sid


def test_api_assessment_without_any_design_is_a_legacy_none_assessment(
    client: TestClient, design_service: DesignService
) -> None:
    # a fresh world under the rule-150 LEGACY default: no catalogue, no
    # network, no capability graph → 200 with nothing evaluated, nothing
    # written (PR #43 correction: LAYOUT_V2_NOT_GENERATED only when the
    # catalogue IS the active design — test_r1_api_layout_v2_active_…)
    sid = _prepare(client)
    derived = design_service.store.derived_dir(sid)
    before = sorted(p.name for p in derived.iterdir())
    r = client.get(f"/api/v1/scenarios/{sid}/design/assessment")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["activeSource"] == "LEGACY" and body["layoutScope"] == "NONE"
    assert body["candidateComparison"] == [] and body["winnerId"] is None
    statuses = {c["id"]: c["status"] for c in body["checks"]}
    assert all(statuses[c] == "NOT_APPLICABLE" for c in LAYOUT_CHECKS)
    assert all(statuses[c] == "NOT_EVALUATED" for c in CAPABILITY_CHECKS)
    assert sorted(p.name for p in derived.iterdir()) == before
    r = client.get("/api/v1/scenarios/nope/design/assessment")
    assert r.status_code == 404


def test_api_assessment_is_a_read_model_over_the_validated_snapshot(
    client: TestClient, design_service: DesignService
) -> None:
    sid = _stack(client, design_service)
    derived = design_service.store.derived_dir(sid)
    before = sorted(p.name for p in derived.iterdir())
    r = client.get(f"/api/v1/scenarios/{sid}/design/assessment")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "SUCCESS"
    assert body["activeSource"] == "LEGACY"  # ramp_source.json absent → rule 150 default
    assert body["winnerId"] == WINNER
    assert body["selectedCandidateId"] is None
    assert [row["candidateId"] for row in body["candidateComparison"]] == RANKING[:5]
    checks = {c["id"]: c for c in body["checks"]}
    assert checks["LAYOUT_SELECTED"]["status"] == "NOT_SATISFIED"
    assert checks["DUAL_EGRESS_ADVISORY"]["status"] == "NOT_SATISFIED"
    assert checks["DUAL_EGRESS_ADVISORY"]["authority"] == "ADVISORY"
    assert checks["REQUIRED_CAPABILITY_PATHS"]["evidence"]["satisfiedPathCount"] == 2
    assert body["sources"] == {
        "activeSource": "LEGACY",
        "layoutV2Revision": _rev(derived / LAYOUT_V2_ARTIFACT),
        "selectedLayoutRevision": None,
        "levelAccessesRevision": None,
        "networkRevision": _rev(derived / NETWORK_ARTIFACT),
        "capabilityGraphRevision": _rev(derived / CAPABILITY_GRAPH_ARTIFACT),
    }
    # §6: nothing is persisted — no design_assessment.json, no rewrite
    assert sorted(p.name for p in derived.iterdir()) == before
    assert not (derived / "design_assessment.json").exists()
    # deterministic: the same snapshot answers byte-identically
    assert client.get(f"/api/v1/scenarios/{sid}/design/assessment").json() == body


def test_api_missing_capability_graph_is_not_evaluated_not_generated(
    client: TestClient, design_service: DesignService
) -> None:
    sid = _stack(client, design_service, with_capability=False)
    derived = design_service.store.derived_dir(sid)
    r = client.get(f"/api/v1/scenarios/{sid}/design/assessment")
    assert r.status_code == 200, r.text
    checks = {c["id"]: c for c in r.json()["checks"]}
    assert checks["DUAL_EGRESS_ADVISORY"]["status"] == "NOT_EVALUATED"
    assert checks["REQUIRED_CAPABILITY_PATHS"]["status"] == "NOT_EVALUATED"
    assert r.json()["sources"]["capabilityGraphRevision"] is None
    assert not (derived / CAPABILITY_GRAPH_ARTIFACT).exists()  # never generated silently


def test_t8_stale_capability_graph_fails_closed(
    client: TestClient, design_service: DesignService
) -> None:
    sid = _stack(client, design_service)
    derived = design_service.store.derived_dir(sid)
    url = f"/api/v1/scenarios/{sid}/design/assessment"
    assert client.get(url).status_code == 200
    # the network moved on (mtime only — the Stage A recipe)
    path = derived / NETWORK_ARTIFACT
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    r = client.get(url)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "CAPABILITY_GRAPH_STALE"
    # a recorded network SOURCE revision disagreeing with the network document
    cap = capability_graph(network_revision=_rev(path), network_source_revision="other")
    _write(derived / CAPABILITY_GRAPH_ARTIFACT, cap.model_dump(mode="json", by_alias=True))
    r = client.get(url)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "CAPABILITY_GRAPH_STALE"


def test_api_stale_selection_and_malformed_catalogue_fail_closed(
    client: TestClient, design_service: DesignService
) -> None:
    sid = _stack(client, design_service)
    derived = design_service.store.derived_dir(sid)
    url = f"/api/v1/scenarios/{sid}/design/assessment"
    _write(derived / LAYOUT_V2_SELECTED_ARTIFACT, selection(WINNER))  # foreign layoutRevision
    r = client.get(url)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "LAYOUT_V2_SELECTION_STALE"
    (derived / LAYOUT_V2_SELECTED_ARTIFACT).unlink()
    (derived / LAYOUT_V2_ARTIFACT).write_text("{", encoding="utf-8")
    r = client.get(url)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ARTIFACT_MALFORMED"


# --------------------------------------------------------------------------- #
# the real chain (e2e tier, tests/conftest.py TEST_MARKERS)
# --------------------------------------------------------------------------- #


def test_e2e_assessment_projects_the_real_layout_and_capability_artifacts(
    client: TestClient, design_service: DesignService
) -> None:
    sid = _prepare(client)
    base = f"/api/v1/scenarios/{sid}"
    cat = _generate_layout(client, sid)
    winner = _winner(cat)
    r = client.post(f"{base}/design/layout-v2/activate", json={"candidateId": winner})
    assert r.status_code == 200, r.text
    assert _levels(client, sid)["status"] == "SUCCESS"
    assert _network(client, sid)["status"] == "SUCCESS"
    r = client.post(f"{base}/design/capability-graph")
    assert r.status_code == 200, r.text
    graph = r.json()

    r = client.get(f"{base}/design/assessment")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["activeSource"] == "LAYOUT_V2"
    assert body["winnerId"] == cat["winnerId"]
    assert body["selectedCandidateId"] == winner
    rows = body["candidateComparison"]
    assert [row["candidateId"] for row in rows] == cat["ranking"][:5]
    by_id = {c["candidateId"]: c for c in cat["candidates"]}
    for row in rows:
        src = by_id[row["candidateId"]]
        assert row["scores"]["total"] == src["scores"]["total"]
        assert row["rank"] == src["rank"] and row["status"] == "FEASIBLE"
    checks = {c["id"]: c for c in body["checks"]}
    assert checks["CANDIDATE_FEASIBLE"]["status"] == "SATISFIED"
    assert checks["ALL_REQUIRED_LEVELS_ACCESSIBLE"]["status"] == "SATISFIED"
    assert checks["CLEARANCE_VALIDATED"]["status"] == "SATISFIED"
    per_node = graph["egressAdvisory"]["perNode"]
    adv = checks["DUAL_EGRESS_ADVISORY"]
    assert adv["evidence"]["undergroundNodeCount"] == len(per_node)
    assert adv["evidence"]["meetingNodeCount"] == sum(1 for p in per_node if p["meetsCriterion"])
    assert adv["evidence"]["failingNodeIds"] == [
        p["nodeId"] for p in per_node if not p["meetsCriterion"]
    ]
    paths = checks["REQUIRED_CAPABILITY_PATHS"]
    assert paths["evidence"]["requiredPathCount"] == len(graph["requiredPaths"])
    assert paths["evidence"]["satisfiedPathCount"] == sum(
        1 for p in graph["requiredPaths"] if p["satisfied"]
    )
    assert body["sources"]["capabilityGraphRevision"] is not None
    # regenerating the network deletes the capability graph (rule 185): the
    # assessment answers NOT_EVALUATED and generates nothing
    assert _network(client, sid)["status"] == "SUCCESS"
    r = client.get(f"{base}/design/assessment")
    assert r.status_code == 200, r.text
    checks = {c["id"]: c for c in r.json()["checks"]}
    assert checks["DUAL_EGRESS_ADVISORY"]["status"] == "NOT_EVALUATED"
    assert client.get(f"{base}/design/capability-graph").status_code == 404


# --------------------------------------------------------------------------- #
# PR #43 review correction — LEGACY-only scenarios keep the generic assessment
# --------------------------------------------------------------------------- #

from minegen.core.artifacts import (  # noqa: E402
    LEGACY_RAMP_ARTIFACT,
    LEVEL_ACCESSES_ARTIFACT,
    RAMP_SOURCE_FILE,
)
from tests.test_artifact_reader import CANDIDATE_ID as DORMANT_ID  # noqa: E402
from tests.test_artifact_reader import _accesses, _selection  # noqa: E402

LAYOUT_CHECKS = (
    "LAYOUT_SELECTED",
    "SELECTED_IS_RANKING_WINNER",
    "CANDIDATE_FEASIBLE",
    "ALL_REQUIRED_LEVELS_ACCESSIBLE",
    "CLEARANCE_VALIDATED",
    "GEOMETRY_VALIDATED",
)
CAPABILITY_CHECKS = ("CAPABILITY_GRAPH_VALID", "REQUIRED_CAPABILITY_PATHS", "DUAL_EGRESS_ADVISORY")


def test_r1_builder_legacy_without_catalogue_keeps_the_generic_checks() -> None:
    payload = build_design_assessment(
        catalogue=None,
        selected=None,
        capability=capability_graph(),
        sources=sources(
            active_source="LEGACY", layout_v2_revision=None, selected_layout_revision=None
        ),
    )
    assert payload.status == "SUCCESS"
    assert payload.active_source == "LEGACY"
    assert payload.layout_scope == "NONE"
    assert payload.winner_id is None
    assert payload.selected_candidate_id is None and payload.selected_candidate is None
    assert payload.active_design_candidate_id is None
    assert payload.candidate_comparison == []
    for cid in LAYOUT_CHECKS:
        c = check(payload, cid)
        assert c.status == "NOT_APPLICABLE", cid
        assert c.scope == "INACTIVE_LAYOUT_V2"
        assert "no layout-v2 catalogue" in c.summary
    for cid in CAPABILITY_CHECKS:
        c = check(payload, cid)
        assert c.status != "NOT_EVALUATED" and c.status != "NOT_APPLICABLE", cid
        assert c.scope == "ACTIVE_DESIGN"
    assert check(payload, "DUAL_EGRESS_ADVISORY").evidence["undergroundNodeCount"] == 5
    assert payload.egress_advisory is not None and len(payload.required_paths) == 3
    assert payload.summary.startswith("Active design: LEGACY")


def test_r1_builder_layout_v2_active_requires_the_catalogue() -> None:
    with pytest.raises(ValueError, match="LAYOUT_V2"):
        build_design_assessment(
            catalogue=None, selected=None, capability=None, sources=sources(layout_v2_revision=None)
        )


def test_r1_builder_legacy_with_a_dormant_selection_is_explicitly_scoped() -> None:
    payload = build(sel=selection(WINNER), cap=capability_graph(), active_source="LEGACY")
    assert payload.active_source == "LEGACY"
    assert payload.layout_scope == "INACTIVE_LAYOUT_V2"
    # the dormant selection is reported AS the layout-v2 selection, never as
    # the active design
    assert payload.selected_candidate_id == WINNER
    assert payload.active_design_candidate_id is None
    assert payload.winner_id == WINNER
    assert [r.candidate_id for r in payload.candidate_comparison] == RANKING[:5]
    for cid in LAYOUT_CHECKS:
        c = check(payload, cid)
        assert c.scope == "INACTIVE_LAYOUT_V2", cid
        assert c.summary.startswith("inactive layout-v2 selection: "), cid
    # the hard checks still read their fields — scoped, never hidden
    assert check(payload, "CANDIDATE_FEASIBLE").status == "SATISFIED"
    assert check(payload, "CLEARANCE_VALIDATED").status == "SATISFIED"
    for cid in CAPABILITY_CHECKS:
        assert check(payload, cid).scope == "ACTIVE_DESIGN", cid
    src = check(payload, "ACTIVE_RAMP_SOURCE")
    assert src.status == "NOT_SATISFIED"
    assert src.evidence["inactiveLayoutSelectionId"] == WINNER
    assert payload.summary.startswith("Active design: LEGACY")
    assert f"Inactive layout-v2 selection: {WINNER}" in payload.summary
    # under an ACTIVE layout-v2 source the same input is the active design
    active = build(sel=selection(WINNER), cap=capability_graph(), active_source="LAYOUT_V2")
    assert active.layout_scope == "ACTIVE_DESIGN"
    assert active.active_design_candidate_id == WINNER
    assert all(c.scope == "ACTIVE_DESIGN" for c in active.checks)


def _legacy_stack(
    client: TestClient,
    design_service: DesignService,
    *,
    with_capability: bool = True,
    with_catalogue: bool = False,
    with_selection: bool = False,
    ramp_source: str | None = None,
) -> str:
    """A hand-written LEGACY design: a VALID legacy ramp artifact, network and
    (optionally) capability graph; optionally a dormant layout-v2 catalogue /
    selection pair and an explicit ramp_source.json."""
    sid = _prepare(client)
    derived = design_service.store.derived_dir(sid)
    _write(derived / LEGACY_RAMP_ARTIFACT, {"status": "SUCCESS", "segments": []})
    _write(derived / NETWORK_ARTIFACT, _network_doc())
    if with_capability:
        cap = capability_graph(network_revision=_rev(derived / NETWORK_ARTIFACT))
        _write(derived / CAPABILITY_GRAPH_ARTIFACT, cap.model_dump(mode="json", by_alias=True))
    if with_catalogue:
        _write(derived / LAYOUT_V2_ARTIFACT, catalogue())
    if with_selection:
        rev = _rev(derived / LAYOUT_V2_ARTIFACT)
        _write(derived / LAYOUT_V2_SELECTED_ARTIFACT, _selection(rev))
        _write(derived / LEVEL_ACCESSES_ARTIFACT, _accesses(rev))
    if ramp_source is not None:
        _write(derived / RAMP_SOURCE_FILE, {"activeSource": ramp_source})
    return sid


def test_r1_api_legacy_only_scenario_receives_the_generic_assessment(
    client: TestClient, design_service: DesignService
) -> None:
    sid = _legacy_stack(client, design_service)
    derived = design_service.store.derived_dir(sid)
    before = sorted(p.name for p in derived.iterdir())
    r = client.get(f"/api/v1/scenarios/{sid}/design/assessment")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "SUCCESS"
    assert body["activeSource"] == "LEGACY"
    assert body["layoutScope"] == "NONE"
    assert body["candidateComparison"] == []
    assert body["winnerId"] is None and body["selectedCandidateId"] is None
    checks = {c["id"]: c for c in body["checks"]}
    adv = checks["DUAL_EGRESS_ADVISORY"]
    assert adv["status"] == "NOT_SATISFIED" and adv["evidence"]["undergroundNodeCount"] == 5
    assert checks["REQUIRED_CAPABILITY_PATHS"]["evidence"]["satisfiedPathCount"] == 2
    assert all(checks[c]["status"] == "NOT_APPLICABLE" for c in LAYOUT_CHECKS)
    assert body["sources"]["layoutV2Revision"] is None
    assert body["sources"]["capabilityGraphRevision"] == _rev(derived / CAPABILITY_GRAPH_ARTIFACT)
    assert sorted(p.name for p in derived.iterdir()) == before  # zero writes
    assert not (derived / LAYOUT_V2_ARTIFACT).exists()


def test_r1_api_legacy_only_without_capability_graph_is_not_evaluated(
    client: TestClient, design_service: DesignService
) -> None:
    sid = _legacy_stack(client, design_service, with_capability=False)
    derived = design_service.store.derived_dir(sid)
    r = client.get(f"/api/v1/scenarios/{sid}/design/assessment")
    assert r.status_code == 200, r.text
    checks = {c["id"]: c for c in r.json()["checks"]}
    assert all(checks[c]["status"] == "NOT_EVALUATED" for c in CAPABILITY_CHECKS)
    assert r.json()["egressAdvisory"] is None and r.json()["requiredPaths"] == []
    assert not (derived / CAPABILITY_GRAPH_ARTIFACT).exists()
    assert not (derived / LAYOUT_V2_ARTIFACT).exists()


def test_r1_api_layout_v2_active_without_catalogue_stays_not_generated(
    client: TestClient, design_service: DesignService
) -> None:
    sid = _legacy_stack(client, design_service, ramp_source="LAYOUT_V2")
    r = client.get(f"/api/v1/scenarios/{sid}/design/assessment")
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "LAYOUT_V2_NOT_GENERATED"


def test_r1_api_legacy_active_with_a_dormant_selection_is_not_conflated(
    client: TestClient, design_service: DesignService
) -> None:
    sid = _legacy_stack(
        client, design_service, with_catalogue=True, with_selection=True, ramp_source="LEGACY"
    )
    r = client.get(f"/api/v1/scenarios/{sid}/design/assessment")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["activeSource"] == "LEGACY"
    assert body["layoutScope"] == "INACTIVE_LAYOUT_V2"
    assert body["selectedCandidateId"] == DORMANT_ID
    assert body["activeDesignCandidateId"] is None
    assert body["winnerId"] == WINNER
    assert [row["candidateId"] for row in body["candidateComparison"]] == RANKING[:5]
    checks = {c["id"]: c for c in body["checks"]}
    for cid in LAYOUT_CHECKS:
        assert checks[cid]["scope"] == "INACTIVE_LAYOUT_V2", cid
        assert checks[cid]["summary"].startswith("inactive layout-v2 selection: "), cid
    for cid in CAPABILITY_CHECKS:
        assert checks[cid]["scope"] == "ACTIVE_DESIGN", cid
    assert checks["ACTIVE_RAMP_SOURCE"]["status"] == "NOT_SATISFIED"
    assert checks["ACTIVE_RAMP_SOURCE"]["evidence"]["inactiveLayoutSelectionId"] == DORMANT_ID
    assert body["sources"]["selectedLayoutRevision"] is not None
    # activating the layout source flips the SAME artifacts to the active design
    _write(design_service.store.derived_dir(sid) / RAMP_SOURCE_FILE, {"activeSource": "LAYOUT_V2"})
    body = client.get(f"/api/v1/scenarios/{sid}/design/assessment").json()
    assert body["layoutScope"] == "ACTIVE_DESIGN"
    assert body["activeDesignCandidateId"] == DORMANT_ID
    assert {c["id"]: c["scope"] for c in body["checks"]}["CANDIDATE_FEASIBLE"] == "ACTIVE_DESIGN"
