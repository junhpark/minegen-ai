"""Mining-method registry (Phase 21A, rule 192) — the ONE authority that
resolves a requested ``MiningMethodType`` to its ``MiningMethodPlan``.

Every enum member resolves EXPLICITLY: implemented methods to their plan,
reserved methods to an ``UnsupportedMethodPlan``. There is no ``None``
result for a caller to interpret and no path on which an unregistered
method could fall back to LONGHOLE_OPEN_STOPING. ``levels/builder.py`` and
``services/design_service.py`` consume this registry; neither selects a
method itself.
"""

from __future__ import annotations

from minegen.core.enums import MiningMethodType
from minegen.mining.methods.contracts import MiningMethodPlan
from minegen.mining.methods.longhole import LongholeOpenStopingPlan
from minegen.mining.methods.unsupported import UnsupportedMethodPlan

__all__ = ["DISPLAY_NAMES", "UnknownMiningMethodError", "all_plans", "plan_for"]

#: read-only presentation names (frontend card, MineExchange semantics)
DISPLAY_NAMES: dict[MiningMethodType, str] = {
    MiningMethodType.LONGHOLE_OPEN_STOPING: "Longhole Open Stoping",
    MiningMethodType.CUT_AND_FILL: "Cut & Fill",
    MiningMethodType.ROOM_AND_PILLAR: "Room & Pillar",
    MiningMethodType.SUBLEVEL_CAVING: "Sublevel Caving",
    MiningMethodType.SHRINKAGE_STOPING: "Shrinkage Stoping",
}


class UnknownMiningMethodError(LookupError):
    """A ``MiningMethodType`` with no registered plan — a programming error
    caught by ``tests/test_mining_method_registry.py`` for every enum
    member, never a runtime fallback."""


_REGISTRY: dict[MiningMethodType, MiningMethodPlan] = {
    MiningMethodType.LONGHOLE_OPEN_STOPING: LongholeOpenStopingPlan(),
    MiningMethodType.CUT_AND_FILL: UnsupportedMethodPlan(
        MiningMethodType.CUT_AND_FILL, DISPLAY_NAMES[MiningMethodType.CUT_AND_FILL]
    ),
    MiningMethodType.ROOM_AND_PILLAR: UnsupportedMethodPlan(
        MiningMethodType.ROOM_AND_PILLAR, DISPLAY_NAMES[MiningMethodType.ROOM_AND_PILLAR]
    ),
    MiningMethodType.SUBLEVEL_CAVING: UnsupportedMethodPlan(
        MiningMethodType.SUBLEVEL_CAVING, DISPLAY_NAMES[MiningMethodType.SUBLEVEL_CAVING]
    ),
    MiningMethodType.SHRINKAGE_STOPING: UnsupportedMethodPlan(
        MiningMethodType.SHRINKAGE_STOPING, DISPLAY_NAMES[MiningMethodType.SHRINKAGE_STOPING]
    ),
}


def plan_for(method: MiningMethodType) -> MiningMethodPlan:
    """Resolve the requested method. Explicit for every registered member;
    a missing registration is a typed lookup error, never a default."""
    try:
        return _REGISTRY[MiningMethodType(method)]
    except (KeyError, ValueError) as err:
        raise UnknownMiningMethodError(
            f"no mining-method plan is registered for {method!r}"
        ) from err


def all_plans() -> dict[MiningMethodType, MiningMethodPlan]:
    return dict(_REGISTRY)
