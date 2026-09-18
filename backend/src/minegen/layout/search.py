"""Layout-v2 hierarchical search (Phase 20A, directive §25–28).

    STAGE 1  finite parametric enumeration            (families.enumerate_candidates)
    STAGE 2  cheap evaluation on the delivered centerline: gradient, plan
             radius, world bounds, monotonic descent, vertical level
             coverage (NO_RL_CROSSING is hard: the main ramp does not span
             the level's elevation). The same-RL crossing → footprint
             distance (``withinReach`` / ACCESS_REACH_EXCEEDED) is an
             ACCESS-POTENTIAL HEURISTIC only (closeout v3 §3): it feeds the
             stage-3 proxy and never rejects a candidate — the Phase 20B
             level-access planner (stage 4) is the final service authority.
    STAGE 3  bounded shortlist (``shortlist_size``) by a cheap proxy
    STAGE 4  detailed engineering validation of the shortlist through the
             shared ``DesignCostEvaluator`` (terrain, cover with the rule 52
             portal transition, restricted zones, orebody clearance under the
             EXACT or CONSERVATIVE policy), geological exposure, scores
    STAGE 5  deterministic ranking → winner

Every candidate stays inspectable with an explicit status and typed failure
reasons (§41). Hard failures never become score penalties (§21). Scores use
three interpretable groups (§26); the coefficients inside each group are
the documented module constants below and the only user-facing weights are
the group weights (§27).
"""

from __future__ import annotations

import math
import time
from typing import Any

from minegen.core.models import (
    LayoutV2Config,
    Scenario,
)
from minegen.design.cost_field import ClearancePolicy, DesignCostEvaluator

# required_clearance is re-exported here for its established import path; the
# ONE shared definition lives in design.profile (Phase 20C.2A)
from minegen.design.profile import build_profile, required_clearance
from minegen.design.progress import ProgressCallback, ProgressEvent, ProgressStage, no_progress
from minegen.layout.certification import (
    CandidateCertification,
    ClearancePolicyReconstructionError,
    ClearanceReport,
    world_search_policy,
)
from minegen.layout.certification import anchor_standoff as _anchor_standoff
from minegen.layout.families import (
    FAMILY_ORDER,
    FamilyInfeasible,
    InfeasibleReason,
    LayoutContext,
    build_family,
    effective_footwall_standoff,
    enumerate_candidates,
    resolved_station_lengths,
)
from minegen.layout.levels import RequiredLevel
from minegen.layout.materialize import (
    LAYOUT_V2_SELECTED_ARTIFACT,
    LEVEL_ACCESSES_ARTIFACT,
    RAMP_END_SEGMENT_ID,
    SOURCE_KIND_PARAMETRIC_V2,
    chainage_of,
    materialize_effective_ramp,
    materialize_level_accesses,
)
from minegen.layout.provider import (
    SectionProvider,
    attach_service_reference,
    build_section_provider,
    context_provider,
)
from minegen.layout.results import (
    LAYOUT_V2_VERSION,
    CandidateResult,
    CandidateStatus,
    FloatArray,
    LayoutSearchResult,
    LevelServiceRecord,
    Scores,
    Stage,
)

# AC-01G commit 3: the stages and the stage helpers live in ``layout.stages``;
# every name ``layout.search`` exported before the move is re-exported here so
# its established import path (and ``__all__``) is unchanged.
from minegen.layout.stages import (
    DEV_ACCESS_COEF,
    GEO_CORE_COEF,
    GEO_CROSSING_COEF,
    GEO_DAMAGE_COEF,
    GEO_POOR_ROCK_COEF,
    GEOM_CLEARANCE_COEF,
    GEOM_CURVATURE_COEF,
    GEOM_HAIRPIN_COEF,
    GEOM_HALF_TURN_COEF,
    GEOM_REVERSAL_COEF,
    GEOM_TURNING_COEF,
    GRADIENT_TOLERANCE,
    RADIUS_TOLERANCE,
    SCORE_TIE_TOLERANCE,
    CheapEvaluation,
    StageContext,
    apply_cheap,
    apply_detailed,
    certify,
    cheap_checks,
    cheap_proxy,
    cheap_stage,
    detailed_stage,
    level_screen_problems,
    level_service,
    score_candidate,
    screen_authority,
)
from minegen.world.synthetic_world import SyntheticWorld

