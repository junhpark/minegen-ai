"""READ ≠ TRUST at the analysis boundary (Phase 22A §9 / §43–46).

The ``ArtifactReader`` validates each artifact STRUCTURALLY; the cross-record
relations the analysis derives quantities from are re-verified here before
anything is summed. Every defect is the typed
:class:`AnalysisSourceInconsistentError` (409 ``ANALYSIS_SOURCE_INCONSISTENT``),
never a bare 500 and never a silently skipped record.

Production-payload semantics reuse ``mining/methods/integrity.py`` (the same
helpers the timeline builder and MineExchange run) — they are not copied.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from typing import Any, ClassVar

from minegen.core.enums import EdgeType, MiningMethodType, TaskType
from minegen.mining.methods.integrity import cut_fill_integrity, room_pillar_integrity
from minegen.mining.models import (
    CutFillMetrics,
    CutFillPayload,
    ProductionPayload,
    RoomPillarMetrics,
    RoomPillarPayload,
    StopesMetrics,
    StopesPayload,
)
from minegen.network.models import NetworkPayload
from minegen.scheduling.models import TimelinePayload, TimelineTask

__all__ = [
    "DECLARED_LENGTH_TOLERANCE_M",
    "QUANTITY_ABS_TOLERANCE",
    "QUANTITY_REL_TOLERANCE",
    "REQUIRED_PRODUCTION_TASK_TYPES",
    "AnalysisSourceInconsistentError",
    "production_units",
    "verify_network",
    "verify_production",
    "verify_production_metrics",
    "verify_timeline",
]

#: absolute agreement of the declared ``NetworkMetrics`` lengths with the
#: edge-derived sums (float summation-order noise is ~1e-12 m)
DECLARED_LENGTH_TOLERANCE_M = 1e-6
#: agreement of a timeline task's basis quantity with its geometric authority
QUANTITY_REL_TOLERANCE = 1e-9
QUANTITY_ABS_TOLERANCE = 1e-6

#: the production task types every method's schedule must carry per unit
REQUIRED_PRODUCTION_TASK_TYPES: dict[MiningMethodType, tuple[TaskType, ...]] = {
    MiningMethodType.LONGHOLE_OPEN_STOPING: (TaskType.STOPING, TaskType.MUCKING),
    MiningMethodType.CUT_AND_FILL: (TaskType.STOPING, TaskType.MUCKING, TaskType.BACKFILL),
    MiningMethodType.ROOM_AND_PILLAR: (TaskType.STOPING, TaskType.MUCKING),
}


class AnalysisSourceInconsistentError(RuntimeError):
    """Two authoritative sources (or one source and its own declared
    metrics) disagree; the analysis refuses rather than guess."""

    code: ClassVar[str] = "ANALYSIS_SOURCE_INCONSISTENT"
    http_status: ClassVar[int] = 409

    def __init__(self, detail: str) -> None:
        super().__init__(f"analysis sources are inconsistent: {detail}")
        self.detail = detail


def _duplicates(ids: Iterable[str]) -> list[str]:
    return sorted(i for i, n in Counter(ids).items() if n > 1)[:3]


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=QUANTITY_REL_TOLERANCE, abs_tol=QUANTITY_ABS_TOLERANCE)


# --------------------------------------------------------------------------- #
# Network
# --------------------------------------------------------------------------- #


def verify_network(network: NetworkPayload) -> None:
    """Unique node / edge ids, endpoints exist, finite positive length and
    cross-section area, and the declared metrics agree with the edges.
    Requires ``status == SUCCESS`` (a FAILED network is NOT_AVAILABLE, never
    verified here)."""
    node_ids = [n.id for n in network.nodes]
    if dup := _duplicates(node_ids):
        raise AnalysisSourceInconsistentError(f"network.json duplicate node ids {dup}")
    edge_ids = [e.id for e in network.edges]
    if dup := _duplicates(edge_ids):
        raise AnalysisSourceInconsistentError(f"network.json duplicate edge ids {dup}")
    known = set(node_ids)
    for e in network.edges:
        if e.from_node not in known or e.to_node not in known:
            raise AnalysisSourceInconsistentError(
                f"network.json edge {e.id} references an unknown node ({e.from_node} → {e.to_node})"
            )
        if not (math.isfinite(e.length3d) and e.length3d > 0.0):
            raise AnalysisSourceInconsistentError(
                f"network.json edge {e.id} has non-positive length3d {e.length3d!r}"
            )
        area = e.cross_section.analytic_area
        if not (math.isfinite(area) and area > 0.0):
            raise AnalysisSourceInconsistentError(
                f"network.json edge {e.id} has non-positive analyticArea {area!r}"
            )
    metrics = network.metrics
    if metrics is None:
        raise AnalysisSourceInconsistentError("network.json is SUCCESS but carries no metrics")
    by_type: dict[EdgeType, list[float]] = {t: [] for t in EdgeType}
    for e in network.edges:
        by_type[e.type].append(e.length3d)
    declared_counts = {
        "edgeCount": (metrics.edge_count, len(network.edges)),
        "levelAccessEdgeCount": (
            metrics.level_access_edge_count,
            len(by_type[EdgeType.LEVEL_ACCESS]),
        ),
        "driftEdgeCount": (metrics.drift_edge_count, len(by_type[EdgeType.DRIFT])),
        "crosscutEdgeCount": (metrics.crosscut_edge_count, len(by_type[EdgeType.CROSSCUT])),
        "shaftEdgeCount": (metrics.shaft_edge_count, len(by_type[EdgeType.SHAFT])),
        "shaftStationAccessEdgeCount": (
            metrics.shaft_station_access_edge_count,
            len(by_type[EdgeType.SHAFT_STATION_ACCESS]),
        ),
    }
    for name, (declared, derived) in declared_counts.items():
        if declared != derived:
            raise AnalysisSourceInconsistentError(
                f"network.json metrics.{name} = {declared} but the edges give {derived}"
            )
    declared_lengths = {
        "totalRampLength3d": (metrics.total_ramp_length3d, EdgeType.RAMP),
        "totalLevelAccessLength3d": (metrics.total_level_access_length3d, EdgeType.LEVEL_ACCESS),
        "totalDriftLength3d": (metrics.total_drift_length3d, EdgeType.DRIFT),
        "totalCrosscutLength3d": (metrics.total_crosscut_length3d, EdgeType.CROSSCUT),
        "totalShaftLength3d": (metrics.total_shaft_length3d, EdgeType.SHAFT),
        "totalShaftStationAccessLength3d": (
            metrics.total_shaft_station_access_length3d,
            EdgeType.SHAFT_STATION_ACCESS,
        ),
    }
    for name, (declared_length, edge_type) in declared_lengths.items():
        derived_length = math.fsum(by_type[edge_type])
        if abs(declared_length - derived_length) > DECLARED_LENGTH_TOLERANCE_M:
            raise AnalysisSourceInconsistentError(
                f"network.json metrics.{name} = {declared_length!r} but the edges sum to "
                f"{derived_length!r} (tolerance {DECLARED_LENGTH_TOLERANCE_M} m)"
            )


def network_cross_check(network: NetworkPayload) -> tuple[float, int]:
    """The measured residuals of a network that PASSED :func:`verify_network`:
    (max |declared − derived| length, max |declared − derived| count)."""
    metrics = network.metrics
    assert metrics is not None
    by_type: dict[EdgeType, list[float]] = {t: [] for t in EdgeType}
    for e in network.edges:
        by_type[e.type].append(e.length3d)
    lengths: list[float] = [
        abs(metrics.total_ramp_length3d - math.fsum(by_type[EdgeType.RAMP])),
        abs(metrics.total_level_access_length3d - math.fsum(by_type[EdgeType.LEVEL_ACCESS])),
        abs(metrics.total_drift_length3d - math.fsum(by_type[EdgeType.DRIFT])),
        abs(metrics.total_crosscut_length3d - math.fsum(by_type[EdgeType.CROSSCUT])),
        abs(metrics.total_shaft_length3d - math.fsum(by_type[EdgeType.SHAFT])),
        abs(
            metrics.total_shaft_station_access_length3d
            - math.fsum(by_type[EdgeType.SHAFT_STATION_ACCESS])
        ),
    ]
    counts: list[int] = [
        abs(metrics.edge_count - len(network.edges)),
        abs(metrics.level_access_edge_count - len(by_type[EdgeType.LEVEL_ACCESS])),
        abs(metrics.drift_edge_count - len(by_type[EdgeType.DRIFT])),
        abs(metrics.crosscut_edge_count - len(by_type[EdgeType.CROSSCUT])),
        abs(metrics.shaft_edge_count - len(by_type[EdgeType.SHAFT])),
        abs(metrics.shaft_station_access_edge_count - len(by_type[EdgeType.SHAFT_STATION_ACCESS])),
    ]
    return max(lengths), max(counts)


# --------------------------------------------------------------------------- #
# Production
# --------------------------------------------------------------------------- #


class ProductionUnit:
    """One production object as the analysis sees it: id, geometric volume,
    planned mined tonnes and the planning grade proxy."""

    __slots__ = ("grade_proxy", "id", "tonnes", "volume_m3")

    def __init__(self, id: str, volume_m3: float, tonnes: float, grade_proxy: float | None):
        self.id = id
        self.volume_m3 = volume_m3
        self.tonnes = tonnes
        self.grade_proxy = grade_proxy


def production_units(payload: ProductionPayload) -> list[ProductionUnit]:
    """The production objects in persisted order: stopes, cuts or extraction
    units. Pillars (retained) and backfills (semantic) are never units."""
    if isinstance(payload, StopesPayload):
        return [
            ProductionUnit(s.id, s.geometric_volume_m3, s.tonnes, s.mean_grade_proxy)
            for s in payload.stopes
        ]
    if isinstance(payload, CutFillPayload):
        return [
            ProductionUnit(c.id, c.geometric_volume_m3, c.tonnes, c.mean_grade_proxy)
            for c in payload.cuts
        ]
    return [
        ProductionUnit(u.id, u.geometric_volume_m3, u.tonnes, u.mean_grade_proxy)
        for u in payload.extraction_units
    ]


def verify_production(
    scenario_method: MiningMethodType, payload: ProductionPayload, raw: dict[str, Any]
) -> None:
    """Method agreement with the scenario, unique unit ids, finite
    non-negative quantities, and the method-specific semantic relations
    (``mining/methods/integrity.py``). Requires ``status == SUCCESS``."""
    if payload.method != scenario_method.value:
        raise AnalysisSourceInconsistentError(
            f"scenario mining method {scenario_method.value} but stopes.json declares "
            f"{payload.method}"
        )
    if isinstance(payload, StopesPayload) and payload.method != "LONGHOLE_OPEN_STOPING":
        raise AnalysisSourceInconsistentError(
            f"stopes.json is SUCCESS under reserved method {payload.method}"
        )
    units = production_units(payload)
    if dup := _duplicates(u.id for u in units):
        raise AnalysisSourceInconsistentError(f"stopes.json duplicate production ids {dup}")
    for u in units:
        for name, value in (("geometricVolumeM3", u.volume_m3), ("tonnes", u.tonnes)):
            if not (math.isfinite(value) and value >= 0.0):
                raise AnalysisSourceInconsistentError(
                    f"stopes.json production object {u.id} has invalid {name} {value!r}"
                )
    if isinstance(payload, CutFillPayload):
        defect = cut_fill_integrity(raw)
    elif isinstance(payload, RoomPillarPayload):
        defect = room_pillar_integrity(raw)
        if dup := _duplicates(p.id for p in payload.pillars):
            defect = f"duplicate pillar ids {dup}"
    else:
        defect = None
    if defect is not None:
        raise AnalysisSourceInconsistentError(f"stopes.json {defect}")
    verify_production_metrics(payload)


def _weighted_grade(units: list[ProductionUnit]) -> float | None:
    graded = [(u.grade_proxy, u.tonnes) for u in units if u.grade_proxy is not None]
    if not graded:
        return None
    mass = math.fsum(t for _, t in graded)
    return math.fsum(g * t for g, t in graded) / mass if mass > 0 else None


def _same_optional(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return _close(a, b)


def verify_production_metrics(payload: ProductionPayload) -> None:
    """The persisted aggregate ``metrics`` block agrees with the entities it
    summarises (PR #48 review hardening): every count, total volume / tonnes
    and the tonnage-weighted grade proxy are re-derived from the records the
    analysis also consumes. Aggregates that need the orebody
    (``geometricExtractionFractionOfOrebody``) or the layout
    (``stationsPerInterval``) are not re-derivable here and stay as
    persisted."""
    metrics = payload.metrics
    if metrics is None:
        raise AnalysisSourceInconsistentError("stopes.json is SUCCESS but carries no metrics")
    units = production_units(payload)
    counts: list[tuple[str, int, int]] = []
    totals: list[tuple[str, float, float]] = []
    if isinstance(payload, StopesPayload):
        assert isinstance(metrics, StopesMetrics)
        pairs = {(s.upper_level_id, s.lower_level_id) for s in payload.stopes}
        counts += [
            ("stopeCount", metrics.stope_count, len(payload.stopes)),
            ("levelIntervalCount", metrics.level_interval_count, len(pairs)),
        ]
        totals += [
            (
                "totalGeometricVolumeM3",
                metrics.total_geometric_volume_m3,
                math.fsum(u.volume_m3 for u in units),
            ),
            ("totalTonnes", metrics.total_tonnes, math.fsum(u.tonnes for u in units)),
        ]
    elif isinstance(payload, CutFillPayload):
        assert isinstance(metrics, CutFillMetrics)
        cut_ids = {c.id for c in payload.cuts}
        lift_cuts = [cid for lift in payload.lifts for cid in lift.cut_ids]
        if sorted(lift_cuts) != sorted(cut_ids):
            raise AnalysisSourceInconsistentError(
                "stopes.json lifts do not partition the cuts (cutIds ≠ cuts)"
            )
        lift_by_index = {lift.lift_index: lift for lift in payload.lifts}
        for c in payload.cuts:
            lift = lift_by_index.get(c.lift_index)
            if lift is None or c.id not in lift.cut_ids:
                raise AnalysisSourceInconsistentError(
                    f"stopes.json cut {c.id} is not listed by lift {c.lift_index}"
                )
        pairs = {(lift.lower_level_id, lift.upper_level_id) for lift in payload.lifts}
        counts += [
            ("cutCount", metrics.cut_count, len(payload.cuts)),
            ("backfillCount", metrics.backfill_count, len(payload.backfills)),
            ("liftCount", metrics.lift_count, len(payload.lifts)),
            ("levelIntervalCount", metrics.level_interval_count, len(pairs)),
        ]
        totals += [
            (
                "totalGeometricVolumeM3",
                metrics.total_geometric_volume_m3,
                math.fsum(u.volume_m3 for u in units),
            ),
            ("totalTonnes", metrics.total_tonnes, math.fsum(u.tonnes for u in units)),
        ]
    else:
        assert isinstance(metrics, RoomPillarMetrics)
        mined_v = math.fsum(u.volume_m3 for u in units)
        pillar_v = math.fsum(p.geometric_volume_m3 for p in payload.pillars)
        counts += [
            ("roomCount", metrics.room_count, len(payload.rooms)),
            ("extractionUnitCount", metrics.extraction_unit_count, len(payload.extraction_units)),
            ("pillarCount", metrics.pillar_count, len(payload.pillars)),
            (
                "headingCount",
                metrics.heading_count,
                sum(1 for u in payload.extraction_units if u.bench_index == 0),
            ),
            (
                "benchCount",
                metrics.bench_count,
                sum(1 for u in payload.extraction_units if u.bench_index > 0),
            ),
        ]
        totals += [
            ("totalMinedVolumeM3", metrics.total_mined_volume_m3, mined_v),
            ("totalPillarVolumeM3", metrics.total_pillar_volume_m3, pillar_v),
            ("totalMinedTonnes", metrics.total_mined_tonnes, math.fsum(u.tonnes for u in units)),
            (
                "geometricExtractionFraction",
                metrics.geometric_extraction_fraction,
                mined_v / metrics.panel_volume_m3 if metrics.panel_volume_m3 > 0 else 0.0,
            ),
        ]
    for name, declared_count, derived_count in counts:
        if declared_count != derived_count:
            raise AnalysisSourceInconsistentError(
                f"stopes.json metrics.{name} = {declared_count} but the records give "
                f"{derived_count}"
            )
    for name, declared_total, derived_total in totals:
        if not _close(declared_total, derived_total):
            raise AnalysisSourceInconsistentError(
                f"stopes.json metrics.{name} = {declared_total!r} but the records give "
                f"{derived_total!r}"
            )
    declared_grade = metrics.weighted_mean_grade_proxy
    derived_grade = _weighted_grade(units)
    if not _same_optional(declared_grade, derived_grade):
        raise AnalysisSourceInconsistentError(
            f"stopes.json metrics.weightedMeanGradeProxy = {declared_grade!r} but the records "
            f"give {derived_grade!r}"
        )


# --------------------------------------------------------------------------- #
# Timeline
# --------------------------------------------------------------------------- #


def verify_timeline(
    scenario_method: MiningMethodType,
    timeline: TimelinePayload,
    network: NetworkPayload,
    payload: ProductionPayload,
) -> dict[str, dict[TaskType, TimelineTask]]:
    """Task ids unique, ``start ≤ end`` with a consistent duration,
    dependencies exist, every DEVELOPMENT target is a network edge (with a
    metre basis equal to the edge length) and every network edge has its
    development task, every production target is a production object, the
    production method agrees with the scenario, and every production unit
    carries the method's required task types with a basis quantity equal to
    its geometric tonnes. Returns ``unit id → {task type → task}`` for the
    production tasks (the cashflow timing lookup)."""
    tasks = timeline.tasks
    if dup := _duplicates(t.id for t in tasks):
        raise AnalysisSourceInconsistentError(f"timeline.json duplicate task ids {dup}")
    by_id = {t.id: t for t in tasks}
    for t in tasks:
        if not (
            math.isfinite(t.start_day)
            and math.isfinite(t.end_day)
            and t.start_day >= 0.0
            and t.end_day >= t.start_day
        ):
            raise AnalysisSourceInconsistentError(
                f"timeline.json task {t.id} has startDay {t.start_day!r} / endDay {t.end_day!r}"
            )
        if not _close(t.end_day - t.start_day, t.duration_days):
            raise AnalysisSourceInconsistentError(
                f"timeline.json task {t.id} durationDays {t.duration_days!r} ≠ "
                f"endDay - startDay {t.end_day - t.start_day!r}"
            )
        for dep in t.dependencies:
            if dep not in by_id:
                raise AnalysisSourceInconsistentError(
                    f"timeline.json task {t.id} depends on unknown task {dep}"
                )
    metrics = timeline.metrics
    if metrics is None:
        raise AnalysisSourceInconsistentError("timeline.json is SUCCESS but carries no metrics")
    if metrics.task_count != len(tasks):
        raise AnalysisSourceInconsistentError(
            f"timeline.json metrics.taskCount {metrics.task_count} ≠ {len(tasks)} tasks"
        )
    # -- development ↔ network ------------------------------------------------ #
    edges = {e.id: e for e in network.edges}
    dev_seen: set[str] = set()
    for t in tasks:
        if t.target_kind != "DEVELOPMENT":
            continue
        edge = edges.get(t.target_id)
        if edge is None:
            raise AnalysisSourceInconsistentError(
                f"timeline.json development task {t.id} targets unknown network edge {t.target_id}"
            )
        if t.target_id in dev_seen:
            raise AnalysisSourceInconsistentError(
                f"timeline.json has two development tasks for edge {t.target_id}"
            )
        dev_seen.add(t.target_id)
        if t.basis.quantity_unit != "m" or not _close(t.basis.quantity, edge.length3d):
            raise AnalysisSourceInconsistentError(
                f"timeline.json development task {t.id} basis {t.basis.quantity!r} "
                f"{t.basis.quantity_unit} ≠ edge length3d {edge.length3d!r} m"
            )
    missing = sorted(set(edges) - dev_seen)[:3]
    if missing:
        raise AnalysisSourceInconsistentError(
            f"network edges without a timeline development task {missing}"
        )
    # -- production ↔ production artifact ------------------------------------- #
    timeline_method = timeline.production.method if timeline.production is not None else None
    if timeline_method is None:
        # the Longhole payload keeps the ``stopes`` block and no production
        # block (rule 196)
        timeline_method = (
            MiningMethodType.LONGHOLE_OPEN_STOPING.value
            if scenario_method is MiningMethodType.LONGHOLE_OPEN_STOPING
            else None
        )
    if timeline_method != scenario_method.value:
        raise AnalysisSourceInconsistentError(
            f"scenario mining method {scenario_method.value} but timeline.json schedules "
            f"{timeline_method}"
        )
    units = {u.id: u for u in production_units(payload)}
    # the BACKFILL basis is the backfill VOLUME: the persisted backfill record
    # for a Cut & Fill cut, the stope's own geometric volume for Longhole
    # (PR #48 review: the CF backfill quantity was unverified)
    backfill_volume: dict[str, float] = (
        {b.source_cut_id: b.volume_m3 for b in payload.backfills}
        if isinstance(payload, CutFillPayload)
        else {u.id: u.volume_m3 for u in units.values()}
    )
    per_unit: dict[str, dict[TaskType, TimelineTask]] = {u: {} for u in units}
    for t in tasks:
        if t.target_kind == "DEVELOPMENT":
            continue
        unit = units.get(t.target_id)
        if unit is None:
            raise AnalysisSourceInconsistentError(
                f"timeline.json production task {t.id} targets unknown production object "
                f"{t.target_id}"
            )
        if t.task_type in per_unit[t.target_id]:
            raise AnalysisSourceInconsistentError(
                f"timeline.json has two {t.task_type.value} tasks for {t.target_id}"
            )
        per_unit[t.target_id][t.task_type] = t
        if t.task_type in (TaskType.STOPING, TaskType.MUCKING) and (
            t.basis.quantity_unit != "t" or not _close(t.basis.quantity, unit.tonnes)
        ):
            raise AnalysisSourceInconsistentError(
                f"timeline.json task {t.id} basis {t.basis.quantity!r} "
                f"{t.basis.quantity_unit} ≠ production tonnes {unit.tonnes!r} t"
            )
        if t.task_type is TaskType.BACKFILL:
            volume = backfill_volume.get(t.target_id)
            if volume is None:
                raise AnalysisSourceInconsistentError(
                    f"timeline.json BACKFILL task {t.id} targets {t.target_id} which has no "
                    "backfill volume"
                )
            if t.basis.quantity_unit != "m3" or not _close(t.basis.quantity, volume):
                raise AnalysisSourceInconsistentError(
                    f"timeline.json task {t.id} basis {t.basis.quantity!r} "
                    f"{t.basis.quantity_unit} ≠ backfill volume {volume!r} m3"
                )
    required = REQUIRED_PRODUCTION_TASK_TYPES.get(scenario_method, ())
    for unit_id, present in per_unit.items():
        for ttype in required:
            if ttype not in present:
                raise AnalysisSourceInconsistentError(
                    f"timeline.json production object {unit_id} has no {ttype.value} task"
                )
    stoping_starts = [t.start_day for t in tasks if t.task_type is TaskType.STOPING]
    first = min(stoping_starts) if stoping_starts else None
    declared_first = metrics.first_stoping_day
    if (first is None) != (declared_first is None) or (
        first is not None and declared_first is not None and not _close(first, declared_first)
    ):
        raise AnalysisSourceInconsistentError(
            f"timeline.json metrics.firstStopingDay {declared_first!r} ≠ the earliest "
            f"STOPING start {first!r}"
        )
    return per_unit
