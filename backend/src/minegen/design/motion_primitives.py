"""Motion primitives for the Chained Hybrid-A* decline generator
(CLAUDE.md rules 47–51).

Pose convention
---------------
``heading`` is an azimuth in radians, clockwise from +Y (North), matching
``docs/coordinate-system.md``. Horizontal unit vectors for heading θ:

    forward = ( sin θ,  cos θ )
    right   = ( cos θ, −sin θ )          (East when facing North)

Primitives
----------
Horizontal length ``Lh = R_min · Δθ`` for every primitive (rule 48).
Steering ∈ {LEFT (−1), STRAIGHT (0), RIGHT (+1)} turns by exactly one
heading bin; grade ∈ {0, −f·g_max} (rule 49), ``dz = grade · Lh`` as a
float (never rounded). A primitive is returned as a list of samples
(start … end) at spacing ≤ ``max_sample_spacing`` so that feasibility and
cost are evaluated along its whole length (rule 50).

Goal shot
---------
A constant-curvature horizontal arc from the current pose to the exact
target position (rule 51). In the pose-local frame with the target at
``(x forward, y right)``:

    k = 2y / (x² + y²),  R = 1/|k| ≥ R_min,  Δθ = 2·atan2(y, x)
    Lh = R·|Δθ| (or √(x²+y²) when straight),  grade = Δz / Lh ∈ [−g_max, 0]
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import IntEnum

import numpy as np
import numpy.typing as npt

from minegen.core.coordinates import wrap_angle_rad

FloatArray = npt.NDArray[np.float64]


class Steering(IntEnum):
    LEFT = -1
    STRAIGHT = 0
    RIGHT = 1


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    z: float
    heading: float  # radians, clockwise from North

    @property
    def position(self) -> FloatArray:
        return np.array([self.x, self.y, self.z])

    @property
    def forward(self) -> FloatArray:
        return np.array([math.sin(self.heading), math.cos(self.heading)])

    @property
    def right(self) -> FloatArray:
        return np.array([math.cos(self.heading), -math.sin(self.heading)])


@dataclass(frozen=True)
class Primitive:
    """One candidate motion: samples from the start pose (inclusive) to the
    end pose (inclusive), all in mine coordinates."""

    steering: Steering
    grade: float  # vertical / horizontal, ≤ 0
    curvature: float  # signed 1/R (+ right), 0 straight
    horizontal_length: float
    length_3d: float
    samples: FloatArray  # (n, 3)
    sample_arc: FloatArray  # (n,) cumulative 3D arc length
    end: Pose

    @property
    def radius(self) -> float:
        return math.inf if self.curvature == 0.0 else 1.0 / abs(self.curvature)


def dubins_cs_length(pose: Pose, target_xy: FloatArray, radius: float) -> float:
    """Horizontal length of the shortest turn-then-straight (CS) path from
    ``pose`` to ``target_xy`` with free final heading, minimum over both turn
    sides. If the target lies inside either turning circle the CS family is
    not guaranteed optimal (a CC path may be shorter), so the plain distance
    is returned instead; the result is therefore always a valid lower bound
    on the horizontal length of any feasible path."""
    px, py = pose.x, pose.y
    tx, ty = float(target_xy[0]), float(target_xy[1])
    d = math.hypot(tx - px, ty - py)
    if d < 1e-9:
        return 0.0
    rx, ry = math.cos(pose.heading), -math.sin(pose.heading)  # right unit vector
    best = math.inf
    for side in (1.0, -1.0):
        cx, cy = px + side * radius * rx, py + side * radius * ry
        vx, vy = tx - cx, ty - cy
        dc = math.hypot(vx, vy)
        if dc < radius - 1e-9:
            return d  # inside a turning circle: fall back to the trivial bound
        # angle of P and of the tangent point around C, measured in the turn direction
        ang_p = math.atan2(py - cy, px - cx)
        ang_t = math.atan2(vy, vx)
        alpha = math.acos(min(1.0, radius / dc))
        # for a right (clockwise) turn the tangent point precedes T by alpha in the
        # clockwise sense; for a left turn it follows T by alpha counter-clockwise
        ang_q = ang_t + side * alpha
        turned = (ang_p - ang_q) if side > 0 else (ang_q - ang_p)
        turned %= 2.0 * math.pi
        if turned > 2.0 * math.pi - 1e-9:  # −ε wrapped to a full circle: the target is dead ahead
            turned = 0.0
        best = min(best, radius * turned + math.sqrt(max(dc * dc - radius * radius, 0.0)))
    return best


def azimuth_between(a: FloatArray, b: FloatArray) -> float:
    """Heading (rad, clockwise from North) of the horizontal vector a → b."""
    d = np.asarray(b)[:2] - np.asarray(a)[:2]
    return math.atan2(float(d[0]), float(d[1]))


def arc_points(
    pose: Pose, curvature: float, horizontal_length: float, grade: float, n_samples: int
) -> tuple[FloatArray, float]:
    """Sample a constant-curvature horizontal arc (or straight) with linear
    descent. Returns ``(points (n,3), end_heading)``."""
    s = np.linspace(0.0, horizontal_length, n_samples)
    f, r = pose.forward, pose.right
    if abs(curvature) < 1e-12:
        xy = pose.position[None, :2] + s[:, None] * f[None, :]
        end_heading = pose.heading
    else:
        radius = 1.0 / abs(curvature)
        phi = s / radius  # turned angle at each sample
        side = 1.0 if curvature > 0 else -1.0
        along = radius * np.sin(phi)
        lateral = side * radius * (1.0 - np.cos(phi))
        xy = pose.position[None, :2] + along[:, None] * f[None, :] + lateral[:, None] * r[None, :]
        end_heading = wrap_angle_rad(pose.heading + side * horizontal_length / radius)
    z = pose.z + grade * s
    return np.column_stack([xy, z]), end_heading


def _n_samples(length_3d: float, max_spacing: float) -> int:
    return max(2, math.ceil(length_3d / max_spacing) + 1)


@dataclass(frozen=True)
class PrimitiveSet:
    min_turn_radius: float
    heading_bins: int
    max_gradient: float
    grade_fractions: tuple[float, ...]
    max_sample_spacing: float

    @property
    def heading_step(self) -> float:
        return 2.0 * math.pi / self.heading_bins

    @property
    def horizontal_length(self) -> float:
        return self.min_turn_radius * self.heading_step

    @property
    def grades(self) -> tuple[float, ...]:
        return tuple(sorted({-f * self.max_gradient for f in self.grade_fractions}, reverse=True))

    @property
    def branching_factor(self) -> int:
        return 3 * len(self.grades)

    def _template(
        self,
    ) -> list[tuple[Steering, float, float, float, FloatArray, FloatArray, float]]:
        """Pose-local sample pattern for the 9 expansion primitives, built once:
        (steering, curvature, grade, length_3d, local (n,3) [forward, right, dz],
        cumulative arc, heading change). ``expand`` only rotates and translates."""
        cached = getattr(self, "_tmpl", None)
        if cached is not None:
            return list(cached)
        tmpl = []
        lh = self.horizontal_length
        origin = Pose(0.0, 0.0, 0.0, 0.0)  # heading 0 → forward = +y, right = +x
        for steering in (Steering.LEFT, Steering.STRAIGHT, Steering.RIGHT):
            curvature = float(steering) / self.min_turn_radius
            for grade in self.grades:
                length_3d = lh * math.sqrt(1.0 + grade * grade)
                n = _n_samples(length_3d, self.max_sample_spacing)
                pts, end_heading = arc_points(origin, curvature, lh, grade, n)
                # pts columns: x = right, y = forward, z = dz (heading 0 frame)
                local = np.column_stack([pts[:, 1], pts[:, 0], pts[:, 2]])
                tmpl.append(
                    (
                        steering,
                        curvature,
                        grade,
                        length_3d,
                        local,
                        np.linspace(0.0, length_3d, n),
                        end_heading,
                    )
                )
        object.__setattr__(self, "_tmpl", tuple(tmpl))
        return tmpl

    def expand(self, pose: Pose) -> list[Primitive]:
        fx, fy = math.sin(pose.heading), math.cos(pose.heading)
        rx, ry = fy, -fx
        out: list[Primitive] = []
        for steering, curvature, grade, length_3d, local, arc, dh in self._template():
            fwd, rgt, dz = local[:, 0], local[:, 1], local[:, 2]
            samples = np.empty_like(local)
            samples[:, 0] = pose.x + fwd * fx + rgt * rx
            samples[:, 1] = pose.y + fwd * fy + rgt * ry
            samples[:, 2] = pose.z + dz
            end = Pose(
                float(samples[-1, 0]),
                float(samples[-1, 1]),
                float(samples[-1, 2]),
                wrap_angle_rad(pose.heading + dh),
            )
            out.append(
                Primitive(
                    steering=steering,
                    grade=grade,
                    curvature=curvature,
                    horizontal_length=self.horizontal_length,
                    length_3d=length_3d,
                    samples=samples,
                    sample_arc=arc,
                    end=end,
                )
            )
        return out

    def primitive(
        self,
        pose: Pose,
        steering: Steering,
        curvature: float,
        grade: float,
        horizontal_length: float,
    ) -> Primitive:
        length_3d = horizontal_length * math.sqrt(1.0 + grade * grade)
        n = _n_samples(length_3d, self.max_sample_spacing)
        pts, end_heading = arc_points(pose, curvature, horizontal_length, grade, n)
        arc = np.linspace(0.0, length_3d, n)
        end = Pose(float(pts[-1, 0]), float(pts[-1, 1]), float(pts[-1, 2]), end_heading)
        return Primitive(
            steering=steering,
            grade=grade,
            curvature=curvature,
            horizontal_length=horizontal_length,
            length_3d=length_3d,
            samples=pts,
            sample_arc=arc,
            end=end,
        )

    # -- goal shot (rule 51) ------------------------------------------------ #

    def _pin(self, prim: Primitive, target: FloatArray) -> Primitive:
        samples = prim.samples.copy()
        samples[-1] = target
        end = Pose(float(target[0]), float(target[1]), float(target[2]), prim.end.heading)
        return Primitive(
            steering=prim.steering,
            grade=prim.grade,
            curvature=prim.curvature,
            horizontal_length=prim.horizontal_length,
            length_3d=prim.length_3d,
            samples=samples,
            sample_arc=prim.sample_arc,
            end=end,
        )

    def _grade_for(self, dz: float, horizontal_length: float) -> tuple[float | None, str]:
        if horizontal_length < 1e-9:
            return None, "ZERO_CHORD"
        grade = dz / horizontal_length
        if grade > 1e-9:
            return None, "TARGET_ABOVE_STATE"
        if grade < -self.max_gradient - 1e-9:
            return None, "GRADE_EXCEEDS_MAXIMUM"
        return min(grade, 0.0), "OK"

    def goal_shot_arc(
        self, pose: Pose, target: FloatArray, max_heading_change: float
    ) -> tuple[list[Primitive] | None, str]:
        """Single constant-curvature arc (or straight) to the exact target."""
        t = np.asarray(target, dtype=np.float64)
        d = t[:2] - pose.position[:2]
        x = float(np.dot(d, pose.forward))
        y = float(np.dot(d, pose.right))
        chord2 = x * x + y * y
        if chord2 < 1e-12:
            return None, "ZERO_CHORD"
        k = 2.0 * y / chord2
        if abs(k) < 1e-9:
            curvature, horizontal_length, dtheta = 0.0, math.sqrt(chord2), 0.0
        else:
            radius = 1.0 / abs(k)
            if radius < self.min_turn_radius - 1e-9:
                return None, "RADIUS_BELOW_MINIMUM"
            dtheta = 2.0 * math.atan2(y, x)
            curvature = k
            horizontal_length = radius * abs(dtheta)
        if abs(dtheta) > max_heading_change + 1e-12:
            return None, "HEADING_CHANGE_TOO_LARGE"
        grade, reason = self._grade_for(float(t[2] - pose.z), horizontal_length)
        if grade is None:
            return None, reason
        steering = (
            Steering.STRAIGHT
            if curvature == 0.0
            else (Steering.RIGHT if curvature > 0 else Steering.LEFT)
        )
        return [
            self._pin(self.primitive(pose, steering, curvature, grade, horizontal_length), t)
        ], "OK"

    def goal_shot_arc_straight(
        self, pose: Pose, target: FloatArray, max_heading_change: float
    ) -> tuple[list[Primitive] | None, str]:
        """Turn on the minimum-radius circle (either side) until the heading
        points at the target, then run straight to it. The turned angle φ is
        the root of ``azimuth(T − Q(φ)) − (θ + φ)`` found by scan + bisection."""
        t = np.asarray(target, dtype=np.float64)
        r = self.min_turn_radius
        best: tuple[float, float, float] | None = None  # (|φ|, signed φ, straight length)
        for side in (1.0, -1.0):

            def q(phi: float, side: float = side) -> FloatArray:
                return (
                    pose.position[:2]
                    + r * math.sin(phi) * pose.forward
                    + side * r * (1.0 - math.cos(phi)) * pose.right
                )

            def mismatch(phi: float, side: float = side) -> float:
                dq = t[:2] - q(phi, side)
                if float(np.linalg.norm(dq)) < 1e-9:
                    return 0.0
                return wrap_angle_rad(
                    math.atan2(float(dq[0]), float(dq[1])) - (pose.heading + side * phi)
                )

            n = max(8, int(math.degrees(max_heading_change)))
            phis = np.linspace(0.0, max_heading_change, n + 1)
            vals = [mismatch(float(p)) for p in phis]
            for i in range(n):
                a, b = float(phis[i]), float(phis[i + 1])
                fa, fb = vals[i], vals[i + 1]
                if abs(fa) < 1e-12:
                    root = a
                elif fa * fb < 0 and abs(fa - fb) < math.pi:  # genuine sign change, not a wrap
                    for _ in range(40):
                        m = 0.5 * (a + b)
                        fm = mismatch(m)
                        if fa * fm <= 0:
                            b, fb = m, fm
                        else:
                            a, fa = m, fm
                    root = 0.5 * (a + b)
                else:
                    continue
                straight = float(
                    np.dot(
                        t[:2] - q(root),
                        np.array(
                            [
                                math.sin(pose.heading + side * root),
                                math.cos(pose.heading + side * root),
                            ]
                        ),
                    )
                )
                if straight < -1e-6:
                    continue
                if best is None or root < best[0]:
                    best = (root, side * root, max(straight, 0.0))
                break
        if best is None:
            return None, "NO_TANGENT"
        phi_abs, phi_signed, straight = best
        arc_len = r * phi_abs
        total_h = arc_len + straight
        grade, reason = self._grade_for(float(t[2] - pose.z), total_h)
        if grade is None:
            return None, reason
        prims: list[Primitive] = []
        cur = pose
        if arc_len > 1e-9:
            steering = Steering.RIGHT if phi_signed > 0 else Steering.LEFT
            arc = self.primitive(cur, steering, float(steering) / r, grade, arc_len)
            prims.append(arc)
            cur = arc.end
        if straight > 1e-9:
            prims.append(self.primitive(cur, Steering.STRAIGHT, 0.0, grade, straight))
        if not prims:
            return None, "ZERO_CHORD"
        prims[-1] = self._pin(prims[-1], t)
        return prims, "OK"

    def goal_shot(
        self, pose: Pose, target: FloatArray, max_heading_change: float
    ) -> tuple[list[Primitive] | None, str]:
        """Exact connector to ``target``: single arc first, then arc + straight.
        The returned primitives' last sample *is* the target."""
        prims, reason = self.goal_shot_arc(pose, target, max_heading_change)
        if prims is not None:
            return prims, "OK"
        prims2, reason2 = self.goal_shot_arc_straight(pose, target, max_heading_change)
        if prims2 is not None:
            return prims2, "OK"
        return None, f"{reason}|{reason2}"
