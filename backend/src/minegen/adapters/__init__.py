"""External application adapters (Phase 23B, ``docs/external-adapters.md``).

    MineExchange bundle BYTES (the ONLY mine input)  →  adapter  →  target package

An adapter is a TRANSLATOR: it consumes a MineExchange bundle through the
manifest-driven reader (never ``derived/*``, never a MineGen service), never
redesigns, re-ranks, re-schedules or reinterprets the mine, never invents an
engineering value (every value a target needs but no MineGen authority owns
is NOT_PROVIDED / USER_REQUIRED / ADAPTER_DEFAULT_EXPLICIT), reports every
bundle group in exactly one of five source states and emits a deterministic,
non-authoritative package with an ``adapter_manifest.json``. Adapter
versions are independent of the MineExchange version.

Targets: VENTSIM (ventilation geometry / network seed), ANYLOGIC
(operational data package), UNITY / UNREAL (engine import packages).
"""

from minegen.adapters.errors import AdapterError
from minegen.adapters.registry import ADAPTERS, build_package

__all__ = ["ADAPTERS", "AdapterError", "build_package"]
