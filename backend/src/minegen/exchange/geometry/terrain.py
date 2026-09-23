"""Terrain projections from the authoritative regular node grid
(``world/terrain.py``: ``z[i, j]`` at ``x0 + i·s``, ``y0 + j·s``, bilinear)."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from minegen.world.terrain import Terrain

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]


def terrain_grid_rows(t: Terrain) -> list[tuple[int, int, float, float, float]]:
    """``(i, j, x, y, z)`` for every node, i-major (lossless)."""
    xs, ys = t.x, t.y
    return [
        (i, j, float(xs[i]), float(ys[j]), float(t.z[i, j]))
        for i in range(t.nx)
        for j in range(t.ny)
    ]


def terrain_surface(t: Terrain) -> tuple[FloatArray, IntArray]:
    """Derived planar TIN of the bilinear node grid: vertex ``i·ny + j`` is
    node ``(i, j)``; every cell is split into two triangles along the
    ``(i, j) → (i+1, j+1)`` diagonal, wound counter-clockwise seen from +Z
    (upward facet normals). An OPEN surface — never a solid."""
    positions = t.positions_flat()
    nx, ny = t.nx, t.ny
    ii, jj = np.meshgrid(np.arange(nx - 1), np.arange(ny - 1), indexing="ij")
    a = (ii * ny + jj).ravel()
    b = ((ii + 1) * ny + jj).ravel()
    c = (ii * ny + jj + 1).ravel()
    d = ((ii + 1) * ny + jj + 1).ravel()
    tris = np.concatenate([np.column_stack([a, b, d]), np.column_stack([a, d, c])], axis=0)
    # deterministic order: cell-major (both triangles of a cell adjacent)
    order = np.empty(tris.shape[0], dtype=np.int64)
    n_cells = a.shape[0]
    order[0::2] = np.arange(n_cells)
    order[1::2] = np.arange(n_cells) + n_cells
    return positions, np.asarray(tris[order], dtype=np.int64)
