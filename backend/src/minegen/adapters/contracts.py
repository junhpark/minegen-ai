"""Common adapter output contract (``docs/external-adapters.md`` §4–§9,
directive §6–§7).

Every adapter package carries one ``adapter_manifest.json`` — an
``AdapterManifest``: what was consumed (FIVE-state source mapping), what was
assumed (three-state assumption policy), what was generated (files with
hashes, semantics and sources), how coordinates map, the identity map
between target ids and bundle ids, and what was deliberately not emitted.
The manifest is deterministic — no wall-clock value.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from minegen.core.models import ApiModel

#: directive §6 — the five source states
#:   AVAILABLE               the bundle carries the group and the adapter consumed it
#:   ARTIFACT_ABSENT         MineGen never generated the artifact (bundle omission)
#:   SOURCE_NOT_SUCCESS      the artifact exists but is FAILED (bundle omission)
#:   NOT_EXPORTED_BY_VERSION the MineGen authority may exist but this MineExchange
#:                           version does not expose it (bundle NOT_IN_V1, or a
#:                           group a newer version would carry)
#:   UNSUPPORTED_BY_ADAPTER  the bundle carries it, this adapter does not consume it
SourceState = Literal[
    "AVAILABLE",
    "ARTIFACT_ABSENT",
    "SOURCE_NOT_SUCCESS",
    "NOT_EXPORTED_BY_VERSION",
    "UNSUPPORTED_BY_ADAPTER",
]
AssumptionState = Literal["NOT_PROVIDED", "USER_REQUIRED", "ADAPTER_DEFAULT_EXPLICIT"]
AdapterTarget = Literal["VENTSIM", "ANYLOGIC", "UNITY", "UNREAL"]


class AdapterSourceState(ApiModel):
    """One bundle group in exactly one of the five states (§6)."""

    group: str
    state: SourceState
    #: the bundle's own omission reason when the bundle decided the state
    bundle_reason_code: str | None = None
    detail: str


class AdapterAssumption(ApiModel):
    """A value the target application needs that no MineGen authority owns
    (§7). ``ADAPTER_DEFAULT_EXPLICIT`` records the applied value, its unit,
    scope, documented source and whether the user overrode it; the other two
    states carry no value — a number in a package that is neither in the
    bundle nor recorded here is a defect."""

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
    """Source frame (always the manifest's) → target frame, exactly (§10).
    ``transform`` is a glTF-style column-major 4×4 (16 values) applied to
    source coordinates, or ``null`` for identity."""

    source_frame: str
    target_frame: str
    unit: str
    unit_factor: float
    handedness: str
    up_axis: str
    transform: list[float] | None = Field(default=None, min_length=16, max_length=16)
    note: str


class AdapterIdentityEntry(ApiModel):
    """One target-side identity ↔ bundle identity link."""

    target_id: str
    target_kind: str
    bundle_entity_id: str | None = None
    bundle_edge_id: str | None = None
    bundle_node_id: str | None = None
    file: str | None = None


class AdapterOmission(ApiModel):
    """Something the adapter did not emit, and why (typed, never silent)."""

    subject: str
    reason_code: str
    detail: str


class AdapterManifest(ApiModel):
    adapter_name: str
    adapter_version: str
    target_application: AdapterTarget
    supported_mine_exchange_versions: str
    source_mine_exchange_version: str
    source_scenario_id: str
    source_scenario_name: str
    #: copied from the bundle manifest (provenance)
    source_snapshot: dict[str, Any]
    coordinate_mapping: AdapterCoordinateMapping
    #: every emitted file EXCEPT this manifest (it cannot carry its own hash)
    generated_files: list[AdapterGeneratedFile]
    identity_map: list[AdapterIdentityEntry]
    source_states: list[AdapterSourceState]
    assumptions: list[AdapterAssumption]
    warnings: list[str]
    omissions: list[AdapterOmission]
    #: adapter-specific typed facts (counts, normalization results)
    details: dict[str, Any] = {}
