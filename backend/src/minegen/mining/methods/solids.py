"""Shared production-solid helpers for the Phase 21B/C methods (Cut & Fill,
Room & Pillar).

Deliberately a SEPARATE implementation from ``longhole.py``: the Longhole
geometry algorithm is a migration target that is never refactored for reuse
(directive §2), so the box corner / winding / quadrature helpers it needs
are re-stated here for the NEW methods. Every solid is an axis-aligned
prism in the analytic TABULAR local frame ``(u strike, v down-dip, w
thickness normal)`` mapped to world space through ``TabularOrebody.to_world``
— the analytic solid is the geometric authority, never a voxel.

Every generated solid is judged INDEPENDENTLY (``geometry.mesh_qa``: finite,
valid indices, non-degenerate, manifold, watertight, outward, positive
signed volume) and its mesh volume must agree with the analytic prism
volume; a defect is a typed per-solid failure that fails the whole
artifact — never a silently dropped or "approximately right" solid.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from minegen.design.cost_field import DesignCostEvaluator
from minegen.geometry.mesh_qa import mesh_qa
from minegen.mining.models import LocalBounds, ProductionReport, SolidGeometry
from minegen.world.orebody import TabularOrebody
from minegen.world.synthetic_world import SyntheticWorld

FloatArray = npt.NDArray[np.float64]

#: hard-validation lattice spacing inside a production solid (m)
HARD_SAMPLE_SPACING = 5.0
#: planning grade proxy quadrature spacing (rule 130): equal local volumes
GRADE_PROXY_SAMPLE_SPACING = 2.5
#: analytic ↔ mesh volume agreement (relative)
VOLUME_REL_TOLERANCE = 1e-6
#: deterministic complexity budget of ONE production artifact (solids of any
#: kind: cuts, extraction units AND pillars). Exceeding it is a typed
#: PRODUCTION_COMPLEXITY_LIMIT failure — never a silent decimation. Sized
#: from the default scenario (600 × 350 × 12 m body): Room & Pillar with the
#: default 8 / 6 m bands and one bench = 7,322 solids, Cut & Fill with the
#: default 4 m lifts / 15 m cuts over 12 level intervals ≈ 3,360 cuts.
MAX_PRODUCTION_SOLIDS = 8000

# canonical box corners: bit i&1 → u, i>>1&1 → v, i>>2&1 → w; triangles wound
# OUTWARD for a right-handed (u, v, w) frame (mirrored once when the analytic
# frame determinant is negative so the WORLD mesh is outward)
_CORNER_BITS = [(i & 1, (i >> 1) & 1, (i >> 2) & 1) for i in range(8)]
_BOX_TRIANGLES = [
    (0, 2, 3),
    (0, 3, 1),
    (4, 5, 7),
    (4, 7, 6),
    (0, 1, 5),
    (0, 5, 4),
    (2, 6, 7),
    (2, 7, 3),
    (0, 4, 6),
    (0, 6, 2),
    (1, 3, 7),
    (1, 7, 5),
]


def equal_partition(lo: float, hi: float, target: float) -> list[tuple[float, float]]:
    """DETERMINISTIC EQUAL PARTITION of ``[lo, hi]`` into ``n = ceil(span /
    target)`` pieces of ``span / n`` each — no tiny residual piece at an edge
    (directive §6). ``target`` must be positive; an empty span yields []."""
    span = hi - lo
    if span <= 0.0:
        return []
    n = max(1, math.ceil(span / target - 1e-9))
    step = span / n
    return [(lo + i * step, hi if i == n - 1 else lo + (i + 1) * step) for i in range(n)]


def frame_triangles(orebody: TabularOrebody) -> list[tuple[int, int, int]]:
    handed = float(np.linalg.det(np.column_stack([orebody.u, orebody.v, orebody.w])))
    return _BOX_TRIANGLES if handed > 0 else [(a, c, b) for a, b, c in _BOX_TRIANGLES]


def prism_geometry(
    orebody: TabularOrebody, bounds: LocalBounds, triangles: list[tuple[int, int, int]]
) -> SolidGeometry:
    lows = np.array([bounds.u_min, bounds.v_min, bounds.w_min])
    highs = np.array([bounds.u_max, bounds.v_max, bounds.w_max])
    corners_local = np.array(
        [[lows[d] if bit == 0 else highs[d] for d, bit in enumerate(bits)] for bits in _CORNER_BITS]
    )
    corners_world = orebody.to_world(corners_local)
    return SolidGeometry(
        vertices=[float(x) for x in corners_world.ravel()],
        triangle_indices=[i for tri in triangles for i in tri],
    )


def analytic_volume(bounds: LocalBounds) -> float:
    return float(
        (bounds.u_max - bounds.u_min)
        * (bounds.v_max - bounds.v_min)
        * (bounds.w_max - bounds.w_min)
    )


def hard_invalid_samples(
    evaluator: DesignCostEvaluator, orebody: TabularOrebody, bounds: LocalBounds
) -> int:
    """Deterministic hard-validation lattice inside the prism (world / terrain
    / cover / restricted-zone constraints of the evaluator's context)."""
    lows = np.array([bounds.u_min, bounds.v_min, bounds.w_min])
    highs = np.array([bounds.u_max, bounds.v_max, bounds.w_max])
    axes = [
        np.linspace(
            lows[d], highs[d], max(2, math.ceil((highs[d] - lows[d]) / HARD_SAMPLE_SPACING) + 1)
        )
        for d in range(3)
    ]
    gu, gv, gw = np.meshgrid(*axes, indexing="ij")
    lattice = orebody.to_world(np.column_stack([gu.ravel(), gv.ravel(), gw.ravel()]))
    hard = evaluator.evaluate_points(lattice)
    return int((~hard.valid).sum())


def grade_proxy(
    world: SyntheticWorld, orebody: TabularOrebody, bounds: LocalBounds
) -> float | None:
    """Deterministic PLANNING grade proxy (rule 130): equal-volume midpoint
    quadrature of the authoritative grade field over the part of the prism
    inside the analytic solid AND below terrain. Never a resource / reserve."""
    lows = np.array([bounds.u_min, bounds.v_min, bounds.w_min])
    highs = np.array([bounds.u_max, bounds.v_max, bounds.w_max])
    extent = highs - lows
    if bool(np.any(extent <= 0.0)):
        return None
    counts = [max(1, math.ceil(float(extent[d]) / GRADE_PROXY_SAMPLE_SPACING)) for d in range(3)]
    axes = [lows[d] + (np.arange(counts[d]) + 0.5) * (extent[d] / counts[d]) for d in range(3)]
    gu, gv, gw = np.meshgrid(*axes, indexing="ij")
    pts = orebody.to_world(np.column_stack([gu.ravel(), gv.ravel(), gw.ravel()]))
    keep = orebody.contains(pts) & (pts[:, 2] <= world.terrain.sample(pts[:, :2]))
    if not bool(keep.any()):
        return None
    return float(world.fields.grade.sample(pts[keep]).mean())


@dataclass(frozen=True)
class SolidBuild:
    geometry: SolidGeometry
    volume: float
    report: ProductionReport


def build_solid(
    orebody: TabularOrebody,
    bounds: LocalBounds,
    triangles: list[tuple[int, int, int]],
    evaluator: DesignCostEvaluator | None,
    *,
    extra_values: tuple[float | None, ...] = (),
    precondition_failure: str | None = None,
) -> SolidBuild:
    """One production solid with its INDEPENDENT QA: mesh contract, analytic
    ↔ mesh volume agreement, hard-evaluator sampling (when an evaluator is
    given — retained pillars are judged geometrically only) and finiteness.
    ``precondition_failure`` records a caller-side failure first."""
    geometry = prism_geometry(orebody, bounds, triangles)
    volume = analytic_volume(bounds)
    qa = mesh_qa(
        np.asarray(geometry.vertices, dtype=np.float64).reshape(-1, 3),
        np.asarray(geometry.triangle_indices, dtype=np.int64).reshape(-1, 3),
    )
    agreement = bool(
        volume > 0.0
        and math.isfinite(qa.signed_volume)
        and abs(qa.signed_volume - volume) <= VOLUME_REL_TOLERANCE * volume
    )
    hard_invalid = hard_invalid_samples(evaluator, orebody, bounds) if evaluator else 0
    values = [volume, qa.signed_volume, *[v for v in extra_values if v is not None]]
    finite = bool(np.isfinite(np.asarray(values, dtype=np.float64)).all())
    reason = precondition_failure
    if reason is None and volume <= 0.0:
        reason = "non-positive solid dimensions"
    if reason is None and not qa.closed_solid:
        reason = f"mesh QA failed ({'; '.join(qa.problems)})"
    if reason is None and not agreement:
        reason = (
            f"mesh volume {qa.signed_volume:.6f} m³ disagrees with the analytic prism "
            f"volume {volume:.6f} m³"
        )
    if reason is None and hard_invalid > 0:
        reason = f"{hard_invalid} prism samples violate hard world/terrain/cover/zone constraints"
    if reason is None and not finite:
        reason = "non-finite solid metrics"
    return SolidBuild(
        geometry=geometry,
        volume=volume,
        report=ProductionReport(
            hard_invalid_samples=hard_invalid,
            mesh_closed_solid=qa.closed_solid,
            mesh_volume_m3=float(qa.signed_volume),
            volume_agreement=agreement,
            finite=finite,
            valid=reason is None,
            failure_reason=reason,
        ),
    )


def weighted_grade(pairs: list[tuple[float | None, float]]) -> float | None:
    graded = [(g, t) for g, t in pairs if g is not None]
    if not graded:
        return None
    total = math.fsum(t for _, t in graded)
    return float(math.fsum(g * t for g, t in graded) / total) if total > 0 else None


def central_access_by_level(
    levels_payload: dict,  # type: ignore[type-arg]
) -> tuple[dict[str, dict], str | None]:  # type: ignore[type-arg]
    """The ONE central production access CROSSCUT (station index 0) of every
    level, keyed by level id; a level without exactly one is a typed
    failure (the fixed access pattern develops exactly one)."""
    found: dict[str, dict] = {}  # type: ignore[type-arg]
    for dev in levels_payload["developments"]:
        if dev["kind"] != "CROSSCUT":
            continue
        if int(dev.get("stationIndex", -1)) != 0:
            return {}, (
                f"development {dev['id']} is not the central production access "
                "(station index 0) — the levels artifact carries a station lattice"
            )
        level = str(dev["levelId"])
        if level in found:
            return {}, f"level {level} carries more than one central production access"
        found[level] = dev
    for lv in levels_payload["levels"]:
        if str(lv["levelId"]) not in found:
            return {}, f"level {lv['levelId']} has no production access crosscut"
    return found, None
