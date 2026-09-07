"""Authoritative section(z) geometry for layout-v2 level development
(Phase 20C.2A commit A1).

At every required-level elevation ``zL`` the orebody's horizontal section is
measured on a world-origin-anchored occupancy grid whose only membership
authority is ``Orebody.contains(x, y, zL)`` (rule 129/133) — never WARPED
control points, a nominal strike, bounding-box edges, mesh vertices or any
frontend reconstruction. Everything in this module is CANDIDATE-INDEPENDENT
geometry built once per level and cached (``LevelSections.geometry``): the
occupancy grid, its 4-connected components, the deterministic dominant
component and its marching-squares outer contour. The footwall-side
orientation (``FootwallTrace``, commit A2) is layered on top of this
geometry afterwards; nothing here consumes ``FootwallTrack``.

Resolution contract
-------------------
The trace must resolve features at the scale of the anchor stand-off, so

    effective_section_spacing <= base_anchor_standoff / SECTION_TRACE_SAMPLES_PER_STANDOFF

with ``base_anchor_standoff`` = the explicit ``access.anchor_standoff`` when
configured, else ``ramp.footwall_access_offset``. The configured
``section_sampling_spacing`` is refined by POWERS OF TWO only (spacing / 2^n,
smallest n that satisfies the bound) so refined grids stay nested in the
coarse one and results are reproducible. A non-positive base stand-off cannot
define a resolution target and fails closed (``SECTION_STANDOFF_NONPOSITIVE``
— the schema permits ``footwall_access_offset = 0``, rule 29); nothing is
clamped and the schema is not changed.

Resource guards (Gate 0, measured on the 32-seed WARPED survey, default
config): the worst default scenario needs ≈ 2.97 M cells over all levels
(max ≈ 185 k cells/level at 2 m) and one /2 refinement of that worst case
≈ 11.9 M cells. The budgets below leave headroom above those measurements
while refusing runaway refinement:

* ``SECTION_MAX_GRID_CELLS_PER_LEVEL`` = 2_000_000
* ``SECTION_MAX_GRID_CELLS_TOTAL``     = 16_000_000  (all required levels)

Both are validated from the projected grid shape BEFORE any allocation
(``SECTION_RESOLUTION_BUDGET_EXCEEDED``), and occupancy is evaluated with a
deterministic chunked ``contains()`` sweep so the transient point buffer
stays bounded regardless of grid size.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy import ndimage
from scipy.spatial import cKDTree

from minegen.world.orebody import Orebody

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]

#: resolution contract: at least this many occupancy samples per base
#: anchor stand-off (directive §A1)
SECTION_TRACE_SAMPLES_PER_STANDOFF = 4
#: per-level occupancy-cell budget (see module docstring for the Gate 0
#: measurements these are documented from)
SECTION_MAX_GRID_CELLS_PER_LEVEL = 2_000_000
#: total occupancy-cell budget over all required levels
SECTION_MAX_GRID_CELLS_TOTAL = 16_000_000
#: chunk size (cells) of the deterministic chunked ``contains`` sweep;
#: bounds the transient (N, 3) probe buffer to ≈ 6 MB
SECTION_CONTAINS_CHUNK = 262_144

#: typed failure codes (fail closed, never clamped — rule 54 analogue)
SECTION_STANDOFF_NONPOSITIVE = "SECTION_STANDOFF_NONPOSITIVE"
SECTION_RESOLUTION_BUDGET_EXCEEDED = "SECTION_RESOLUTION_BUDGET_EXCEEDED"

#: 4-connectivity structuring element (edge neighbours only, no diagonals)
_STRUCTURE_4 = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool)


class SectionGeometryError(Exception):
    """Typed section-geometry failure. ``code`` is one of the module's
    SECTION_* constants; ``diagnostics`` is JSON-able."""

    def __init__(self, code: str, detail: str, diagnostics: dict[str, Any] | None = None):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.diagnostics: dict[str, Any] = diagnostics or {}


@dataclass(frozen=True)
class SectionResolution:
    """Resolved section sampling resolution (directive §A1 contract)."""

    base_spacing: float  # configured section_sampling_spacing
    base_standoff: float  # explicit anchor_standoff else footwall_access_offset
    effective_spacing: float  # base_spacing / refinement_factor
    refinement_factor: int  # power of two, 1 = no refinement

    def payload(self) -> dict[str, Any]:
        return {
            "baseSpacing": self.base_spacing,
            "baseStandoff": self.base_standoff,
            "effectiveSpacing": self.effective_spacing,
            "refinementFactor": self.refinement_factor,
            "samplesPerStandoff": SECTION_TRACE_SAMPLES_PER_STANDOFF,
        }


def resolve_section_resolution(base_spacing: float, base_standoff: float) -> SectionResolution:
    """Smallest power-of-two refinement of ``base_spacing`` satisfying the
    resolution contract. Fails closed on a non-positive stand-off."""
    if base_standoff <= 0.0:
        raise SectionGeometryError(
            SECTION_STANDOFF_NONPOSITIVE,
            "base anchor stand-off must be positive to define the section "
            f"resolution target (got {base_standoff!r}); configure "
            "access.anchorStandoff or a positive ramp.footwallAccessOffset",
            {"baseStandoff": base_standoff, "baseSpacing": base_spacing},
        )
    target = base_standoff / SECTION_TRACE_SAMPLES_PER_STANDOFF
    factor = 1
    while base_spacing / factor > target * (1.0 + 1e-12):
        factor *= 2
    return SectionResolution(
        base_spacing=float(base_spacing),
        base_standoff=float(base_standoff),
        effective_spacing=float(base_spacing / factor),
        refinement_factor=factor,
    )


def grid_axis(lo: float, hi: float, spacing: float) -> tuple[float, int]:
    """World-origin-anchored axis covering ``[lo − spacing, hi + spacing]``:
    start coordinate and sample count. The formula is the one
    ``build_level_section`` has always used (grid anchored at multiples of
    ``spacing``), expressed without allocating the axis."""
    x0 = float(np.floor((lo - spacing) / spacing) * spacing)
    x1 = float(np.ceil((hi + spacing) / spacing) * spacing)
    return x0, round((x1 - x0) / spacing) + 1


def projected_grid_shape(orebody: Orebody, spacing: float) -> tuple[float, float, int, int]:
    """(x0, y0, nx, ny) of the section occupancy grid — pure arithmetic,
    nothing allocated. Every level shares it (the bounding-box footprint is
    global), so per-level cell counts are identical."""
    lo, hi = orebody.bounding_box()
    x0, nx = grid_axis(float(lo[0]), float(hi[0]), spacing)
    y0, ny = grid_axis(float(lo[1]), float(hi[1]), spacing)
    return x0, y0, nx, ny


def validate_section_budgets(
    orebody: Orebody, resolution: SectionResolution, level_count: int
) -> dict[str, Any]:
    """Check both cell budgets from the PROJECTED shape, before any
    allocation. Returns the budget diagnostics on success."""
    _, _, nx, ny = projected_grid_shape(orebody, resolution.effective_spacing)
    cells_per_level = nx * ny
    total_cells = cells_per_level * level_count
    diag = {
        "cellsPerLevel": cells_per_level,
        "totalCells": total_cells,
        "levelCount": level_count,
        "perLevelBudget": SECTION_MAX_GRID_CELLS_PER_LEVEL,
        "totalBudget": SECTION_MAX_GRID_CELLS_TOTAL,
        **resolution.payload(),
    }
    if cells_per_level > SECTION_MAX_GRID_CELLS_PER_LEVEL:
        raise SectionGeometryError(
            SECTION_RESOLUTION_BUDGET_EXCEEDED,
            f"section occupancy grid needs {cells_per_level} cells per level "
            f"(> {SECTION_MAX_GRID_CELLS_PER_LEVEL}) at effective spacing "
            f"{resolution.effective_spacing} m",
            diag,
        )
    if total_cells > SECTION_MAX_GRID_CELLS_TOTAL:
        raise SectionGeometryError(
            SECTION_RESOLUTION_BUDGET_EXCEEDED,
            f"section occupancy grids need {total_cells} cells over "
            f"{level_count} levels (> {SECTION_MAX_GRID_CELLS_TOTAL}) at "
            f"effective spacing {resolution.effective_spacing} m",
            diag,
        )
    return diag


def _occupancy_chunked(
    orebody: Orebody, elevation: float, x0: float, y0: float, nx: int, ny: int, spacing: float
) -> BoolArray:
    """Occupancy of the (nx, ny) grid at ``elevation`` via deterministic
    fixed-size chunks of the flattened cell index (row-major, ij), so the
    transient probe buffer never exceeds ``SECTION_CONTAINS_CHUNK`` points."""
    total = nx * ny
    occ = np.zeros(total, dtype=bool)
    for start in range(0, total, SECTION_CONTAINS_CHUNK):
        stop = min(start + SECTION_CONTAINS_CHUNK, total)
        flat = np.arange(start, stop, dtype=np.int64)
        pts = np.empty((stop - start, 3), dtype=np.float64)
        pts[:, 0] = x0 + (flat // ny) * spacing
        pts[:, 1] = y0 + (flat % ny) * spacing
        pts[:, 2] = elevation
        occ[start:stop] = orebody.contains(pts)
    return occ.reshape(nx, ny)


@dataclass(frozen=True)
class SectionComponent:
    """One 4-connected component of a level's occupancy grid."""

    component_id: int  # 1-based ndimage label
    sample_count: int
    area_proxy: float  # sample_count × spacing², m² (a proxy, not a survey)
    centroid_xy: tuple[float, float]

    def payload(self) -> dict[str, Any]:
        return {
            "componentId": self.component_id,
            "sampleCount": self.sample_count,
            "areaProxy": self.area_proxy,
            "centroid": [self.centroid_xy[0], self.centroid_xy[1]],
        }


