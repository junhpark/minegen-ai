"""Planning IRR (hardening PR-2 H3 §8.2).

The internal rate of return of the Planning Cashflow under EXACTLY the
Baseline Planning NPV timing convention (rule 202, ``cashflow.py``): every
bucket's net cashflow sits at the bucket MIDPOINT, ``year = midDay / 365.25``,
and the IRR is the annual rate ``r`` with ``Σ net_i / (1 + r)^year_i = 0``.
Day / bucket based — never an Excel-style annual period.

Definition is TYPED, never NaN / Infinity (rule 34):

* ``DEFINED`` — the non-zero bucket net cashflows change sign EXACTLY once
  (the classical single-root condition); the root is found by deterministic
  bisection on the bounded bracket ``[IRR_MIN, IRR_MAX]``;
* ``NOT_DEFINED`` with ``NO_SIGN_CHANGE`` (all nets on one side of zero, or
  the NPV function keeps one sign over the whole bracket) or
  ``MULTIPLE_SIGN_CHANGES`` (two or more sign changes — several roots are
  possible, so no single rate is reported);
* ``NOT_CONFIGURED`` — no Planning Cashflow exists (economics not configured
  or a source unavailable).

It is "Planning IRR" — a planning comparator over synthetic assumptions,
never a bankable or feasibility figure.
"""

from __future__ import annotations

import math
from itertools import pairwise

from minegen.analysis.cashflow import DAYS_PER_YEAR
from minegen.analysis.models import (
    IRR_MAX,
    IRR_MIN,
    CashflowBucket,
    PlanningIrr,
    not_configured_irr,
)

__all__ = ["IRR_MAX", "IRR_MIN", "PlanningIrr", "not_configured_irr", "planning_irr"]

BISECTION_STEPS = 200
BISECTION_TOLERANCE = 1e-10


def _sign_changes(values: list[float]) -> int:
    signs = [1 if v > 0 else -1 for v in values if v != 0.0]
    return sum(1 for a, b in pairwise(signs) if a != b)


def npv_at(buckets: list[CashflowBucket], annual_rate: float) -> float:
    total = 0.0
    for b in buckets:
        mid = 0.5 * (b.start_day + b.end_day)
        total += b.net_cashflow / (1.0 + annual_rate) ** (mid / DAYS_PER_YEAR)
    return total


def planning_irr(buckets: list[CashflowBucket]) -> PlanningIrr:
    nets = [b.net_cashflow for b in buckets]
    changes = _sign_changes(nets)
    if changes == 0:
        return PlanningIrr(status="NOT_DEFINED", annual_rate=None, reason="NO_SIGN_CHANGE")
    if changes > 1:
        return PlanningIrr(status="NOT_DEFINED", annual_rate=None, reason="MULTIPLE_SIGN_CHANGES")
    lo, hi = IRR_MIN, IRR_MAX
    f_lo, f_hi = npv_at(buckets, lo), npv_at(buckets, hi)
    if not (math.isfinite(f_lo) and math.isfinite(f_hi)) or f_lo * f_hi > 0.0:
        # one cashflow sign change but no NPV root inside the bounded bracket
        return PlanningIrr(status="NOT_DEFINED", annual_rate=None, reason="NO_SIGN_CHANGE")
    if f_lo == 0.0:
        return PlanningIrr(status="DEFINED", annual_rate=lo, reason=None)
    if f_hi == 0.0:
        return PlanningIrr(status="DEFINED", annual_rate=hi, reason=None)
    for _ in range(BISECTION_STEPS):
        mid = 0.5 * (lo + hi)
        f_mid = npv_at(buckets, mid)
        if f_mid == 0.0 or hi - lo < BISECTION_TOLERANCE:
            lo = hi = mid
            break
        if (f_mid > 0.0) == (f_lo > 0.0):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    rate = 0.5 * (lo + hi)
    if not math.isfinite(rate):  # pragma: no cover - the bracket is finite
        return PlanningIrr(status="NOT_DEFINED", annual_rate=None, reason="NO_SIGN_CHANGE")
    return PlanningIrr(status="DEFINED", annual_rate=rate, reason=None)
