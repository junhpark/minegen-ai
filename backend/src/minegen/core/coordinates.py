"""Canonical coordinate conventions and frame utilities.

Everything here is ENU Z-up meters (``docs/coordinate-system.md``).
There is deliberately no Three.js conversion in this module (CLAUDE.md rule 4).

Functions accept and return NumPy arrays of shape ``(3,)`` or ``(N, 3)`` so
they can be used both for single points and for bulk field evaluation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

Vec3 = npt.NDArray[np.float64]

GLOBAL_UP: Vec3 = np.array([0.0, 0.0, 1.0])
_EPS = 1e-12


def normalize(v: Vec3) -> Vec3:
    """Unit vector along ``v``. Raises on zero-length input."""
    n = float(np.linalg.norm(v))
    if n < _EPS:
        raise ValueError("cannot normalize a zero-length vector")
    return np.asarray(v, dtype=np.float64) / n


# --------------------------------------------------------------------------- #
# Headings / azimuths
# --------------------------------------------------------------------------- #


def azimuth_to_unit_vector(azimuth_deg: float) -> Vec3:
    """Horizontal unit vector for a clockwise-from-North azimuth."""
    a = math.radians(azimuth_deg)
    return np.array([math.sin(a), math.cos(a), 0.0])


def unit_vector_to_azimuth(v: Vec3) -> float:
    """Clockwise-from-North azimuth in ``[0, 360)`` of the horizontal
    projection of ``v``. Vertical vectors raise."""
    x, y = float(v[0]), float(v[1])
    if abs(x) < _EPS and abs(y) < _EPS:
        raise ValueError("vector has no horizontal component")
    return math.degrees(math.atan2(x, y)) % 360.0


def wrap_angle_rad(a: float) -> float:
    """Wrap to ``(-pi, pi]``."""
    return (a + math.pi) % (2.0 * math.pi) - math.pi


# --------------------------------------------------------------------------- #
# Strike / dip orebody frame (rule 28)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Frame:
    """Right-handed orthonormal frame with an origin.

    ``axes`` rows are the three unit vectors expressed in world coordinates.
    ``world_to_local`` / ``local_to_world`` are rigid transforms."""

    origin: Vec3
    axes: npt.NDArray[np.float64]  # shape (3, 3), rows = local axes in world coords

    def world_to_local(self, p: Vec3) -> Vec3:
        return np.asarray(np.asarray(p, dtype=np.float64) - self.origin) @ self.axes.T

    def local_to_world(self, q: Vec3) -> Vec3:
        return np.asarray(np.asarray(q, dtype=np.float64) @ self.axes + self.origin)

    @property
    def is_right_handed(self) -> bool:
        return bool(np.linalg.det(self.axes) > 0.0)


def strike_dip_vectors(strike_deg: float, dip_deg: float) -> tuple[Vec3, Vec3, Vec3]:
    """Orebody-local unit vectors ``(u, v, w)``.

    * ``u`` along strike (horizontal)
    * ``v`` down dip, horizontal azimuth = strike + 90°
    * ``w = u × v``: plane normal pointing **downward to the footwall side**

    ``(u, v, w)`` is right-handed. See ``docs/coordinate-system.md``.
    """
    s = math.radians(strike_deg)
    d = math.radians(dip_deg)
    u = np.array([math.sin(s), math.cos(s), 0.0])
    dip_dir_h = azimuth_to_unit_vector(strike_deg + 90.0)
    v = math.cos(d) * dip_dir_h + np.array([0.0, 0.0, -math.sin(d)])
    w = np.cross(u, v)
    return normalize(u), normalize(v), normalize(w)


def strike_dip_frame(origin: Vec3, strike_deg: float, dip_deg: float) -> Frame:
    u, v, w = strike_dip_vectors(strike_deg, dip_deg)
    return Frame(origin=np.asarray(origin, dtype=np.float64), axes=np.vstack([u, v, w]))


# --------------------------------------------------------------------------- #
# Gravity-aligned tunnel sweep frame (rule 26)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SweepFrame:
    right: Vec3
    forward: Vec3
    up: Vec3


def gravity_aligned_frame(tangent: Vec3, *, max_vertical_cos: float = 0.95) -> SweepFrame:
    """Sweep frame for ordinary tunnels: ``up`` is global Z projected
    perpendicular to the tangent, so the floor never banks.

    Raises if the tangent is within ``acos(max_vertical_cos)`` of vertical;
    those cases (raises, shafts) need a parallel-transport frame (v0.2).
    """
    forward = normalize(tangent)
    c = float(np.dot(GLOBAL_UP, forward))
    if abs(c) >= max_vertical_cos:
        raise ValueError(
            f"tangent is too close to vertical (|cos|={abs(c):.3f}); "
            "gravity-aligned frame is undefined, use a parallel-transport frame"
        )
    up = normalize(GLOBAL_UP - c * forward)
    right = normalize(np.cross(forward, up))
    return SweepFrame(right=right, forward=forward, up=up)


# --------------------------------------------------------------------------- #
# Gradient helpers (rule 25)
# --------------------------------------------------------------------------- #


def gradient_of(p0: Vec3, p1: Vec3) -> float:
    """Signed gradient (vertical / horizontal) from ``p0`` to ``p1``.
    Returns ``inf`` for a purely vertical step."""
    d = np.asarray(p1, dtype=np.float64) - np.asarray(p0, dtype=np.float64)
    horizontal = math.hypot(float(d[0]), float(d[1]))
    if horizontal < _EPS:
        return math.inf if abs(float(d[2])) > _EPS else 0.0
    return float(d[2]) / horizontal


def grade_limited_length(dz: float, max_gradient: float) -> float:
    """Minimum 3D centerline length needed to change elevation by ``dz``
    without exceeding ``max_gradient`` (vertical/horizontal)."""
    if max_gradient <= 0:
        raise ValueError("max_gradient must be positive")
    horizontal_min = abs(dz) / max_gradient
    return math.hypot(horizontal_min, dz)


def decline_heuristic_distance(p: Vec3, goal: Vec3, max_gradient: float) -> float:
    """Admissible lower bound on remaining centerline length (rule 25)."""
    euclid = float(np.linalg.norm(np.asarray(goal, dtype=np.float64) - np.asarray(p)))
    return max(euclid, grade_limited_length(float(goal[2]) - float(p[2]), max_gradient))