#: every name that was importable from ``layout.search`` before AC-01C keeps
#: importing from here (explicit re-export: mypy strict has no implicit one)
__all__ = [
    "DEV_ACCESS_COEF",
    "GEOM_CLEARANCE_COEF",
    "GEOM_CURVATURE_COEF",
    "GEOM_HAIRPIN_COEF",
    "GEOM_HALF_TURN_COEF",
    "GEOM_REVERSAL_COEF",
    "GEOM_TURNING_COEF",
    "GEO_CORE_COEF",
    "GEO_CROSSING_COEF",
    "GEO_DAMAGE_COEF",
    "GEO_POOR_ROCK_COEF",
    "GRADIENT_TOLERANCE",
    "LAYOUT_V2_SELECTED_ARTIFACT",
    "LAYOUT_V2_VERSION",
    "LEVEL_ACCESSES_ARTIFACT",
    "RADIUS_TOLERANCE",
    "RAMP_END_SEGMENT_ID",
    "SCORE_TIE_TOLERANCE",
    "SOURCE_KIND_PARAMETRIC_V2",
    "CandidateResult",
    "CandidateStatus",
    "ClearancePolicyReconstructionError",
    "ClearanceReport",
    "FloatArray",
    "LayoutSearchResult",
    "LayoutV2Search",
    "LevelServiceRecord",
    "Scores",
    "Stage",
    "chainage_of",
    "cheap_checks",
    "cheap_proxy",
    "level_screen_problems",
    "level_service",
    "materialize_effective_ramp",
    "materialize_level_accesses",
    "required_clearance",
    "score_candidate",
    "screen_authority",
    "shortlist_key",
]


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #


