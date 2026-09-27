"""Phase 10 MineTimeline typed contract (rules 81–86).

``derived/timeline.json`` is the temporal artifact: it owns TIME, TASKS and
STATE only — never geometry (rule 81). Geometry stays with its owning
artifacts (``decline_smoothed.json`` for RAMP, ``levels.json`` for
DRIFT/CROSSCUT, ``stopes.json`` for stope prisms); the timeline references
them by stable IDs and geometryRef and overlays temporal state on the
immutable Phase 09 geometry. The schedule is a deterministic
precedence-only earliest-start baseline (rule 82) — not a production
forecast or optimized schedule.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, SerializerFunctionWrapHandler, model_serializer

from minegen.core.enums import ObjectState, TaskType
from minegen.core.models import ApiModel
from minegen.network.models import GeometryRef


class TaskBasis(ApiModel):
    """Transparent duration derivation: duration = quantity / rate."""

    quantity: float
    quantity_unit: str
    rate: float
    rate_unit: str


#: production target kinds — STOPE (Longhole, Phase 10), CUT (Cut & Fill,
#: Phase 21B) and ROOM_EXTRACTION (Room & Pillar, Phase 21C). Pillars are
#: never a target: they are retained material, not a task.
ProductionTargetKind = Literal["STOPE", "CUT", "ROOM_EXTRACTION"]
TargetKind = Literal["DEVELOPMENT", "STOPE", "CUT", "ROOM_EXTRACTION"]


class TimelineTask(ApiModel):
    id: str
    task_type: TaskType
    target_kind: TargetKind
    target_id: str
    duration_days: float
    start_day: float
    end_day: float
    dependencies: list[str]
    basis: TaskBasis


class StateTransition(ApiModel):
    """state(day) = the latest transition whose ``day <= day`` — this
    exact-boundary rule is binding (rule 84)."""

    day: float
    state: ObjectState


def state_at(initial: ObjectState, transitions: list[StateTransition], day: float) -> ObjectState:
    """Binding evaluation semantics (rule 84): the latest transition whose
    ``transition.day <= day``; before every transition, ``initial``."""
    state = initial
    for t in transitions:
        if t.day <= day:
            state = t.state
        else:
            break
    return state


class DevelopmentTimeline(ApiModel):
    edge_id: str
    edge_type: str
    geometry_ref: GeometryRef
    task_id: str
    initial_state: ObjectState = ObjectState.NOT_BUILT
    transitions: list[StateTransition]
    progress_start_day: float
    progress_end_day: float
    # normalized cumulative 3D chainage aligned 1:1 with the OWNING centerline
    # points (rule 83): first 0, last 1, monotonic. The timeline never copies
    # geometry coordinates.
    point_chainage_fractions: list[float]
    #: Phase 20C.1-V excavation direction contract (rule 174): the network
    #: node the excavation STARTS from (the endpoint reached first from the
    #: portal / level entry) and the direction of progress along the owning
    #: centerline's point order: +1 when the first point is that start
    #: (progress p reveals chainage fractions [0, p]), −1 when the LAST point
    #: is (progress reveals [1 − p, 1], i.e. the geometry is traversed
    #: backwards). Geometry order is never changed; only the semantics of
    #: progress are made explicit so lines, meshes and future face
    #: calculations inherit one direction.
    excavation_start_node: str = ""
    progress_direction: Literal[1, -1] = 1


class StopeTimeline(ApiModel):
    stope_id: str
    initial_state: ObjectState = ObjectState.PLANNED
    transitions: list[StateTransition]


class ProductionUnitTimeline(ApiModel):
    """Temporal state machine of one non-Longhole production unit (a Cut & Fill
    cut or a Room & Pillar extraction unit). Geometry stays with the production
    artifact; this references it by id only (rule 81)."""

    unit_id: str
    initial_state: ObjectState = ObjectState.PLANNED
    transitions: list[StateTransition]


class ProductionTimeline(ApiModel):
    """Phase 21B/C generic production block — present ONLY for a
    non-Longhole active method (the Longhole payload keeps ``stopes``)."""

    method: str
    target_kind: ProductionTargetKind
    units: list[ProductionUnitTimeline]


_OPTIONAL_PRODUCTION_KEYS = ("productionTaskCount", "productionObjectCount", "productionTargetKind")


class TimelineMetrics(ApiModel):
    task_count: int
    development_task_count: int
    stope_task_count: int
    development_object_count: int
    stope_object_count: int
    total_development_length3d: float = Field(alias="totalDevelopmentLength3d")
    total_scheduled_tonnes: float
    ramp_completion_day: float
    first_stoping_day: float | None
    end_day: float
    #: Phase 21B/C: counts of the non-Longhole production block; OMITTED from
    #: serialization when absent so the Longhole payload is unchanged
    production_task_count: int | None = None
    production_object_count: int | None = None
    production_target_kind: ProductionTargetKind | None = None

    @model_serializer(mode="wrap")
    def _omit_absent_production(self, handler: SerializerFunctionWrapHandler) -> Any:
        out = handler(self)
        if isinstance(out, dict):
            for key in _OPTIONAL_PRODUCTION_KEYS:
                if key in out and out[key] is None:
                    del out[key]
            for key in (
                "production_task_count",
                "production_object_count",
                "production_target_kind",
            ):
                if key in out and out[key] is None:
                    del out[key]
        return out


class TimelinePayload(ApiModel):
    status: Literal["SUCCESS", "FAILED"]
    failure_reason: str | None
    source_revision: str
    start_day: float
    end_day: float
    tasks: list[TimelineTask]
    developments: list[DevelopmentTimeline]
    stopes: list[StopeTimeline]
    metrics: TimelineMetrics | None
    #: Phase 21B/C generic production block (Cut & Fill cuts / Room & Pillar
    #: extraction units); ``None`` — and OMITTED from serialization — for the
    #: Longhole method, whose ``stopes`` block is unchanged
    production: ProductionTimeline | None = None

    @model_serializer(mode="wrap")
    def _omit_absent_production(self, handler: SerializerFunctionWrapHandler) -> Any:
        out = handler(self)
        if isinstance(out, dict) and out.get("production") is None:
            out.pop("production", None)
        return out
