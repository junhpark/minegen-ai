"""CUT_AND_FILL production geometry (Phase 21B, H2-CF block / panel
structure).

Consumes the validated ``levels.json`` ONLY. The strike extent of the
analytic TABULAR body is partitioned equally into PANELS of ≈ ``panelLengthM``
(rule 194 partition); every level carries one production access CROSSCUT per
panel (``PanelAccessPattern``: station index = panel index). Two adjacent
levels bound one level INTERVAL = one stope BLOCK; a block × a panel is the
schedule unit, and inside it the ore is mined in lifts × cuts in the
analytic local frame ``(u, v, w)``:

    block     v ∈ [v(upper access terminal), v(lower access terminal)],
              referenced at the central-most panel's accesses
    lift      an EQUAL PARTITION of the block interval into ≈ liftHeightM
              VERTICAL slices (local dv = liftHeightM / |v_z| per lift)
    panel     an EQUAL PARTITION of u ∈ [−L/2, L/2] into ≈ panelLengthM
              pieces; a rib pillar of ``ribPillarWidthM`` is carved out of
              the partition between adjacent panels (retained material)
    cut       an EQUAL PARTITION of the panel's MINED span into ≈ cutLengthM
              pieces; w spans the full thickness

Sequence (a deterministic method-sequencing BASELINE, never an
optimization): OVERHAND lifts bottom → top inside a block, cuts in a snake
(even lifts-in-block −u → +u, odd +u → −u); blocks in the declared
``blockOrder`` (SHALLOW_TO_DEEP: top interval first); panels of a block
centre-out (ties: the −u panel first). Under SHALLOW_TO_DEEP every block
above an unmined block mines its bottom lift onto a CEMENTED sill mat — the
backfill of that lift is ``cemented = true``. UNDERHAND stoping is a
declared axis this version refuses with the typed
UNSUPPORTED_STOPING_DIRECTION failure. Each cut has exactly ONE backfill
that REFERENCES the cut's void geometry (``sourceCutId``); vertices are
never persisted twice. TABULAR orebodies only: an implicit / ellipsoid body
is a typed METHOD_GEOMETRY_NOT_IMPLEMENTED failure, never a Longhole
fallback.
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
    ImplementationStatus,
    PanelAccessPattern,
    ProductionAccessPattern,
    ProductionScheduleContext,
    ProductionScheduleSpec,
    ProductionStateSpec,
    ProductionTaskSpec,
    ProductionUnitSpec,
)
from minegen.mining.methods.integrity import cut_fill_integrity
from minegen.mining.methods.schedule_support import access_task_for, fixed_days_task, rate_task
from minegen.mining.methods.solids import (
    MAX_PRODUCTION_SOLIDS,
    build_solid,
    equal_partition,
    frame_triangles,
    grade_proxy,
    weighted_grade,
)
from minegen.mining.models import (
    CutFillBackfill,
    CutFillBlock,
    CutFillCut,
    CutFillLift,
    CutFillMetrics,
    CutFillPanel,
    CutFillPayload,
    CutFillRibPillar,
    CutFillSequencing,
    LocalBounds,
)
from minegen.scheduling.models import ProductionTargetKind
from minegen.world.orebody import TabularOrebody
from minegen.world.synthetic_world import SyntheticWorld

METHOD = MiningMethodType.CUT_AND_FILL

#: agreement of a persisted crosscut station with the panel centre (m)
STATION_TOLERANCE = 1e-6


def _failed(source_revision: str, reason: str) -> CutFillPayload:
    return CutFillPayload(
        status="FAILED",
        failure_reason=reason,
        source_revision=source_revision,
        method="CUT_AND_FILL",
        sequencing=None,
        blocks=[],
        panels=[],
        lifts=[],
        cuts=[],
        backfills=[],
        rib_pillars=[],
        metrics=None,
    )


def block_id(lower: str, upper: str) -> str:
    return f"BLOCK:{lower}-{upper}"


def panel_id(lower: str, upper: str, panel_index: int) -> str:
    return f"PANEL:{lower}-{upper}:P{panel_index:02d}"


def cut_id(lower: str, upper: str, panel_index: int, lift_in_block: int, cut_index: int) -> str:
    return f"CUT:{lower}-{upper}:P{panel_index:02d}:LF{lift_in_block:02d}:C{cut_index:02d}"


def backfill_id(cut: str) -> str:
    return "BACKFILL:" + cut.removeprefix("CUT:")


def rib_pillar_id(lower: str, upper: str, boundary_index: int) -> str:
    """The rib pillar between panel ``boundary_index`` and ``boundary_index + 1``."""
    return f"PILLAR:{lower}-{upper}:R{boundary_index:02d}"


def panel_access_by_level(
    levels_payload: dict[str, Any], panel_centres: list[float]
) -> tuple[dict[str, dict[int, dict[str, Any]]], str | None]:
    """The production access CROSSCUT of every (level, panel), keyed by level
    id then panel index. The levels artifact must carry EXACTLY the panel
    partition's accesses (station index = panel index, station u = panel
    centre within ``STATION_TOLERANCE``); anything else — a station lattice,
    a missing panel, a stale partition — is a typed failure."""
    n = len(panel_centres)
    found: dict[str, dict[int, dict[str, Any]]] = {}
    for dev in levels_payload["developments"]:
        if dev["kind"] != "CROSSCUT":
            continue
        level = str(dev["levelId"])
        k = int(dev.get("stationIndex", -1))
        if not 0 <= k < n:
            return {}, (
                f"development {dev['id']} carries station index {k}, outside the panel "
                f"partition 0 … {n - 1} — the levels artifact does not carry this panel layout"
            )
        if abs(float(dev["stationU"]) - panel_centres[k]) > STATION_TOLERANCE:
            return {}, (
                f"development {dev['id']} sits at u = {float(dev['stationU']):.6f} m but panel "
                f"{k} is centred at {panel_centres[k]:.6f} m — stale panel partition"
            )
        per_level = found.setdefault(level, {})
        if k in per_level:
            return {}, f"level {level} carries two production accesses for panel {k}"
        per_level[k] = dev
    for lv in levels_payload["levels"]:
        level = str(lv["levelId"])
        have = sorted(found.get(level, {}))
        if have != list(range(n)):
            return {}, (
                f"level {level} carries production accesses for panels {have} but the panel "
                f"partition requires 0 … {n - 1}"
            )
    return found, None


def _unsupported_direction(direction: str) -> str:
    return (
        f"UNSUPPORTED_STOPING_DIRECTION: {direction} stoping is a declared Cut & Fill axis "
        "that this version does not implement (top → bottom slices under cemented fill need "
        "per-cut cemented fill, cure precedence and an attack ramp) — no fallback to OVERHAND"
    )


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
    if params.stoping_direction != "OVERHAND":
        return _failed(source_revision, _unsupported_direction(params.stoping_direction))
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
    half_length = float(ob.half_length)
    pattern = PanelAccessPattern(float(params.panel_length_m))
    panel_spans = pattern.panels(half_length)
    panel_centres = pattern.offsets(half_length)
    n_panels = len(panel_spans)
    if n_panels == 0:
        return _failed(source_revision, "orebody strike extent is not positive")
    access, access_failure = panel_access_by_level(levels_payload, panel_centres)
    if access_failure is not None:
        return _failed(source_revision, access_failure)
    rib = float(params.rib_pillar_width_m)
    panel_actual = 2.0 * half_length / n_panels
    if rib > 0.0 and rib >= panel_actual:
        return _failed(
            source_revision,
            f"RIB_PILLAR_TOO_WIDE: ribPillarWidthM {rib:g} m leaves no mined span inside the "
            f"{panel_actual:.3f} m panel partition ({n_panels} panels over {2 * half_length:g} m "
            "of strike) — nothing is clamped",
        )
    # the MINED span of every panel: half a rib pillar is carved from each
    # interior boundary
    mined_spans: list[tuple[float, float]] = []
    for i, (p0, p1) in enumerate(panel_spans):
        u0 = p0 + (0.5 * rib if i > 0 else 0.0)
        u1 = p1 - (0.5 * rib if i < n_panels - 1 else 0.0)
        mined_spans.append((u0, u1))
    # the central-most panel (ties → lower index) references the block interval
    central = min(range(n_panels), key=lambda i: (abs(panel_centres[i]), i))

    def terminal_v(dev: dict[str, Any]) -> float:
        pts = np.asarray(dev["centerline"]["points"], dtype=np.float64).reshape(-1, 3)
        return float(ob.to_local(pts[-1][None, :])[0][1])

    dv_target = float(params.lift_height_m) / v_z
    # level ids are listed top → bottom; intervals in the same (top-first) order
    intervals_top_first = list(pairwise(level_order))
    deepest = intervals_top_first[-1]
    block_plan: list[tuple[str, str, list[tuple[float, float]]]] = []  # top first
    for upper_id, lower_id in intervals_top_first:
        v_a, v_b = sorted(
            (terminal_v(access[upper_id][central]), terminal_v(access[lower_id][central]))
        )
        lifts = equal_partition(v_a, v_b, dv_target)
        if not lifts:
            return _failed(
                source_revision, f"interval {upper_id}-{lower_id} has no down-dip span to lift"
            )
        block_plan.append((upper_id, lower_id, lifts[::-1]))  # deepest lift first
    # cut partition per panel (identical for every lift of every block)
    cut_spans = [equal_partition(u0, u1, float(params.cut_length_m)) for u0, u1 in mined_spans]
    if any(not spans for spans in cut_spans):
        return _failed(source_revision, "a panel's mined span cannot hold one cut")
    total_lifts = sum(len(lifts) for _, _, lifts in block_plan)
    total_cuts = total_lifts * sum(len(spans) for spans in cut_spans)
    total_pillars = (n_panels - 1) * len(block_plan) if rib > 0.0 else 0
    if total_cuts + total_pillars > MAX_PRODUCTION_SOLIDS:
        return _failed(
            source_revision,
            f"PRODUCTION_COMPLEXITY_LIMIT: {total_cuts} cuts + {total_pillars} rib pillars "
            f"exceed the production solid budget of {MAX_PRODUCTION_SOLIDS} — enlarge "
            "liftHeightM / cutLengthM / panelLengthM; nothing is decimated silently",
        )

    # -- block / panel start orders (deterministic, rule 82) ---------------- #
    shallow_first = params.block_order == "SHALLOW_TO_DEEP"
    block_order_pairs = intervals_top_first if shallow_first else intervals_top_first[::-1]
    block_rank = {block_id(lo, up): r for r, (up, lo) in enumerate(block_order_pairs)}
    panel_centre_out = sorted(range(n_panels), key=lambda i: (abs(panel_centres[i]), i))
    panel_start_order: list[str] = [
        panel_id(lo, up, i) for up, lo in block_order_pairs for i in panel_centre_out
    ]
    panel_rank = {pid: r for r, pid in enumerate(panel_start_order)}

    # -- geometry ------------------------------------------------------------ #
    triangles = frame_triangles(ob)
    density = float(scenario.orebody.density)
    w_min, w_max = -float(ob.half_thickness), float(ob.half_thickness)
    blocks: list[CutFillBlock] = []
    panels: list[CutFillPanel] = []
    lifts_out: list[CutFillLift] = []
    cuts_by_panel: dict[str, list[CutFillCut]] = {}
    backfills_by_panel: dict[str, list[CutFillBackfill]] = {}
    rib_pillars: list[CutFillRibPillar] = []
    first_failure: str | None = None
    global_lift = 0
    # lifts are numbered from the deepest block upward (global index = world z order)
    for upper_id, lower_id in intervals_top_first[::-1]:
        lifts = next(lf for up, lo, lf in block_plan if (up, lo) == (upper_id, lower_id))
        bid = block_id(lower_id, upper_id)
        sill_mat_required = (
            params.block_order == "SHALLOW_TO_DEEP" and (upper_id, lower_id) != deepest
        )
        # lifts are listed deepest (largest v) first
        v_block_min, v_block_max = lifts[-1][0], lifts[0][1]
        block_lift_indices: list[int] = []
        block_panel_ids = [panel_id(lower_id, upper_id, i) for i in range(n_panels)]
        for pid in block_panel_ids:
            cuts_by_panel[pid] = []
            backfills_by_panel[pid] = []
        for lift_in_block, (v0, v1) in enumerate(lifts):
            lift_cut_ids: list[str] = []
            for p_index in range(n_panels):
                pid = block_panel_ids[p_index]
                ordered = cut_spans[p_index] if lift_in_block % 2 == 0 else cut_spans[p_index][::-1]
                for cut_index, (u0, u1) in enumerate(ordered):
                    bounds = LocalBounds(
                        u_min=u0, u_max=u1, v_min=v0, v_max=v1, w_min=w_min, w_max=w_max
                    )
                    proxy = grade_proxy(world, ob, bounds)
                    built = build_solid(
                        ob, bounds, triangles, hard_evaluator, extra_values=(proxy,)
                    )
                    cid = cut_id(lower_id, upper_id, p_index, lift_in_block, cut_index)
                    if built.report.failure_reason is not None and first_failure is None:
                        first_failure = f"{cid}: {built.report.failure_reason}"
                    cuts_by_panel[pid].append(
                        CutFillCut(
                            id=cid,
                            method="CUT_AND_FILL",
                            block_id=bid,
                            panel_id=pid,
                            panel_index=p_index,
                            lift_index=global_lift,
                            lift_index_in_block=lift_in_block,
                            cut_index=cut_index,
                            lower_level_id=lower_id,
                            upper_level_id=upper_id,
                            access_development_id=str(access[lower_id][p_index]["id"]),
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
                    backfills_by_panel[pid].append(
                        CutFillBackfill(
                            id=backfill_id(cid),
                            source_cut_id=cid,
                            volume_m3=built.volume,
                            cemented=sill_mat_required and lift_in_block == 0,
                        )
                    )
                    lift_cut_ids.append(cid)
            lifts_out.append(
                CutFillLift(
                    lift_index=global_lift,
                    block_id=bid,
                    lift_index_in_block=lift_in_block,
                    lower_level_id=lower_id,
                    upper_level_id=upper_id,
                    v_min=v0,
                    v_max=v1,
                    vertical_height=(v1 - v0) * v_z,
                    cut_ids=lift_cut_ids,
                )
            )
            block_lift_indices.append(global_lift)
            global_lift += 1
        for p_index in range(n_panels):
            pid = block_panel_ids[p_index]
            u0, u1 = mined_spans[p_index]
            panels.append(
                CutFillPanel(
                    id=pid,
                    block_id=bid,
                    panel_index=p_index,
                    lower_level_id=lower_id,
                    upper_level_id=upper_id,
                    start_order=panel_rank[pid],
                    u_min=u0,
                    u_max=u1,
                    strike_length=u1 - u0,
                    access_development_id=str(access[lower_id][p_index]["id"]),
                    cut_ids=[c.id for c in cuts_by_panel[pid]],
                )
            )
        if rib > 0.0:
            for boundary in range(n_panels - 1):
                b_u = panel_spans[boundary][1]
                bounds = LocalBounds(
                    u_min=b_u - 0.5 * rib,
                    u_max=b_u + 0.5 * rib,
                    v_min=v_block_min,
                    v_max=v_block_max,
                    w_min=w_min,
                    w_max=w_max,
                )
                proxy = grade_proxy(world, ob, bounds)
                built = build_solid(ob, bounds, triangles, None, extra_values=(proxy,))
                rid = rib_pillar_id(lower_id, upper_id, boundary)
                if built.report.failure_reason is not None and first_failure is None:
                    first_failure = f"{rid}: {built.report.failure_reason}"
                rib_pillars.append(
                    CutFillRibPillar(
                        id=rid,
                        block_id=bid,
                        left_panel_id=block_panel_ids[boundary],
                        right_panel_id=block_panel_ids[boundary + 1],
                        local_bounds=bounds,
                        geometry=built.geometry,
                        geometric_volume_m3=built.volume,
                        tonnes_equivalent=built.volume * density,
                        mean_grade_proxy=proxy,
                        report=built.report,
                    )
                )
        blocks.append(
            CutFillBlock(
                id=bid,
                lower_level_id=lower_id,
                upper_level_id=upper_id,
                start_order=block_rank[bid],
                v_min=v_block_min,
                v_max=v_block_max,
                vertical_height=(v_block_max - v_block_min) * v_z,
                panel_ids=block_panel_ids,
                lift_indices=block_lift_indices,
                sill_mat_required=sill_mat_required,
            )
        )
    # persisted cut / backfill order: panel start order, then the panel's own
    # mining order (lifts bottom → top, snake) — one canonical sequence
    cuts: list[CutFillCut] = [c for pid in panel_start_order for c in cuts_by_panel[pid]]
    backfills: list[CutFillBackfill] = [
        b for pid in panel_start_order for b in backfills_by_panel[pid]
    ]
    blocks.sort(key=lambda b: b.start_order)
    panels.sort(key=lambda p: p.start_order)
    total_v = float(math.fsum(c.geometric_volume_m3 for c in cuts))
    total_t = float(math.fsum(c.tonnes for c in cuts))
    cemented = [b for b in backfills if b.cemented]
    orebody_v = 8.0 * ob.half_length * ob.half_height * ob.half_thickness
    metrics = CutFillMetrics(
        cut_count=len(cuts),
        backfill_count=len(backfills),
        lift_count=len(lifts_out),
        level_interval_count=len(block_plan),
        block_count=len(blocks),
        panel_count=len(panels),
        rib_pillar_count=len(rib_pillars),
        cemented_backfill_count=len(cemented),
        total_geometric_volume_m3=total_v,
        total_tonnes=total_t,
        cemented_backfill_volume_m3=float(math.fsum(b.volume_m3 for b in cemented)),
        total_rib_pillar_volume_m3=float(math.fsum(p.geometric_volume_m3 for p in rib_pillars)),
        total_rib_pillar_tonnes_equivalent=float(
            math.fsum(p.tonnes_equivalent for p in rib_pillars)
        ),
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
        actual_mean_panel_length=(
            float(math.fsum(p.strike_length for p in panels) / len(panels)) if panels else 0.0
        ),
    )
    sequencing = CutFillSequencing(
        stoping_direction=params.stoping_direction,
        block_order=params.block_order,
        panel_length_m=float(params.panel_length_m),
        rib_pillar_width_m=rib,
        max_concurrent_panels=int(params.max_concurrent_panels),
        sill_mat_cure_days=float(params.sill_mat_cure_days),
        block_order_ids=[block_id(lo, up) for up, lo in block_order_pairs],
        panel_start_order=panel_start_order,
    )
    return CutFillPayload(
        status="SUCCESS" if first_failure is None else "FAILED",
        failure_reason=first_failure,
        source_revision=source_revision,
        method="CUT_AND_FILL",
        sequencing=sequencing,
        blocks=blocks,
        panels=panels,
        lifts=lifts_out,
        cuts=cuts,
        backfills=backfills,
        rib_pillars=rib_pillars,
        metrics=metrics,
    )


class CutFillPlan:
    """The CUT_AND_FILL ``MiningMethodPlan`` (Phase 21B, H2-CF): one
    production access per strike panel and level, blocks × panels × lifts ×
    cuts, referenced (optionally cemented) backfills and retained rib
    pillars."""

    method = METHOD
    implementation_status: ImplementationStatus = "IMPLEMENTED"
    display_name = "Cut & Fill"

    def production_development(self, scenario: Scenario) -> ProductionDevelopment:
        return ProductionDevelopment(method=self.method.value, status="IMPLEMENTED")

    def production_access_pattern(self, scenario: Scenario) -> ProductionAccessPattern | None:
        params = scenario.mining.method_parameters
        if not isinstance(params, CutFillParameters):
            raise ValueError("CUT_AND_FILL scenario carries no CutFillParameters")
        return PanelAccessPattern(float(params.panel_length_m))

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
        # semantic integrity FIRST (review blocker 4): the schedule derives
        # BACKFILL / CURE tasks from the persisted 1:1 backfill relation and
        # must never invent them for a cut whose backfill record is missing
        integrity = cut_fill_integrity(production_payload)
        if integrity is not None:
            return integrity
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
