"""Phase 20C.4 Gate C — corridor call-site integration of the construction
``ServiceReference`` (C2 SPIRAL, C3 SWITCHBACK).

The corridor and the level anchors now share ONE spacing reference: on the
delivered polyline the ore-facing corridor lateral at every level is at
least ``support + 6 widths`` from the construction backbone the ramp runs
alongside (rule 170 intent), the correction is outward-only, a corridor the
reference does not touch is bit-identical to the pre-reference build, and no
hard gate, threshold, score coefficient or screen semantic changes.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from minegen.layout.families import (
    FamilyGeometry,
    LayoutContext,
    build_family,
    corridor_profile,
    rotate,
)
from minegen.layout.geometry import find_crossing
from minegen.layout.search import CandidateResult, LayoutSearchResult, LayoutV2Search

#: one chord-exact descent sample on a drifting axis: the level crossing is
#: interpolated between two samples whose axes differ by < 1 m of lateral
#: (sample spacing × gradient × lateral slope ≤ 5 × 0.12 × 1) — a numerical
#: sampling tolerance, never an engineering margin
CROSSING_SAMPLE_TOLERANCE_M = 1.0


def _spiral_frame(
    search: LayoutV2Search, res: LayoutSearchResult, cand: CandidateResult
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    track = search._track
    assert cand.params.entry_orientation_deg is not None
    n = np.asarray(rotate(track.w_h, cand.params.entry_orientation_deg), dtype=np.float64)[:2]
    along = np.array([n[1], -n[0]])
    centres = np.asarray(
        [float(track.footwall_edge(lv.elevation) @ along) for lv in res.serviceable_levels]
    )
    return n, along, centres, float(cand.derived["radius"])


def _crossing_lateral(points: np.ndarray, z: float, n: np.ndarray) -> float | None:
    cr = find_crossing(points, z)
    if cr is None:
        return None
    return float(np.asarray(cr.point)[:2] @ n)


# --------------------------------------------------------------------------- #
# SPIRAL (C2)
# --------------------------------------------------------------------------- #


def test_spiral_rim_holds_the_corridor_intent_against_the_construction_backbone(
    warped_301_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    """Corridor and anchors share authority: on every level the winner's rim
    runs alongside, the delivered RL crossing lies at least six widths
    outward of the construction backbone support; the correction is exactly
    the reference profile (outward only) and is reported on the candidate."""
    search, res = warped_301_search
    ctx = search._ctx
    ref = search._reference
    assert ctx is not None and ref is not None and ref.active
    winner = res.candidate(res.winner_id or "")
    assert winner is not None and winner.params.family.value == "SPIRAL"
    n, along, centres, radius = _spiral_frame(search, res, winner)
    profile, records = corridor_profile(ctx, n, along, centres, radius)
    assert not profile.zero  # 301: the shallow levels need a correction
    correction = winner.derived["corridorCorrection"]
    assert correction["active"] is True
    assert correction["deltas"] == profile.to_dict()["deltas"]
    assert winner.derived["corridorCorrectionLevels"] == records
    legacy = build_family(winner.params, replace(ctx, reference=None))
    assert isinstance(legacy, FamilyGeometry)
    assert winner.points is not None
    checked = 0
    for lv, rec in zip(res.serviceable_levels, records, strict=True):
        if rec["support"] is None:
            continue
        z = lv.elevation
        lateral_new = _crossing_lateral(winner.points, z, n)
        lateral_old = _crossing_lateral(legacy.points, z, n)
        assert lateral_new is not None and lateral_old is not None
        # six widths from the backbone the rim runs alongside (the intent)
        assert lateral_new >= rec["support"] + ref.margin - CROSSING_SAMPLE_TOLERANCE_M, (
            lv.level_id,
            lateral_new,
            rec,
        )
        # moved outward by the profile and by nothing else
        assert lateral_new - lateral_old == pytest.approx(
            profile(z), abs=CROSSING_SAMPLE_TOLERANCE_M
        ), (lv.level_id, lateral_new, lateral_old, profile(z))
        assert lateral_new >= lateral_old - 1e-9
        checked += 1
    assert checked >= len(res.serviceable_levels) - 1


def test_uncorrected_candidates_are_bit_identical_and_the_reference_only_moves_outward(
    warped_301_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    """Ordering can only change where geometry changes: every constructed
    candidate whose profile is zero rebuilds bit-identically without the
    reference; every corrected one keeps its family invariants (helix radius
    / leg spacing unchanged) and only moves its corridor outward."""
    search, res = warped_301_search
    ctx = search._ctx
    assert ctx is not None
    legacy_ctx: LayoutContext = replace(ctx, reference=None)
    identical = corrected = 0
    for cand in res.candidates:
        if cand.points is None or cand.params.family.value != "SPIRAL":
            continue
        rebuilt = build_family(cand.params, legacy_ctx)
        assert isinstance(rebuilt, FamilyGeometry)
        correction = cand.derived["corridorCorrection"]
        if not correction["active"]:
            assert np.array_equal(cand.points, rebuilt.points), cand.candidate_id
            identical += 1
            continue
        corrected += 1
        assert cand.derived["radius"] == rebuilt.derived["radius"]
        assert correction["maxDelta"] > 0.0
        assert all(d >= 0.0 for d in correction["deltas"].values())
        n, _, _, _ = _spiral_frame(search, res, cand)
        for lv in res.serviceable_levels:
            new = _crossing_lateral(cand.points, lv.elevation, n)
            old = _crossing_lateral(rebuilt.points, lv.elevation, n)
            if new is None or old is None:
                continue
            assert new >= old - CROSSING_SAMPLE_TOLERANCE_M, (cand.candidate_id, lv.level_id)
    assert corrected > 0
    assert identical + corrected > 0
