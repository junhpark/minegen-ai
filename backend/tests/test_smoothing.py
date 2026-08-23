"""Phase 05 gate tests: smoothing + full revalidation (rules 61–64)."""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest

from minegen.core.coordinates import wrap_angle_rad
from minegen.core.models import Point3D, RestrictedZone
from minegen.design.cost_field import DesignCostEvaluator
from minegen.design.mine_designer import ChainedDeclineGenerator
from minegen.design.motion_primitives import Pose, PrimitiveSet, Steering
from minegen.design.smoothing import (
    DeclineSmoother,
    SegmentReport,
    blended_tangents,
    boundary_grades,
    build_curve,
    control_grid,
    distance_to_polyline,
    feasible_controls,
    polyline_arclength,
    segments_from_decline_payload,
    simplify_primitives,
    smooth_control_points,
)
from minegen.design.targets import generate_access_targets, resolve_portal
from minegen.world.synthetic_world import generate_world
from tests.conftest import small_scenario


@pytest.fixture(scope="module")
def smoothed():  # type: ignore[no-untyped-def]
    """Small-scenario chain: decline (all levels) → DeclineSmoother."""
    sc = small_scenario(with_fault=True)
    sc.design.candidate_count = 1
    sc.design.search.max_expansions_per_candidate = 20000
    w = generate_world(sc)
    ev = DesignCostEvaluator(w, sc.design)
    portal, gen = resolve_portal(sc, w)
    ts = generate_access_targets(
        w, sc.design, sc.ramp, sc.mining.sublevel_interval, ev, portal, gen
    )
    res = ChainedDeclineGenerator(ev, sc.ramp, sc.design.search).generate(ts)
    payload = res.to_dict()
    smoother = DeclineSmoother(ev, sc.ramp, sc.design.smoothing)
    return sc, ev, payload, smoother, smoother.smooth(payload)


def _ps(sc) -> PrimitiveSet:  # type: ignore[no-untyped-def]
    return PrimitiveSet(
        min_turn_radius=sc.ramp.min_turn_radius,
        heading_bins=16,
        max_gradient=sc.ramp.max_gradient,
        grade_fractions=(0.0, 0.5, 1.0),
        max_sample_spacing=2.0,
    )


# -- 1. lossless simplification ------------------------------------------------


def test_simplification_is_lossless(smoothed) -> None:  # type: ignore[no-untyped-def]
    sc, *_ = smoothed
    ps = _ps(sc)
    rng = np.random.default_rng(7)
    for _ in range(25):
        pose = Pose(*rng.uniform(-50, 50, 3), float(rng.uniform(-math.pi, math.pi)))
        prims = []
        for _ in range(int(rng.integers(4, 20))):
            st = Steering(int(rng.integers(-1, 2)))
            g = float(rng.choice([0.0, -0.06, -0.12]))
            prim = ps.primitive(pose, st, float(st) / 18.0, g, ps.horizontal_length)
            prims.append(prim)
            pose = prim.end
        merged = simplify_primitives(prims, ps)
        assert len(merged) <= len(prims)
        # equal (curvature, grade) runs collapse to a single primitive
        for a, b in itertools.pairwise(merged):
            assert (a.curvature, a.grade) != (b.curvature, b.grade)
        assert np.linalg.norm(merged[-1].end.position - prims[-1].end.position) < 1e-9
        assert abs(wrap_angle_rad(merged[-1].end.heading - prims[-1].end.heading)) < 1e-9
        la = sum(p.length_3d for p in prims)
        lb = sum(p.length_3d for p in merged)
        assert abs(la - lb) / la < 1e-9


# -- 2/3/4/5. pose preservation, connections, boundary tangents, status --------


def test_all_segments_smoothed_and_valid(smoothed) -> None:  # type: ignore[no-untyped-def]
    *_, result = smoothed
    assert result.status == "SUCCESS"
    for seg in result.segments:
        assert seg.effective_source == "SMOOTHED"
        r = seg.report
        assert r.valid and r.invalid_sample_count == 0
        assert r.grade_violations == 0 and r.monotonicity_violations == 0
        assert r.radius_violations == 0 and r.corridor_violations == 0


def test_endpoints_and_headings_exact(smoothed) -> None:  # type: ignore[no-untyped-def]
    *_, result = smoothed
    for seg in result.segments:
        eff = seg.effective_points
        assert np.linalg.norm(eff[0] - seg.raw_points[0]) < 1e-6
        assert np.linalg.norm(eff[-1] - seg.raw_points[-1]) < 1e-6
        assert seg.report.endpoint_position_error < 1e-6
        assert seg.report.start_heading_error_deg < math.degrees(1e-6)
        assert seg.report.end_heading_error_deg < math.degrees(1e-6)


