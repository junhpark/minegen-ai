"""Reserved mining methods (Phase 21A): an EXPLICIT plan whose every answer
is the typed UNSUPPORTED_METHOD outcome. Nothing here yields geometry — the
level builder still develops the generic footwall backbone (common mine
development, never a method implementation, rule 159) and the stope
generator returns the typed FAILED payload (rule 78)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from minegen.core.enums import MiningMethodType
from minegen.levels.models import ProductionDevelopment
from minegen.mining.methods.contracts import (
    ImplementationStatus,
    ProductionLattice,
    unsupported_method_payload,
)
from minegen.mining.models import StopesPayload

if TYPE_CHECKING:
    from minegen.core.models import Scenario
    from minegen.design.cost_field import DesignCostEvaluator
    from minegen.world.synthetic_world import SyntheticWorld


class UnsupportedMethodPlan:
    implementation_status: ImplementationStatus = "UNSUPPORTED_METHOD"

    def __init__(self, method: MiningMethodType, display_name: str) -> None:
        self.method = method
        self.display_name = display_name

    def production_development(self, scenario: Scenario) -> ProductionDevelopment:
        method = self.method.value
        return ProductionDevelopment(
            method=method,
            status="UNSUPPORTED_METHOD",
            reason=(
                f"{method} production development (ore drives, lift / fill "
                "accesses, raises) is reserved and not implemented; only the generic "
                "footwall backbone drift is developed — no longhole crosscut lattice "
                "is substituted (rule 159)"
            ),
        )

    def production_lattice(self, scenario: Scenario) -> ProductionLattice | None:
        return None

    def generate_production(
        self,
        scenario: Scenario,
        world: SyntheticWorld,
        levels_payload: dict[str, Any],
        hard_evaluator: DesignCostEvaluator,
        source_revision: str,
    ) -> StopesPayload:
        return unsupported_method_payload(self.method, source_revision)
