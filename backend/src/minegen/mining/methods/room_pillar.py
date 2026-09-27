"""ROOM_AND_PILLAR production geometry (Phase 21C).

Consumes the validated ``levels.json`` ONLY (one central production access
CROSSCUT per level). The analytic TABULAR local plane ``(u strike, v
down-dip)`` carries an orthogonal ALTERNATING BAND grid:

    band pitch P = roomWidthM + pillarWidthM
    ROOM band k  = [k·P − roomWidthM/2, k·P + roomWidthM/2]   (u = 0 and v = 0 are ROOM)
    cell (u-band, v-band):  ROOM  when the u-band OR the v-band is a ROOM band
                            PILLAR when BOTH are PILLAR bands

The regular grid is extracted only inside the panel inset by
``boundaryPillarM`` from the orebody outline — the perimeter shell stays
unmined. Cells are non-overlapping rectangles; a ROOM cell is a semantic
parent whose thickness is mined in stages along ``w``: HEADING (the top
``headingHeightM`` of the thickness, or the whole thickness when it is not
thicker than the heading) then one or two BENCHES — an equal partition of
the remaining thickness. PILLARS are RETAINED material solids: never an
excavation, never a task, never a geotechnical certification. TABULAR
orebodies only (typed METHOD_GEOMETRY_NOT_IMPLEMENTED otherwise).
"""

from __future__ import annotations

import math
from itertools import pairwise
from typing import Any, Literal

import numpy as np

from minegen.core.enums import MiningMethodType, ObjectState, TaskType
from minegen.core.models import RoomPillarParameters, Scenario
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
from minegen.mining.methods.integrity import room_pillar_integrity
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
    ExtractionStage,
    LocalBounds,
    Pillar,
    PlanBounds,
    RoomCell,
    RoomExtractionUnit,
    RoomPillarMetrics,
    RoomPillarPayload,
)
from minegen.scheduling.models import ProductionTargetKind
from minegen.world.orebody import TabularOrebody
from minegen.world.synthetic_world import SyntheticWorld

METHOD = MiningMethodType.ROOM_AND_PILLAR
BandKind = Literal["ROOM", "PILLAR"]
#: zero-length band intervals below this are dropped (m)
BAND_EPSILON = 1e-9
STAGES: tuple[ExtractionStage, ...] = ("HEADING", "BENCH_1", "BENCH_2")


def _failed(source_revision: str, reason: str) -> RoomPillarPayload:
    return RoomPillarPayload(
        status="FAILED",
        failure_reason=reason,
        source_revision=source_revision,
        method="ROOM_AND_PILLAR",
        rooms=[],
        extraction_units=[],
        pillars=[],
        metrics=None,
    )


def band_intervals(
    lo: float, hi: float, room: float, pillar: float
) -> list[tuple[float, float, BandKind]]:
    """Alternating ROOM / PILLAR intervals covering ``[lo, hi]`` exactly, with
    the ROOM band centred on 0 (``[−room/2, room/2]``), clipped at both ends.
    Deterministic; the union of the intervals IS ``[lo, hi]``."""
    pitch = room + pillar
    k_lo = math.floor((lo + room / 2.0) / pitch) - 1
    k_hi = math.ceil((hi + room / 2.0) / pitch) + 1
    edges: list[float] = []
    for k in range(k_lo, k_hi + 1):
        for e in (k * pitch - room / 2.0, k * pitch + room / 2.0):
            if lo + BAND_EPSILON < e < hi - BAND_EPSILON:
                edges.append(e)
    cuts = [lo, *sorted(set(edges)), hi]
    out: list[tuple[float, float, BandKind]] = []
    for a, b in pairwise(cuts):
        if b - a <= BAND_EPSILON:
            continue
        mid = 0.5 * (a + b)
        kind: BandKind = "ROOM" if ((mid + room / 2.0) % pitch) < room else "PILLAR"
        out.append((a, b, kind))
    return out


def thickness_stages(
    w_min: float, w_max: float, heading: float, bench_count: int
) -> list[tuple[ExtractionStage, float, float]]:
    """HEADING = the top ``heading`` of the thickness (whole thickness when it
    is not thicker than the heading → one HEADING stage); the remainder is an
    equal partition into ``bench_count`` benches below it."""
    thickness = w_max - w_min
    if heading >= thickness - BAND_EPSILON:
        return [("HEADING", w_min, w_max)]
    stages: list[tuple[ExtractionStage, float, float]] = [("HEADING", w_max - heading, w_max)]
    benches = equal_partition(w_min, w_max - heading, (w_max - heading - w_min) / bench_count)
    # benches listed top → bottom (BENCH_1 directly under the heading)
    for i, (a, b) in enumerate(reversed(benches)):
        stages.append((STAGES[i + 1], a, b))
    return stages


