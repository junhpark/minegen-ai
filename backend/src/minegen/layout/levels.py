"""Required levels and numerical level service for layout-v2 (Phase 20A).

Required levels come from the ONE existing generator
(``design.targets.generate_level_elevations``, rule 141) — it works through
the generic ``Orebody`` bounding box, so TABULAR, ELLIPSOID and WARPED_VEIN
share it. Nothing here re-derives elevations.

Level service (directive §6) is numerical: the horizontal distance from a
ramp/level crossing point ``p`` to the orebody FOOTPRINT at ``z = zL``

    d_access = inf ‖p_xy − q_xy‖  over  q.z = zL, orebody.contains(q)

is measured on the authoritative solid itself (``contains``), never from a
global strike (rule 145 — a WARPED_VEIN has no such thing). Implementation:
a deterministic in-plane sample of the footprint (spacing
``section_sampling_spacing``, grid anchored at the world origin), a KD-tree
over the inside samples and a bisection refinement along the segment from
``p`` to its nearest inside sample ``s``. The refinement returns an inside
point on that segment, so the distance is always an UPPER bound of the true
distance (never optimistic). Its over-estimate is at most
``‖p − s‖ − d_true``, i.e. the gap between the true nearest footprint point
and its nearest inside sample: ≤ ``spacing·√2`` wherever the footprint
contains a full grid cell next to that point, wider across thin slivers or
at grazing incidence. Footprint slivers thinner than the spacing can be
missed entirely; a missed sliver only makes a level look LESS served.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

import numpy as np
import numpy.typing as npt
from scipy.spatial import cKDTree

from minegen.design.targets import generate_level_elevations, level_id
from minegen.world.orebody import Orebody

FloatArray = npt.NDArray[np.float64]

#: bisection depth of the access-distance refinement (2 m / 2^24 ≈ 0.1 µm)
REFINEMENT_ITERATIONS = 24


@dataclass(frozen=True)
class RequiredLevel:
    level_id: str
    index: int  # 0 = top
    elevation: float


def required_levels(
    orebody: Orebody, sublevel_interval: float, top_margin: float, bottom_margin: float
) -> list[RequiredLevel]:
    """Rule 141: the existing generator is the only elevation source."""
    elevations = generate_level_elevations(orebody, sublevel_interval, top_margin, bottom_margin)
    return [RequiredLevel(level_id(i, z), i, float(z)) for i, z in enumerate(elevations)]


def level_intervals(levels: list[RequiredLevel]) -> list[float]:
    return [float(levels[i].elevation - levels[i + 1].elevation) for i in range(len(levels) - 1)]


@dataclass
class LevelSection:
    """Deterministic in-plane sample of the orebody footprint at one
    elevation. ``inside_xy`` are the sample points that the authoritative
    ``contains`` accepted; everything else is derived from them."""

    elevation: float
    spacing: float
    inside_xy: FloatArray  # (N, 2)
    orebody: Orebody

    @property
    def empty(self) -> bool:
        return bool(self.inside_xy.shape[0] == 0)

    @cached_property
    def centroid(self) -> FloatArray:
        return np.asarray(self.inside_xy.mean(axis=0))

    @cached_property
    def _tree(self) -> cKDTree:
        return cKDTree(self.inside_xy)

    def extent_along(self, direction_xy: FloatArray) -> tuple[float, float]:
        """(min, max) of ``(s − centroid)·direction`` over the inside samples."""
        d = np.asarray(direction_xy, dtype=np.float64)
        proj = (self.inside_xy - self.centroid) @ d
        return float(proj.min()), float(proj.max())

    def access_distance(self, xy: FloatArray) -> float:
        """Upper-bound horizontal distance from ``xy`` to the footprint
        (see module docstring); 0 when ``xy`` itself is inside."""
        p = np.asarray(xy, dtype=np.float64)[:2]
        probe = np.array([[p[0], p[1], self.elevation]])
        if bool(self.orebody.contains(probe)[0]):
            return 0.0
        dist, idx = self._tree.query(p)
        s = self.inside_xy[int(idx)]
        # bisection: t_out (outside) → t_in (inside) along p→s
        t_out, t_in = 0.0, 1.0
        for _ in range(REFINEMENT_ITERATIONS):
            t_mid = 0.5 * (t_out + t_in)
            q = p + t_mid * (s - p)
            if bool(self.orebody.contains(np.array([[q[0], q[1], self.elevation]]))[0]):
                t_in = t_mid
            else:
                t_out = t_mid
        return float(t_in * dist)

    def nearest_inside(self, xy: FloatArray) -> FloatArray:
        p = np.asarray(xy, dtype=np.float64)[:2]
        _, idx = self._tree.query(p)
        return np.asarray(self.inside_xy[int(idx)])


def build_level_section(orebody: Orebody, elevation: float, spacing: float) -> LevelSection:
    """Sample the footprint at ``elevation`` on a world-origin-anchored grid
    covering the orebody's bounding-box footprint (padded by one spacing)."""
    lo, hi = orebody.bounding_box()
    if not (lo[2] - 1e-9 <= elevation <= hi[2] + 1e-9):
        return LevelSection(elevation, spacing, np.zeros((0, 2)), orebody)
    x0 = np.floor((lo[0] - spacing) / spacing) * spacing
    x1 = np.ceil((hi[0] + spacing) / spacing) * spacing
    y0 = np.floor((lo[1] - spacing) / spacing) * spacing
    y1 = np.ceil((hi[1] + spacing) / spacing) * spacing
    xs = np.arange(x0, x1 + 0.5 * spacing, spacing)
    ys = np.arange(y0, y1 + 0.5 * spacing, spacing)
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    pts = np.column_stack([gx.ravel(), gy.ravel(), np.full(gx.size, elevation)])
    inside = orebody.contains(pts)
    return LevelSection(elevation, spacing, np.asarray(pts[inside][:, :2]), orebody)


class LevelSections:
    """Sections for every required level, built once per search (the same
    sections serve every candidate; results are deterministic)."""

    def __init__(self, orebody: Orebody, levels: list[RequiredLevel], spacing: float) -> None:
        self.orebody = orebody
        self.levels = levels
        self.spacing = spacing
        self.sections: dict[str, LevelSection] = {
            lv.level_id: build_level_section(orebody, lv.elevation, spacing) for lv in levels
        }

    def section(self, level: RequiredLevel) -> LevelSection:
        return self.sections[level.level_id]

    def all_present(self) -> bool:
        return all(not s.empty for s in self.sections.values())

    def serviceable(self) -> list[RequiredLevel]:
        """Required levels that actually intersect the orebody solid. The
        generic elevation generator works from the bounding box, which is
        CONSERVATIVE for implicit bodies (rule 138), so it can emit levels
        above the real top / below the real bottom of a WARPED_VEIN. Such a
        level has no ore to serve: it is reported
        (``NO_OREBODY_SECTION_AT_LEVEL``) and excluded from the
        all-levels-served requirement. For analytic bodies the box is exact
        and every level is serviceable."""
        return [lv for lv in self.levels if not self.section(lv).empty]
