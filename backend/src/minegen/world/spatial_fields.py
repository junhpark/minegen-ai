"""Spatial scalar fields on a numerical sampling lattice (Phase 18).

    RegularScalarField   one scalar field + BATCH trilinear ``sample(N×3)``
    SpatialFieldSet      the synthetic geological fields of one world

Contract (rules 127–131):

* Cells are sampling support only. Nothing here classifies rock, ore or
  air, counts blocks, or attaches tonnage to a cell.
* The public query is batch-first and NumPy-vectorized: ``sample(points)``
  takes ``(N, 3)`` world points and returns ``(N,)`` values. There is no
  per-point scalar entry point because Hybrid-A* evaluates thousands of
  samples per expansion.
* ``rock_quality`` is the synthetic RMR-like 0–100 index (never actual RMR
  or Q). ``grade`` is a synthetic planning field defined EVERYWHERE on the
  lattice; outside the authoritative orebody solid it has no
  mineral-resource meaning and every consumer must apply the analytic
  orebody geometry itself (rule 129).
* Terrain boundary policy: the correlated fields are generated on the whole
  lattice, but the engineering consumers only ever query below ground. So
  that trilinear interpolation just under the surface is not pulled toward
  an arbitrary above-ground value, the rock-quality field carries the
  ``COLUMN_TOP_FILL`` policy — cells whose ``terrain_support`` (fraction of
  the cell below the terrain surface, from a fixed sub-sample pattern) is
  below 0.5 take the value of the nearest supported cell beneath them in
  the same column. This is an interpolation boundary policy, not an AIR
  classification; the support fraction is also the visualization mask.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.world.field_grid import FieldGrid
from minegen.world.terrain import Terrain

FloatArray = npt.NDArray[np.float64]
F32 = npt.NDArray[np.float32]

#: bumped whenever the arrays.npz layout changes incompatibly
FIELD_ARTIFACT_VERSION = 1
FIELD_ARTIFACT_KEY = "field_artifact_version"
#: fraction of a cell that must lie below the terrain surface for the cell
#: to count as terrain-supported (interpolation policy + display mask)
TERRAIN_SUPPORT_THRESHOLD = 0.5
DEFAULT_SUBSAMPLES = 2
COLUMN_TOP_FILL = "COLUMN_TOP_FILL"


class IncompatibleFieldArtifactError(ValueError):
    """``arrays.npz`` is not a Phase-18 field artifact (e.g. a legacy
    Phase-17 BlockModel NPZ). It must never be consumed under the new
    semantics — regenerate the world."""


# --------------------------------------------------------------------------- #
# One scalar field
# --------------------------------------------------------------------------- #


@dataclass
class RegularScalarField:
    """Scalar field attached to the cell centers of a :class:`FieldGrid`.

    ``sample`` is trilinear on the center lattice with coordinates CLAMPED
    to the center lattice (no extrapolation past the outermost centers);
    whether a point is inside the modelled volume is a separate decision
    for the caller (``DesignCostEvaluator.world_valid``)."""

    name: str
    grid: FieldGrid
    values: npt.NDArray[Any]
    #: free-form provenance, e.g. {"boundaryPolicy": "COLUMN_TOP_FILL"}
    meta: dict[str, Any] = field(default_factory=dict)
    _dense: FloatArray | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if tuple(self.values.shape) != tuple(self.grid.shape):
            raise ValueError(
                f"field {self.name!r} values shape {self.values.shape} != grid {self.grid.shape}"
            )
        centers = [self.grid.axis_centers(a) for a in range(3)]
        self._center_lo = np.array([c[0] for c in centers])
        self._center_hi = np.array([c[-1] for c in centers])
        self._spacing = np.asarray(self.grid.spacing, dtype=np.float64)
        self._shape = np.asarray(self.grid.shape, dtype=np.intp)

    @property
    def dense(self) -> FloatArray:
        """float64 view used by interpolation (built once, lazily)."""
        if self._dense is None:
            self._dense = np.asarray(self.values, dtype=np.float64)
        return self._dense

    def sample(self, points: FloatArray) -> FloatArray:
        """Batch trilinear interpolation for ``(N, 3)`` world points →
        ``(N,)`` float64. Pure NumPy; no Python loop over points."""
        p = np.atleast_2d(np.asarray(points, dtype=np.float64))
        if p.shape[-1] != 3:
            raise ValueError("points must have shape (N, 3)")
        p = np.clip(p, self._center_lo, self._center_hi)
        f = (p - self._center_lo) / self._spacing  # fractional index in the center lattice
        f = np.minimum(f, self._shape - 1 - 1e-12)
        i0 = np.floor(f).astype(np.intp)
        t = f - i0
        i1 = np.minimum(i0 + 1, self._shape - 1)
        v = self.dense
        x0, y0, z0 = i0[:, 0], i0[:, 1], i0[:, 2]
        x1, y1, z1 = i1[:, 0], i1[:, 1], i1[:, 2]
        tx, ty, tz = t[:, 0], t[:, 1], t[:, 2]
        c00 = v[x0, y0, z0] * (1 - tx) + v[x1, y0, z0] * tx
        c10 = v[x0, y1, z0] * (1 - tx) + v[x1, y1, z0] * tx
        c01 = v[x0, y0, z1] * (1 - tx) + v[x1, y0, z1] * tx
        c11 = v[x0, y1, z1] * (1 - tx) + v[x1, y1, z1] * tx
        c0 = c00 * (1 - ty) + c10 * ty
        c1 = c01 * (1 - ty) + c11 * ty
        return np.asarray(c0 * (1 - tz) + c1 * tz, dtype=np.float64)

    def sample_nearest(self, points: FloatArray) -> npt.NDArray[Any]:
        """Nearest-cell lookup (categorical fields such as fault zone)."""
        p = np.atleast_2d(np.asarray(points, dtype=np.float64))
        p = np.clip(p, self._center_lo, self._center_hi)
        idx = np.rint((p - self._center_lo) / self._spacing).astype(np.intp)
        idx = np.clip(idx, 0, self._shape - 1)
        return np.asarray(self.values[idx[:, 0], idx[:, 1], idx[:, 2]])

    def slice(self, axis: int, index: int) -> FloatArray:
        """Axis-aligned plane ``index`` of the field as float64."""
        return np.asarray(np.take(self.values, index, axis=axis), dtype=np.float64)

    def stats(self, mask: npt.NDArray[np.bool_] | None = None) -> dict[str, float]:
        a = self.dense if mask is None else self.dense[mask]
        a = a[np.isfinite(a)]
        if a.size == 0:
            return {"min": 0.0, "max": 0.0, "mean": 0.0, "std": 0.0}
        return {
            "min": float(a.min()),
            "max": float(a.max()),
            "mean": float(a.mean()),
            "std": float(a.std()),
        }


# --------------------------------------------------------------------------- #
# Terrain boundary policy
# --------------------------------------------------------------------------- #


def _subsample_pattern(grid: FieldGrid, n_sub: int) -> tuple[FloatArray, FloatArray]:
    """XY offsets ``(n_sub², 2)`` and Z offsets ``(n_sub,)`` relative to the
    cell center — one fixed deterministic pattern per lattice."""
    t = (np.arange(n_sub, dtype=np.float64) + 0.5) / n_sub - 0.5
    ox, oy = np.meshgrid(t * grid.spacing[0], t * grid.spacing[1], indexing="ij")
    return np.column_stack([ox.ravel(), oy.ravel()]), t * grid.spacing[2]


def terrain_support_fraction(
    grid: FieldGrid, terrain: Terrain, n_sub: int = DEFAULT_SUBSAMPLES
) -> F32:
    """Fraction of each cell (``n_sub³`` sub-samples) that lies at or below
    the terrain surface. The terrain is sampled once at every XY
    sub-position (``nx·ny·n_sub²`` points); memory is bounded by
    ``nx·ny·nz·n_sub³`` booleans."""
    nx, ny, _ = grid.shape
    xy_off, z_off = _subsample_pattern(grid, n_sub)
    n_xy = xy_off.shape[0]
    xc, yc, zc = (grid.axis_centers(a) for a in range(3))
    gx, gy = np.meshgrid(xc, yc, indexing="ij")
    xy = np.stack([gx, gy], axis=-1)[:, :, None, :] + xy_off[None, None, :, :]  # (nx,ny,n_xy,2)
    surface = terrain.sample(xy.reshape(-1, 2)).reshape(nx, ny, n_xy)
    zs = zc[:, None] + z_off[None, :]  # (nz, n_z)
    below = zs[None, None, :, :, None] <= surface[:, :, None, None, :]  # (nx,ny,nz,n_z,n_xy)
    return np.asarray(below.mean(axis=(3, 4)), dtype=np.float32)


def column_top_fill(values: npt.NDArray[Any], supported: npt.NDArray[np.bool_]) -> npt.NDArray[Any]:
    """``COLUMN_TOP_FILL`` boundary policy: every unsupported cell takes the
    value of the nearest supported cell BELOW it in the same column. The
    bottom layer must be supported everywhere (the model floor is below
    the terrain by construction, rule 35)."""
    if not bool(supported[:, :, 0].all()):
        raise ValueError("column_top_fill: the bottom lattice layer must be terrain-supported")
    out = values.copy()
    for k in range(1, out.shape[2]):
        out[:, :, k] = np.where(supported[:, :, k], out[:, :, k], out[:, :, k - 1])
    return out


# --------------------------------------------------------------------------- #
# The field set of one world
# --------------------------------------------------------------------------- #


@dataclass
class SpatialFieldSet:
    grid: FieldGrid
    rock_quality: RegularScalarField  # synthetic RMR-like 0–100, COLUMN_TOP_FILL above terrain
    grade: RegularScalarField  # synthetic planning field; no resource meaning outside the orebody
    fault_signed_distance: RegularScalarField  # to the nearest fault plane (+inf if none)
    fault_zone: RegularScalarField  # uint8 FaultZone (nearest-cell semantics)
    fault_influence: RegularScalarField  # [0, 1]
    terrain_support: F32  # fraction of each cell below the terrain surface
    meta: dict[str, Any] = field(default_factory=dict)

    FIELD_NAMES = (
        "rock_quality",
        "grade",
        "fault_signed_distance",
        "fault_zone",
        "fault_influence",
    )

    def field(self, name: str) -> RegularScalarField:
        if name not in self.FIELD_NAMES:
            raise KeyError(name)
        f: RegularScalarField = getattr(self, name)
        return f

    @property
    def supported(self) -> npt.NDArray[np.bool_]:
        """Cells counted as below ground (display mask / statistics)."""
        return np.asarray(self.terrain_support >= TERRAIN_SUPPORT_THRESHOLD)

    # -- diagnostics (neutral: no resource / block-inventory semantics) ------ #

    def stats(self) -> dict[str, Any]:
        arrays = {name: self.field(name).values for name in self.FIELD_NAMES}
        arrays["terrain_support"] = self.terrain_support
        per_array = {
            name: {"dtype": str(a.dtype), "bytes": int(a.nbytes)} for name, a in arrays.items()
        }
        total_bytes = sum(int(a.nbytes) for a in arrays.values())
        supported = self.supported
        return {
            "grid": self.grid.to_dict(),
            "cellCount": self.grid.cell_count,
            "terrainSupportedFraction": float(supported.mean()) if supported.size else 0.0,
            "rockQuality": self.rock_quality.stats(supported),
            "rockQualitySemantics": "synthetic RMR-like index, 0-100; not measured RMR or Q",
            "boundaryPolicy": self.rock_quality.meta.get("boundaryPolicy"),
            "arrays": per_array,
            "totalBytes": total_bytes,
            "totalMB": total_bytes / (1024 * 1024),
        }

    # -- persistence ------------------------------------------------------- #

    def to_npz_fields(self) -> dict[str, npt.NDArray[Any]]:
        fields: dict[str, npt.NDArray[Any]] = {
            FIELD_ARTIFACT_KEY: np.asarray([FIELD_ARTIFACT_VERSION], dtype=np.int64),
            "field_terrain_support": self.terrain_support,
        }
        for name in self.FIELD_NAMES:
            fields[f"field_{name}"] = self.field(name).values
        fields.update(self.grid.to_npz_fields())
        return fields

    @classmethod
    def from_npz(cls, npz: Any) -> SpatialFieldSet:
        """Rebuild from ``np.load`` output; refuses anything that is not a
        Phase-18 field artifact of the current version."""
        keys = set(npz.files) if hasattr(npz, "files") else set(npz.keys())
        if FIELD_ARTIFACT_KEY not in keys:
            hint = (
                " (legacy Phase-17 BlockModel arrays detected)"
                if {"rock_type", "ore_fraction"} & keys
                else ""
            )
            raise IncompatibleFieldArtifactError(
                f"arrays.npz carries no {FIELD_ARTIFACT_KEY}{hint}; regenerate the world"
            )
        version = int(np.asarray(npz[FIELD_ARTIFACT_KEY]).ravel()[0])
        if version != FIELD_ARTIFACT_VERSION:
            raise IncompatibleFieldArtifactError(
                f"arrays.npz field artifact version {version} != {FIELD_ARTIFACT_VERSION}; "
                "regenerate the world"
            )
        missing = {f"field_{n}" for n in cls.FIELD_NAMES} | {"field_terrain_support"}
        missing -= keys
        if missing:
            raise IncompatibleFieldArtifactError(
                f"arrays.npz is missing field arrays {sorted(missing)}; regenerate the world"
            )
        grid = FieldGrid.from_npz_fields(npz)
        rq = RegularScalarField(
            "rock_quality", grid, npz["field_rock_quality"], {"boundaryPolicy": COLUMN_TOP_FILL}
        )
        return cls(
            grid=grid,
            rock_quality=rq,
            grade=RegularScalarField("grade", grid, npz["field_grade"]),
            fault_signed_distance=RegularScalarField(
                "fault_signed_distance", grid, npz["field_fault_signed_distance"]
            ),
            fault_zone=RegularScalarField("fault_zone", grid, npz["field_fault_zone"]),
            fault_influence=RegularScalarField(
                "fault_influence", grid, npz["field_fault_influence"]
            ),
            terrain_support=np.asarray(npz["field_terrain_support"], dtype=np.float32),
        )
