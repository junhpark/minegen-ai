"""Ventsim geometry / network SEED adapter (Phase 23B, directive §21–§28).

The seed makes MineGen's development topology the exact geometry / network
starting point of a Ventsim airway model: the bundle's FULL-FIDELITY
centerline DXF (the vendor's documented DXF → Convert Centrelines path),
the node and airway tables carrying the bundle's authoritative lengths and
cross-section dimensions, and the DXF-handle identity map. It is NOT a
ventilation model: friction, resistance, fans, regulators, doors, leakage,
heat, diesel, airflow and pressure have no MineGen authority and are never
written.
"""

from minegen.adapters.ventsim.adapter import ADAPTER_NAME, ADAPTER_VERSION, build_ventsim_package

__all__ = ["ADAPTER_NAME", "ADAPTER_VERSION", "build_ventsim_package"]
