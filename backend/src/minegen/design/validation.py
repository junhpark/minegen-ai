"""Shared per-sample design validation (CLAUDE.md rules 50, 52, 62).

Phase 04 (Hybrid-A* primitive evaluation) and Phase 05 (smoothed-curve
revalidation) must apply identical semantics, in particular the portal
cover transition: before ``minimum_surface_cover`` is first achieved,
``INSUFFICIENT_COVER`` is forgiven; from the first sample that achieves it,
never again. ``ABOVE_TERRAIN`` (and every other reason) always rejects.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from minegen.design.constraints import RejectionReason
from minegen.design.cost_field import CostEvaluation, DesignCostEvaluator

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]


@dataclass
class SampleValidation:
    ok: bool
    cover_established: bool
    first_invalid_index: int  # -1 when ok
    invalid_count: int = 0
    rejection_reason_counts: dict[str, int] = field(default_factory=dict)


def validate_samples(
    evaluation: CostEvaluation,
    cover: FloatArray,
    *,
    cover_established: bool,
    minimum_cover: float,
    stop_at_first: bool = True,
) -> SampleValidation:
    """Walk samples in order applying the rule 52 cover transition.

    ``cover`` is ``surface_elevation − z`` per sample. With
    ``stop_at_first=True`` (the Phase 04 search hot path) the walk stops at
    the first rejected sample; Phase 05 revalidation passes ``False`` to
    count every invalid sample and every reason for the report.
    """
    valid = evaluation.valid
    reasons = evaluation.rejection_reasons
    n = valid.shape[0]
    established = cover_established
    transition_possible = minimum_cover > 0.0 and not cover_established
    first_invalid = -1
    invalid_count = 0
    counts: dict[str, int] = {}
    for i in range(n):
        rejected = False
        if not valid[i] and (
            not transition_possible
            or established
            or any(r is not RejectionReason.INSUFFICIENT_COVER for r in reasons[i])
        ):
            rejected = True
        if rejected:
            invalid_count += 1
            if first_invalid < 0:
                first_invalid = i
            for r in reasons[i]:
                counts[r.value] = counts.get(r.value, 0) + 1
            if stop_at_first:
                return SampleValidation(False, established, first_invalid, invalid_count, counts)
        if transition_possible and not established and cover[i] >= minimum_cover:
            established = True
    return SampleValidation(first_invalid < 0, established, first_invalid, invalid_count, counts)


def accepted_mask(
    evaluation: CostEvaluation,
    cover: FloatArray,
    *,
    cover_established: bool,
    minimum_cover: float,
) -> tuple[BoolArray, bool]:
    """Per-sample accept/reject replaying the rule 52 transition in order.
    Returns ``(mask, cover_established_after)``. ``validate_samples`` and this
    helper agree by construction (same walk)."""
    valid = evaluation.valid
    reasons = evaluation.rejection_reasons
    n = valid.shape[0]
    established = cover_established
    transition_possible = minimum_cover > 0.0 and not cover_established
    mask = np.ones(n, dtype=bool)
    for i in range(n):
        if not valid[i] and (
            not transition_possible
            or established
            or any(r is not RejectionReason.INSUFFICIENT_COVER for r in reasons[i])
        ):
            mask[i] = False
        if transition_possible and not established and cover[i] >= minimum_cover:
            established = True
    return mask, established


def evaluate_and_validate(
    evaluator: DesignCostEvaluator,
    points: FloatArray,
    *,
    cover_established: bool,
    stop_at_first: bool = False,
) -> tuple[CostEvaluation, SampleValidation, FloatArray]:
    """One-call helper for Phase 05: evaluator pass + rule 52 walk.
    Returns ``(evaluation, validation, finite_field_cost_per_m)``."""
    ev = evaluator.evaluate_points(points)
    surface = evaluator.surface_elevation(points)
    cover = surface - points[:, 2]
    validation = validate_samples(
        ev,
        cover,
        cover_established=cover_established,
        minimum_cover=evaluator.context.minimum_surface_cover,
        stop_at_first=stop_at_first,
    )
    finite_cost = ev.base_cost + ev.rock_penalty + ev.fault_penalty + ev.orebody_penalty
    return ev, validation, finite_cost
