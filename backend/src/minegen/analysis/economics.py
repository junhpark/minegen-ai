"""Planning economics assumptions (Phase 22B §23–32).

``EconomicsConfig`` is the USER-AUTHORED assumption document persisted as
``data/scenarios/{id}/economics.json`` — beside ``scenario.json``, NOT under
``derived/``. It is not a mine-design input: changing it invalidates no
geometry, production or timeline artifact, and no scenario field carries an
economic assumption. There are no hidden defaults — an absent document makes
the economics section ``NOT_CONFIGURED`` — and the ONE revenue model is
``plannedMinedTonnes × grossRevenuePerMinedTonne``. No metal price, recovery,
payability, smelter charge, grade unit or commodity exists in v0.1; the
planning grade proxy is never a revenue input.

The document revision is ``sha256(canonical JSON)`` of the validated config:
deterministic, no timestamp, identical for identical assumptions.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError

from minegen.core.enums import EdgeType, MiningMethodType
from minegen.core.models import ApiModel
from minegen.core.publication import publish_text
from minegen.core.revision import file_revision
from minegen.services.artifact_errors import ArtifactMalformedError
from minegen.services.scenario_service import ScenarioStore

__all__ = [
    "ECONOMICS_FILE",
    "CostBreakdown",
    "DevelopmentCostRates",
    "EconomicsConfig",
    "EconomicsConfigResponse",
    "EconomicsObservation",
    "ProductionCostRates",
    "canonical_json",
    "config_revision",
    "development_rate",
    "economics_path",
    "observe_economics",
    "production_rate",
    "write_economics",
]

ECONOMICS_FILE = "economics.json"


class DevelopmentCostRates(ApiModel):
    """Cost per metre of development, by MineNetwork edge type."""

    ramp_per_m: float = Field(ge=0.0)
    level_access_per_m: float = Field(ge=0.0)
    drift_per_m: float = Field(ge=0.0)
    crosscut_per_m: float = Field(ge=0.0)
    #: ``EdgeType.RAISE`` is a typed network edge (no generator emits one in
    #: v0.1); the rate exists so a RAISE edge is priced, never refused as an
    #: inconsistency (PR #48 review)
    raise_per_m: float = Field(ge=0.0)
    shaft_per_m: float = Field(ge=0.0)
    shaft_station_access_per_m: float = Field(ge=0.0)


class ProductionCostRates(ApiModel):
    """Mining cost per planned mined tonne, by method. Only the ACTIVE
    scenario method's rate is consumed; the others are kept editable."""

    longhole_open_stoping_per_tonne: float = Field(ge=0.0)
    cut_and_fill_per_tonne: float = Field(ge=0.0)
    room_and_pillar_per_tonne: float = Field(ge=0.0)


class EconomicsConfig(ApiModel):
    version: Literal[1] = 1
    currency_code: str = Field(pattern=r"^[A-Z]{3}$")
    development_costs: DevelopmentCostRates
    production_costs: ProductionCostRates
    processing_cost_per_tonne: float = Field(ge=0.0)
    backfill_cost_per_m3: float = Field(ge=0.0)
    fixed_operating_cost_per_day: float = Field(ge=0.0)
    gross_revenue_per_mined_tonne: float = Field(ge=0.0)
    initial_capital_cost: float = Field(ge=0.0)
    annual_discount_rate: float = Field(ge=0.0)
    #: explicit — recommended 30, never defaulted
    cashflow_bucket_days: float = Field(gt=0.0)


class EconomicsConfigResponse(ApiModel):
    configured: bool
    revision: str | None
    config: EconomicsConfig | None


