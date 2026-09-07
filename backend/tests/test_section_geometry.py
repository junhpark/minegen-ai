"""Phase 20C.2A commit A1 — authoritative section(z) geometry contract
(directive tests A9 multi-component and A10 resolution/determinism).

The stubs below are duck-typed footprint solids (union of vertical
cylinders minus hole cylinders): ``contains`` is the only membership
authority the module may consult, so a stub exercises the contract exactly
as an implicit orebody would."""

from __future__ import annotations

import math

import numpy as np
import pytest

from minegen.layout.levels import LevelSections, RequiredLevel
from minegen.layout.sections import (
    SECTION_MAX_GRID_CELLS_PER_LEVEL,
    SECTION_MAX_GRID_CELLS_TOTAL,
    SECTION_RESOLUTION_BUDGET_EXCEEDED,
    SECTION_STANDOFF_NONPOSITIVE,
    SECTION_TRACE_SAMPLES_PER_STANDOFF,
    SectionGeometryError,
    build_section_geometry,
    projected_grid_shape,
    resolve_section_resolution,
    validate_section_budgets,
)


class FootprintOrebody:
    """Duck-typed Orebody: union of vertical cylinders minus holes."""

    def __init__(self, discs, holes=(), z_range=(-100.0, 0.0)):
        self.discs = list(discs)  # (cx, cy, r)
        self.holes = list(holes)
        self.z_range = z_range

    def bounding_box(self):
        lo_x = min(c - r for c, _, r in self.discs)
        hi_x = max(c + r for c, _, r in self.discs)
        lo_y = min(c - r for _, c, r in self.discs)
        hi_y = max(c + r for _, c, r in self.discs)
        return (
            np.array([lo_x, lo_y, self.z_range[0]]),
            np.array([hi_x, hi_y, self.z_range[1]]),
        )

    def contains(self, points):
        pts = np.asarray(points, dtype=np.float64)
        inside = np.zeros(pts.shape[0], dtype=bool)
        for cx, cy, r in self.discs:
            inside |= (pts[:, 0] - cx) ** 2 + (pts[:, 1] - cy) ** 2 <= r * r
        for cx, cy, r in self.holes:
            inside &= (pts[:, 0] - cx) ** 2 + (pts[:, 1] - cy) ** 2 > r * r
        inside &= (pts[:, 2] >= self.z_range[0]) & (pts[:, 2] <= self.z_range[1])
        return inside


RES_DEFAULT = resolve_section_resolution(2.0, 20.0)