class LayoutV2Search:
    """Deterministic layout-v2 search over one generated world."""

    def __init__(self, scenario: Scenario, world: SyntheticWorld) -> None:
        self.scenario = scenario
        self.world = world
        self.cfg: LayoutV2Config = scenario.layout
        # AC-01D: the world policy / evaluator have ONE definition, shared
        # with the certification restore
        policy, evaluator = world_search_policy(scenario, world)
        self.policy: ClearancePolicy = policy
        self.evaluator: DesignCostEvaluator = evaluator
        self.shape = build_profile(scenario.ramp, scenario.tunnel_profile)
        #: Phase 20C.1-S: the longest declared hairpin station (+ one sample
        #: spacing) is the straight a same-sense turning run may bridge and
        #: still count as ONE reversal; None when no station is declared
        stations = resolved_station_lengths(self.cfg)
        self.station_merge_bound: float | None = (
            max(stations) + float(self.cfg.sample_spacing) if max(stations) > 0.0 else None
        )
        #: the stage-4 LayoutContext of the last run — the ONLY run state
        #: the search keeps (AC-01G): the section geometry, footwall track
        #: and construction reference are the provider's, and the context
        #: carries the very same objects, so the candidate-specific
        #: clearance policy can still be rebuilt after the fact
        self._ctx: LayoutContext | None = None

    @property
    def context(self) -> LayoutContext:
        """The ONLY sanctioned view of post-run state (AC-01C): the stage
        context of the last ``run()`` — serviceable levels, the level
        sections (including their offset-trace cache), the footwall track
        and the construction ServiceReference. The objects are the very ones
        the search used; a search that has not run — or that returned
        early on a section-geometry failure or with no serviceable level —
        has no context and raises."""
        if self._ctx is None:
            raise RuntimeError("LayoutV2Search.run() has not built a stage context")
        return self._ctx

    def anchor_standoff(self, required: float, policy: ClearancePolicy | None = None) -> float:
        """Level-entry stand-off from the footwall edge: the configured /
        ramp value, raised for a conservative clearance policy so the entry
        itself satisfies ``required + errorBound`` (rule 146 honesty). With a
        stage-4 REFINED_CONSERVATIVE policy the smaller refined bound is what
        raises it (C-2), so entries move back toward the configured value."""
        p = policy if policy is not None else self.policy
        return _anchor_standoff(self.cfg, self.scenario.ramp, required, p)

    def run(
        self, on_progress: ProgressCallback = no_progress, *, detailed_all: bool = False
    ) -> LayoutSearchResult:
        """``detailed_all`` is a DIAGNOSTIC switch (closeout v3 §3.E shortlist
        starvation audit): every cheap-feasible candidate receives detailed
        validation instead of the bounded shortlist. It is never exposed
        through the scenario config or the API."""
        self._ctx = None
        t0 = time.perf_counter()
        sc = self.scenario
        world = self.world
        # AC-01D: the setup block has ONE definition (layout.setup), shared
        # with the search-object-free certification restore. AC-01G: the
        # section geometry (sections, footwall track, serviceable levels and
        # the construction ServiceReference) has ONE owner for the run.
        setup, provider = build_section_provider(sc, world, self.policy)
        levels, sections, section_error, track = (
            setup.levels,
            provider.sections,
            setup.section_error,
            provider.track,
        )
        portal, generated = setup.portal, setup.portal_generated
        req_clear = setup.required_clearance
        perf: dict[str, Any] = {}
        params = enumerate_candidates(self.cfg)
        perf["candidateCount"] = len(params)
        results = [CandidateResult(p) for p in params]
        t_setup = time.perf_counter()
        perf["setupSeconds"] = t_setup - t0
        if section_error is not None:
            for c in results:
                c.failure_reasons = [section_error.code]
                c.failure_detail = section_error.detail
            perf["sectionGeometry"] = section_error.diagnostics
            perf["totalSeconds"] = time.perf_counter() - t0
            return self._result(
                levels,
                provider.serviceable,
                portal,
                generated,
                results,
                [],
                [],
                None,
                req_clear,
                perf,
                None,
            )
        if sections.budget_diagnostics is not None:
            perf["sectionGeometry"] = sections.budget_diagnostics
        serviceable = provider.serviceable
        if not serviceable or track is None:
            for c in results:
                c.failure_reasons = [InfeasibleReason.NO_REQUIRED_LEVELS.value]
                c.failure_detail = "no required level intersects the orebody solid"
            perf["totalSeconds"] = time.perf_counter() - t0
            return self._result(
                levels,
                provider.serviceable,
                portal,
                generated,
                results,
                [],
                [],
                None,
                req_clear,
                perf,
                None,
            )
        # Phase 20C.4: the conservative construction ServiceReference (built
        # by the provider, rule 170 vs rules 158 / 178) is reported here, in
        # the persisted `performance` insertion order it has always had.
        # AC-01G (Park review): the reference build happens HERE, after the
        # guards, exactly where the pre-extraction code ran it — so its cost
        # stays inside ``constructAndCheapSeconds`` and the two persisted
        # timing keys keep their meaning. The provider is still its ONE
        # construction owner (``layout/provider.py``).
        provider = attach_service_reference(provider, setup, sc, world, self.policy)
        reference = provider.reference
        if reference is not None:
            perf["serviceReference"] = reference.to_dict()
        ctx = LayoutContext(
            portal,
            serviceable,
            sections,
            track,
            sc.ramp,
            self.cfg,
            sc.world.size_x / 2.0,
            sc.world.size_y / 2.0,
            reference=reference,
        )
        self._ctx = ctx
        stage_ctx = self._stage_context(provider, ctx, req_clear)

        # -- STAGE 1 + 2: construct and cheap-evaluate every candidate --------- #
        # AC-01G: a stage RETURNS its outcome; ``apply_cheap`` is the only
        # writer of the persisted record. The outcome is kept so stage 4 can
        # take it as a typed argument instead of reading the record back.
        cheap_outcomes: dict[str, CheapEvaluation] = {}
        n = len(results)
        for i, cand in enumerate(results):
            on_progress(_event(ProgressStage.CANDIDATE_STARTED, i, n, cand.candidate_id, "CHEAP"))
            built = build_family(cand.params, ctx)
            if isinstance(built, FamilyInfeasible):
                cand.failure_reasons = [built.reason.value]
                cand.failure_detail = built.detail
                on_progress(
                    _event(ProgressStage.CANDIDATE_COMPLETED, i, n, cand.candidate_id, cand.status)
                )
                continue
            evaluation = cheap_stage(stage_ctx, cand.candidate_id, built)
            apply_cheap(cand, evaluation)
            cheap_outcomes[cand.candidate_id] = evaluation
            on_progress(
                _event(ProgressStage.CANDIDATE_COMPLETED, i, n, cand.candidate_id, cand.status)
            )
        t_cheap = time.perf_counter()
        perf["constructAndCheapSeconds"] = t_cheap - t_setup

        # -- STAGE 3: bounded shortlist --------------------------------------- #
        cheap_ok = [c for c in results if c.status == CandidateStatus.NOT_VALIDATED]
        cheap_ok.sort(key=_shortlist_key)
        if detailed_all:
            shortlist = cheap_ok
        else:
            shortlist = cheap_ok[: self.cfg.shortlist_size]
            # rule 165 family diversity (Phase 20B.1 D): every family's best
            # cheap-feasible candidate holds a slot, displacing the proxy
            # tail — the bound stays `shortlist_size`, the order stays
            # deterministic (proxy, family order, id)
            missing = [
                fam for fam in FAMILY_ORDER if not any(c.params.family is fam for c in shortlist)
            ]
            extras = [
                best
                for fam in missing
                if (best := next((c for c in cheap_ok if c.params.family is fam), None)) is not None
            ]
            if extras:
                shortlist = shortlist[: max(0, self.cfg.shortlist_size - len(extras))] + extras
                shortlist.sort(key=_shortlist_key)
        for c in shortlist:
            c.shortlisted = True
        perf["shortlistSize"] = len(shortlist)
        perf["cheapFeasibleCount"] = len(cheap_ok)
        perf["exhaustiveDiagnostic"] = detailed_all

        # -- STAGE 4: detailed validation ------------------------------------- #
        for j, cand in enumerate(shortlist):
            on_progress(
                _event(
                    ProgressStage.CANDIDATE_STARTED,
                    j,
                    len(shortlist),
                    cand.candidate_id,
                    "DETAILED",
                )
            )
            outcome = cheap_outcomes[cand.candidate_id]
            apply_detailed(cand, detailed_stage(stage_ctx, cand, outcome))
            on_progress(
                _event(
                    ProgressStage.CANDIDATE_COMPLETED,
                    j,
                    len(shortlist),
                    cand.candidate_id,
                    cand.status,
                )
            )
        perf["detailedSeconds"] = time.perf_counter() - t_cheap

        # -- STAGE 5: deterministic ranking ----------------------------------- #
        feasible = [c for c in results if c.status == CandidateStatus.FEASIBLE]
        feasible.sort(key=_rank_key)
        for r, c in enumerate(feasible, start=1):
            c.rank = r
        ranking = [c.candidate_id for c in feasible]
        winner = ranking[0] if ranking else None
        perf["totalSeconds"] = time.perf_counter() - t0
        on_progress(
            ProgressEvent(
                stage=ProgressStage.DECLINE_COMPLETED,
                phase="LAYOUT_V2",
                level=len(levels),
                total_levels=len(levels),
                candidate=n,
                total_candidates=n,
                progress=1.0,
                expanded_states=0,
                message=winner or "NO_FEASIBLE_CANDIDATE",
            )
        )
        return self._result(
            levels,
            serviceable,
            portal,
            generated,
            results,
            [c.candidate_id for c in shortlist],
            ranking,
            winner,
            req_clear,
            perf,
            track,
        )

    def _result(
        self,
        levels: list[RequiredLevel],
        serviceable: list[RequiredLevel],
        portal: FloatArray,
        generated: bool,
        results: list[CandidateResult],
        shortlist: list[str],
        ranking: list[str],
        winner: str | None,
        req_clear: float,
        perf: dict[str, Any],
        track: Any,
    ) -> LayoutSearchResult:
        standoff = effective_footwall_standoff(self.cfg, self.scenario.ramp)[0]
        return LayoutSearchResult(
            levels=levels,
            serviceable_ids=[lv.level_id for lv in serviceable],
            track=track.to_dict() if track is not None else None,
            portal=portal,
            portal_generated=generated,
            candidates=results,
            shortlist=shortlist,
            ranking=ranking,
            winner_id=winner,
            clearance_basis=self.policy.basis,
            clearance_error_bound=float(self.policy.error_bound),
            required_clearance=req_clear,
            access_reach=self.cfg.access_reach,
            standoff=standoff,
            performance=perf,
            config=self.cfg.model_dump(mode="json", by_alias=True),
        )

    # -- stage context ------------------------------------------------------ #

    def _stage_context(
        self, provider: SectionProvider, ctx: LayoutContext, required_clearance: float
    ) -> StageContext:
        """The stage-side state as ONE explicit value (AC-01G): the
        constructor-owned world policy / evaluator / profile / station merge
        bound, the run's section-geometry provider and the construction
        context. ``run()`` and the post-run ``candidate_policy`` facade build
        it from the SAME inputs — in particular the constructor objects
        ``self.policy`` / ``self.evaluator``, whose identity decides the
        offset-trace cache token inside the certification recipe."""
        return StageContext(
            scenario=self.scenario,
            world=self.world,
            cfg=self.cfg,
            world_policy=self.policy,
            world_evaluator=self.evaluator,
            shape=self.shape,
            station_merge_bound=self.station_merge_bound,
            required_clearance=required_clearance,
            provider=provider,
            ctx=ctx,
        )

    def candidate_policy(
        self, result: LayoutSearchResult, candidate_id: str
    ) -> tuple[DesignCostEvaluator, ClearancePolicy, dict[str, Any]]:
        """The candidate-specific stage-4 evaluator / clearance policy of a
        DETAILED candidate, rebuilt deterministically from the same inputs
        (Phase 20B.1-v2 1.1). Selection materialization, the tunnel sweep and
        the development sweep call this so the downstream chain judges the
        selected design under the SAME certification that made it FEASIBLE —
        never the whole-body COARSE basis again. Fails closed
        (``ClearancePolicyReconstructionError``) when the rebuilt refinement
        provenance disagrees with the candidate's recorded stage-4 report."""
        cand = result.candidate(candidate_id)
        if cand is None:
            raise KeyError(candidate_id)
        if cand.stage_reached != Stage.DETAILED or cand.clearance is None or self._ctx is None:
            raise ClearancePolicyReconstructionError(
                candidate_id, "the candidate has no stage-4 clearance report to reconstruct"
            )
        ctx = self._ctx
        # the context carries the run's sections / track / serviceable levels
        # / reference BY IDENTITY, so the provider view recomputes nothing
        provider = context_provider(ctx.sections, ctx.track, ctx.levels, ctx.reference)
        if cand.points is None:  # pragma: no cover - a DETAILED candidate has points
            raise ClearancePolicyReconstructionError(
                candidate_id, "the candidate has no delivered centerline to certify"
            )
        clearance = certify(
            self._stage_context(provider, ctx, result.required_clearance),
            cand.candidate_id,
            cand.points,
        )
        CandidateCertification.from_report(cand.candidate_id, cand.clearance).verify(
            clearance.policy, clearance.refinement
        )
        return clearance.evaluator, clearance.policy, clearance.refinement


