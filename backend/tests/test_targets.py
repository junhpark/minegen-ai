"""Phase 03 gate tests: levels and level-aware footwall candidates (rules 43–45)."""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from minegen.core.coordinates import azimuth_to_unit_vector
from minegen.core.models import OrebodyConfig, Point3D
from minegen.design.constraints import RejectionReason
from minegen.design.cost_field import DesignCostEvaluator
from minegen.design.targets import (
    AccessTargetSet,
    default_portal,
    footwall_candidate_position,
    generate_access_targets,
    generate_level_elevations,
    resolve_portal,
)
from minegen.world.orebody import TabularOrebody, build_orebody
from minegen.world.synthetic_world import generate_world
from tests.conftest import small_scenario


def build(sc=None) -> tuple:  # type: ignore[no-untyped-def, type-arg]
    sc = sc or small_scenario(with_fault=True)
    w = generate_world(sc)
    ev = DesignCostEvaluator(w, sc.design)
    portal, gen = resolve_portal(sc, w)
    ts = generate_access_targets(
        w, sc.design, sc.ramp, sc.mining.sublevel_interval, ev, portal, gen
    )
    return sc, w, ev, ts


# -- levels -----------------------------------------------------------------


def test_level_elevations_from_analytic_extent() -> None:
    sc = small_scenario()
    w = generate_world(sc)
    lo, hi = w.orebody.bounding_box()
    levels = generate_level_elevations(w.orebody, 25.0, 10.0, 10.0)
    assert levels[0] == pytest.approx(hi[2] - 10.0)
    assert all(b - a == pytest.approx(-25.0) for a, b in itertools.pairwise(levels))
    assert levels[-1] >= lo[2] + 10.0
    assert levels[-1] - 25.0 < lo[2] + 10.0  # no further level fits


def test_no_levels_when_margins_exceed_extent() -> None:
    sc = small_scenario()
    w = generate_world(sc)
    assert generate_level_elevations(w.orebody, 25.0, 500.0, 500.0) == []


# -- candidate geometry (rule 43) --------------------------------------------


@pytest.mark.parametrize("strike", [0.0, 35.0, 90.0, 200.0])
@pytest.mark.parametrize("dip", [30.0, 70.0, 90.0])
def test_candidate_has_exact_elevation_and_footwall_offset(strike: float, dip: float) -> None:
    ob = build_orebody(
        OrebodyConfig(
            center=Point3D(x=40, y=20, z=-50),
            strike_deg=strike,
            dip_deg=dip,
            length=200,
            height=120,
            thickness=12,
        )
    )
    assert isinstance(ob, TabularOrebody)
    for z in (-80.0, -50.0, -20.0):
        for u in (-50.0, 0.0, 50.0):
            p, v_coord, q = footwall_candidate_position(ob, u, z, 20.0)
            assert p[2] == pytest.approx(z, abs=1e-9)  # exact level elevation
            local = ob.to_local(p)
            assert local[0] == pytest.approx(u, abs=1e-9)  # along-strike coordinate
            assert local[1] == pytest.approx(v_coord, abs=1e-9)
            assert local[2] == pytest.approx(q, abs=1e-9)  # perpendicular footwall offset
            assert (
                ob.signed_distance(p[None, :])[0] == pytest.approx(20.0, abs=1e-9)
                or abs(v_coord) > ob.half_height
            )


def test_candidates_on_a_level_share_elevation_and_offset_only_u_varies() -> None:
    sc, w, _ev, ts = build()
    ob = w.orebody
    assert isinstance(ob, TabularOrebody)
    max_z_err = max_q_err = 0.0
    for lv in ts.levels:
        locals_ = np.array([ob.to_local(c.position) for c in lv.candidates])
        zs = np.array([c.position[2] for c in lv.candidates])
        max_z_err = max(max_z_err, float(np.abs(zs - lv.elevation).max()))
        q_expected = ob.half_thickness + sc.ramp.footwall_access_offset
        max_q_err = max(max_q_err, float(np.abs(locals_[:, 2] - q_expected).max()))
        assert np.allclose(locals_[:, 1], locals_[0, 1])  # same v on the level
        assert np.allclose(
            np.diff(locals_[:, 0]),
            sc.design.candidate_along_strike_span / (sc.design.candidate_count - 1),
        )
    print(f"\nGATE candidate elevation max error {max_z_err:.2e} m")
    print(f"GATE candidate footwall-offset max error {max_q_err:.2e} m")
    assert max_z_err < 1e-9 and max_q_err < 1e-9


