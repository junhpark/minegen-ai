"""Regular axis-aligned NUMERICAL sampling lattice in mine coordinates
(ENU Z-up), Phase 18 (rule 127).

A ``FieldGrid`` cell is sampling support for a scalar field — nothing
more. It is never a mining block, an SMU, a resource block or a reserve
unit, and no engineering quantity (tonnes, ore/waste membership, grade
inventory) is ever attached to a cell. The Hybrid-A* search space stays
continuous (rule 23); this lattice only supports interpolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class FieldGrid:
    """``origin`` is the minimum corner of cell (0, 0, 0); cell ``(i, j, k)``
    spans ``origin + (i·sx, j·sy, k·sz)`` to ``origin + ((i+1)·sx, …)``.
    Field values are attached to cell CENTERS."""

    origin: tuple[float, float, float]
    spacing: tuple[float, float, float]
    shape: tuple[int, int, int]

    @classmethod
    def from_extent(
        cls,
        min_corner: tuple[float, float, float],
        max_corner: tuple[float, float, float],
        spacing: tuple[float, float, float],
    ) -> FieldGrid:
        """Lattice that covers ``[min, max]`` at ``spacing``; the last cell
        may extend past ``max`` so that the extent is fully covered."""
        shape = tuple(
            int(np.ceil((hi - lo) / s - 1e-9))
            for lo, hi, s in zip(min_corner, max_corner, spacing, strict=True)
        )
        if any(n <= 0 for n in shape):
            raise ValueError(f"empty field grid for extent {min_corner}..{max_corner}")
        return cls(origin=min_corner, spacing=spacing, shape=(shape[0], shape[1], shape[2]))

    # -- sizes ------------------------------------------------------------- #

    @property
    def cell_count(self) -> int:
        return int(np.prod(self.shape))

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
        """All cell centers, shape ``(nx, ny, nz, 3)``."""
        x, y, z = (self.axis_centers(a) for a in range(3))
        gx, gy, gz = np.meshgrid(x, y, z, indexing="ij")
        return np.stack([gx, gy, gz], axis=-1)

    @property
    def cell_half_diagonal(self) -> float:
        """Half the space diagonal of one cell: the largest distance from a
        cell center to any point of that cell. A solid whose signed distance
        at the center exceeds this cannot reach into the cell."""
        return 0.5 * float(np.linalg.norm(np.asarray(self.spacing)))

    def cell_subsample_offsets(self, n: int) -> FloatArray:
        """Offsets (relative to a cell CENTER) of a deterministic ``n×n×n``
        sub-sampling pattern inside one cell, shape ``(n³, 3)``. Midpoints of
        equal sub-boxes, so the pattern is symmetric and seed-independent."""
        if n < 1:
            raise ValueError(f"sub-sample count must be >= 1, got {n}")
        t = (np.arange(n, dtype=np.float64) + 0.5) / n - 0.5
        ox, oy, oz = np.meshgrid(
            t * self.spacing[0], t * self.spacing[1], t * self.spacing[2], indexing="ij"
        )
        return np.stack([ox.ravel(), oy.ravel(), oz.ravel()], axis=-1)

    def plane_centers(self, axis: int, index: int) -> FloatArray:
        """World coordinates of the cell centers on ONE lattice plane, shape
        ``(rows·cols, 3)``, ordered row-major over the two remaining axes —
        the same ordering as ``np.take(values, index, axis=axis).ravel()``.

        Only the requested plane is built: a full ``centers()`` allocation is
        ~1 M × 3 floats on the default lattice and would be rebuilt on every
        slice request."""
        n = self.shape[axis]
        if not 0 <= index < n:
            raise IndexError(f"plane index {index} out of range [0, {n})")
        others = [a for a in range(3) if a != axis]
        gr, gc = np.meshgrid(
            self.axis_centers(others[0]), self.axis_centers(others[1]), indexing="ij"
        )
        pts = np.empty((gr.size, 3), dtype=np.float64)
        pts[:, others[0]] = gr.ravel()
        pts[:, others[1]] = gc.ravel()
        pts[:, axis] = self.axis_centers(axis)[index]
        return pts

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
            "field_grid_origin": np.asarray(self.origin, dtype=np.float64),
            "field_grid_spacing": np.asarray(self.spacing, dtype=np.float64),
            "field_grid_shape": np.asarray(self.shape, dtype=np.float64),
        }

    @classmethod
    def from_npz_fields(cls, npz: Any) -> FieldGrid:
        o, s, n = npz["field_grid_origin"], npz["field_grid_spacing"], npz["field_grid_shape"]
        return cls(
            origin=(float(o[0]), float(o[1]), float(o[2])),
            spacing=(float(s[0]), float(s[1]), float(s[2])),
            shape=(int(n[0]), int(n[1]), int(n[2])),
        )