def _family_rank(c: CandidateResult) -> int:
    return FAMILY_ORDER.index(c.params.family)


def _shortlist_key(c: CandidateResult) -> tuple[int, float, int, str]:
    """Stage-3 order (rule 176): geometric-screen blocked levels first, then
    the cheap lower-bound proxy (rule 165), family order, id.

    Under an EXACT distance contract a blocked level is a NECESSARY
    CONDITION of a stage-4 failure (the screen anchor is the stage-4
    anchor), so the prefix orders by something the candidate cannot
    recover. Under a CONSERVATIVE contract it is only a HEURISTIC
    (``screen_authority``): stage 4 may refine the bound, move the entry and
    still serve a blocked level. The closeout-B measurement
    (``golden/phase20c1_closeout_screen_audit.json``) quantified exactly
    that — 0 false blocks on the four EXACT cases, 56 over the three
    conservative ones (301: 27, 307: 2, IRREGULAR: 27), 6 of them on
    candidates the production shortlist had validated.

    Dropping the prefix on the conservative side was therefore ATTEMPTED and
    REVERTED: it fails the family-yield acceptance
    (``golden/phase20c1_closeout_ordering_attempt_shortlist_audit.json``) —
    WARPED-301 loses the whole SWITCHBACK family again
    (``missedFamilies`` [] → ['SWITCHBACK'], feasible 10 → 3), which is the
    regression rule 176's screen was introduced to fix. The heuristic
    prefix is kept there as an ORDERING HEURISTIC ONLY, never as authority:
    it rejects nothing under either contract, the `blocked ⊆ failed`
    contract is not claimed or tested on the conservative side, and stage 4
    stays the final authority. Ordering the conservative side without a
    heuristic that mis-blocks — by improving the proxy itself — is recorded
    as a Phase 20C.2 candidate, not attempted here."""
    return (c.screen_blocked, c.cheap_proxy or math.inf, _family_rank(c), c.candidate_id)


