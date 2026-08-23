from __future__ import annotations

import numpy as np
import pytest

from minegen.core.models import TerrainConfig, WorldConfig
from minegen.world.terrain import generate_terrain

WORLD = WorldConfig(size_x=400, size_y=300, depth=200)
CFG = TerrainConfig(grid_spacing=10, base_elevation=100, relief=40, octaves=3)


def test_grid_shape_and_axes() -> None:
    t = generate_terrain(WORLD, CFG, seed=1)
    assert t.z.shape == (41, 31)
    assert t.x[0] == -200 and t.x[-1] == 200
    assert t.y[0] == -150 and t.y[-1] == 150
    assert t.spacing == 10


def test_elevation_statistics_match_config() -> None:
    t = generate_terrain(WORLD, CFG, seed=1)
    assert t.z.mean() == pytest.approx(CFG.base_elevation, abs=1e-9)
    assert t.z_max - t.z_min == pytest.approx(CFG.relief, abs=1e-9)
    assert np.isfinite(t.z).all()


def test_zero_relief_is_flat() -> None:
    t = generate_terrain(WORLD, TerrainConfig(relief=0, base_elevation=250), seed=1)
    assert np.all(t.z == 250)


def test_terrain_is_deterministic_for_seed() -> None:  # gate A
    a = generate_terrain(WORLD, CFG, seed=42)
    b = generate_terrain(WORLD, CFG, seed=42)
    assert np.array_equal(a.z, b.z)


def test_terrain_changes_with_seed() -> None:  # gate B
    a = generate_terrain(WORLD, CFG, seed=42)
    b = generate_terrain(WORLD, CFG, seed=43)
    assert not np.array_equal(a.z, b.z)
    assert np.abs(a.z - b.z).max() > 1.0


def test_terrain_is_smooth_not_white_noise() -> None:
    t = generate_terrain(WORLD, CFG, seed=7)
    step = np.abs(np.diff(t.z, axis=0)).max()
    assert step < 0.2 * CFG.relief  # no single-cell jumps close to the full relief


def test_sample_interpolates_and_clamps() -> None:
    t = generate_terrain(WORLD, CFG, seed=3)
    # exact at grid nodes
    pts = np.array([[t.x[5], t.y[7]], [t.x[0], t.y[0]]])
    np.testing.assert_allclose(t.sample(pts), [t.z[5, 7], t.z[0, 0]], atol=1e-9)
    # midpoint is the mean of the two neighbouring nodes (bilinear)
    mid = np.array([[(t.x[5] + t.x[6]) / 2, t.y[7]]])
    assert t.sample(mid)[0] == pytest.approx((t.z[5, 7] + t.z[6, 7]) / 2)
    # outside the grid clamps to the edge instead of extrapolating
    assert t.sample(np.array([[10_000.0, 10_000.0]]))[0] == pytest.approx(t.z[-1, -1])
