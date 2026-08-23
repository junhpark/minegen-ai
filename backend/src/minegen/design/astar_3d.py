"""Single-segment Hybrid-A* decline search (CLAUDE.md rules 47–55).

Search state is a continuous ``Pose`` plus a ``cover_established`` flag;
the closed set is keyed on ``(ix, iy, iz, ih, cover)``. Every primitive is
validated and costed along all its samples through ``DesignCostEvaluator``;
a successful segment ends with an exact goal-shot connector.

Ordering: ``(floor(f / bucket), horizontal_distance_to_target, f)``. With
``bucket = 0`` this is plain A*. With the default bucket of one primitive's
minimum cost, ties within a bucket prefer states closer to the target, which
keeps the search spiralling near the access point instead of flooding the
plateau where the admissible heuristic is flat (rule 55).
"""

from __future__ import annotations

import heapq
import math
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.core.models import DeclineSearchConfig, RampConstraints
from minegen.design.constraints import RejectionReason
from minegen.design.cost_field import DesignCostEvaluator
from minegen.design.motion_primitives import (
    Pose,
    Primitive,
    PrimitiveSet,
    Steering,
    dubins_cs_length,
)

FloatArray = npt.NDArray[np.float64]


class SegmentStatus(StrEnum):
    SUCCESS = "SUCCESS"
    INFEASIBLE = "INFEASIBLE"  # open set exhausted
    EXPANSION_LIMIT = "EXPANSION_LIMIT"
    TIME_LIMIT = "TIME_LIMIT"


@dataclass
class SearchDiagnostics:
    expanded_states: int = 0
    generated_states: int = 0
    closed_states: int = 0
    peak_open_size: int = 0
    pruned_overshoot: int = 0
    rejected_primitives: int = 0
    goal_shot_attempts: int = 0
    goal_shot_failures: dict[str, int] = field(default_factory=dict)
    elapsed_ms: float = 0.0
    termination: str = ""
    tie_break_bucket: float = 0.0
    heuristic_weight: float = 1.0
    admissible_bound: float = 0.0  # h(start): lower bound on the segment cost
    # closest approach to the target among expanded states (failure analysis)
    best_approach_horizontal: float = math.inf
    best_approach_dz: float = math.inf
    best_approach_depth: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "expandedStates": self.expanded_states,
            "generatedStates": self.generated_states,
            "closedStates": self.closed_states,
            "peakOpenSize": self.peak_open_size,
            "prunedOvershoot": self.pruned_overshoot,
            "rejectedPrimitives": self.rejected_primitives,
            "goalShotAttempts": self.goal_shot_attempts,
            "goalShotFailures": dict(self.goal_shot_failures),
            "elapsedMs": self.elapsed_ms,
            "termination": self.termination,
            "tieBreakBucket": self.tie_break_bucket,
            "heuristicWeight": self.heuristic_weight,
            "admissibleBound": self.admissible_bound,
            "bestApproach": {
                "horizontal": None
                if math.isinf(self.best_approach_horizontal)
                else self.best_approach_horizontal,
                "dz": None if math.isinf(self.best_approach_dz) else self.best_approach_dz,
                "depth": self.best_approach_depth,
            },
        }


@dataclass
class SegmentPath:
    primitives: list[Primitive]
    start: Pose
    end: Pose

    @property
    def points(self) -> FloatArray:
        """Concatenated samples with shared endpoints removed, shape (N, 3)."""
        parts = [self.primitives[0].samples] + [p.samples[1:] for p in self.primitives[1:]]
        return np.vstack(parts)

    @property
    def length(self) -> float:
        return float(sum(p.length_3d for p in self.primitives))

    @property
    def max_grade(self) -> float:
        return float(max(abs(p.grade) for p in self.primitives))

    @property
    def min_radius(self) -> float:
        return float(min(p.radius for p in self.primitives))

    def to_dict(self) -> dict[str, Any]:
        pts = self.points
        return {
            "points": pts.ravel().tolist(),
            "pointCount": int(pts.shape[0]),
            "primitives": [
                {
                    "steering": p.steering.name,
                    "grade": p.grade,
                    "curvature": p.curvature,
                    "horizontalLength": p.horizontal_length,
                    "length3d": p.length_3d,
                    "endHeadingDeg": math.degrees(p.end.heading) % 360.0,
                }
                for p in self.primitives
            ],
            "length": self.length,
            "maxGrade": self.max_grade,
            "minRadius": None if math.isinf(self.min_radius) else self.min_radius,
            "startHeadingDeg": math.degrees(self.start.heading) % 360.0,
            "endHeadingDeg": math.degrees(self.end.heading) % 360.0,
        }


