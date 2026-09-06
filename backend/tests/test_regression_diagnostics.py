"""Phase 20C.1-Q / W diagnostic helpers of the layout-v2 regression module."""

from __future__ import annotations

import math

from minegen.regression.layout_v2 import (
    YIELD_AUC_CORRELATED,
    YIELD_MIN_PAIRS,
    _rank_auc,
    _spearman,
)


def test_rank_auc_counts_pass_before_fail_pairs_with_half_ties() -> None:
    assert _rank_auc([], [1, 2]) == (None, 0)
    assert _rank_auc([1, 2], []) == (None, 0)
    # every pass ranks ahead of every fail → 1.0
    assert _rank_auc([1, 2], [3, 4]) == (1.0, 4)
    # every pass behind → 0.0; interleaved → 0.5
    assert _rank_auc([3, 4], [1, 2]) == (0.0, 4)
    auc, pairs = _rank_auc([1, 4], [2, 3])
    assert pairs == 4 and math.isclose(auc or 0.0, 0.5)
    # a tie counts one half
    auc, pairs = _rank_auc([2], [2])
    assert pairs == 1 and auc == 0.5


def test_spearman_handles_ties_and_degenerate_input() -> None:
    assert _spearman([1.0, 2.0], [1.0, 2.0]) is None  # below 3 pairs
    assert _spearman([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None  # constant input
    assert math.isclose(_spearman([1.0, 2.0, 3.0, 4.0], [10.0, 20.0, 30.0, 40.0]) or 0.0, 1.0)
    assert math.isclose(_spearman([1.0, 2.0, 3.0, 4.0], [40.0, 30.0, 20.0, 10.0]) or 0.0, -1.0)
    # ties take average ranks: (1, 1, 3) vs (1, 2, 3) → 0.866
    r = _spearman([1.0, 1.0, 3.0], [1.0, 2.0, 3.0])
    assert r is not None and math.isclose(r, math.sqrt(3.0) / 2.0, rel_tol=1e-9)


def test_yield_decision_rule_constants_are_sane() -> None:
    assert 0.5 < YIELD_AUC_CORRELATED < 1.0 and YIELD_MIN_PAIRS >= 1
