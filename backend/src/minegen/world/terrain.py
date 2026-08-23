"""Synthetic smooth topography.

Seeded fractional-Brownian-motion value noise: each octave is a coarse random
lattice upsampled with cubic interpolation; octaves are summed with halving
amplitude and doubling frequency. The result is normalized so the peak-to-peak
relief equals ``TerrainConfig.relief`` and the mean equals ``base_elevation``.

Everything is deterministic for a given seed (CLAUDE.md rule 7).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from scipy import ndimage

from minegen.core.models import TerrainConfig, WorldConfig

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class Terrain:
    """Heightmap ``z[i, j]`` at ``x = x0 + i·spacing``, ``y = y0 + j·spacing``."""

    x0: float
    y0: float
    spacing: float
    z: FloatArray  # shape (nx, ny)

    @property
    def nx(self) -> int:
        return int(self.z.shape[0])

    @property
    def ny(self) -> int:
        return int(self.z.shape[1])

    @property
    def x(self) -> FloatArray:
        return np.asarray(self.x0 + np.arange(self.nx) * self.spacing, dtype=np.float64)

    @property
    def y(self) -> FloatArray:
        return np.asarray(self.y0 + np.arange(self.ny) * self.spacing, dtype=np.float64)

    @property
    def z_min(self) -> float:
        return float(self.z.min())

    @property
    def z_max(self) -> float:
        return float(self.z.max())

    def sample(self, xy: FloatArray) -> FloatArray:
        """Bilinear elevation at ``(N, 2)`` horizontal points. Points outside
        the grid are clamped to the edge. Direct index arithmetic (no
        ``RegularGridInterpolator``): this is on the Hybrid-A* hot path."""
        p = np.asarray(xy, dtype=np.float64)
        nx, ny = self.nx, self.ny
        fx = np.clip((p[:, 0] - self.x0) / self.spacing, 0.0, nx - 1 - 1e-12)
        fy = np.clip((p[:, 1] - self.y0) / self.spacing, 0.0, ny - 1 - 1e-12)
        i0 = np.floor(fx).astype(np.intp)
        j0 = np.floor(fy).astype(np.intp)
        i1 = np.minimum(i0 + 1, nx - 1)
        j1 = np.minimum(j0 + 1, ny - 1)
        tx = fx - i0
        ty = fy - j0
        z = self.z
        return np.asarray(
            (1 - tx) * (1 - ty) * z[i0, j0]
            + tx * (1 - ty) * z[i1, j0]
            + (1 - tx) * ty * z[i0, j1]
            + tx * ty * z[i1, j1],
            dtype=np.float64,
        )

    def positions_flat(self) -> FloatArray:
        """``(nx·ny, 3)`` vertex positions in mine coordinates, i-major."""
        gx, gy = np.meshgrid(self.x, self.y, indexing="ij")
        return np.column_stack([gx.ravel(), gy.ravel(), self.z.ravel()])


def _octave(rng: np.random.Generator, nx: int, ny: int, cells: int) -> FloatArray:
    """One value-noise octave: a ``(cells+1)²`` random lattice resampled to
    ``(nx, ny)`` with cubic interpolation."""
    lattice = rng.standard_normal((cells + 1, cells + 1))
    zoom = (nx / lattice.shape[0], ny / lattice.shape[1])
    return np.asarray(ndimage.zoom(lattice, zoom, order=3, mode="nearest"), dtype=np.float64)


def generate_terrain(world: WorldConfig, cfg: TerrainConfig, seed: int) -> Terrain:
    rng = np.random.default_rng([seed, 0x7E44A1])  # sub-stream dedicated to terrain
    nx = round(world.size_x / cfg.grid_spacing) + 1
    ny = round(world.size_y / cfg.grid_spacing) + 1

    field = np.zeros((nx, ny), dtype=np.float64)
    amplitude = 1.0
    cells = 4  # base frequency: 4 cells across the world
    for _ in range(cfg.octaves):
        field += amplitude * _octave(rng, nx, ny, cells)
        amplitude *= 0.5
        cells *= 2

    field -= field.mean()
    peak_to_peak = float(field.max() - field.min())
    if peak_to_peak > 0 and cfg.relief > 0:
        field *= cfg.relief / peak_to_peak
    else:
        field[:] = 0.0
    z = cfg.base_elevation + field
    return Terrain(x0=-world.size_x / 2, y0=-world.size_y / 2, spacing=cfg.grid_spacing, z=z)