@dataclass
class SegmentResult:
    status: SegmentStatus
    path: SegmentPath | None
    cost: float  # generalized cost, inf on failure
    diagnostics: SearchDiagnostics
    end_pose: Pose | None
    cover_established_at_end: bool

    @property
    def success(self) -> bool:
        return self.status is SegmentStatus.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "generalizedCost": self.cost if math.isfinite(self.cost) else None,
            "rawPathLength": self.path.length if self.path else None,
            "maxGrade": self.path.max_grade if self.path else None,
            "minimumRadius": (
                None
                if self.path is None or math.isinf(self.path.min_radius)
                else self.path.min_radius
            ),
            "endHeadingDeg": math.degrees(self.end_pose.heading) % 360.0 if self.end_pose else None,
            "diagnostics": self.diagnostics.to_dict(),
            "path": self.path.to_dict() if self.path else None,
        }


@dataclass(order=False)
class _Node:
    pose: Pose
    g: float
    h: float
    cover: bool
    parent: _Node | None
    primitive: Primitive | None
    depth: int

    def f(self, weight: float) -> float:
        return self.g + weight * self.h


class HybridAStar:
    def __init__(
        self,
        evaluator: DesignCostEvaluator,
        ramp: RampConstraints,
        cfg: DeclineSearchConfig,
        *,
        sample_spacing: float | None = None,
    ) -> None:
        self.ev = evaluator
        self.ramp = ramp
        self.cfg = cfg
        spacing = sample_spacing if sample_spacing is not None else self.default_sample_spacing()
        self.prims = PrimitiveSet(
            min_turn_radius=ramp.min_turn_radius,
            heading_bins=cfg.heading_bins,
            max_gradient=ramp.max_gradient,
            grade_fractions=tuple(cfg.grade_fractions),
            max_sample_spacing=spacing,
        )
        self._best_node: _Node | None = None
        self.min_cover = evaluator.context.minimum_surface_cover
        self.min_cost = evaluator.minimum_cost_per_m
        self.heading_step = self.prims.heading_step

    def default_sample_spacing(self) -> float:
        """Rule 50: ≤ min(max_sample_spacing, smallest fault core half-width)."""
        cores = [f.config.core_half_width for f in self.ev.faults]
        return float(min([self.cfg.max_sample_spacing, *cores]))

    # -- discretization (rule 47) ------------------------------------------ #

    def key(self, pose: Pose, cover: bool) -> tuple[int, int, int, int, bool]:
        ih = round(pose.heading / self.heading_step) % self.cfg.heading_bins
        return (
            math.floor(pose.x / self.cfg.xy_resolution),
            math.floor(pose.y / self.cfg.xy_resolution),
            math.floor(pose.z / self.cfg.z_resolution),
            ih,
            cover,
        )

    # -- primitive evaluation (rules 50, 52) ------------------------------- #

    def evaluate_primitives(
        self, prims: list[Primitive], cover_established: bool
    ) -> list[tuple[float, bool] | None]:
        """For each primitive: ``(integrated cost, cover_established_after)``
        or ``None`` if any sample is infeasible. One batched evaluator call."""
        all_pts = np.vstack([p.samples for p in prims])
        ev = self.ev.evaluate_points(all_pts)
        surface = self.ev.surface_elevation(all_pts)
        finite_cost = ev.base_cost + ev.rock_penalty + ev.fault_penalty + ev.orebody_penalty
        out: list[tuple[float, bool] | None] = []
        offset = 0
        transition_possible = self.min_cover > 0.0 and not cover_established
        for p in prims:
            n = p.samples.shape[0]
            sl = slice(offset, offset + n)
            offset += n
            valid = ev.valid[sl]
            established = cover_established
            if not transition_possible:
                if not valid.all():
                    out.append(None)
                    continue
            else:
                reasons = ev.rejection_reasons[sl]
                cover = surface[sl] - p.samples[:, 2]
                ok = True
                for i in range(n):
                    if not valid[i] and (
                        established
                        or any(r is not RejectionReason.INSUFFICIENT_COVER for r in reasons[i])
                    ):
                        ok = False  # only INSUFFICIENT_COVER is forgiven, only before cover
                        break
                    if not established and cover[i] >= self.min_cover:
                        established = True
                if not ok:
                    out.append(None)
                    continue
            c = finite_cost[sl]
            cost = float(np.dot(0.5 * (c[1:] + c[:-1]), np.diff(p.sample_arc)))
            out.append((cost, established))
        return out

    # -- search ------------------------------------------------------------ #

    def search(
        self,
        start: Pose,
        target: FloatArray,
        *,
        cover_established: bool = True,
    ) -> SegmentResult:
        t0 = time.perf_counter()
        diag = SearchDiagnostics()
        tgt = np.asarray(target, dtype=np.float64)
        gmax = self.ramp.max_gradient
        bucket = self.cfg.tie_break_bucket_primitives * self.prims.horizontal_length * self.min_cost
        diag.tie_break_bucket = bucket
        goal_radius = self.cfg.goal_shot_radius_primitives * self.prims.horizontal_length
        max_dtheta = math.radians(self.cfg.goal_shot_max_heading_change_deg)
        z_floor = float(tgt[2]) - self.cfg.vertical_tolerance
        deadline = (
            t0 + self.cfg.max_search_seconds if self.cfg.max_search_seconds is not None else None
        )

        r_min = self.ramp.min_turn_radius

        def h_of(pose: Pose) -> float:
            """Admissible: horizontal length ≥ max(Dubins CS length, Δz/g_max);
            3D length ≥ sqrt(horizontal² + Δz²); times the minimum cost/m."""
            dz = float(tgt[2]) - pose.z
            l_dub = dubins_cs_length(pose, tgt[:2], r_min)
            horizontal = max(l_dub, abs(dz) / gmax)
            return math.hypot(horizontal, dz) * self.min_cost

        def horiz(pose: Pose) -> float:
            return math.hypot(pose.x - float(tgt[0]), pose.y - float(tgt[1]))

        mode = self.cfg.tie_break_mode
        standoff = self.cfg.standoff_radius_factor * r_min
        turn_cost = self.cfg.turn_penalty_factor * self.prims.horizontal_length * self.min_cost

        def docking(pose: Pose) -> float:
            """Tie-break key (rule 55), ``cone`` mode by default.

            Let ``h_rem = Δz / g_max`` be the horizontal travel still required
            by the remaining descent and ``L_dock = d_h + R·|ψ|`` the horizontal
            length of an aligned approach (distance plus the minimum-radius arc
            needed to face the target).

            * descent regime (``h_rem > standoff``): ``|d_h − standoff|`` — spiral
              on a standoff ring around the access point, not toward it (the
              orebody leans over the target at higher elevations);
            * docking regime (``h_rem ≤ standoff``): ``|L_dock − h_rem|`` — sit on
              the approach cone where a max-grade aligned run lands exactly on
              the target; flat primitives close the gap, max-grade keeps it.
            """
            d = horiz(pose)
            if mode == "horizontal":
                return d
            l_dock = dubins_cs_length(pose, tgt[:2], r_min)
            if mode == "docking":
                return l_dock
            h_rem = max(0.0, pose.z - float(tgt[2])) / gmax
            if h_rem > standoff:
                return abs(d - standoff)
            return abs(l_dock - h_rem)

        eps = self.cfg.heuristic_weight
        diag.heuristic_weight = eps

        def priority(node: _Node) -> tuple[float, float, float, int]:
            f = node.f(eps)
            b = math.floor(f / bucket) if bucket > 0 else f
            return (b, docking(node.pose), f, 0)

        counter = 0
        root = _Node(start, 0.0, h_of(start), cover_established, None, None, 0)
        diag.admissible_bound = root.h
        open_heap: list[tuple[tuple[float, float, float, int], int, _Node]] = []
        heapq.heappush(open_heap, (priority(root), counter, root))
        # Cell dominance is decided on f = g + ε·h, not g alone: with a 1 m z bin
        # and 0.85 m max-grade steps, a flat child and a descending child of the
        # same parent alias to one cell; their g differs by < 1 % while their h
        # differs by ~Δz/g_max. Comparing g would silently drop every descent.
        best_f: dict[tuple[int, int, int, int, bool], float] = {
            self.key(start, cover_established): root.f(eps)
        }
        expanded: set[tuple[int, int, int, int, bool]] = set()

        def finish(
            status: SegmentStatus,
            node: _Node | None,
            goal: list[Primitive] | None,
            gcost: float,
            cover_after: bool,
        ) -> SegmentResult:
            diag.closed_states = len(expanded)
            diag.elapsed_ms = (time.perf_counter() - t0) * 1000.0
            diag.termination = status.value
            if node is None or goal is None:
                return SegmentResult(status, None, math.inf, diag, None, cover_established)
            prims: list[Primitive] = []
            cur: _Node | None = node
            while cur is not None and cur.primitive is not None:
                prims.append(cur.primitive)
                cur = cur.parent
            prims.reverse()
            prims.extend(goal)
            path = SegmentPath(prims, start, goal[-1].end)
            return SegmentResult(status, path, node.g + gcost, diag, goal[-1].end, cover_after)

        while open_heap:
            diag.peak_open_size = max(diag.peak_open_size, len(open_heap))
            _, _, node = heapq.heappop(open_heap)
            k = self.key(node.pose, node.cover)
            if node.f(eps) > best_f.get(k, math.inf) + 1e-9:
                continue  # stale: a better node for this cell was pushed later
            if deadline is not None and time.perf_counter() > deadline:
                return finish(SegmentStatus.TIME_LIMIT, None, None, math.inf, False)
            if diag.expanded_states >= self.cfg.max_expansions_per_candidate:
                return finish(SegmentStatus.EXPANSION_LIMIT, None, None, math.inf, False)
            if k in expanded:
                continue  # already expanded with the best f for this cell
            expanded.add(k)

            # goal shot (rule 51)
            if horiz(node.pose) <= goal_radius:
                diag.goal_shot_attempts += 1
                shot, reason = self.prims.goal_shot(node.pose, tgt, max_dtheta)
                if shot is None:
                    diag.goal_shot_failures[reason] = diag.goal_shot_failures.get(reason, 0) + 1
                else:
                    evals = self.evaluate_primitives(shot, node.cover)
                    if any(e is None for e in evals):
                        diag.goal_shot_failures["INFEASIBLE_SAMPLES"] = (
                            diag.goal_shot_failures.get("INFEASIBLE_SAMPLES", 0) + 1
                        )
                    else:
                        total = 0.0
                        cover_after = node.cover
                        for e in evals:
                            assert e is not None
                            total += e[0]
                            cover_after = e[1]
                        return finish(SegmentStatus.SUCCESS, node, shot, total, cover_after)

            # overshoot prune
            if node.pose.z < z_floor:
                diag.pruned_overshoot += 1
                continue

            diag.expanded_states += 1
            approach = horiz(node.pose) + abs(node.pose.z - float(tgt[2])) / gmax
            if approach < diag.best_approach_horizontal + abs(diag.best_approach_dz) / gmax:
                diag.best_approach_horizontal = horiz(node.pose)
                diag.best_approach_dz = node.pose.z - float(tgt[2])
                diag.best_approach_depth = node.depth
                self._best_node = node
            prims = self.prims.expand(node.pose)
            results = self.evaluate_primitives(prims, node.cover)
            for prim, res in zip(prims, results, strict=True):
                if res is None:
                    diag.rejected_primitives += 1
                    continue
                if prim.end.z < z_floor:
                    diag.pruned_overshoot += 1
                    continue
                cost, est = res
                if prim.steering is not Steering.STRAIGHT:
                    cost += turn_cost  # curvature penalty (SRS §14); non-negative, h unaffected
                g = node.g + cost
                child = _Node(prim.end, g, h_of(prim.end), est, node, prim, node.depth + 1)
                ck = self.key(prim.end, est)
                cf = child.f(eps)
                if cf >= best_f.get(ck, math.inf) - 1e-9:
                    continue
                best_f[ck] = cf
                if ck in expanded:
                    expanded.discard(ck)  # reopen with a strictly better f
                counter += 1
                diag.generated_states += 1
                heapq.heappush(open_heap, (priority(child), counter, child))

        return finish(SegmentStatus.INFEASIBLE, None, None, math.inf, False)
