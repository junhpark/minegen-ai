"""External application adapters (Phase 23B, ``docs/external-adapters.md``).

    MineExchange bundle (the ONLY external boundary)  →  adapter  →  target package

An adapter is a TRANSLATOR: it consumes a MineExchange bundle by its
manifest, never ``derived/*``, never redesigns the mine, never invents an
engineering value (every value a target needs but no MineGen authority owns
is recorded as NOT_PROVIDED / USER_REQUIRED / ADAPTER_DEFAULT_EXPLICIT), and
reports every consumed bundle group in exactly one of four source states.
Adapter versions are independent of the MineExchange version.
"""

from minegen.adapters.errors import AdapterError

__all__ = ["AdapterError"]
