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

import numpy as np

from minegen.core.models import (
    LayoutV2Config,
    RampConstraints,
    Scenario,
)
from minegen.design.constraints import DesignContext, RejectionReason
from minegen.design.cost_field import (
    ClearancePolicy,
    DesignCostEvaluator,
    clearance_policy_for,
)
from minegen.design.exposure import measure_exposure

# required_clearance is re-exported here for its established import path; the
# ONE shared definition lives in design.profile (Phase 20C.2A)
from minegen.design.profile import build_profile, required_clearance
from minegen.design.progress import ProgressCallback, ProgressEvent, ProgressStage, no_progress
from minegen.design.targets import default_portal
from minegen.layout.access import (
    BACKBONE_END_MARGIN,
    MIN_DEVELOPMENT_TRACE_LENGTH,
    SCREEN_HEURISTIC,
    SCREEN_NECESSARY_CONDITION,
    build_anchor,
    geometric_access_screen,
    plan_level_accesses,
)
from minegen.layout.certification import (
    CandidateCertification,
    ClearancePolicyReconstructionError,
    ClearanceReport,
    build_candidate_policy,
)
from minegen.layout.certification import anchor_standoff as _anchor_standoff
from minegen.layout.families import (
    FAMILY_ORDER,
    RAMP_CORRIDOR_MARGIN_WIDTHS,
    FamilyGeometry,
    FamilyInfeasible,
    InfeasibleReason,
    LayoutContext,
    build_family,
    build_footwall_track,
    effective_footwall_standoff,
    enumerate_candidates,
    resolved_station_lengths,
)
from minegen.layout.geometry import (
    CenterlineDiagnostics,
    Crossing,
    analyze_centerline,
    find_crossing,
)
from minegen.layout.levels import LevelSections, RequiredLevel, required_levels
from minegen.layout.materialize import (
    LAYOUT_V2_SELECTED_ARTIFACT,
    LEVEL_ACCESSES_ARTIFACT,
    RAMP_END_SEGMENT_ID,
    SOURCE_KIND_PARAMETRIC_V2,
    chainage_of,
    materialize_effective_ramp,
    materialize_level_accesses,
)
from minegen.layout.reference import ServiceReference, build_service_reference
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
from minegen.layout.sections import SectionGeometryError, resolve_section_resolution
from minegen.layout.validation import validate_delivered_centerline
from minegen.world.orebody import TabularOrebody
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

# -- documented internal score coefficients (§27) ----------------------------- #
#: DEVELOPMENT: ramp length / grade-limited ideal length, plus the mean
#: level access distance as a fraction of the reach (future development proxy)
DEV_ACCESS_COEF = 0.5
#: GEOLOGY: length fractions in fault core / damage zone / poor rock, plus a
#: per-crossing term
GEO_CORE_COEF = 10.0
GEO_DAMAGE_COEF = 3.0
GEO_POOR_ROCK_COEF = 5.0
GEO_CROSSING_COEF = 0.1
#: GEOMETRY: unused gradient, turning fraction, worst level access as a
#: fraction of reach, clearance headroom below twice the requirement
GEOM_TURNING_COEF = 0.5
GEOM_CLEARANCE_COEF = 1.0
#: GEOMETRY curvature quality (Phase 20B.1 D-2): the diagnostics the
#: family signature already measures become priced score components. Round
#: planning coefficients chosen A PRIORI — never reverse-engineered to
#: crown a family (D-4); a mine whose scale genuinely favours k2 or a
#: helix must still be able to win.
#: × mean |Δheading| per metre of 3-D length (rad/m): overall turniness —
#: a constant-R helix contributes ≈ 20/R, a switchback its hairpin share
GEOM_CURVATURE_COEF = 20.0
#: × count of 150–210° same-sense turning runs (switchback hairpins)
GEOM_REVERSAL_COEF = 0.05
#: × count of ≥ 150° same-sense turning runs (hairpins AND a spiral's
#: continuous winding — one long run for a helix)
GEOM_HAIRPIN_COEF = 0.02
#: × equivalentHalfTurns = cumulative |Δheading| (rad) / π — the ABSOLUTE
#: turning burden as a dimensionless count of 180° units (Phase 20B.2-B).
#: The 20B.2-B audit (golden/phase20b2_turning_burden_audit.json) showed the
#: structural asymmetry: meanCurvature is length-normalized, so a helix
#: winding 34 half-turns over 3954 m priced 0.55 while a k1 switchback
#: turning 17 half-turns paid 0.8 + 0.32 through the ABSOLUTE reversal and
#: hairpin counts. Coefficient chosen A PRIORI, before the sensitivity run:
#: 180° of cumulative steering costs the same 0.05 as one direction
#: reversal (GEOM_REVERSAL_COEF), so a hairpin (180° + a reversal) and one
#: helix loop (360°, no reversal) both price 0.10 — symmetric by
#: construction, not fitted to any family. It is a geometry planning
#: proxy, not a tyre / fuel / ventilation model; it shares its measurement
#: (cumulative heading) with meanCurvature (turning DENSITY per metre) —
#: the two are different normalizations and are reported separately.
GEOM_HALF_TURN_COEF = 0.05
#: score ties within this tolerance fall through to the family-order and
#: candidate-id tie-breaks (§28)
SCORE_TIE_TOLERANCE = 1e-9
#: plan-radius numerical tolerance on the delivered centerline (rule 62)
RADIUS_TOLERANCE = 0.05
#: gradient numerical tolerance on the delivered centerline
GRADIENT_TOLERANCE = 1e-9


