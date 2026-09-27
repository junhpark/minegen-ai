"""CUT_AND_FILL production geometry (Phase 21B).

Consumes the validated ``levels.json`` ONLY. Every level carries exactly one
central production access CROSSCUT (the Cut & Fill access pattern); the
paired access terminals of two adjacent levels bound the ore INTERVAL in
the analytic TABULAR local frame ``(u, v, w)``:

    interval  v ∈ [v(upper terminal), v(lower terminal)]
    lift      an EQUAL PARTITION of the interval into ≈ liftHeightM VERTICAL
              slices (local dv = liftHeightM / |v_z| per lift)
    cut       an EQUAL PARTITION of the strike extent u ∈ [−L/2, L/2] into
              ≈ cutLengthM pieces; w spans the full thickness

Sequence (a deterministic method-sequencing BASELINE, never an optimization):
intervals bottom → top, lifts bottom → top, cuts in a snake — even lifts
−u → +u, odd lifts +u → −u. Each cut has exactly ONE backfill that
REFERENCES the cut's void geometry (``sourceCutId``); vertices are never
persisted twice. TABULAR orebodies only: an implicit / ellipsoid body is a
typed METHOD_GEOMETRY_NOT_IMPLEMENTED failure, never a Longhole fallback.
"""

from __future__ import annotations

import math
from itertools import pairwise
from typing import Any

import numpy as np

from minegen.core.enums import MiningMethodType, ObjectState, TaskType
from minegen.core.models import CutFillParameters, Scenario
from minegen.design.cost_field import DesignCostEvaluator
from minegen.levels.models import ProductionDevelopment
from minegen.mining.methods.contracts import (
    FixedAccessPattern,
    ImplementationStatus,
    ProductionAccessPattern,
    ProductionScheduleContext,
    ProductionScheduleSpec,
    ProductionStateSpec,
    ProductionTaskSpec,
    ProductionUnitSpec,
)
from minegen.mining.methods.schedule_support import access_task_for, fixed_days_task, rate_task
from minegen.mining.methods.solids import (
    MAX_PRODUCTION_SOLIDS,
    build_solid,
    central_access_by_level,
    equal_partition,
    frame_triangles,
    grade_proxy,
    weighted_grade,
)
from minegen.mining.models import (
    CutFillBackfill,
    CutFillCut,
    CutFillLift,
    CutFillMetrics,
    CutFillPayload,
    LocalBounds,
)
from minegen.scheduling.models import ProductionTargetKind
from minegen.world.orebody import TabularOrebody
from minegen.world.synthetic_world import SyntheticWorld

METHOD = MiningMethodType.CUT_AND_FILL


def _failed(source_revision: str, reason: str) -> CutFillPayload:
    return CutFillPayload(
        status="FAILED",
        failure_reason=reason,
        source_revision=source_revision,
        method="CUT_AND_FILL",
        lifts=[],
        cuts=[],
        backfills=[],
        metrics=None,
    )


def cut_id(lower: str, upper: str, lift_index: int, cut_index: int) -> str:
    return f"CUT:{lower}-{upper}:LF{lift_index:02d}:C{cut_index:02d}"


def backfill_id(cut: str) -> str:
    return "BACKFILL:" + cut.removeprefix("CUT:")


