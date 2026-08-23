"""Chained Hybrid-A* Decline Generator (CLAUDE.md rules 21–22, 53–54).

    Portal ──► {L1 candidates} ──► {L2 candidates} ──► … ──► {Ln candidates}

Greedy, level by level: from the current terminal pose every valid
candidate (up to K) is searched with Hybrid-A*; the winner minimizes

    segment generalized cost + next_level_accessibility × minimum_cost_per_m

and its terminal continuous pose (position + heading) becomes the start of
the next segment. The first segment starts at the portal with the heading
pointing at each candidate (portal orientation is still a free design
variable); later segments inherit the heading. Failure of every candidate
on a level yields a structured SEGMENT_INFEASIBLE result; constraints are
never relaxed.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.core.models import DeclineSearchConfig, RampConstraints
from minegen.design.astar_3d import HybridAStar, SegmentResult
from minegen.design.cost_field import DesignCostEvaluator
from minegen.design.motion_primitives import Pose, azimuth_between
from minegen.design.progress import ProgressCallback, ProgressEvent, ProgressStage, no_progress
from minegen.design.targets import AccessCandidate, AccessTargetSet, LevelAccessTargets

FloatArray = npt.NDArray[np.float64]


class LevelStatus(StrEnum):
    SUCCESS = "SUCCESS"
    INFEASIBLE = "INFEASIBLE"  # every searched candidate failed
    NO_VALID_CANDIDATES = "NO_VALID_CANDIDATES"
    SKIPPED = "SKIPPED"  # a previous level failed


@dataclass
class CandidateSearchResult:
    candidate: AccessCandidate
    initial_heading: float
    result: SegmentResult
    selection_score: float  # inf on failure
    selected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidateId": self.candidate.id,
            "initialHeadingDeg": math.degrees(self.initial_heading) % 360.0,
            "selectionScore": self.selection_score if math.isfinite(self.selection_score) else None,
            "selected": self.selected,
            **self.result.to_dict(),
        }


@dataclass
class LevelResult:
    level: LevelAccessTargets
    status: LevelStatus
    candidate_results: list[CandidateSearchResult] = field(default_factory=list)

    @property
    def selected(self) -> CandidateSearchResult | None:
        return next((c for c in self.candidate_results if c.selected), None)

    def to_dict(self) -> dict[str, Any]:
        sel = self.selected
        return {
            "levelId": self.level.level_id,
            "elevation": self.level.elevation,
            "status": self.status.value,
            "selectedCandidateId": sel.candidate.id if sel else None,
            "candidateResults": [c.to_dict() for c in self.candidate_results],
        }


@dataclass
class DeclineResult:
    portal: FloatArray
    levels: list[LevelResult]
    elapsed_ms: float
    search_config: DeclineSearchConfig

    @property
    def completed_levels(self) -> int:
        return sum(1 for lv in self.levels if lv.status is LevelStatus.SUCCESS)

    @property
    def status(self) -> str:
        if not self.levels:
            return "NO_LEVELS"
        return "SUCCESS" if self.completed_levels == len(self.levels) else "PARTIAL"

    @property
    def selected_segments(self) -> list[CandidateSearchResult]:
        return [lv.selected for lv in self.levels if lv.selected is not None]

    def centerline(self) -> FloatArray:
        parts: list[FloatArray] = []
        for seg in self.selected_segments:
            assert seg.result.path is not None
            pts = seg.result.path.points
            parts.append(pts if not parts else pts[1:])
        return np.vstack(parts) if parts else np.zeros((0, 3))

    def totals(self) -> dict[str, Any]:
        segs = self.selected_segments
        return {
            "rawLength": float(sum(s.result.path.length for s in segs if s.result.path)),
            "generalizedCost": float(sum(s.result.cost for s in segs)),
            "expandedStates": int(
                sum(
                    c.result.diagnostics.expanded_states
                    for lv in self.levels
                    for c in lv.candidate_results
                )
            ),
            "searches": int(sum(len(lv.candidate_results) for lv in self.levels)),
            "maxGrade": float(
                max((s.result.path.max_grade for s in segs if s.result.path), default=0.0)
            ),
            "minimumRadius": float(
                min((s.result.path.min_radius for s in segs if s.result.path), default=math.inf)
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        totals = self.totals()
        if math.isinf(totals["minimumRadius"]):
            totals["minimumRadius"] = None
        cl = self.centerline()
        return {
            "status": self.status,
            "portal": [float(v) for v in self.portal],
            "nLevels": len(self.levels),
            "completedLevels": self.completed_levels,
            "elapsedMs": self.elapsed_ms,
            "totals": totals,
            "searchConfig": self.search_config.model_dump(by_alias=True),
            "levels": [lv.to_dict() for lv in self.levels],
            "centerline": {"points": cl.ravel().tolist(), "pointCount": int(cl.shape[0])},
        }


class ChainedDeclineGenerator:
    def __init__(
        self,
        evaluator: DesignCostEvaluator,
        ramp: RampConstraints,
        cfg: DeclineSearchConfig,
    ) -> None:
        self.ev = evaluator
        self.ramp = ramp
        self.cfg = cfg
        self.astar = HybridAStar(evaluator, ramp, cfg)

    def generate(
        self,
        targets: AccessTargetSet,
        *,
        max_levels: int | None = None,
        on_progress: ProgressCallback = no_progress,
    ) -> DeclineResult:
        t0 = time.perf_counter()
        levels = targets.levels if max_levels is None else targets.levels[:max_levels]
        n_levels = len(levels)
        expanded_total = 0

        def emit(
            stage: ProgressStage,
            li: int,
            ci: int,
            n_c: int,
            *,
            level_id: str = "",
            candidate_id: str = "",
            candidate_status: str = "",
            message: str = "",
        ) -> None:
            # progress = completed levels + fraction of the current level's candidates
            frac = (li + (ci / n_c if n_c else 0.0)) / n_levels if n_levels else 1.0
            on_progress(
                ProgressEvent(
                    stage=stage,
                    phase="DECLINE_SEARCH",
                    level=min(li + 1, n_levels),
                    total_levels=n_levels,
                    candidate=ci,
                    total_candidates=n_c,
                    progress=min(1.0, frac),
                    expanded_states=expanded_total,
                    message=message,
                    level_id=level_id,
                    candidate_id=candidate_id,
                    candidate_status=candidate_status,
                )
            )

        portal = np.asarray(targets.portal, dtype=np.float64)
        start_pos = portal
        start_heading: float | None = None  # None → free (portal)
        cover_established = self.ev.context.minimum_surface_cover <= 0.0
        results: list[LevelResult] = []
        failed = False

        for li, lv in enumerate(levels):
            if failed:
                results.append(LevelResult(lv, LevelStatus.SKIPPED))
                continue
            cands = lv.valid_candidates[: self.cfg.max_candidates_per_level]
            emit(ProgressStage.LEVEL_STARTED, li, 0, len(cands), level_id=lv.level_id)
            if not cands:
                results.append(LevelResult(lv, LevelStatus.NO_VALID_CANDIDATES))
                failed = True
                emit(
                    ProgressStage.LEVEL_COMPLETED,
                    li,
                    0,
                    0,
                    level_id=lv.level_id,
                    message="NO_VALID_CANDIDATES",
                )
                continue

            cres: list[CandidateSearchResult] = []
            for ci, c in enumerate(cands):
                emit(
                    ProgressStage.CANDIDATE_STARTED,
                    li,
                    ci,
                    len(cands),
                    level_id=lv.level_id,
                    candidate_id=c.id,
                )
                heading = (
                    azimuth_between(start_pos, c.position)
                    if start_heading is None
                    else start_heading
                )
                start = Pose(float(start_pos[0]), float(start_pos[1]), float(start_pos[2]), heading)
                res = self.astar.search(start, c.position, cover_established=cover_established)
                expanded_total += res.diagnostics.expanded_states
                score = math.inf
                if res.success:
                    nla = c.next_level_accessibility or 0.0
                    score = res.cost + nla * self.ev.minimum_cost_per_m
                cres.append(CandidateSearchResult(c, heading, res, score))
                emit(
                    ProgressStage.CANDIDATE_COMPLETED,
                    li,
                    ci + 1,
                    len(cands),
                    level_id=lv.level_id,
                    candidate_id=c.id,
                    candidate_status=res.status.value,
                )

            ok = [r for r in cres if r.result.success]
            if not ok:
                results.append(LevelResult(lv, LevelStatus.INFEASIBLE, cres))
                failed = True
                emit(
                    ProgressStage.LEVEL_COMPLETED,
                    li,
                    len(cands),
                    len(cands),
                    level_id=lv.level_id,
                    message="INFEASIBLE",
                )
                continue
            best = min(ok, key=lambda r: r.selection_score)
            best.selected = True
            results.append(LevelResult(lv, LevelStatus.SUCCESS, cres))
            emit(
                ProgressStage.LEVEL_COMPLETED,
                li,
                len(cands),
                len(cands),
                level_id=lv.level_id,
                candidate_id=best.candidate.id,
                message="SUCCESS",
            )
            assert best.result.end_pose is not None
            start_pos = best.result.end_pose.position
            start_heading = best.result.end_pose.heading  # rule 22
            cover_established = best.result.cover_established_at_end

        result = DeclineResult(
            portal=portal,
            levels=results,
            elapsed_ms=(time.perf_counter() - t0) * 1000.0,
            search_config=self.cfg,
        )
        emit(ProgressStage.DECLINE_COMPLETED, n_levels, 0, 0, message=result.status)
        return result
