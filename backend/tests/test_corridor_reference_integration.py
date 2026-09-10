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
    track = search.context.track
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
    ctx = search.context
    ref = search.context.reference
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
    ctx = search.context
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


# --------------------------------------------------------------------------- #
# SWITCHBACK (C3)
# --------------------------------------------------------------------------- #


def _switchback_frame(
    search: LayoutV2Search, cand: CandidateResult
) -> tuple[np.ndarray, np.ndarray]:
    """(n away from the ore, leg direction) of a SWITCHBACK candidate."""
    track = search.context.track
    assert cand.params.principal_orientation_deg is not None
    leg_dir = np.asarray(
        rotate(track.u_h, cand.params.principal_orientation_deg), dtype=np.float64
    )[:2]
    n = np.array([leg_dir[1], -leg_dir[0]])
    if float(n @ np.asarray(track.w_h)[:2]) < 0:
        n = -n
    return n, leg_dir


def _near_lateral(points: np.ndarray, z: float, half_interval: float, n: np.ndarray) -> float:
    """Ore-facing extreme of the delivered stack within ± half a level
    interval of ``z`` (the near leg or hairpin serving that level)."""
    sel = np.abs(points[:, 2] - z) <= half_interval
    assert sel.any()
    return float(np.min(points[sel, :2] @ n))


def _leg_runs(
    points: np.ndarray, leg_dir: np.ndarray, n: np.ndarray
) -> list[tuple[float, float, float]]:
    """Straight leg runs of a switchback stack as (z_top, z_bottom, lateral):
    maximal runs of samples whose heading is parallel to the leg direction.
    Hairpins (and their stations) are excluded, so the laterals are the
    legs' own — comparable between two builds whose z phase differs. The
    lateral is the MEDIAN over the run (robust to an end sample)."""
    seg = points[1:, :2] - points[:-1, :2]
    hat = seg / np.maximum(np.linalg.norm(seg, axis=1), 1e-12)[:, None]
    # straight legs are exactly parallel to the leg direction (a hairpin
    # reverses the heading by exactly π); a looser threshold admits the last
    # chord of a wide hairpin (1.6° off at R = 35 m) and lifts the run's top
    on_leg = np.abs(hat @ leg_dir) > 1.0 - 1e-9
    runs: list[tuple[float, float, float]] = []
    start: int | None = None
    for i, flag in enumerate(on_leg):
        if flag and start is None:
            start = i
        if not flag and start is not None:
            runs.append(
                (
                    float(points[start, 2]),
                    float(points[i, 2]),
                    float(np.median(points[start : i + 1, :2] @ n)),
                )
            )
            start = None
    if start is not None:
        runs.append(
            (
                float(points[start, 2]),
                float(points[-1, 2]),
                float(np.median(points[start:, :2] @ n)),
            )
        )
    return runs


