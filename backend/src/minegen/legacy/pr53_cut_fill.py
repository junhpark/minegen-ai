"""FROZEN PR #53 artifact models (PR #54 review B2, rule 223).

The PR #53 ``CutFillPayload`` and the production models it is built from
(``LocalBounds``, ``SolidGeometry``, ``ProductionReport``, ``CutFillLift``,
``CutFillCut``, ``CutFillBackfill``, ``CutFillMetrics``).

Copied VERBATIM from ``backend/src/minegen/mining/models.py`` at the PR-2 base commit
``1bd68c807730d12053d723d1189c4b901a18cf3e`` (the last commit whose Cut & Fill
artifacts carry no model version). These classes are the ONLY definition of
"a recognized earlier Cut & Fill artifact": ``services/artifact_reader.py``
classifies a document LEGACY only when it VALIDATES here (``extra="forbid"``
through ``ApiModel``, every field typed) — key presence or a method name alone
never does. A document that fails this validation falls through to the
current parser and stays MALFORMED, so no scene read ever discards derived
state on the strength of a corrupt file.

This module is never edited: ``tests/test_cut_fill_legacy_migration.py``
pins its content hash. A change here is an explicit, reviewed decision.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, ValidationError

from minegen.core.models import ApiModel

__all__ = [
    "CutFillPayload",
    "validate_pr53_cut_fill",
]


class LocalBounds(ApiModel):
    """Axis-aligned bounds in the analytic orebody local frame (u strike,
    v down-dip, w thickness normal) — the Phase 21B/C production frame."""

    u_min: float
    u_max: float
    v_min: float
    v_max: float
    w_min: float
    w_max: float


class SolidGeometry(ApiModel):
    """World-space (backend ENU) closed prism mesh: 8 corner vertices as a flat
    ``[x0, y0, z0, …]`` list and 12 outward-wound triangles. Authoritative
    backend geometry; the frontend assembles it verbatim and MineExchange
    exports it verbatim — never re-derived from the bounds."""

    vertices: list[float]
    triangle_indices: list[int]


class ProductionReport(ApiModel):
    """Hard-QA record of one production solid: independent mesh QA
    (finite / indices / degenerate / manifold / watertight / outward) plus
    the analytic ↔ mesh volume agreement and the hard-evaluator sampling."""

    hard_invalid_samples: int
    mesh_closed_solid: bool
    mesh_volume_m3: float = Field(alias="meshVolumeM3")
    volume_agreement: bool
    finite: bool
    valid: bool
    failure_reason: str | None = None


# -- Cut & Fill (Phase 21B) --------------------------------------------------- #


class CutFillLift(ApiModel):
    """One lift of a level interval: an equal partition of the down-dip
    interval between two adjacent levels into ≈ ``liftHeightM`` vertical
    slices, ordered bottom → top."""

    lift_index: int  # 0 = the bottom lift of the whole body, increasing upward
    lower_level_id: str
    upper_level_id: str
    v_min: float
    v_max: float
    vertical_height: float
    cut_ids: list[str]


class CutFillCut(ApiModel):
    id: str
    method: Literal["CUT_AND_FILL"]
    lift_index: int
    cut_index: int
    lower_level_id: str
    upper_level_id: str
    #: the production access CROSSCUT this cut is mined from (levels.json id)
    access_development_id: str
    local_bounds: LocalBounds
    geometry: SolidGeometry
    strike_length: float
    down_dip_span: float
    vertical_height: float
    thickness: float
    geometric_volume_m3: float = Field(alias="geometricVolumeM3")
    tonnes: float
    mean_grade_proxy: float | None  # planning proxy only — NOT a reserve/resource
    planned_state: Literal["PLANNED"] = "PLANNED"
    report: ProductionReport


class CutFillBackfill(ApiModel):
    """Backfill of ONE cut: references the cut's void geometry (1:1), never a
    second copy of the vertices."""

    id: str
    source_cut_id: str
    volume_m3: float = Field(alias="volumeM3")


class CutFillMetrics(ApiModel):
    cut_count: int
    backfill_count: int
    lift_count: int
    level_interval_count: int
    total_geometric_volume_m3: float = Field(alias="totalGeometricVolumeM3")
    total_tonnes: float
    geometric_extraction_fraction_of_orebody: float
    weighted_mean_grade_proxy: float | None
    actual_mean_lift_height: float
    actual_mean_cut_length: float


class CutFillPayload(ApiModel):
    status: Literal["SUCCESS", "FAILED"]
    failure_reason: str | None
    source_revision: str
    method: Literal["CUT_AND_FILL"]
    lifts: list[CutFillLift]
    cuts: list[CutFillCut]
    backfills: list[CutFillBackfill]
    metrics: CutFillMetrics | None


def validate_pr53_cut_fill(document: dict[str, object]) -> CutFillPayload | None:
    """The document as a VALID PR #53 Cut & Fill payload, or ``None`` when it
    is not one (a ``ValidationError`` of the frozen model — a corrupt field,
    a stray key, a wrong type — is never reported further: the caller falls
    through to the current parser, which answers MALFORMED)."""
    try:
        return CutFillPayload.model_validate(document)
    except ValidationError:
        return None