def canonical_json(config: EconomicsConfig) -> str:
    """The persisted form: sorted keys, compact separators, aliases."""
    return json.dumps(
        config.model_dump(mode="json", by_alias=True),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def config_revision(config: EconomicsConfig) -> str:
    return hashlib.sha256(canonical_json(config).encode("utf-8")).hexdigest()


def economics_path(store: ScenarioStore, scenario_id: str) -> Path:
    return store.scenario_dir(scenario_id) / ECONOMICS_FILE


@dataclass(frozen=True)
class EconomicsObservation:
    """One lock-held observation of ``economics.json``: absent (``config``
    ``None``), or the validated config with its content revision. The file
    revision (rule-60 stat identity) is what the snapshot re-check compares."""

    config: EconomicsConfig | None
    revision: str | None
    file_revision: str | None


def observe_economics(store: ScenarioStore, scenario_id: str) -> EconomicsObservation:
    """Read + validate under the store lock. A present-but-unusable document
    is ``ARTIFACT_MALFORMED`` (409), never a silent NOT_CONFIGURED."""
    path = economics_path(store, scenario_id)
    with store.lock(scenario_id):
        rev = file_revision(path)
        if rev is None:
            return EconomicsObservation(None, None, None)
        try:
            data = path.read_bytes()
        except OSError as err:
            raise ArtifactMalformedError(ECONOMICS_FILE, "its bytes could not be read") from err
    try:
        document: Any = json.loads(data)
    except ValueError as err:
        raise ArtifactMalformedError(ECONOMICS_FILE, "is not valid JSON") from err
    if not isinstance(document, dict):
        raise ArtifactMalformedError(ECONOMICS_FILE, "is not a JSON object")
    try:
        config = EconomicsConfig.model_validate(document)
    except ValidationError as err:
        raise ArtifactMalformedError(
            ECONOMICS_FILE, f"fails the EconomicsConfig schema ({err.error_count()} errors)"
        ) from err
    return EconomicsObservation(config, config_revision(config), rev)


def write_economics(store: ScenarioStore, scenario_id: str, config: EconomicsConfig) -> str:
    """Atomic publication of the canonical document (rule-60 atomic write);
    touches nothing else in the scenario directory. Returns the content
    revision."""
    path = economics_path(store, scenario_id)
    with store.lock(scenario_id):
        publish_text(path, canonical_json(config))
    return config_revision(config)


# --------------------------------------------------------------------------- #
# Rates and totals (22B §31–32)
# --------------------------------------------------------------------------- #

_DEVELOPMENT_RATE_FIELD: dict[EdgeType, str] = {
    EdgeType.RAMP: "ramp_per_m",
    EdgeType.LEVEL_ACCESS: "level_access_per_m",
    EdgeType.DRIFT: "drift_per_m",
    EdgeType.CROSSCUT: "crosscut_per_m",
    EdgeType.RAISE: "raise_per_m",
    EdgeType.SHAFT: "shaft_per_m",
    EdgeType.SHAFT_STATION_ACCESS: "shaft_station_access_per_m",
}

_PRODUCTION_RATE_FIELD: dict[MiningMethodType, str] = {
    MiningMethodType.LONGHOLE_OPEN_STOPING: "longhole_open_stoping_per_tonne",
    MiningMethodType.CUT_AND_FILL: "cut_and_fill_per_tonne",
    MiningMethodType.ROOM_AND_PILLAR: "room_and_pillar_per_tonne",
}


def development_rate(config: EconomicsConfig, edge_type: EdgeType) -> float | None:
    """The per-metre rate of an edge type — every ``EdgeType`` member has
    one; ``None`` only for a member added to the enum without a rate (a
    programming error the analysis reports as a typed inconsistency)."""
    field = _DEVELOPMENT_RATE_FIELD.get(edge_type)
    if field is None:
        return None
    return float(getattr(config.development_costs, field))


def production_rate(config: EconomicsConfig, method: MiningMethodType) -> float | None:
    field = _PRODUCTION_RATE_FIELD.get(method)
    if field is None:
        return None
    return float(getattr(config.production_costs, field))


@dataclass(frozen=True)
class CostBreakdown:
    development_cost: float
    production_mining_cost: float
    processing_cost: float
    backfill_cost: float
    fixed_operating_cost: float
    initial_capital_cost: float
    total_revenue: float

    @property
    def total_cost(self) -> float:
        return math.fsum(
            [
                self.development_cost,
                self.production_mining_cost,
                self.processing_cost,
                self.backfill_cost,
                self.fixed_operating_cost,
                self.initial_capital_cost,
            ]
        )

    @property
    def undiscounted_net_cashflow(self) -> float:
        return self.total_revenue - self.total_cost
