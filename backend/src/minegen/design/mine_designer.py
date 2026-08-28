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

from minegen.core.models import DeclineSearchConfig, RampConstraints, TunnelProfile
from minegen.design.astar_3d import HybridAStar, SegmentResult, SegmentStatus
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
    chain_backtracks: int = 0

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
            "chainBacktracks": self.chain_backtracks,
            "levels": [lv.to_dict() for lv in self.levels],
            "centerline": {"points": cl.ravel().tolist(), "pointCount": int(cl.shape[0])},
        }


class ChainedDeclineGenerator:
    def __init__(
        self,
        evaluator: DesignCostEvaluator,
        ramp: RampConstraints,
        cfg: DeclineSearchConfig,
        tunnel_profile: TunnelProfile | None = None,
    ) -> None:
        self.ev = evaluator
        self.ramp = ramp
        self.cfg = cfg
        self.astar = HybridAStar(evaluator, ramp, cfg, tunnel_profile=tunnel_profile)

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

        @dataclass
        class _Frame:
            lv: LevelAccessTargets
            cres: list[CandidateSearchResult]
            ok: list[CandidateSearchResult]  # successes, deterministic order
            pick: int = 0

        # chain state = (position, heading|None, cover, burial|None); the
        # initial state starts the portal segment with a free heading
        init_state: tuple[FloatArray, float | None, bool, bool | None] = (
            portal,
            None,
            self.ev.context.minimum_surface_cover <= 0.0,
            None,
        )

        def advance(
            state: tuple[FloatArray, float | None, bool, bool | None],
            pick: CandidateSearchResult,
        ) -> tuple[FloatArray, float | None, bool, bool | None]:
            end = pick.result.end_pose
            assert end is not None
            return (
                end.position,
                end.heading,  # rule 22: terminal heading is inherited
                pick.result.cover_established_at_end,
                pick.result.burial_established_at_end,
            )

        def replay(
            frames: list[_Frame],
        ) -> tuple[FloatArray, float | None, bool, bool | None]:
            st = init_state
            for fr in frames:
                st = advance(st, fr.ok[fr.pick])
            return st

        def search_level(
            li: int,
            lv: LevelAccessTargets,
            state: tuple[FloatArray, float | None, bool, bool | None],
        ) -> _Frame:
            nonlocal expanded_total
            start_pos, start_heading, cover_established, burial_established = state
            cands = lv.valid_candidates[: self.cfg.max_candidates_per_level]
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
                res = self.astar.search(
                    start,
                    c.position,
                    cover_established=cover_established,
                    burial_established=burial_established,
                )
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

            # next-segment launchability (rule 66): a non-final terminal pose
            # must have at least one legal forward/downward successor
            # primitive under the same envelope-aware feasibility contract —
            # an exact target pose whose inherited heading is immediately
            # trapped at the next segment is not a usable arrival
            if li < n_levels - 1:
                for r in cres:
                    if not r.result.success:
                        continue
                    end = r.result.end_pose
                    assert end is not None
                    successors = self.astar.prims.expand(end)
                    evals = self.astar.evaluate_primitives(
                        successors,
                        r.result.cover_established_at_end,
                        r.result.burial_established_at_end,
                    )
                    if not any(e is not None for e in evals):
                        r.result.status = SegmentStatus.INFEASIBLE
                        r.result.cost = math.inf
                        r.result.diagnostics.termination = "NEXT_LAUNCH_INFEASIBLE"
                        r.selection_score = math.inf

            order = sorted(
                (i for i, r in enumerate(cres) if r.result.success),
                key=lambda i: (cres[i].selection_score, i),
            )
            return _Frame(lv, cres, [cres[i] for i in order])

        # bounded deterministic backtracking over per-level candidate lists:
        # a greedy chain commits each level to its best-scored arrival, but an
        # arrival can be one-step launchable yet leave the NEXT level with no
        # feasible corridor (measured on the default scenario: the L10
        # best-scored approach heads into the footwall and strands L11 while
        # two sibling candidates open every L11 target). When a level dies,
        # the nearest ancestor with an untried candidate advances to its next
        # deterministic pick and the chain below is re-searched. The budget
        # keeps worst-case cost bounded; exhausting it fails EXPLICITLY.
        frames: list[_Frame] = []
        state = init_state
        backtracks = 0
        dead: tuple[LevelStatus, LevelResult] | None = None
        while len(frames) < n_levels:
            li = len(frames)
            lv = levels[li]
            cands = lv.valid_candidates[: self.cfg.max_candidates_per_level]
            emit(ProgressStage.LEVEL_STARTED, li, 0, len(cands), level_id=lv.level_id)
            if not cands:
                dead = (
                    LevelStatus.NO_VALID_CANDIDATES,
                    LevelResult(lv, LevelStatus.NO_VALID_CANDIDATES),
                )
                emit(
                    ProgressStage.LEVEL_COMPLETED,
                    li,
                    0,
                    0,
                    level_id=lv.level_id,
                    message="NO_VALID_CANDIDATES",
                )
                break
            f = search_level(li, lv, state)
            if f.ok:
                frames.append(f)
                state = advance(state, f.ok[f.pick])
                emit(
                    ProgressStage.LEVEL_COMPLETED,
                    li,
                    len(cands),
                    len(cands),
                    level_id=lv.level_id,
                    candidate_id=f.ok[f.pick].candidate.id,
                    message="SUCCESS",
                )
                continue
            emit(
                ProgressStage.LEVEL_COMPLETED,
                li,
                len(cands),
                len(cands),
                level_id=lv.level_id,
                message="INFEASIBLE",
            )
            j = len(frames) - 1
            while j >= 0 and frames[j].pick + 1 >= len(frames[j].ok):
                j -= 1
            if j < 0 or backtracks >= self.cfg.max_chain_backtracks:
                dead = (LevelStatus.INFEASIBLE, LevelResult(lv, LevelStatus.INFEASIBLE, f.cres))
                break
            backtracks += 1
            del frames[j + 1 :]
            frames[j].pick += 1
            state = replay(frames)
            emit(
                ProgressStage.LEVEL_STARTED,
                j,
                0,
                0,
                level_id=frames[j].lv.level_id,
                candidate_id=frames[j].ok[frames[j].pick].candidate.id,
                message="CHAIN_BACKTRACK",
            )

        results: list[LevelResult] = []
        for fr in frames:
            for r in fr.cres:
                r.selected = False
            fr.ok[fr.pick].selected = True
            results.append(LevelResult(fr.lv, LevelStatus.SUCCESS, fr.cres))
        if dead is not None:
            results.append(dead[1])
        for lv in levels[len(results) :]:
            results.append(LevelResult(lv, LevelStatus.SKIPPED))

        result = DeclineResult(
            portal=portal,
            levels=results,
            elapsed_ms=(time.perf_counter() - t0) * 1000.0,
            search_config=self.cfg,
            chain_backtracks=backtracks,
        )
        emit(ProgressStage.DECLINE_COMPLETED, n_levels, 0, 0, message=result.status)
        return result