# --------------------------------------------------------------------------- #
# Stage helpers
# --------------------------------------------------------------------------- #


def level_service(
    points: FloatArray, levels: list[RequiredLevel], sections: LevelSections, reach: float
) -> tuple[list[LevelServiceRecord], list[Crossing | None]]:
    records: list[LevelServiceRecord] = []
    crossings: list[Crossing | None] = []
    for lv in levels:
        sec = sections.section(lv)
        cr = find_crossing(points, lv.elevation)
        crossings.append(cr)
        if sec.empty:
            records.append(
                LevelServiceRecord(
                    lv.level_id,
                    lv.elevation,
                    False,
                    unserved_reason=InfeasibleReason.NO_OREBODY_SECTION_AT_LEVEL.value,
                )
            )
            continue
        if cr is None:
            records.append(
                LevelServiceRecord(
                    lv.level_id,
                    lv.elevation,
                    False,
                    unserved_reason=InfeasibleReason.NO_RL_CROSSING.value,
                )
            )
            continue
        d = sec.access_distance(cr.point[:2])
        within = d <= reach
        records.append(
            LevelServiceRecord(
                lv.level_id,
                lv.elevation,
                within,
                connection_position=cr.point,
                connection_chainage=cr.chainage,
                access_distance=d,
                unserved_reason=None if within else InfeasibleReason.ACCESS_REACH_EXCEEDED.value,
            )
        )
    return records, crossings


def cheap_checks(
    diag: CenterlineDiagnostics,
    points: FloatArray,
    ramp: RampConstraints,
    half_x: float,
    half_y: float,
) -> list[tuple[InfeasibleReason, str]]:
    problems: list[tuple[InfeasibleReason, str]] = []
    if diag.max_abs_gradient > ramp.max_gradient + GRADIENT_TOLERANCE:
        problems.append(
            (
                InfeasibleReason.GRADE_LIMIT,
                f"delivered max gradient {diag.max_abs_gradient:.5f} > {ramp.max_gradient:g}",
            )
        )
    if diag.min_plan_radius is not None and (
        diag.min_plan_radius < ramp.min_turn_radius - RADIUS_TOLERANCE
    ):
        problems.append(
            (
                InfeasibleReason.TURN_RADIUS,
                f"delivered min plan radius {diag.min_plan_radius:.2f} m < "
                f"{ramp.min_turn_radius:g} m",
            )
        )
    if not diag.monotonic_descent:
        problems.append((InfeasibleReason.GEOMETRY_ASSEMBLY, "centerline is not monotonic"))
    out = np.any(np.abs(points[:, 0]) > half_x) or np.any(np.abs(points[:, 1]) > half_y)
    if bool(out):
        problems.append((InfeasibleReason.WORLD_BOUNDS, "centerline leaves the world"))
    return problems


