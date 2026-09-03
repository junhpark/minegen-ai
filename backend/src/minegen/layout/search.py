"""Layout-v2 hierarchical search (Phase 20A, directive §25–28).

    STAGE 1  finite parametric enumeration            (families.enumerate_candidates)
    STAGE 2  cheap evaluation on the delivered centerline: gradient, plan
             radius, world bounds, monotonic descent, level service
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
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.core.models import (
    DesignConfig,
    LayoutV2Config,
    RampConstraints,
    Scenario,
    TunnelProfile,
)
from minegen.design.constraints import DesignContext, RejectionReason
from minegen.design.cost_field import (
    ClearancePolicy,
    DesignCostEvaluator,
    clearance_policy_for,
)
from minegen.design.exposure import measure_exposure
from minegen.design.progress import ProgressCallback, ProgressEvent, ProgressStage, no_progress
from minegen.design.targets import default_portal
from minegen.layout.families import (
    FAMILY_ORDER,
    CandidateParams,
    FamilyGeometry,
    FamilyInfeasible,
    InfeasibleReason,
    LayoutContext,
    build_family,
    build_footwall_track,
    enumerate_candidates,
)
from minegen.layout.geometry import (
    CenterlineDiagnostics,
    Crossing,
    analyze_centerline,
    find_crossing,
    insert_vertices,
    split_at,
)
from minegen.layout.levels import LevelSections, RequiredLevel, required_levels
from minegen.layout.validation import validate_delivered_centerline
from minegen.world.synthetic_world import SyntheticWorld

FloatArray = npt.NDArray[np.float64]

LAYOUT_V2_VERSION = 1
SOURCE_KIND_PARAMETRIC_V2 = "PARAMETRIC_V2"
#: owning artifact name of a materialized layout-v2 effective ramp
LAYOUT_V2_SELECTED_ARTIFACT = "layout_v2_selected.json"

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
#: score ties within this tolerance fall through to the family-order and
#: candidate-id tie-breaks (§28)
SCORE_TIE_TOLERANCE = 1e-9
#: plan-radius numerical tolerance on the delivered centerline (rule 62)
RADIUS_TOLERANCE = 0.05
#: gradient numerical tolerance on the delivered centerline
GRADIENT_TOLERANCE = 1e-9


class CandidateStatus:
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    NOT_VALIDATED = "NOT_VALIDATED"  # cheap-feasible but outside the shortlist


class Stage:
    CONSTRUCT = "CONSTRUCT"
    CHEAP = "CHEAP"
    DETAILED = "DETAILED"


@dataclass
class LevelServiceRecord:
    level_id: str
    elevation: float
    served: bool
    connection_position: FloatArray | None = None
    connection_chainage: float | None = None
    access_distance: float | None = None
    unserved_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "levelId": self.level_id,
            "elevation": self.elevation,
            "served": self.served,
            "connectionPosition": (
                [float(v) for v in self.connection_position]
                if self.connection_position is not None
                else None
            ),
            "connectionChainage": self.connection_chainage,
            "accessDistance": self.access_distance,
            "unservedReason": self.unserved_reason,
        }


@dataclass
class ClearanceReport:
    basis: str
    required: float
    conservative_minimum: float
    approximate_minimum: float | None
    error_bound: float | None
    satisfied: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "clearanceBasis": self.basis,
            "requiredClearance": self.required,
            "conservativeMinimumClearance": self.conservative_minimum,
            "approximateMinimumClearance": self.approximate_minimum,
            "clearanceErrorBound": self.error_bound,
            "satisfied": self.satisfied,
        }


@dataclass
class Scores:
    development: float
    geology: float
    geometry: float
    total: float
    components: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "development": self.development,
            "geology": self.geology,
            "geometry": self.geometry,
            "total": self.total,
            "components": dict(self.components),
        }


@dataclass
class CandidateResult:
    params: CandidateParams
    status: str = CandidateStatus.INFEASIBLE
    stage_reached: str = Stage.CONSTRUCT
    failure_reasons: list[str] = field(default_factory=list)
    failure_detail: str | None = None
    diagnostics: CenterlineDiagnostics | None = None
    level_service: list[LevelServiceRecord] = field(default_factory=list)
    scores: Scores | None = None
    clearance: ClearanceReport | None = None
    exposure: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    derived: dict[str, Any] = field(default_factory=dict)
    pieces: list[dict[str, Any]] = field(default_factory=list)
    points: FloatArray | None = None
    crossings: list[Crossing | None] = field(default_factory=list)
    shortlisted: bool = False
    cheap_proxy: float | None = None
    rank: int | None = None

    @property
    def candidate_id(self) -> str:
        return self.params.candidate_id

    @property
    def served_count(self) -> int:
        return sum(1 for r in self.level_service if r.served)

    def to_dict(self, *, include_points: bool) -> dict[str, Any]:
        d: dict[str, Any] = {
            "candidateId": self.candidate_id,
            "family": self.params.family.value,
            "parameters": self.params.to_dict(),
            "status": self.status,
            "stageReached": self.stage_reached,
            "failureReasons": list(self.failure_reasons),
            "failureDetail": self.failure_detail,
            "shortlisted": self.shortlisted,
            "rank": self.rank,
            "servedLevels": self.served_count,
            "requiredLevels": len(self.level_service),
            "levelService": [r.to_dict() for r in self.level_service],
            "diagnostics": self.diagnostics.to_dict() if self.diagnostics else None,
            "scores": self.scores.to_dict() if self.scores else None,
            "clearance": self.clearance.to_dict() if self.clearance else None,
            "exposure": self.exposure,
            "validation": self.validation,
            "derived": _finite_dict(self.derived),
            "pieces": self.pieces,
            "cheapProxy": self.cheap_proxy,
        }
        if include_points and self.points is not None:
            d["centerline"] = {
                "points": [float(v) for v in self.points.ravel()],
                "pointCount": int(self.points.shape[0]),
            }
        else:
            d["centerline"] = None
        return d


def _finite_dict(d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, float | np.floating):
            out[k] = float(v) if math.isfinite(float(v)) else None
        elif isinstance(v, np.integer):
            out[k] = int(v)
        elif isinstance(v, np.bool_):
            out[k] = bool(v)
        else:
            out[k] = v
    return out


@dataclass
class LayoutSearchResult:
    levels: list[RequiredLevel]  # every required level from the generic generator
    serviceable_ids: list[str]  # those intersecting the orebody solid
    track: dict[str, Any] | None
    portal: FloatArray
    portal_generated: bool
    candidates: list[CandidateResult]
    shortlist: list[str]
    ranking: list[str]
    winner_id: str | None
    clearance_basis: str
    clearance_error_bound: float
    required_clearance: float
    access_reach: float
    standoff: float
    performance: dict[str, Any]
    config: dict[str, Any]

    @property
    def serviceable_levels(self) -> list[RequiredLevel]:
        return [lv for lv in self.levels if lv.level_id in self.serviceable_ids]

    def candidate(self, candidate_id: str) -> CandidateResult | None:
        for c in self.candidates:
            if c.candidate_id == candidate_id:
                return c
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "layoutVersion": LAYOUT_V2_VERSION,
            "status": "SUCCESS" if self.winner_id is not None else "NO_FEASIBLE_CANDIDATE",
            "portal": [float(v) for v in self.portal],
            "portalGenerated": self.portal_generated,
            "requiredLevels": [
                {
                    "levelId": lv.level_id,
                    "index": lv.index,
                    "elevation": lv.elevation,
                    "hasOrebodySection": lv.level_id in self.serviceable_ids,
                }
                for lv in self.levels
            ],
            "serviceableLevelCount": len(self.serviceable_ids),
            "footwallTrack": self.track,
            "candidateCount": len(self.candidates),
            "feasibleCount": sum(
                1 for c in self.candidates if c.status == CandidateStatus.FEASIBLE
            ),
            "shortlist": list(self.shortlist),
            "ranking": list(self.ranking),
            "winnerId": self.winner_id,
            "clearanceBasis": self.clearance_basis,
            "clearanceErrorBound": self.clearance_error_bound,
            "requiredClearance": self.required_clearance,
            "accessReach": self.access_reach,
            "footwallStandoff": self.standoff,
            "performance": self.performance,
            "searchConfig": self.config,
            "candidates": [c.to_dict(include_points=c.shortlisted) for c in self.candidates],
        }


# --------------------------------------------------------------------------- #
# Stage helpers
# --------------------------------------------------------------------------- #


def required_clearance(cfg: DesignConfig, ramp: RampConstraints, profile: TunnelProfile) -> float:
    """Centerline clearance that keeps the whole excavation envelope outside
    the orebody exclusion buffer: buffer + the profile's farthest point from
    the floor centerline (half width sideways, full height up)."""
    return cfg.orebody_exclusion_buffer + math.hypot(ramp.tunnel_width / 2.0, ramp.tunnel_height)


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
        served = d <= reach
        records.append(
            LevelServiceRecord(
                lv.level_id,
                lv.elevation,
                served,
                connection_position=cr.point,
                connection_chainage=cr.chainage,
                access_distance=d,
                unserved_reason=None if served else InfeasibleReason.ACCESS_REACH_EXCEEDED.value,
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


def cheap_proxy(
    diag: CenterlineDiagnostics, records: list[LevelServiceRecord], ctx: LayoutContext
) -> float:
    """Stage-3 ordering proxy: length ratio + mean access ratio (the
    DEVELOPMENT group without the evaluator)."""
    drop = float(ctx.portal[2] - ctx.z_last)
    ideal = math.hypot(drop / ctx.ramp.max_gradient, drop)
    access = [r.access_distance for r in records if r.access_distance is not None]
    mean_access = float(np.mean(access)) if access else ctx.cfg.access_reach
    return diag.length3d / ideal + DEV_ACCESS_COEF * mean_access / ctx.cfg.access_reach


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
    length_ratio = diag.length3d / ideal
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
    geometry = (
        unused_grade
        + GEOM_TURNING_COEF * turning_frac
        + max_access / reach
        + GEOM_CLEARANCE_COEF * headroom
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
            "meanAccessRatio": mean_access / reach,
            "maxAccessRatio": max_access / reach,
            "faultCoreFraction": core_frac,
            "faultDamageFraction": damage_frac,
            "poorRockFraction": poor_frac,
            "faultCrossings": float(exposure["faultCrossings"]),
            "unusedGradient": unused_grade,
            "turningFraction": turning_frac,
            "clearanceHeadroom": headroom,
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

    def run(self, on_progress: ProgressCallback = no_progress) -> LayoutSearchResult:
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
        track = build_footwall_track(world.orebody, sections)
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
        serviceable = sections.serviceable()
        if not serviceable or track is None:
            for c in results:
                c.failure_reasons = [InfeasibleReason.NO_REQUIRED_LEVELS.value]
                c.failure_detail = "no required level intersects the orebody solid"
            perf["totalSeconds"] = time.perf_counter() - t0
            return self._result(
                levels, sections, portal, generated, results, [], [], None, req_clear, perf, None
            )
        ctx = LayoutContext(
            portal,
            serviceable,
            sections,
            track,
            sc.ramp,
            self.cfg,
            sc.world.size_x / 2.0,
            sc.world.size_y / 2.0,
        )

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
            self._cheap_stage(cand, built, ctx)
            on_progress(
                _event(ProgressStage.CANDIDATE_COMPLETED, i, n, cand.candidate_id, cand.status)
            )
        t_cheap = time.perf_counter()
        perf["constructAndCheapSeconds"] = t_cheap - t_setup

        # -- STAGE 3: bounded shortlist --------------------------------------- #
        cheap_ok = [c for c in results if c.status == CandidateStatus.NOT_VALIDATED]
        cheap_ok.sort(key=lambda c: (c.cheap_proxy or math.inf, _family_rank(c), c.candidate_id))
        shortlist = cheap_ok[: self.cfg.shortlist_size]
        for c in shortlist:
            c.shortlisted = True
        perf["shortlistSize"] = len(shortlist)

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
        standoff = (
            self.cfg.footwall_standoff
            if self.cfg.footwall_standoff is not None
            else self.scenario.ramp.footwall_access_offset
        )
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
        self, cand: CandidateResult, built: FamilyGeometry, ctx: LayoutContext
    ) -> None:
        cand.stage_reached = Stage.CHEAP
        cand.points = built.points
        cand.pieces = built.pieces
        cand.derived = built.derived
        diag = analyze_centerline(built.points)
        cand.diagnostics = diag
        problems = cheap_checks(diag, built.points, ctx.ramp, ctx.world_half_x, ctx.world_half_y)
        records, crossings = level_service(
            built.points, ctx.levels, ctx.sections, ctx.cfg.access_reach
        )
        cand.level_service = records
        cand.crossings = crossings
        unserved = [r for r in records if not r.served]
        if unserved:
            reasons = sorted({r.unserved_reason or "" for r in unserved})
            problems.append(
                (
                    InfeasibleReason.LEVEL_SERVICE_INFEASIBLE,
                    f"{len(unserved)} of {len(records)} required levels unserved "
                    f"({', '.join(reasons)})",
                )
            )
        cand.cheap_proxy = cheap_proxy(diag, records, ctx)
        if problems:
            cand.status = CandidateStatus.INFEASIBLE
            cand.failure_reasons = [p[0].value for p in problems]
            cand.failure_detail = "; ".join(p[1] for p in problems)
        else:
            cand.status = CandidateStatus.NOT_VALIDATED

    def _detailed_stage(self, cand: CandidateResult, ctx: LayoutContext, req_clear: float) -> None:
        assert cand.points is not None and cand.diagnostics is not None
        cand.stage_reached = Stage.DETAILED
        report = validate_delivered_centerline(self.evaluator, cand.points)
        cand.validation = report.to_dict()
        # clearance under the evaluator's policy (EXACT or CONSERVATIVE)
        conservative_min = float(np.min(report.orebody_distance))
        approx_min: float | None = None
        bound: float | None = None
        if self.policy.basis == "CONSERVATIVE":
            bound = float(self.policy.error_bound)
            approx_min = conservative_min + bound
        clear_ok = conservative_min >= req_clear - 1e-9
        cand.clearance = ClearanceReport(
            self.policy.basis, req_clear, conservative_min, approx_min, bound, clear_ok
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
                    f"{req_clear:.2f} m ({self.policy.basis})",
                )
            )
        # connection points must themselves be valid samples (§6)
        for rec, cr in zip(cand.level_service, cand.crossings, strict=True):
            if cr is None:
                continue
            if not report.point_valid(cr.point):
                rec.served = False
                rec.unserved_reason = InfeasibleReason.CONNECTION_POINT_INVALID.value
                problems.append(
                    (
                        InfeasibleReason.CONNECTION_POINT_INVALID,
                        f"{rec.level_id} connection invalid",
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


# --------------------------------------------------------------------------- #
# Effective ramp materialization (rule 149)
# --------------------------------------------------------------------------- #


def materialize_effective_ramp(
    result: LayoutSearchResult,
    cand: CandidateResult,
    evaluator: DesignCostEvaluator,
    source_revision: str,
) -> dict[str, Any]:
    """Split the validated delivered centerline at the EXACT level connection
    points into Effective Ramp segments in the source-neutral contract the
    downstream consumers read (``segments[].effectiveCenterline`` etc.).
    Each segment owns one level; consecutive segments share their boundary
    vertex and 3-D tangent. No smoothing, no re-sampling: the geometry is
    the validated candidate centerline itself."""
    if cand.status != CandidateStatus.FEASIBLE or cand.points is None:
        raise ValueError(f"candidate {cand.candidate_id} is not FEASIBLE")
    levels = result.serviceable_levels
    crossings = [c for c in cand.crossings if c is not None]
    if len(crossings) != len(levels):
        raise ValueError("a FEASIBLE candidate must cross every serviceable required level")
    pts, idx = insert_vertices(cand.points, crossings)
    pieces = split_at(pts, idx)
    segments: list[dict[str, Any]] = []
    raw_total = 0.0
    cost_total = 0.0
    max_grade = 0.0
    radii: list[float] = []
    for k, (piece, lv) in enumerate(zip(pieces, levels, strict=True)):
        # boundary tangents: chord directions, shared at the split vertices
        start_t = _tangent(pts, idx[k - 1] if k > 0 else 0, shared=k > 0)
        end_t = _tangent(pts, idx[k], shared=k < len(pieces) - 1)
        diag = analyze_centerline(piece) if piece.shape[0] >= 2 else None
        ev = evaluator.evaluate_points(piece)
        finite = ev.base_cost + ev.rock_penalty + ev.fault_penalty + ev.orebody_penalty
        seg_len = np.linalg.norm(np.diff(piece, axis=0), axis=1)
        mid_cost = 0.5 * (finite[:-1] + finite[1:])
        field_cost = float(np.sum(mid_cost * seg_len))
        length = float(np.sum(seg_len))
        raw_total += length
        cost_total += field_cost
        if diag is not None:
            max_grade = max(max_grade, diag.max_abs_gradient)
            if diag.min_plan_radius is not None:
                radii.append(diag.min_plan_radius)
        segments.append(
            {
                "levelId": lv.level_id,
                "candidateId": cand.candidate_id,
                "smoothed": None,
                "effectiveSource": SOURCE_KIND_PARAMETRIC_V2,
                "effectiveCenterline": {
                    "points": [float(v) for v in piece.ravel()],
                    "pointCount": int(piece.shape[0]),
                },
                "boundaryTangents": {
                    "start": [float(v) for v in start_t],
                    "end": [float(v) for v in end_t],
                },
                "levelConnection": {
                    "levelId": lv.level_id,
                    "elevation": lv.elevation,
                    "position": [float(v) for v in piece[-1]],
                    "chainage": crossings[k].chainage,
                    "accessDistance": cand.level_service[k].access_distance,
                },
                "report": {
                    "rawLength": length,
                    "smoothedLength": None,
                    "fieldCostRaw": field_cost,
                    "fieldCostSmoothed": None,
                    "fieldCostDeltaPct": None,
                    "maxGradient": diag.max_abs_gradient if diag else 0.0,
                    "minPlanRadius": diag.min_plan_radius if diag else None,
                    "maxDeviationFromRaw": 0.0,
                    "endpointPositionError": 0.0,
                    "startHeadingErrorDeg": 0.0,
                    "endHeadingErrorDeg": 0.0,
                    "invalidSampleCount": 0,
                    "rejectionReasonCounts": {},
                    "monotonicityViolations": 0,
                    "gradeViolations": 0,
                    "radiusViolations": 0,
                    "corridorViolations": 0,
                    "repairs": 0,
                    "valid": True,
                    "effectiveSource": SOURCE_KIND_PARAMETRIC_V2,
                    "fallbackReason": None,
                },
            }
        )
    return {
        "status": "SUCCESS",
        "sourceKind": SOURCE_KIND_PARAMETRIC_V2,
        "sourceRevision": source_revision,
        "candidateId": cand.candidate_id,
        "family": cand.params.family.value,
        "failureReason": None,
        "portal": [float(v) for v in result.portal],
        "segments": segments,
        "levelConnections": [s["levelConnection"] for s in segments],
        "totals": {
            "segments": len(segments),
            "smoothedSegments": 0,
            "fallbackSegments": 0,
            "rawLength": raw_total,
            "effectiveLength": raw_total,
            "fieldCostRaw": cost_total,
            "fieldCostEffective": cost_total,
            "fieldCostDeltaPct": None,
            "maxGradient": max_grade,
            "minimumPlanRadius": float(min(radii)) if radii else None,
            "maxDeviation": 0.0,
        },
        "diagnostics": cand.diagnostics.to_dict() if cand.diagnostics else None,
        "clearance": cand.clearance.to_dict() if cand.clearance else None,
        "scores": cand.scores.to_dict() if cand.scores else None,
    }


def _tangent(pts: FloatArray, vertex: int, *, shared: bool) -> FloatArray:
    """Unit 3-D tangent at a vertex: mean of the incoming and outgoing chord
    directions when the vertex is shared by two segments, otherwise the
    single available chord (portal start / terminal end)."""
    n = pts.shape[0]
    dirs: list[FloatArray] = []
    if vertex > 0:
        d = pts[vertex] - pts[vertex - 1]
        dirs.append(d / max(float(np.linalg.norm(d)), 1e-12))
    if vertex < n - 1:
        d = pts[vertex + 1] - pts[vertex]
        dirs.append(d / max(float(np.linalg.norm(d)), 1e-12))
    if not shared and vertex == 0 and len(dirs) > 1:
        dirs = dirs[1:]
    if not shared and vertex == n - 1 and len(dirs) > 1:
        dirs = dirs[:1]
    t = np.sum(np.asarray(dirs), axis=0)
    return np.asarray(t / max(float(np.linalg.norm(t)), 1e-12))
