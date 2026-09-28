"""Planning Cashflow and Baseline Planning NPV (Phase 22B §33–41).

Timing comes ONLY from the MineTimeline (start / end days of the matching
tasks); every quantity comes ONLY from geometry (edge lengths, production
tonnes, backfill volumes). An amount attached to a task interval is spread
linearly over that interval and allocated to fixed buckets of
``cashflowBucketDays`` by the overlap fraction; a zero-length interval lands
whole in the bucket containing its day. Initial capital sits in bucket 0;
fixed operating cost is linear over ``[0, endDay]``.

Discounting convention (fixed here and in the tests): each bucket's net
cashflow is discounted at the bucket MIDPOINT, ``year = midDay / 365.25``,
``discounted = net / (1 + annualRate)^year``; NPV = Σ discounted. With a zero
rate NPV equals the undiscounted net cashflow exactly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from minegen.analysis.models import CashflowBucket

__all__ = ["DAYS_PER_YEAR", "BucketLedger", "allocate_linear", "bucket_count", "build_buckets"]

DAYS_PER_YEAR = 365.25

#: the ledger columns, in the payload's order
COLUMNS = (
    "development_cost",
    "production_mining_cost",
    "processing_cost",
    "backfill_cost",
    "fixed_operating_cost",
    "initial_capital_cost",
    "revenue",
)


def bucket_count(end_day: float, bucket_days: float) -> int:
    """Buckets ``[k·b, (k+1)·b)`` covering ``[0, endDay]``; the last bucket is
    closed at ``endDay`` so an event AT the mine end is still allocated. At
    least one bucket exists."""
    if end_day <= 0.0:
        return 1
    n = math.ceil(end_day / bucket_days - 1e-12)
    return max(1, int(n))


@dataclass
class BucketLedger:
    bucket_days: float
    count: int
    cells: dict[str, list[float]] = field(init=False)

    def __post_init__(self) -> None:
        self.cells = {c: [0.0] * self.count for c in COLUMNS}

    def add(self, column: str, start_day: float, end_day: float, amount: float) -> None:
        if amount == 0.0:
            return
        for index, fraction in allocate_linear(start_day, end_day, self.bucket_days, self.count):
            self.cells[column][index] += amount * fraction


def allocate_linear(
    start_day: float, end_day: float, bucket_days: float, count: int
) -> list[tuple[int, float]]:
    """Overlap fractions of ``[start, end]`` with each bucket (sum = 1). A
    zero-length interval is a point event in the bucket containing it; an
    interval beyond the last bucket's end is clipped INTO the last bucket
    (the mine end day defines the ledger, so nothing lies beyond it)."""
    last = count - 1
    if end_day <= start_day:
        return [(min(last, max(0, math.floor(start_day / bucket_days + 1e-12))), 1.0)]
    length = end_day - start_day
    first = min(last, max(0, math.floor(start_day / bucket_days + 1e-12)))
    out: list[tuple[int, float]] = []
    remaining = 1.0
    for index in range(first, count):
        b0 = index * bucket_days
        b1 = (index + 1) * bucket_days if index < last else math.inf
        overlap = min(end_day, b1) - max(start_day, b0)
        if overlap <= 0.0:
            break
        fraction = overlap / length
        out.append((index, fraction))
        remaining -= fraction
        if b1 >= end_day:
            break
    if out and abs(remaining) > 1e-12:
        # clip: whatever fell outside the ledger goes to the last touched bucket
        index, fraction = out[-1]
        out[-1] = (index, fraction + remaining)
    return out


def build_buckets(ledger: BucketLedger, annual_rate: float) -> list[CashflowBucket]:
    buckets: list[CashflowBucket] = []
    cumulative = 0.0
    for i in range(ledger.count):
        start = i * ledger.bucket_days
        end = (i + 1) * ledger.bucket_days
        costs = [ledger.cells[c][i] for c in COLUMNS[:-1]]
        revenue = ledger.cells["revenue"][i]
        net = revenue - math.fsum(costs)
        cumulative += net
        mid = 0.5 * (start + end)
        factor = (1.0 + annual_rate) ** (mid / DAYS_PER_YEAR)
        buckets.append(
            CashflowBucket(
                index=i,
                start_day=start,
                end_day=end,
                development_cost=ledger.cells["development_cost"][i],
                production_mining_cost=ledger.cells["production_mining_cost"][i],
                processing_cost=ledger.cells["processing_cost"][i],
                backfill_cost=ledger.cells["backfill_cost"][i],
                fixed_operating_cost=ledger.cells["fixed_operating_cost"][i],
                initial_capital_cost=ledger.cells["initial_capital_cost"][i],
                revenue=revenue,
                net_cashflow=net,
                cumulative_cashflow=cumulative,
                discounted_net_cashflow=net / factor,
            )
        )
    return buckets
