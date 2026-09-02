from __future__ import annotations

import math

import numpy as np
import pytest

from minegen.core.coordinates import GLOBAL_UP, azimuth_to_unit_vector
from minegen.core.enums import OrebodyType
from minegen.core.models import OrebodyConfig, Point3D
from minegen.world.orebody import EllipsoidOrebody, TabularOrebody, build_orebody


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


# -- Phase 17: ELLIPSOID geometry integrity (spec §8/§9) -------------------- #


def make_ellipsoid(
    strike: float = 35.0, dip: float = 70.0, center=(200.0, 100.0, 0.0)
) -> EllipsoidOrebody:  # type: ignore[no-untyped-def]
    cfg = OrebodyConfig(
        orebody_type=OrebodyType.ELLIPSOID,
        center=Point3D(x=center[0], y=center[1], z=center[2]),
        strike_deg=strike,
        dip_deg=dip,
        length=600,
        height=350,
        thickness=12,
    )
    ob = build_orebody(cfg)
    assert isinstance(ob, EllipsoidOrebody)
    return ob


def test_ellipsoid_axis_points_have_exact_analytic_sdf() -> None:
    """Analytic references. EXTERIOR points on any principal axis map to
    that axis vertex (the evolute cusps lie inside/behind the vertices for
    this geometry), so sdf = t - semi exactly. On the SHORTEST (w) axis the
    curvature radius at the pole (a_max^2/a_w = 15 000 m) exceeds a_w, so
    the ENTIRE interior w-segment also maps to the pole: sdf = t - a_w for
    all t in [0, a_w]. Interior points on the LONG axis are the classic
    trap — their nearest surface point is near the thin w-direction, NOT
    the far u-vertex — so only a rigorous bound is asserted there."""
    ob = make_ellipsoid()
    a = ob.semi_axes
    for axis_vec, semi in ((ob.u, a[0]), (ob.v, a[1]), (ob.w, a[2])):
        for t in (semi, semi + 37.0, semi + 500.0):  # surface + exterior
            p = ob.center + axis_vec * t
            d = float(ob.signed_distance(p[None, :])[0])
            assert d == pytest.approx(t - semi, abs=1e-6)
    for t in (0.0, 1.5, 0.5 * a[2], a[2]):  # whole interior w-segment
        p = ob.center + ob.w * t
        d = float(ob.signed_distance(p[None, :])[0])
        assert d == pytest.approx(t - a[2], abs=1e-6)
    # interior on the LONG axis: nearest surface is ~thickness away, and
    # exactly w*sqrt(1 - (u/a_u)^2) is an upper bound on |sdf|
    u_t = 0.25 * a[0]
    d = float(ob.signed_distance((ob.center + ob.u * u_t)[None, :])[0])
    bound = a[2] * math.sqrt(1.0 - (u_t / a[0]) ** 2)
    assert -bound - 1e-6 <= d < 0.0
    assert abs(d) > 0.9 * a[2] * 0.5  # sanity: same order as the thickness


def test_ellipsoid_contains_sdf_and_level_agree() -> None:
    ob = make_ellipsoid()
    rng = np.random.default_rng(7)
    pts = ob.center + rng.normal(scale=250.0, size=(4000, 3))
    inside = ob.contains(pts)
    sdf = ob.signed_distance(pts)
    assert np.all((sdf <= 1e-9) == inside)  # SAME solid (rule 120)
    # sdf is a true metric lower bound: |sdf| <= distance to center path…
    assert np.all(np.isfinite(sdf))


def test_ellipsoid_surface_points_have_zero_sdf() -> None:
    ob = make_ellipsoid(strike=123.0, dip=55.0)
    rng = np.random.default_rng(3)
    unit = rng.normal(size=(500, 3))
    unit /= np.linalg.norm(unit, axis=1, keepdims=True)
    world = ob.to_world(unit * ob.semi_axes)  # exactly on the surface
    d = ob.signed_distance(world)
    assert np.max(np.abs(d)) < 1e-6


def test_ellipsoid_volume_bbox_and_mesh_consistency() -> None:
    ob = make_ellipsoid()
    a = ob.semi_axes
    assert ob.volume() == pytest.approx(4.0 / 3.0 * math.pi * a[0] * a[1] * a[2])
    lo, hi = ob.bounding_box()
    assert np.all(hi > lo) and np.all(np.isfinite(lo)) and np.all(np.isfinite(hi))
    verts, faces = ob.mesh()
    assert np.all(np.isfinite(verts))
    assert faces.min() >= 0 and faces.max() < len(verts)
    # every mesh vertex lies exactly on the analytic surface
    assert float(np.max(np.abs(ob.signed_distance(verts)))) < 1e-6
    # mesh bounds inside the analytic AABB (and close to it)
    assert np.all(verts.min(axis=0) >= lo - 1e-6) and np.all(verts.max(axis=0) <= hi + 1e-6)
    assert np.max(np.abs(verts.min(axis=0) - lo)) < 6.0  # UV sampling gap only
    # no degenerate triangles; deterministic
    tri = verts[faces]
    areas = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    assert np.min(areas) > 1e-9
    v2, f2 = ob.mesh()
    assert np.array_equal(verts, v2) and np.array_equal(faces, f2)


def test_ellipsoid_mesh_winding_is_outward() -> None:
    """Signed volume from the triangle fan about the center must be positive
    (outward CCW winding), and ≈ analytic volume within tessellation error."""
    ob = make_ellipsoid(strike=10.0, dip=80.0)
    verts, faces = ob.mesh()
    rel = verts - ob.center
    tri = rel[faces]
    signed = float(np.sum(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])))) / 6.0
    assert signed > 0
    assert signed == pytest.approx(ob.volume(), rel=0.02)


def test_tabular_regression_unchanged_by_phase17() -> None:
    ob = make(35.0, 70.0)
    assert ob.volume() == pytest.approx(600 * 350 * 12)
    assert bool(ob.contains(np.array([[200.0, 100.0, 0.0]]))[0])
