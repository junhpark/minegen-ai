"""Ventsim geometry / network SEED adapter (Phase 23B.1).

The seed makes MineGen's development topology usable as the starting point
of a Ventsim airway model: one 3-D DXF polyline per MineNetwork edge (the
vendor's documented DXF → Convert Centrelines path), an airway attribute
table carrying the bundle's authoritative lengths and cross-section
dimensions, the junction table, an identity map (DXF handle ↔ network edge)
and the adapter report. It is NOT a ventilation model: resistance, fans,
regulators, heat and gas sources have no MineGen authority and stay
NOT_PROVIDED.
"""

from minegen.adapters.ventsim.config import VentsimSeedConfig
from minegen.adapters.ventsim.seed import (
    ADAPTER_NAME,
    ADAPTER_VERSION,
    VentsimSeedPackage,
    build_ventsim_seed,
)

__all__ = [
    "ADAPTER_NAME",
    "ADAPTER_VERSION",
    "VentsimSeedConfig",
    "VentsimSeedPackage",
    "build_ventsim_seed",
]