def room_id(row: int, col: int) -> str:
    return f"ROOM:R{row:03d}:C{col:03d}"


def unit_id(row: int, col: int, stage: str) -> str:
    return f"{room_id(row, col)}:{stage}"


def pillar_id(row: int, col: int) -> str:
    return f"PILLAR:R{row:03d}:C{col:03d}"


def generate_room_pillar(
    scenario: Scenario,
    world: SyntheticWorld,
    levels_payload: dict[str, Any],
    hard_evaluator: DesignCostEvaluator,
    source_revision: str,
) -> RoomPillarPayload:
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
            "METHOD_GEOMETRY_NOT_IMPLEMENTED: Room & Pillar production geometry is "
            f"implemented for TABULAR orebodies only ({type(ob).__name__} is deferred) — no "
            "fallback to another method's geometry",
        )
    params = scenario.mining.method_parameters
    if not isinstance(params, RoomPillarParameters):
        return _failed(source_revision, "scenario carries no RoomPillarParameters")
    if not levels_payload["levels"]:
        return _failed(source_revision, "no completed levels")
    access, access_failure = central_access_by_level(levels_payload)
    if access_failure is not None:
        return _failed(source_revision, access_failure)

    def terminal_v(dev: dict[str, Any]) -> float:
        pts = np.asarray(dev["centerline"]["points"], dtype=np.float64).reshape(-1, 3)
        return float(ob.to_local(pts[-1][None, :])[0][1])

    level_v = {lv: terminal_v(dev) for lv, dev in access.items()}
    b = float(params.boundary_pillar_m)
    hu, hv = float(ob.half_length) - b, float(ob.half_height) - b
    if hu <= BAND_EPSILON or hv <= BAND_EPSILON:
        return _failed(
            source_revision,
            f"boundaryPillarM {b:g} m leaves no panel inside the orebody outline "
            f"({2 * ob.half_length:g} x {2 * ob.half_height:g} m)",
        )
    room, pillar = float(params.room_width_m), float(params.pillar_width_m)
    u_bands = band_intervals(-hu, hu, room, pillar)
    v_bands = band_intervals(-hv, hv, room, pillar)
    w_min, w_max = -float(ob.half_thickness), float(ob.half_thickness)
    stages = thickness_stages(w_min, w_max, float(params.heading_height_m), int(params.bench_count))
    cells = [(r, c, ub, vb) for r, vb in enumerate(v_bands) for c, ub in enumerate(u_bands)]
    room_cells = [x for x in cells if x[2][2] == "ROOM" or x[3][2] == "ROOM"]
    pillar_cells = [x for x in cells if x[2][2] == "PILLAR" and x[3][2] == "PILLAR"]
    solid_count = len(room_cells) * len(stages) + len(pillar_cells)
    if solid_count > MAX_PRODUCTION_SOLIDS:
        return _failed(
            source_revision,
            f"PRODUCTION_COMPLEXITY_LIMIT: {solid_count} production solids exceed the budget "
            f"of {MAX_PRODUCTION_SOLIDS} — enlarge roomWidthM / pillarWidthM; nothing is "
            "decimated silently",
        )

    triangles = frame_triangles(ob)
    density = float(scenario.orebody.density)
    first_failure: str | None = None

    def nearest_level(v_mid: float) -> str:
        return min(level_v, key=lambda lv: (abs(level_v[lv] - v_mid), lv))

    rooms: list[RoomCell] = []
    units: list[RoomExtractionUnit] = []
    for r, c, (u0, u1, _), (v0, v1, _) in room_cells:
        rid = room_id(r, c)
        access_dev = str(access[nearest_level(0.5 * (v0 + v1))]["id"])
        unit_ids: list[str] = []
        for bench_index, (stage, wa, wb) in enumerate(stages):
            bounds = LocalBounds(u_min=u0, u_max=u1, v_min=v0, v_max=v1, w_min=wa, w_max=wb)
            proxy = grade_proxy(world, ob, bounds)
            built = build_solid(ob, bounds, triangles, hard_evaluator, extra_values=(proxy,))
            uid = unit_id(r, c, stage)
            if built.report.failure_reason is not None and first_failure is None:
                first_failure = f"{uid}: {built.report.failure_reason}"
            units.append(
                RoomExtractionUnit(
                    id=uid,
                    room_id=rid,
                    stage=stage,
                    bench_index=bench_index,
                    local_bounds=bounds,
                    geometry=built.geometry,
                    geometric_volume_m3=built.volume,
                    tonnes=built.volume * density,
                    mean_grade_proxy=proxy,
                    report=built.report,
                )
            )
            unit_ids.append(uid)
        rooms.append(
            RoomCell(
                id=rid,
                row_index=r,
                column_index=c,
                local_plan_bounds=PlanBounds(u_min=u0, u_max=u1, v_min=v0, v_max=v1),
                access_development_id=access_dev,
                extraction_unit_ids=unit_ids,
            )
        )
    pillars: list[Pillar] = []
    for r, c, (u0, u1, _), (v0, v1, _) in pillar_cells:
        bounds = LocalBounds(u_min=u0, u_max=u1, v_min=v0, v_max=v1, w_min=w_min, w_max=w_max)
        proxy = grade_proxy(world, ob, bounds)
        # retained material: judged geometrically (no excavation evaluator)
        built = build_solid(ob, bounds, triangles, None, extra_values=(proxy,))
        pid = pillar_id(r, c)
        if built.report.failure_reason is not None and first_failure is None:
            first_failure = f"{pid}: {built.report.failure_reason}"
        pillars.append(
            Pillar(
                id=pid,
                row_index=r,
                column_index=c,
                local_bounds=bounds,
                geometry=built.geometry,
                geometric_volume_m3=built.volume,
                tonnes_equivalent=built.volume * density,
                mean_grade_proxy=proxy,
                report=built.report,
            )
        )
    mined_v = float(math.fsum(u.geometric_volume_m3 for u in units))
    pillar_v = float(math.fsum(p.geometric_volume_m3 for p in pillars))
    panel_v = float(2.0 * hu * 2.0 * hv * (w_max - w_min))
    metrics = RoomPillarMetrics(
        room_count=len(rooms),
        extraction_unit_count=len(units),
        pillar_count=len(pillars),
        heading_count=sum(1 for u in units if u.stage == "HEADING"),
        bench_count=sum(1 for u in units if u.stage != "HEADING"),
        total_mined_volume_m3=mined_v,
        total_pillar_volume_m3=pillar_v,
        panel_volume_m3=panel_v,
        total_mined_tonnes=float(math.fsum(u.tonnes for u in units)),
        geometric_extraction_fraction=mined_v / panel_v if panel_v > 0 else 0.0,
        weighted_mean_grade_proxy=weighted_grade([(u.mean_grade_proxy, u.tonnes) for u in units]),
    )
    return RoomPillarPayload(
        status="SUCCESS" if first_failure is None else "FAILED",
        failure_reason=first_failure,
        source_revision=source_revision,
        method="ROOM_AND_PILLAR",
        rooms=rooms,
        extraction_units=units,
        pillars=pillars,
        metrics=metrics,
    )


