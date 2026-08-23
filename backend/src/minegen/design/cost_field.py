"""Continuous design cost evaluator (CLAUDE.md rules 41–42).

``DesignCostEvaluator.evaluate_points(points)`` returns, for each point:

    valid                  all hard constraints satisfied
    total_cost_per_m       base + rock + fault + orebody penalties (+inf if invalid)
    base_cost, rock_penalty, fault_penalty, orebody_penalty
    rock_quality           trilinear interpolation of the block field
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

Hard rejections: outside block-grid extent, above terrain (or cover < min),
inside orebody, within the exclusion buffer, inside a restricted zone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.core.models import DesignConfig
from minegen.design.constraints import DesignContext, RejectionReason, in_restricted_zone
from minegen.world.block_model import BlockModel, RockType
from minegen.world.geology import FaultPlane
from minegen.world.orebody import Orebody
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


def _rock_only_field(bm: BlockModel) -> FloatArray:
    """Rock-quality field with AIR blocks filled from the topmost rock block of
    their column, so near-surface interpolation is not pulled toward 0.
    Air is a column property (everything above an air block is air)."""
    rq = bm.rock_quality.astype(np.float64).copy()
    air = bm.rock_type == RockType.AIR
    for k in range(1, rq.shape[2]):  # bottom layer is never air
        rq[:, :, k] = np.where(air[:, :, k], rq[:, :, k - 1], rq[:, :, k])
    return rq


class DesignCostEvaluator:
    def __init__(
        self,
        world: SyntheticWorld,
        cfg: DesignConfig,
        context: DesignContext | None = None,
    ) -> None:
        self.world = world
        self.cfg = cfg
        self.context = context or DesignContext.decline(cfg)
        self.orebody: Orebody = world.orebody
        self.terrain: Terrain = world.terrain
        self.faults: list[FaultPlane] = world.faults

        grid = world.block_model.grid
        self.grid_min = np.asarray(grid.origin, dtype=np.float64)
        self.grid_max = np.asarray(grid.max_corner, dtype=np.float64)
        centers = [grid.axis_centers(a) for a in range(3)]
        self._center_lo = np.array([c[0] for c in centers])
        self._center_hi = np.array([c[-1] for c in centers])
        self._spacing = np.asarray(grid.spacing, dtype=np.float64)
        self._shape = np.asarray(grid.shape, dtype=np.intp)
        self._rq_field = _rock_only_field(world.block_model)

    # -- component queries ------------------------------------------------- #

    def rock_quality(self, points: FloatArray) -> FloatArray:
        """Trilinear rock quality. Coordinates are clamped to the block-center
        lattice (no extrapolation); validity of the point is decided
        separately by ``world_valid``."""
        p = np.clip(np.asarray(points, dtype=np.float64), self._center_lo, self._center_hi)
        f = (p - self._center_lo) / self._spacing  # fractional index in the center lattice
        f = np.minimum(f, self._shape - 1 - 1e-12)
        i0 = np.floor(f).astype(np.intp)
        t = f - i0
        i1 = np.minimum(i0 + 1, self._shape - 1)
        v = self._rq_field
        x0, y0, z0 = i0[:, 0], i0[:, 1], i0[:, 2]
        x1, y1, z1 = i1[:, 0], i1[:, 1], i1[:, 2]
        tx, ty, tz = t[:, 0], t[:, 1], t[:, 2]
        c00 = v[x0, y0, z0] * (1 - tx) + v[x1, y0, z0] * tx
        c10 = v[x0, y1, z0] * (1 - tx) + v[x1, y1, z0] * tx
        c01 = v[x0, y0, z1] * (1 - tx) + v[x1, y0, z1] * tx
        c11 = v[x0, y1, z1] * (1 - tx) + v[x1, y1, z1] * tx
        c0 = c00 * (1 - ty) + c10 * ty
        c1 = c01 * (1 - ty) + c11 * ty
        return np.asarray(c0 * (1 - tz) + c1 * tz, dtype=np.float64)

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
        return self.orebody.signed_distance(points)

    def surface_elevation(self, points: FloatArray) -> FloatArray:
        return self.terrain.sample(np.asarray(points, dtype=np.float64)[:, :2])

    def world_valid(self, points: FloatArray) -> BoolArray:
        p = np.asarray(points, dtype=np.float64)
        return np.all((p >= self.grid_min) & (p <= self.grid_max), axis=-1)

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
