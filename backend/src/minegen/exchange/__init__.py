"""MineExchange Core v1 (Phase 23A) — the versioned interoperability boundary.

    MineGen authoritative artifacts  →  MineExchange DTO  →  format writers  →  ZIP

A READ-ONLY, deterministic projection of existing authoritative state
(terrain, orebody, faults, validated excavation centerlines and their
closed logical sweeps, MineNetwork, capability semantics). It never
redesigns the mine, re-ranks, re-plans or invents engineering semantics,
and it persists nothing: the bundle is an on-demand download built from
ONE coherent validated snapshot.
"""

from minegen.exchange.models import COORDINATE_FRAME, MINE_EXCHANGE_VERSION

__all__ = ["COORDINATE_FRAME", "MINE_EXCHANGE_VERSION"]
