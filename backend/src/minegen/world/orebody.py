"""Analytic orebody geometry.

The orebody is an exact mathematical solid. The block model *samples* it
(Phase 02); access targets (Phase 03) and stopes (Phase 09) are derived from
it. It is never reconstructed from voxels.

Frame convention (CLAUDE.md rule 28, ``docs/coordinate-system.md``):
``u`` along strike, ``v`` down dip, ``w = u × v`` to the footwall side.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.core.coordinates import Frame, strike_dip_frame
from minegen.core.enums import OrebodyType
from minegen.core.models import OrebodyConfig

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]


class Orebody(ABC):
    """Analytic orebody interface. Subclasses are pure geometry."""

    config: OrebodyConfig
    frame: Frame

    @abstractmethod
    def contains(self, points: FloatArray) -> BoolArray:
        """Inclusion test for world points of shape ``(..., 3)``."""

    @abstractmethod
    def signed_distance(self, points: FloatArray) -> FloatArray:
        """Exact signed distance to the solid's surface for world points of
        shape ``(..., 3)``: negative inside, zero on the surface, positive
        outside (Euclidean distance to the nearest surface point)."""

    @abstractmethod
    def volume(self) -> float:
        """Exact solid volume in m³."""

    @abstractmethod
    def bounding_box(self) -> tuple[FloatArray, FloatArray]:
        """Axis-aligned world bounds ``(min, max)`` of the solid."""

    @abstractmethod
    def mesh(self) -> tuple[FloatArray, npt.NDArray[np.int32]]:
        """Triangle mesh ``(vertices (N,3), faces (M,3))`` in world coords."""

    def tonnes(self) -> float:
        return self.volume() * self.config.density

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

    def footwall_point(self, local_u: float, local_v: float, offset: float) -> FloatArray:
        """World point on the footwall side of the orebody: at in-plane local
        coordinates ``(local_u, local_v)``, displaced ``offset`` metres past the
        footwall contact along ``+w``. Used by Phase 03 access targets."""
        w_local = self.half_thickness + offset
        return self.to_world(np.array([local_u, local_v, w_local]))

    @property
    @abstractmethod
    def half_thickness(self) -> float: ...

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """JSON-safe description (no arrays larger than a few vectors)."""


@dataclass(init=False)
class TabularOrebody(Orebody):
    """Rectangular slab: ``|u| ≤ length/2``, ``|v| ≤ height/2`` (down-dip),
    ``|w| ≤ thickness/2``."""

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
            "tonnes": self.tonnes(),
            "bboxMin": lo.tolist(),
            "bboxMax": hi.tolist(),
        }


def build_orebody(config: OrebodyConfig) -> Orebody:
    if config.orebody_type is OrebodyType.TABULAR:
        return TabularOrebody(config)
    raise NotImplementedError(f"orebody type {config.orebody_type} is not implemented in v0.1")
