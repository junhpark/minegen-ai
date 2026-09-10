"""Phase 20C.4 Gate C — the conservative construction ``ServiceReference``
(commit C1: abstraction + tests, no corridor call-site change).

Contract under test (docs/verification/phase20c4_gate_b_contract.md §4,
refined by Gate C step 0):

* one construction reference per search, built from the WORLD-policy offset
  traces stage 4 already caches (token ``"WORLD"`` — no second clearance
  field);
* ``delta(z) ≥ 0`` piecewise-linear between the required levels, constant
  beyond, EXACTLY ``0.0`` when inactive — TABULAR (analytic path) and an
  explicit ``footwallStandoff`` keep the legacy geometry bit-for-bit;
* footprint = the ramp's own along-extent; an empty footprint yields 0;
* stage-4 dominance: the candidate-policy backbone never lies outward of
  the construction backbone inside the same footprint.
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from minegen.core.enums import ScenarioPreset
from minegen.core.models import Scenario
from minegen.layout.access import MIN_DEVELOPMENT_TRACE_LENGTH
from minegen.layout.families import (
    RAMP_CORRIDOR_MARGIN_WIDTHS,
    build_family,
    corridor_profile,
    rotate,
)
from minegen.layout.reference import (
    INACTIVE_EXPLICIT_STANDOFF,
    INACTIVE_TABULAR,
    ZERO_PROFILE,
    DeltaProfile,
    build_service_reference,
)
from minegen.layout.search import LayoutSearchResult, LayoutV2Search
from minegen.services.scenario_realizer import realize_scenario
from minegen.world.synthetic_world import SyntheticWorld, generate_world

from .conftest import small_scenario


@pytest.fixture(scope="module")
def tabular_search() -> tuple[LayoutV2Search, LayoutSearchResult]:
    sc = small_scenario()
    search = LayoutV2Search(sc, generate_world(sc))
    return search, search.run()


def _spiral_footprint(
    search: LayoutV2Search, res: LayoutSearchResult, candidate_id: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """(n, along, per-level centres, half) of a SPIRAL candidate's rim."""
    cand = res.candidate(candidate_id)
    assert cand is not None and cand.params.entry_orientation_deg is not None
    track = search._track
    n = np.asarray(rotate(track.w_h, cand.params.entry_orientation_deg), dtype=np.float64)[:2]
    along = np.array([n[1], -n[0]])
    radius = float(cand.derived["radius"])
    centres = np.asarray(
        [float(track.footwall_edge(lv.elevation) @ along) for lv in res.serviceable_levels]
    )
    return n, along, centres, radius


# --------------------------------------------------------------------------- #
# DeltaProfile
# --------------------------------------------------------------------------- #


def test_delta_profile_is_piecewise_linear_clamped_and_exactly_zero_when_inactive() -> None:
    p = DeltaProfile(np.array([0.0, -25.0, -50.0]), np.array([0.0, 10.0, -3.0]), ("A", "B", "C"))
    assert not p.zero
    assert p(-12.5) == pytest.approx(5.0)
    assert p(-25.0) == pytest.approx(10.0)
    assert p(-37.5) == pytest.approx(5.0)  # the −3 is clamped to 0, never negative
    assert p(-50.0) == 0.0
    assert p(10.0) == 0.0 and p(-90.0) == 0.0  # constant beyond the level range
    assert p.to_dict()["deltas"] == {"A": 0.0, "B": 10.0, "C": 0.0}
    assert p.max_delta == 10.0
    z = DeltaProfile(np.array([0.0, -25.0]), np.zeros(2), ("A", "B"))
    assert z.zero and ZERO_PROFILE.zero
    for value in (z(-12.5), ZERO_PROFILE(-12.5), ZERO_PROFILE(1e9)):
        assert value == 0.0 and math.copysign(1.0, value) == 1.0  # exact +0.0


# --------------------------------------------------------------------------- #
# TABULAR: inactive, bit-identical
# --------------------------------------------------------------------------- #


