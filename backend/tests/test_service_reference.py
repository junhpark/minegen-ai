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
from typing import Any

import numpy as np
import pytest

from minegen.core.enums import ScenarioPreset
from minegen.core.models import Scenario
from minegen.layout.access import MIN_DEVELOPMENT_TRACE_LENGTH
from minegen.layout.families import (
    RAMP_CORRIDOR_MARGIN_WIDTHS,
    LayoutContext,
    build_family,
    corridor_profile,
    rotate,
)
from minegen.layout.reference import (
    INACTIVE_EXPLICIT_STANDOFF,
    INACTIVE_TABULAR,
    ZERO_PROFILE,
    DeltaProfile,
    WindowRequirementProfile,
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


def test_window_requirement_profile_semantics() -> None:
    """The window profile is ``max(0, max Q inside [z − below, z + above] −
    base(z))``: the base is read at the placement elevation itself, an empty
    window (or a level without support) contributes nothing, a level entering
    the window may jump the profile, and a profile with no requirement at all
    is the exact zero profile."""
    z = np.array([0.0, -25.0, -50.0, -75.0])
    req: list[float | None] = [None, 60.0, 20.0, None]

    def base(zz: float) -> float:
        return 30.0 + 0.2 * zz  # linear track edge + stand-off

    prof = WindowRequirementProfile(z, ("A", "B", "C", "D"), req, base, below=15.0, above=10.0)
    assert not prof.zero and prof.window == (15.0, 10.0)
    # window of z = -25: [-40, -15] → only B (60): 60 − base(−25) = 60 − 25
    assert prof(-25.0) == pytest.approx(35.0)
    # z = -40: [-55, -30] → C only (20): 20 − base(−40) = 20 − 22 → clamped 0
    assert prof(-40.0) == 0.0
    # z = -35: [-50, -25] → B and C → 60 − base(−35) = 60 − 23
    assert prof(-35.0) == pytest.approx(37.0)
    # just below z = -35 B (−25) leaves the window [z − 15, z + 10]: only C
    # remains (20 − base(−35.1) < 0 → 0) — the profile jumps at the window edge
    assert prof(-35.1) == 0.0
    # z = -9: [-24, 1] holds only A, which carries no requirement → 0;
    # z = -10 puts B exactly on the window edge (inclusive)
    assert prof(-9.0) == 0.0
    assert prof(-10.0) == pytest.approx(60.0 - base(-10.0))
    assert prof(1e6) == 0.0 and prof(-1e6) == 0.0  # beyond every level: no requirement
    payload = prof.to_dict()
    assert payload["windowBelowM"] == 15.0 and payload["windowAboveM"] == 10.0
    assert payload["requirements"] == {"A": None, "B": 60.0, "C": 20.0, "D": None}
    assert payload["deltas"]["B"] == pytest.approx(35.0) and payload["active"] is True
    empty = WindowRequirementProfile(z, ("A", "B", "C", "D"), [None] * 4, base, 15.0, 10.0)
    assert empty.zero and empty(-25.0) == 0.0 and empty.to_dict()["active"] is False
    with pytest.raises(ValueError):
        WindowRequirementProfile(z, ("A",), [None], base, 1.0, 1.0)


# --------------------------------------------------------------------------- #
# SWITCHBACK pair window — "why that width", derived from the pair geometry
# --------------------------------------------------------------------------- #


def _synthetic_switchback_setup(
    warped_301_search: tuple[LayoutV2Search, LayoutSearchResult],
    requirements: dict[str, float],
    edge_slope: float = 0.1,
) -> tuple[LayoutContext, np.ndarray, np.ndarray, np.ndarray, float, float, float]:
    """A synthetic ServiceReference on the real WARPED-301 context: one
    backbone point per level placed so that its lateral along ``n`` is
    exactly ``requirements[level] − margin`` (so the absolute corridor
    requirement of the level is ``requirements[level]``), and a synthetic
    LINEAR track edge ``edge(z)·n = edge_slope · z``. Everything else (levels,
    footprint) comes from the fixture."""
    import dataclasses

    search, res = warped_301_search
    ctx = search._ctx
    ref = search._reference
    assert ctx is not None and ref is not None and ref.active
    n = np.array([1.0, 0.0])
    along = np.array([0.0, 1.0])
    levels = res.serviceable_levels
    centres = np.zeros(len(levels))
    half = 50.0
    backbones = []
    for lv in levels:
        q = requirements.get(lv.level_id)
        if q is None:
            backbones.append(np.zeros((0, 2)))
        else:
            backbones.append(np.array([[q - ref.margin, 0.0]]))
    synthetic = dataclasses.replace(ref, backbones=tuple(backbones))

    class _Track:
        def __init__(self, base: Any) -> None:
            self._base = base
            self.w_h = base.w_h
            self.u_h = base.u_h

        def footwall_edge(self, z: float) -> np.ndarray:
            return np.array([edge_slope * z, 0.0])

        def centroid(self, z: float) -> np.ndarray:
            return self._base.centroid(z)

    fake_ctx = replace(ctx, reference=synthetic, track=_Track(ctx.track))
    dz = abs(levels[1].elevation - levels[0].elevation)
    drop = dz / 2.0  # k = 2: the pair span (2·drop) is one level interval
    return fake_ctx, n, along, centres, half, drop, dz


def test_switchback_window_is_the_pair_span_derived_from_the_leg_geometry(
    warped_301_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    """Why that width — derived from the stacking mechanics, not chosen.
    ``build_switchback`` applies ``delta`` exactly at every near-leg start,
    so the near leg starting at ``z`` (spanning ``[z − drop, z]``) sits at
    ``legacy_near(z) + delta(z)``. Attributing every leg elevation to its
    nearest level plane (± interval/2), the ABSOLUTE requirement a placement
    at ``z`` must honour is the maximum over the levels inside
    ``[z − drop − dz/2, z + dz/2]`` and nothing outside it — one window, no
    second band. The legacy stack itself is START-anchored on the linear
    track edge for a near-first stack and lags one cycle drop of edge for a
    far-first stack (its first near leg is placed by the whole first pair's
    drift), so the far-first base reads the most ore-ward edge of
    ``z ± drop``; no ± 2·drop edge band-min."""
    from minegen.layout.families import switchback_corridor_profile

    base_req = {"L03": 40.0, "L04": 10.0, "L05": 70.0, "L06": 10.0, "L07": 10.0, "L08": 55.0}
    ctx, n, along, centres, half, drop, dz = _synthetic_switchback_setup(
        warped_301_search, base_req
    )
    levels = ctx.levels
    z_of = {lv.level_id: lv.elevation for lv in levels}
    below, above = drop + 0.5 * dz, 0.5 * dz

    def edge(z: float) -> float:
        return float(ctx.track.footwall_edge(z) @ n)

    def base(z: float, far_first: bool) -> float:
        # a far-first stack carries one cycle drop of edge lag (the first
        # pair places its first near leg): the most ore-ward edge of z ± drop
        lat = min(edge(z - drop), edge(z), edge(z + drop)) if far_first else edge(z)
        return lat + ctx.standoff

    def expected(z: float, req: dict[str, float], far_first: bool) -> float:
        inside = [q for lid, q in req.items() if z - below <= z_of[lid] <= z + above]
        return max(0.0, max(inside) - base(z, far_first)) if inside else 0.0

    zs = np.linspace(z_of["L03"] + 3 * dz, z_of["L08"] - 3 * dz, 121)
    for far_first in (False, True):
        profile, records = switchback_corridor_profile(
            ctx, n, along, centres, half, drop, dz, far_first=far_first
        )
        for z in zs:
            assert profile(float(z)) == pytest.approx(
                expected(float(z), base_req, far_first), abs=1e-9
            ), (far_first, z)
        payload = profile.to_dict()
        assert payload["farFirst"] is far_first
        assert payload["edgeLagM"] == (drop if far_first else 0.0)
        assert payload["windowBelowM"] == below and payload["windowAboveM"] == above
        assert len(records) == len(levels) and all("requirement" in r for r in records)
    # the derived descent closure extends the window ABOVE only (a near leg
    # starts at most that far above the nominal z_pair its delta is read at)
    p_closed, _ = switchback_corridor_profile(
        ctx, n, along, centres, half, drop, dz, False, descent_closure=0.25
    )
    assert p_closed.window == (below, above + 0.25)
    assert p_closed.to_dict()["descentClosureM"] == 0.25
    p_near_first, _ = switchback_corridor_profile(ctx, n, along, centres, half, drop, dz, False)
    assert all(p_closed(float(z)) >= p_near_first(float(z)) - 1e-12 for z in zs)
    # the far-first stack is never placed ore-ward of the near-first one
    p_far_first, _ = switchback_corridor_profile(ctx, n, along, centres, half, drop, dz, True)
    assert all(p_far_first(float(z)) >= p_near_first(float(z)) - 1e-12 for z in zs)
    # a requirement change OUTSIDE the window of z never moves the corridor at z;
    # one INSIDE does — L07 is exactly one interval below L06
    z = z_of["L06"]
    far = dict(base_req)
    far["L03"] = 500.0  # L03 is 3 intervals above L06: outside [z − below, z + above]
    assert z_of["L03"] > z + above
    p_far, _ = switchback_corridor_profile(
        _synthetic_switchback_setup(warped_301_search, far)[0],
        n,
        along,
        centres,
        half,
        drop,
        dz,
        False,
    )
    assert p_far(z) == pytest.approx(p_near_first(z), abs=1e-9)
    near = dict(base_req)
    near["L07"] = 500.0  # one interval below L06: inside the window
    assert z - below <= z_of["L07"] <= z + above
    p_near, _ = switchback_corridor_profile(
        _synthetic_switchback_setup(warped_301_search, near)[0],
        n,
        along,
        centres,
        half,
        drop,
        dz,
        False,
    )
    assert p_near(z) == pytest.approx(500.0 - base(z, False), abs=1e-9)
