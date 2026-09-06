"""Phase 20C.1-Q / W diagnostic helpers of the layout-v2 regression module."""

from __future__ import annotations

import json
import math

from minegen.regression.layout_v2 import (
    WARPED_SURVEY_SEEDS,
    YIELD_AUC_CORRELATED,
    YIELD_MIN_PAIRS,
    _rank_auc,
    _spearman,
    pooled_rank_auc,
)
from minegen.regression.repool import repool


def test_pooled_auc_is_pair_weighted_within_case_not_concatenated() -> None:
    """Closeout A-1: family-internal ranks restart at 1 in every case, so the
    pooled statistic must combine per-case Mann-Whitney counts
    (Σ wins / Σ pairs), never a rank list concatenated across cases."""
    # both cases are PERFECT internally (the pass outranks the fail), but the
    # second case's family has more candidates, so its ranks are larger
    per_case = [([1], [2]), ([5], [6])]
    out = pooled_rank_auc(per_case)
    assert out["rankAuc"] == 1.0 and out["rankPairs"] == 2
    assert out["casesUsed"] == 2 and out["casesWithoutPairs"] == 0
    assert out["pooling"] == "PAIR_WEIGHTED_WITHIN_CASE"
    # the discarded pooling concatenates the rank lists and compares case-1
    # ranks with case-2 ranks (5 < 2 is a "loss" between different scales),
    # answering 0.75 for two perfectly ordered cases
    naive, naive_pairs = _rank_auc([1, 5], [2, 6])
    assert naive_pairs == 4 and naive == 0.75
    # a case with no pass/fail pair contributes nothing and is counted
    out2 = pooled_rank_auc([*per_case, ([], [1, 2, 3]), ([1], [])])
    assert out2["rankAuc"] == out["rankAuc"] and out2["rankPairs"] == out["rankPairs"]
    assert out2["casesUsed"] == 2 and out2["casesWithoutPairs"] == 2
    # pair weighting: a case with many pairs carries more weight than a
    # one-pair case, which plain averaging of per-case AUCs would not do
    weighted = pooled_rank_auc([([1], [2]), ([3, 4], [1, 2])])
    assert weighted["rankPairs"] == 5 and weighted["rankAuc"] == 0.2
    # empty input is honest, not zero
    empty = pooled_rank_auc([])
    assert empty["rankAuc"] is None and empty["rankPairs"] == 0 and not empty["correlated"]
    # the correlation verdict uses the documented a priori thresholds
    assert pooled_rank_auc([([1, 2, 3], [4, 5, 6])])["correlated"] is True
    assert pooled_rank_auc([([4, 5, 6], [1, 2, 3])])["correlated"] is False


def test_repool_rewrites_only_the_pooled_block_of_a_historical_artifact() -> None:
    """Closeout A-2: the correction is recomputed from the artifact's own
    rows — every per-case measurement survives untouched."""
    report = {
        "label": "historical",
        "pooled": {"SPIRAL": {"rankAuc": 0.9, "rankPairs": 99}},
        "cases": [
            {
                "key": "C1",
                "families": {
                    "SPIRAL": {
                        "rankAuc": 1.0,
                        "rows": [
                            {"familyRank": 1, "detailedPass": True},
                            {"familyRank": 2, "detailedPass": False},
                        ],
                    }
                },
            },
            {
                "key": "C2",
                "families": {
                    "SPIRAL": {
                        "rankAuc": 0.0,
                        "rows": [
                            {"familyRank": 1, "detailedPass": False},
                            {"familyRank": 2, "detailedPass": True},
                        ],
                    }
                },
            },
        ],
    }
    original_cases = json.dumps(report["cases"], sort_keys=True)
    out = repool(report)
    assert out["pooled"]["SPIRAL"]["rankAuc"] == 0.5  # one win, one loss
    assert out["pooled"]["SPIRAL"]["rankPairs"] == 2 and out["pooled"]["SPIRAL"]["casesUsed"] == 2
    assert "closeout A-2" in out["pooledCorrection"]
    assert json.dumps(out["cases"], sort_keys=True) == original_cases


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


def test_survey_seed_list_is_fixed_and_large_enough() -> None:
    assert len(WARPED_SURVEY_SEEDS) >= 30
    assert len(set(WARPED_SURVEY_SEEDS)) == len(WARPED_SURVEY_SEEDS)
    assert 301 in WARPED_SURVEY_SEEDS and 307 in WARPED_SURVEY_SEEDS  # the golden seeds
    assert 0.5 < YIELD_AUC_CORRELATED < 1.0 and YIELD_MIN_PAIRS >= 1
