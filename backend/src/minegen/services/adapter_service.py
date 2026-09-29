"""External adapter service (Phase 23B, directive §53–§55).

The ONLY MineGen service an adapter export touches is ``ExchangeService``:
the MineExchange bundle of the scenario's current authoritative state (ONE
coherent validated snapshot) is handed to the adapter as BYTES — the
adapter never sees ``derived/*``, ``ScenarioStore``, ``ArtifactReader`` or
``DesignService`` and consumes the bundle exactly as an offline user would.
Nothing is generated, nothing is persisted, no derived artifact exists.
"""

from __future__ import annotations

from dataclasses import dataclass

from minegen.adapters.contracts import AdapterTarget
from minegen.adapters.package import AdapterPackage
from minegen.adapters.registry import build_package
from minegen.exchange.models import ExchangeManifest
from minegen.services.exchange_service import ExchangeService, safe_scenario_id


@dataclass(frozen=True)
class AdapterExport:
    package: AdapterPackage
    exchange_manifest: ExchangeManifest
    filename: str


class AdapterService:
    def __init__(self, exchange: ExchangeService) -> None:
        self.exchange = exchange

    def export(self, scenario_id: str, target: AdapterTarget) -> AdapterExport:
        exported = self.exchange.export(scenario_id)
        package = build_package(target, exported.zip_bytes)
        return AdapterExport(
            package=package,
            exchange_manifest=exported.manifest,
            filename=f"minegen_{safe_scenario_id(scenario_id)}_{target.lower()}.zip",
        )
