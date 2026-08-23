"""Regular axis-aligned voxel grid in mine coordinates (ENU Z-up).

This is the *block-model* grid (geology / economics). It is deliberately not
the Hybrid-A* search space, which stays continuous (CLAUDE.md rule 23).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class VoxelGrid:
    """``origin`` is the minimum corner of block (0, 0, 0); block ``(i, j, k)``
    spans ``origin + (i·dx, j·dy, k·dz)`` to ``origin + ((i+1)·dx, …)``."""

    origin: tuple[float, float, float]
    spacing: tuple[float, float, float]
    shape: tuple[int, int, int]

    @classmethod
    def from_extent(
        cls,
        min_corner: tuple[float, float, float],
        max_corner: tuple[float, float, float],
        spacing: tuple[float, float, float],
    ) -> VoxelGrid:
        """Grid that covers ``[min, max]`` with blocks of ``spacing``; the last
        block may extend past ``max`` so that the extent is fully covered."""
        shape = tuple(
            int(np.ceil((hi - lo) / s - 1e-9))
            for lo, hi, s in zip(min_corner, max_corner, spacing, strict=True)
        )
        if any(n <= 0 for n in shape):
            raise ValueError(f"empty grid for extent {min_corner}..{max_corner}")
        return cls(origin=min_corner, spacing=spacing, shape=(shape[0], shape[1], shape[2]))

    # -- sizes ------------------------------------------------------------- #

    @property
    def n_blocks(self) -> int:
        return int(np.prod(self.shape))

    @property
    def block_volume(self) -> float:
        return float(np.prod(self.spacing))

    @property
    def max_corner(self) -> tuple[float, float, float]:
        return (
            self.origin[0] + self.shape[0] * self.spacing[0],
            self.origin[1] + self.shape[1] * self.spacing[1],
            self.origin[2] + self.shape[2] * self.spacing[2],
        )

    # -- coordinates ------------------------------------------------------- #

    def axis_centers(self, axis: int) -> FloatArray:
        n, o, s = self.shape[axis], self.origin[axis], self.spacing[axis]
        return o + (np.arange(n, dtype=np.float64) + 0.5) * s

    def centers(self) -> FloatArray:
        """All block centers, shape ``(nx, ny, nz, 3)``."""
        x, y, z = (self.axis_centers(a) for a in range(3))
        gx, gy, gz = np.meshgrid(x, y, z, indexing="ij")
        return np.stack([gx, gy, gz], axis=-1)

    def subsample_offsets(self, n: int) -> FloatArray:
        """Offsets (relative to block center) of an ``n×n×n`` sub-sampling
        pattern inside one block, shape ``(n³, 3)``."""
        t = (np.arange(n, dtype=np.float64) + 0.5) / n - 0.5
        ox, oy, oz = np.meshgrid(
            t * self.spacing[0], t * self.spacing[1], t * self.spacing[2], indexing="ij"
        )
        return np.stack([ox.ravel(), oy.ravel(), oz.ravel()], axis=-1)

    def world_to_index(self, points: FloatArray) -> npt.NDArray[np.int64]:
        """Floor index of each point, shape ``(N, 3)``. Out-of-range points get
        out-of-range indices; callers clip or mask."""
        p = np.asarray(points, dtype=np.float64)
        idx = np.floor((p - np.asarray(self.origin)) / np.asarray(self.spacing))
        return np.asarray(idx, dtype=np.int64)

    def contains_index(self, idx: npt.NDArray[np.int64]) -> npt.NDArray[np.bool_]:
        return np.all((idx >= 0) & (idx < np.asarray(self.shape)), axis=-1)

    # -- serialization ----------------------------------------------------- #

    def to_dict(self) -> dict[str, Any]:
        return {
            "origin": list(self.origin),
            "spacing": list(self.spacing),
            "shape": list(self.shape),
        }

    def to_npz_fields(self) -> dict[str, FloatArray]:
        return {
            "grid_origin": np.asarray(self.origin, dtype=np.float64),
            "grid_spacing": np.asarray(self.spacing, dtype=np.float64),
            "grid_shape": np.asarray(self.shape, dtype=np.float64),
        }

    @classmethod
    def from_npz_fields(cls, npz: Any) -> VoxelGrid:
        o, s, n = npz["grid_origin"], npz["grid_spacing"], npz["grid_shape"]
        return cls(
            origin=(float(o[0]), float(o[1]), float(o[2])),
            spacing=(float(s[0]), float(s[1]), float(s[2])),
            shape=(int(n[0]), int(n[1]), int(n[2])),
        )