def shoelace(loop):
    x, y = loop[:, 0], loop[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


# --------------------------------------------------------------------------- #
# A10 — resolution contract
# --------------------------------------------------------------------------- #


class TestResolutionContract:
    def test_default_needs_no_refinement(self):
        res = resolve_section_resolution(2.0, 20.0)
        assert res.refinement_factor == 1
        assert res.effective_spacing == 2.0
        assert res.effective_spacing <= 20.0 / SECTION_TRACE_SAMPLES_PER_STANDOFF

    def test_refinement_is_power_of_two_only(self):
        # target 1.0 → one halving
        res = resolve_section_resolution(2.0, 4.0)
        assert (res.refinement_factor, res.effective_spacing) == (2, 1.0)
        # target 0.75 → 2.0/2 = 1.0 is not enough, 2.0/4 = 0.5 is; /3 is
        # never considered (nested power-of-two grids only)
        res = resolve_section_resolution(2.0, 3.0)
        assert (res.refinement_factor, res.effective_spacing) == (4, 0.5)
        assert res.effective_spacing <= 3.0 / SECTION_TRACE_SAMPLES_PER_STANDOFF

    @pytest.mark.parametrize("standoff", [0.0, -5.0])
    def test_nonpositive_standoff_fails_closed(self, standoff):
        with pytest.raises(SectionGeometryError) as ei:
            resolve_section_resolution(2.0, standoff)
        assert ei.value.code == SECTION_STANDOFF_NONPOSITIVE

    def test_per_level_budget_checked_before_allocation(self):
        # 4000 m square footprint at 2 m ≈ 2001² > 2 M cells / level
        big = FootprintOrebody([(0.0, 0.0, 2000.0)])
        _, _, nx, ny = projected_grid_shape(big, RES_DEFAULT.effective_spacing)
        assert nx * ny > SECTION_MAX_GRID_CELLS_PER_LEVEL
        with pytest.raises(SectionGeometryError) as ei:
            validate_section_budgets(big, RES_DEFAULT, 1)
        assert ei.value.code == SECTION_RESOLUTION_BUDGET_EXCEEDED
        with pytest.raises(SectionGeometryError) as ei2:
            build_section_geometry(big, "L01", -50.0, RES_DEFAULT)
        assert ei2.value.code == SECTION_RESOLUTION_BUDGET_EXCEEDED

    def test_total_budget_over_all_levels(self):
        # ≈ 1.006 M cells / level: 15 levels fit the 16 M total, 16 do not
        ob = FootprintOrebody([(1000.0, 1000.0, 1000.0)], z_range=(-200.0, 0.0))
        _, _, nx, ny = projected_grid_shape(ob, RES_DEFAULT.effective_spacing)
        per_level = nx * ny
        assert per_level <= SECTION_MAX_GRID_CELLS_PER_LEVEL
        assert 15 * per_level <= SECTION_MAX_GRID_CELLS_TOTAL < 16 * per_level
        diag = validate_section_budgets(ob, RES_DEFAULT, 15)
        assert diag["totalCells"] == 15 * per_level
        levels = [RequiredLevel(f"L{i:02d}", i, -10.0 * (i + 1)) for i in range(16)]
        with pytest.raises(SectionGeometryError) as ei:
            LevelSections(ob, levels, 2.0, resolution=RES_DEFAULT)
        assert ei.value.code == SECTION_RESOLUTION_BUDGET_EXCEEDED
        # the failure is decided upfront from the projected shape — the
        # diagnostics carry the projected totals, proving no grid was built
        assert ei.value.diagnostics["totalCells"] == 16 * per_level

    def test_determinism_same_input_same_geometry(self):
        ob = FootprintOrebody([(10.0, -20.0, 33.0), (95.0, 40.0, 17.0)])
        a = build_section_geometry(ob, "L01", -50.0, RES_DEFAULT)
        b = build_section_geometry(ob, "L01", -50.0, RES_DEFAULT)
        assert np.array_equal(a.occupancy, b.occupancy)
        assert np.array_equal(a.selected_mask, b.selected_mask)
        assert np.array_equal(a.outer_contour_xy, b.outer_contour_xy)
        assert a.payload() == b.payload()

    def test_refined_grid_measures_the_same_footprint(self):
        ob = FootprintOrebody([(0.0, 0.0, 30.0)])
        coarse = build_section_geometry(ob, "L01", -50.0, RES_DEFAULT)
        fine = build_section_geometry(ob, "L01", -50.0, resolve_section_resolution(2.0, 4.0))
        assert fine.spacing == 1.0 and fine.refinement_factor == 2
        area = math.pi * 30.0**2
        for g in (coarse, fine):
            assert g.components[0].area_proxy == pytest.approx(area, rel=0.05)
        # the finer proxy is the tighter one
        assert abs(fine.components[0].area_proxy - area) <= abs(
            coarse.components[0].area_proxy - area
        )

    def test_elevation_outside_bbox_is_empty(self):
        ob = FootprintOrebody([(0.0, 0.0, 30.0)], z_range=(-100.0, -10.0))
        g = build_section_geometry(ob, "L01", 5.0, RES_DEFAULT)
        assert g.empty and g.component_count == 0
        assert g.outer_contour_xy.shape == (0, 2)


# --------------------------------------------------------------------------- #
# A9 — multi-component sections
# --------------------------------------------------------------------------- #


class TestMultiComponent:
    def test_dominant_component_selected_ignored_recorded_never_merged(self):
        ob = FootprintOrebody([(0.0, 0.0, 30.0), (120.0, 10.0, 15.0)])
        g = build_section_geometry(ob, "L01", -50.0, RES_DEFAULT)
        assert g.component_count == 2
        selected, ignored = g.components[0], g.components[1]
        assert g.selected_component_id == selected.component_id
        assert selected.sample_count > ignored.sample_count
        assert selected.centroid_xy == pytest.approx((0.0, 0.0), abs=0.5)
        # the ignored component stays fully recorded (never deleted) …
        assert ignored.sample_count > 0
        assert ignored.centroid_xy == pytest.approx((120.0, 10.0), abs=0.5)
        # … and is never merged into the selection
        assert int(g.selected_mask.sum()) == selected.sample_count
        assert int(g.occupancy.sum()) == selected.sample_count + ignored.sample_count
        # the outer contour belongs to the dominant component only
        assert abs(shoelace(g.outer_contour_xy)) == pytest.approx(math.pi * 30.0**2, rel=0.05)
        assert np.all(g.outer_contour_xy[:, 0] < 60.0)

    def test_tie_break_centroid_x_then_y(self):
        # identical discs centred on grid points → identical sample counts
        gx = build_section_geometry(
            FootprintOrebody([(100.0, 0.0, 15.0), (0.0, 0.0, 15.0)]), "L01", -50.0, RES_DEFAULT
        )
        c0, c1 = gx.components
        assert c0.sample_count == c1.sample_count
        assert c0.centroid_xy[0] < c1.centroid_xy[0]
        gy = build_section_geometry(
            FootprintOrebody([(0.0, 100.0, 15.0), (0.0, 0.0, 15.0)]), "L01", -50.0, RES_DEFAULT
        )
        c0, c1 = gy.components
        assert c0.sample_count == c1.sample_count
        assert c0.centroid_xy[0] == pytest.approx(c1.centroid_xy[0], abs=1e-9)
        assert c0.centroid_xy[1] < c1.centroid_xy[1]

    def test_components_are_4_connected(self):
        # two discs touching only diagonally at grid scale stay separate
        # under 4-connectivity: build a footprint from two offset squares
        class Checker(FootprintOrebody):
            def contains(self, points):
                pts = np.asarray(points, dtype=np.float64)
                a = (
                    (pts[:, 0] >= 0.0)
                    & (pts[:, 0] <= 10.0)
                    & (pts[:, 1] >= 0.0)
                    & (pts[:, 1] <= 10.0)
                )
                b = (
                    (pts[:, 0] >= 12.0)
                    & (pts[:, 0] <= 22.0)
                    & (pts[:, 1] >= 12.0)
                    & (pts[:, 1] <= 22.0)
                )
                return (a | b) & (pts[:, 2] >= -100.0) & (pts[:, 2] <= 0.0)

        ob = Checker([(11.0, 11.0, 12.0)])  # bbox only
        g = build_section_geometry(ob, "L01", -50.0, RES_DEFAULT)
        assert g.component_count == 2


# --------------------------------------------------------------------------- #
# Outer contour contract
# --------------------------------------------------------------------------- #


class TestOuterContour:
    def test_contour_closed_ccw_on_grid_resolution_boundary(self):
        ob = FootprintOrebody([(5.0, -7.0, 25.0)])
        g = build_section_geometry(ob, "L01", -50.0, RES_DEFAULT)
        loop = g.outer_contour_xy
        assert loop.shape[0] > 3
        assert np.array_equal(loop[0], loop[-1])  # closed
        assert shoelace(loop) > 0.0  # CCW-normalized
        # every vertex sits within one grid diagonal of the true circle
        r = np.hypot(loop[:, 0] - 5.0, loop[:, 1] + 7.0)
        assert np.all(np.abs(r - 25.0) <= g.spacing * math.sqrt(2.0))

    def test_holes_are_diagnostic_only(self):
        ob = FootprintOrebody([(0.0, 0.0, 30.0)], holes=[(0.0, 0.0, 10.0)])
        g = build_section_geometry(ob, "L01", -50.0, RES_DEFAULT)
        assert g.component_count == 1  # an annulus is one 4-connected piece
        assert (g.loop_count, g.hole_count) == (2, 1)
        # the OUTER loop (largest |area|) is the one delivered
        assert abs(shoelace(g.outer_contour_xy)) == pytest.approx(math.pi * 30.0**2, rel=0.06)
        r = np.hypot(g.outer_contour_xy[:, 0], g.outer_contour_xy[:, 1])
        assert np.all(r > 20.0)


# --------------------------------------------------------------------------- #
# LevelSections wiring
# --------------------------------------------------------------------------- #


class TestLevelSectionsGeometry:
    def test_lazy_cache_and_missing_resolution(self):
        ob = FootprintOrebody([(0.0, 0.0, 30.0)])
        levels = [RequiredLevel("L01", 0, -20.0), RequiredLevel("L02", 1, -40.0)]
        plain = LevelSections(ob, levels, 2.0)
        with pytest.raises(RuntimeError, match="SectionResolution"):
            plain.geometry(levels[0])
        sections = LevelSections(ob, levels, 2.0, resolution=RES_DEFAULT)
        assert sections.budget_diagnostics is not None
        g1 = sections.geometry(levels[0])
        assert sections.geometry(levels[0]) is g1  # cached
        g2 = sections.geometry(levels[1])
        assert g2.level_id == "L02"
        assert not g1.empty and not g2.empty