#: stage-2 level-screen reasons that reject a candidate (closeout v3 §3.B).
#: ACCESS_REACH_EXCEEDED is deliberately absent: it is a heuristic, not a
#: physical infeasibility. NO_OREBODY_SECTION_AT_LEVEL never reaches the
#: screen (the context carries serviceable levels only, rule 141).
_HARD_SCREEN_REASONS = frozenset(
    {
        InfeasibleReason.NO_RL_CROSSING.value,
        InfeasibleReason.NO_OREBODY_SECTION_AT_LEVEL.value,
    }
)


def level_screen_problems(
    records: list[LevelServiceRecord],
) -> list[tuple[InfeasibleReason, str]]:
    """Stage-2 decision on the level screen (closeout v3 §3.B): only a level
    the main ramp does not vertically cover (NO_RL_CROSSING) rejects the
    candidate. ACCESS_REACH_EXCEEDED alone never does — the record stays
    inspectable (``withinReach = false``) and stage 4 plans the access."""
    hard = [r for r in records if r.unserved_reason in _HARD_SCREEN_REASONS]
    if not hard:
        return []
    reasons = sorted({r.unserved_reason or "" for r in hard})
    return [
        (
            InfeasibleReason.LEVEL_SERVICE_INFEASIBLE,
            f"{len(hard)} of {len(records)} required levels are not vertically covered "
            f"by the main ramp ({', '.join(reasons)})",
        )
    ]


def cheap_proxy(
    diag: CenterlineDiagnostics, records: list[LevelServiceRecord], ctx: LayoutContext
) -> float:
    """Stage-3 ordering proxy (Phase 20B.1 D, rule 165 corrective): a cheap
    LOWER BOUND of the final weighted total, computable at stage 2 with no
    evaluator — the DEVELOPMENT group without its non-negative access-length
    term, plus the FULL GEOMETRY group except its non-negative clearance
    headroom; GEOLOGY (≥ 0) is omitted. The 20B.1-D shortlist audit showed
    the old length-only proxy missing exhaustive winners (TABULAR rank
    40/62, GEOMETRY-STRESS rank 22/26): under the hard gates the surviving
    candidates are longer but geometrically calmer, which only a bound that
    prices the measured curvature can rank."""
    drop = float(ctx.portal[2] - ctx.z_last)
    ideal = math.hypot(drop / ctx.ramp.max_gradient, drop)
    access = [r.access_distance for r in records if r.access_distance is not None]
    mean_access = float(np.mean(access)) if access else ctx.cfg.access_reach
    max_access = float(np.max(access)) if access else ctx.cfg.access_reach
    reach = ctx.cfg.access_reach
    dev_lb = diag.length3d / ideal + DEV_ACCESS_COEF * mean_access / reach
    total_len = max(diag.length3d, 1e-9)
    unused_grade = max(0.0, 1.0 - diag.mean_abs_gradient / ctx.ramp.max_gradient)
    geom_lb = (
        unused_grade
        + GEOM_TURNING_COEF * diag.turning_length / total_len
        + max_access / reach
        + GEOM_CURVATURE_COEF * math.radians(diag.cumulative_heading_change_deg) / total_len
        + GEOM_REVERSAL_COEF * diag.heading_reversal_count
        + GEOM_HAIRPIN_COEF * diag.hairpin_run_count
        + GEOM_HALF_TURN_COEF * math.radians(diag.cumulative_heading_change_deg) / math.pi
    )
    w = ctx.cfg.weights
    return w.development * dev_lb + w.geometry * geom_lb


