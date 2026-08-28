"""Mining-method strategy contract (rule 78).

Exactly one method is implemented in v0.1 — ``LONGHOLE_OPEN_STOPING``. Every
other reserved method resolves to an EXPLICIT typed ``UNSUPPORTED_METHOD``
failure: a scenario asking for CUT_AND_FILL must never silently receive
longhole stopes. No automatic method-selection rule exists in Phase 09;
rule-based recommendation may be added later only with explicitly sourced
engineering criteria.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from minegen.core.enums import MiningMethodType
from minegen.mining.models import StopesPayload

if TYPE_CHECKING:
    from minegen.core.models import Scenario
    from minegen.design.cost_field import DesignCostEvaluator
    from minegen.world.synthetic_world import SyntheticWorld


class MiningMethodStrategy(Protocol):
    """A strategy turns the validated Phase 08 levels artifact into the typed
    Phase 09 stopes payload. It never recomputes the station lattice from the
    scenario (rule 76) and never mutates MineNetwork topology."""

    method: MiningMethodType

    def generate(
        self,
        scenario: Scenario,
        world: SyntheticWorld,
        levels_payload: dict[str, Any],
        hard_evaluator: DesignCostEvaluator,
        source_revision: str,
    ) -> StopesPayload: ...


def strategy_for(method: MiningMethodType) -> MiningMethodStrategy | None:
    """Factory: ``None`` for reserved-but-unimplemented methods; the caller
    must convert that into an explicit UNSUPPORTED_METHOD failure."""
    from minegen.mining.methods.longhole import LongholeOpenStopingStrategy

    if method is MiningMethodType.LONGHOLE_OPEN_STOPING:
        return LongholeOpenStopingStrategy()
    return None


def unsupported_method_payload(method: MiningMethodType, source_revision: str) -> StopesPayload:
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
