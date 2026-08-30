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

from typing import Literal

from pydantic import Field

from minegen.core.enums import ObjectState, TaskType
from minegen.core.models import ApiModel
from minegen.network.models import GeometryRef


class TaskBasis(ApiModel):
    """Transparent duration derivation: duration = quantity / rate."""

    quantity: float
    quantity_unit: str
    rate: float
    rate_unit: str


class TimelineTask(ApiModel):
    id: str
    task_type: TaskType
    target_kind: Literal["DEVELOPMENT", "STOPE"]
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


class StopeTimeline(ApiModel):
    stope_id: str
    initial_state: ObjectState = ObjectState.PLANNED
    transitions: list[StateTransition]


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
