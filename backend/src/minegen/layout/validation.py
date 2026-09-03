"""Detailed engineering validation of a delivered layout-v2 centerline
(Phase 20A, directive §18/§21).

Reuses the shared design infrastructure unchanged: the ``DesignCostEvaluator``
(terrain, minimum cover with the rule 52 portal transition, restricted
zones, world extent, orebody clearance under the evaluator's clearance
policy) through the same ``evaluate_and_validate`` walk Phase 05 uses. No
constraint is re-implemented here and no hard failure is ever converted
into a score term.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.design.cost_field import DesignCostEvaluator
from minegen.design.validation import accepted_mask, evaluate_and_validate

FloatArray = npt.NDArray[np.float64]


@dataclass
class DeliveredValidation:
    sample_count: int
    invalid_count: int
    rejection_counts: dict[str, int]
    cover_established: bool
    field_cost: float  # ∫ finite cost/m ds over the whole centerline
    orebody_distance: FloatArray  # per sample, under the evaluator's policy
    valid_mask: npt.NDArray[np.bool_]
    points: FloatArray
    minimum_cover: float
    extra: dict[str, Any] = field(default_factory=dict)

    def point_valid(self, point: FloatArray) -> bool:
        """Is this exact point an accepted sample of the walk? Matches by
        position (connection points are inserted vertices of the same
        polyline, so they coincide with a sample or lie on an accepted
        edge — the edge test is the mean of its endpoints)."""
        d = np.linalg.norm(self.points - np.asarray(point, dtype=np.float64)[None, :], axis=1)
        i = int(np.argmin(d))
        if d[i] < 1e-6:
            return bool(self.valid_mask[i])
        # between two samples: the nearest and its closer neighbour must both
        # be accepted
        nxt = min(i + 1, self.points.shape[0] - 1)
        prv = max(i - 1, 0)
        j = nxt if d[nxt] < d[prv] else prv
        return bool(self.valid_mask[i] and self.valid_mask[j])

    def to_dict(self) -> dict[str, Any]:
        return {
            "sampleCount": self.sample_count,
            "invalidSampleCount": self.invalid_count,
            "rejectionReasonCounts": dict(self.rejection_counts),
            "coverEstablished": self.cover_established,
            "fieldCost": self.field_cost,
            "minimumOrebodyDistance": float(np.min(self.orebody_distance)),
            "minimumCover": self.minimum_cover,
        }


def validate_delivered_centerline(
    evaluator: DesignCostEvaluator, points: FloatArray
) -> DeliveredValidation:
    pts = np.asarray(points, dtype=np.float64)
    ev, validation, finite = evaluate_and_validate(
        evaluator, pts, cover_established=False, stop_at_first=False
    )
    # per-sample acceptance replaying the rule 52 walk (portal transition)
    surface = evaluator.surface_elevation(pts)
    cover = surface - pts[:, 2]
    mask, _ = accepted_mask(
        ev,
        cover,
        cover_established=False,
        minimum_cover=evaluator.context.minimum_surface_cover,
    )
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    mid = 0.5 * (finite[:-1] + finite[1:])
    return DeliveredValidation(
        sample_count=int(pts.shape[0]),
        invalid_count=validation.invalid_count,
        rejection_counts=dict(validation.rejection_reason_counts),
        cover_established=validation.cover_established,
        field_cost=float(np.sum(mid * seg)),
        orebody_distance=np.asarray(ev.orebody_distance, dtype=np.float64),
        valid_mask=np.asarray(mask, dtype=np.bool_),
        points=pts,
        minimum_cover=float(np.min(cover)),
    )