def test_candidates_lie_on_footwall_side() -> None:
    _, w, _, ts = build()
    ob = w.orebody
    dip_dir = azimuth_to_unit_vector(ob.config.strike_deg + 90)
    for lv in ts.levels:
        for c in lv.candidates:
            assert not ob.contains(c.position)
            # horizontally on the side opposite the dip direction of the contact at this level
            contact = c.position - c.footwall_offset * ob.w
            assert float(np.dot(c.position - contact, dip_dir)) < 0


# -- rejection retention (rule 44) -------------------------------------------


def test_rejected_candidates_are_kept_with_reasons() -> None:
    sc = small_scenario(with_fault=True)
    sc.design.candidate_along_strike_span = 320.0  # orebody length 200 → outer ones fall off
    sc, w, _ev, ts = build(sc)
    n_cfg = sc.design.candidate_count
    for lv in ts.levels:
        assert len(lv.candidates) == n_cfg
        outer = [c for c in lv.candidates if abs(c.u_coord) > w.orebody.half_length]
        assert outer and all(
            not c.valid and RejectionReason.OUTSIDE_OREBODY_STRIKE_EXTENT in c.rejection_reasons
            for c in outer
        )
        for c in lv.candidates:
            assert c.valid == (len(c.rejection_reasons) == 0)
            if not c.valid:
                assert c.point_cost_per_m == float("inf")


def test_world_boundary_rejection_is_retained() -> None:
    sc = small_scenario(with_fault=False)
    sc.orebody.center = Point3D(x=200.0, y=20.0, z=-50.0)  # on the +x edge (world ±200)
    sc.design.candidate_along_strike_span = 100.0
    sc, _w, _ev, ts = build(sc)
    reasons = {r for lv in ts.levels for c in lv.candidates for r in c.rejection_reasons}
    assert RejectionReason.OUTSIDE_WORLD in reasons
    assert all(len(lv.candidates) == sc.design.candidate_count for lv in ts.levels)


# -- scores / heuristic (rule 45) ---------------------------------------------


def test_candidate_scores_match_evaluator_and_heuristic_is_admissible_bound() -> None:
    sc, _w, ev, ts = build()
    for lv, nxt in zip(ts.levels, ts.levels[1:], strict=False):
        for c in lv.candidates:
            r = ev.evaluate_points(c.position[None, :])
            assert c.rock_quality == pytest.approx(float(r.rock_quality[0]))
            assert c.fault_penalty == pytest.approx(float(r.fault_penalty[0]))
            if c.valid:
                assert c.point_cost_per_m == pytest.approx(float(r.total_cost_per_m[0]))
            # heuristic: at least the grade-limited length for one sublevel drop
            dz = lv.elevation - nxt.elevation
            bound = abs(dz) * np.sqrt(1 + sc.ramp.max_gradient**2) / sc.ramp.max_gradient
            assert c.next_level_accessibility is not None
            assert c.next_level_accessibility >= bound - 1e-9
    assert all(c.next_level_accessibility is None for c in ts.levels[-1].candidates)


def test_targets_are_deterministic_and_serializable() -> None:
    _, _, _, a = build()
    _, _, _, b = build()
    assert a.to_dict() == b.to_dict()
    d = a.to_dict()
    assert d["nLevels"] == len(d["levels"]) and d["nValid"] + d["nRejected"] == d["nCandidates"]
    import json

    json.dumps(d)  # no NaN/inf on the wire


# -- portal --------------------------------------------------------------------


def test_default_portal_is_on_surface_on_footwall_side_inside_world() -> None:
    sc, w, _, ts = build()
    ob = w.orebody
    assert isinstance(ob, TabularOrebody)
    p = default_portal(sc, ob, w.terrain)
    assert p[2] == pytest.approx(float(w.terrain.sample(p[None, :2])[0]))
    assert abs(p[0]) <= sc.world.size_x / 2 and abs(p[1]) <= sc.world.size_y / 2
    dip_dir = azimuth_to_unit_vector(ob.config.strike_deg + 90)
    assert float(np.dot(p[:2] - ob.center[:2], dip_dir[:2])) < 0  # footwall side
    assert ts.portal_generated and np.array_equal(ts.portal, p)


def test_explicit_portal_is_respected() -> None:
    sc = small_scenario()
    sc.portal = Point3D(x=-150, y=-150, z=100)
    w = generate_world(sc)
    p, gen = resolve_portal(sc, w)
    assert not gen and p.tolist() == [-150, -150, 100]
    assert isinstance(
        generate_access_targets(
            w, sc.design, sc.ramp, 25.0, DesignCostEvaluator(w, sc.design), p, gen
        ),
        AccessTargetSet,
    )
