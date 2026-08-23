"""Ramp smoothing + full revalidation (CLAUDE.md rules 61–64).

Per selected Phase 04 segment:

    raw primitives
      → lossless simplification (merge equal curvature+grade runs)
      → arc-length control resampling (``control_spacing``)
      → iterative constrained smoothing of control points
            J = w_b Σ‖2p_i − p_{i−1} − p_{i+1}‖² + w_f Σ‖p_i − p_i^raw‖²
            projections per iteration: endpoints fixed, deviation corridor
            (min distance to the raw polyline), isotonic z
      → curve construction
            XY: clamped cubic Hermite — explicit boundary tangents carry the
                Phase 04 headings; interior tangents centered differences
            z:  piecewise-linear between control points, boundary intervals
                forced to the shared boundary grade (rule 61)
      → full revalidation (rule 62) + field-cost preservation (rule 63)
      → deterministic local repair, else RAW_FALLBACK

The effective centerline (SMOOTHED or revalidated RAW_FALLBACK) is the only
Phase 06 input (rule 64).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.core.models import RampConstraints, SmoothingConfig
from minegen.design.cost_field import DesignCostEvaluator
from minegen.design.motion_primitives import Pose, Primitive, PrimitiveSet, Steering, arc_points
from minegen.design.validation import accepted_mask, evaluate_and_validate

FloatArray = npt.NDArray[np.float64]


# --------------------------------------------------------------------------- #
# 1. Lossless simplification
# --------------------------------------------------------------------------- #


def simplify_primitives(prims: list[Primitive], ps: PrimitiveSet) -> list[Primitive]:
    """Merge consecutive primitives with equal (curvature, grade) into single
    analytic arcs/lines. Lossless: rebuilt from the run's start pose with the
    summed horizontal length; the final sample of the last run is pinned to
    the original terminal sample (the goal-shot target)."""
    if not prims:
        return []
    merged: list[Primitive] = []
    run_start = _start_pose(prims[0])
    run_curv, run_grade = prims[0].curvature, prims[0].grade
    run_len = prims[0].horizontal_length
    for p in prims[1:]:
        if p.curvature == run_curv and p.grade == run_grade:
            run_len += p.horizontal_length
            continue
        merged.append(_build(ps, run_start, run_curv, run_grade, run_len))
        run_start = merged[-1].end
        run_curv, run_grade, run_len = p.curvature, p.grade, p.horizontal_length
    merged.append(_build(ps, run_start, run_curv, run_grade, run_len))
    # pin the terminal sample to the exact original endpoint (rule 51 heritage)
    last = merged[-1]
    samples = last.samples.copy()
    samples[-1] = prims[-1].samples[-1]
    end = Pose(
        float(samples[-1][0]), float(samples[-1][1]), float(samples[-1][2]), last.end.heading
    )
    merged[-1] = Primitive(
        steering=last.steering,
        grade=last.grade,
        curvature=last.curvature,
        horizontal_length=last.horizontal_length,
        length_3d=last.length_3d,
        samples=samples,
        sample_arc=last.sample_arc,
        end=end,
    )
    return merged


def _start_pose(p: Primitive) -> Pose:
    """Start pose of a primitive: first sample + heading unwound by the turn."""
    first = p.samples[0]
    turned = p.curvature * p.horizontal_length  # signed heading change
    return Pose(float(first[0]), float(first[1]), float(first[2]), p.end.heading - turned)


def _build(
    ps: PrimitiveSet, start: Pose, curvature: float, grade: float, horizontal_length: float
) -> Primitive:
    steering = (
        Steering.STRAIGHT
        if curvature == 0.0
        else (Steering.RIGHT if curvature > 0 else Steering.LEFT)
    )
    return ps.primitive(start, steering, curvature, grade, horizontal_length)


# --------------------------------------------------------------------------- #
# 2. Resampling & raw polyline utilities
# --------------------------------------------------------------------------- #


def polyline_arclength(points: FloatArray) -> FloatArray:
    steps = np.linalg.norm(np.diff(points, axis=0), axis=1)
    return np.concatenate([[0.0], np.cumsum(steps)])


def resample_polyline(points: FloatArray, spacing: float) -> FloatArray:
    """Uniform arc-length resampling of a polyline; both endpoints exact."""
    s = polyline_arclength(points)
    total = float(s[-1])
    n = max(2, math.ceil(total / spacing) + 1)
    targets = np.linspace(0.0, total, n)
    out = np.empty((n, 3))
    for a in range(3):
        out[:, a] = np.interp(targets, s, points[:, a])
    out[0], out[-1] = points[0], points[-1]
    return out


def distance_to_polyline(points: FloatArray, poly: FloatArray) -> FloatArray:
    """Minimum Euclidean distance from each point to a polyline (segment-wise,
    fully vectorized: N points × M segments)."""
    a = poly[:-1]
    d = poly[1:] - a
    dd = np.einsum("md,md->m", d, d)
    dd[dd == 0] = 1.0
    w = points[:, None, :] - a[None, :, :]  # (N, M, 3)
    t = np.clip(np.einsum("nmd,md->nm", w, d) / dd[None, :], 0.0, 1.0)
    closest = a[None, :, :] + t[..., None] * d[None, :, :]
    dist = np.linalg.norm(points[:, None, :] - closest, axis=2)
    return np.asarray(dist.min(axis=1))


def control_grid(
    simplified: list[Primitive], spacing: float, pinned_end: FloatArray
) -> tuple[FloatArray, FloatArray]:
    """See _control_grid; returns (controls, tangents with arc-corrected
    magnitudes)."""
    controls, tangents, kappa, grade = _control_grid(simplified, spacing, pinned_end)
    return controls, scale_tangents(controls, tangents, kappa, grade)


def scale_tangents(
    controls: FloatArray, unit_tangents: FloatArray, kappa: FloatArray, grade: FloatArray
) -> FloatArray:
    """The Hermite parameter is the 3D chord length, so the XY tangent
    magnitude must be the horizontal speed 1/√(1+g²) — unit magnitudes on a
    12 % path overstate it by 0.7 %, which appeared as a ±1.4 % plan-
    curvature oscillation on R_min arcs (outside the 0.05 m tolerance).
    (1 + θ²/16), θ = |κ|·h, is the cubic arc-reproduction correction."""
    s = polyline_arclength(controls)
    h = np.zeros(len(controls))
    h[1:-1] = 0.5 * (s[2:] - s[:-2])
    h[0] = s[1] - s[0]
    h[-1] = s[-1] - s[-2]
    theta = np.abs(kappa) * h
    factor = (1.0 + theta * theta / 16.0) / np.sqrt(1.0 + grade * grade)
    return np.asarray(unit_tangents * factor[:, None])


def _control_grid(
    simplified: list[Primitive], spacing: float, pinned_end: FloatArray
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
    """Control points on the exact analytic path, aligned to primitive
    junctions (every Hermite interval then interpolates a single arc/line, so
    the unsmoothed reconstruction is near-exact — no curvature overshoot at
    curvature discontinuities). Returns ``(controls, unit XY tangents)``; the
    terminal control is pinned to the stored exact endpoint."""
    pts_list: list[FloatArray] = []
    tan_list: list[FloatArray] = []
    pose = _start_pose(simplified[0])
    for j, prim in enumerate(simplified):
        # curvature-adaptive spacing: a cubic Hermite interval of length h on a
        # circle of radius R overshoots curvature by O((h/R)²); h ≤ 0.09·R keeps
        # the reconstructed radius within the 0.05 m validation tolerance.
        target = spacing
        if prim.curvature != 0.0:
            target = min(spacing, 0.09 / abs(prim.curvature))
        n = max(2, math.ceil(prim.horizontal_length / target) + 1)
        pts, _ = arc_points(pose, prim.curvature, prim.horizontal_length, prim.grade, n)
        h = np.linspace(0.0, prim.horizontal_length, n)
        headings = pose.heading + prim.curvature * h
        tans = np.column_stack([np.sin(headings), np.cos(headings)])
        last = j == len(simplified) - 1
        pts_list.append(pts if last else pts[:-1])
        tan_list.append(tans if last else tans[:-1])
        pose = Pose(float(pts[-1, 0]), float(pts[-1, 1]), float(pts[-1, 2]), float(headings[-1]))
    controls = np.vstack(pts_list)
    tangents = np.vstack(tan_list)
    controls[-1] = pinned_end
    kaps: list[FloatArray] = []
    grds: list[FloatArray] = []
    for j, prim in enumerate(simplified):
        m = pts_list[j].shape[0]
        kaps.append(np.full(m, prim.curvature))
        grds.append(np.full(m, prim.grade))
    return controls, tangents, np.concatenate(kaps), np.concatenate(grds)


def blended_tangents(
    raw_controls: FloatArray, controls: FloatArray, raw_tangents: FloatArray
) -> FloatArray:
    """Per-control unit XY tangents for the deformed control polygon: the
    analytic raw tangent rotated by the change in the centered-difference
    direction. Zero displacement → exactly the raw tangents (near-exact
    reconstruction); any displacement rotates the tangents with it."""

    def centered(c: FloatArray) -> FloatArray:
        d = np.zeros_like(c[:, :2])
        d[1:-1] = c[2:, :2] - c[:-2, :2]
        d[0] = c[1, :2] - c[0, :2]
        d[-1] = c[-1, :2] - c[-2, :2]
        n = np.linalg.norm(d, axis=1, keepdims=True)
        n[n == 0] = 1.0
        return d / n

    mag = np.linalg.norm(raw_tangents, axis=1, keepdims=True)
    mag[mag == 0] = 1.0
    t = raw_tangents / mag + centered(controls) - centered(raw_controls)
    n = np.linalg.norm(t, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return np.asarray(t / n * mag)


# --------------------------------------------------------------------------- #
# 3. Constrained iterative smoothing of control points
# --------------------------------------------------------------------------- #


def smooth_control_points(
    raw_controls: FloatArray,
    raw_polyline: FloatArray,
    cfg: SmoothingConfig,
) -> FloatArray:
    """Gradient descent on J with per-iteration projections: endpoints fixed,
    deviation corridor (distance to the raw polyline), isotonic z (rule 61).
    Deterministic: fixed step, fixed iteration count."""
    p = raw_controls.copy()
    n = p.shape[0]
    if n < 5:
        return p  # too short to smooth while anchoring the boundary-compatible controls
    ref = raw_controls
    w_b, w_f, step = cfg.bending_weight, cfg.fidelity_weight, cfg.step_size
    for _ in range(cfg.max_iterations):
        grad = np.zeros_like(p)
        bend = 2.0 * p[1:-1] - p[:-2] - p[2:]
        grad[1:-1] += 2.0 * w_b * 2.0 * bend
        grad[:-2] -= 2.0 * w_b * bend
        grad[2:] -= 2.0 * w_b * bend
        grad += 2.0 * w_f * (p - ref)
        # endpoints AND the first/last interior controls stay put: headings are
        # enforced by the explicit tangent BC (rule 61); anchoring p1 / p_{n-2}
        # keeps the entry/exit geometry compatible with that fixed tangent so
        # the clamped Hermite does not have to bend sharply out of the pose.
        grad[:2] = 0.0
        grad[-2:] = 0.0
        p -= step * grad
        # corridor projection: pull violators straight back toward their raw twin
        dist = distance_to_polyline(p[1:-1], raw_polyline)
        over = dist > cfg.max_deviation_from_raw
        if over.any():
            idx = np.nonzero(over)[0] + 1
            towards = ref[idx] - p[idx]
            norm = np.linalg.norm(towards, axis=1, keepdims=True)
            norm[norm == 0] = 1.0
            excess = (dist[idx - 1] - cfg.max_deviation_from_raw)[:, None]
            p[idx] += towards / norm * excess
        # isotonic z (non-increasing) — cumulative minimum keeps endpoints fixed
        p[:, 2] = np.minimum.accumulate(p[:, 2])
        p[-2] = ref[-2]
        p[-1] = ref[-1]
    p[0], p[1] = ref[0], ref[1]
    p[:, 2] = np.minimum.accumulate(p[:, 2])
    p[-1, 2] = ref[-1, 2]
    return p


def feasible_controls(
    raw_controls: FloatArray,
    smoothed: FloatArray,
    raw_tangents: FloatArray,
    start_heading: float,
    end_heading: float,
    start_grade: float,
    end_grade: float,
    max_gradient: float,
    min_turn_radius: float,
    *,
    grade_tolerance: float = 1e-5,
    radius_margin: float = 0.04,
    probe_spacing: float = 0.5,
    bisections: int = 40,
) -> FloatArray:
    """Scale the smoothing displacement field globally (deterministic
    bisection on α ∈ [0, 1]) until the built curve satisfies the grade band
    and the XY plan-radius bound. On a grade-limited raw path any horizontal
    shortcut must exceed g_max — the feasible displacement there is ≈ 0 and
    this projection finds it up front instead of leaving it to repairs."""

    def build(alpha: float) -> SegmentCurve:
        c = raw_controls + alpha * (smoothed - raw_controls)
        return build_curve(
            c,
            start_heading,
            end_heading,
            start_grade,
            end_grade,
            tangents_xy=blended_tangents(raw_controls, c, raw_tangents),
            max_gradient=max_gradient,
        )

    def ok(alpha: float) -> bool:
        curve = build(alpha)
        dh = np.diff(curve.h_controls)
        dh[dh == 0] = 1e-12
        g = np.diff(curve.controls[:, 2]) / dh
        if not ((g <= grade_tolerance).all() and (g >= -max_gradient - grade_tolerance).all()):
            return False
        total = float(curve.s[-1])
        sq = np.linspace(0.0, total, max(3, math.ceil(total / probe_spacing) + 1))
        kappa = curve.plan_curvature(sq)
        return bool((kappa <= 1.0 / (min_turn_radius - radius_margin)).all())

    if ok(1.0):
        return smoothed
    if not ok(0.0):
        return raw_controls  # even the unsmoothed reconstruction violates → validation decides
    lo, hi = 0.0, 1.0
    for _ in range(bisections):
        mid = 0.5 * (lo + hi)
        if ok(mid):
            lo = mid
        else:
            hi = mid
    return raw_controls + lo * (smoothed - raw_controls)


# --------------------------------------------------------------------------- #
# 4. Curve: clamped cubic Hermite XY + piecewise-linear z
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SegmentCurve:
    """XY: clamped cubic Hermite over the chord-length parameter ``s`` with
    UNIT tangent directions (boundary = prescribed headings, interior =
    normalized centered differences — equal magnitudes keep the traced speed
    near 1 and the plan curvature free of parameterization spikes).

    z: piecewise-LINEAR in the cumulative *horizontal* arc length ``H`` between
    control points, so the physical grade on every interval equals the control
    secant ``Δz/ΔH`` exactly, independent of the Hermite parameterization.
    A dense lookup table (``table_spacing``) maps s → H."""

    controls: FloatArray  # (n, 3)
    s: FloatArray  # (n,) chord-length parameter of the controls
    tan_xy: FloatArray  # (n, 2) unit tangent directions
    start_tangent: FloatArray  # unit 3D boundary tangent (rule 61)
    end_tangent: FloatArray
    s_dense: FloatArray  # dense parameter grid
    h_dense: FloatArray  # cumulative horizontal length at s_dense
    h_controls: FloatArray  # cumulative horizontal length at the controls

    def _xy(self, sq: FloatArray) -> tuple[FloatArray, FloatArray, FloatArray]:
        sq = np.clip(sq, self.s[0], self.s[-1])
        idx = np.clip(np.searchsorted(self.s, sq, side="right") - 1, 0, len(self.s) - 2)
        h = self.s[idx + 1] - self.s[idx]
        u = (sq - self.s[idx]) / h
        p0, p1 = self.controls[idx, :2], self.controls[idx + 1, :2]
        m0, m1 = self.tan_xy[idx] * h[:, None], self.tan_xy[idx + 1] * h[:, None]
        u2, u3 = u * u, u * u * u
        xy = (
            (2 * u3 - 3 * u2 + 1)[:, None] * p0
            + (u3 - 2 * u2 + u)[:, None] * m0
            + (-2 * u3 + 3 * u2)[:, None] * p1
            + (u3 - u2)[:, None] * m1
        )
        dxy = (
            (6 * u2 - 6 * u)[:, None] * p0
            + (3 * u2 - 4 * u + 1)[:, None] * m0
            + (-6 * u2 + 6 * u)[:, None] * p1
            + (3 * u2 - 2 * u)[:, None] * m1
        ) / h[:, None]
        ddxy = (
            (12 * u - 6)[:, None] * p0
            + (6 * u - 4)[:, None] * m0
            + (-12 * u + 6)[:, None] * p1
            + (6 * u - 2)[:, None] * m1
        ) / (h * h)[:, None]
        return xy, dxy, ddxy

    def horizontal_length(self, sq: FloatArray) -> FloatArray:
        return np.interp(np.clip(sq, self.s[0], self.s[-1]), self.s_dense, self.h_dense)

    def sample(self, s_query: FloatArray) -> tuple[FloatArray, FloatArray, FloatArray]:
        """Positions and XY first/second derivatives w.r.t. s at ``s_query``."""
        sq = np.asarray(s_query, dtype=np.float64)
        xy, dxy, ddxy = self._xy(sq)
        z = np.interp(self.horizontal_length(sq), self.h_controls, self.controls[:, 2])
        return np.column_stack([xy, z]), dxy, ddxy

    def grades(self, s_query: FloatArray) -> FloatArray:
        """Physical grade dz/dH: the control-interval secant, exact."""
        hq = self.horizontal_length(np.asarray(s_query, dtype=np.float64))
        idx = np.clip(
            np.searchsorted(self.h_controls, hq, side="right") - 1, 0, len(self.h_controls) - 2
        )
        dh = self.h_controls[idx + 1] - self.h_controls[idx]
        dh[dh == 0] = 1e-12
        return np.asarray((self.controls[idx + 1, 2] - self.controls[idx, 2]) / dh)

    def plan_curvature(self, s_query: FloatArray) -> FloatArray:
        _, dxy, ddxy = self._xy(np.asarray(s_query, dtype=np.float64))
        num = np.abs(dxy[:, 0] * ddxy[:, 1] - dxy[:, 1] * ddxy[:, 0])
        den = (dxy[:, 0] ** 2 + dxy[:, 1] ** 2) ** 1.5
        den[den == 0] = 1e-12
        return np.asarray(num / den)


def boundary_tangent(heading: float, grade: float) -> FloatArray:
    t = np.array([math.sin(heading), math.cos(heading), grade])
    return np.asarray(t / np.linalg.norm(t))


def build_curve(
    controls: FloatArray,
    start_heading: float,
    end_heading: float,
    start_grade: float,
    end_grade: float,
    *,
    tangents_xy: FloatArray | None = None,
    table_spacing: float = 0.25,
    max_gradient: float | None = None,
) -> SegmentCurve:
    """Clamped Hermite in XY (explicit unit boundary tangents from the Phase 04
    headings — rule 61: never by freezing points; interior tangents are unit
    centered-difference directions). z is anchored in horizontal arc length:
    the boundary intervals carry the shared boundary grade exactly."""
    c = controls.copy()
    s = polyline_arclength(c)
    n = c.shape[0]
    if tangents_xy is not None:
        tan = tangents_xy.copy()
        m0 = float(np.linalg.norm(tan[0])) or 1.0
        m1 = float(np.linalg.norm(tan[-1])) or 1.0
        tan[0] = np.array([math.sin(start_heading), math.cos(start_heading)]) * m0
        tan[-1] = np.array([math.sin(end_heading), math.cos(end_heading)]) * m1
    else:
        tan = np.zeros((n, 2))
        diffs = c[2:, :2] - c[:-2, :2]
        norms = np.linalg.norm(diffs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        tan[1:-1] = diffs / norms
        tan[0] = np.array([math.sin(start_heading), math.cos(start_heading)])
        tan[-1] = np.array([math.sin(end_heading), math.cos(end_heading)])

    # dense horizontal-length table over the XY Hermite
    total = float(s[-1])
    n_dense = max(3, math.ceil(total / table_spacing) + 1)
    s_dense = np.linspace(0.0, total, n_dense)
    probe = SegmentCurve(
        controls=c,
        s=s,
        tan_xy=tan,
        start_tangent=np.zeros(3),
        end_tangent=np.zeros(3),
        s_dense=s_dense,
        h_dense=s_dense,  # placeholder for the XY-only probe
        h_controls=s,
    )
    xy_dense, _, _ = probe._xy(s_dense)
    h_dense = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(xy_dense, axis=0), axis=1))])
    h_controls = np.interp(s, s_dense, h_dense)

    # Boundary z-intervals carry the shared boundary grade (rule 61). The
    # induced offsets are absorbed by projecting the interior z-profile into
    # the feasible band implied by the grade limit: from the fixed z₁ forward
    # and the fixed z_{n−2} backward no point may require a steeper-than-g_max
    # descent, and the profile stays monotone. A forward per-interval clip then
    # yields a deterministic O(n) profile that meets both boundary grades
    # exactly wherever that is geometrically feasible; if it is not (a fully
    # grade-saturated segment given shallower boundary grades), validation
    # rejects and the segment falls back (rule 63).
    if n >= 4 and max_gradient is not None:
        h = h_controls
        z = c[:, 2]
        z[1] = z[0] + start_grade * float(h[1] - h[0])
        z[n - 2] = z[n - 1] - end_grade * float(h[n - 1] - h[n - 2])
        # Reconstruction noise can leave the interior span needing marginally
        # more than g_max (Hermite H differs from the true arc length by
        # O(1e-5) relative); spreading that excess uniformly keeps every
        # interval within the grade tolerance instead of dumping it into the
        # last free interval. Genuine infeasibility still exceeds the
        # tolerance and is caught by validation.
        span_h = float(h[n - 2] - h[1])
        required = (float(z[1]) - float(z[n - 2])) / span_h if span_h > 0 else 0.0
        g = max(max_gradient, required)
        for i in range(2, n - 2):
            lower = max(z[1] - g * float(h[i] - h[1]), z[n - 2])
            upper = min(z[1], z[n - 2] + g * float(h[n - 2] - h[i]))
            z[i] = min(max(z[i], lower), upper) if lower <= upper else lower
        for i in range(2, n - 2):
            lo = z[i - 1] - g * float(h[i] - h[i - 1])
            z[i] = min(max(z[i], lo), z[i - 1])
    elif n >= 3:
        c[1, 2] = c[0, 2] + start_grade * float(h_controls[1] - h_controls[0])
        c[-2, 2] = c[-1, 2] - end_grade * float(h_controls[-1] - h_controls[-2])
        c[1:-1, 2] = np.minimum.accumulate(np.minimum(c[1:-1, 2], c[0, 2]))
        c[1:-1, 2] = np.maximum(c[1:-1, 2], c[-1, 2])
    return SegmentCurve(
        controls=c,
        s=s,
        tan_xy=tan,
        start_tangent=boundary_tangent(start_heading, start_grade),
        end_tangent=boundary_tangent(end_heading, end_grade),
        s_dense=s_dense,
        h_dense=h_dense,
        h_controls=h_controls,
    )


# --------------------------------------------------------------------------- #
# 5. Revalidation + report (rules 62–63)
# --------------------------------------------------------------------------- #


@dataclass
class SegmentReport:
    raw_length: float = 0.0
    smoothed_length: float | None = None
    field_cost_raw: float = 0.0
    field_cost_smoothed: float | None = None
    field_cost_delta_pct: float | None = None
    max_gradient: float = 0.0
    min_plan_radius: float | None = None
    max_deviation_from_raw: float = 0.0
    endpoint_position_error: float = 0.0
    start_heading_error_deg: float = 0.0
    end_heading_error_deg: float = 0.0
    invalid_sample_count: int = 0
    rejection_reason_counts: dict[str, int] = field(default_factory=dict)
    monotonicity_violations: int = 0
    grade_violations: int = 0
    radius_violations: int = 0
    corridor_violations: int = 0
    repairs: int = 0
    valid: bool = False
    effective_source: str = "RAW_FALLBACK"
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        def f(v: float | None) -> float | None:
            return None if v is None or not math.isfinite(v) else float(v)

        return {
            "rawLength": f(self.raw_length),
            "smoothedLength": f(self.smoothed_length),
            "fieldCostRaw": f(self.field_cost_raw),
            "fieldCostSmoothed": f(self.field_cost_smoothed),
            "fieldCostDeltaPct": f(self.field_cost_delta_pct),
            "maxGradient": f(self.max_gradient),
            "minPlanRadius": f(self.min_plan_radius),
            "maxDeviationFromRaw": f(self.max_deviation_from_raw),
            "endpointPositionError": f(self.endpoint_position_error),
            "startHeadingErrorDeg": f(self.start_heading_error_deg),
            "endHeadingErrorDeg": f(self.end_heading_error_deg),
            "invalidSampleCount": self.invalid_sample_count,
            "rejectionReasonCounts": dict(self.rejection_reason_counts),
            "monotonicityViolations": self.monotonicity_violations,
            "gradeViolations": self.grade_violations,
            "radiusViolations": self.radius_violations,
            "corridorViolations": self.corridor_violations,
            "repairs": self.repairs,
            "valid": self.valid,
            "effectiveSource": self.effective_source,
            "fallbackReason": self.fallback_reason,
        }


@dataclass
class Violations:
    chainages: list[float]

    @property
    def any(self) -> bool:
        return len(self.chainages) > 0


class SegmentSmoother:
    """Smooths one Phase 04 segment (rules 61–63). Deterministic throughout."""

    def __init__(
        self,
        evaluator: DesignCostEvaluator,
        ramp: RampConstraints,
        cfg: SmoothingConfig,
    ) -> None:
        self.ev = evaluator
        self.ramp = ramp
        self.cfg = cfg
        cores = [f.config.core_half_width for f in evaluator.faults]
        self.validation_spacing = float(min([1.0, *cores]))

    # -- validation --------------------------------------------------------- #

    def validate_curve(
        self,
        curve: SegmentCurve,
        raw_polyline: FloatArray,
        report: SegmentReport,
        *,
        cover_established: bool,
    ) -> Violations:
        total = float(curve.s[-1])
        n = max(3, math.ceil(total / self.validation_spacing) + 1)
        sq = np.linspace(0.0, total, n)
        pts, _, _ = curve.sample(sq)
        chain: list[float] = []

        evaluation, val, _ = evaluate_and_validate(
            self.ev, pts, cover_established=cover_established, stop_at_first=False
        )
        report.invalid_sample_count = val.invalid_count
        report.rejection_reason_counts = val.rejection_reason_counts
        if not val.ok:
            cover = self.ev.surface_elevation(pts) - pts[:, 2]
            mask, _ = accepted_mask(
                evaluation,
                cover,
                cover_established=cover_established,
                minimum_cover=self.ev.context.minimum_surface_cover,
            )
            chain.extend(float(v) for v in sq[~mask])

        grades = curve.grades(sq)
        g_tol = self.cfg.grade_numerical_tolerance
        g_bad = (grades > g_tol) | (grades < -self.ramp.max_gradient - g_tol)
        report.grade_violations = int(g_bad.sum())
        report.max_gradient = float(np.abs(grades).max())
        chain.extend(float(v) for v in sq[g_bad])

        dz = np.diff(pts[:, 2])
        mono_bad = dz > 1e-9
        report.monotonicity_violations = int(mono_bad.sum())
        chain.extend(float(v) for v in sq[1:][mono_bad])

        kappa = curve.plan_curvature(sq)
        with np.errstate(divide="ignore"):
            radius = np.where(kappa > 1e-12, 1.0 / kappa, np.inf)
        r_bad = radius < self.ramp.min_turn_radius - self.cfg.radius_numerical_tolerance
        report.radius_violations = int(r_bad.sum())
        report.min_plan_radius = float(radius.min()) if np.isfinite(radius).any() else None
        chain.extend(float(v) for v in sq[r_bad])

        dev = distance_to_polyline(pts, raw_polyline)
        c_bad = dev > self.cfg.max_deviation_from_raw + 1e-9
        report.corridor_violations = int(c_bad.sum())
        report.max_deviation_from_raw = float(dev.max())
        chain.extend(float(v) for v in sq[c_bad])

        return Violations(sorted(set(chain)))

    def field_cost(self, points: FloatArray, *, cover_established: bool) -> float:
        _, _, cost = evaluate_and_validate(
            self.ev, points, cover_established=cover_established, stop_at_first=False
        )
        s = polyline_arclength(points)
        return float(np.dot(0.5 * (cost[1:] + cost[:-1]), np.diff(s)))


# --------------------------------------------------------------------------- #
# 6. Whole-decline orchestration (rules 61–64)
# --------------------------------------------------------------------------- #


@dataclass
class SmoothedSegment:
    level_id: str
    candidate_id: str
    raw_points: FloatArray
    effective_points: FloatArray
    effective_source: str  # SMOOTHED | RAW_FALLBACK
    report: SegmentReport
    start_tangent: FloatArray
    end_tangent: FloatArray

    def to_dict(self) -> dict[str, Any]:
        smoothed = (
            {
                "points": self.effective_points.ravel().tolist(),
                "pointCount": int(self.effective_points.shape[0]),
            }
            if self.effective_source == "SMOOTHED"
            else None
        )
        return {
            "levelId": self.level_id,
            "candidateId": self.candidate_id,
            "smoothed": smoothed,
            "effectiveSource": self.effective_source,
            "effectiveCenterline": {
                "points": self.effective_points.ravel().tolist(),
                "pointCount": int(self.effective_points.shape[0]),
            },
            "boundaryTangents": {
                "start": [float(v) for v in self.start_tangent],
                "end": [float(v) for v in self.end_tangent],
            },
            "report": self.report.to_dict(),
        }


@dataclass
class SmoothedDecline:
    status: str  # SUCCESS | SUCCESS_WITH_FALLBACK | FAILED
    segments: list[SmoothedSegment]
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        smoothed = sum(1 for s in self.segments if s.effective_source == "SMOOTHED")
        raw_len = float(sum(s.report.raw_length for s in self.segments))
        eff_len = float(
            sum(
                (s.report.smoothed_length or s.report.raw_length)
                if s.effective_source == "SMOOTHED"
                else s.report.raw_length
                for s in self.segments
            )
        )
        cost_raw = float(sum(s.report.field_cost_raw for s in self.segments))
        cost_eff = float(
            sum(
                s.report.field_cost_smoothed
                if s.effective_source == "SMOOTHED" and s.report.field_cost_smoothed is not None
                else s.report.field_cost_raw
                for s in self.segments
            )
        )
        radii = [
            s.report.min_plan_radius for s in self.segments if s.report.min_plan_radius is not None
        ]
        return {
            "status": self.status,
            "failureReason": self.failure_reason,
            "segments": [s.to_dict() for s in self.segments],
            "totals": {
                "segments": len(self.segments),
                "smoothedSegments": smoothed,
                "fallbackSegments": len(self.segments) - smoothed,
                "rawLength": raw_len,
                "effectiveLength": eff_len,
                "fieldCostRaw": cost_raw,
                "fieldCostEffective": cost_eff,
                "maxGradient": float(
                    max((s.report.max_gradient for s in self.segments), default=0.0)
                ),
                "minimumPlanRadius": float(min(radii)) if radii else None,
                "maxDeviation": float(
                    max((s.report.max_deviation_from_raw for s in self.segments), default=0.0)
                ),
            },
        }


@dataclass(frozen=True)
class RawSegment:
    """One selected Phase 04 segment reconstructed from the decline artifact."""

    level_id: str
    candidate_id: str
    primitives: list[Primitive]
    points: FloatArray
    start_heading: float
    end_heading: float

    @property
    def first_grade(self) -> float:
        return self.primitives[0].grade

    @property
    def last_grade(self) -> float:
        return self.primitives[-1].grade


def segments_from_decline_payload(payload: dict[str, Any], ps: PrimitiveSet) -> list[RawSegment]:
    """Rebuild the selected segments' analytic primitives from
    ``derived/decline.json`` (exact: same construction Phase 04 used), with
    the terminal sample pinned back to the stored exact endpoint."""
    out: list[RawSegment] = []
    for lv in payload["levels"]:
        sel_id = lv.get("selectedCandidateId")
        if sel_id is None:
            continue
        cand = next(c for c in lv["candidateResults"] if c["candidateId"] == sel_id)
        path = cand["path"]
        pts = np.asarray(path["points"], dtype=np.float64).reshape(-1, 3)
        pose = Pose(
            float(pts[0, 0]),
            float(pts[0, 1]),
            float(pts[0, 2]),
            math.radians(path["startHeadingDeg"]),
        )
        prims: list[Primitive] = []
        for spec in path["primitives"]:
            prim = ps.primitive(
                pose,
                Steering[spec["steering"]],
                float(spec["curvature"]),
                float(spec["grade"]),
                float(spec["horizontalLength"]),
            )
            prims.append(prim)
            pose = prim.end
        # pin the terminal sample/pose to the stored exact endpoint
        last = prims[-1]
        samples = last.samples.copy()
        samples[-1] = pts[-1]
        prims[-1] = Primitive(
            steering=last.steering,
            grade=last.grade,
            curvature=last.curvature,
            horizontal_length=last.horizontal_length,
            length_3d=last.length_3d,
            samples=samples,
            sample_arc=last.sample_arc,
            end=Pose(float(pts[-1, 0]), float(pts[-1, 1]), float(pts[-1, 2]), last.end.heading),
        )
        out.append(
            RawSegment(
                level_id=lv["levelId"],
                candidate_id=sel_id,
                primitives=prims,
                points=pts,
                start_heading=math.radians(path["startHeadingDeg"]),
                end_heading=math.radians(path["endHeadingDeg"]),
            )
        )
    return out


def boundary_grades(segments: list[RawSegment], max_gradient: float) -> list[tuple[float, float]]:
    """(start_grade, end_grade) per segment. Internal boundaries share the
    clamped mean of incoming/outgoing raw local grades (rule 61)."""
    grades: list[tuple[float, float]] = []
    for i, seg in enumerate(segments):
        start = seg.first_grade
        if i > 0:
            start = _clamp_grade((segments[i - 1].last_grade + seg.first_grade) / 2.0, max_gradient)
        end = seg.last_grade
        if i < len(segments) - 1:
            end = _clamp_grade((seg.last_grade + segments[i + 1].first_grade) / 2.0, max_gradient)
        grades.append((start, end))
    return grades


def _clamp_grade(g: float, max_gradient: float) -> float:
    return float(min(0.0, max(-max_gradient, g)))


class DeclineSmoother:
    def __init__(
        self,
        evaluator: DesignCostEvaluator,
        ramp: RampConstraints,
        cfg: SmoothingConfig,
    ) -> None:
        self.ev = evaluator
        self.ramp = ramp
        self.cfg = cfg
        self.segment_smoother = SegmentSmoother(evaluator, ramp, cfg)
        self.ps = PrimitiveSet(
            min_turn_radius=ramp.min_turn_radius,
            heading_bins=16,
            max_gradient=ramp.max_gradient,
            grade_fractions=(0.0, 0.5, 1.0),
            max_sample_spacing=2.0,
        )

    def smooth(self, decline_payload: dict[str, Any], on_progress: Any = None) -> SmoothedDecline:
        segments = segments_from_decline_payload(decline_payload, self.ps)
        if not segments:
            return SmoothedDecline(
                status="FAILED", segments=[], failure_reason="decline has no selected segments"
            )
        grades = boundary_grades(segments, self.ramp.max_gradient)
        min_cover = self.ev.context.minimum_surface_cover
        out: list[SmoothedSegment] = []
        any_fallback = False
        for i, (seg, (g_start, g_end)) in enumerate(zip(segments, grades, strict=True)):
            if on_progress is not None:
                on_progress(i, len(segments), seg.level_id, "SEGMENT_STARTED")
            cover_established = min_cover <= 0.0 or i > 0
            result = self.smooth_segment(seg, g_start, g_end, cover_established=cover_established)
            if result is None:  # raw itself failed revalidation
                return SmoothedDecline(
                    status="FAILED",
                    segments=out,
                    failure_reason=f"raw segment {seg.level_id} failed revalidation",
                )
            out.append(result)
            any_fallback = any_fallback or result.effective_source == "RAW_FALLBACK"
            if on_progress is not None:
                on_progress(i + 1, len(segments), seg.level_id, "SEGMENT_COMPLETED")
        return SmoothedDecline(
            status="SUCCESS_WITH_FALLBACK" if any_fallback else "SUCCESS", segments=out
        )

    # -- one segment -------------------------------------------------------- #

    def smooth_segment(
        self,
        seg: RawSegment,
        start_grade: float,
        end_grade: float,
        *,
        cover_established: bool,
    ) -> SmoothedSegment | None:
        cfg = self.cfg
        sm = self.segment_smoother
        raw_poly = seg.points
        raw_report = self._raw_report(seg, cover_established=cover_established)
        if raw_report is None:
            return None  # raw invalid → phase FAILED (rule 63)

        simplified = simplify_primitives(seg.primitives, self.ps)
        raw_controls, raw_tangents = control_grid(simplified, cfg.control_spacing, raw_poly[-1])
        controls = smooth_control_points(raw_controls, raw_poly, cfg)
        controls = feasible_controls(
            raw_controls,
            controls,
            raw_tangents,
            seg.start_heading,
            seg.end_heading,
            start_grade,
            end_grade,
            self.ramp.max_gradient,
            self.ramp.min_turn_radius,
            grade_tolerance=cfg.grade_numerical_tolerance,
        )

        report = SegmentReport(
            raw_length=raw_report.raw_length, field_cost_raw=raw_report.field_cost_raw
        )
        attempt = 0
        while True:
            curve = build_curve(
                controls,
                seg.start_heading,
                seg.end_heading,
                start_grade,
                end_grade,
                tangents_xy=blended_tangents(raw_controls, controls, raw_tangents),
                max_gradient=self.ramp.max_gradient,
            )
            report = SegmentReport(
                raw_length=raw_report.raw_length,
                field_cost_raw=raw_report.field_cost_raw,
                repairs=attempt,
            )
            violations = sm.validate_curve(
                curve, raw_poly, report, cover_established=cover_established
            )
            self._fill_smoothed_metrics(curve, seg, report, cover_established=cover_established)
            cost_ok = (
                report.field_cost_delta_pct is not None
                and report.field_cost_delta_pct <= cfg.max_field_cost_increase_pct + 1e-9
            )
            if not violations.any and cost_ok and self._endpoints_ok(report):
                report.valid = True
                report.effective_source = "SMOOTHED"
                eff = self._sample_effective(curve)
                return SmoothedSegment(
                    level_id=seg.level_id,
                    candidate_id=seg.candidate_id,
                    raw_points=raw_poly,
                    effective_points=eff,
                    effective_source="SMOOTHED",
                    report=report,
                    start_tangent=curve.start_tangent,
                    end_tangent=curve.end_tangent,
                )
            if attempt >= cfg.max_repairs:
                fb = raw_report
                fb.repairs = attempt
                fb.fallback_reason = self._fallback_reason(violations, cost_ok, report)
                fb.valid = True  # the raw centerline itself is validated
                fb.effective_source = "RAW_FALLBACK"
                return SmoothedSegment(
                    level_id=seg.level_id,
                    candidate_id=seg.candidate_id,
                    raw_points=raw_poly,
                    effective_points=raw_poly,
                    effective_source="RAW_FALLBACK",
                    report=fb,
                    start_tangent=boundary_tangent(seg.start_heading, start_grade),
                    end_tangent=boundary_tangent(seg.end_heading, end_grade),
                )
            attempt += 1
            controls = self._repair(controls, raw_controls, curve, violations, cost_ok)

    # -- helpers ------------------------------------------------------------ #

    def _raw_report(self, seg: RawSegment, *, cover_established: bool) -> SegmentReport | None:
        sm = self.segment_smoother
        pts = resample_polyline(seg.points, sm.validation_spacing)
        _, val, _ = evaluate_and_validate(
            self.ev, pts, cover_established=cover_established, stop_at_first=False
        )
        if not val.ok:
            return None
        report = SegmentReport(
            raw_length=float(polyline_arclength(seg.points)[-1]),
            field_cost_raw=sm.field_cost(pts, cover_established=cover_established),
            valid=True,
            effective_source="RAW_FALLBACK",
        )
        # geometry metrics of the raw path (exact samples lie on the arcs)
        report.max_gradient = float(max(abs(p.grade) for p in seg.primitives))
        radii = [p.radius for p in seg.primitives if math.isfinite(p.radius)]
        report.min_plan_radius = float(min(radii)) if radii else None
        return report

    def _fill_smoothed_metrics(
        self,
        curve: SegmentCurve,
        seg: RawSegment,
        report: SegmentReport,
        *,
        cover_established: bool,
    ) -> None:
        sm = self.segment_smoother
        total = float(curve.s[-1])
        n = max(3, math.ceil(total / sm.validation_spacing) + 1)
        sq = np.linspace(0.0, total, n)
        pts, _, _ = curve.sample(sq)
        report.smoothed_length = float(polyline_arclength(pts)[-1])
        report.field_cost_smoothed = sm.field_cost(pts, cover_established=cover_established)
        if report.field_cost_raw > 0:
            report.field_cost_delta_pct = (
                (report.field_cost_smoothed - report.field_cost_raw) / report.field_cost_raw * 100.0
            )
        report.endpoint_position_error = float(
            max(
                np.linalg.norm(pts[0] - seg.points[0]),
                np.linalg.norm(pts[-1] - seg.points[-1]),
            )
        )
        _, dxy0, _ = curve.sample(np.array([0.0]))
        _, dxy1, _ = curve.sample(np.array([total]))
        report.start_heading_error_deg = math.degrees(
            abs(_heading_error(dxy0[0], seg.start_heading))
        )
        report.end_heading_error_deg = math.degrees(abs(_heading_error(dxy1[0], seg.end_heading)))

    def _endpoints_ok(self, report: SegmentReport) -> bool:
        return (
            report.endpoint_position_error < 1e-6
            and report.start_heading_error_deg < math.degrees(1e-6)
            and report.end_heading_error_deg < math.degrees(1e-6)
        )

    def _sample_effective(self, curve: SegmentCurve) -> FloatArray:
        total = float(curve.s[-1])
        n = max(2, math.ceil(total / self.cfg.output_spacing) + 1)
        pts, _, _ = curve.sample(np.linspace(0.0, total, n))
        return pts

    def _fallback_reason(self, violations: Violations, cost_ok: bool, report: SegmentReport) -> str:
        parts: list[str] = []
        if report.invalid_sample_count:
            parts.append(f"{report.invalid_sample_count} invalid samples")
        if report.grade_violations:
            parts.append(f"{report.grade_violations} grade violations")
        if report.monotonicity_violations:
            parts.append(f"{report.monotonicity_violations} monotonicity violations")
        if report.radius_violations:
            parts.append(f"{report.radius_violations} plan-radius violations")
        if report.corridor_violations:
            parts.append(f"{report.corridor_violations} corridor violations")
        if not cost_ok and report.field_cost_delta_pct is not None:
            parts.append(f"field cost +{report.field_cost_delta_pct:.1f}%")
        if not self._endpoints_ok(report):
            parts.append("endpoint pose error")
        _ = violations
        return "; ".join(parts) if parts else "unspecified violation"

    def _repair(
        self,
        controls: FloatArray,
        raw_controls: FloatArray,
        curve: SegmentCurve,
        violations: Violations,
        cost_ok: bool,
    ) -> FloatArray:
        """Deterministic local repair (rule 63): blend the control window
        around every violating chainage toward raw by the repair factor. A
        field-cost violation has no chainage — blend the whole interior."""
        out = controls.copy()
        beta = self.cfg.repair_blend_factor
        n = out.shape[0]
        if violations.any:
            idx: set[int] = set()
            for c in violations.chainages:
                i = int(np.clip(np.searchsorted(curve.s, c), 1, n - 2))
                idx.update(range(max(1, i - 2), min(n - 1, i + 3)))
            sel = sorted(idx)
        else:
            sel = list(range(1, n - 1))  # cost violation: shrink smoothing everywhere
        _ = cost_ok
        for i in sel:
            out[i] = raw_controls[i] + (out[i] - raw_controls[i]) * (1.0 - beta)
        return out


def _heading_error(dxy: FloatArray, heading: float) -> float:
    actual = math.atan2(float(dxy[0]), float(dxy[1]))
    diff = (actual - heading + math.pi) % (2.0 * math.pi) - math.pi
    return diff
