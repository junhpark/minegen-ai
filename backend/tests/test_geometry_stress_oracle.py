"""GEOMETRY-STRESS oracle (Phase 20B.x, Park decision §1).

The layout-v2 golden's GEOMETRY-STRESS case (15 m sublevels, R_min 20 m,
10 % ramp, access g_max 0.12) lost its SWITCHBACK winner when the level-
access branch started to follow the ramp floor (rule 188). This is a
feasibility-semantics change, so it is pinned EXPLICITLY rather than read
off the regenerated baseline: the old winner's odd-level accesses were
short branches climbing straight out of the descending ramp floor — the
unphysical vertical step itself — and once the branch lies ON the ramp
floor through the turnout the same entries cannot be reached inside the
gradient limit, while every gradient-passing alternative (a long descending
branch from a junction above the level) runs alongside the switchback legs
and fails the B-2 rock pillar. Nothing here goldenizes search order or
incidental counts: every assertion names a hard gate.
"""

from __future__ import annotations

from minegen.design.profile import build_profile
from minegen.layout import access as acc
from minegen.layout.families import InfeasibleReason, build_footwall_track
from minegen.layout.levels import LevelSections, required_levels
from minegen.layout.results import CandidateStatus
from minegen.layout.search import LayoutV2Search, required_clearance
from minegen.regression.layout_v2 import case_by_key
from minegen.world.synthetic_world import generate_world

OLD_WINNER = "SWITCHBACK-k1-p+20-CW-s50-g0.100"
HARD_GATES = {
    acc.AccessFailure.GRADE_LIMIT,
    acc.AccessFailure.INSUFFICIENT_RAMP_PILLAR,
    acc.AccessFailure.CONNECTOR_UNAVAILABLE,
    acc.AccessFailure.JUNCTION_SPACING_CONFLICT,
}


def test_geometry_stress_has_no_feasible_candidate_for_hard_physical_reasons() -> None:
    case = case_by_key("GEOMETRY-STRESS")
    sc = case.realize()
    world = generate_world(sc)
    search = LayoutV2Search(sc, world)
    res = search.run()

    # 4. the deterministic outcome: no feasible candidate
    assert res.winner_id is None
    assert all(c.status != CandidateStatus.FEASIBLE for c in res.candidates)

    # 1. the old winner exists, was validated, and is refused for level access only
    old = res.candidate(OLD_WINNER)
    assert old is not None and old.status == CandidateStatus.INFEASIBLE
    assert old.failure_reasons == [InfeasibleReason.LEVEL_ACCESS_INFEASIBLE]
    plan = old.access_plan
    assert plan is not None and not plan.feasible
    failed = [a for a in plan.accesses if not a.ok]
    served = [a for a in plan.accesses if a.ok]
    assert failed and served  # a real mix: the rule kills SOME levels, not the search

    # 2. every failed level fails on hard gates — no numerical instability, no
    #    starvation: GRADE_LIMIT is the dominant reason, the pillar refuses the
    #    rest, and ignoring the used junction spacing changes nothing
    for a in failed:
        assert a.failure_reason == acc.AccessFailure.GRADE_LIMIT, a.level_id
        assert a.candidates_valid == 0
        assert set(a.rejection_counts) <= HARD_GATES, (a.level_id, a.rejection_counts)
        assert a.rejection_counts.get(acc.AccessFailure.GRADE_LIMIT, 0) > 0
        assert a.rejection_counts.get(acc.AccessFailure.INSUFFICIENT_RAMP_PILLAR, 0) > 0
        if a.assignment_diagnostic is not None:
            assert a.assignment_diagnostic["starvationSuspected"] is False
            assert a.assignment_diagnostic["validCandidatesIgnoringSpacing"] == 0

    # 1.–3. connector-level proof on the first failed level, with the SAME
    #       context the planner used (junction lattice, r_min, g_max, taper,
    #       pillar requirement): (a) an access that the chord-only profile
    #       admitted is refused by the gradient gate under rule 188 because it
    #       must first descend WITH the ramp; (b) every branch the gradient
    #       gate still admits fails the rock-pillar gate
    levels = required_levels(
        world.orebody,
        sc.mining.sublevel_interval,
        sc.design.top_mining_margin,
        sc.design.bottom_mining_margin,
    )
    sections = LevelSections(world.orebody, levels, sc.layout.section_sampling_spacing)
    track = build_footwall_track(world.orebody, sections)
    assert track is not None
    req = required_clearance(sc.design, sc.ramp, sc.tunnel_profile)
    shape = build_profile(sc.ramp, sc.tunnel_profile)
    cfg = sc.layout.access
    ctx = acc._plan_context(
        old.points, cfg, sc.ramp, search.evaluator, shape, req, acc.LONG_ACCESS_COEF
    )
    by_id = {lv.level_id: lv for lv in sections.serviceable()}
    checked = 0
    for a in failed[:3]:
        lv = by_id[a.level_id]
        anchor = acc.build_anchor(
            world.orebody,
            lv,
            sections,
            track,
            old.points,
            search.anchor_standoff(req),
            sc.mining.method.value,
        )
        assert isinstance(anchor, acc.LevelDevelopmentAnchor)
        cands = acc._junction_candidates(
            old.points, lv.elevation, cfg, anchor.position[:2], ctx.ramp_ch, ctx.ramp_az
        )
        refused_physical = 0
        admitted_by_grade = 0
        for cand in cands:
            for kind in ("L", "R"):
                legacy = acc.build_connector(
                    cand.position,
                    cand.heading,
                    anchor.position,
                    ctx.r_min,
                    cfg.access_sampling_spacing,
                    kind,
                    None,
                )
                new = acc.build_connector(
                    cand.position,
                    cand.heading,
                    anchor.position,
                    ctx.r_min,
                    cfg.access_sampling_spacing,
                    kind,
                    ctx.floor,
                    cand.chainage,
                )
                if legacy is None or new is None:
                    continue
                legacy_ok = legacy.max_gradient <= ctx.g_max + acc.GRADIENT_TOLERANCE
                new_ok = new.max_gradient <= ctx.g_max + acc.GRADIENT_TOLERANCE
                if legacy_ok and not new_ok:
                    # (a) the branch starts by descending with the ramp floor
                    # (follow length > 0, follow edges descend) and only then
                    # reaches for the entry — the chord profile hid that
                    assert new.ramp_follow_length > 0.0
                    h = new.handoff_index
                    assert float(new.points[h, 2] - new.points[0, 2]) < 0.0
                    refused_physical += 1
                if new_ok:
                    admitted_by_grade += 1
                    # (b) the pillar gate: delivered branch beyond the taper
                    _, gap = acc.gated_separation(
                        new.points, old.points, ctx.shape, ctx.taper_arc, ctx.ramp_tree
                    )
                    assert gap < ctx.exc_sep_min - acc.SEPARATION_TOLERANCE, (
                        a.level_id,
                        cand.chainage,
                        kind,
                        gap,
                    )
        assert refused_physical > 0, a.level_id
        assert admitted_by_grade > 0, a.level_id
        checked += 1
    assert checked >= 1
