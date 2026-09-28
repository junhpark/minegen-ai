"""External adapter service (Phase 23B.1): the MineExchange bundle of the
scenario's current authoritative state (ONE coherent validated snapshot,
``ExchangeService.export``) is handed to an adapter as BYTES — the adapter
never sees ``derived/*`` and consumes the bundle exactly as an offline user
would. Nothing is persisted and no derived artifact is registered."""

from __future__ import annotations

from dataclasses import dataclass

from minegen.adapters.bundle_reader import read_mine_exchange_bundle
from minegen.adapters.ventsim import VentsimSeedConfig, VentsimSeedPackage, build_ventsim_seed
from minegen.exchange.models import ExchangeManifest
from minegen.services.exchange_service import ExchangeService, safe_scenario_id


@dataclass(frozen=True)
class VentsimSeedExport:
    package: VentsimSeedPackage
    manifest: ExchangeManifest
    filename: str


class AdapterService:
    def __init__(self, exchange: ExchangeService) -> None:
        self.exchange = exchange

    def ventsim_seed(
        self, scenario_id: str, config: VentsimSeedConfig | None = None
    ) -> VentsimSeedExport:
        exported = self.exchange.export(scenario_id)
        bundle = read_mine_exchange_bundle(exported.zip_bytes)
        package = build_ventsim_seed(bundle, config)
        return VentsimSeedExport(
            package=package,
            manifest=exported.manifest,
            filename=f"minegen_{safe_scenario_id(scenario_id)}_ventsim_seed.zip",
        )
