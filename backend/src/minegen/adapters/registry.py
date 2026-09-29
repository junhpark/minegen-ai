"""The four adapter builders keyed by target (directive §52–§53). A plain
table, not a plugin runtime: every builder is ``bytes → AdapterPackage``."""

from __future__ import annotations

from collections.abc import Callable

from minegen.adapters.anylogic import build_anylogic_package
from minegen.adapters.bundle_reader import MineExchangeBundle, read_mine_exchange_bundle
from minegen.adapters.contracts import AdapterTarget
from minegen.adapters.engine import build_unity_package, build_unreal_package
from minegen.adapters.errors import AdapterTargetUnsupportedError
from minegen.adapters.package import AdapterPackage
from minegen.adapters.ventsim import build_ventsim_package

ADAPTERS: dict[str, Callable[[MineExchangeBundle], AdapterPackage]] = {
    "VENTSIM": build_ventsim_package,
    "ANYLOGIC": build_anylogic_package,
    "UNITY": build_unity_package,
    "UNREAL": build_unreal_package,
}


def build_package(target: AdapterTarget | str, bundle_bytes: bytes) -> AdapterPackage:
    """Adapter entry over MineExchange ZIP bytes — the API composes this with
    the exporter; an offline bundle is adapted the very same way."""
    builder = ADAPTERS.get(str(target))
    if builder is None:
        raise AdapterTargetUnsupportedError(
            f"no adapter for target {target!r}; targets: {sorted(ADAPTERS)}",
            adapter=str(target),
            subject="target",
        )
    return builder(read_mine_exchange_bundle(bundle_bytes))