def score_candidate(
    cand: CandidateResult, ctx: LayoutContext, exposure: dict[str, float], weights: Any
) -> Scores:
    assert cand.diagnostics is not None and cand.clearance is not None
    diag = cand.diagnostics
    drop = float(ctx.portal[2] - ctx.z_last)
    ideal = math.hypot(drop / ctx.ramp.max_gradient, drop)
    access = [r.access_distance for r in cand.level_service if r.access_distance is not None]
    mean_access = float(np.mean(access)) if access else ctx.cfg.access_reach
    max_access = float(np.max(access)) if access else ctx.cfg.access_reach
    reach = ctx.cfg.access_reach
    # Phase 20B: development = main ramp + EXPLICIT level-access development
    # (rule 158); the cheap footprint-distance term stays as a corridor proxy
    access_length = cand.access_plan.total_length if cand.access_plan else 0.0
    length_ratio = (diag.length3d + access_length) / ideal
    development = length_ratio + DEV_ACCESS_COEF * mean_access / reach
    total_len = max(diag.length3d, 1e-9)
    core_frac = exposure["lengthFaultCore"] / total_len
    damage_frac = exposure["lengthFaultDamage"] / total_len
    poor_frac = exposure["lengthPoorRock"] / total_len
    geology = (
        GEO_CORE_COEF * core_frac
        + GEO_DAMAGE_COEF * damage_frac
        + GEO_POOR_ROCK_COEF * poor_frac
        + GEO_CROSSING_COEF * exposure["faultCrossings"]
    )
    unused_grade = max(0.0, 1.0 - diag.mean_abs_gradient / ctx.ramp.max_gradient)
    turning_frac = diag.turning_length / total_len
    req = cand.clearance.required
    headroom = max(0.0, 1.0 - cand.clearance.conservative_minimum / (2.0 * req)) if req > 0 else 0.0
    # Phase 20B.1 D-2: curvature quality — the measured family signature
    # priced into the geometry group (documented coefficients above)
    mean_curvature = math.radians(diag.cumulative_heading_change_deg) / total_len
    reversals = float(diag.heading_reversal_count)
    hairpin_runs = float(diag.hairpin_run_count)
    # Phase 20B.2-B: absolute turning burden in 180° units (see the
    # GEOM_HALF_TURN_COEF rationale) — reported next to the density term
    half_turns = math.radians(diag.cumulative_heading_change_deg) / math.pi
    geometry = (
        unused_grade
        + GEOM_TURNING_COEF * turning_frac
        + max_access / reach
        + GEOM_CLEARANCE_COEF * headroom
        + GEOM_CURVATURE_COEF * mean_curvature
        + GEOM_REVERSAL_COEF * reversals
        + GEOM_HAIRPIN_COEF * hairpin_runs
        + GEOM_HALF_TURN_COEF * half_turns
    )
    total = (
        weights.development * development + weights.geology * geology + weights.geometry * geometry
    )
    return Scores(
        development,
        geology,
        geometry,
        total,
        {
            "lengthRatio": length_ratio,
            "mainRampLength": diag.length3d,
            "levelAccessLength": access_length,
            "meanAccessRatio": mean_access / reach,
            "maxAccessRatio": max_access / reach,
            "faultCoreFraction": core_frac,
            "faultDamageFraction": damage_frac,
            "poorRockFraction": poor_frac,
            "faultCrossings": float(exposure["faultCrossings"]),
            "unusedGradient": unused_grade,
            "turningFraction": turning_frac,
            "clearanceHeadroom": headroom,
            "meanCurvatureRadPerM": mean_curvature,
            "headingReversalCount": reversals,
            "hairpinRunCount": hairpin_runs,
            "equivalentHalfTurns": half_turns,
        },
    )


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #


class LayoutV2Search:
    """Deterministic layout-v2 search over one generated world."""

    def __init__(self, scenario: Scenario, world: SyntheticWorld) -> None:
        self.scenario = scenario
        self.world = world
        self.cfg: LayoutV2Config = scenario.layout
        self.policy: ClearancePolicy = clearance_policy_for(world.orebody)
        self.evaluator = DesignCostEvaluator(
            world,
            scenario.design,
            DesignContext.decline(scenario.design),
            clearance=self.policy,
        )
        self.shape = build_profile(scenario.ramp, scenario.tunnel_profile)
        #: Phase 20C.1-S: the longest declared hairpin station (+ one sample
        #: spacing) is the straight a same-sense turning run may bridge and
        #: still count as ONE reversal; None when no station is declared
        stations = resolved_station_lengths(self.cfg)
        self.station_merge_bound: float | None = (
            max(stations) + float(self.cfg.sample_spacing) if max(stations) > 0.0 else None
        )
        self._sections: LevelSections | None = None
        self._track: Any = None
        self._reference: ServiceReference | None = None
        #: the stage-4 LayoutContext of the last run — retained so the
        #: candidate-specific clearance policy can be rebuilt after the fact
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
        t0 = time.perf_counter()
        sc = self.scenario
        world = self.world
        levels = required_levels(
            world.orebody,
            sc.mining.sublevel_interval,
            sc.design.top_mining_margin,
            sc.design.bottom_mining_margin,
        )
        sections = LevelSections(world.orebody, levels, self.cfg.section_sampling_spacing)
        # Phase 20C.2A: non-TABULAR level development anchors come from the
        # section(z) geometry, which needs a resolved sampling resolution.
        # Base stand-off = explicit access.anchorStandoff else the configured
        # footwall access offset (never the honesty-raised value). A typed
        # resolution/budget failure fails EVERY candidate closed below.
        section_error: SectionGeometryError | None = None
        if not isinstance(world.orebody, TabularOrebody):
            base_standoff = (
                self.cfg.access.anchor_standoff
                if self.cfg.access.anchor_standoff is not None
                else sc.ramp.footwall_access_offset
            )
            try:
                sections.set_resolution(
                    resolve_section_resolution(
                        float(self.cfg.section_sampling_spacing), float(base_standoff)
                    )
                )
            except SectionGeometryError as err:
                section_error = err
        track = build_footwall_track(world.orebody, sections)
        self._sections, self._track = sections, track
        if sc.portal is not None:
            portal = np.array(sc.portal.as_tuple(), dtype=np.float64)
            generated = False
        else:
            portal = default_portal(sc, world.orebody, world.terrain)  # generic frame use
            generated = True
        req_clear = required_clearance(sc.design, sc.ramp, sc.tunnel_profile)
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
                levels, sections, portal, generated, results, [], [], None, req_clear, perf, None
            )
        if sections.budget_diagnostics is not None:
            perf["sectionGeometry"] = sections.budget_diagnostics
        serviceable = sections.serviceable()
        if not serviceable or track is None:
            for c in results:
                c.failure_reasons = [InfeasibleReason.NO_REQUIRED_LEVELS.value]
                c.failure_detail = "no required level intersects the orebody solid"
            perf["totalSeconds"] = time.perf_counter() - t0
            return self._result(
                levels, sections, portal, generated, results, [], [], None, req_clear, perf, None
            )
        # Phase 20C.4: the conservative construction ServiceReference — the
        # WORLD-policy offset traces stage 4 builds for coarse anchors (same
        # cache token), read once here so the ramp corridor and the level
        # anchors share ONE spacing reference (rule 170 vs rules 158 / 178).
        # Inactive (delta ≡ 0, bit-identical) on TABULAR and for an explicit
        # footwallStandoff; per-level trace failures are reported, never hidden.
        standoff_value, standoff_source = effective_footwall_standoff(self.cfg, sc.ramp)
        reference = build_service_reference(
            sections,
            serviceable,
            track.w_h,
            orebody=world.orebody,
            clearance=self.policy.signed_clearance,
            basis=self.policy.basis,
            standoff=standoff_value,
            standoff_source=standoff_source,
            margin=RAMP_CORRIDOR_MARGIN_WIDTHS * float(sc.ramp.tunnel_width),
            anchor_standoff=self.anchor_standoff(req_clear, self.policy),
            min_trace_length=MIN_DEVELOPMENT_TRACE_LENGTH,
            end_margin=BACKBONE_END_MARGIN,
            required_clearance=req_clear,
        )
        self._reference = reference
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

        # -- STAGE 1 + 2: construct and cheap-evaluate every candidate --------- #
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
            self._cheap_stage(cand, built, ctx, req_clear)
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
            self._detailed_stage(cand, ctx, req_clear)
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
            sections,
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
        sections: LevelSections,
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
            serviceable_ids=[lv.level_id for lv in sections.serviceable()],
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

    # -- stages ------------------------------------------------------------- #

    def _cheap_stage(
        self, cand: CandidateResult, built: FamilyGeometry, ctx: LayoutContext, req_clear: float
    ) -> None:
        cand.stage_reached = Stage.CHEAP
        cand.points = built.points
        cand.pieces = built.pieces
        cand.derived = built.derived
        diag = analyze_centerline(built.points, station_merge_max_m=self.station_merge_bound)
        cand.diagnostics = diag
        problems = cheap_checks(diag, built.points, ctx.ramp, ctx.world_half_x, ctx.world_half_y)
        records, crossings = level_service(
            built.points, ctx.levels, ctx.sections, ctx.cfg.access_reach
        )
        cand.level_service = records
        cand.crossings = crossings
        # closeout v3 §3: only a level the main ramp does NOT vertically cover
        # (NO_RL_CROSSING — no junction lattice can exist for a ramp that never
        # reaches the level) is a hard stage-2 failure. ACCESS_REACH_EXCEEDED is
        # a soft access-potential heuristic: it stays visible per level and in
        # the stage-3 proxy, and stage 4 plans the explicit access.
        problems.extend(level_screen_problems(records))
        cand.cheap_proxy = cheap_proxy(diag, records, ctx)
        if problems:
            cand.status = CandidateStatus.INFEASIBLE
            cand.failure_reasons = [p[0].value for p in problems]
            cand.failure_detail = "; ".join(p[1] for p in problems)
        else:
            cand.status = CandidateStatus.NOT_VALIDATED
            # Phase 20C.1-Q: evaluator-free geometric access screen on the
            # delivered polyline (coarse-stand-off anchors) — the stage-3
            # ordering prefix (rule 176); it never rejects, stage 4 decides
            assert self._sections is not None and self._track is not None
            standoff = self.anchor_standoff(req_clear, self.policy)
            anchors = [
                build_anchor(
                    self.world.orebody,
                    lv,
                    self._sections,
                    self._track,
                    built.points,
                    standoff,
                    self.scenario.mining.method.value,
                    clearance=self.policy.signed_clearance,
                    policy_token="WORLD",
                    minimum_clearance=req_clear,
                )
                for lv in ctx.levels
            ]
            cand.access_screen = geometric_access_screen(
                built.points,
                anchors,
                ctx.levels,
                self.cfg.access,
                ctx.ramp,
                self.shape,
                screen_authority(self.policy),
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
        evaluator, policy, refinement = self._candidate_policy(
            cand, self._ctx, result.required_clearance
        )
        CandidateCertification.from_report(cand.candidate_id, cand.clearance).verify(
            policy, refinement
        )
        return evaluator, policy, refinement

    def _candidate_policy(
        self, cand: CandidateResult, ctx: LayoutContext, req_clear: float
    ) -> tuple[DesignCostEvaluator, ClearancePolicy, dict[str, Any]]:
        """Stage-4 evaluator for ONE candidate (Phase 20B.1 C-2): the shared
        policy, or a per-candidate REFINED_CONSERVATIVE policy built from one
        LOCAL refined window covering (a) the centerline samples whose COARSE
        certification falls below the requirement and (b) the level-entry
        corridor (preliminary anchors under the coarse stand-off — the
        refined bound moves the entries). Points outside the window keep the
        coarse certification, so refinement can only certify MORE, never
        admit an optimistic distance. A window over the cell budget skips
        refinement with an explicit diagnostic."""
        assert cand.points is not None
        assert self._sections is not None and self._track is not None
        return build_candidate_policy(
            self.world,
            self.scenario,
            self.cfg,
            world_policy=self.policy,
            world_evaluator=self.evaluator,
            points=cand.points,
            levels=ctx.levels,
            sections=self._sections,
            track=self._track,
            required_clearance=req_clear,
        )

    def _detailed_stage(self, cand: CandidateResult, ctx: LayoutContext, req_clear: float) -> None:
        assert cand.points is not None and cand.diagnostics is not None
        cand.stage_reached = Stage.DETAILED
        evaluator, policy, refinement = self._candidate_policy(cand, ctx, req_clear)
        report = validate_delivered_centerline(evaluator, cand.points)
        cand.validation = report.to_dict()
        # clearance under the candidate's policy (EXACT, COARSE_CONSERVATIVE
        # or the stage-4 REFINED_CONSERVATIVE window)
        conservative_min = float(np.min(report.orebody_distance))
        approx_min: float | None = None
        bound: float | None = None
        if policy.basis != "EXACT":
            bound = float(policy.error_bound)
            approx_min = conservative_min + bound
        clear_ok = conservative_min >= req_clear - 1e-9
        cand.clearance = ClearanceReport(
            policy.basis, req_clear, conservative_min, approx_min, bound, clear_ok, refinement
        )
        problems: list[tuple[InfeasibleReason, str]] = []
        for reason, count in sorted(report.rejection_counts.items()):
            mapped = _map_reason(reason)
            problems.append((mapped, f"{count} samples {reason}"))
        if not clear_ok:
            problems.append(
                (
                    InfeasibleReason.OREBODY_CLEARANCE,
                    f"conservative minimum clearance {conservative_min:.2f} m < required "
                    f"{req_clear:.2f} m ({policy.basis})",
                )
            )
        # Phase 20B: explicit ramp-junction + level-access planning (rule 156).
        # Only a main ramp that is itself valid gets an access plan; an
        # unreachable level is a HARD failure, never a score term. The plan
        # runs under the CANDIDATE's policy (C-2): a refined bound shrinks
        # the anchor stand-off, so entries sit at the configured value again.
        if not problems:
            assert self._sections is not None and self._track is not None
            standoff = self.anchor_standoff(req_clear, policy)
            # trace cache identity: the shared world policy, or this
            # candidate's own stage-4 refined policy (deterministic token)
            token = "WORLD" if policy is self.policy else cand.candidate_id
            cand.anchors = [
                build_anchor(
                    self.world.orebody,
                    lv,
                    self._sections,
                    self._track,
                    cand.points,
                    standoff,
                    self.scenario.mining.method.value,
                    clearance=policy.signed_clearance,
                    policy_token=token,
                    minimum_clearance=req_clear,
                )
                for lv in ctx.levels
            ]
            cand.access_plan = plan_level_accesses(
                cand.points,
                cand.anchors,
                ctx.levels,
                self.cfg.access,
                self.scenario.ramp,
                evaluator,
                self.shape,
                req_clear,
            )
            if not cand.access_plan.feasible:
                failed = [a for a in cand.access_plan.accesses if not a.ok]
                problems.append(
                    (
                        InfeasibleReason.LEVEL_ACCESS_INFEASIBLE,
                        f"{len(failed)} of {len(cand.access_plan.accesses)} required levels "
                        "have no valid ramp junction + level access ("
                        + ", ".join(f"{a.level_id}: {a.failure_reason}" for a in failed)
                        + ")",
                    )
                )
        exposure = measure_exposure([cand.points], self.world.faults, self.evaluator.rock_quality)
        cand.exposure = {
            "faultCrossings": exposure.fault_crossings,
            "lengthFaultCore": exposure.length_fault_core,
            "lengthFaultDamage": exposure.length_fault_damage,
            "lengthPoorRock": exposure.length_poor_rock,
            "totalLength": exposure.total_length,
            "fieldCost": report.field_cost,
        }
        cand.scores = score_candidate(cand, ctx, cand.exposure, self.cfg.weights)
        if problems:
            cand.status = CandidateStatus.INFEASIBLE
            cand.failure_reasons = sorted({p[0].value for p in problems})
            cand.failure_detail = "; ".join(p[1] for p in problems)
        else:
            cand.status = CandidateStatus.FEASIBLE


def _map_reason(reason: str) -> InfeasibleReason:
    table = {
        RejectionReason.OUTSIDE_WORLD.value: InfeasibleReason.WORLD_BOUNDS,
        RejectionReason.ABOVE_TERRAIN.value: InfeasibleReason.ABOVE_TERRAIN,
        RejectionReason.INSUFFICIENT_COVER.value: InfeasibleReason.SURFACE_COVER,
        RejectionReason.INSIDE_OREBODY.value: InfeasibleReason.OREBODY_CLEARANCE,
        RejectionReason.OREBODY_BUFFER.value: InfeasibleReason.OREBODY_CLEARANCE,
        RejectionReason.RESTRICTED_ZONE.value: InfeasibleReason.RESTRICTED_ZONE,
    }
    return table.get(reason, InfeasibleReason.GEOMETRY_ASSEMBLY)


def _family_rank(c: CandidateResult) -> int:
    return FAMILY_ORDER.index(c.params.family)


def screen_authority(policy: ClearancePolicy) -> str:
    """What a BLOCKED level of the stage-2 geometric access screen proves,
    decided by the CLEARANCE POLICY's distance contract (closeout B), never
    by the orebody type. The screen's only policy dependence is the anchor
    stand-off (``anchor_standoff``), which is raised above the configured
    value exactly when ``basis != "EXACT"``: with an exact contract the
    screen anchor IS the stage-4 anchor, so a blocked level is unservable in
    stage 4 as well; with a conservative one stage 4 may refine the bound,
    shrink the stand-off and move the entry, so the blocked count is only a
    heuristic."""
    return SCREEN_NECESSARY_CONDITION if policy.basis == "EXACT" else SCREEN_HEURISTIC


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
    assert c.scores is not None
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