def test_segment_connections_and_shared_boundary_tangent(smoothed) -> None:  # type: ignore[no-untyped-def]
    sc, _, payload, smoother, result = smoothed
    # position continuity: each segment starts exactly where the previous ended
    for a, b in zip(result.segments, result.segments[1:], strict=False):
        assert np.linalg.norm(a.effective_points[-1] - b.effective_points[0]) < 1e-6
        # rule 61: adjacent segments share one 3D boundary tangent
        assert np.allclose(a.end_tangent, b.start_tangent, atol=1e-12)
    # the shared grade is the clamped mean of the adjacent raw local grades
    segs = segments_from_decline_payload(payload, smoother.ps)
    grades = boundary_grades(segs, sc.ramp.max_gradient)
    for i in range(len(segs) - 1):
        expected = (segs[i].last_grade + segs[i + 1].first_grade) / 2.0
        expected = min(0.0, max(-sc.ramp.max_gradient, expected))
        assert grades[i][1] == pytest.approx(expected, abs=1e-12)
        assert grades[i + 1][0] == pytest.approx(expected, abs=1e-12)


def test_effective_centerline_monotonic_grade_radius_corridor(smoothed) -> None:  # type: ignore[no-untyped-def]
    sc, *_, result = smoothed
    tol_g = sc.design.smoothing.grade_numerical_tolerance
    for seg in result.segments:
        eff = seg.effective_points
        dz = np.diff(eff[:, 2])
        assert (dz <= 1e-9).all()  # rule 49 preserved on the final curve
        assert seg.report.max_gradient <= sc.ramp.max_gradient + tol_g
        assert seg.report.min_plan_radius is not None
        assert (
            seg.report.min_plan_radius
            >= sc.ramp.min_turn_radius - sc.design.smoothing.radius_numerical_tolerance
        )
        assert seg.report.max_deviation_from_raw <= sc.design.smoothing.max_deviation_from_raw
        assert distance_to_polyline(eff, seg.raw_points).max() <= (
            sc.design.smoothing.max_deviation_from_raw + 1e-9
        )


def test_field_cost_within_cap(smoothed) -> None:  # type: ignore[no-untyped-def]
    sc, *_, result = smoothed
    cap = sc.design.smoothing.max_field_cost_increase_pct
    for seg in result.segments:
        assert seg.report.field_cost_delta_pct is not None
        assert seg.report.field_cost_delta_pct <= cap + 1e-9


def test_report_json_is_finite(smoothed) -> None:  # type: ignore[no-untyped-def]
    *_, result = smoothed
    import json

    text = json.dumps(result.to_dict())
    assert "NaN" not in text and "Infinity" not in text
    totals = result.to_dict()["totals"]
    assert totals["segments"] == totals["smoothedSegments"] and totals["fallbackSegments"] == 0


# -- 7/8. grade & XY plan radius validators on synthetic curves ----------------


def test_plan_radius_is_measured_in_xy(smoothed) -> None:  # type: ignore[no-untyped-def]
    """A descending helix arc has 3D curvature < plan curvature; rule 62
    requires plan view. The measured plan radius must match the raw arc radius,
    not the (larger) 3D circumradius."""
    sc, _ev, *_ = smoothed
    ps = _ps(sc)
    arc = ps.primitive(Pose(0.0, 0.0, 0.0, 0.0), Steering.RIGHT, 1.0 / 18.0, -0.12, 18.0 * math.pi)
    simplified = simplify_primitives([arc], ps)
    rc, rt = control_grid(simplified, 5.0, arc.samples[-1])
    curve = build_curve(rc, 0.0, arc.end.heading, -0.12, -0.12, tangents_xy=rt, max_gradient=0.12)
    sq = np.linspace(0.0, float(curve.s[-1]), 800)
    radius = 1.0 / np.maximum(curve.plan_curvature(sq), 1e-12)
    # the 3D circumradius of this helix is 18·(1+g²) ≈ 18.26; plan view is 18
    assert float(radius.min()) >= 17.95 and float(radius.max()) <= 18.26 - 0.15
    grades = curve.grades(sq)
    assert float(np.abs(grades).max()) <= 0.12 + sc.design.smoothing.grade_numerical_tolerance
    assert float(grades.max()) <= sc.design.smoothing.grade_numerical_tolerance


# -- 10/11. corner-cutting detection via the shared validator ------------------


