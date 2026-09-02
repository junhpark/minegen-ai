"""Synthetic geology: rock-quality field and fault planes.

Phase 02 produces *measurements* (rock quality, distance to faults, fault
zone, fault influence in [0, 1]). Converting these into engineering cost is
Phase 03 (``design/cost_field.py``); nothing here is a cost.

Correlated field
----------------
White noise → anisotropic Gaussian smoothing → standardize → ``mean + std·f``
→ clip. Convolving white noise with a Gaussian of standard deviation σ gives a
correlation function ``exp(−r² / 4σ²)``; defining the *correlation length* L
as the lag at which correlation falls to 1/e yields ``σ = L / 2``. XY and Z
use separate σ, so the field is anisotropic (CLAUDE.md rule 27).

Faults
------
Faults are scenario-defined planes (not seed-generated). For a plane through
``origin`` with unit normal ``n``, the signed distance of ``p`` is
``dot(p − origin, n)``. Zones use **half-widths** (rule 36):

    |d| ≤ core_half_width                           CORE    influence 1
    core_half_width < |d| ≤ influence_half_width    DAMAGE  influence 1 → 0 (linear)
    |d| > influence_half_width                      NORMAL  influence 0
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

import numpy as np
import numpy.typing as npt
from scipy import ndimage

from minegen.core.coordinates import strike_dip_vectors
from minegen.core.models import FaultConfig, RockQualityConfig
from minegen.world.field_grid import FieldGrid

FloatArray = npt.NDArray[np.float64]
F32 = npt.NDArray[np.float32]


class FaultZone(IntEnum):
    NORMAL = 0
    DAMAGE = 1
    CORE = 2


# --------------------------------------------------------------------------- #
# Correlated random fields
# --------------------------------------------------------------------------- #


def correlation_sigma_voxels(correlation_length_m: float, spacing_m: float) -> float:
    """Gaussian σ (in voxels) that yields 1/e correlation at ``correlation_length_m``."""
    return 0.5 * correlation_length_m / spacing_m


def correlated_standard_field(
    rng: np.random.Generator,
    shape: tuple[int, int, int],
    spacing: tuple[float, float, float],
    correlation_length_xy: float,
    correlation_length_z: float,
) -> FloatArray:
    """Zero-mean, unit-variance spatially correlated Gaussian field."""
    noise = rng.standard_normal(shape)
    sigma = (
        correlation_sigma_voxels(correlation_length_xy, spacing[0]),
        correlation_sigma_voxels(correlation_length_xy, spacing[1]),
        correlation_sigma_voxels(correlation_length_z, spacing[2]),
    )
    smooth = np.asarray(ndimage.gaussian_filter(noise, sigma=sigma, mode="reflect"))
    std = float(smooth.std())
    if std < 1e-12:  # degenerate (e.g. a 1×1×1 grid)
        return np.zeros(shape, dtype=np.float64)
    return np.asarray((smooth - smooth.mean()) / std, dtype=np.float64)


def generate_rock_quality(
    grid: FieldGrid, cfg: RockQualityConfig, seed: int
) -> tuple[F32, FloatArray]:
    """Rock-quality field (0–100) on the numerical field lattice.

    Returns ``(rock_quality float32, standard_field float64)``; the standard
    field is exposed so callers can test correlation structure directly."""
    rng = np.random.default_rng([seed, 0x20C4])  # dedicated sub-stream
    f = correlated_standard_field(
        rng, grid.shape, grid.spacing, cfg.correlation_length_xy, cfg.correlation_length_z
    )
    rq = np.clip(cfg.mean + cfg.std * f, cfg.minimum, cfg.maximum)
    return rq.astype(np.float32), f


def generate_grade_field(
    grid: FieldGrid,
    mean_grade: float,
    variability: float,
    correlation_length_xy: float,
    correlation_length_z: float,
    seed: int,
) -> F32:
    """Log-normal grade field with expected value ``mean_grade`` everywhere:
    ``grade = mean · exp(v·f − v²/2)`` for a standard correlated field ``f``.
    Always positive; ``variability`` is the log-standard-deviation."""
    rng = np.random.default_rng([seed, 0x6A4D])
    f = correlated_standard_field(
        rng, grid.shape, grid.spacing, correlation_length_xy, correlation_length_z
    )
    grade = mean_grade * np.exp(variability * f - 0.5 * variability**2)
    return grade.astype(np.float32)


# --------------------------------------------------------------------------- #
# Faults
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FaultPlane:
    config: FaultConfig
    origin: FloatArray
    normal: FloatArray  # unit, points to the footwall side (u × v)
    u: FloatArray  # along strike
    v: FloatArray  # down dip

    @classmethod
    def from_config(cls, cfg: FaultConfig) -> FaultPlane:
        u, v, w = strike_dip_vectors(cfg.strike_deg, cfg.dip_deg)
        return cls(config=cfg, origin=np.array(cfg.origin.as_tuple()), normal=w, u=u, v=v)

    def signed_distance(self, points: FloatArray) -> FloatArray:
        p = np.asarray(points, dtype=np.float64)
        return np.asarray((p - self.origin) @ self.normal)

    def zone(self, distance: FloatArray) -> npt.NDArray[np.uint8]:
        d = np.abs(distance)
        z = np.full(d.shape, FaultZone.NORMAL, dtype=np.uint8)
        z[d <= self.config.influence_half_width] = FaultZone.DAMAGE
        z[d <= self.config.core_half_width] = FaultZone.CORE
        return z

    def influence(self, distance: FloatArray) -> FloatArray:
        """1 in the core, linearly to 0 at the influence half-width, 0 outside."""
        d = np.abs(np.asarray(distance, dtype=np.float64))
        c, w = self.config.core_half_width, self.config.influence_half_width
        if w <= c:  # degenerate: no damage zone
            return np.where(d <= c, 1.0, 0.0)
        return np.asarray(np.clip((w - d) / (w - c), 0.0, 1.0))

    def clip_to_box(self, box_min: FloatArray, box_max: FloatArray) -> FloatArray:
        """Convex polygon (``(N, 3)``, N ≤ 6, ordered) where the plane cuts an
        axis-aligned box. Empty ``(0, 3)`` if the plane misses the box.
        Visualization only; not used by any numerical field."""
        lo = np.asarray(box_min, dtype=np.float64)
        hi = np.asarray(box_max, dtype=np.float64)
        corners = np.array(
            [
                [
                    lo[0] if i & 4 == 0 else hi[0],
                    lo[1] if i & 2 == 0 else hi[1],
                    lo[2] if i & 1 == 0 else hi[2],
                ]
                for i in range(8)
            ]
        )
        edges = [(a, b) for a in range(8) for b in range(a + 1, 8) if bin(a ^ b).count("1") == 1]
        d = self.signed_distance(corners)
        pts: list[FloatArray] = []
        for a, b in edges:
            da, db = d[a], d[b]
            if da == 0.0:
                pts.append(corners[a])
            if (da < 0 < db) or (db < 0 < da):
                t = da / (da - db)
                pts.append(corners[a] + t * (corners[b] - corners[a]))
        if not pts:
            return np.zeros((0, 3))
        p = np.unique(np.round(np.array(pts), 6), axis=0)
        if p.shape[0] < 3:
            return np.zeros((0, 3))
        c = p.mean(axis=0)
        ang = np.arctan2((p - c) @ self.v, (p - c) @ self.u)
        return np.asarray(p[np.argsort(ang)])


@dataclass(frozen=True)
class FaultFields:
    """Per-cell fault measurements on the field lattice (closest fault wins)."""

    signed_distance: F32  # to the nearest fault plane; +inf if no faults
    zone: npt.NDArray[np.uint8]
    influence: F32  # max over faults, in [0, 1]
    nearest_index: npt.NDArray[np.int16]  # −1 if no faults


def compute_fault_fields(grid: FieldGrid, faults: list[FaultPlane]) -> FaultFields:
    shape = grid.shape
    if not faults:
        return FaultFields(
            signed_distance=np.full(shape, np.inf, dtype=np.float32),
            zone=np.zeros(shape, dtype=np.uint8),
            influence=np.zeros(shape, dtype=np.float32),
            nearest_index=np.full(shape, -1, dtype=np.int16),
        )

    centers = grid.centers().reshape(-1, 3)
    best_abs = np.full(centers.shape[0], np.inf)
    best_signed = np.full(centers.shape[0], np.inf)
    best_idx = np.full(centers.shape[0], -1, dtype=np.int16)
    influence = np.zeros(centers.shape[0])
    zone = np.zeros(centers.shape[0], dtype=np.uint8)

    for i, f in enumerate(faults):
        d = f.signed_distance(centers)
        ad = np.abs(d)
        closer = ad < best_abs
        best_abs[closer] = ad[closer]
        best_signed[closer] = d[closer]
        best_idx[closer] = i
        influence = np.maximum(influence, f.influence(d))
        zone = np.maximum(zone, f.zone(d))

    return FaultFields(
        signed_distance=best_signed.reshape(shape).astype(np.float32),
        zone=zone.reshape(shape),
        influence=influence.reshape(shape).astype(np.float32),
        nearest_index=best_idx.reshape(shape),
    )
