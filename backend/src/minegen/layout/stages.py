"""Layout-v2 stages: context, anchor lens, stage helpers and stage outcomes.

The state a layout-v2 stage needs, as ONE explicit frozen argument instead of
nine reach-ins into ``LayoutV2Search`` (Stage A §A4). A stage function takes a
``StageContext`` and nothing else from the search object; there is no ``self``
to reach through, so the invariant is carried by the type, not by discipline.

``AnchorLens`` names the three values that distinguish a stage-2 screen anchor
from a stage-4 planning anchor (rules 172 / 176): the level-entry stand-off,
the clearance field the offset backbone is a level set of, and the
offset-trace cache token that names that field. The screen lens always uses
the WORLD policy, the coarse stand-off and the ``"WORLD"`` token; the detailed
lens takes them from the candidate's own certification. ``build_anchors``
performs the one anchor loop both stages share.

AC-01G commit 3 — the stage boundary is a VALUE, not a mutation. Each stage is
a pure function of a ``StageContext`` returning a frozen outcome
(``CheapEvaluation`` / ``DetailedEvaluation``) whose fields are REQUIRED, so a
stage result can never be half-built. Exactly two functions write the
persisted ``CandidateResult`` — ``apply_cheap`` and ``apply_detailed`` — with
the same fields, the same values and the same order as the mutating stages
had; ``LayoutV2Search.run`` keeps its own run-level writes
(``failure_reasons`` / ``failure_detail`` on the two early returns,
``shortlisted``, ``rank``). Illegal stage transitions are refused with
``ValueError``, never with ``assert``: a refusal that vanishes under
``python -O`` is not a refusal.

The score coefficients, tolerances and the stage helpers (``level_service``,
``cheap_checks``, ``level_screen_problems``, ``cheap_proxy``,
``score_candidate``, ``screen_authority``) moved here VERBATIM from
``layout.search``, which re-exports every one of them so their established
import path keeps working. Not one expression was reordered: a re-associated
float sum can move a score past ``SCORE_TIE_TOLERANCE`` and re-rank a tie.
The ONE line that is not a byte-for-byte copy is ``score_candidate``'s
sentinel ``assert``, which became the explicit refusal the no-``assert`` rule
above requires; its arithmetic is untouched.

Leaf module: it must not import ``layout.search`` or ``minegen.services``.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.core.models import LayoutV2Config, RampConstraints, Scenario
from minegen.design.constraints import RejectionReason
from minegen.design.cost_field import ClearancePolicy, DesignCostEvaluator
from minegen.design.exposure import measure_exposure
from minegen.layout.access import (
    SCREEN_HEURISTIC,
    SCREEN_NECESSARY_CONDITION,
    AnchorFailure,
    LevelAccessPlan,
    LevelDevelopmentAnchor,
    build_anchor,
    geometric_access_screen,
    plan_level_accesses,
)
from minegen.layout.certification import (
    CandidateClearance,
    ClearanceReport,
    anchor_standoff,
    certify_candidate,
)
from minegen.layout.families import (
    FamilyGeometry,
    FootwallTrack,
    InfeasibleReason,
    LayoutContext,
)
from minegen.layout.geometry import (
    CenterlineDiagnostics,
    Crossing,
    analyze_centerline,
    find_crossing,
)
from minegen.layout.levels import LevelSections, RequiredLevel
from minegen.layout.provider import SectionProvider
from minegen.layout.results import (
    CandidateResult,
    CandidateStatus,
    LevelServiceRecord,
    Scores,
    Stage,
)
from minegen.layout.validation import validate_delivered_centerline
from minegen.world.synthetic_world import SyntheticWorld

FloatArray = npt.NDArray[np.float64]


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


@dataclass(frozen=True)
class StageContext:
    """Everything a layout-v2 stage reads that is not the candidate itself.

    ``world_policy`` / ``world_evaluator`` are the CONSTRUCTOR objects of the
    search (``LayoutV2Search.policy`` / ``.evaluator``) — identity matters:
    the offset-trace cache token is decided by ``policy is world_policy``
    inside the certification recipe (rule 172 / census O10). ``provider`` is
    the run's section-geometry authority and ``ctx`` the unchanged
    ``LayoutContext`` the families construct against; its ``sections`` /
    ``track`` / ``levels`` / ``reference`` are the provider's objects.
    """

    scenario: Scenario
    world: SyntheticWorld
    cfg: LayoutV2Config
    world_policy: ClearancePolicy
    world_evaluator: DesignCostEvaluator
    shape: Any
    station_merge_bound: float | None
    required_clearance: float
    provider: SectionProvider
    ctx: LayoutContext

    @property
    def ramp(self) -> RampConstraints:
        return self.scenario.ramp

    @property
    def mining_method(self) -> str:
        return str(self.scenario.mining.method.value)

    @property
    def levels(self) -> list[RequiredLevel]:
        """The SERVICEABLE required levels the stages iterate (rule 141)."""
        return self.ctx.levels

    @property
    def sections(self) -> LevelSections:
        return self.provider.sections

    @property
    def track(self) -> FootwallTrack:
        return self.provider.footwall_track


@dataclass(frozen=True)
class AnchorLens:
    """How ONE stage looks at the level-development anchors: the level-entry
    stand-off, the clearance measure the offset backbone is a level set of,
    and the deterministic cache token naming that measure."""

    standoff: float
    clearance: Callable[[FloatArray], FloatArray]
    trace_token: str


def screen_lens(sc: StageContext) -> AnchorLens:
    """Stage-2 geometric access screen (rule 176): the WORLD clearance
    policy, its coarse stand-off, the ``"WORLD"`` token — the same key the
    construction ``ServiceReference`` filled, so the screen never builds a
    second clearance field. It takes no candidate, by type."""
    return AnchorLens(
        standoff=anchor_standoff(sc.cfg, sc.scenario.ramp, sc.required_clearance, sc.world_policy),
        clearance=sc.world_policy.signed_clearance,
        trace_token="WORLD",
    )


def detailed_lens(sc: StageContext, clearance: CandidateClearance) -> AnchorLens:
    """Stage-4 level-access planning (rule 172): the CANDIDATE's certified
    policy, the stand-off that policy's error bound implies, and the token
    the certification recipe derived — ``"WORLD"`` for a non-refined
    candidate, the candidate id for a refined one."""
    return AnchorLens(
        standoff=anchor_standoff(sc.cfg, sc.scenario.ramp, sc.required_clearance, clearance.policy),
        clearance=clearance.policy.signed_clearance,
        trace_token=clearance.trace_token,
    )


def build_anchors(
    sc: StageContext, lens: AnchorLens, points: FloatArray
) -> list[LevelDevelopmentAnchor | AnchorFailure | None]:
    """The level-development anchors of one delivered centerline under one
    lens — the single definition of the loop the screen and the detailed
    stage both run (they differed only in the lens)."""
    return [
        build_anchor(
            sc.world.orebody,
            lv,
            sc.provider.sections,
            sc.track,
            points,
            lens.standoff,
            sc.mining_method,
            clearance=lens.clearance,
            policy_token=lens.trace_token,
            minimum_clearance=sc.required_clearance,
        )
        for lv in sc.ctx.levels
    ]


# --------------------------------------------------------------------------- #
# Stage outcomes (AC-01G): what a stage RETURNS
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CheapEvaluation:
    """The complete result of stage 2 for ONE constructed candidate.

    Every field is REQUIRED: a ``CheapEvaluation`` exists only for a candidate
    whose geometry was built and cheap-evaluated, so ``points``,
    ``diagnostics``, ``level_service`` and ``cheap_proxy`` can never be the
    ``None`` sentinels the persisted record still carries (census A3). In
    particular ``cheap_proxy`` is computed for EVERY constructed candidate,
    before the feasibility branch, exactly as the mutating stage did — a
    cheap-INFEASIBLE row's persisted ``cheapProxy`` is a real number, never
    ``null`` (risk R3).

    ``failure_reasons`` keeps the CHEAP list semantics — ``[p[0].value for p in
    problems]``, problem order, duplicates allowed — which is HARD-CONTRACT
    golden content and deliberately differs from the detailed stage's
    de-duplicated ``sorted({...})`` (risk R5).
    """

    points: FloatArray
    diagnostics: CenterlineDiagnostics
    level_service: list[LevelServiceRecord]
    cheap_proxy: float
    problems: list[tuple[InfeasibleReason, str]]
    status: str
    failure_reasons: list[str]
    failure_detail: str | None
    access_screen: dict[str, Any] | None
    derived: dict[str, Any]
    pieces: list[dict[str, Any]]


@dataclass(frozen=True)
class DetailedEvaluation:
    """The complete result of stage 4 for ONE shortlisted candidate.

    Every field is a REQUIRED constructor argument, so a detailed outcome is
    never half-built. ``clearance``, ``validation``, ``scores`` and
    ``exposure`` are produced on every path — which is what makes the illegal
    combination "FEASIBLE with no clearance report" (census A3 (a))
    unconstructible rather than merely unwritten. ``anchors`` and
    ``access_plan`` are required too, but they carry the values the mutating
    stage left behind when a hard gate had already failed: an empty anchor
    list and ``None``, since level-access planning only runs for a main ramp
    that is itself valid.
    """

    clearance: ClearanceReport
    validation: dict[str, Any]
    scores: Scores
    exposure: dict[str, Any]
    anchors: list[LevelDevelopmentAnchor | AnchorFailure | None]
    access_plan: LevelAccessPlan | None
    status: str
    failure_reasons: list[str]
    failure_detail: str | None


# --------------------------------------------------------------------------- #
# Stage helpers (moved VERBATIM from layout.search, AC-01G commit 3)
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
    # AC-01G I4: an explicit refusal, never an ``assert`` — a stage-module
    # precondition must survive ``python -O``. The arithmetic below is
    # unchanged, line for line (risk R7).
    if cand.diagnostics is None or cand.clearance is None:
        raise ValueError(f"candidate '{cand.candidate_id}' has no cheap/detailed report to score")
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


# --------------------------------------------------------------------------- #
# Stages: pure functions of a StageContext
# --------------------------------------------------------------------------- #


def _certify(sc: StageContext, cand: CandidateResult) -> CandidateClearance:
    """Stage-4 certification of ONE candidate: the shared world policy, or a
    per-candidate REFINED_CONSERVATIVE policy, plus the offset-trace cache
    token the recipe derived (``layout.certification.certify_candidate`` —
    the token is decided there, never against a search attribute)."""
    if cand.points is None:
        raise ValueError(f"candidate '{cand.candidate_id}' has no delivered centerline to certify")
    return certify_candidate(
        sc.world,
        sc.scenario,
        sc.cfg,
        world_policy=sc.world_policy,
        world_evaluator=sc.world_evaluator,
        points=cand.points,
        levels=sc.ctx.levels,
        sections=sc.provider.sections,
        track=sc.track,
        required_clearance=sc.required_clearance,
        candidate_id=cand.candidate_id,
    )


def cheap_stage(sc: StageContext, built: FamilyGeometry) -> CheapEvaluation:
    """Stage 2 on the DELIVERED centerline (rule 144). Pure: it reads the
    context and the constructed geometry and returns the outcome; the
    persisted record is written by ``apply_cheap`` and by nothing else."""
    ctx = sc.ctx
    diag = analyze_centerline(built.points, station_merge_max_m=sc.station_merge_bound)
    problems = cheap_checks(diag, built.points, ctx.ramp, ctx.world_half_x, ctx.world_half_y)
    # ``level_service`` also returns the per-level RL crossings; they have no
    # consumer (census O1) and the cheap stage discards them
    records, _ = level_service(built.points, ctx.levels, ctx.sections, ctx.cfg.access_reach)
    # closeout v3 §3: only a level the main ramp does NOT vertically cover
    # (NO_RL_CROSSING — no junction lattice can exist for a ramp that never
    # reaches the level) is a hard stage-2 failure. ACCESS_REACH_EXCEEDED is
    # a soft access-potential heuristic: it stays visible per level and in
    # the stage-3 proxy, and stage 4 plans the explicit access.
    problems.extend(level_screen_problems(records))
    proxy = cheap_proxy(diag, records, ctx)
    if problems:
        return CheapEvaluation(
            points=built.points,
            diagnostics=diag,
            level_service=records,
            cheap_proxy=proxy,
            problems=problems,
            status=CandidateStatus.INFEASIBLE,
            failure_reasons=[p[0].value for p in problems],
            failure_detail="; ".join(p[1] for p in problems),
            access_screen=None,
            derived=built.derived,
            pieces=built.pieces,
        )
    # Phase 20C.1-Q: evaluator-free geometric access screen on the
    # delivered polyline (coarse-stand-off anchors) — the stage-3
    # ordering prefix (rule 176); it never rejects, stage 4 decides
    anchors = build_anchors(sc, screen_lens(sc), built.points)
    return CheapEvaluation(
        points=built.points,
        diagnostics=diag,
        level_service=records,
        cheap_proxy=proxy,
        problems=problems,
        status=CandidateStatus.NOT_VALIDATED,
        failure_reasons=[],
        failure_detail=None,
        access_screen=geometric_access_screen(
            built.points,
            anchors,
            ctx.levels,
            sc.cfg.access,
            ctx.ramp,
            sc.shape,
            screen_authority(sc.world_policy),
        ),
        derived=built.derived,
        pieces=built.pieces,
    )


def detailed_stage(
    sc: StageContext, cand: CandidateResult, cheap: CheapEvaluation
) -> DetailedEvaluation:
    """Stage 4 for ONE shortlisted candidate. ``cand`` is READ ONLY — its
    delivered centerline and its id — and the outcome is returned; only
    ``apply_detailed`` writes it back.

    The cheap outcome is a required argument, so a candidate that never
    completed stage 2 cannot reach here by type. A cheap outcome that FAILED
    is refused explicitly (I4): the shortlist is drawn from
    ``NOT_VALIDATED`` candidates only, so this is unreachable by
    construction — which is exactly why it must not be an ``assert``."""
    if cheap.problems:
        raise ValueError(
            f"candidate '{cand.candidate_id}' failed the cheap stage and cannot be validated"
        )
    ctx = sc.ctx
    req_clear = sc.required_clearance
    if cand.points is None or cand.diagnostics is None:
        raise ValueError(f"candidate '{cand.candidate_id}' never completed the cheap stage")
    clearance = _certify(sc, cand)
    evaluator, policy, refinement = clearance.evaluator, clearance.policy, clearance.refinement
    report = validate_delivered_centerline(evaluator, cand.points)
    validation = report.to_dict()
    # clearance under the candidate's policy (EXACT, COARSE_CONSERVATIVE
    # or the stage-4 REFINED_CONSERVATIVE window)
    conservative_min = float(np.min(report.orebody_distance))
    approx_min: float | None = None
    bound: float | None = None
    if policy.basis != "EXACT":
        bound = float(policy.error_bound)
        approx_min = conservative_min + bound
    clear_ok = conservative_min >= req_clear - 1e-9
    clearance_report = ClearanceReport(
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
    anchors: list[LevelDevelopmentAnchor | AnchorFailure | None] = []
    access_plan: LevelAccessPlan | None = None
    if not problems:
        anchors = build_anchors(sc, detailed_lens(sc, clearance), cand.points)
        access_plan = plan_level_accesses(
            cand.points,
            anchors,
            ctx.levels,
            sc.cfg.access,
            sc.scenario.ramp,
            evaluator,
            sc.shape,
            req_clear,
        )
        if not access_plan.feasible:
            failed = [a for a in access_plan.accesses if not a.ok]
            problems.append(
                (
                    InfeasibleReason.LEVEL_ACCESS_INFEASIBLE,
                    f"{len(failed)} of {len(access_plan.accesses)} required levels "
                    "have no valid ramp junction + level access ("
                    + ", ".join(f"{a.level_id}: {a.failure_reason}" for a in failed)
                    + ")",
                )
            )
    measured = measure_exposure([cand.points], sc.world.faults, sc.world_evaluator.rock_quality)
    exposure = {
        "faultCrossings": measured.fault_crossings,
        "lengthFaultCore": measured.length_fault_core,
        "lengthFaultDamage": measured.length_fault_damage,
        "lengthPoorRock": measured.length_poor_rock,
        "totalLength": measured.total_length,
        "fieldCost": report.field_cost,
    }
    # ``score_candidate`` reads four fields of a candidate record; it is given
    # a READ-ONLY view carrying this stage's own values, so scoring never
    # depends on whether the record has been written yet
    scored = replace(
        cand,
        diagnostics=cheap.diagnostics,
        level_service=cheap.level_service,
        clearance=clearance_report,
        access_plan=access_plan,
    )
    scores = score_candidate(scored, ctx, exposure, sc.cfg.weights)
    if problems:
        status = CandidateStatus.INFEASIBLE
        failure_reasons = sorted({p[0].value for p in problems})
        failure_detail: str | None = "; ".join(p[1] for p in problems)
    else:
        status = CandidateStatus.FEASIBLE
        failure_reasons = []
        failure_detail = None
    return DetailedEvaluation(
        clearance=clearance_report,
        validation=validation,
        scores=scores,
        exposure=exposure,
        anchors=anchors,
        access_plan=access_plan,
        status=status,
        failure_reasons=failure_reasons,
        failure_detail=failure_detail,
    )


# --------------------------------------------------------------------------- #
# The only two writers of a persisted CandidateResult (AC-01G I4)
# --------------------------------------------------------------------------- #


def apply_cheap(cand: CandidateResult, ev: CheapEvaluation) -> None:
    """Write a stage-2 outcome onto the persisted record — the SAME fields,
    the same values, in the same order the mutating stage used.

    The transition is refused explicitly when the record has already moved
    past CONSTRUCT: never an ``assert``, which ``python -O`` removes."""
    if cand.stage_reached != Stage.CONSTRUCT:
        raise ValueError(
            f"candidate '{cand.candidate_id}' is at stage {cand.stage_reached}, "
            "not CONSTRUCT: a cheap outcome cannot be applied to it"
        )
    cand.stage_reached = Stage.CHEAP
    cand.points = ev.points
    cand.pieces = ev.pieces
    cand.derived = ev.derived
    cand.diagnostics = ev.diagnostics
    cand.level_service = ev.level_service
    cand.cheap_proxy = ev.cheap_proxy
    cand.status = ev.status
    cand.failure_reasons = ev.failure_reasons
    cand.failure_detail = ev.failure_detail
    cand.access_screen = ev.access_screen


def apply_detailed(cand: CandidateResult, ev: DetailedEvaluation) -> None:
    """Write a stage-4 outcome onto the persisted record — the SAME fields,
    the same values, in the same order the mutating stage used.

    Only a cheap-feasible record that has not been validated yet can receive
    one; anything else is refused explicitly (I4)."""
    if (cand.stage_reached, cand.status) != (Stage.CHEAP, CandidateStatus.NOT_VALIDATED):
        raise ValueError(
            f"candidate '{cand.candidate_id}' is ({cand.stage_reached}, {cand.status}), "
            f"not ({Stage.CHEAP}, {CandidateStatus.NOT_VALIDATED}): "
            "a detailed outcome cannot be applied to it"
        )
    cand.stage_reached = Stage.DETAILED
    cand.validation = ev.validation
    cand.clearance = ev.clearance
    cand.anchors = ev.anchors
    cand.access_plan = ev.access_plan
    cand.exposure = ev.exposure
    cand.scores = ev.scores
    cand.status = ev.status
    cand.failure_reasons = ev.failure_reasons
    cand.failure_detail = ev.failure_detail