def _corner_setup(smoothed):  # type: ignore[no-untyped-def]
    """A flat right-angle corner path; deliberately displaced controls cut the
    corner so exclusion checks must fire."""
    sc, ev, *_ = smoothed
    ps = _ps(sc)
    a = ps.primitive(Pose(-140.0, -140.0, -60.0, 0.0), Steering.STRAIGHT, 0.0, 0.0, 60.0)
    b = ps.primitive(a.end, Steering.RIGHT, 1.0 / 18.0, 0.0, 18.0 * math.pi / 2)
    c = ps.primitive(b.end, Steering.STRAIGHT, 0.0, 0.0, 60.0)
    prims = [a, b, c]
    dense = np.vstack([a.samples, b.samples[1:], c.samples[1:]])
    simplified = simplify_primitives(prims, ps)
    rc, rt = control_grid(simplified, 5.0, dense[-1])
    cut = rc.copy()
    inner = np.array([b.end.position[0] - 12.0, a.end.position[1] + 6.0])
    for i in range(2, len(cut) - 2):
        d = inner - cut[i, :2]
        n = float(np.linalg.norm(d))
        if 0 < n < 30.0:
            cut[i, :2] += d / n * min(6.0, n)  # pull the corner region inward
    return sc, ev, prims, dense, rc, rt, cut, c.end.heading


def test_restricted_zone_corner_cut_is_detected(smoothed) -> None:  # type: ignore[no-untyped-def]
    sc, ev0, prims, dense, rc, rt, cut, end_heading = _corner_setup(smoothed)
    design = sc.design.model_copy(deep=True)
    corner = prims[1].end.position
    cx, cy = float(corner[0]) - 10.0, float(prims[0].end.position[1]) + 6.0
    design.restricted_zones = [
        RestrictedZone(
            min=Point3D(x=cx - 4.0, y=cy - 4.0, z=-80.0),
            max=Point3D(x=cx + 4.0, y=cy + 4.0, z=-40.0),
        )
    ]
    ev = DesignCostEvaluator(ev0.world, design)
    smoother = DeclineSmoother(ev, sc.ramp, sc.design.smoothing)
    curve = build_curve(
        cut,
        0.0,
        end_heading,
        0.0,
        0.0,
        tangents_xy=blended_tangents(rc, cut, rt),
        max_gradient=sc.ramp.max_gradient,
    )
    report = SegmentReport()
    violations = smoother.segment_smoother.validate_curve(
        curve, dense, report, cover_established=True
    )
    assert violations.any
    assert report.invalid_sample_count > 0
    assert "RESTRICTED_ZONE" in report.rejection_reason_counts
    # the raw path itself stays clean under the same validator
    raw_curve = build_curve(
        rc, 0.0, end_heading, 0.0, 0.0, tangents_xy=rt, max_gradient=sc.ramp.max_gradient
    )
    raw_report = SegmentReport()
    raw_viol = smoother.segment_smoother.validate_curve(
        raw_curve, dense, raw_report, cover_established=True
    )
    assert not raw_viol.any and raw_report.invalid_sample_count == 0


