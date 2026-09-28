"""Generic adapter output contract (``docs/external-adapters.md`` §4–§9).

Every adapter package carries one ``AdapterReport``: what was consumed
(four-state source mapping), what was assumed (three-state assumption
policy), what was generated (files with hashes and source ids), how the
coordinates map, and what was deliberately not emitted. The report is a
deterministic document — no wall-clock value.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from minegen.core.models import ApiModel

SourceState = Literal["AVAILABLE", "ABSENT", "SOURCE_NOT_SUCCESS", "UNSUPPORTED_BY_ADAPTER"]
AssumptionState = Literal["NOT_PROVIDED", "USER_REQUIRED", "ADAPTER_DEFAULT_EXPLICIT"]
#: the contract failure codes (§8); the API answers each with its own class
AdapterFailureCode = Literal[
    "MINEEXCHANGE_BUNDLE_INVALID",
    "MINEEXCHANGE_VERSION_UNSUPPORTED",
    "REQUIRED_SOURCE_ABSENT",
    "REQUIRED_PARAMETER_MISSING",
    "TARGET_FORMAT_UNSUPPORTED",
    "COORDINATE_MAPPING_UNSUPPORTED",
    "ADAPTER_CONVERSION_FAILED",
]


class AdapterSourceState(ApiModel):
    """One consumed (or deliberately unconsumed) bundle group (§6)."""

    group: str
    state: SourceState
    #: the bundle's own omission reason when the bundle decided the state
    bundle_reason_code: str | None = None
    detail: str


class AdapterAssumption(ApiModel):
    """A value the target application needs that no MineGen authority owns
    (§7). ``ADAPTER_DEFAULT_EXPLICIT`` records the applied value, its unit,
    scope, documented source and whether the user overrode it; the other two
    states carry no value."""

    kind: str
    state: AssumptionState
    value: float | str | None = None
    unit: str | None = None
    scope: str
    source: str
    user_override: bool | None = None
    note: str


class AdapterGeneratedFile(ApiModel):
    path: str
    media_type: str
    target_semantic: str
    source_entity_ids: list[str]
    source_files: list[str]
    sha256: str


class AdapterCoordinateMapping(ApiModel):
    """Source frame (always the manifest's) → target frame, exactly (§10)."""

    source_frame: str
    target_frame: str
    unit: str
    unit_factor: float
    #: added to every source coordinate (metres, source axes) — an explicit
    #: parameter, never a hidden re-basing
    translation: list[float] = Field(min_length=3, max_length=3)
    note: str


class AdapterOmission(ApiModel):
    """Something the adapter did not emit, and why (typed, never silent)."""

    subject: str
    reason_code: str
    detail: str


class AdapterReport(ApiModel):
    adapter_name: str
    adapter_version: str
    supported_mine_exchange_versions: str
    target_application: str
    source_mine_exchange_version: str
    source_scenario_id: str
    source_scenario_name: str
    #: copied from the manifest (provenance)
    source_snapshot: dict[str, Any]
    coordinate_mapping: AdapterCoordinateMapping
    source_states: list[AdapterSourceState]
    assumptions: list[AdapterAssumption]
    #: every emitted file EXCEPT this report (it cannot carry its own hash)
    generated_files: list[AdapterGeneratedFile]
    omissions: list[AdapterOmission]
    warnings: list[str]