class RoomPillarPlan:
    """The ROOM_AND_PILLAR ``MiningMethodPlan`` (Phase 21C): one central
    production access per level, band-grid rooms (heading / benches) and
    retained pillars."""

    method = METHOD
    implementation_status: ImplementationStatus = "IMPLEMENTED"
    display_name = "Room & Pillar"

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
    ) -> RoomPillarPayload:
        return generate_room_pillar(
            scenario, world, levels_payload, hard_evaluator, source_revision
        )

    def production_identity(self, production_payload: dict[str, Any]) -> tuple[list[str], str]:
        return [u["id"] for u in production_payload["extractionUnits"]], "extraction unit"

    def production_schedule(
        self,
        scenario: Scenario,
        production_payload: dict[str, Any],
        ctx: ProductionScheduleContext,
    ) -> ProductionScheduleSpec | str:
        """ONE single-front Room & Pillar chain: rooms are worked outward from
        the central room (the cell containing the orebody centre, ties by
        row/column index) by Manhattan index distance, then row, then
        column; inside a room HEADING → BENCH_1 → BENCH_2. Every extraction
        unit runs PREP → STOPING → MUCKING; its preparation depends on the
        development task of the room's production access AND on the previous
        unit's mucking. Pillars are retained material and are never
        scheduled. A deterministic sequencing BASELINE (rule 82)."""
        # semantic integrity FIRST (review blocker 4): unique ids (a
        # duplicate room id must never be a silent dict overwrite) and the
        # exact two-way room ↔ extraction-unit membership
        integrity = room_pillar_integrity(production_payload)
        if integrity is not None:
            return integrity
        sch = ctx.schedule
        rooms = {str(r["id"]): r for r in production_payload["rooms"]}
        if not rooms:
            return "ROOM_AND_PILLAR: no rooms to schedule"
        units_by_room: dict[str, list[dict[str, Any]]] = {}
        for u in production_payload["extractionUnits"]:
            units_by_room.setdefault(str(u["roomId"]), []).append(u)
        for rid in units_by_room:
            units_by_room[rid].sort(key=lambda u: int(u["benchIndex"]))
        central = _central_room(list(rooms.values()))
        r0, c0 = int(central["rowIndex"]), int(central["columnIndex"])

        def room_key(room: dict[str, Any]) -> tuple[int, int, int]:
            r, c = int(room["rowIndex"]), int(room["columnIndex"])
            return (abs(r - r0) + abs(c - c0), r, c)

        tasks: list[ProductionTaskSpec] = []
        units: list[ProductionUnitSpec] = []
        previous_mucking: str | None = None
        kind: ProductionTargetKind = "ROOM_EXTRACTION"
        for room in sorted(rooms.values(), key=room_key):
            access_task = access_task_for(room, ctx.development_task_by_edge, "room")
            if access_task.startswith("!"):
                return access_task[1:]
            for u in units_by_room.get(str(room["id"]), []):
                uid = str(u["id"])
                tonnes = float(u["tonnes"])
                prep_deps = sorted(
                    {access_task} | ({previous_mucking} if previous_mucking else set())
                )
                chain = [
                    fixed_days_task(
                        f"TASK:PREP:{uid}",
                        TaskType.STOPE_PREPARATION,
                        kind,
                        uid,
                        float(sch.stope_preparation_days),
                        prep_deps,
                    ),
                    rate_task(
                        f"TASK:STOPING:{uid}",
                        TaskType.STOPING,
                        kind,
                        uid,
                        tonnes,
                        "t",
                        float(sch.stoping_tonnes_per_day),
                        [f"TASK:PREP:{uid}"],
                    ),
                    rate_task(
                        f"TASK:MUCKING:{uid}",
                        TaskType.MUCKING,
                        kind,
                        uid,
                        tonnes,
                        "t",
                        float(sch.mucking_tonnes_per_day),
                        [f"TASK:STOPING:{uid}"],
                    ),
                ]
                for task in chain:
                    if not (task.duration_days > 0.0 and math.isfinite(task.duration_days)):
                        return f"non-positive duration for {task.id}"
                tasks.extend(chain)
                units.append(
                    ProductionUnitSpec(
                        unit_id=uid,
                        transitions=[
                            ProductionStateSpec(f"TASK:STOPING:{uid}", "start", ObjectState.ACTIVE),
                            ProductionStateSpec(f"TASK:STOPING:{uid}", "end", ObjectState.MINED),
                            ProductionStateSpec(f"TASK:MUCKING:{uid}", "end", ObjectState.VOID),
                        ],
                    )
                )
                previous_mucking = f"TASK:MUCKING:{uid}"
        return ProductionScheduleSpec(
            target_kind=kind,
            tasks=tasks,
            units=units,
            tasks_per_unit=3,
            scheduled_tonnes=float(
                math.fsum(float(u["tonnes"]) for u in production_payload["extractionUnits"])
            ),
        )


def _central_room(rooms: list[dict[str, Any]]) -> dict[str, Any]:
    """The room whose plan cell contains the orebody centre (u = v = 0); when
    the centre falls on a pillar band, the room whose centroid is nearest to
    it (ties by row then column index)."""

    def key(room: dict[str, Any]) -> tuple[float, int, int]:
        b = room["localPlanBounds"]
        du = max(0.0, float(b["uMin"]), -float(b["uMax"]))
        dv = max(0.0, float(b["vMin"]), -float(b["vMax"]))
        return (du + dv, int(room["rowIndex"]), int(room["columnIndex"]))

    return min(rooms, key=key)
