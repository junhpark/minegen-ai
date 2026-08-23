from __future__ import annotations

import math

import numpy as np
import pytest

from minegen.core.coordinates import GLOBAL_UP, azimuth_to_unit_vector
from minegen.core.models import OrebodyConfig, Point3D
from minegen.world.orebody import TabularOrebody, build_orebody


def make(strike: float, dip: float, center=(200.0, 100.0, 0.0)) -> TabularOrebody:  # type: ignore[no-untyped-def]
    cfg = OrebodyConfig(
        center=Point3D(x=center[0], y=center[1], z=center[2]),
        strike_deg=strike,
        dip_deg=dip,
        length=600,
        height=350,
        thickness=12,
    )
    ob = build_orebody(cfg)
    assert isinstance(ob, TabularOrebody)
    return ob


# -- gate C: orientation --------------------------------------------------- #


@pytest.mark.parametrize("strike", [0.0, 90.0, 35.0])
@pytest.mark.parametrize("dip", [30.0, 70.0, 90.0])
def test_local_world_roundtrip(strike: float, dip: float) -> None:
    ob = make(strike, dip)
    rng = np.random.default_rng(0)
    pts = rng.uniform(-800, 800, size=(500, 3))
    np.testing.assert_allclose(ob.to_world(ob.to_local(pts)), pts, atol=1e-9)
    np.testing.assert_allclose(ob.to_local(ob.to_world(pts)), pts, atol=1e-9)


def test_strike_0_axes() -> None:
    ob = make(0.0, 70.0)
    np.testing.assert_allclose(ob.u, [0, 1, 0], atol=1e-12)  # along North
    np.testing.assert_allclose(ob.v[:2] / np.linalg.norm(ob.v[:2]), [1, 0], atol=1e-12)  # dips East


def test_strike_90_axes() -> None:
    ob = make(90.0, 70.0)
    np.testing.assert_allclose(ob.u, [1, 0, 0], atol=1e-12)  # along East
    np.testing.assert_allclose(ob.v[:2] / np.linalg.norm(ob.v[:2]), [0, -1], atol=1e-12)  # dips S


@pytest.mark.parametrize("dip", [30.0, 70.0, 90.0])
def test_vertical_extent_matches_dip(dip: float) -> None:
    ob = make(35.0, dip)
    zlo, zhi = ob.z_range
    # slab: vertical extent = height·sin(dip) + thickness·cos(dip)
    expected = 350 * math.sin(math.radians(dip)) + 12 * math.cos(math.radians(dip))
    assert zhi - zlo == pytest.approx(expected, abs=1e-9)


def test_geometry_follows_strike_and_dip() -> None:
    ob = make(35.0, 70.0)
    # a point 250 m along strike is inside; 310 m is outside
    assert ob.contains(ob.center + 250 * ob.u)
    assert not ob.contains(ob.center + 310 * ob.u)
    # 170 m down dip inside; 180 outside
    assert ob.contains(ob.center + 170 * ob.v)
    assert not ob.contains(ob.center + 180 * ob.v)
    # across thickness: 5 m inside, 7 m outside on both sides
    assert ob.contains(ob.center + 5 * ob.w) and ob.contains(ob.center - 5 * ob.w)
    assert not ob.contains(ob.center + 7 * ob.w) and not ob.contains(ob.center - 7 * ob.w)


# -- gate D: footwall convention ------------------------------------------- #


def test_footwall_point_is_below_and_opposite_dip_direction() -> None:
    ob = make(35.0, 70.0)
    p = ob.footwall_point(0.0, 0.0, offset=20.0)
    # outside the orebody, at 6 + 20 = 26 m perpendicular distance
    assert not ob.contains(p)
    assert abs(ob.to_local(p)[2]) == pytest.approx(26.0)
    # footwall is below the plane …
    assert float(np.dot(ob.w, GLOBAL_UP)) < 0
    assert p[2] < ob.center[2]
    # … and horizontally on the side opposite the dip direction
    dip_dir = azimuth_to_unit_vector(35.0 + 90.0)
    assert float(np.dot(p - ob.center, dip_dir)) < 0


def test_footwall_point_for_vertical_orebody_is_horizontal_offset() -> None:
    ob = make(35.0, 90.0)
    p = ob.footwall_point(0.0, 0.0, offset=20.0)
    assert p[2] == pytest.approx(ob.center[2])
    assert np.linalg.norm(p[:2] - ob.center[:2]) == pytest.approx(26.0)


# -- mesh / volume --------------------------------------------------------- #


def test_volume_and_tonnes() -> None:
    ob = make(35.0, 70.0)
    assert ob.volume() == 600 * 350 * 12
    assert ob.tonnes() == pytest.approx(600 * 350 * 12 * 2.8)


def test_mesh_is_closed_box_with_outward_normals() -> None:
    ob = make(35.0, 70.0)
    verts, faces = ob.mesh()
    assert verts.shape == (8, 3) and faces.shape == (12, 3)
    # every corner lies exactly on the slab boundary
    local = ob.to_local(verts)
    np.testing.assert_allclose(np.abs(local), np.tile(ob.half_extents, (8, 1)), atol=1e-9)
    # each triangle's normal points away from the center (consistent CCW winding)
    for tri in faces:
        a, b, c = verts[tri]
        n = np.cross(b - a, c - a)
        centroid = (a + b + c) / 3
        assert float(np.dot(n, centroid - ob.center)) > 0
    # closed: each undirected edge appears exactly twice
    edges = sorted(tuple(sorted((int(t[i]), int(t[(i + 1) % 3])))) for t in faces for i in range(3))
    assert all(edges.count(e) == 2 for e in set(edges))
    assert len(set(edges)) == 18
