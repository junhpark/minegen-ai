"""Phase 20C.2A commit A2 — footwall trace, offset development trace and
the curved level-development anchor (directive test A8 + trace contracts).

The A8 fixture is a HALF-ANNULUS footprint (a strongly curved body): its
global principal axis is the x-axis, while the local footwall tangent at a
45-degree entry differs from it by ~45 degrees — exactly the geometry the
old whole-section-PCA anchor got wrong and the curved anchor must get
right. The REMOVED principal-axis backbone is replicated inline below,
purely to MEASURE the divergence (commit A3 deleted it from production:
``build_anchor`` now dispatches every non-TABULAR body to the curved
anchor, and that dispatch is asserted here too)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from minegen.layout.access import (
    LevelDevelopmentAnchor,
    _principal_axis,
    build_anchor,
    build_curved_anchor,
)
from minegen.layout.families import build_footwall_track
from minegen.layout.levels import LevelSections, RequiredLevel
from minegen.layout.sections import (
    SECTION_FOOTWALL_AMBIGUOUS,
    SECTION_TRACE_OFFSET_INVALID,
    TRACE_SMOOTHING_PASSES,
    SectionGeometryError,
    _segments_intersect_any,
    build_footwall_trace,
    build_offset_trace,
    resolve_section_resolution,
    smoothing_allowance,
)

RES = resolve_section_resolution(2.0, 20.0)
LEVEL = RequiredLevel("L01", 0, -50.0)
STANDOFF = 20.0


class ArcOrebody:
    """Half-annulus footprint (r_in <= r <= r_out, y >= 0), duck-typed with
    the u/v/w frame ``build_footwall_track`` reads."""

    u = np.array([1.0, 0.0, 0.0])
    v = np.array([0.0, 0.0, -1.0])
    w = np.array([0.0, 1.0, 0.0])
    center = np.zeros(3)

    def __init__(self, r_in=80.0, r_out=120.0, z_range=(-100.0, 0.0)):
        self.r_in = r_in
        self.r_out = r_out
        self.z_range = z_range

    def bounding_box(self):
        return (
            np.array([-self.r_out, 0.0, self.z_range[0]]),
            np.array([self.r_out, self.r_out, self.z_range[1]]),
        )

    def contains(self, points):
        pts = np.asarray(points, dtype=np.float64)
        r2 = pts[:, 0] ** 2 + pts[:, 1] ** 2
        return (
            (r2 >= self.r_in**2)
            & (r2 <= self.r_out**2)
            & (pts[:, 1] >= 0.0)
            & (pts[:, 2] >= self.z_range[0])
            & (pts[:, 2] <= self.z_range[1])
        )

    def signed_clearance(self, points):
        # vertical-sided body: the 3-D clearance IS the plan signed distance
        pts = np.asarray(points, dtype=np.float64)
        r = np.hypot(pts[:, 0], pts[:, 1])
        return np.maximum(np.maximum(self.r_in - r, r - self.r_out), -pts[:, 1])


class BittenDisc:
    """Disc with a concave bite whose radius is SMALLER than the stand-off:
    a naive per-vertex normal offset would self-intersect there; the EDT
    level set must round it instead."""

    def __init__(self, r=60.0, bite=(60.0, 0.0, 15.0), z_range=(-100.0, 0.0)):
        self.r = r
        self.bite = bite
        self.z_range = z_range

    def bounding_box(self):
        return (
            np.array([-self.r, -self.r, self.z_range[0]]),
            np.array([self.r, self.r, self.z_range[1]]),
        )

    def contains(self, points):
        pts = np.asarray(points, dtype=np.float64)
        bx, by, br = self.bite
        inside = pts[:, 0] ** 2 + pts[:, 1] ** 2 <= self.r**2
        inside &= (pts[:, 0] - bx) ** 2 + (pts[:, 1] - by) ** 2 > br**2
        inside &= (pts[:, 2] >= self.z_range[0]) & (pts[:, 2] <= self.z_range[1])
        return inside

    def signed_clearance(self, points):
        pts = np.asarray(points, dtype=np.float64)
        bx, by, br = self.bite
        d_disc = np.hypot(pts[:, 0], pts[:, 1]) - self.r
        d_bite = br - np.hypot(pts[:, 0] - bx, pts[:, 1] - by)
        return np.maximum(d_disc, d_bite)


def make_sections(ob):
    return LevelSections(ob, [LEVEL], 2.0, resolution=RES)


RAMP_PTS = np.array([[176.0, 176.0, -40.0], [176.0, 176.0, -60.0]])


# --------------------------------------------------------------------------- #
# A8 — curved fixture: local tangent vs global PCA
# --------------------------------------------------------------------------- #


def _removed_pca_anchor(ob, sections, track, ref, standoff):
    """Inline replica of the REMOVED whole-section principal-axis backbone
    (pre-20C.2A ``build_anchor`` else-branch) — kept only to MEASURE how far
    the curved anchor moves; production has no PCA path any more."""
    sec = sections.section(LEVEL)
    axis = _principal_axis(sec.inside_xy, track.u_h)
    normal = np.array([axis[1], -axis[0]])
    if float(normal @ track.w_h) < 0.0:
        normal = -normal
    _, hi_n = sec.extent_along(normal)
    lo_u, hi_u = sec.extent_along(axis)
    edge = sec.centroid + normal * hi_n
    origin = np.array(
        [edge[0] + normal[0] * standoff, edge[1] + normal[1] * standoff, LEVEL.elevation]
    )
    margin = min(5.0, 0.25 * (hi_u - lo_u))
    t = min(max(float((ref[:2] - origin[:2]) @ axis), lo_u + margin), hi_u - margin)
    pos = np.array([origin[0] + axis[0] * t, origin[1] + axis[1] * t, LEVEL.elevation])
    direction = axis if t <= 0.5 * (lo_u + hi_u) else -axis
    heading = math.atan2(float(direction[0]), float(direction[1]))
    return pos, heading


class TestCurvedAnchorVsPca:
    def test_curved_anchor_diverges_from_pca_and_matches_local_geometry(self):
        ob = ArcOrebody()
        sections = make_sections(ob)
        track = build_footwall_track(ob, sections)
        assert track is not None
        ref = np.array([176.0, 176.0, -50.0])
        old_pos, old_heading = _removed_pca_anchor(ob, sections, track, ref, STANDOFF)
        new = build_curved_anchor(
            ob,
            LEVEL,
            sections,
            track.w_h,
            track.u_h,
            RAMP_PTS,
            STANDOFF,
            "LONGHOLE",
            ob.signed_clearance,
            "TEST",
            10.0,
        )
        assert new is not None
        # production dispatch (commit A3): build_anchor itself yields the
        # curved anchor for every non-TABULAR body — the PCA path is gone
        dispatched = build_anchor(
            ob,
            LEVEL,
            sections,
            track,
            RAMP_PTS,
            STANDOFF,
            "LONGHOLE",
            clearance=ob.signed_clearance,
            policy_token="TEST",
            minimum_clearance=10.0,
        )
        assert isinstance(dispatched, LevelDevelopmentAnchor)
        assert dispatched.diagnostics["backbone"] == "SECTION_FOOTWALL_OFFSET_TRACE"
        assert np.allclose(dispatched.position, new.position)

        # measured divergence (directive A8): the PCA anchor puts the entry
        # on the global x-axis backbone; the curved anchor follows the arc
        position_diff = float(np.linalg.norm(old_pos - new.position))
        assert position_diff > 30.0
        axis_mismatch = abs(
            math.degrees(
                math.asin(
                    abs(math.sin(new.heading - old_heading))  # heading AXIS difference, mod 180
                )
            )
        )
        assert axis_mismatch > 20.0

        # the new entry sits on the offset arc at r_out + the CONSTRUCTION
        # stand-off (stand-off + the derived smoothing allowance; on this
        # gentle 146 m-radius arc the smoothing itself moves it < 1 m),
        # near the ramp reference's 45-degree azimuth, with the analytic
        # arc tangent
        construction = STANDOFF + smoothing_allowance(
            STANDOFF, RES.base_standoff, TRACE_SMOOTHING_PASSES
        )
        r_entry = float(np.hypot(new.position[0], new.position[1]))
        assert r_entry == pytest.approx(120.0 + construction, abs=3.0)
        phi = math.atan2(float(new.position[1]), float(new.position[0]))
        assert math.degrees(phi) == pytest.approx(45.0, abs=8.0)
        arc_tangent = np.array([-math.sin(phi), math.cos(phi)])
        cosang = abs(float(np.clip(new.local_tangent @ arc_tangent, -1.0, 1.0)))
        assert math.degrees(math.acos(cosang)) < 10.0

        # ore contact: nearest contact-trace vertex on the outer arc
        assert new.ore_contact is not None
        r_contact = float(np.hypot(new.ore_contact[0], new.ore_contact[1]))
        assert r_contact == pytest.approx(120.0, abs=3.0)
        d_contact = float(np.linalg.norm(new.ore_contact[:2] - new.position[:2]))
        assert d_contact == pytest.approx(construction, abs=2.0 * RES.effective_spacing)
        # inward local normal points from the entry toward the ore
        assert new.local_normal is not None
        assert float(new.local_normal @ (new.ore_contact[:2] - new.position[:2])) > 0.0

        # payload contract of the curved anchor
        d = new.to_dict()
        assert d["traceChainage"] is not None and d["traceLength"] is not None
        assert 0.0 < d["traceChainage"] < d["traceLength"]
        assert d["selectedComponentId"] == 1
        assert d["sectionSamplingSpacing"] == 2.0
        assert d["sectionEffectiveSpacing"] == RES.effective_spacing
        assert d["diagnostics"]["backbone"] == "SECTION_FOOTWALL_OFFSET_TRACE"
        assert d["diagnostics"]["localTangentVsGlobalPcaDeg"] > 25.0

    def test_heading_points_toward_longer_trace_side(self):
        ob = ArcOrebody()
        sections = make_sections(ob)
        new = build_curved_anchor(
            ob,
            LEVEL,
            sections,
            np.array([0.0, 1.0]),
            np.array([1.0, 0.0]),
            RAMP_PTS,
            STANDOFF,
            "LONGHOLE",
            ob.signed_clearance,
            "TEST",
            10.0,
        )
        assert new is not None
        t = new.trace_chainage
        length = new.trace_length
        assert t is not None and length is not None
        forward = length - t
        expected = new.local_tangent if forward >= t else -new.local_tangent
        az = math.atan2(float(expected[0]), float(expected[1]))
        assert new.heading == pytest.approx(az, abs=1e-12)


# --------------------------------------------------------------------------- #
# Footwall side selection and typed failures
# --------------------------------------------------------------------------- #


class TestFootwallTrace:
    def test_seed_selects_the_side(self):
        ob = ArcOrebody()
        sections = make_sections(ob)
        geom = sections.geometry(LEVEL)
        outer = build_footwall_trace(ob, geom, RES, np.array([0.0, 1.0]))
        inner = build_footwall_trace(ob, geom, RES, np.array([0.0, -1.0]))
        r_outer = np.hypot(outer.contact_points[:, 0], outer.contact_points[:, 1])
        assert float(np.median(r_outer)) > 100.0  # the r=120 contact arc
        # the opposite seed picks the inner-side boundary (inner arc / flats)
        r_inner = np.hypot(inner.contact_points[:, 0], inner.contact_points[:, 1])
        assert float(np.median(r_inner)) < 100.0
        # outward normals verified against contains(): probing outward from
        # the outer trace must leave the body
        probe = outer.contact_points[:, :2] + 3.0 * outer.outward_normals
        z = np.full(probe.shape[0], LEVEL.elevation)
        assert not ob.contains(np.column_stack([probe, z])).any()

    def test_sub_resolution_body_is_ambiguous_never_pca(self):
        # a single-occupancy-cell blob: its contour exists but no footwall-
        # side run reaches the MIN_FOOTWALL_RUN_SPACINGS floor — the typed
        # failure fires instead of any PCA fallback
        class TinyBlob:
            def bounding_box(self):
                return (np.array([-0.5, -0.5, -100.0]), np.array([0.5, 0.5, 0.0]))

            def contains(self, points):
                pts = np.asarray(points, dtype=np.float64)
                return (
                    (np.hypot(pts[:, 0], pts[:, 1]) <= 0.5)
                    & (pts[:, 2] >= -100.0)
                    & (pts[:, 2] <= 0.0)
                )

        ob = TinyBlob()
        sections = LevelSections(ob, [LEVEL], 2.0, resolution=RES)
        with pytest.raises(SectionGeometryError) as ei:
            sections.footwall_trace(LEVEL, np.array([0.0, 1.0]))
        assert ei.value.code == SECTION_FOOTWALL_AMBIGUOUS
        # the failure is cached and re-raised deterministically
        with pytest.raises(SectionGeometryError) as ei2:
            sections.footwall_trace(LEVEL, np.array([0.0, 1.0]))
        assert ei2.value is ei.value


class TestOffsetTrace:
    def test_concave_bite_rounds_instead_of_self_intersecting(self):
        ob = BittenDisc()  # bite radius 15 < stand-off 20
        sections = LevelSections(ob, [LEVEL], 2.0, resolution=RES)
        off = sections.offset_trace(
            LEVEL, np.array([1.0, 0.0]), STANDOFF, 10.0, ob.signed_clearance, "TEST", 10.0
        )
        assert off.total_length > 50.0
        assert bool(np.isfinite(off.points).all())
        assert not _segments_intersect_any(off.points[:, :2])
        # never materially closer to the contact than the stand-off
        assert float(off.ore_contact_distance.min()) >= STANDOFF - 2.0 * RES.effective_spacing
        # and never inside the body
        assert not ob.contains(off.points).any()

    def test_minimum_length_is_typed(self):
        ob = ArcOrebody()
        sections = make_sections(ob)
        geom = sections.geometry(LEVEL)
        trace = build_footwall_trace(ob, geom, RES, np.array([0.0, 1.0]))
        with pytest.raises(SectionGeometryError) as ei:
            build_offset_trace(geom, trace, RES, STANDOFF, 10_000.0, ob.signed_clearance, 10.0)
        assert ei.value.code == SECTION_TRACE_OFFSET_INVALID
        assert "shorter than" in ei.value.detail

    def test_planning_standoff_floor_is_a_hard_gate(self):
        """PR #24 follow-up §2: a smoothed trace that keeps the engineering
        minimum-clearance floor but sits materially closer to the footwall
        contact than the PLANNING stand-off fails typed — the docstring
        contract is enforced, not just reported. Fixture: a clearance
        measure inflated +14 m over the true plan distance, so the level
        set at the construction stand-off lands ~14 m closer in plan than
        intended — below the stand-off floor (20 - 2 x spacing) — while the
        measured clearance stays far above the small engineering floor
        (both gates are separate contracts; the engineering gate must NOT
        be the one firing here)."""
        ob = ArcOrebody()
        sections = make_sections(ob)
        geom = sections.geometry(LEVEL)
        trace = build_footwall_trace(ob, geom, RES, np.array([0.0, 1.0]))

        def inflated(pts):
            return ob.signed_clearance(pts) + 14.0

        with pytest.raises(SectionGeometryError) as ei:
            build_offset_trace(geom, trace, RES, STANDOFF, 10.0, inflated, 5.0)
        assert ei.value.code == SECTION_TRACE_OFFSET_INVALID
        assert "planning stand-off floor" in ei.value.detail

    def test_determinism_and_cache(self):
        ob = ArcOrebody()
        a = make_sections(ob).offset_trace(
            LEVEL, np.array([0.0, 1.0]), STANDOFF, 10.0, ob.signed_clearance, "TEST", 10.0
        )
        sections_b = make_sections(ob)
        b = sections_b.offset_trace(
            LEVEL, np.array([0.0, 1.0]), STANDOFF, 10.0, ob.signed_clearance, "TEST", 10.0
        )
        assert np.array_equal(a.points, b.points)
        assert np.array_equal(a.tangents, b.tangents)
        assert np.array_equal(a.ore_contact, b.ore_contact)
        assert a.total_length == b.total_length
        assert (
            sections_b.offset_trace(
                LEVEL, np.array([0.0, 1.0]), STANDOFF, 10.0, ob.signed_clearance, "TEST", 10.0
            )
            is b
        )

    def test_orientation_follows_footwall_trace_chainage(self):
        ob = ArcOrebody()
        sections = make_sections(ob)
        trace = sections.footwall_trace(LEVEL, np.array([0.0, 1.0]))
        off = sections.offset_trace(
            LEVEL, np.array([0.0, 1.0]), STANDOFF, 10.0, ob.signed_clearance, "TEST", 10.0
        )
        # start of the offset trace maps near the start of the contact trace
        d_start = float(np.linalg.norm(off.ore_contact[0] - trace.contact_points[0]))
        d_end = float(np.linalg.norm(off.ore_contact[-1] - trace.contact_points[-1]))
        assert d_start < 0.25 * trace.total_length
        assert d_end < 0.25 * trace.total_length
