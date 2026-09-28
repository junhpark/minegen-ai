"""Layout Development Economics (Phase 22C, rules 204–206).

A READ-ONLY projection of the persisted layout-v2 catalogue into a
per-candidate *Comparable Layout Development Cost*:

    mainRampLengthM(c)            = candidates[c].diagnostics.length3d
    levelAccessLengthM(c)         = candidates[c].access.totalAccessLength
    rampCost(c)                   = mainRampLengthM × economics.developmentCosts.rampPerM
    levelAccessCost(c)            = levelAccessLengthM × economics.developmentCosts.levelAccessPerM
    comparableDevelopmentCost(c)  = rampCost + levelAccessCost
    comparableDevelopmentLengthM  = mainRampLengthM + levelAccessLengthM

Both quantities are the candidate's OWN persisted facts (`layout_v2.json`,
written by the layout search); nothing is re-swept, re-summed from a
centerline or re-planned here, and no per-candidate level, production,
network or timeline artifact exists or is imagined (rule 204). The cost is
a synthetic planning comparator over the two candidate-owned development
kinds only — it is never a total mine development cost, a project cost,
an NPV, a feasibility or an optimization recommendation (rule 205).

Rows are the catalogue ``ranking`` in its persisted order (rule 148); the
ranking winner, the selection and every score are copied verbatim through
the Phase 20D.3 helpers (:func:`comparison_scores`, :func:`score_deltas`).
The comparison never re-sorts by cost and carries no cost rank, no
"cheapest" flag and no recommendation (rule 206).
"""

from __future__ import annotations

import math
from typing import Any, Literal

from minegen.analysis.economics import EconomicsConfig
from minegen.assessment.builder import (
    FEASIBLE,
    CatalogueShapeError,
    comparison_scores,
    score_deltas,
    validate_catalogue_shape,
)
from minegen.assessment.models import (
    CandidateStatusLiteral,
    ComparisonScores,
    LayoutScope,
    ScoreDeltas,
)
from minegen.core.models import ApiModel

__all__ = [
    "COMPARISON_DISCLAIMER",
    "EXCLUDED_COST_KINDS",
    "INCLUDED_COST_KINDS",
    "LayoutComparisonAvailability",
    "LayoutComparisonBasis",
    "LayoutComparisonPayload",
    "LayoutDevelopmentComparisonRow",
    "build_layout_comparison",
    "validate_layout_economics_shape",
]

LayoutComparisonAvailability = Literal["AVAILABLE", "NOT_AVAILABLE", "NOT_CONFIGURED"]

#: the ONLY development kinds a candidate owns in the catalogue, hence the
#: only ones a candidate-level cost may include (directive §4 / §7)
INCLUDED_COST_KINDS: tuple[str, ...] = ("RAMP", "LEVEL_ACCESS")
#: everything a whole-mine economics would carry and this comparison does
#: NOT (directive §7): named explicitly so the omission is never mistaken
#: for a zero
EXCLUDED_COST_KINDS: tuple[str, ...] = (
    "DRIFT",
    "CROSSCUT",
    "RAISE",
    "SHAFT",
    "SHAFT_STATION_ACCESS",
    "PRODUCTION",
    "PROCESSING",
    "BACKFILL",
    "FIXED_OPEX",
    "CAPITAL",
    "REVENUE",
    "NPV",
)

COMPARISON_DISCLAIMER = (
    "Comparable layout development cost includes only candidate-owned main-ramp and "
    "level-access development priced at the configured planning rates. It is not the "
    "mine's total development cost, not total mine cost, not NPV, not a feasibility "
    "statement and not an optimization recommendation. Engineering ranking, winner and "
    "selection are owned by the layout authority and are never changed by cost."
)

REASON_NO_WORLD = "world not generated"
REASON_NO_CATALOGUE = "layout-v2 catalogue not generated"
REASON_NOT_CONFIGURED = "planning economics not configured"


# --------------------------------------------------------------------------- #
# DTOs
# --------------------------------------------------------------------------- #


class LayoutComparisonBasis(ApiModel):
    """What the comparable cost includes and, explicitly, what it excludes."""

    included: list[str]
    excluded: list[str]