def generate_cut_fill(
    scenario: Scenario,
    world: SyntheticWorld,
    levels_payload: dict[str, Any],
    hard_evaluator: DesignCostEvaluator,
    source_revision: str,
) -> CutFillPayload:
    if levels_payload.get("status") != "SUCCESS":
        return _failed(
            source_revision,
            f"prerequisite levels artifact status {levels_payload.get('status')!r} is not "
            "consumable (rule 79)",
        )
    ob = world.orebody
    if not isinstance(ob, TabularOrebody):
        return _failed(
            source_revision,
            "METHOD_GEOMETRY_NOT_IMPLEMENTED: Cut & Fill production geometry is implemented "
            f"for TABULAR orebodies only ({type(ob).__name__} is deferred) — no fallback to "
            "another method's geometry",
        )
    params = scenario.mining.method_parameters
    if not isinstance(params, CutFillParameters):
        return _failed(source_revision, "scenario carries no CutFillParameters")
    v_z = abs(float(ob.v[2]))
    if v_z < 1e-9:
        return _failed(
            source_revision, "orebody is horizontal: a vertical lift has no down-dip span"
        )
    level_order = [str(lv["levelId"]) for lv in levels_payload["levels"]]
    if len(level_order) < 2:
        return _failed(
            source_revision, "at least two completed levels are required to span a lift interval"
        )
    access, access_failure = central_access_by_level(levels_payload)
    if access_failure is not None:
        return _failed(source_revision, access_failure)

    def terminal_v(dev: dict[str, Any]) -> float:
        pts = np.asarray(dev["centerline"]["points"], dtype=np.float64).reshape(-1, 3)
        return float(ob.to_local(pts[-1][None, :])[0][1])

    dv_target = float(params.lift_height_m) / v_z
    half_length = float(ob.half_length)
    u_pieces = equal_partition(-half_length, half_length, float(params.cut_length_m))
    # bottom interval first: level ids are listed top → bottom
    intervals = list(pairwise(level_order))[::-1]
    plan: list[tuple[str, str, list[tuple[float, float]]]] = []
    for upper_id, lower_id in intervals:
        v_a, v_b = sorted((terminal_v(access[upper_id]), terminal_v(access[lower_id])))
        lifts = equal_partition(v_a, v_b, dv_target)
        if not lifts:
            return _failed(
                source_revision, f"interval {upper_id}-{lower_id} has no down-dip span to lift"
            )
        plan.append((upper_id, lower_id, lifts[::-1]))  # deepest (largest v) lift first
    total_cuts = sum(len(lifts) for _, _, lifts in plan) * len(u_pieces)
    if total_cuts > MAX_PRODUCTION_SOLIDS:
        return _failed(
            source_revision,
            f"PRODUCTION_COMPLEXITY_LIMIT: {total_cuts} cuts exceed the production solid "
            f"budget of {MAX_PRODUCTION_SOLIDS} — enlarge liftHeightM / cutLengthM; nothing "
            "is decimated silently",
        )

    triangles = frame_triangles(ob)
    density = float(scenario.orebody.density)
    w_min, w_max = -float(ob.half_thickness), float(ob.half_thickness)
    lifts_out: list[CutFillLift] = []
    cuts: list[CutFillCut] = []
    first_failure: str | None = None
    lift_index = 0
    for upper_id, lower_id, lifts in plan:
        for v0, v1 in lifts:
            ordered = u_pieces if lift_index % 2 == 0 else u_pieces[::-1]
            cut_ids: list[str] = []
            for cut_index, (u0, u1) in enumerate(ordered):
                bounds = LocalBounds(
                    u_min=u0, u_max=u1, v_min=v0, v_max=v1, w_min=w_min, w_max=w_max
                )
                proxy = grade_proxy(world, ob, bounds)
                built = build_solid(ob, bounds, triangles, hard_evaluator, extra_values=(proxy,))
                cid = cut_id(lower_id, upper_id, lift_index, cut_index)
                if built.report.failure_reason is not None and first_failure is None:
                    first_failure = f"{cid}: {built.report.failure_reason}"
                cuts.append(
                    CutFillCut(
                        id=cid,
                        method="CUT_AND_FILL",
                        lift_index=lift_index,
                        cut_index=cut_index,
                        lower_level_id=lower_id,
                        upper_level_id=upper_id,
                        access_development_id=str(access[lower_id]["id"]),
                        local_bounds=bounds,
                        geometry=built.geometry,
                        strike_length=u1 - u0,
                        down_dip_span=v1 - v0,
                        vertical_height=(v1 - v0) * v_z,
                        thickness=w_max - w_min,
                        geometric_volume_m3=built.volume,
                        tonnes=built.volume * density,
                        mean_grade_proxy=proxy,
                        report=built.report,
                    )
                )
                cut_ids.append(cid)
            lifts_out.append(
                CutFillLift(
                    lift_index=lift_index,
                    lower_level_id=lower_id,
                    upper_level_id=upper_id,
                    v_min=v0,
                    v_max=v1,
                    vertical_height=(v1 - v0) * v_z,
                    cut_ids=cut_ids,
                )
            )
            lift_index += 1
    backfills = [
        CutFillBackfill(id=backfill_id(c.id), source_cut_id=c.id, volume_m3=c.geometric_volume_m3)
        for c in cuts
    ]
    total_v = float(math.fsum(c.geometric_volume_m3 for c in cuts))
    total_t = float(math.fsum(c.tonnes for c in cuts))
    orebody_v = 8.0 * ob.half_length * ob.half_height * ob.half_thickness
    metrics = CutFillMetrics(
        cut_count=len(cuts),
        backfill_count=len(backfills),
        lift_count=len(lifts_out),
        level_interval_count=len(plan),
        total_geometric_volume_m3=total_v,
        total_tonnes=total_t,
        geometric_extraction_fraction_of_orebody=total_v / orebody_v if orebody_v > 0 else 0.0,
        weighted_mean_grade_proxy=weighted_grade([(c.mean_grade_proxy, c.tonnes) for c in cuts]),
        actual_mean_lift_height=(
            float(math.fsum(lf.vertical_height for lf in lifts_out) / len(lifts_out))
            if lifts_out
            else 0.0
        ),
        actual_mean_cut_length=(
            float(math.fsum(c.strike_length for c in cuts) / len(cuts)) if cuts else 0.0
        ),
    )
    return CutFillPayload(
        status="SUCCESS" if first_failure is None else "FAILED",
        failure_reason=first_failure,
        source_revision=source_revision,
        method="CUT_AND_FILL",
        lifts=lifts_out,
        cuts=cuts,
        backfills=backfills,
        metrics=metrics,
    )


