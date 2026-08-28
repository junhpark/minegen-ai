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

from minegen.core.models import DeclineSearchConfig, RampConstraints, TunnelProfile
from minegen.design.cost_field import CostEvaluation, DesignCostEvaluator
from minegen.design.motion_primitives import (
    Pose,
    Primitive,
    PrimitiveSet,
    Steering,
    dubins_cs_length,
)
from minegen.design.profile import boundary_points, build_profile
from minegen.design.validation import validate_samples

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
    burial_established_at_end: bool = False

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
    burial: bool  # rule 66 profile-burial state (portal roof transition)
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
        tunnel_profile: TunnelProfile | None = None,
    ) -> None:
        self.ev = evaluator
        self.ramp = ramp
        self.cfg = cfg
        # excavation-envelope feasibility contract (rule 66): every primitive
        # sample sweeps the ACTUAL tunnel profile boundary with the
        # heading/grade gravity-aligned frame — the same shared geometry the
        # Phase 06 mesh excavates. Always on; the default profile applies
        # when none is given.
        self.envelope_shape = build_profile(ramp, tunnel_profile or TunnelProfile())
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

    def key(self, pose: Pose, cover: bool, burial: bool) -> tuple[int, int, int, int, bool, bool]:
        ih = round(pose.heading / self.heading_step) % self.cfg.heading_bins
        return (
            math.floor(pose.x / self.cfg.xy_resolution),
            math.floor(pose.y / self.cfg.xy_resolution),
            math.floor(pose.z / self.cfg.z_resolution),
            ih,
            cover,
            burial,
        )

    def start_burial_established(self, pose: Pose) -> bool:
        """Initial rule-66 burial state for a search: True iff the start
        ring's full profile is already below the terrain (deep level starts);
        False at the portal, where the roof legitimately daylights until the
        profile first buries."""
        t = np.array([[math.sin(pose.heading), math.cos(pose.heading), 0.0]])
        ring = boundary_points(pose.position[None, :], t, self.envelope_shape).reshape(-1, 3)
        _, above = self.ev.envelope_masks(ring)
        return not bool(above.any())

    # -- primitive evaluation (rules 50, 52) ------------------------------- #

    def evaluate_primitives(
        self, prims: list[Primitive], cover_established: bool, burial_established: bool
    ) -> list[tuple[float, bool, bool] | None]:
        """For each primitive:
        ``(integrated cost, cover_established_after, burial_established_after)``
        or ``None`` if any sample is infeasible. One batched evaluator call
        for the centerline plus one batched excavation-envelope mask call for
        the swept tunnel-profile boundary (rule 66): a primitive whose
        centerline is valid but whose wall or roof would clip a hard
        exclusion is rejected here, not first discovered by the Phase 06
        gate. Above-terrain envelope points follow the rule-66 profile-burial
        transition: allowed until the full ring first buries, breakthrough
        afterwards rejects the primitive."""
        all_pts = np.vstack([p.samples for p in prims])
        ev = self.ev.evaluate_points(all_pts)
        surface = self.ev.surface_elevation(all_pts)
        # per-sample unit tangents: every primitive is a constant-curvature,
        # constant-grade arc, so heading is affine in horizontal arc length:
        # θ(s) = θ_end − curvature·(Lh − s)
        tangent_rows = []
        for p in prims:
            inv = 1.0 / math.sqrt(1.0 + p.grade * p.grade)
            s_h = p.sample_arc * inv
            theta = p.end.heading - p.curvature * (p.horizontal_length - s_h)
            tangent_rows.append(
                np.column_stack(
                    [np.sin(theta) * inv, np.cos(theta) * inv, np.full_like(theta, p.grade * inv)]
                )
            )
        boundary = boundary_points(all_pts, np.vstack(tangent_rows), self.envelope_shape)
        k = self.envelope_shape.k
        env_hard, env_above = self.ev.envelope_masks(boundary.reshape(-1, 3))
        env_hard_any = env_hard.reshape(-1, k).any(axis=1)
        env_above_any = env_above.reshape(-1, k).any(axis=1)
        finite_cost = ev.base_cost + ev.rock_penalty + ev.fault_penalty + ev.orebody_penalty
        out: list[tuple[float, bool, bool] | None] = []
        offset = 0
        transition_possible = self.min_cover > 0.0 and not cover_established
        for p in prims:
            n = p.samples.shape[0]
            sl = slice(offset, offset + n)
            offset += n
            if env_hard_any[sl].any():
                out.append(None)
                continue
            # rule 66 burial walk along the primitive's rings
            above_rows = env_above_any[sl]
            if burial_established:
                if above_rows.any():
                    out.append(None)
                    continue
                burial_after = True
            else:
                buried_rows = ~above_rows
                if buried_rows.any():
                    first = int(np.argmax(buried_rows))
                    if above_rows[first:].any():
                        out.append(None)  # breakthrough after burial
                        continue
                    burial_after = True
                else:
                    burial_after = False
            if not transition_possible:
                # fast path: no forgiveness possible, a single all() decides
                if not ev.valid[sl].all():
                    out.append(None)
                    continue
                established = cover_established
            else:
                sub = CostEvaluation(
                    points=p.samples,
                    valid=ev.valid[sl],
                    total_cost_per_m=ev.total_cost_per_m[sl],
                    base_cost=ev.base_cost[sl],
                    rock_penalty=ev.rock_penalty[sl],
                    fault_penalty=ev.fault_penalty[sl],
                    orebody_penalty=ev.orebody_penalty[sl],
                    rock_quality=ev.rock_quality[sl],
                    nearest_fault_distance=ev.nearest_fault_distance[sl],
                    orebody_distance=ev.orebody_distance[sl],
                    rejection_reasons=ev.rejection_reasons[sl],
                )
                res = validate_samples(
                    sub,
                    surface[sl] - p.samples[:, 2],
                    cover_established=cover_established,
                    minimum_cover=self.min_cover,
                    stop_at_first=True,
                )
                if not res.ok:
                    out.append(None)
                    continue
                established = res.cover_established
            c = finite_cost[sl]
            cost = float(np.dot(0.5 * (c[1:] + c[:-1]), np.diff(p.sample_arc)))
            out.append((cost, established, burial_after))
        return out

    # -- search ------------------------------------------------------------ #

    def search(
        self,
        start: Pose,
        target: FloatArray,
        *,
        cover_established: bool = True,
        burial_established: bool | None = None,
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
        burial0 = (
            burial_established
            if burial_established is not None
            else self.start_burial_established(start)
        )
        root = _Node(start, 0.0, h_of(start), cover_established, burial0, None, None, 0)
        diag.admissible_bound = root.h
        open_heap: list[tuple[tuple[float, float, float, int], int, _Node]] = []
        heapq.heappush(open_heap, (priority(root), counter, root))
        # Cell dominance is decided on f = g + ε·h, not g alone: with a 1 m z bin
        # and 0.85 m max-grade steps, a flat child and a descending child of the
        # same parent alias to one cell; their g differs by < 1 % while their h
        # differs by ~Δz/g_max. Comparing g would silently drop every descent.
        best_f: dict[tuple[int, int, int, int, bool, bool], float] = {
            self.key(start, cover_established, burial0): root.f(eps)
        }
        expanded: set[tuple[int, int, int, int, bool, bool]] = set()

        def finish(
            status: SegmentStatus,
            node: _Node | None,
            goal: list[Primitive] | None,
            gcost: float,
            cover_after: bool,
            burial_after: bool,
        ) -> SegmentResult:
            diag.closed_states = len(expanded)
            diag.elapsed_ms = (time.perf_counter() - t0) * 1000.0
            diag.termination = status.value
            if node is None or goal is None:
                return SegmentResult(status, None, math.inf, diag, None, cover_established, burial0)
            prims: list[Primitive] = []
            cur: _Node | None = node
            while cur is not None and cur.primitive is not None:
                prims.append(cur.primitive)
                cur = cur.parent
            prims.reverse()
            prims.extend(goal)
            path = SegmentPath(prims, start, goal[-1].end)
            return SegmentResult(
                status, path, node.g + gcost, diag, goal[-1].end, cover_after, burial_after
            )

        while open_heap:
            diag.peak_open_size = max(diag.peak_open_size, len(open_heap))
            _, _, node = heapq.heappop(open_heap)
            k = self.key(node.pose, node.cover, node.burial)
            if node.f(eps) > best_f.get(k, math.inf) + 1e-9:
                continue  # stale: a better node for this cell was pushed later
            if deadline is not None and time.perf_counter() > deadline:
                return finish(SegmentStatus.TIME_LIMIT, None, None, math.inf, False, False)
            if diag.expanded_states >= self.cfg.max_expansions_per_candidate:
                return finish(SegmentStatus.EXPANSION_LIMIT, None, None, math.inf, False, False)
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
                    evals = self.evaluate_primitives(shot, node.cover, node.burial)
                    if any(e is None for e in evals):
                        diag.goal_shot_failures["INFEASIBLE_SAMPLES"] = (
                            diag.goal_shot_failures.get("INFEASIBLE_SAMPLES", 0) + 1
                        )
                    else:
                        total = 0.0
                        cover_after = node.cover
                        burial_after = node.burial
                        for e in evals:
                            assert e is not None
                            total += e[0]
                            cover_after = e[1]
                            burial_after = e[2]
                        return finish(
                            SegmentStatus.SUCCESS, node, shot, total, cover_after, burial_after
                        )

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
            results = self.evaluate_primitives(prims, node.cover, node.burial)
            for prim, res in zip(prims, results, strict=True):
                if res is None:
                    diag.rejected_primitives += 1
                    continue
                if prim.end.z < z_floor:
                    diag.pruned_overshoot += 1
                    continue
                cost, est, burial_est = res
                if prim.steering is not Steering.STRAIGHT:
                    cost += turn_cost  # curvature penalty (SRS §14); non-negative, h unaffected
                g = node.g + cost
                child = _Node(
                    prim.end, g, h_of(prim.end), est, burial_est, node, prim, node.depth + 1
                )
                ck = self.key(prim.end, est, burial_est)
                cf = child.f(eps)
                if cf >= best_f.get(ck, math.inf) - 1e-9:
                    continue
                best_f[ck] = cf
                if ck in expanded:
                    expanded.discard(ck)  # reopen with a strictly better f
                counter += 1
                diag.generated_states += 1
                heapq.heappush(open_heap, (priority(child), counter, child))

        return finish(SegmentStatus.INFEASIBLE, None, None, math.inf, False, False)
