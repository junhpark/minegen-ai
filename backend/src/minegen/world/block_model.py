"""NumPy block model (CLAUDE.md rule 6: arrays, never per-block objects).

Per-block fields, all shaped ``grid.shape = (nx, ny, nz)``:

    rock_type           uint8    0 AIR (solid_fraction < 0.5), 1 HOST, 2 ORE
    ore_fraction        float32  fraction of the block that is inside the analytic
                                 orebody AND below the terrain surface (in-situ ore)
    ore_flag            bool     ore_fraction >= ORE_FRACTION_THRESHOLD
    grade               float32  g/t-like; 0 outside ore
    rock_quality        float32  0–100 synthetic rock-mass quality
    fault_signed_distance float32  to nearest fault plane (+inf if no faults)
    fault_zone          uint8    FaultZone: 0 NORMAL, 1 DAMAGE, 2 CORE
    fault_influence     float32  [0, 1]

The analytic orebody is the source of truth; ``ore_fraction`` is a sampling
of it with an ``n×n×n`` sub-grid per block so that thin tabular bodies are not
aliased by block-center tests. The same sub-samples are tested against the
terrain, so

    orebody.volume()          = geometric mineralized-body volume (may outcrop)
    block_model.ore_volume()  = in-situ mineralized rock volume (below ground)

and AIR/ROCK classification uses the sub-sampled solid fraction rather than a
block-center test. ``solid_fraction`` is not persisted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.core.models import BlockModelConfig, WorldConfig
from minegen.world.geology import FaultFields
from minegen.world.orebody import Orebody
from minegen.world.terrain import Terrain
from minegen.world.voxel_grid import VoxelGrid

ORE_FRACTION_THRESHOLD = 0.5
SOLID_FRACTION_THRESHOLD = 0.5
DEFAULT_SUBSAMPLES = 2


class RockType:
    AIR = 0
    HOST = 1
    ORE = 2


@dataclass
class BlockModel:
    grid: VoxelGrid
    rock_type: npt.NDArray[np.uint8]
    ore_fraction: npt.NDArray[np.float32]
    ore_flag: npt.NDArray[np.bool_]
    grade: npt.NDArray[np.float32]
    rock_quality: npt.NDArray[np.float32]
    fault_signed_distance: npt.NDArray[np.float32]
    fault_zone: npt.NDArray[np.uint8]
    fault_influence: npt.NDArray[np.float32]
    meta: dict[str, Any] = field(default_factory=dict)

    ARRAY_FIELDS = (
        "rock_type",
        "ore_fraction",
        "ore_flag",
        "grade",
        "rock_quality",
        "fault_signed_distance",
        "fault_zone",
        "fault_influence",
    )

    # -- derived quantities ------------------------------------------------ #

    def ore_volume(self) -> float:
        """In-situ mineralized rock volume (inside orebody AND below terrain).
        Equals the analytic solid volume only when the orebody does not outcrop."""
        return float(self.ore_fraction.sum()) * self.grid.block_volume

    def ore_tonnes(self, density: float) -> float:
        return self.ore_volume() * density

    def mean_ore_grade(self) -> float:
        w = self.ore_fraction.astype(np.float64)
        total = w.sum()
        if total <= 0:
            return 0.0
        return float((self.grade.astype(np.float64) * w).sum() / total)

    def stats(self, density: float) -> dict[str, Any]:
        arrays = {name: getattr(self, name) for name in self.ARRAY_FIELDS}
        per_array = {
            name: {"dtype": str(a.dtype), "bytes": int(a.nbytes)} for name, a in arrays.items()
        }
        total_bytes = sum(int(a.nbytes) for a in arrays.values())
        n_ore = int(self.ore_flag.sum())
        rock = self.rock_type != RockType.AIR
        n_air = int((~rock).sum())
        return {
            "shape": list(self.grid.shape),
            "nBlocks": self.grid.n_blocks,
            "spacing": list(self.grid.spacing),
            "origin": list(self.grid.origin),
            "nOreBlocks": n_ore,
            "nAirBlocks": n_air,
            "nRockBlocks": self.grid.n_blocks - n_air,
            "oreVolumeM3": self.ore_volume(),
            "oreTonnes": self.ore_tonnes(density),
            "meanOreGrade": self.mean_ore_grade(),
            "rockQualityMean": float(self.rock_quality[rock].mean()) if rock.any() else 0.0,
            # mine statistics count rock blocks only; the fault *fields* remain
            # defined everywhere (they are mathematical plane distances)
            "faultCoreBlocks": int(((self.fault_zone == 2) & rock).sum()),
            "faultDamageBlocks": int(((self.fault_zone == 1) & rock).sum()),
            "arrays": per_array,
            "totalBytes": total_bytes,
            "totalMB": total_bytes / (1024 * 1024),
        }

    # -- persistence ------------------------------------------------------- #

    def save_npz(self, path: Path) -> None:
        fields = {name: getattr(self, name) for name in self.ARRAY_FIELDS}
        fields.update(self.grid.to_npz_fields())
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, **fields)

    @classmethod
    def load_npz(cls, path: Path) -> BlockModel:
        with np.load(path) as npz:
            grid = VoxelGrid.from_npz_fields(npz)
            data = {name: npz[name] for name in cls.ARRAY_FIELDS}
        return cls(grid=grid, **data)


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #


def build_block_grid(
    world: WorldConfig, cfg: BlockModelConfig, reference_elevation: float, relief: float
) -> VoxelGrid:
    """Grid from the model bottom (``reference_elevation − depth``, rule 35)
    to ``reference_elevation + relief``.

    The top comes from *configuration*, not from the realized terrain, so the
    grid shape is identical for every seed of the same scenario and seed-to-
    seed field comparisons are element-wise meaningful."""
    bottom = world.bottom_elevation(reference_elevation)
    top = reference_elevation + relief
    return VoxelGrid.from_extent(
        (-world.size_x / 2, -world.size_y / 2, bottom),
        (world.size_x / 2, world.size_y / 2, top),
        (cfg.dx, cfg.dy, cfg.dz),
    )


@dataclass(frozen=True)
class BlockFractions:
    ore: npt.NDArray[np.float32]  # inside orebody AND below terrain
    solid: npt.NDArray[np.float32]  # below terrain


def _subsample_pattern(
    grid: VoxelGrid, n_sub: int
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """XY offsets ``(n_sub², 2)`` and Z offsets ``(n_sub,)`` relative to the
    block center. Full 3D sample ``s = ixy * n_sub + iz``."""
    t = (np.arange(n_sub, dtype=np.float64) + 0.5) / n_sub - 0.5
    ox, oy = np.meshgrid(t * grid.spacing[0], t * grid.spacing[1], indexing="ij")
    return np.column_stack([ox.ravel(), oy.ravel()]), t * grid.spacing[2]


def sample_block_fractions(
    grid: VoxelGrid, orebody: Orebody, terrain: Terrain, n_sub: int = DEFAULT_SUBSAMPLES
) -> BlockFractions:
    """Per-block ``solid`` (below terrain) and ``ore`` (inside the analytic
    orebody AND below terrain) fractions from one shared ``n_sub³`` pattern.

    The terrain is sampled once at every XY sub-position (``nx·ny·n_sub²``
    points); ore tests are restricted to blocks overlapping the orebody
    bounding box and evaluated one z-layer at a time to bound memory."""
    nx, ny, _ = grid.shape
    xy_off, z_off = _subsample_pattern(grid, n_sub)
    n_xy, n_z = xy_off.shape[0], z_off.shape[0]

    xc, yc, zc = (grid.axis_centers(a) for a in range(3))
    gx, gy = np.meshgrid(xc, yc, indexing="ij")
    xy = np.stack([gx, gy], axis=-1)[:, :, None, :] + xy_off[None, None, :, :]  # (nx,ny,n_xy,2)
    surface = terrain.sample(xy.reshape(-1, 2)).reshape(nx, ny, n_xy)

    # solid fraction for every block: sub-sample z <= surface at its XY sub-position
    zs = zc[:, None] + z_off[None, :]  # (nz, n_z)
    below = zs[None, None, :, :, None] <= surface[:, :, None, None, :]  # (nx,ny,nz,n_z,n_xy)
    solid = below.mean(axis=(3, 4)).astype(np.float32)

    ore = np.zeros(grid.shape, dtype=np.float32)
    lo, hi = orebody.bounding_box()
    half = np.asarray(grid.spacing) / 2.0
    ix = np.nonzero((xc + half[0] >= lo[0]) & (xc - half[0] <= hi[0]))[0]
    iy = np.nonzero((yc + half[1] >= lo[1]) & (yc - half[1] <= hi[1]))[0]
    iz = np.nonzero((zc + half[2] >= lo[2]) & (zc - half[2] <= hi[2]))[0]
    if ix.size and iy.size and iz.size:
        sub_xy = xy[np.ix_(ix, iy)].reshape(-1, n_xy, 2)  # (n_layer, n_xy, 2)
        sub_surface = surface[np.ix_(ix, iy)].reshape(-1, n_xy)  # (n_layer, n_xy)
        for k in iz:
            z_sub = zc[k] + z_off  # (n_z,)
            pts = np.empty((sub_xy.shape[0], n_xy, n_z, 3))
            pts[..., :2] = sub_xy[:, :, None, :]
            pts[..., 2] = z_sub[None, None, :]
            inside = orebody.contains(pts.reshape(-1, 3)).reshape(pts.shape[:3])
            below_k = z_sub[None, None, :] <= sub_surface[:, :, None]
            frac = (inside & below_k).mean(axis=(1, 2)).astype(np.float32)
            ore[np.ix_(ix, iy, [k])] = frac.reshape(len(ix), len(iy), 1)
    return BlockFractions(ore=ore, solid=solid)


def assemble_block_model(
    grid: VoxelGrid,
    terrain: Terrain,
    orebody: Orebody,
    grade: npt.NDArray[np.float32],
    rock_quality: npt.NDArray[np.float32],
    fault_fields: FaultFields,
    n_sub: int = DEFAULT_SUBSAMPLES,
) -> BlockModel:
    fractions = sample_block_fractions(grid, orebody, terrain, n_sub)
    ore_fraction = fractions.ore
    air = fractions.solid < SOLID_FRACTION_THRESHOLD
    # ore ⊆ solid, so ore_fraction >= 0.5 already implies solid >= 0.5 (not AIR)
    ore_flag = ore_fraction >= ORE_FRACTION_THRESHOLD

    rock_type = np.full(grid.shape, RockType.HOST, dtype=np.uint8)
    rock_type[ore_flag] = RockType.ORE
    rock_type[air] = RockType.AIR

    grade_out = np.where(ore_fraction > 0, grade, 0.0).astype(np.float32)
    rq = rock_quality.copy()
    rq[air] = 0.0

    return BlockModel(
        grid=grid,
        rock_type=rock_type,
        ore_fraction=ore_fraction,
        ore_flag=ore_flag,
        grade=grade_out,
        rock_quality=rq,
        fault_signed_distance=fault_fields.signed_distance,
        fault_zone=fault_fields.zone,
        fault_influence=fault_fields.influence,
        meta={
            "subsamplesPerAxis": n_sub,
            "oreFractionThreshold": ORE_FRACTION_THRESHOLD,
            "solidFractionThreshold": SOLID_FRACTION_THRESHOLD,
        },
    )