@dataclass
class LevelSectionGeometry:
    """Candidate-independent section geometry of ONE level (see module
    docstring). ``outer_contour_xy`` is the marching-squares loop of the
    dominant component with the largest |shoelace area|, normalized
    counter-clockwise and closed (first row == last row). It is a
    grid-resolution boundary of the occupancy — reported as such, never as
    an exact ore contact. Hole loops are counted as diagnostics only."""

    level_id: str
    elevation: float
    spacing: float  # effective spacing the grid was built at
    refinement_factor: int
    x0: float
    y0: float
    shape: tuple[int, int]
    occupancy: BoolArray  # (nx, ny)
    components: list[SectionComponent]  # dominance order (best first)
    selected_component_id: int | None
    selected_mask: BoolArray  # (nx, ny), the dominant component only
    outer_contour_xy: FloatArray  # (M, 2) closed CCW loop; (0, 2) when empty
    loop_count: int  # all marching-squares loops of the dominant component
    hole_count: int  # loop_count − 1 (diagnostic only)

    @property
    def empty(self) -> bool:
        return self.selected_component_id is None

    @property
    def component_count(self) -> int:
        return len(self.components)

    def payload(self) -> dict[str, Any]:
        return {
            "levelId": self.level_id,
            "elevation": self.elevation,
            "effectiveSpacing": self.spacing,
            "refinementFactor": self.refinement_factor,
            "gridShape": [self.shape[0], self.shape[1]],
            "componentCount": self.component_count,
            "selectedComponentId": self.selected_component_id,
            # explicit contract fields (PR #24 follow-up §3) — derived from
            # the existing components list, never recomputed
            "selectedAreaProxy": next(
                (
                    c.area_proxy
                    for c in self.components
                    if c.component_id == self.selected_component_id
                ),
                None,
            ),
            "ignoredComponentIds": [
                c.component_id
                for c in self.components
                if c.component_id != self.selected_component_id
            ],
            "ignoredAreaProxy": float(
                sum(
                    c.area_proxy
                    for c in self.components
                    if c.component_id != self.selected_component_id
                )
            ),
            "components": [c.payload() for c in self.components],
            "outerContourVertexCount": int(self.outer_contour_xy.shape[0]),
            "loopCount": self.loop_count,
            "holeCount": self.hole_count,
        }


