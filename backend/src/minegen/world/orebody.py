"""Orebody geometry contracts and the analytic reference bodies.

The orebody solid is the ONLY authority for mineralized-domain membership
(rule 129): access targets (Phase 03) and stopes (Phase 09) are derived from
it, and the numerical field lattice never defines ore/waste geometry. It is
never reconstructed from voxels.

Phase 19 splits the contract honestly (rule 134):

``AnalyticOrebody``
    TABULAR / ELLIPSOID — closed-form solids with an EXACT Euclidean signed
    distance (``signed_distance``), exact/analytic volume and bounding box.
``ImplicitOrebody``
    WARPED_VEIN (``world/warped_vein.py``) — defined by a smooth implicit
    membership function ``level`` (φ < 0 inside). Only a lattice-derived,
    explicitly APPROXIMATE signed clearance exists; it is never called an
    SDF and never drives hard engineering buffers (rule 135).

Frame convention (CLAUDE.md rule 28, ``docs/coordinate-system.md``):
``u`` along strike, ``v`` down dip, ``w = u × v`` to the footwall side.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.core.coordinates import Frame, strike_dip_frame
from minegen.core.enums import DistanceContract, OrebodyType
from minegen.core.models import OrebodyConfig

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]


class Orebody(ABC):
    """Shape-neutral orebody interface (rule 120: one solid — ``contains``,
    ``volume``, ``bounding_box`` and ``mesh`` describe the same geometry).

    Distance queries are NOT part of this base contract: they differ by
    ``distance_contract`` (rule 134) and live on the two sub-interfaces."""

    config: OrebodyConfig
    frame: Frame

    @property
    @abstractmethod
    def distance_contract(self) -> DistanceContract: ...

    @abstractmethod
    def contains(self, points: FloatArray) -> BoolArray:
        """Authoritative inclusion test for world points of shape ``(..., 3)``."""

    @abstractmethod
    def volume(self) -> float:
        """Solid volume in m³ (exact for analytic bodies, a documented
        deterministic numerical estimate for implicit bodies). Geometric
        only — never a resource, reserve or recoverable figure."""

    @abstractmethod
    def bounding_box(self) -> tuple[FloatArray, FloatArray]:
        """Axis-aligned world bounds ``(min, max)`` guaranteed to contain
        the whole solid (tight for analytic bodies, conservative for
        implicit ones)."""

    @abstractmethod
    def mesh(self) -> tuple[FloatArray, npt.NDArray[np.int32]]:
        """Triangle mesh ``(vertices (N,3), faces (M,3))`` in world coords —
        a DERIVATIVE of the solid for rendering; never membership."""

    def to_local(self, points: FloatArray) -> FloatArray:
        return self.frame.world_to_local(points)

    def to_world(self, local: FloatArray) -> FloatArray:
        return self.frame.local_to_world(local)

    @property
    def center(self) -> FloatArray:
        return np.asarray(self.frame.origin, dtype=np.float64)

    @property
    def u(self) -> FloatArray:
        return np.asarray(self.frame.axes[0], dtype=np.float64)

    @property
    def v(self) -> FloatArray:
        return np.asarray(self.frame.axes[1], dtype=np.float64)

    @property
    def w(self) -> FloatArray:
        """Unit normal toward the footwall side (downward for dip < 90°)."""
        return np.asarray(self.frame.axes[2], dtype=np.float64)

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """JSON-safe description (no arrays larger than a few vectors)."""


class AnalyticOrebody(Orebody):
    """Closed-form solid with an EXACT Euclidean signed distance. The legacy
    Phase 03–18 design pipeline (hard orebody exclusion buffers) accepts
    only this contract (rule 135)."""

    @property
    def distance_contract(self) -> DistanceContract:
        return DistanceContract.EXACT_METRIC_SDF

    @abstractmethod
    def signed_distance(self, points: FloatArray) -> FloatArray:
        """Exact signed distance to the solid's surface for world points of
        shape ``(..., 3)``: negative inside, zero on the surface, positive
        outside (Euclidean distance to the nearest surface point)."""


class ImplicitOrebody(Orebody):
    """Solid defined by a smooth implicit membership function φ
    (rule 133): ``contains`` is ``level(points) <= 0`` and nothing else.
    Distance is available only as a DERIVED, explicitly approximate signed
    clearance whose sign is forced to agree with ``contains``."""

    @property
    def distance_contract(self) -> DistanceContract:
        return DistanceContract.DERIVED_APPROXIMATE_CLEARANCE

    @abstractmethod
    def level(self, points: FloatArray) -> FloatArray:
        """Dimensionless implicit value φ for world points ``(..., 3)``:
        φ < 0 inside, φ = 0 on the boundary, φ > 0 outside. NOT a metric
        distance."""

    @abstractmethod
    def approximate_clearance(self, points: FloatArray) -> FloatArray:
        """Lattice-derived approximate signed Euclidean clearance (m):
        negative inside, positive outside, sign guaranteed to agree with
        ``contains``. Never an exact SDF; see ``clearance_info``."""

    @abstractmethod
    def clearance_info(self) -> dict[str, Any]:
        """Metadata of the clearance approximation: contract, lattice
        spacing, method, error estimate."""


@dataclass(init=False)
class TabularOrebody(AnalyticOrebody):
    """Rectangular slab: ``|u| ≤ length/2``, ``|v| ≤ height/2`` (down-dip),
    ``|w| ≤ thickness/2``. The legacy Phase 03–18 layout (targets, levels,
    stopes) is typed against THIS class, not the generic interface."""

    config: OrebodyConfig
    frame: Frame

    def __init__(self, config: OrebodyConfig) -> None:
        if config.orebody_type is not OrebodyType.TABULAR:
            raise ValueError(f"TabularOrebody requires TABULAR, got {config.orebody_type}")
        self.config = config
        self.frame = strike_dip_frame(
            np.array(config.center.as_tuple()), config.strike_deg, config.dip_deg
        )

    # -- extents ----------------------------------------------------------- #

    @property
    def half_length(self) -> float:
        return self.config.length / 2.0

    @property
    def half_height(self) -> float:
        return self.config.height / 2.0

    @property
    def half_thickness(self) -> float:
        return self.config.thickness / 2.0

    @property
    def half_extents(self) -> FloatArray:
        return np.array([self.half_length, self.half_height, self.half_thickness])

    def footwall_point(self, local_u: float, local_v: float, offset: float) -> FloatArray:
        """World point on the footwall side of the slab: at in-plane local
        coordinates ``(local_u, local_v)``, displaced ``offset`` metres past
        the footwall contact along ``+w``. Used by Phase 03 access targets.
        Tabular-only: an irregular body has no global footwall plane."""
        w_local = self.half_thickness + offset
        return self.to_world(np.array([local_u, local_v, w_local]))

    # -- geometry ---------------------------------------------------------- #

    def contains(self, points: FloatArray) -> BoolArray:
        local = self.to_local(np.asarray(points, dtype=np.float64))
        return np.asarray(np.all(np.abs(local) <= self.half_extents, axis=-1))

    def signed_distance(self, points: FloatArray) -> FloatArray:
        """Oriented-box SDF in the local frame:
        ``q = |local| − half``, ``sdf = ‖max(q, 0)‖ + min(max(q), 0)``."""
        local = self.to_local(np.asarray(points, dtype=np.float64))
        q = np.abs(local) - self.half_extents
        outside = np.linalg.norm(np.maximum(q, 0.0), axis=-1)
        inside = np.minimum(np.max(q, axis=-1), 0.0)
        return np.asarray(outside + inside)

    def volume(self) -> float:
        return self.config.length * self.config.height * self.config.thickness

    def corners(self) -> FloatArray:
        """Eight world-space corners, ordered by local sign pattern."""
        h = self.half_extents
        signs = np.array(
            [[sx, sy, sz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)],
            dtype=np.float64,
        )
        return self.to_world(signs * h)

    def bounding_box(self) -> tuple[FloatArray, FloatArray]:
        c = self.corners()
        return c.min(axis=0), c.max(axis=0)

    def mesh(self) -> tuple[FloatArray, npt.NDArray[np.int32]]:
        """Box mesh with outward-facing CCW triangles (right-handed frame,
        handedness preserved by the world transform)."""
        verts = self.corners()
        # corner index = 4*ix + 2*iy + iz with (ix, iy, iz) ∈ {0,1} for (-,+)
        faces = np.array(
            [
                # -w face (hanging-wall side, normal along -w)
                [0, 2, 6],
                [0, 6, 4],
                # +w face (footwall side)
                [1, 5, 7],
                [1, 7, 3],
                # -u face
                [0, 1, 3],
                [0, 3, 2],
                # +u face
                [4, 6, 7],
                [4, 7, 5],
                # -v face
                [0, 4, 5],
                [0, 5, 1],
                # +v face
                [2, 3, 7],
                [2, 7, 6],
            ],
            dtype=np.int32,
        )
        return verts, faces

    @property
    def z_range(self) -> tuple[float, float]:
        lo, hi = self.bounding_box()
        return float(lo[2]), float(hi[2])

    def to_dict(self) -> dict[str, Any]:
        lo, hi = self.bounding_box()
        return {
            "type": self.config.orebody_type.value,
            "center": self.center.tolist(),
            "u": self.u.tolist(),
            "v": self.v.tolist(),
            "w": self.w.tolist(),
            "halfExtents": self.half_extents.tolist(),
            "volumeM3": self.volume(),
            "volumeMethod": "analytic",
            "distanceContract": self.distance_contract.value,
            "bboxMin": lo.tolist(),
            "bboxMax": hi.tolist(),
        }


class EllipsoidOrebody(AnalyticOrebody):
    """Triaxial ellipsoid in the strike/dip frame (Phase 17): semi-axes are
    ``length/2`` along strike (u), ``height/2`` down dip (v) and
    ``thickness/2`` across (w) — i.e. the ellipsoid inscribed in the
    equivalent tabular slab, so every existing OrebodyConfig field keeps
    its meaning and the persisted schema is unchanged.

    ``signed_distance`` is the EXACT Euclidean distance (rule: the SDF,
    ``contains``, ``volume``, ``bounding_box`` and ``mesh`` all describe
    the SAME solid). The nearest-point problem for an axis-aligned
    ellipsoid is solved per point via the classic largest-root equation

        f(t) = Σ (aᵢ pᵢ / (aᵢ² + t))² − 1 = 0,   t ∈ (−min(aᵢ²), ∞)

    (Eberly), using a deterministic bisection — no iteration-count or
    seed dependence, mypy/NumPy only.
    """

    config: OrebodyConfig
    frame: Frame

    def __init__(self, config: OrebodyConfig) -> None:
        if config.orebody_type is not OrebodyType.ELLIPSOID:
            raise ValueError(f"EllipsoidOrebody requires ELLIPSOID, got {config.orebody_type}")
        self.config = config
        self.frame = strike_dip_frame(
            np.array(config.center.as_tuple()), config.strike_deg, config.dip_deg
        )

    # -- extents ----------------------------------------------------------- #

    @property
    def semi_axes(self) -> FloatArray:
        return np.array(
            [self.config.length / 2.0, self.config.height / 2.0, self.config.thickness / 2.0]
        )

    @property
    def half_thickness(self) -> float:
        return self.config.thickness / 2.0

    # -- geometry ---------------------------------------------------------- #

    def _level(self, local: FloatArray) -> FloatArray:
        """Quadratic level value: <=1 inside, ==1 on the surface."""
        return np.asarray(np.sum((local / self.semi_axes) ** 2, axis=-1))

    def contains(self, points: FloatArray) -> BoolArray:
        local = self.to_local(np.asarray(points, dtype=np.float64))
        return np.asarray(self._level(local) <= 1.0)

    def signed_distance(self, points: FloatArray) -> FloatArray:
        pts = np.asarray(points, dtype=np.float64)
        local = self.to_local(pts).reshape(-1, 3)
        a = self.semi_axes
        a2 = a * a
        p = np.abs(local)  # symmetry: distance depends on |coords| only
        # zero components make the largest-root equation degenerate (the
        # nearest point leaves the axis plane); a 1 nm clamp keeps the
        # bracket valid and perturbs the distance by far less than 1e-6 m
        p = np.maximum(p, 1e-9)
        # largest root of f(t) = sum((a p / (a^2 + t))^2) - 1 lives in
        # (-min(a^2), inf); bracket the upper end analytically:
        # f(t) < 1 once t >= |a p| * sqrt(3) - min(a^2) elementwise bound
        t_lo = np.full(p.shape[0], -np.min(a2) + 1e-12)
        t_hi = np.linalg.norm(a * p, axis=-1) * math.sqrt(3.0) + np.max(a2)
        # ensure f(t_hi) < 0 (outside the root)
        for _ in range(80):  # fixed deterministic bisection depth
            t_mid = 0.5 * (t_lo + t_hi)
            f = np.sum((a[None, :] * p / (a2[None, :] + t_mid[:, None])) ** 2, axis=-1) - 1.0
            take_hi = f > 0.0
            t_lo = np.where(take_hi, t_mid, t_lo)
            t_hi = np.where(take_hi, t_hi, t_mid)
        t = 0.5 * (t_lo + t_hi)
        closest = a2[None, :] * p / (a2[None, :] + t[:, None])
        dist = np.linalg.norm(p - closest, axis=-1)
        sign = np.where(self._level(local) <= 1.0, -1.0, 1.0)
        # points numerically at the center: distance = min semi-axis
        at_center = np.linalg.norm(local, axis=-1) < 1e-12
        dist = np.where(at_center, np.min(a), dist)
        out = sign * dist
        return np.asarray(out.reshape(pts.shape[:-1]))

    def volume(self) -> float:
        a = self.semi_axes
        return float(4.0 / 3.0 * math.pi * a[0] * a[1] * a[2])

    def bounding_box(self) -> tuple[FloatArray, FloatArray]:
        """Closed-form AABB of a rotated ellipsoid: the world half-extent
        along axis i is sqrt(Σⱼ (Rᵢⱼ aⱼ)²) with R columns = frame axes."""
        axes = np.stack([self.u, self.v, self.w], axis=0)  # (3 local, 3 world)
        half = np.sqrt(np.sum((axes * self.semi_axes[:, None]) ** 2, axis=0))
        return self.center - half, self.center + half

    def mesh(self, rings: int = 24, sectors: int = 48) -> tuple[FloatArray, npt.NDArray[np.int32]]:
        """UV-sphere scaled by the semi-axes: every vertex lies EXACTLY on
        the ellipsoid surface, so the mesh, SDF and contains() describe the
        same solid. Outward CCW winding (right-handed frame preserved)."""
        iu = np.arange(1, rings)
        phi = np.pi * iu / rings  # polar angle, poles handled separately
        theta = 2.0 * np.pi * np.arange(sectors) / sectors
        sin_phi = np.sin(phi)[:, None]
        ring_local = np.stack(
            [
                np.broadcast_to(np.cos(theta)[None, :], (rings - 1, sectors)) * sin_phi,
                np.broadcast_to(np.sin(theta)[None, :], (rings - 1, sectors)) * sin_phi,
                np.broadcast_to(np.cos(phi)[:, None], (rings - 1, sectors)),
            ],
            axis=-1,
        ).reshape(-1, 3)
        poles = np.array([[0.0, 0.0, 1.0], [0.0, 0.0, -1.0]])
        unit = np.concatenate([poles, ring_local], axis=0)
        verts = self.to_world(unit * self.semi_axes)
        faces: list[list[int]] = []

        def rid(r: int, s: int) -> int:
            return 2 + r * sectors + (s % sectors)

        for sct in range(sectors):  # top cap (north pole = +w local)
            faces.append([0, rid(0, sct), rid(0, sct + 1)])
        for r in range(rings - 2):
            for sct in range(sectors):
                a_, b_, c_, d_ = rid(r, sct), rid(r, sct + 1), rid(r + 1, sct + 1), rid(r + 1, sct)
                faces.append([a_, d_, c_])
                faces.append([a_, c_, b_])
        for sct in range(sectors):  # bottom cap
            faces.append([1, rid(rings - 2, sct + 1), rid(rings - 2, sct)])
        return verts, np.asarray(faces, dtype=np.int32)

    def to_dict(self) -> dict[str, Any]:
        lo, hi = self.bounding_box()
        return {
            "type": self.config.orebody_type.value,
            "center": self.center.tolist(),
            "u": self.u.tolist(),
            "v": self.v.tolist(),
            "w": self.w.tolist(),
            "semiAxes": self.semi_axes.tolist(),
            "volumeM3": self.volume(),
            "volumeMethod": "analytic",
            "distanceContract": self.distance_contract.value,
            "bboxMin": lo.tolist(),
            "bboxMax": hi.tolist(),
        }


def build_orebody(config: OrebodyConfig) -> Orebody:
    """Factory. Construction is cheap for every type (the realizer builds
    candidates only to test their bounding box, rule 125); implicit bodies
    derive clearance and mesh lazily (rule 138)."""
    if config.orebody_type is OrebodyType.TABULAR:
        return TabularOrebody(config)
    if config.orebody_type is OrebodyType.ELLIPSOID:
        return EllipsoidOrebody(config)
    if config.orebody_type is OrebodyType.WARPED_VEIN:
        from minegen.world.warped_vein import WarpedVeinOrebody  # cycle: warped_vein imports us

        return WarpedVeinOrebody(config)
    raise NotImplementedError(f"orebody type {config.orebody_type} is not implemented in v0.1")
