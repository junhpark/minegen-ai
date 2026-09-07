"""Phase 08 level-development typed contract (rules 71–74).

``derived/levels.json`` is the validated centerline artifact that OWNS the
Phase 08 DRIFT and CROSSCUT geometry (rule 71): polylines live here, and
MineNetwork edges reference this artifact by development index. The persisted
payload is exactly the deterministic camelCase serialization of these models.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from minegen.core.models import ApiModel


class DevelopmentKind(StrEnum):
    DRIFT = "DRIFT"
    CROSSCUT = "CROSSCUT"


class Centerline(ApiModel):
    points: list[float]  # flat [x0, y0, z0, x1, …] — same shape as Phase 05


class DevelopmentReport(ApiModel):
    """Explicit hard-validation record per development (rule 72): invalid
    required development fails the artifact, never silently omitted."""

    start_weld_error: float
    centerline_invalid_samples: int = 0  # blocker-1 gate: hard-context validity
    envelope_hard_violations: int
    envelope_above_terrain: int
    terminal_sdf: float | None = None  # crosscut only: |sdf| at first contact
    #: crosscut on an implicit body (Phase 20C.2A): width of the final
    #: contains()-bisection bracket at the ore-contact terminal (m); the
    #: terminal itself is the OUTSIDE end of that bracket
    terminal_contact_gap: float | None = None
    interior_breach_samples: int = 0  # crosscut only: pre-terminal inside-ore
    field_cost: float
    valid: bool
    failure_reason: str | None = None


class Development(ApiModel):
    id: str
    kind: DevelopmentKind
    level_id: str
    station_index: int | None = None  # crosscut station k (…,-1, 0, +1,…)
    station_u: float | None = None  # crosscut station strike coordinate
    #: span coordinates along the level backbone: the canonical +u strike
    #: coordinate (TABULAR rule 43) or the offset-trace CHAINAGE for a
    #: curved section-trace backbone (Phase 20C.2A)
    from_u: float
    to_u: float
    centerline: Centerline
    length3d: float = Field(alias="length3d")
    mean_gradient_signed: float  # Δz / horizontal length; negative = descending
    max_abs_gradient: float
    report: DevelopmentReport


class ExcludedStation(ApiModel):
    """A planned crosscut station excluded from the REQUIRED lattice
    (rule 180, rule 141 precedent): neither horizontal perpendicular of the
    local trace tangent finds ore within the bounded probe — the offset
    level set wraps around the body's tapered ends, so end stations can sit
    past the local ore extent. Reported explicitly, never silently
    dropped; ``probe_length`` is the bounded probe used (m)."""

    station_index: int
    station_u: float
    reason: Literal["NO_PERPENDICULAR_ORE_SUPPORT"]
    probe_length: float


class LevelSummary(ApiModel):
    level_id: str
    candidate_id: str
    #: exact LEVEL_ENTRY (rule 71): the Phase 05 segment end for LEGACY, the
    #: level-access terminal for LAYOUT_V2 (rule 157)
    entry: tuple[float, float, float]
    entry_u: float
    drift_piece_count: int
    crosscut_count: int
    valid: bool
    #: rule 180 station confirmation (curved backbones only; empty for
    #: TABULAR_RULE_43): planned stations excluded from the required lattice
    excluded_stations: list[ExcludedStation] = []


class LevelsMetrics(ApiModel):
    level_count: int
    development_count: int
    drift_piece_count: int
    crosscut_count: int
    station_pitch: float  # stope_length + minimum_pillar (rule 72)
    stations_per_level: int
    total_drift_length3d: float = Field(alias="totalDriftLength3d")
    total_crosscut_length3d: float = Field(alias="totalCrosscutLength3d")


class ProductionDevelopment(ApiModel):
    """Method-specific production development status (Phase 20B, rule 159):
    the generic backbone drift is always attempted; the production lattice
    (longhole crosscut stations) exists only for an implemented method, and
    a reserved method reports UNSUPPORTED_METHOD explicitly — never a silent
    longhole substitute."""

    method: str
    status: Literal["IMPLEMENTED", "UNSUPPORTED_METHOD"]
    reason: str | None = None


class LevelsPayload(ApiModel):
    status: Literal["SUCCESS", "FAILED"]
    failure_reason: str | None
    source_revision: str
    #: LEGACY_RAMP_SEGMENT (Phase 05 segment ends) | LEVEL_ACCESS (rule 157)
    entry_source: Literal["LEGACY_RAMP_SEGMENT", "LEVEL_ACCESS"] = "LEGACY_RAMP_SEGMENT"
    #: which backbone geometry contract developed the levels (Phase 20C.2A):
    #: TABULAR_RULE_43 (exact strike line) or SECTION_FOOTWALL_OFFSET_TRACE
    #: (curved trace of the numerical section geometry)
    development_geometry: Literal["TABULAR_RULE_43", "SECTION_FOOTWALL_OFFSET_TRACE"] | None = None
    production_development: ProductionDevelopment | None = None
    developments: list[Development]
    levels: list[LevelSummary]
    metrics: LevelsMetrics | None