def _near_legs(runs: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    """The ore-facing (near) legs of an alternating stack: local minima of
    the lateral sequence (the approach and any partial landing excluded)."""
    lat = [r[2] for r in runs]
    out = []
    for i in range(1, len(runs) - 1):
        if lat[i] < lat[i - 1] and lat[i] < lat[i + 1]:
            out.append(runs[i])
    return out


def test_switchback_stack_holds_the_corridor_intent_and_keeps_its_family_invariants(
    warped_301_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    """Every constructed SWITCHBACK candidate: each near leg lies at least six
    widths outward of the construction backbone support of every level whose
    plane is within half an interval of the leg's own z-span (the derived
    pair window + parity edge term); every near leg moved outward (never inward) against the
    reference-less build, cycle by cycle; hairpin radii never shrink below
    R_min and the leg spacing / nominal leg length are untouched; a
    zero-profile stack is bit-identical to the reference-less build."""
    search, res = warped_301_search
    ctx = search.context
    ref = search.context.reference
    assert ctx is not None and ref is not None and ref.active
    legacy_ctx: LayoutContext = replace(ctx, reference=None)
    levels = res.serviceable_levels
    half_interval = 0.5 * abs(levels[1].elevation - levels[0].elevation)
    r_min = float(search.scenario.ramp.min_turn_radius)
    corrected = identical = 0
    for cand in res.candidates:
        if cand.points is None or cand.params.family.value != "SWITCHBACK":
            continue
        rebuilt = build_family(cand.params, legacy_ctx)
        assert isinstance(rebuilt, FamilyGeometry)
        correction = cand.derived["corridorCorrection"]
        assert cand.derived["legSpacing"] == rebuilt.derived["legSpacing"]
        assert cand.derived["legLengthNominal"] == rebuilt.derived["legLengthNominal"]
        for piece in cand.pieces:
            if piece["kind"] == "ARC":
                assert piece["radius"] >= r_min - 1e-9, (cand.candidate_id, piece)
        if not correction["active"]:
            assert np.array_equal(cand.points, rebuilt.points), cand.candidate_id
            identical += 1
            continue
        corrected += 1
        n, leg_dir = _switchback_frame(search, cand)
        new_near = _near_legs(_leg_runs(cand.points, leg_dir, n))
        old_near = _near_legs(_leg_runs(rebuilt.points, leg_dir, n))
        assert new_near and old_near, cand.candidate_id
        # outward only, cycle by cycle: the corrected stack's join elevation
        # (hence every leg's start) shifts slightly with the corridor, and the
        # legacy near leg follows the linear track edge, so the comparison
        # allows exactly the edge shift between the two legs' start elevations
        edge = search.context.track.footwall_edge
        for (z_new, _, lat_new), (z_old, _, lat_old) in zip(new_near, old_near, strict=False):
            edge_shift = abs(float((edge(z_new) - edge(z_old)) @ n))
            assert lat_new >= lat_old - edge_shift - 1e-6, (
                cand.candidate_id,
                (z_new, lat_new),
                (z_old, lat_old),
                edge_shift,
            )
        # the intent: every near leg clears every level plane near its z-span
        records = cand.derived["corridorCorrectionLevels"]
        assert len(records) == len(levels)
        checked = 0
        for z_top, z_bot, lat in new_near:
            for lv, rec in zip(levels, records, strict=True):
                if rec["support"] is None:
                    continue
                if not (z_bot - half_interval <= lv.elevation <= z_top + half_interval):
                    continue
                assert lat >= rec["support"] + ref.margin - CROSSING_SAMPLE_TOLERANCE_M, (
                    cand.candidate_id,
                    lv.level_id,
                    (z_top, z_bot, lat),
                    rec,
                )
                checked += 1
        assert checked > 0, cand.candidate_id
    assert corrected + identical > 0, "no SWITCHBACK candidate constructed on WARPED-301"


# --------------------------------------------------------------------------- #
# WARPED-307 causal regressions (Gate A population; slow)
# --------------------------------------------------------------------------- #


def test_307_failing_candidates_now_hold_the_separation_at_every_rl_crossing() -> None:
    """Gate A causal fact on WARPED-307: SPIRAL-n1-CW-e+0-g0.100 and
    SWITCHBACK-k1-p+0-CW-s50-g0.120 failed their level accesses because the
    corridor sat ≈ 7 m from the level backbones (GRADE_LIMIT /
    INSUFFICIENT_RAMP_PILLAR plurality labels). With the shared reference the
    delivered corridor keeps six widths from the construction backbone at
    every RL crossing the ramp runs alongside. This is a SEPARATION
    regression on the delivered geometry — never a success-count or
    feasibility assertion: the access planner keeps its full authority."""
    from minegen.core.enums import ScenarioPreset
    from minegen.core.models import Scenario
    from minegen.services.scenario_realizer import realize_scenario
    from minegen.world.synthetic_world import generate_world

    sc = Scenario(
        **realize_scenario(ScenarioPreset.RANDOM_WARPED_VEIN, 307, fault_count=1).model_dump()
    )
    search = LayoutV2Search(sc, generate_world(sc))
    res = search.run()
    ref = search.context.reference
    assert ref is not None and ref.active
    levels = res.serviceable_levels
    half_interval = 0.5 * abs(levels[1].elevation - levels[0].elevation)
    checked = 0
    for cid in ("SPIRAL-n1-CW-e+0-g0.100", "SWITCHBACK-k1-p+0-CW-s50-g0.120"):
        cand = res.candidate(cid)
        assert cand is not None, cid
        if cand.points is None:
            # a typed construction failure under the corrected corridor is a
            # legitimate outcome (never relaxed); it must be typed, not silent
            assert cand.failure_reasons, cid
            continue
        correction = cand.derived["corridorCorrection"]
        assert correction["active"] is True and correction["maxDelta"] > 0.0, cid
        if cand.params.family.value == "SPIRAL":
            n, _, _, _ = _spiral_frame(search, res, cand)
        else:
            n, _ = _switchback_frame(search, cand)
        for lv, rec in zip(levels, cand.derived["corridorCorrectionLevels"], strict=True):
            if rec["support"] is None:
                continue
            near = _near_lateral(cand.points, lv.elevation, half_interval, n)
            if cand.params.family.value == "SPIRAL":
                lateral = _crossing_lateral(cand.points, lv.elevation, n)
                near = lateral if lateral is not None else near
            assert near >= rec["support"] + ref.margin - CROSSING_SAMPLE_TOLERANCE_M, (
                cid,
                lv.level_id,
                near,
                rec,
            )
            checked += 1
    assert checked > 0
