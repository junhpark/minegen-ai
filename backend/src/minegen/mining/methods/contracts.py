"""Mining-method plan contract (Phase 21A, rule 78 → rule 192).

ONE abstraction answers every mining-method question the design chain asks:

* ``MiningMethodPlan`` — the declarative method contract. It owns WHAT a
  method requires: the production-development intent, the production
  ACCESS PATTERN the level builder develops (a station lattice for
  Longhole, one fixed central access for Cut & Fill / Room & Pillar), the
  production generation (the method's typed payload) and — Phase 21B/C —
  the production SCHEDULE specification the timeline builder executes; or
  the typed UNSUPPORTED_METHOD outcome of a reserved one.
* ``LevelDevelopmentBuilder`` keeps WHERE that intent is constructed and
  whether it is valid: drift / crosscut polylines, envelope validation, ore
  contact, curved section geometry.

The plan is a code-level contract object, never persisted state: the
scenario stays the method-configuration authority, ``levels.json`` the
development-geometry authority and ``stopes.json`` the (longhole) production
geometry authority. Every plan is resolved through ``registry.plan_for``;
nothing else selects a method.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

from minegen.core.enums import MiningMethodType, ObjectState, TaskType
from minegen.levels.models import ProductionDevelopment
from minegen.mining.models import ProductionPayload, StopesPayload
from minegen.scheduling.models import ProductionTargetKind, TaskBasis

if TYPE_CHECKING:
    from minegen.core.models import MiningConfig, Scenario
    from minegen.design.cost_field import DesignCostEvaluator
    from minegen.world.synthetic_world import SyntheticWorld

ImplementationStatus = Literal["IMPLEMENTED", "UNSUPPORTED_METHOD"]


def station_pitch(mining: MiningConfig) -> float:
    """The persisted ``LevelsMetrics.stationPitch`` value — the scenario's
    ``stope_length + minimum_pillar`` (rule 72). It is echoed for every
    method (the Phase 20B artifact contract), even when no production
    lattice is developed; the lattice itself belongs to the plan."""
    return float(mining.stope_length + mining.minimum_pillar)


def station_margin(mining: MiningConfig) -> float:
    """Half a planned stope proxy plus its end pillar — the room a station
    needs inside the developed span (rule 72)."""
    return mining.stope_length / 2.0 + mining.minimum_pillar


class ProductionAccessPattern(Protocol):
    """WHERE along a level backbone a method needs production access
    (Phase 21B/C): a declarative pattern the level builder maps onto the
    strike coordinate (TABULAR, about ``u = 0``) or the drift chainage
    (curved, about the trace midpoint). The builder consumes the pattern and
    never inspects the method."""

    @property
    def kind(self) -> str:
        """Pattern discriminator for diagnostics."""
        ...

    @property
    def pitch(self) -> float:
        """The persisted ``LevelsMetrics.stationPitch`` value of this pattern."""
        ...

    @property
    def defines_drift_extent(self) -> bool:
        """True when the level drift spans exactly the pattern's stations (the
        Longhole lattice); False when the generic backbone extent is developed
        and the pattern only adds breakpoints (fixed access)."""
        ...

    def offsets(self, half_span: float) -> list[float]: ...

    def station_index(self, offset: float, half_span: float) -> int:
        """The persisted station index of the access at ``offset`` (one of
        ``offsets(half_span)``): the lattice rank for Longhole, the panel
        index for Cut & Fill, the fixed-list position otherwise."""
        ...

    def describe_empty(self, half_span: float) -> str: ...


@dataclass(frozen=True)
class StationLatticeAccessPattern:
    """Declarative station-lattice intent of a method with a production
    access lattice (LONGHOLE_OPEN_STOPING): stations every ``pitch`` metres,
    symmetric about the span centre, each keeping ``margin`` inside the span.

    ``offsets(half_span)`` is the exact Phase 08 / 20C.2A arithmetic
    (``k_max = floor((half_span − margin) / pitch + 1e-9)``, offsets
    ``k · pitch`` for ``k ∈ [−k_max, k_max]``). An empty list means the span
    cannot accommodate one station; the builder reports that, typed, in its
    own geometric terms."""

    pitch: float
    margin: float
    kind: str = "STATION_LATTICE"
    defines_drift_extent: bool = True

    def offsets(self, half_span: float) -> list[float]:
        k_max = math.floor((half_span - self.margin) / self.pitch + 1e-9)
        return [k * self.pitch for k in range(-k_max, k_max + 1)]

    def station_index(self, offset: float, half_span: float) -> int:
        return round(offset / self.pitch)

    def describe_empty(self, half_span: float) -> str:
        return (
            f"stope-access station (half-length {half_span:g} m < "
            f"stope_length/2 + minimum_pillar = {self.margin:g} m, rule 72)"
        )


#: Phase 21A name kept for its importers — the Longhole lattice pattern
ProductionLattice = StationLatticeAccessPattern


@dataclass(frozen=True)
class FixedAccessPattern:
    """A fixed set of production accesses at declared span offsets — Phase
    21C Room & Pillar develops ONE central production access per level
    (``offsets_at = (0.0,)``; Cut & Fill moved to the per-panel
    ``PanelAccessPattern`` under H2-CF). The generic backbone drift is still
    developed over its full extent; the accesses only add breakpoints. The
    persisted ``stationPitch`` is 0.0: there is no lattice pitch."""

    offsets_at: tuple[float, ...] = (0.0,)
    kind: str = "FIXED_ACCESS"
    pitch: float = 0.0
    defines_drift_extent: bool = False

    def offsets(self, half_span: float) -> list[float]:
        return [o for o in self.offsets_at if abs(o) < half_span]

    def station_index(self, offset: float, half_span: float) -> int:
        return self.offsets_at.index(offset)

    def describe_empty(self, half_span: float) -> str:
        return f"central production access (half-length {half_span:g} m is not positive)"


@dataclass(frozen=True)
class PanelAccessPattern:
    """H2-CF Cut & Fill production access: ONE crosscut per strike PANEL.
    The span ``[−half_span, half_span]`` is partitioned equally into
    ``n = ceil(2·half_span / panel_length)`` panels (rule 194 partition) and
    the access of panel ``i`` sits at the panel centre; its station index IS
    the panel index (``0 … n − 1``, −u → +u), so the persisted
    ``CROSSCUT:<level>:S+0i`` id is the panel's stable access identity.
    The generic backbone drift keeps its full extent (the accesses only add
    breakpoints) and the persisted ``stationPitch`` is 0.0 — there is no
    lattice pitch."""

    panel_length: float
    kind: str = "PANEL_ACCESS"
    pitch: float = 0.0
    defines_drift_extent: bool = False

    def panels(self, half_span: float) -> list[tuple[float, float]]:
        from minegen.mining.methods.solids import equal_partition

        return equal_partition(-half_span, half_span, self.panel_length)

    def offsets(self, half_span: float) -> list[float]:
        return [0.5 * (a + b) for a, b in self.panels(half_span)]

    def station_index(self, offset: float, half_span: float) -> int:
        centres = self.offsets(half_span)
        for i, c in enumerate(centres):
            if abs(c - offset) <= 1e-9:
                return i
        raise ValueError(
            f"offset {offset!r} is not a panel centre of half-span {half_span!r} "
            f"(panel length {self.panel_length!r})"
        )

    def describe_empty(self, half_span: float) -> str:
        return f"Cut & Fill panel access (half-length {half_span:g} m is not positive)"


# --------------------------------------------------------------------------- #
# Phase 21B/C — production schedule specification (executed by the timeline
# builder; the builder never inspects the method)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ProductionTaskSpec:
    """One production task the timeline builder inserts verbatim (id, type,
    target, duration, transparent basis, dependencies on other task ids)."""

    id: str
    task_type: TaskType
    target_kind: ProductionTargetKind
    target_id: str
    duration_days: float
    basis: TaskBasis
    dependencies: list[str]


@dataclass(frozen=True)
class ProductionStateSpec:
    """A state transition bound to a task boundary: ``state`` is entered at
    the ``start`` or ``end`` day of ``task_id`` once the DAG is solved."""

    task_id: str
    boundary: Literal["start", "end"]
    state: ObjectState


@dataclass(frozen=True)
class ProductionUnitSpec:
    unit_id: str
    transitions: list[ProductionStateSpec]


@dataclass(frozen=True)
class ProductionScheduleSpec:
    """The method's production schedule: tasks in insertion order, the
    temporal units they drive and the aggregate contract the builder
    verifies (``tasks_per_unit × units == tasks``)."""

    target_kind: ProductionTargetKind
    tasks: list[ProductionTaskSpec]
    units: list[ProductionUnitSpec]
    tasks_per_unit: int
    scheduled_tonnes: float


@dataclass(frozen=True)
class ProductionScheduleContext:
    """What the timeline builder already validated and the production
    schedule may depend on: network nodes by id, the development task of
    every physical edge and the CROSSCUT development tasks terminating at
    each access node."""

    nodes: dict[str, dict[str, Any]]
    development_task_by_edge: dict[str, str]
    crosscut_tasks_by_access_node: dict[str, list[str]]
    schedule: Any  # ScheduleConfig (typed rates; no hidden constants)


class MiningMethodPlan(Protocol):
    """The mining-method contract resolved for a scenario's requested method."""

    method: MiningMethodType
    implementation_status: ImplementationStatus
    #: human-readable method name for read-only presentation
    display_name: str

    def production_development(self, scenario: Scenario) -> ProductionDevelopment:
        """The production-development intent recorded in ``levels.json``:
        IMPLEMENTED (a production lattice is developed) or a typed
        UNSUPPORTED_METHOD with its reason — never a silent substitute."""
        ...

    def production_access_pattern(self, scenario: Scenario) -> ProductionAccessPattern | None:
        """The production access pattern the level builder must develop —
        a station lattice (Longhole), a fixed central access (Cut & Fill,
        Room & Pillar) — or ``None`` when the method develops only the
        generic backbone drift (reserved methods)."""
        ...

    def generate_production(
        self,
        scenario: Scenario,
        world: SyntheticWorld,
        levels_payload: dict[str, Any],
        hard_evaluator: DesignCostEvaluator,
        source_revision: str,
    ) -> ProductionPayload:
        """Production generation from the validated ``levels.json`` ONLY
        (rule 76): the method's typed payload (``StopesPayload`` /
        ``CutFillPayload`` / ``RoomPillarPayload``); an unsupported method
        returns its typed FAILED payload."""
        ...

    def production_identity(self, production_payload: dict[str, Any]) -> tuple[list[str], str]:
        """The production unit ids of a SUCCESS payload and the noun used in
        the builder's uniqueness gate (``"stope"`` / ``"cut"`` /
        ``"extraction unit"``)."""
        ...

    def production_schedule(
        self,
        scenario: Scenario,
        production_payload: dict[str, Any],
        ctx: ProductionScheduleContext,
    ) -> ProductionScheduleSpec | str:
        """The method's production task graph over the validated production
        payload (Phase 21B/C), or a failure reason string. A deterministic
        method-sequencing BASELINE — never a resource-capacity optimization."""
        ...


def unsupported_method_payload(method: MiningMethodType, source_revision: str) -> StopesPayload:
    """The typed stope outcome of a reserved method (rule 78 wording kept)."""
    return StopesPayload(
        status="FAILED",
        failure_reason=(
            f"UNSUPPORTED_METHOD: {method.value} is reserved but not implemented in "
            "v0.1 — no silent fallback to LONGHOLE_OPEN_STOPING (rule 78)"
        ),
        source_revision=source_revision,
        method=method.value,
        stopes=[],
        metrics=None,
    )
