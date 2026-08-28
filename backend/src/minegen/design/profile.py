"""Tunnel cross-section profile + excavation-envelope geometry (rules 65–67).

This is the LOW-LEVEL shared module: both the Phase 04 Hybrid-A* feasibility
check and the Phase 06 mesh builder consume it, so the search validates
exactly the geometry the mesh will excavate. It must not import the search
or the mesh builder.

The centerline is the tunnel FLOOR centerline; profile dimensions come
exclusively from ``RampConstraints``; the circular crown radius is DERIVED
from (width, height, wall_height). The engineering profile area is the exact
ANALYTIC circular D-profile area — the tessellated polygon area is reported
separately so nominal excavation volume never depends on ``arch_segments``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from minegen.core.models import RampConstraints, TunnelProfile

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class ProfileShape:
    """Closed horseshoe cross-section in local (right, up) coordinates with
    the floor centerline at the origin. Vertex order (K = arch_segments + 3):
    floor_R, wall_R(top), arch interior …, wall_L(top), floor_L (counter-
    clockwise); the closing edge floor_L → floor_R is the floor."""

    points: FloatArray  # (K, 2) local (x=right, y=up), counter-clockwise
    mesh_area: float  # tessellated polygon area (shoelace)
    analytic_area: float  # exact rectangle + circular-segment area (rule 67)
    perimeter_u: FloatArray  # (K+1,) cumulative perimeter fraction incl. seam
    crown_radius: float
    crown_center_y: float
    centroid: FloatArray  # (2,) polygon centroid (cap fan apex, rule 66)

    @property
    def k(self) -> int:
        return int(self.points.shape[0])

    @property
    def tessellation_bias_pct(self) -> float:
        """(mesh − analytic) / analytic × 100 — the inscribed polygon is
        always smaller, so this is ≤ 0 and shrinks ~1/n² with arch_segments."""
        return (self.mesh_area - self.analytic_area) / self.analytic_area * 100.0


def build_profile(ramp: RampConstraints, profile: TunnelProfile) -> ProfileShape:
    width = ramp.tunnel_width
    height = ramp.tunnel_height
    wall_h = profile.wall_height
    if wall_h >= height:
        raise ValueError(
            f"wall_height ({wall_h:g}) must be smaller than tunnel_height ({height:g})"
        )
    a = width / 2.0
    rise = height - wall_h
    crown_radius = (a * a + rise * rise) / (2.0 * rise)
    center_y = height - crown_radius  # arch circle center on the profile axis
    # exact analytic area: wall rectangle + circular segment above the chord
    # at wall height (chord half-length a, central angle 2·asin(a/Rc))
    theta = 2.0 * math.asin(min(1.0, a / crown_radius))
    analytic_area = width * wall_h + crown_radius * crown_radius * (theta - math.sin(theta)) / 2.0
    # arch from wall_R top (a, wall_h) counter-clockwise over the crown
    theta_r = math.atan2(wall_h - center_y, a)
    theta_l = math.atan2(wall_h - center_y, -a)
    n = profile.arch_segments
    if theta_l < theta_r:
        theta_l += 2.0 * math.pi
    thetas = np.linspace(theta_r, theta_l, n + 1)
    arch = np.column_stack(
        [crown_radius * np.cos(thetas), center_y + crown_radius * np.sin(thetas)]
    )
    pts = np.vstack(
        [
            [a, 0.0],  # floor_R
            arch,  # wall_R top … wall_L top (n+1 points)
            [-a, 0.0],  # floor_L
        ]
    )
    # shoelace area (must be positive: counter-clockwise by construction)
    x, y = pts[:, 0], pts[:, 1]
    xn, yn = np.roll(x, -1), np.roll(y, -1)
    mesh_area = 0.5 * float(np.sum(x * yn - xn * y))
    if mesh_area <= 0:
        raise ValueError("profile construction is not counter-clockwise")
    cx = float(np.sum((x + xn) * (x * yn - xn * y)) / (6.0 * mesh_area))
    cy = float(np.sum((y + yn) * (x * yn - xn * y)) / (6.0 * mesh_area))
    edges = np.linalg.norm(np.diff(np.vstack([pts, pts[:1]]), axis=0), axis=1)
    perim = float(edges.sum())
    u = np.concatenate([[0.0], np.cumsum(edges)]) / perim
    return ProfileShape(
        points=pts,
        mesh_area=mesh_area,
        analytic_area=analytic_area,
        perimeter_u=u,
        crown_radius=crown_radius,
        crown_center_y=center_y,
        centroid=np.array([cx, cy]),
    )


def profile_envelope_reach(ramp: RampConstraints, profile: TunnelProfile) -> float:
    """Maximal distance of any profile vertex from the floor centerline
    (5.0 m for the default 5×5 profile — the crown apex). The 1-Lipschitz
    sufficient-condition margin for isotropic exclusion clearance; the
    direction-aware feasibility check below is the exact contract."""
    shape = build_profile(ramp, profile)
    return float(np.linalg.norm(shape.points, axis=1).max())


def gravity_frames(tangents: FloatArray) -> tuple[FloatArray, FloatArray]:
    """Vectorized rule-26 gravity-aligned frame for N unit tangents:
    ``up = normalize(Z − (Z·t)t)``, ``right = t × up`` — row-for-row equal to
    ``core.coordinates.gravity_aligned_frame`` (tested). Requires non-vertical
    tangents (guaranteed: grade ≤ max_gradient)."""
    t = np.asarray(tangents, dtype=np.float64)
    up = -t[:, 2:3] * t
    up[:, 2] += 1.0
    up = up / np.linalg.norm(up, axis=1, keepdims=True)
    right = np.cross(t, up)
    return right, up


def boundary_points(centers: FloatArray, tangents: FloatArray, shape: ProfileShape) -> FloatArray:
    """Excavation-envelope sample points: the K profile vertices swept to
    every (center, tangent) with the shared gravity-aligned frame →
    ``(N, K, 3)``. This single function feeds BOTH the Phase 04 feasibility
    check and the Phase 06 mesh, so they validate identical geometry."""
    right, up = gravity_frames(tangents)
    x = shape.points[:, 0]
    y = shape.points[:, 1]
    return (
        centers[:, None, :]
        + x[None, :, None] * right[:, None, :]
        + y[None, :, None] * up[:, None, :]
    )
