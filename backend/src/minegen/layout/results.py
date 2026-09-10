"""Layout-v2 search result data model and serialization (AC-01C).

The typed result of one ``LayoutV2Search`` run — candidate records, their
stage-4 reports and the catalogue payload — extracted verbatim from
``layout.search`` so the certification and materialization boundaries can
type their inputs without importing the search itself. Every ``to_dict``
here is byte-load-bearing: the persisted artifacts are written with
``json.dumps`` in dict insertion order.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.layout.access import AnchorFailure, LevelAccessPlan, LevelDevelopmentAnchor
from minegen.layout.certification import ClearanceReport
from minegen.layout.families import CandidateParams
from minegen.layout.geometry import CenterlineDiagnostics, Crossing
from minegen.layout.levels import RequiredLevel

FloatArray = npt.NDArray[np.float64]

LAYOUT_V2_VERSION = 1


class CandidateStatus:
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    NOT_VALIDATED = "NOT_VALIDATED"  # cheap-feasible but outside the shortlist


class Stage:
    CONSTRUCT = "CONSTRUCT"
    CHEAP = "CHEAP"
    DETAILED = "DETAILED"


@dataclass
class LevelServiceRecord:
    """Cheap ACCESS-POTENTIAL screen of one required level against the main
    ramp (Phase 20A semantics, kept as a stage-2 screen in Phase 20B): the
    ramp's RL crossing and its horizontal distance to the orebody footprint.
    ``within_reach`` is NOT "served" — a level is served only by a validated
    level access (``LevelAccess.ok``, rule 156)."""

    level_id: str
    elevation: float
    within_reach: bool
    connection_position: FloatArray | None = None
    connection_chainage: float | None = None
    access_distance: float | None = None
    unserved_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "levelId": self.level_id,
            "elevation": self.elevation,
            "withinReach": self.within_reach,
            "referencePosition": (
                [float(v) for v in self.connection_position]
                if self.connection_position is not None
                else None
            ),
            "referenceChainage": self.connection_chainage,
            "footprintDistance": self.access_distance,
            "screenReason": self.unserved_reason,
        }


@dataclass
class Scores:
    development: float
    geology: float
    geometry: float
    total: float
    components: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "development": self.development,
            "geology": self.geology,
            "geometry": self.geometry,
            "total": self.total,
            "components": dict(self.components),
        }


@dataclass
class CandidateResult:
    params: CandidateParams
    status: str = CandidateStatus.INFEASIBLE
    stage_reached: str = Stage.CONSTRUCT
    failure_reasons: list[str] = field(default_factory=list)
    failure_detail: str | None = None
    diagnostics: CenterlineDiagnostics | None = None
    level_service: list[LevelServiceRecord] = field(default_factory=list)
    scores: Scores | None = None
    clearance: ClearanceReport | None = None
    exposure: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    access_plan: LevelAccessPlan | None = None
    anchors: list[LevelDevelopmentAnchor | AnchorFailure | None] = field(default_factory=list)
    derived: dict[str, Any] = field(default_factory=dict)
    pieces: list[dict[str, Any]] = field(default_factory=list)
    points: FloatArray | None = None
    crossings: list[Crossing | None] = field(default_factory=list)
    shortlisted: bool = False
    cheap_proxy: float | None = None
    #: Phase 20C.1-Q geometric access screen (evaluator-free stage-4 gates,
    #: spacing ignored; NECESSARY_CONDITION under EXACT, HEURISTIC under
    #: conservative clearance; never a rejection)
    access_screen: dict[str, Any] | None = None
    rank: int | None = None

    @property
    def candidate_id(self) -> str:
        return self.params.candidate_id

    @property
    def screened_count(self) -> int:
        """Levels passing the cheap access-potential screen."""
        return sum(1 for r in self.level_service if r.within_reach)

    @property
    def screen_blocked(self) -> int:
        """Levels the geometric access screen reports BLOCKED (0 before it ran).
        What that PROVES depends on the clearance policy — see
        ``screen_authority`` and ``access_screen["authority"]``: a necessary
        condition under an exact distance contract, a heuristic under a
        conservative one."""
        return int(self.access_screen["blockedCount"]) if self.access_screen else 0

    @property
    def screen_authority(self) -> str:
        """``NECESSARY_CONDITION`` | ``HEURISTIC`` (empty before the screen ran)."""
        return str(self.access_screen["authority"]) if self.access_screen else ""

    @property
    def accessible_count(self) -> int | None:
        """Levels with a validated level access (None before stage 4)."""
        if self.access_plan is None:
            return None
        return sum(1 for a in self.access_plan.accesses if a.ok)

    def to_dict(self, *, include_points: bool) -> dict[str, Any]:
        d: dict[str, Any] = {
            "candidateId": self.candidate_id,
            "family": self.params.family.value,
            "parameters": self.params.to_dict(),
            "status": self.status,
            "stageReached": self.stage_reached,
            "failureReasons": list(self.failure_reasons),
            "failureDetail": self.failure_detail,
            "shortlisted": self.shortlisted,
            "rank": self.rank,
            "screenedLevels": self.screened_count,
            "accessibleLevels": self.accessible_count,
            "requiredLevels": len(self.level_service),
            "rampLevelReferences": [r.to_dict() for r in self.level_service],
            "access": self.access_plan.summary() if self.access_plan else None,
            "levelAccesses": (
                [a.to_dict(include_points=include_points) for a in self.access_plan.accesses]
                if self.access_plan
                else None
            ),
            "diagnostics": self.diagnostics.to_dict() if self.diagnostics else None,
            "scores": self.scores.to_dict() if self.scores else None,
            "clearance": self.clearance.to_dict() if self.clearance else None,
            "exposure": self.exposure,
            "validation": self.validation,
            "derived": _finite_dict(self.derived),
            "pieces": self.pieces,
            "cheapProxy": self.cheap_proxy,
            "accessScreen": self.access_screen,
        }
        if include_points and self.points is not None:
            d["centerline"] = {
                "points": [float(v) for v in self.points.ravel()],
                "pointCount": int(self.points.shape[0]),
            }
        else:
            d["centerline"] = None
        return d


def _finite_dict(d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, float | np.floating):
            out[k] = float(v) if math.isfinite(float(v)) else None
        elif isinstance(v, np.integer):
            out[k] = int(v)
        elif isinstance(v, np.bool_):
            out[k] = bool(v)
        else:
            out[k] = v
    return out


@dataclass
class LayoutSearchResult:
    levels: list[RequiredLevel]  # every required level from the generic generator
    serviceable_ids: list[str]  # those intersecting the orebody solid
    track: dict[str, Any] | None
    portal: FloatArray
    portal_generated: bool
    candidates: list[CandidateResult]
    shortlist: list[str]
    ranking: list[str]
    winner_id: str | None
    clearance_basis: str
    clearance_error_bound: float
    required_clearance: float
    access_reach: float
    standoff: float
    performance: dict[str, Any]
    config: dict[str, Any]

    @property
    def serviceable_levels(self) -> list[RequiredLevel]:
        return [lv for lv in self.levels if lv.level_id in self.serviceable_ids]

    def candidate(self, candidate_id: str) -> CandidateResult | None:
        for c in self.candidates:
            if c.candidate_id == candidate_id:
                return c
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "layoutVersion": LAYOUT_V2_VERSION,
            "status": "SUCCESS" if self.winner_id is not None else "NO_FEASIBLE_CANDIDATE",
            "portal": [float(v) for v in self.portal],
            "portalGenerated": self.portal_generated,
            "requiredLevels": [
                {
                    "levelId": lv.level_id,
                    "index": lv.index,
                    "elevation": lv.elevation,
                    "hasOrebodySection": lv.level_id in self.serviceable_ids,
                }
                for lv in self.levels
            ],
            "serviceableLevelCount": len(self.serviceable_ids),
            "footwallTrack": self.track,
            "candidateCount": len(self.candidates),
            "feasibleCount": sum(
                1 for c in self.candidates if c.status == CandidateStatus.FEASIBLE
            ),
            "shortlist": list(self.shortlist),
            "ranking": list(self.ranking),
            "winnerId": self.winner_id,
            "clearanceBasis": self.clearance_basis,
            "clearanceErrorBound": self.clearance_error_bound,
            "requiredClearance": self.required_clearance,
            "accessReach": self.access_reach,
            "footwallStandoff": self.standoff,
            "performance": self.performance,
            "searchConfig": self.config,
            "candidates": [c.to_dict(include_points=c.shortlisted) for c in self.candidates],
        }
