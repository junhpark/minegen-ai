"""Mining-method plan contract (Phase 21A, rule 78 → rule 192).

ONE abstraction answers every mining-method question the design chain asks:

* ``MiningMethodPlan`` — the declarative method contract. It owns WHAT a
  method requires: the production-development intent (is a production
  lattice developed, and with which pitch / margin) and the production
  generation (stopes) of an implemented method, or the typed
  UNSUPPORTED_METHOD outcome of a reserved one.
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

from minegen.core.enums import MiningMethodType
from minegen.levels.models import ProductionDevelopment
from minegen.mining.models import StopesPayload

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


@dataclass(frozen=True)
class ProductionLattice:
    """Declarative station-lattice intent of a method with a production
    access lattice: stations every ``pitch`` metres, symmetric about the
    span centre, each keeping ``margin`` inside the span.

    ``offsets(half_span)`` is the exact Phase 08 / 20C.2A arithmetic
    (``k_max = floor((half_span − margin) / pitch + 1e-9)``, offsets
    ``k · pitch`` for ``k ∈ [−k_max, k_max]``); the builder maps an offset to
    a strike coordinate (TABULAR, about ``u = 0``) or a drift chainage
    (curved, about the trace midpoint). An empty list means the span cannot
    accommodate one station; the builder reports that, typed, in its own
    geometric terms."""

    pitch: float
    margin: float

    def offsets(self, half_span: float) -> list[float]:
        k_max = math.floor((half_span - self.margin) / self.pitch + 1e-9)
        return [k * self.pitch for k in range(-k_max, k_max + 1)]


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

    def production_lattice(self, scenario: Scenario) -> ProductionLattice | None:
        """The station lattice the level builder must develop, or ``None``
        when the method develops only the generic backbone drift."""
        ...

    def generate_production(
        self,
        scenario: Scenario,
        world: SyntheticWorld,
        levels_payload: dict[str, Any],
        hard_evaluator: DesignCostEvaluator,
        source_revision: str,
    ) -> StopesPayload:
        """Production generation from the validated ``levels.json`` ONLY
        (rule 76); an unsupported method returns the typed FAILED payload."""
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