class CutFillPlan:
    """The CUT_AND_FILL ``MiningMethodPlan`` (Phase 21B): one central
    production access per level, lifts + cuts + referenced backfills."""

    method = METHOD
    implementation_status: ImplementationStatus = "IMPLEMENTED"
    display_name = "Cut & Fill"

    def production_development(self, scenario: Scenario) -> ProductionDevelopment:
        return ProductionDevelopment(method=self.method.value, status="IMPLEMENTED")

    def production_access_pattern(self, scenario: Scenario) -> ProductionAccessPattern | None:
        return FixedAccessPattern()

    def generate_production(
        self,
        scenario: Scenario,
        world: SyntheticWorld,
        levels_payload: dict[str, Any],
        hard_evaluator: DesignCostEvaluator,
        source_revision: str,
    ) -> CutFillPayload:
        return generate_cut_fill(scenario, world, levels_payload, hard_evaluator, source_revision)

    def production_identity(self, production_payload: dict[str, Any]) -> tuple[list[str], str]:
        return [c["id"] for c in production_payload["cuts"]], "cut"

    def production_schedule(
        self,
        scenario: Scenario,
        production_payload: dict[str, Any],
        ctx: ProductionScheduleContext,
    ) -> ProductionScheduleSpec | str:
        """ONE conservative Cut & Fill chain over the persisted cut order
        (lowest lift first, cuts along strike, snake): every cut runs
        PREP → STOPING → MUCKING → BACKFILL → CURE, its preparation depends
        on the development task of its own production access AND on the
        previous cut's cure — so a lift is only mined once the lift below is
        fully backfilled and cured, and no two cuts are worked at once.
        A deterministic sequencing BASELINE (rule 82), never a resource
        optimization; rates come from ``scenario.schedule`` only."""
        sch = ctx.schedule
        tasks: list[ProductionTaskSpec] = []
        units: list[ProductionUnitSpec] = []
        previous_cure: str | None = None
        kind: ProductionTargetKind = "CUT"
        for cut in production_payload["cuts"]:
            cid = str(cut["id"])
            access_task = access_task_for(cut, ctx.development_task_by_edge, "cut")
            if access_task.startswith("!"):
                return access_task[1:]
            tonnes = float(cut["tonnes"])
            volume = float(cut["geometricVolumeM3"])
            prep_deps = sorted({access_task} | ({previous_cure} if previous_cure else set()))
            chain = [
                fixed_days_task(
                    f"TASK:PREP:{cid}",
                    TaskType.STOPE_PREPARATION,
                    kind,
                    cid,
                    float(sch.stope_preparation_days),
                    prep_deps,
                ),
                rate_task(
                    f"TASK:STOPING:{cid}",
                    TaskType.STOPING,
                    kind,
                    cid,
                    tonnes,
                    "t",
                    float(sch.stoping_tonnes_per_day),
                    [f"TASK:PREP:{cid}"],
                ),
                rate_task(
                    f"TASK:MUCKING:{cid}",
                    TaskType.MUCKING,
                    kind,
                    cid,
                    tonnes,
                    "t",
                    float(sch.mucking_tonnes_per_day),
                    [f"TASK:STOPING:{cid}"],
                ),
                rate_task(
                    f"TASK:BACKFILL:{cid}",
                    TaskType.BACKFILL,
                    kind,
                    cid,
                    volume,
                    "m3",
                    float(sch.backfill_m3_per_day),
                    [f"TASK:MUCKING:{cid}"],
                ),
                fixed_days_task(
                    f"TASK:CURE:{cid}",
                    TaskType.CURE_BACKFILL,
                    kind,
                    cid,
                    float(sch.backfill_cure_days),
                    [f"TASK:BACKFILL:{cid}"],
                ),
            ]
            for task in chain:
                if not (task.duration_days > 0.0 and math.isfinite(task.duration_days)):
                    return f"non-positive duration for {task.id}"
            tasks.extend(chain)
            units.append(
                ProductionUnitSpec(
                    unit_id=cid,
                    transitions=[
                        ProductionStateSpec(f"TASK:STOPING:{cid}", "start", ObjectState.ACTIVE),
                        ProductionStateSpec(f"TASK:STOPING:{cid}", "end", ObjectState.MINED),
                        ProductionStateSpec(f"TASK:MUCKING:{cid}", "end", ObjectState.VOID),
                        ProductionStateSpec(f"TASK:BACKFILL:{cid}", "end", ObjectState.BACKFILLED),
                    ],
                )
            )
            previous_cure = f"TASK:CURE:{cid}"
        return ProductionScheduleSpec(
            target_kind=kind,
            tasks=tasks,
            units=units,
            tasks_per_unit=5,
            scheduled_tonnes=float(
                math.fsum(float(c["tonnes"]) for c in production_payload["cuts"])
            ),
        )
