"""Shared production-schedule building blocks for the Phase 21B/C methods
(Cut & Fill, Room & Pillar).

Every duration is ``quantity / rate`` from the typed ``ScheduleConfig`` (rule
82: no hidden rate constants) and every task carries its transparent
``TaskBasis``. Longhole keeps its own verbatim Phase 10 chain in
``longhole.py`` — this module is used only by the new methods.
"""

from __future__ import annotations

from typing import Any

from minegen.core.enums import TaskType
from minegen.mining.methods.contracts import ProductionTaskSpec
from minegen.scheduling.models import ProductionTargetKind, TaskBasis


def fixed_days_task(
    task_id: str,
    task_type: TaskType,
    target_kind: ProductionTargetKind,
    target_id: str,
    days: float,
    dependencies: list[str],
) -> ProductionTaskSpec:
    """A fixed-duration task (preparation, cure): ``days`` at 1 day/day."""
    return ProductionTaskSpec(
        id=task_id,
        task_type=task_type,
        target_kind=target_kind,
        target_id=target_id,
        duration_days=float(days),
        basis=TaskBasis(quantity=float(days), quantity_unit="day", rate=1.0, rate_unit="day/day"),
        dependencies=list(dependencies),
    )


def rate_task(
    task_id: str,
    task_type: TaskType,
    target_kind: ProductionTargetKind,
    target_id: str,
    quantity: float,
    quantity_unit: str,
    rate: float,
    dependencies: list[str],
) -> ProductionTaskSpec:
    """A quantity-driven task: ``duration = quantity / rate``."""
    return ProductionTaskSpec(
        id=task_id,
        task_type=task_type,
        target_kind=target_kind,
        target_id=target_id,
        duration_days=float(quantity) / float(rate),
        basis=TaskBasis(
            quantity=float(quantity),
            quantity_unit=quantity_unit,
            rate=float(rate),
            rate_unit=f"{quantity_unit}/day",
        ),
        dependencies=list(dependencies),
    )


def access_task_for(
    unit: dict[str, Any],
    development_task_by_edge: dict[str, str],
    noun: str,
) -> str:
    """The development task of the production access this unit is mined from
    (``accessDevelopmentId`` == the levels.json / network CROSSCUT id), or a
    failure reason prefixed with ``!`` — the access must physically exist."""
    dev_id = str(unit["accessDevelopmentId"])
    task = development_task_by_edge.get(dev_id)
    if task is None:
        return (
            f"!{noun} {unit['id']} references production access {dev_id} that has no "
            "development task in the network"
        )
    return task