def _dominance_order(components: list[SectionComponent]) -> list[SectionComponent]:
    """Largest sample count first; ties by centroid x ascending, then
    centroid y ascending (directive §A1 — deterministic, never merged)."""
    return sorted(components, key=lambda c: (-c.sample_count, c.centroid_xy[0], c.centroid_xy[1]))


def _shoelace_area(loop_xy: FloatArray) -> float:
    x, y = loop_xy[:, 0], loop_xy[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def _outer_contour(mask: BoolArray, x0: float, y0: float, spacing: float) -> tuple[FloatArray, int]:
    """Marching-squares loops of ``mask`` (zero-padded so every loop is
    closed); returns the largest-|area| loop in world XY, CCW-normalized,
    and the total loop count."""
    from skimage import measure  # heavy import kept lazy (Phase 19 pattern)

    padded = np.zeros((mask.shape[0] + 2, mask.shape[1] + 2), dtype=np.float64)
    padded[1:-1, 1:-1] = mask
    loops = measure.find_contours(padded, 0.5)  # type: ignore[no-untyped-call]
    if not loops:
        return np.zeros((0, 2)), 0
    world_loops: list[FloatArray] = []
    for lp in loops:
        w = np.empty_like(lp)
        w[:, 0] = x0 + (lp[:, 0] - 1.0) * spacing
        w[:, 1] = y0 + (lp[:, 1] - 1.0) * spacing
        world_loops.append(w)
    areas = [_shoelace_area(w) for w in world_loops]
    best = int(np.argmax(np.abs(np.asarray(areas))))
    outer = world_loops[best]
    if areas[best] < 0.0:
        outer = outer[::-1].copy()
    return outer, len(world_loops)


def build_section_geometry(
    orebody: Orebody, level_id: str, elevation: float, resolution: SectionResolution
) -> LevelSectionGeometry:
    """Build one level's candidate-independent section geometry. The
    per-level budget is re-checked from the projected shape before any
    allocation (the total budget is a ``LevelSections`` responsibility,
    validated upfront over all levels)."""
    spacing = resolution.effective_spacing
    x0, y0, nx, ny = projected_grid_shape(orebody, spacing)
    if nx * ny > SECTION_MAX_GRID_CELLS_PER_LEVEL:
        raise SectionGeometryError(
            SECTION_RESOLUTION_BUDGET_EXCEEDED,
            f"level {level_id}: occupancy grid {nx} x {ny} exceeds the "
            f"per-level budget {SECTION_MAX_GRID_CELLS_PER_LEVEL}",
            {"levelId": level_id, "gridShape": [nx, ny], **resolution.payload()},
        )
    lo, hi = orebody.bounding_box()
    if not (float(lo[2]) - 1e-9 <= elevation <= float(hi[2]) + 1e-9):
        occ = np.zeros((0, 0), dtype=bool)
        return LevelSectionGeometry(
            level_id,
            elevation,
            spacing,
            resolution.refinement_factor,
            x0,
            y0,
            (0, 0),
            occ,
            [],
            None,
            occ,
            np.zeros((0, 2)),
            0,
            0,
        )
    occ = _occupancy_chunked(orebody, elevation, x0, y0, nx, ny, spacing)
    labels, n_components = ndimage.label(occ, structure=_STRUCTURE_4)
    if n_components == 0:
        return LevelSectionGeometry(
            level_id,
            elevation,
            spacing,
            resolution.refinement_factor,
            x0,
            y0,
            (nx, ny),
            occ,
            [],
            None,
            np.zeros((nx, ny), dtype=bool),
            np.zeros((0, 2)),
            0,
            0,
        )
    components: list[SectionComponent] = []
    for label in range(1, int(n_components) + 1):
        ii, jj = np.nonzero(labels == label)
        count = int(ii.size)
        components.append(
            SectionComponent(
                component_id=label,
                sample_count=count,
                area_proxy=count * spacing * spacing,
                centroid_xy=(
                    x0 + float(ii.mean()) * spacing,
                    y0 + float(jj.mean()) * spacing,
                ),
            )
        )
    ordered = _dominance_order(components)
    selected = ordered[0]
    selected_mask = np.asarray(labels == selected.component_id)
    contour, loop_count = _outer_contour(selected_mask, x0, y0, spacing)
    return LevelSectionGeometry(
        level_id=level_id,
        elevation=elevation,
        spacing=spacing,
        refinement_factor=resolution.refinement_factor,
        x0=x0,
        y0=y0,
        shape=(nx, ny),
        occupancy=occ,
        components=ordered,
        selected_component_id=selected.component_id,
        selected_mask=selected_mask,
        outer_contour_xy=contour,
        loop_count=loop_count,
        hole_count=max(loop_count - 1, 0),
    )


# --------------------------------------------------------------------------- #
# Footwall trace + offset development trace (Phase 20C.2A commit A2)
# --------------------------------------------------------------------------- #

#: typed failure codes of the trace layer (fail closed, never smoothed away)
SECTION_FOOTWALL_AMBIGUOUS = "SECTION_FOOTWALL_AMBIGUOUS"
SECTION_TRACE_OFFSET_INVALID = "SECTION_TRACE_OFFSET_INVALID"

#: contour vertices probed (evenly spaced) by the contains()-based outward-
#: orientation verification
ORIENTATION_PROBE_COUNT = 16
#: minimum dominant footwall run length, in effective spacings — below this
#: the side classification is noise, not a footwall
MIN_FOOTWALL_RUN_SPACINGS = 4.0
#: tolerance band (in effective spacings) by which the offset trace may sit
#: CLOSER (in plan) to the contact trace than the stand-off — the level set
#: interpolates between grid nodes while the contact trace sits on mid-cell
#: contour vertices; the plan distance to the contact is always at least
#: the 3-D clearance the level set holds
OFFSET_CONTACT_TOLERANCE_SPACINGS = 2.0
#: block size of the chunked self-intersection sweep (pairs per block)
_SELF_INTERSECT_BLOCK = 256
#: uniform chainage spacing (m) the offset trace is delivered at
TRACE_RESAMPLE_SPACING = 2.0
#: arc-length box-smoothing passes applied to the resampled offset trace.
#: The clearance field is piecewise-trilinear, so its raw level set carries
#: corners at lattice-cell boundaries (measured up to ~70°) that no drift
#: could drive; features below the stand-off scale are sub-resolution by
#: the trace contract, so the backbone is smoothed at that scale
#: (half-window = base stand-off, endpoints fixed) and then RE-VALIDATED
#: against the same clearance measure — smoothing is never allowed to hide
#: a stand-off violation, and the unchanged hard gates still judge every
#: delivered development (rule 61/62 pattern).
TRACE_SMOOTHING_PASSES = 2


def _interp_along(pts: FloatArray, s: FloatArray, query: FloatArray) -> FloatArray:
    """Linear interpolation of a polyline at arc-length coordinates."""
    out = np.empty((query.shape[0], pts.shape[1]), dtype=np.float64)
    for k in range(pts.shape[1]):
        out[:, k] = np.interp(query, s, pts[:, k])
    return out


def _windowed_tangents(pts: FloatArray, half_window: float, *, closed: bool) -> FloatArray:
    """Unit tangent per vertex from the symmetric secant over ``±half_window``
    of arc length. This is a documented tangent ESTIMATOR resolution — the
    secant is exact (parallel to the midpoint tangent) on constant-curvature
    arcs and suppresses sub-window grid staircase; the polyline itself is
    never moved (no smoothing of the geometry). Windows are clamped to a
    quarter of the total length (closed) or the ends (open)."""
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    if closed:
        loop_pts = np.concatenate([pts, pts[:1]], axis=0)
        s_full = np.concatenate([[0.0], np.cumsum(seg), [0.0]])
        s_full[-1] = s_full[-2] + float(np.linalg.norm(pts[0] - pts[-1]))
        total = float(s_full[-1])
        s = s_full[:-1]
        hw = min(half_window, 0.25 * total)
        ext_pts = np.concatenate([loop_pts, loop_pts, loop_pts], axis=0)
        s_ext = np.concatenate([s_full - total, s_full, s_full + total])
        fwd = _interp_along(ext_pts, s_ext, s + hw)
        bwd = _interp_along(ext_pts, s_ext, s - hw)
    else:
        s = np.concatenate([[0.0], np.cumsum(seg)])
        total = float(s[-1])
        hw = min(half_window, 0.25 * total) if total > 0.0 else 0.0
        fwd = _interp_along(pts, s, np.minimum(s + hw, total))
        bwd = _interp_along(pts, s, np.maximum(s - hw, 0.0))
    d = fwd - bwd
    n = np.linalg.norm(d, axis=1)
    n[n < 1e-12] = 1.0
    return np.asarray(d / n[:, None])


def _cyclic_runs(mask: npt.NDArray[np.bool_]) -> list[npt.NDArray[np.int64]]:
    """Maximal cyclic runs of True indices, each as a contiguous index array
    (wrapping runs are unrolled past N). Deterministic order: by unwrapped
    start index."""
    n = mask.shape[0]
    if not bool(mask.any()):
        return []
    if bool(mask.all()):
        return [np.arange(n, dtype=np.int64)]
    starts = np.flatnonzero(mask & ~np.roll(mask, 1))
    runs: list[npt.NDArray[np.int64]] = []
    for st in starts:
        length = 1
        while mask[(st + length) % n]:
            length += 1
        runs.append(np.arange(st, st + length, dtype=np.int64))
    return runs


def _run_arc_length(pts: FloatArray, run: npt.NDArray[np.int64]) -> float:
    idx = run % pts.shape[0]
    return float(np.linalg.norm(np.diff(pts[idx], axis=0), axis=1).sum())


def _segments_intersect_any(pts_xy: FloatArray) -> bool:
    """True when any two NON-ADJACENT segments of the open polyline
    intersect. Chunked all-pairs orientation test."""
    a = pts_xy[:-1]
    b = pts_xy[1:]
    m = a.shape[0]
    if m < 3:
        return False

    def cross(o: FloatArray, p: FloatArray, q: FloatArray) -> FloatArray:
        return np.asarray(
            (p[..., 0] - o[..., 0]) * (q[..., 1] - o[..., 1])
            - (p[..., 1] - o[..., 1]) * (q[..., 0] - o[..., 0])
        )

    for i0 in range(0, m, _SELF_INTERSECT_BLOCK):
        i1 = min(i0 + _SELF_INTERSECT_BLOCK, m)
        ai, bi = a[i0:i1, None, :], b[i0:i1, None, :]
        aj, bj = a[None, :, :], b[None, :, :]
        d1 = cross(ai, bi, aj)
        d2 = cross(ai, bi, bj)
        d3 = cross(aj, bj, ai)
        d4 = cross(aj, bj, bi)
        hit = ((d1 * d2) < 0.0) & ((d3 * d4) < 0.0)
        idx_i = np.arange(i0, i1)[:, None]
        idx_j = np.arange(m)[None, :]
        hit &= (idx_j - idx_i) >= 2  # each unordered pair once, skip adjacent
        if bool(hit.any()):
            return True
    return False


@dataclass
class FootwallTrace:
    """Dominant footwall arc of a level's outer contour: the ore-CONTACT
    polyline (grid resolution — never an exact ore contact) with per-vertex
    chainage, local tangents and local OUTWARD (away from ore) normals.
    ``track.w_h`` enters only as the orientation seed deciding WHICH side of
    the contour is the footwall; every tangent/normal is local contour
    geometry verified against ``contains``."""

    level_id: str
    elevation: float
    contact_points: FloatArray  # (K, 3)
    chainage: FloatArray  # (K,) cumulative, starts at 0
    tangents: FloatArray  # (K, 2) unit, along increasing chainage
    outward_normals: FloatArray  # (K, 2) unit, away from the ore
    total_length: float
    diagnostics: dict[str, Any]

    def payload(self) -> dict[str, Any]:
        return {
            "levelId": self.level_id,
            "elevation": self.elevation,
            "vertexCount": int(self.contact_points.shape[0]),
            "totalLength": self.total_length,
            **self.diagnostics,
        }


def build_footwall_trace(
    orebody: Orebody,
    geometry: LevelSectionGeometry,
    resolution: SectionResolution,
    w_h: FloatArray,
) -> FootwallTrace:
    """Extract the dominant footwall trace from the section's outer contour.

    1. Local tangents on the closed contour via the ``±base_standoff / 2``
       windowed secant estimator; outward normals as their right-hand
       perpendicular (CCW loop → interior on the left).
    2. ``contains``-verified orientation: probe vertices ``± spacing`` along
       the normal; a majority of decisive probes must confirm (or
       consistently invert, in which case the normals are flipped and the
       flip is recorded). No decisive majority is a typed
       ``SECTION_FOOTWALL_AMBIGUOUS`` failure — never a PCA fallback.
    3. Footwall side: cyclic runs of ``outward · w_h > 0``; the dominant run
       is the one with the largest arc length (tie: smallest start index).
       Runs shorter than ``MIN_FOOTWALL_RUN_SPACINGS × spacing`` are noise;
       having none is ambiguous. Ignored runs are recorded."""
    spacing = geometry.spacing
    loop = geometry.outer_contour_xy
    if geometry.empty or loop.shape[0] < 5:
        raise SectionGeometryError(
            SECTION_FOOTWALL_AMBIGUOUS,
            f"level {geometry.level_id}: outer contour has too few vertices "
            f"({int(loop.shape[0])}) to orient a footwall side",
            {"levelId": geometry.level_id, "vertexCount": int(loop.shape[0])},
        )
    pts = loop[:-1]  # drop the duplicate closing vertex
    n = pts.shape[0]
    half_window = 0.5 * resolution.base_standoff
    tangents = _windowed_tangents(pts, half_window, closed=True)
    normals = np.column_stack([tangents[:, 1], -tangents[:, 0]])

    probe_idx = np.unique(
        np.linspace(0, n - 1, min(ORIENTATION_PROBE_COUNT, n)).round().astype(int)
    )
    delta = spacing
    outer = pts[probe_idx] + delta * normals[probe_idx]
    inner = pts[probe_idx] - delta * normals[probe_idx]
    z = np.full(probe_idx.shape[0], geometry.elevation)
    outer_in = orebody.contains(np.column_stack([outer, z]))
    inner_in = orebody.contains(np.column_stack([inner, z]))
    votes_ok = int(np.sum(~outer_in & inner_in))
    votes_inverted = int(np.sum(outer_in & ~inner_in))
    flipped = False
    if votes_inverted > votes_ok:
        normals = -normals
        tangents = -tangents
        flipped = True
    elif votes_ok == votes_inverted:  # includes zero decisive probes
        raise SectionGeometryError(
            SECTION_FOOTWALL_AMBIGUOUS,
            f"level {geometry.level_id}: contains()-probes cannot confirm the "
            f"contour's outward side ({votes_ok} outward vs {votes_inverted} "
            f"inverted decisive votes of {int(probe_idx.shape[0])} probes)",
            {
                "levelId": geometry.level_id,
                "votesOutward": votes_ok,
                "votesInverted": votes_inverted,
                "probeCount": int(probe_idx.shape[0]),
            },
        )

    w = np.asarray(w_h, dtype=np.float64)
    w = w / float(np.linalg.norm(w))
    side = np.asarray((normals @ w) > 0.0)
    runs = _cyclic_runs(side)
    min_run = MIN_FOOTWALL_RUN_SPACINGS * spacing
    scored = [(r, _run_arc_length(pts, r)) for r in runs]
    usable = [(r, ln) for r, ln in scored if ln >= min_run]
    if not usable:
        raise SectionGeometryError(
            SECTION_FOOTWALL_AMBIGUOUS,
            f"level {geometry.level_id}: no footwall-side contour run of at "
            f"least {min_run:.1f} m (runs: "
            f"{[round(ln, 1) for _, ln in scored]})",
            {"levelId": geometry.level_id, "runLengths": [ln for _, ln in scored]},
        )
    usable.sort(key=lambda rl: (-rl[1], int(rl[0][0])))
    run, run_length = usable[0]
    idx = run % n
    contact = np.column_stack([pts[idx], np.full(idx.shape[0], geometry.elevation)])
    seg = np.linalg.norm(np.diff(contact[:, :2], axis=0), axis=1)
    chain = np.concatenate([[0.0], np.cumsum(seg)])
    t_open = _windowed_tangents(pts[idx], half_window, closed=False)
    # keep the loop's verified outward sense: re-derive the open-trace normals
    # from the open tangents, oriented to agree with the loop normals
    n_open = np.column_stack([t_open[:, 1], -t_open[:, 0]])
    agree = np.sum(n_open * normals[idx], axis=1)
    n_open[agree < 0.0] = -n_open[agree < 0.0]
    return FootwallTrace(
        level_id=geometry.level_id,
        elevation=geometry.elevation,
        contact_points=contact,
        chainage=chain,
        tangents=t_open,
        outward_normals=n_open,
        total_length=float(chain[-1]),
        diagnostics={
            "selectedComponentId": geometry.selected_component_id,
            "componentCount": geometry.component_count,
            "effectiveSpacing": spacing,
            "refinementFactor": geometry.refinement_factor,
            "tangentWindowHalfWidth": float(min(half_window, 0.25 * (chain[-1] + 1e-9))),
            "orientationVotes": {"outward": votes_ok, "inverted": votes_inverted},
            "orientationFlipped": flipped,
            "footwallRunCount": len(usable),
            "ignoredRunLengths": [ln for _, ln in scored if ln < min_run],
            "dominantRunLength": run_length,
        },
    )


@dataclass
class OffsetTrace:
    """Curved development backbone: the arc of the CLEARANCE-FIELD level set
    ``clearance = standoff`` on the level plane, adjacent to the dominant
    footwall trace. The measure is the caller's authoritative clearance
    (the design clearance policy — exact SDF or conservative basis), NEVER a
    2-D in-plane distance: a dipping / warped body leans over the level
    plane, and an in-plane offset of the section under-clears it (measured
    on WARPED-301 L03: 82 % of the in-plane-EDT trace sat below the
    required 3-D clearance; the clearance level set holds it by
    construction). A level set rounds concave stretches instead of
    self-intersecting; it is extracted, never smoothed, and every defect
    that survives is a typed failure."""

    level_id: str
    elevation: float
    standoff: float
    points: FloatArray  # (K, 3)
    chainage: FloatArray  # (K,)
    tangents: FloatArray  # (K, 2) unit
    ore_contact: FloatArray  # (K, 3) nearest footwall-trace contact vertex
    ore_contact_distance: FloatArray  # (K,)
    total_length: float
    diagnostics: dict[str, Any]

    def point_at(self, chainage: float) -> FloatArray:
        return np.asarray(_interp_along(self.points, self.chainage, np.array([chainage]))[0])

    def tangent_at(self, chainage: float) -> FloatArray:
        """Unit local tangent (2-D plan) at an arc-length chainage —
        linear interpolation of the per-vertex windowed tangents,
        renormalized. The crosscut inward-normal contract (rule 180) takes
        its ± perpendicular from this tangent."""
        t = np.asarray(_interp_along(self.tangents, self.chainage, np.array([chainage]))[0])
        n = float(np.linalg.norm(t))
        return t / n if n > 1e-12 else t

    def payload(self) -> dict[str, Any]:
        return {
            "levelId": self.level_id,
            "elevation": self.elevation,
            "standoff": self.standoff,
            "vertexCount": int(self.points.shape[0]),
            "totalLength": self.total_length,
            **self.diagnostics,
        }


def _clearance_grid(
    clearance: Callable[[FloatArray], FloatArray],
    x0: float,
    y0: float,
    nx: int,
    ny: int,
    spacing: float,
    elevation: float,
) -> FloatArray:
    """Clearance field sampled on the (padded) section grid at the level
    elevation — deterministic fixed-size chunks, bounded probe buffer."""
    total = nx * ny
    out = np.empty(total, dtype=np.float64)
    for start in range(0, total, SECTION_CONTAINS_CHUNK):
        stop = min(start + SECTION_CONTAINS_CHUNK, total)
        flat = np.arange(start, stop, dtype=np.int64)
        pts = np.empty((stop - start, 3), dtype=np.float64)
        pts[:, 0] = x0 + (flat // ny) * spacing
        pts[:, 1] = y0 + (flat % ny) * spacing
        pts[:, 2] = elevation
        out[start:stop] = clearance(pts)
    return out.reshape(nx, ny)


def build_offset_trace(
    geometry: LevelSectionGeometry,
    trace: FootwallTrace,
    resolution: SectionResolution,
    standoff: float,
    minimum_length: float,
    clearance: Callable[[FloatArray], FloatArray],
    minimum_clearance: float,
) -> OffsetTrace:
    """Extract and validate the offset development trace at ``standoff``.

    ``clearance`` is the AUTHORITATIVE stand-off measure — the design
    clearance policy's ``signed_clearance`` (exact SDF for analytic bodies,
    the conservative basis for implicit ones; the same policy whose hard
    gates later judge the delivered development, so the backbone holds the
    stand-off by construction of its geometry, with nothing relaxed). It is
    sampled on the section grid extended by ``ceil(2·standoff / spacing) +
    2`` cells (a leaning body pushes the level set outward in plan;
    transient float grid only — the contains() cell budgets are not
    affected), contoured at ``standoff``, and the arc whose vertices are
    nearest to the dominant footwall trace (against the rest of the outer
    contour) is kept, oriented along increasing trace chainage. An arc that
    leaves the extended grid is handled as an open contour.

    Typed ``SECTION_TRACE_OFFSET_INVALID`` failures — nothing is smoothed,
    trimmed or clamped to hide a defect: no footwall-adjacent offset arc;
    arc shorter than ``minimum_length``; non-finite vertices;
    self-intersection; any vertex materially closer to the contact than the
    stand-off (``standoff − OFFSET_CONTACT_TOLERANCE_SPACINGS × spacing``)."""
    from skimage import measure  # heavy import kept lazy (Phase 19 pattern)

    spacing = geometry.spacing
    mask = geometry.selected_mask
    if geometry.empty or not bool(mask.any()):
        raise SectionGeometryError(
            SECTION_TRACE_OFFSET_INVALID,
            f"level {geometry.level_id}: no selected component to offset",
            {"levelId": geometry.level_id},
        )
    # construct the level set at standoff + the derived smoothing allowance
    # so the SMOOTHED backbone still holds the planning stand-off
    allowance = smoothing_allowance(standoff, resolution.base_standoff, TRACE_SMOOTHING_PASSES)
    construction = standoff + allowance
    pad = int(np.ceil(2.0 * construction / spacing)) + 2
    dist = _clearance_grid(
        clearance,
        geometry.x0 - pad * spacing,
        geometry.y0 - pad * spacing,
        mask.shape[0] + 2 * pad,
        mask.shape[1] + 2 * pad,
        spacing,
        geometry.elevation,
    )
    loops = measure.find_contours(dist, construction)  # type: ignore[no-untyped-call]
    contour_pts = geometry.outer_contour_xy[:-1]
    contact_tree = cKDTree(contour_pts)
    trace_start = trace.contact_points[0, :2]
    # membership of each outer-contour vertex in the dominant footwall run
    _, first_idx = contact_tree.query(trace_start)
    k = trace.contact_points.shape[0]
    member = np.zeros(contour_pts.shape[0], dtype=bool)
    member[(int(first_idx) + np.arange(k)) % contour_pts.shape[0]] = True

    candidates: list[tuple[float, int, int, FloatArray]] = []
    for li, lp in enumerate(loops):
        w = np.empty_like(lp)
        w[:, 0] = geometry.x0 + (lp[:, 0] - pad) * spacing
        w[:, 1] = geometry.y0 + (lp[:, 1] - pad) * spacing
        closed = bool(np.allclose(w[0], w[-1]))
        v = w[:-1] if closed and w.shape[0] > 1 else w
        if v.shape[0] < 2:
            continue
        _, nearest = contact_tree.query(v)
        labs = member[np.asarray(nearest, dtype=int)]
        runs = _cyclic_runs(labs) if closed else _open_runs(labs)
        for r in runs:
            ln = _run_arc_length(v, r)
            candidates.append((ln, li, int(r[0]), v[r % v.shape[0]]))
    if not candidates:
        raise SectionGeometryError(
            SECTION_TRACE_OFFSET_INVALID,
            f"level {geometry.level_id}: the {standoff:.1f} m offset level set "
            "has no arc adjacent to the dominant footwall trace",
            {"levelId": geometry.level_id, "standoff": standoff, "loopCount": len(loops)},
        )
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
    run_length, loop_index, _, run_pts = candidates[0]

    # deterministic orientation: advance with the footwall-trace chainage
    _, c_first = contact_tree.query(run_pts[0])
    _, c_last = contact_tree.query(run_pts[-1])
    pos_first = _member_chainage_rank(int(c_first), int(first_idx), k, contour_pts.shape[0])
    pos_last = _member_chainage_rank(int(c_last), int(first_idx), k, contour_pts.shape[0])
    if pos_last < pos_first:
        run_pts = run_pts[::-1].copy()

    # delivered form: uniform chainage, smoothed at the stand-off scale,
    # re-resampled to uniform chainage (the clipped smoothing windows
    # compress spacing near the ends and can collapse neighbouring vertices
    # into exact duplicates), END-TRIMMED by the smoothing half-window (the
    # end regions only receive one-sided windows, so residual level-set
    # curvature survives there — below the smoothing contract's guarantee;
    # trimming is conservative-only, it just shortens the usable backbone),
    # then RE-VALIDATED below
    run_pts = _resample_polyline(run_pts, TRACE_RESAMPLE_SPACING)
    run_pts = _box_smooth(run_pts, resolution.base_standoff, TRACE_SMOOTHING_PASSES)
    run_pts = _resample_polyline(run_pts, TRACE_RESAMPLE_SPACING)
    seg_l = np.linalg.norm(np.diff(run_pts, axis=0), axis=1)
    s_full = np.concatenate([[0.0], np.cumsum(seg_l)])
    trim = min(float(resolution.base_standoff), 0.2 * float(s_full[-1]))
    keep = (s_full >= trim - 1e-9) & (s_full <= float(s_full[-1]) - trim + 1e-9)
    if int(keep.sum()) >= 2:
        run_pts = run_pts[keep]
    run_length = float(np.linalg.norm(np.diff(run_pts, axis=0), axis=1).sum())

    fail_diag: dict[str, Any] = {
        "levelId": geometry.level_id,
        "standoff": standoff,
        "arcLength": run_length,
        "minimumLength": minimum_length,
    }
    if not bool(np.isfinite(run_pts).all()):
        raise SectionGeometryError(
            SECTION_TRACE_OFFSET_INVALID,
            f"level {geometry.level_id}: offset trace has non-finite vertices",
            fail_diag,
        )
    if run_length < minimum_length:
        raise SectionGeometryError(
            SECTION_TRACE_OFFSET_INVALID,
            f"level {geometry.level_id}: offset trace arc {run_length:.1f} m is "
            f"shorter than the minimum development length {minimum_length:.1f} m",
            fail_diag,
        )
    if _segments_intersect_any(run_pts):
        raise SectionGeometryError(
            SECTION_TRACE_OFFSET_INVALID,
            f"level {geometry.level_id}: offset trace self-intersects",
            fail_diag,
        )
    pts3 = np.column_stack([run_pts, np.full(run_pts.shape[0], geometry.elevation)])
    # clearance RE-VALIDATION of the smoothed backbone under the SAME
    # measure. The HARD floor is ``minimum_clearance`` (the required design
    # clearance — the same gate the delivered development must pass);
    # ``standoff`` is the level-set PLANNING target, and the achieved
    # minimum is reported against it as a diagnostic. Smoothing can never
    # hide a hard-clearance violation (typed).
    cvals = np.asarray(clearance(pts3), dtype=np.float64)
    if float(cvals.min()) < minimum_clearance - 1e-9:
        raise SectionGeometryError(
            SECTION_TRACE_OFFSET_INVALID,
            f"level {geometry.level_id}: smoothed offset trace clearance "
            f"{float(cvals.min()):.2f} m falls below the required design "
            f"clearance {minimum_clearance:.2f} m (planning stand-off "
            f"{standoff:.1f} m)",
            fail_diag,
        )
    trace_tree = cKDTree(trace.contact_points[:, :2])
    contact_dist, contact_idx = trace_tree.query(run_pts)
    contact_dist = np.asarray(contact_dist, dtype=np.float64)
    # planning stand-off HARD validation (PR #24 follow-up §2): the docstring
    # contract — no smoothed vertex materially closer to the footwall contact
    # than the stand-off — is enforced, not just reported. This is a SEPARATE
    # contract from the engineering ``minimum_clearance`` floor above (both
    # gates stay): a trace that keeps the engineering floor but misses the
    # planning stand-off fails typed instead of passing silently.
    contact_floor = standoff - OFFSET_CONTACT_TOLERANCE_SPACINGS * spacing
    if float(contact_dist.min()) < contact_floor - 1e-9:
        raise SectionGeometryError(
            SECTION_TRACE_OFFSET_INVALID,
            f"level {geometry.level_id}: smoothed offset trace approaches the "
            f"footwall contact to {float(contact_dist.min()):.2f} m — below the "
            f"planning stand-off floor {contact_floor:.2f} m (stand-off "
            f"{standoff:.1f} m - {OFFSET_CONTACT_TOLERANCE_SPACINGS:g} x "
            f"{spacing:g} m spacing)",
            {**fail_diag, "minContactDistance": float(contact_dist.min())},
        )
    seg = np.linalg.norm(np.diff(run_pts, axis=0), axis=1)
    chain = np.concatenate([[0.0], np.cumsum(seg)])
    tangents = _windowed_tangents(run_pts, 0.5 * resolution.base_standoff, closed=False)
    return OffsetTrace(
        level_id=geometry.level_id,
        elevation=geometry.elevation,
        standoff=standoff,
        points=pts3,
        chainage=chain,
        tangents=tangents,
        ore_contact=trace.contact_points[np.asarray(contact_idx, dtype=int)],
        ore_contact_distance=contact_dist,
        total_length=float(chain[-1]),
        diagnostics={
            "selectedComponentId": geometry.selected_component_id,
            "effectiveSpacing": spacing,
            "refinementFactor": geometry.refinement_factor,
            "padCells": pad,
            "offsetLoopCount": len(loops),
            "footwallArcCandidates": len(candidates),
            "minContactDistance": float(contact_dist.min()),
            "maxContactDistance": float(contact_dist.max()),
            "minSmoothedClearance": float(cvals.min()),
            "smoothingPasses": TRACE_SMOOTHING_PASSES,
            "smoothingAllowance": allowance,
            "constructionStandoff": construction,
            "resampleSpacing": TRACE_RESAMPLE_SPACING,
            "loopIndex": loop_index,
        },
    )


def _resample_polyline(pts_xy: FloatArray, spacing: float) -> FloatArray:
    """Uniform-chainage resampling of an open polyline (endpoints exact)."""
    seg = np.linalg.norm(np.diff(pts_xy, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(s[-1])
    if total <= spacing:
        return pts_xy.copy()
    n = max(2, round(total / spacing) + 1)
    return _interp_along(pts_xy, s, np.linspace(0.0, total, n))


def smoothing_allowance(standoff: float, half_window: float, passes: int) -> float:
    """DERIVED upper bound of the inward displacement box smoothing can
    apply to the offset level set. The level set's tightest convex
    roundings have radius = the stand-off; the box average of a circular
    arc of radius R over arc half-window W sits at ``R·sin(θ)/θ`` with
    ``θ = W/R``, i.e. an inward displacement of ``R·(1 − sin θ / θ)`` per
    pass (later passes act on a flatter curve, so ``passes ×`` is an upper
    bound). The trace is CONSTRUCTED at ``standoff + allowance`` so the
    smoothed backbone still holds the planning stand-off — a raise-only
    compensation (rule 158 precedent), never a relaxed gate: the hard
    clearance floor is re-validated unchanged."""
    theta = min(half_window / max(standoff, 1e-9), math.pi / 2.0)
    return passes * standoff * (1.0 - math.sin(theta) / theta)


def _box_smooth(pts_xy: FloatArray, half_window: float, passes: int) -> FloatArray:
    """Arc-length box smoothing: each vertex becomes the mean of the
    vertices within ``± half_window`` of arc length, the window CLIPPED (not
    shrunk) at the ends so the trace is uniformly smooth everywhere — a
    shrink-to-zero window leaves the raw level-set kinks standing near the
    ends. The trace ends are free geometry (the entry is picked mid-trace
    afterwards); the caller re-validates the smoothed result against the
    clearance measure. Deterministic."""
    out = pts_xy
    for _ in range(passes):
        seg = np.linalg.norm(np.diff(out, axis=0), axis=1)
        s = np.concatenate([[0.0], np.cumsum(seg)])
        lo = np.searchsorted(s, s - half_window, side="left")
        hi = np.searchsorted(s, s + half_window, side="right")
        csum = np.concatenate([np.zeros((1, 2)), np.cumsum(out, axis=0)])
        counts = (hi - lo).astype(np.float64)
        out = (csum[hi] - csum[lo]) / counts[:, None]
    return np.asarray(out)


def _open_runs(mask: npt.NDArray[np.bool_]) -> list[npt.NDArray[np.int64]]:
    """Maximal runs of True in an OPEN (non-cyclic) label array."""
    if not bool(mask.any()):
        return []
    padded = np.concatenate([[False], mask, [False]])
    starts = np.flatnonzero(padded[1:] & ~padded[:-1])
    ends = np.flatnonzero(~padded[1:] & padded[:-1])
    return [np.arange(st, en, dtype=np.int64) for st, en in zip(starts, ends, strict=True)]


def _member_chainage_rank(contour_idx: int, first_idx: int, k: int, n: int) -> int:
    """Rank of an outer-contour vertex along the footwall run (0 = run start;
    non-members rank past the run, keeping order stable)."""
    off = (contour_idx - first_idx) % n
    return off if off < k else k + off