#: public alias of the stage-3 key (AC-01C) — the SAME function object the
#: search sorts with, so an external reconstruction proves the shortlist
#: against production's own ordering (rule 176 keeps naming ``_shortlist_key``)
shortlist_key = _shortlist_key


def _rank_key(c: CandidateResult) -> tuple[int, float, int, str]:
    # AC-01G Stage D (D2): an explicit refusal, not an ``assert`` — the last
    # candidate-state precondition that ``python -O`` would have removed. The
    # arithmetic below is unchanged.
    if c.scores is None:
        raise ValueError(f"candidate '{c.candidate_id}' has no scores to rank")
    total = round(c.scores.total / SCORE_TIE_TOLERANCE) * SCORE_TIE_TOLERANCE
    return (
        0 if c.status == CandidateStatus.FEASIBLE else 1,
        total,
        _family_rank(c),
        c.candidate_id,
    )


def _event(
    stage: ProgressStage, index: int, total: int, candidate_id: str, status: str
) -> ProgressEvent:
    return ProgressEvent(
        stage=stage,
        phase="LAYOUT_V2",
        level=1,
        total_levels=1,
        candidate=index + 1,
        total_candidates=total,
        progress=(index + (1 if stage is ProgressStage.CANDIDATE_COMPLETED else 0)) / max(total, 1),
        expanded_states=0,
        candidate_id=candidate_id,
        candidate_status=status,
    )