def test_orebody_buffer_corner_cut_is_detected(smoothed) -> None:  # type: ignore[no-untyped-def]
    """Same displaced-corner construction, but the exclusion is the orebody
    hard buffer: place the corner beside the orebody so the cut enters it."""
    sc, ev, *_ = smoothed
    ps = _ps(sc)
    # find a point just outside the hard buffer and aim the cut inside it
    center = sc.orebody.center
    start = Pose(center.x - 120.0, center.y - 60.0, center.z, math.atan2(1.0, 0.0))
    a = ps.primitive(start, Steering.STRAIGHT, 0.0, 0.0, 80.0)
    b = ps.primitive(a.end, Steering.STRAIGHT, 0.0, 0.0, 80.0)
    dense = np.vstack([a.samples, b.samples[1:]])
    simplified = simplify_primitives([a, b], ps)
    rc, rt = control_grid(simplified, 5.0, dense[-1])
    towards = np.array([center.x, center.y]) - rc[len(rc) // 2, :2]
    towards /= np.linalg.norm(towards)
    cut = rc.copy()
    for i in range(2, len(cut) - 2):
        cut[i, :2] += towards * 60.0  # push the middle into the orebody buffer
        cut[i, 2] = center.z
    smoother = DeclineSmoother(ev, sc.ramp, sc.design.smoothing)
    curve = build_curve(
        cut,
        start.heading,
        b.end.heading,
        0.0,
        0.0,
        tangents_xy=blended_tangents(rc, cut, rt),
        max_gradient=sc.ramp.max_gradient,
    )
    report = SegmentReport()
    violations = smoother.segment_smoother.validate_curve(
        curve, dense, report, cover_established=True
    )
    assert violations.any and report.invalid_sample_count > 0
    assert "OREBODY_BUFFER" in report.rejection_reason_counts


# -- 13/14/15/16. cost cap, deterministic repair, fallback, FAILED -------------


def test_field_cost_cap_forces_explicit_fallback(smoothed) -> None:  # type: ignore[no-untyped-def]
    """With a zero-increase cap and no repair budget, any measurable field-cost
    increase must yield an explicit RAW_FALLBACK (never a silently invalid
    smoothed curve)."""
    sc, ev, payload, _smoother, _ = smoothed
    cfg = sc.design.smoothing.model_copy(deep=True)
    cfg.max_repairs = 0
    cfg.max_field_cost_increase_pct = 0.0
    strict = DeclineSmoother(ev, sc.ramp, cfg)
    result = strict.smooth(payload)
    assert result.status in ("SUCCESS", "SUCCESS_WITH_FALLBACK", "FAILED")
    assert result.status != "FAILED"
    fallbacks = [s for s in result.segments if s.effective_source == "RAW_FALLBACK"]
    assert fallbacks, "zero cost cap with zero repairs must force at least one fallback"
    for seg in fallbacks:
        assert seg.report.fallback_reason  # explicit, never silent (rule 63)
        assert seg.report.valid  # the raw centerline itself is revalidated
        assert np.allclose(seg.effective_points, seg.raw_points)
        # smoothed payload is null in the artifact
        assert seg.to_dict()["smoothed"] is None
        assert seg.to_dict()["effectiveCenterline"]["pointCount"] == len(seg.raw_points)


def test_repairs_are_deterministic(smoothed) -> None:  # type: ignore[no-untyped-def]
    sc, ev, payload, *_ = smoothed
    a = DeclineSmoother(ev, sc.ramp, sc.design.smoothing).smooth(payload)
    b = DeclineSmoother(ev, sc.ramp, sc.design.smoothing).smooth(payload)
    assert a.status == b.status
    for sa, sb in zip(a.segments, b.segments, strict=True):
        assert sa.effective_source == sb.effective_source
        assert sa.report.repairs == sb.report.repairs
        assert np.array_equal(sa.effective_points, sb.effective_points)


def test_invalid_raw_input_fails_not_fallback(smoothed) -> None:  # type: ignore[no-untyped-def]
    """Rule 63: if the raw centerline itself fails revalidation the phase is
    FAILED — a fallback would launder an invalid path as validated."""
    sc, ev0, payload, *_ = smoothed
    design = sc.design.model_copy(deep=True)
    first = payload["levels"][0]
    cand = next(
        c for c in first["candidateResults"] if c["candidateId"] == first["selectedCandidateId"]
    )
    pts = np.asarray(cand["path"]["points"], dtype=np.float64).reshape(-1, 3)
    mid = pts[len(pts) // 2]
    design.restricted_zones = [
        RestrictedZone(
            min=Point3D(x=float(mid[0]) - 5.0, y=float(mid[1]) - 5.0, z=float(mid[2]) - 5.0),
            max=Point3D(x=float(mid[0]) + 5.0, y=float(mid[1]) + 5.0, z=float(mid[2]) + 5.0),
        )
    ]
    ev = DesignCostEvaluator(ev0.world, design)
    result = DeclineSmoother(ev, sc.ramp, sc.design.smoothing).smooth(payload)
    assert result.status == "FAILED"
    assert result.failure_reason and "raw segment" in result.failure_reason


# -- feasibility projection sanity --------------------------------------------


def test_feasible_controls_is_identity_when_unconstrained(smoothed) -> None:  # type: ignore[no-untyped-def]
    sc, *_ = smoothed
    ps = _ps(sc)
    stra = ps.primitive(Pose(0.0, 0.0, 0.0, 0.3), Steering.STRAIGHT, 0.0, -0.03, 300.0)
    simplified = simplify_primitives([stra], ps)
    rc, rt = control_grid(simplified, 5.0, stra.samples[-1])
    sm = smooth_control_points(rc, stra.samples, sc.design.smoothing)
    out = feasible_controls(rc, sm, rt, 0.3, stra.end.heading, -0.03, -0.03, 0.12, 18.0)
    assert np.array_equal(out, sm)  # a shallow straight has full slack


def test_polyline_arclength_monotone(smoothed) -> None:  # type: ignore[no-untyped-def]
    pts = np.array([[0.0, 0.0, 0.0], [3.0, 4.0, 0.0], [3.0, 4.0, 5.0]])
    s = polyline_arclength(pts)
    assert s.tolist() == [0.0, 5.0, 10.0]