class LayoutDevelopmentComparisonRow(ApiModel):
    """One ranked FEASIBLE catalogue candidate. Lengths are the persisted
    candidate facts; costs are ``length × rate`` and ``None`` whenever
    planning economics is not configured (never a hidden default)."""

    candidate_id: str
    family: str
    #: the persisted layout rank (1 = ranking winner) — the ONLY rank here
    catalogue_rank: int | None
    selected: bool
    winner: bool
    status: CandidateStatusLiteral
    main_ramp_length_m: float
    level_access_length_m: float
    comparable_development_length_m: float
    ramp_cost: float | None
    level_access_cost: float | None
    comparable_development_cost: float | None
    #: ``candidate − winner`` / ``candidate − selected`` plain subtraction
    cost_delta_from_winner: float | None
    cost_delta_from_selected: float | None
    scores: ComparisonScores | None
    score_delta_from_winner: ScoreDeltas | None


class LayoutComparisonPayload(ApiModel):
    status: Literal["SUCCESS"]
    availability: LayoutComparisonAvailability
    reason: str | None
    scope: LayoutScope
    active_source: str
    winner_id: str | None
    selected_candidate_id: str | None
    currency_code: str | None
    ramp_rate_per_m: float | None
    level_access_rate_per_m: float | None
    economics_revision: str | None
    layout_revision: str | None
    selection_revision: str | None
    comparison_basis: LayoutComparisonBasis
    rows: list[LayoutDevelopmentComparisonRow]
    disclaimer: str


# --------------------------------------------------------------------------- #
# consumer-specific shape extension (directive §14)
# --------------------------------------------------------------------------- #


def _is_length(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0.0
    )


def validate_layout_economics_shape(catalogue: dict[str, Any]) -> None:
    """The fields THIS consumer reads beyond :func:`validate_catalogue_shape`
    (which must have passed first): every RANKED candidate carries a
    ``diagnostics.length3d`` and an ``access.totalAccessLength`` that are
    finite, non-negative numbers. They stay OPTIONAL for the assessment —
    this extension is applied only here, so a catalogue without them keeps
    answering the design assessment (directive §14). The message names the
    JSON path; the service translates the error into
    ``ArtifactMalformedError(LAYOUT_V2_ARTIFACT, …)`` (409)."""
    by_id = {str(c["candidateId"]): (i, c) for i, c in enumerate(catalogue["candidates"])}
    for cid in catalogue["ranking"]:
        i, cand = by_id[cid]
        path = f"$.candidates[{i}]"
        diagnostics = cand.get("diagnostics")
        if not isinstance(diagnostics, dict):
            raise CatalogueShapeError(
                f"{path}.diagnostics: expected object for ranked candidate {cid!r}, "
                f"got {type(diagnostics).__name__}"
            )
        if not _is_length(diagnostics.get("length3d")):
            raise CatalogueShapeError(
                f"{path}.diagnostics.length3d: expected finite non-negative number for ranked "
                f"candidate {cid!r}, got {diagnostics.get('length3d')!r}"
            )
        access = cand.get("access")
        if not isinstance(access, dict):
            raise CatalogueShapeError(
                f"{path}.access: expected object for ranked candidate {cid!r}, "
                f"got {type(access).__name__}"
            )
        if not _is_length(access.get("totalAccessLength")):
            raise CatalogueShapeError(
                f"{path}.access.totalAccessLength: expected finite non-negative number for "
                f"ranked candidate {cid!r}, got {access.get('totalAccessLength')!r}"
            )


# --------------------------------------------------------------------------- #
# builder
# --------------------------------------------------------------------------- #


def _basis() -> LayoutComparisonBasis:
    return LayoutComparisonBasis(
        included=list(INCLUDED_COST_KINDS), excluded=list(EXCLUDED_COST_KINDS)
    )


def _unavailable(
    *,
    reason: str,
    active_source: str,
    economics: EconomicsConfig | None,
    economics_revision: str | None,
) -> LayoutComparisonPayload:
    return LayoutComparisonPayload(
        status="SUCCESS",
        availability="NOT_AVAILABLE",
        reason=reason,
        scope="NONE",
        active_source=active_source,
        winner_id=None,
        selected_candidate_id=None,
        currency_code=None if economics is None else economics.currency_code,
        ramp_rate_per_m=None if economics is None else economics.development_costs.ramp_per_m,
        level_access_rate_per_m=(
            None if economics is None else economics.development_costs.level_access_per_m
        ),
        economics_revision=economics_revision,
        layout_revision=None,
        selection_revision=None,
        comparison_basis=_basis(),
        rows=[],
        disclaimer=COMPARISON_DISCLAIMER,
    )