def test_tabular_reference_is_inactive_and_every_family_is_bit_identical(
    tabular_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    search, res = tabular_search
    ref = search._reference
    assert ref is not None and not ref.active and ref.inactive_reason == INACTIVE_TABULAR
    assert res.performance["serviceReference"]["active"] is False
    assert res.performance["serviceReference"]["inactiveReason"] == INACTIVE_TABULAR
    ctx = search._ctx
    assert ctx is not None and ctx.reference is ref
    legacy = replace(ctx, reference=None)
    compared = 0
    for cand in res.candidates:
        with_ref = build_family(cand.params, ctx)
        without = build_family(cand.params, legacy)
        assert type(with_ref) is type(without)
        if hasattr(with_ref, "points"):
            assert np.array_equal(with_ref.points, without.points)  # bit-identical
            assert with_ref.derived == without.derived
            compared += 1
        else:
            assert with_ref.reason == without.reason and with_ref.detail == without.detail
    assert compared > 0
    # the profile helper itself returns the exact zero profile
    n = np.array([1.0, 0.0])
    prof, records = corridor_profile(ctx, n, np.array([0.0, 1.0]), np.zeros(len(ctx.levels)), 30.0)
    assert prof is ZERO_PROFILE and records == []


# --------------------------------------------------------------------------- #
# explicit stand-off: legacy corridor preserved
# --------------------------------------------------------------------------- #


def test_explicit_footwall_standoff_keeps_the_legacy_corridor(
    warped_301_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    search, res = warped_301_search
    assert search._sections is not None and search._track is not None
    ref = build_service_reference(
        search._sections,
        res.serviceable_levels,
        search._track.w_h,
        orebody=search.world.orebody,
        clearance=search.policy.signed_clearance,
        basis=search.policy.basis,
        standoff=50.0,
        standoff_source="EXPLICIT",
        margin=RAMP_CORRIDOR_MARGIN_WIDTHS * search.scenario.ramp.tunnel_width,
        anchor_standoff=search.anchor_standoff(res.required_clearance, search.policy),
        min_trace_length=MIN_DEVELOPMENT_TRACE_LENGTH,
        end_margin=30.0,
        required_clearance=res.required_clearance,
    )
    assert not ref.active and ref.inactive_reason == INACTIVE_EXPLICIT_STANDOFF
    assert all(b is None for b in ref.backbones)  # nothing built, nothing hidden
    assert ref.diagnostics["traceFailures"] == {}
    n, along, centres, half = _spiral_footprint(search, res, res.ranking[0])
    prof, records = ref.profile(n, along, centres, half, np.zeros_like(centres))
    assert prof is ZERO_PROFILE and records == []


# --------------------------------------------------------------------------- #
# WARPED: active, deterministic, outward-only, empty footprint ⇒ 0
# --------------------------------------------------------------------------- #


def test_warped_reference_is_active_deterministic_and_corrects_outward_only(
    warped_301_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    search, res = warped_301_search
    ref = search._reference
    assert ref is not None and ref.active and ref.inactive_reason is None
    assert ref.basis == search.policy.basis == "COARSE_CONSERVATIVE"
    assert ref.standoff_source == "DEFAULT_OFFSET_PLUS_CORRIDOR_MARGIN"
    assert ref.standoff == res.standoff
    assert ref.diagnostics["traceFailures"] == {}
    assert all(b is not None and b.shape[0] > 0 for b in ref.backbones)
    payload = res.performance["serviceReference"]
    assert payload["active"] is True and payload["basis"] == "COARSE_CONSERVATIVE"
    assert len(payload["levels"]) == len(res.serviceable_levels)
    # the winner is a SPIRAL (golden WARPED-301): its rim footprint
    winner = res.winner_id
    assert winner is not None and winner.startswith("SPIRAL")
    n, along, centres, half = _spiral_footprint(search, res, winner)
    ctx = search._ctx
    assert ctx is not None
    prof_a, rec_a = corridor_profile(ctx, n, along, centres, half)
    prof_b, rec_b = corridor_profile(ctx, n, along, centres, half)
    assert np.array_equal(prof_a.deltas, prof_b.deltas) and rec_a == rec_b  # deterministic
    deltas = prof_a.deltas
    assert deltas.shape == (len(res.serviceable_levels),)
    assert np.all(np.isfinite(deltas)) and np.all(deltas >= 0.0)
    # causal fact (Gate B / C0 on the 301 winner): the corridor is too close to
    # the shallow-level backbones and already clear at the deepest level
    assert deltas[0] > 0.0, rec_a[0]
    assert deltas[-1] == 0.0, rec_a[-1]
    assert not prof_a.zero and prof_a.max_delta == float(np.max(deltas))
    for rec in rec_a:
        assert rec["pointsInFootprint"] > 0  # the rim runs alongside every level here
        base = rec["baseLateral"]
        assert rec["delta"] == pytest.approx(max(0.0, rec["support"] + ref.margin - base))
    # piecewise-linear between levels, constant beyond
    z0, z1 = res.serviceable_levels[0].elevation, res.serviceable_levels[1].elevation
    assert prof_a(0.5 * (z0 + z1)) == pytest.approx(0.5 * (deltas[0] + deltas[1]))
    assert prof_a(z0 + 100.0) == pytest.approx(deltas[0])
    # an empty footprint (nothing alongside the ramp at that level) is 0, never a fallback
    prof_e, rec_e = corridor_profile(ctx, n, along, centres + 1.0e4, half)
    assert prof_e.zero and prof_e(z0) == 0.0
    assert all(r["pointsInFootprint"] == 0 and r["delta"] == 0.0 for r in rec_e)


def test_reference_reads_the_same_world_trace_stage_4_caches(
    warped_301_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    """No second clearance field: the reference's traces are the cached
    WORLD-token offset traces (one per serviceable level at the world anchor
    stand-off) that stage-4 coarse anchors read."""
    search, res = warped_301_search
    assert search._sections is not None and search._reference is not None
    world_keys = {k for k in search._sections._offsets if k[4] == "WORLD"}
    assert len(world_keys) == len(res.serviceable_levels)
    standoffs = {k[2] for k in world_keys}
    assert standoffs == {round(search._reference.anchor_standoff, 6)}


# --------------------------------------------------------------------------- #
# stage-4 dominance invariant
# --------------------------------------------------------------------------- #


def test_stage_4_backbone_never_lies_outward_of_the_construction_backbone(
    warped_301_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    """``RefinedConservativeClearance = max(coarse, refined)`` certifies at
    least the construction field everywhere, so the candidate-policy offset
    trace (the backbone the level builder develops on) lies on or ore-ward of
    the WORLD construction trace: inside the winner's own footprint the
    candidate support along ``n`` never exceeds the construction support by
    more than the grid resolution the traces were extracted at. The
    candidate policy is reconstructed through the public ``candidate_policy``
    (refined-clearance provenance untouched by the reference)."""
    search, res = warped_301_search
    winner = res.winner_id
    assert winner is not None
    cand = res.candidate(winner)
    assert cand is not None and cand.clearance is not None
    _, policy, refinement = search.candidate_policy(res, winner)
    assert policy.basis == cand.clearance.basis == "REFINED_CONSERVATIVE"
    assert refinement["applied"] is True
    ref = search._reference
    sections, track = search._sections, search._track
    assert ref is not None and sections is not None and track is not None
    assert sections.resolution is not None
    tolerance = float(sections.resolution.effective_spacing)  # grid-resolution boundary (rule 177)
    n, along, centres, half = _spiral_footprint(search, res, winner)
    standoff_c = search.anchor_standoff(res.required_clearance, policy)
    assert standoff_c < ref.anchor_standoff  # the refined bound lowers the stand-off
    _, records = ref.level_deltas(n, along, centres, half, np.zeros(len(res.serviceable_levels)))
    checked = 0
    worst = -math.inf
    for i, lv in enumerate(res.serviceable_levels):
        off = sections.offset_trace(
            lv,
            track.w_h,
            standoff_c,
            MIN_DEVELOPMENT_TRACE_LENGTH,
            policy.signed_clearance,
            winner,
            res.required_clearance,
        )
        pts = np.asarray(off.points)[:, :2]
        win = np.abs(pts @ along - centres[i]) <= half
        if not win.any() or records[i]["support"] is None:
            continue
        support_c = float(np.max(pts[win] @ n))
        excess = support_c - float(records[i]["support"])
        worst = max(worst, excess)
        assert excess <= tolerance, (lv.level_id, support_c, records[i]["support"], tolerance)
        checked += 1
    assert checked >= len(res.serviceable_levels) - 1, checked
    assert worst < tolerance


# --------------------------------------------------------------------------- #
# WARPED-307: the failing spiral of the Gate A population
# --------------------------------------------------------------------------- #


def test_reference_delta_is_positive_on_the_failing_307_spiral() -> None:
    """Gate A / B causal fact: on WARPED-307 the corridor sits 19–20 m inside
    the intended separation on the SPIRAL-n1-CW-e+0-g0.100 rim (measured
    shadow); the reference reports a positive outward correction on every
    level the rim runs alongside, and (C2) the delivered helix is built on
    the corrected corridor."""
    sc = Scenario(
        **realize_scenario(ScenarioPreset.RANDOM_WARPED_VEIN, 307, fault_count=1).model_dump()
    )
    world: SyntheticWorld = generate_world(sc)
    search = LayoutV2Search(sc, world)
    res = search.run()
    ref = search._reference
    assert ref is not None and ref.active
    n, along, centres, half = _spiral_footprint(search, res, "SPIRAL-n1-CW-e+0-g0.100")
    ctx = search._ctx
    assert ctx is not None
    prof, records = corridor_profile(ctx, n, along, centres, half)
    alongside = [r for r in records if r["pointsInFootprint"] > 0]
    assert len(alongside) >= len(records) // 2, records
    assert all(r["delta"] > 0.0 for r in alongside), [(r["levelId"], r["delta"]) for r in records]
    assert prof.max_delta > 0.0
    cand = res.candidate("SPIRAL-n1-CW-e+0-g0.100")
    assert cand is not None and cand.points is not None
    # C2: the delivered helix differs from the reference-less build exactly
    # because the profile is active, and the candidate reports the correction
    assert cand.derived["corridorCorrection"]["active"] is True
    assert cand.derived["corridorCorrection"]["maxDelta"] == pytest.approx(prof.max_delta)
    legacy = replace(ctx, reference=None)
    rebuilt = build_family(cand.params, legacy)
    assert hasattr(rebuilt, "points") and not np.array_equal(rebuilt.points, cand.points)
