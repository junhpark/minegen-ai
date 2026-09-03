"""Delivered-centerline geometry for layout-v2 (Phase 20A, rule 144).

Everything downstream and every acceptance decision uses ONE discretized
centerline. Analytic family parameters are design intent; this module
measures what was actually delivered:

* per-edge gradient (vertical / horizontal, MineGen convention),
* heading (clockwise azimuth from +Y, ``docs/coordinate-system.md``),
* unwrapped heading change, plan curvature radius at every interior vertex
  (chord-based: exact for uniformly sampled circular arcs),
* family-signature diagnostics (rule 145): cumulative / signed heading
  change, reversal count, dominant azimuths, turn-direction consistency,
* level crossings by segment interpolation (no elevation tolerance), and the
  exact insertion of crossing points as vertices so effective-ramp segments
  can be split at them (rule 149).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]

#: below this heading change per vertex (rad) an edge pair counts as straight
STRAIGHT_HEADING_EPS = 1e-6
#: a same-sense turning run totalling within [MIN, MAX] degrees is a hairpin
#: reversal (a spiral's single multi-thousand-degree run is not one)
REVERSAL_MIN_DEG = 150.0
REVERSAL_MAX_DEG = 210.0
#: azimuth histogram bin width for dominant-axis detection (deg)
AZIMUTH_BIN_DEG = 15.0
#: plan radius above which an edge is not "turning" for the turning-length
#: diagnostic (m)
TURNING_RADIUS_LIMIT = 500.0


def horizontal_lengths(points: FloatArray) -> FloatArray:
    d = np.diff(points[:, :2], axis=0)
    return np.asarray(np.hypot(d[:, 0], d[:, 1]))


def chainage(points: FloatArray) -> FloatArray:
    seg = np.linalg.norm(np.diff(points, axis=0), axis=1)
    return np.concatenate([[0.0], np.cumsum(seg)])


def headings(points: FloatArray) -> FloatArray:
    """Clockwise-from-North azimuth (rad, in (−π, π]) of every edge."""
    d = np.diff(points[:, :2], axis=0)
    return np.asarray(np.arctan2(d[:, 0], d[:, 1]))


def unwrap_delta(a: FloatArray) -> FloatArray:
    """Heading change per interior vertex wrapped to (−π, π]."""
    d = np.diff(a)
    return np.asarray((d + math.pi) % (2.0 * math.pi) - math.pi)


@dataclass
class CenterlineDiagnostics:
    point_count: int
    length3d: float
    horizontal_length: float
    vertical_drop: float
    max_abs_gradient: float
    mean_abs_gradient: float
    min_plan_radius: float | None  # None when the line never turns
    turning_length: float
    cumulative_heading_change_deg: float
    signed_heading_change_deg: float
    heading_reversal_count: int
    hairpin_run_count: int
    dominant_azimuths_deg: list[float]
    turn_direction_consistency: float
    max_local_turn_deg: float
    monotonic_descent: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "pointCount": self.point_count,
            "length3d": self.length3d,
            "horizontalLength": self.horizontal_length,
            "verticalDrop": self.vertical_drop,
            "maxAbsGradient": self.max_abs_gradient,
            "meanAbsGradient": self.mean_abs_gradient,
            "minPlanRadius": self.min_plan_radius,
            "turningLength": self.turning_length,
            "cumulativeHeadingChangeDeg": self.cumulative_heading_change_deg,
            "signedHeadingChangeDeg": self.signed_heading_change_deg,
            "headingReversalCount": self.heading_reversal_count,
            "hairpinRunCount": self.hairpin_run_count,
            "dominantAzimuthsDeg": self.dominant_azimuths_deg,
            "turnDirectionConsistency": self.turn_direction_consistency,
            "maxLocalTurnDeg": self.max_local_turn_deg,
            "monotonicDescent": self.monotonic_descent,
        }


def analyze_centerline(points: FloatArray) -> CenterlineDiagnostics:
    pts = np.asarray(points, dtype=np.float64)
    if pts.shape[0] < 2:
        raise ValueError("a centerline needs at least two points")
    h = horizontal_lengths(pts)
    dz = np.diff(pts[:, 2])
    length3d = float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1)))
    with np.errstate(divide="ignore", invalid="ignore"):
        grad = np.where(h > 1e-12, dz / np.maximum(h, 1e-12), 0.0)
    az = headings(pts)
    delta = unwrap_delta(az) if az.shape[0] > 1 else np.zeros(0)
    # chord-based plan radius at interior vertices
    radii: list[float] = []
    turning_len = 0.0
    if delta.shape[0]:
        mean_len = 0.5 * (h[:-1] + h[1:])
        turning = np.abs(delta) > STRAIGHT_HEADING_EPS
        r = np.full(delta.shape[0], np.inf)
        r[turning] = mean_len[turning] / np.abs(delta[turning])
        radii = [float(v) for v in r[turning]]
        turning_len = float(np.sum(mean_len[turning & (r < TURNING_RADIUS_LIMIT)]))
    cumulative = float(np.sum(np.abs(delta)))
    signed = float(np.sum(delta))
    # hairpin runs: same-sign turning runs totalling ≥ REVERSAL_MIN_DEG. A
    # REVERSAL is such a run that stops near 180° (150°–210°): a switchback
    # hairpin. A spiral is ONE run of thousands of degrees → 0 reversals.
    run_totals: list[float] = []
    run_sign = 0
    run_total = 0.0
    for d in delta:
        s_ = 0 if abs(d) <= STRAIGHT_HEADING_EPS else (1 if d > 0 else -1)
        if s_ != run_sign:
            # a straight vertex or a sense change closes the current run
            if run_sign != 0 and math.degrees(run_total) >= REVERSAL_MIN_DEG:
                run_totals.append(math.degrees(run_total))
            run_sign, run_total = s_, 0.0
        if s_ != 0:
            run_total += abs(d)
    if run_sign != 0 and math.degrees(run_total) >= REVERSAL_MIN_DEG:
        run_totals.append(math.degrees(run_total))
    hairpin_runs = len(run_totals)
    reversals = sum(1 for t in run_totals if t <= REVERSAL_MAX_DEG)
    # dominant azimuths: length-weighted histogram of edge headings, folded
    # to [0, 180) so an axis and its opposite share a bin
    bins = round(180.0 / AZIMUTH_BIN_DEG)
    folded = (np.degrees(az) % 180.0) // AZIMUTH_BIN_DEG
    weights = np.zeros(bins)
    for b, w in zip(folded.astype(int), h, strict=True):
        weights[min(int(b), bins - 1)] += w
    order = np.argsort(-weights, kind="stable")
    dominant = [float(int(i) * AZIMUTH_BIN_DEG + AZIMUTH_BIN_DEG / 2) for i in order[:2]]
    consistency = abs(signed) / cumulative if cumulative > 1e-12 else 1.0
    return CenterlineDiagnostics(
        point_count=int(pts.shape[0]),
        length3d=length3d,
        horizontal_length=float(np.sum(h)),
        vertical_drop=float(pts[0, 2] - pts[-1, 2]),
        max_abs_gradient=float(np.max(np.abs(grad))) if grad.size else 0.0,
        mean_abs_gradient=float(np.sum(np.abs(dz)) / np.sum(h)) if np.sum(h) > 0 else 0.0,
        min_plan_radius=float(min(radii)) if radii else None,
        turning_length=turning_len,
        cumulative_heading_change_deg=math.degrees(cumulative),
        signed_heading_change_deg=math.degrees(signed),
        heading_reversal_count=reversals,
        hairpin_run_count=hairpin_runs,
        dominant_azimuths_deg=dominant,
        turn_direction_consistency=float(consistency),
        max_local_turn_deg=float(math.degrees(np.max(np.abs(delta)))) if delta.size else 0.0,
        monotonic_descent=bool(np.all(dz <= 1e-9)),
    )


@dataclass(frozen=True)
class Crossing:
    """First crossing of the descending centerline with ``z = elevation``."""

    elevation: float
    edge_index: int  # edge (i, i+1) containing the crossing
    t: float  # position inside the edge, 0 ≤ t ≤ 1
    point: FloatArray
    chainage: float


def find_crossing(points: FloatArray, elevation: float) -> Crossing | None:
    """Segment interpolation, no elevation tolerance: the first edge whose
    z-range brackets ``elevation`` (``z_i ≥ zL ≥ z_{i+1}``, descending)."""
    z = points[:, 2]
    ch = chainage(points)
    for i in range(points.shape[0] - 1):
        z0, z1 = float(z[i]), float(z[i + 1])
        if z0 >= elevation >= z1 and z0 > z1:
            t = (z0 - elevation) / (z0 - z1)
            p = points[i] + t * (points[i + 1] - points[i])
            p[2] = elevation  # exact by definition of the crossing
            return Crossing(elevation, i, float(t), p, float(ch[i] + t * (ch[i + 1] - ch[i])))
        if z0 == elevation == z1:
            return Crossing(elevation, i, 0.0, points[i].copy(), float(ch[i]))
    return None


def insert_vertices(points: FloatArray, crossings: list[Crossing]) -> tuple[FloatArray, list[int]]:
    """Insert every crossing as an exact vertex (unless it already is one)
    and return the new polyline plus the vertex index of each crossing, in
    the order given. Crossings must be given in increasing chainage."""
    pts = [points[0]]
    indices: list[int] = []
    cursor = 0  # next original vertex to emit
    for c in crossings:
        # emit original vertices up to the crossing edge start
        while cursor < c.edge_index:
            cursor += 1
            pts.append(points[cursor])
        if c.t <= 1e-12:
            indices.append(len(pts) - 1)
        elif c.t >= 1.0 - 1e-12:
            cursor += 1
            pts.append(points[cursor])
            indices.append(len(pts) - 1)
        else:
            pts.append(c.point)
            indices.append(len(pts) - 1)
    while cursor < points.shape[0] - 1:
        cursor += 1
        pts.append(points[cursor])
    return np.asarray(pts, dtype=np.float64), indices


def split_at(points: FloatArray, vertex_indices: list[int]) -> list[FloatArray]:
    """Split into consecutive pieces sharing their boundary vertices."""
    pieces: list[FloatArray] = []
    start = 0
    for idx in vertex_indices:
        pieces.append(points[start : idx + 1].copy())
        start = idx
    return pieces
