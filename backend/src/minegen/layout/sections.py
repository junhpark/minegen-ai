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

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy import ndimage

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