def build_layout_comparison(
    *,
    catalogue: dict[str, Any] | None,
    selected: dict[str, Any] | None,
    active_source: str,
    world_generated: bool,
    economics: EconomicsConfig | None,
    economics_revision: str | None,
    layout_revision: str | None,
    selection_revision: str | None,
) -> LayoutComparisonPayload:
    """Pure projection: no file system, no search, no geometry. ``catalogue``
    and ``selected`` are the raw validated documents (``None`` when absent).

    Availability (directive §8): no world / no catalogue → NOT_AVAILABLE with
    an empty row list; catalogue without ``economics.json`` → NOT_CONFIGURED
    with the geometry facts and ``None`` costs; both → AVAILABLE. Scope
    follows the assessment: ACTIVE_DESIGN under LAYOUT_V2, INACTIVE_LAYOUT_V2
    for a catalogue beside a LEGACY active ramp, NONE without a catalogue.
    """
    if not world_generated:
        return _unavailable(
            reason=REASON_NO_WORLD,
            active_source=active_source,
            economics=economics,
            economics_revision=economics_revision,
        )
    if catalogue is None:
        return _unavailable(
            reason=REASON_NO_CATALOGUE,
            active_source=active_source,
            economics=economics,
            economics_revision=economics_revision,
        )
    # the shared grammar first, then this consumer's extension (§14)
    validate_catalogue_shape(catalogue, selected)
    validate_layout_economics_shape(catalogue)

    by_id = {str(c["candidateId"]): c for c in catalogue["candidates"]}
    ranking = [str(cid) for cid in catalogue["ranking"]]
    winner_id = catalogue.get("winnerId")
    winner_id = str(winner_id) if winner_id is not None else None
    selected_id = None if selected is None else str(selected["candidateId"])
    winner_scores = by_id[winner_id].get("scores") if winner_id in by_id else None

    ramp_rate = None if economics is None else float(economics.development_costs.ramp_per_m)
    access_rate = (
        None if economics is None else float(economics.development_costs.level_access_per_m)
    )

    def cost(cid: str) -> float | None:
        if ramp_rate is None or access_rate is None:
            return None
        cand = by_id[cid]
        ramp_len = float(cand["diagnostics"]["length3d"])
        access_len = float(cand["access"]["totalAccessLength"])
        return ramp_len * ramp_rate + access_len * access_rate

    winner_cost = cost(winner_id) if winner_id in ranking else None
    selected_cost = cost(selected_id) if selected_id in ranking else None

    rows: list[LayoutDevelopmentComparisonRow] = []
    for cid in ranking:
        cand = by_id[cid]
        ramp_len = float(cand["diagnostics"]["length3d"])
        access_len = float(cand["access"]["totalAccessLength"])
        ramp_cost = None if ramp_rate is None else ramp_len * ramp_rate
        access_cost = None if access_rate is None else access_len * access_rate
        total = None if ramp_cost is None or access_cost is None else ramp_cost + access_cost
        scores = comparison_scores(cand.get("scores"))
        rows.append(
            LayoutDevelopmentComparisonRow(
                candidate_id=cid,
                family=str(cand["family"]),
                catalogue_rank=cand.get("rank"),
                selected=cid == selected_id,
                winner=cid == winner_id,
                status=cand["status"],
                main_ramp_length_m=ramp_len,
                level_access_length_m=access_len,
                comparable_development_length_m=ramp_len + access_len,
                ramp_cost=ramp_cost,
                level_access_cost=access_cost,
                comparable_development_cost=total,
                cost_delta_from_winner=(
                    None if total is None or winner_cost is None else total - winner_cost
                ),
                cost_delta_from_selected=(
                    None if total is None or selected_cost is None else total - selected_cost
                ),
                scores=scores,
                score_delta_from_winner=score_deltas(scores, winner_scores),
            )
        )
    assert all(by_id[cid]["status"] == FEASIBLE for cid in ranking)  # shape-validated

    scope: LayoutScope = "ACTIVE_DESIGN" if active_source == "LAYOUT_V2" else "INACTIVE_LAYOUT_V2"
    configured = economics is not None
    return LayoutComparisonPayload(
        status="SUCCESS",
        availability="AVAILABLE" if configured else "NOT_CONFIGURED",
        reason=None if configured else REASON_NOT_CONFIGURED,
        scope=scope,
        active_source=active_source,
        winner_id=winner_id,
        selected_candidate_id=selected_id,
        currency_code=None if economics is None else economics.currency_code,
        ramp_rate_per_m=ramp_rate,
        level_access_rate_per_m=access_rate,
        economics_revision=economics_revision,
        layout_revision=layout_revision,
        selection_revision=selection_revision,
        comparison_basis=_basis(),
        rows=rows,
        disclaimer=COMPARISON_DISCLAIMER,
    )
