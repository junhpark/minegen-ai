"""Continuous design cost evaluator (CLAUDE.md rules 41–42).

``DesignCostEvaluator.evaluate_points(points)`` returns, for each point:

    valid                  all hard constraints satisfied
    total_cost_per_m       base + rock + fault + orebody penalties (+inf if invalid)
    base_cost, rock_penalty, fault_penalty, orebody_penalty
    rock_quality           batch trilinear sample of the rock-quality spatial field
    nearest_fault_distance |signed distance| to the nearest analytic fault plane
    orebody_distance       analytic signed distance to the orebody (negative inside)
    rejection_reasons      list[RejectionReason] per point

No dense volume is built. Phase 04 samples motion primitives through this
evaluator and integrates cost per metre along them.

Interpretation (engineering, not geology — rule 42):

    rock_penalty    = w_rock · (100 − rq) / 100
    fault_penalty   = Σ_f  core_penalty_f                       if |d_f| ≤ core_f
                         damage_penalty_f · (infl_f − |d_f|) / (infl_f − core_f)
                                                               if core_f < |d_f| ≤ infl_f
    orebody_penalty = w_ster · max(0, 1 − (sdf − buffer) / range)   (outside buffer)

Hard rejections: outside the field-lattice extent, above terrain (or cover
< min), inside orebody, within the exclusion buffer, inside a restricted zone.

Rock quality comes ONLY from ``world.fields.rock_quality.sample`` (rule 128):
the evaluator knows nothing about lattice cells, rock types or ore membership
of cells — the field's terrain boundary policy (COLUMN_TOP_FILL) is what
keeps near-surface interpolation sound.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.core.models import DesignConfig
from minegen.design.constraints import DesignContext, RejectionReason, in_restricted_zone
from minegen.world.geology import FaultPlane
from minegen.world.orebody import AnalyticOrebody, ImplicitOrebody, Orebody
from minegen.world.synthetic_world import SyntheticWorld
from minegen.world.terrain import Terrain

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]


@dataclass
class CostEvaluation:
    points: FloatArray
    valid: BoolArray
    total_cost_per_m: FloatArray
    base_cost: FloatArray
    rock_penalty: FloatArray
    fault_penalty: FloatArray
    orebody_penalty: FloatArray
    rock_quality: FloatArray
    nearest_fault_distance: FloatArray
    orebody_distance: FloatArray
    rejection_reasons: list[list[RejectionReason]]

    def __len__(self) -> int:
        return int(self.points.shape[0])

    def to_payload(self) -> list[dict[str, Any]]:
        """Finite-only wire form (rule 34): non-finite costs become ``None``."""

        def f(v: float) -> float | None:
            return float(v) if np.isfinite(v) else None

        out: list[dict[str, Any]] = []
        for i in range(len(self)):
            out.append(
                {
                    "point": [float(c) for c in self.points[i]],
                    "valid": bool(self.valid[i]),
                    "totalCostPerM": f(self.total_cost_per_m[i]),
                    "baseCost": f(self.base_cost[i]),
                    "rockPenalty": f(self.rock_penalty[i]),
                    "faultPenalty": f(self.fault_penalty[i]),
                    "orebodyPenalty": f(self.orebody_penalty[i]),
                    "rockQuality": f(self.rock_quality[i]),
                    "nearestFaultDistance": f(self.nearest_fault_distance[i]),
                    "orebodyDistance": f(self.orebody_distance[i]),
                    "rejectionReasons": [r.value for r in self.rejection_reasons[i]],
                }
            )
        return out


class ExactDistanceRequiredError(TypeError):
    """The legacy design evaluator applies HARD orebody exclusion buffers
    from the orebody signed distance, so it accepts only bodies with the
    EXACT_METRIC_SDF contract (rule 135). An implicit body's approximate
    clearance must never silently weaken that contract."""


# --------------------------------------------------------------------------- #
# Orebody clearance policies (Phase 20A)
# --------------------------------------------------------------------------- #

#: multiple of the derived-geometry lattice diagonal used as the conservative
#: error bound of the Phase 19 approximate clearance (see
#: ``ConservativeClearance`` for the derivation)
CONSERVATIVE_CLEARANCE_DIAGONAL_FACTOR = 1.5


@dataclass(frozen=True)
class ExactClearance:
    """EXACT basis: the analytic body's Euclidean signed distance. This is
    exactly what the legacy evaluator always used; it is the default policy
    and its numbers are unchanged."""

    orebody: AnalyticOrebody
    basis: str = "EXACT"
    error_bound: float = 0.0

    def signed_clearance(self, points: FloatArray) -> FloatArray:
        return self.orebody.signed_distance(points)


@dataclass(frozen=True)
class ConservativeClearance:
    """CONSERVATIVE basis for implicit bodies (Phase 20A, rule 146):

        safe_clearance = approximate_clearance − error_bound

    with ``error_bound = CONSERVATIVE_CLEARANCE_DIAGONAL_FACTOR × ‖lattice
    spacing‖``. Derivation: the Phase 19 clearance is a signed Euclidean
    distance transform between lattice CELL CENTERS classified by φ, queried
    by trilinear interpolation. (1) The classified boundary lies within one
    cell of the true φ = 0 surface, so the cell-to-cell distance differs from
    the true distance to the surface by at most one cell diagonal; (2) the
    distance field is 1-Lipschitz, so trilinear interpolation between
    centers adds at most half a diagonal. The factor 1.5 covers both terms.
    Slivers thinner than the across-thickness spacing are the only feature
    the lattice cannot see; the Phase 19 lattice keeps ≥ 3 cells across the
    guaranteed interior thickness floor, so only the vanishing taper rim
    (< 1 m wide in plan) is affected, well inside one in-plane cell. The
    bound is exercised empirically in ``tests/test_layout_v2.py`` against
    the dense mesh surface. Subtracting the bound only ever makes a point
    LESS clear, so no accepted design can rely on optimistic distance."""

    orebody: ImplicitOrebody
    error_bound: float
    basis: str = "CONSERVATIVE"

    @classmethod
    def for_orebody(cls, orebody: ImplicitOrebody) -> ConservativeClearance:
        spacing = np.asarray(orebody.clearance_info()["latticeSpacing"], dtype=np.float64)
        bound = CONSERVATIVE_CLEARANCE_DIAGONAL_FACTOR * float(np.linalg.norm(spacing))
        return cls(orebody=orebody, error_bound=bound)

    def signed_clearance(self, points: FloatArray) -> FloatArray:
        return np.asarray(self.orebody.approximate_clearance(points) - self.error_bound)


ClearancePolicy = ExactClearance | ConservativeClearance


def clearance_policy_for(orebody: Orebody) -> ClearancePolicy:
    """Layout-v2 policy selection (rule 146): exact for analytic bodies,
    conservative bounded clearance for implicit ones. The LEGACY evaluator
    never calls this — it still requires an analytic body."""
    if isinstance(orebody, AnalyticOrebody):
        return ExactClearance(orebody)
    if isinstance(orebody, ImplicitOrebody):
        return ConservativeClearance.for_orebody(orebody)
    raise ExactDistanceRequiredError(
        f"orebody type {orebody.config.orebody_type.value} has no clearance policy"
    )


class DesignCostEvaluator:
    def __init__(
        self,
        world: SyntheticWorld,
        cfg: DesignConfig,
        context: DesignContext | None = None,
        clearance: ClearancePolicy | None = None,
    ) -> None:
        self.world = world
        self.cfg = cfg
        self.context = context or DesignContext.decline(cfg)
        # Legacy contract (rule 135): with no explicit policy the evaluator
        # takes the analytic body's EXACT signed distance and refuses every
        # other body. Only layout-v2 passes an explicit policy; the exact
        # path is numerically identical to the pre-Phase-20A evaluator.
        if clearance is None:
            if not isinstance(world.orebody, AnalyticOrebody):
                raise ExactDistanceRequiredError(
                    f"orebody type {world.orebody.config.orebody_type.value} has distance "
                    f"contract {world.orebody.distance_contract.value}; the legacy design "
                    "evaluator requires EXACT_METRIC_SDF"
                )
            clearance = ExactClearance(world.orebody)
        self.clearance: ClearancePolicy = clearance
        self.orebody: Orebody = world.orebody
        self.terrain: Terrain = world.terrain
        self.faults: list[FaultPlane] = world.faults

        # the modelled volume is the field-lattice extent (rule 127: a
        # numerical sampling extent, not a block-model volume)
        grid = world.fields.grid
        self.grid_min = np.asarray(grid.origin, dtype=np.float64)
        self.grid_max = np.asarray(grid.max_corner, dtype=np.float64)
        self._rock_quality_field = world.fields.rock_quality

    # -- component queries ------------------------------------------------- #

    def rock_quality(self, points: FloatArray) -> FloatArray:
        """Batch rock quality from the spatial field (rule 128). Coordinates
        are clamped to the field's center lattice by the field itself (no
        extrapolation); validity of the point is decided separately by
        ``world_valid``."""
        return self._rock_quality_field.sample(np.asarray(points, dtype=np.float64))

    def fault_penalty(self, points: FloatArray) -> tuple[FloatArray, FloatArray]:
        """(summed penalty, |distance| to nearest fault). Analytic per plane."""
        p = np.asarray(points, dtype=np.float64)
        n = p.shape[0]
        penalty = np.zeros(n)
        nearest = np.full(n, np.inf)
        for f in self.faults:
            d = np.abs(f.signed_distance(p))
            c, w = f.config.core_half_width, f.config.influence_half_width
            core = d <= c
            damage = (d > c) & (d <= w)
            penalty += np.where(core, f.config.core_penalty, 0.0)
            if w > c:
                penalty += np.where(damage, f.config.damage_zone_penalty * (w - d) / (w - c), 0.0)
            nearest = np.minimum(nearest, d)
        return penalty, nearest

    def orebody_distance(self, points: FloatArray) -> FloatArray:
        """Signed clearance to the orebody under the evaluator's policy:
        exact SDF (legacy / analytic) or conservative bounded clearance
        (layout-v2 on implicit bodies). Negative inside."""
        return self.clearance.signed_clearance(points)

    def surface_elevation(self, points: FloatArray) -> FloatArray:
        return self.terrain.sample(np.asarray(points, dtype=np.float64)[:, :2])

    def world_valid(self, points: FloatArray) -> BoolArray:
        p = np.asarray(points, dtype=np.float64)
        return np.all((p >= self.grid_min) & (p <= self.grid_max), axis=-1)

    # -- excavation-envelope masks (rule 66, Phase 04 feasibility) ---------- #

    def envelope_masks(self, points: FloatArray) -> tuple[BoolArray, BoolArray]:
        """Lean boolean masks for excavation-ENVELOPE points (tunnel profile
        boundary, not the centerline): ``(hard_invalid, above_terrain_like)``.

        ``hard_invalid``: outside the world in XY or below its bottom, inside
        the orebody, inside the orebody exclusion buffer, or inside a
        restricted zone — always fatal for the envelope.
        ``above_terrain_like``: above the terrain surface OR above the world
        TOP (the portal-roof case) — fatal only once surface cover is
        established (rule 52 at search time; the exact profile-burial
        transition is re-checked by the Phase 06 gate, rule 66).
        ``minimum_surface_cover`` is a centerline constraint and is NOT
        applied to envelope points. No per-point reason lists are built:
        this runs inside the Hybrid-A* hot loop."""
        p = np.atleast_2d(np.asarray(points, dtype=np.float64))
        xy_bottom_out = ~(
            np.all((p[:, :2] >= self.grid_min[:2]) & (p[:, :2] <= self.grid_max[:2]), axis=1)
            & (p[:, 2] >= self.grid_min[2])
        )
        above_top = p[:, 2] > self.grid_max[2]
        surface = self.surface_elevation(p)
        above_terrain_like = (p[:, 2] > surface) | above_top
        hard = xy_bottom_out.copy()
        if not self.context.allow_inside_orebody:
            sdf = self.orebody_distance(p)
            hard |= sdf < self.context.orebody_exclusion_buffer
        if self.context.restricted_zones:
            hard |= in_restricted_zone(p, self.context.restricted_zones)
        return hard, above_terrain_like

    # -- full evaluation --------------------------------------------------- #

    def evaluate_points(self, points: FloatArray) -> CostEvaluation:
        p = np.atleast_2d(np.asarray(points, dtype=np.float64))
        if p.shape[-1] != 3:
            raise ValueError("points must have shape (N, 3)")
        n = p.shape[0]
        reasons: list[list[RejectionReason]] = [[] for _ in range(n)]

        def reject(mask: BoolArray, reason: RejectionReason) -> None:
            for i in np.nonzero(mask)[0]:
                reasons[int(i)].append(reason)

        valid = self.world_valid(p)
        reject(~valid, RejectionReason.OUTSIDE_WORLD)

        surface = self.surface_elevation(p)
        above = p[:, 2] > surface
        reject(above, RejectionReason.ABOVE_TERRAIN)
        cover = self.context.minimum_surface_cover
        if cover > 0:
            thin = (~above) & (surface - p[:, 2] < cover)
            reject(thin, RejectionReason.INSUFFICIENT_COVER)
            valid &= ~thin
        valid &= ~above

        sdf = self.orebody_distance(p)
        if not self.context.allow_inside_orebody:
            inside = sdf <= 0.0
            reject(inside, RejectionReason.INSIDE_OREBODY)
            valid &= ~inside
            buf = self.context.orebody_exclusion_buffer
            if buf > 0:
                near = (sdf > 0.0) & (sdf < buf)
                reject(near, RejectionReason.OREBODY_BUFFER)
                valid &= ~near

        if self.context.restricted_zones:
            hit = in_restricted_zone(p, self.context.restricted_zones)
            reject(hit, RejectionReason.RESTRICTED_ZONE)
            valid &= ~hit

        rq = self.rock_quality(p)
        rock_pen = self.cfg.rock_penalty_weight * np.clip((100.0 - rq) / 100.0, 0.0, 1.0)
        fault_pen, nearest = self.fault_penalty(p)
        buf = self.context.orebody_exclusion_buffer
        ster = self.cfg.orebody_sterilization_weight * np.clip(
            1.0 - (sdf - buf) / self.cfg.orebody_sterilization_range, 0.0, 1.0
        )
        base = np.full(n, self.cfg.base_cost_per_m)
        total = base + rock_pen + fault_pen + ster
        total = np.where(valid, total, np.inf)

        return CostEvaluation(
            points=p,
            valid=valid,
            total_cost_per_m=total,
            base_cost=base,
            rock_penalty=rock_pen,
            fault_penalty=fault_pen,
            orebody_penalty=ster,
            rock_quality=rq,
            nearest_fault_distance=nearest,
            orebody_distance=sdf,
            rejection_reasons=reasons,
        )

    @property
    def minimum_cost_per_m(self) -> float:
        """Lower bound on cost per metre anywhere (base cost only), for use as
        the admissible heuristic multiplier (rule 25)."""
        return float(self.cfg.base_cost_per_m)
