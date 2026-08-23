"""Coordinate convention tests (docs/coordinate-system.md, CLAUDE.md 25/26/28)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from minegen.core.coordinates import (
    GLOBAL_UP,
    azimuth_to_unit_vector,
    decline_heuristic_distance,
    grade_limited_length,
    gradient_of,
    gravity_aligned_frame,
    strike_dip_frame,
    strike_dip_vectors,
    unit_vector_to_azimuth,
)

# -- azimuths ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("azimuth", "expected"),
    [(0.0, (0, 1, 0)), (90.0, (1, 0, 0)), (180.0, (0, -1, 0)), (270.0, (-1, 0, 0))],
)
def test_azimuth_is_clockwise_from_north(azimuth: float, expected: tuple[int, int, int]) -> None:
    np.testing.assert_allclose(azimuth_to_unit_vector(azimuth), expected, atol=1e-12)
    assert unit_vector_to_azimuth(np.array(expected, dtype=float)) == pytest.approx(azimuth)


def test_azimuth_roundtrip() -> None:
    for a in np.linspace(0, 359.9, 37):
        assert unit_vector_to_azimuth(azimuth_to_unit_vector(a)) == pytest.approx(a, abs=1e-9)


# -- strike / dip frame (rule 28) --------------------------------------------


def test_strike_dip_vectors_are_orthonormal_and_right_handed() -> None:
    for strike in (0.0, 35.0, 120.0, 275.0):
        for dip in (10.0, 45.0, 70.0, 90.0):
            u, v, w = strike_dip_vectors(strike, dip)
            m = np.vstack([u, v, w])
            np.testing.assert_allclose(m @ m.T, np.eye(3), atol=1e-12)
            assert np.linalg.det(m) == pytest.approx(1.0)


def test_strike_vector_is_horizontal_along_strike_azimuth() -> None:
    u, _, _ = strike_dip_vectors(35.0, 70.0)
    assert u[2] == pytest.approx(0.0)
    assert unit_vector_to_azimuth(u) == pytest.approx(35.0)


def test_dip_vector_points_down_dip_at_strike_plus_90() -> None:
    strike, dip = 35.0, 70.0
    _, v, _ = strike_dip_vectors(strike, dip)
    assert v[2] == pytest.approx(-math.sin(math.radians(dip)))
    assert unit_vector_to_azimuth(v) == pytest.approx(strike + 90.0)


def test_normal_points_to_footwall_side() -> None:
    """w = u × v has negative z for dip < 90 (footwall is below the plane)."""
    _, _, w = strike_dip_vectors(35.0, 70.0)
    assert w[2] == pytest.approx(-math.cos(math.radians(70.0)))
    assert w[2] < 0
    _, _, w_vertical = strike_dip_vectors(35.0, 90.0)
    assert w_vertical[2] == pytest.approx(0.0, abs=1e-12)


def test_frame_roundtrip_and_tabular_inclusion() -> None:
    center = np.array([200.0, 100.0, 0.0])
    frame = strike_dip_frame(center, strike_deg=35.0, dip_deg=70.0)
    assert frame.is_right_handed

    rng = np.random.default_rng(42)
    pts = rng.uniform(-500, 500, size=(200, 3))
    local = frame.world_to_local(pts)
    back = frame.local_to_world(local)
    np.testing.assert_allclose(back, pts, atol=1e-9)

    # a point displaced along strike by 100 m sits at local (100, 0, 0)
    u, _, _ = strike_dip_vectors(35.0, 70.0)
    np.testing.assert_allclose(frame.world_to_local(center + 100 * u), [100, 0, 0], atol=1e-9)

    # tabular inclusion test in local coords: length 600, height 350, thickness 12
    inside = frame.local_to_world(np.array([250.0, -170.0, 5.0]))
    outside = frame.local_to_world(np.array([250.0, -170.0, 7.0]))
    l_in, l_out = frame.world_to_local(inside), frame.world_to_local(outside)
    assert abs(l_in[0]) <= 300 and abs(l_in[1]) <= 175 and abs(l_in[2]) <= 6
    assert abs(l_out[2]) > 6


# -- gravity-aligned sweep frame (rule 26) -----------------------------------


@pytest.mark.parametrize(
    "tangent",
    [
        [0.0, 1.0, 0.0],  # flat, north
        [1.0, 0.0, 0.0],  # flat, east
        [0.0, 1.0, 0.12],  # 12 % up-grade north
        [0.7, -0.3, -0.10],  # down-grade, arbitrary heading
        [-0.2, 0.9, 0.08],
    ],
)
def test_gravity_aligned_frame_is_orthonormal_right_handed_with_level_floor(
    tangent: list[float],
) -> None:
    f = gravity_aligned_frame(np.array(tangent))
    m = np.vstack([f.right, f.forward, f.up])
    np.testing.assert_allclose(m @ m.T, np.eye(3), atol=1e-12)
    # (right, forward, up) right-handed: right × forward = up
    np.testing.assert_allclose(np.cross(f.right, f.forward), f.up, atol=1e-12)
    # floor is level across the section: `right` has no vertical component
    assert f.right[2] == pytest.approx(0.0, abs=1e-12)
    # up is the global-up projection, so it never points downward
    assert float(np.dot(f.up, GLOBAL_UP)) > 0.0


def test_gravity_aligned_frame_right_is_drivers_right() -> None:
    f = gravity_aligned_frame(np.array([0.0, 1.0, 0.0]))  # facing north
    np.testing.assert_allclose(f.right, [1.0, 0.0, 0.0], atol=1e-12)  # east


def test_gravity_aligned_frame_does_not_bank_along_a_spiral() -> None:
    """Sweep a full spiral turn at 12 %: `right` must stay horizontal everywhere
    (a parallel-transport frame would accumulate roll here)."""
    r, g = 18.0, 0.12
    for theta in np.linspace(0, 2 * math.pi, 73):
        tangent = np.array([-r * math.sin(theta), r * math.cos(theta), g * r])
        f = gravity_aligned_frame(tangent)
        assert abs(f.right[2]) < 1e-12


def test_gravity_aligned_frame_rejects_near_vertical() -> None:
    with pytest.raises(ValueError, match="vertical"):
        gravity_aligned_frame(np.array([0.0, 0.0, 1.0]))
    with pytest.raises(ValueError, match="vertical"):
        gravity_aligned_frame(np.array([0.01, 0.0, -1.0]))


# -- gradients and the decline heuristic (rule 25) ---------------------------


def test_gradient_is_vertical_over_horizontal() -> None:
    assert gradient_of(np.zeros(3), np.array([100.0, 0.0, 12.0])) == pytest.approx(0.12)
    assert gradient_of(np.zeros(3), np.array([60.0, 80.0, -10.0])) == pytest.approx(-0.10)
    assert math.isinf(gradient_of(np.zeros(3), np.array([0.0, 0.0, 5.0])))


def test_grade_limited_length_matches_closed_form() -> None:
    dz, g = 300.0, 0.12
    expected = abs(dz) * math.sqrt(1 + g**2) / g
    assert grade_limited_length(dz, g) == pytest.approx(expected)
    assert grade_limited_length(-dz, g) == pytest.approx(expected)


def test_decline_heuristic_is_max_of_euclid_and_grade_bound() -> None:
    p = np.array([0.0, 0.0, 280.0])
    deep_goal = np.array([200.0, 0.0, -20.0])  # 300 m below, 200 m away
    h = decline_heuristic_distance(p, deep_goal, 0.12)
    assert h == pytest.approx(grade_limited_length(300.0, 0.12))
    assert h > np.linalg.norm(deep_goal - p)  # euclid is far too optimistic

    far_goal = np.array([3000.0, 0.0, 270.0])  # mostly horizontal
    h2 = decline_heuristic_distance(p, far_goal, 0.12)
    assert h2 == pytest.approx(float(np.linalg.norm(far_goal - p)))


def test_decline_heuristic_is_admissible_for_a_feasible_helix() -> None:
    """A 12 % helix from p to goal is a feasible path; its length must be >= h."""
    r, g = 18.0, 0.12
    theta_total = 2 * math.pi * 2.5
    start = np.array([r, 0.0, 0.0])
    end = np.array([r * math.cos(theta_total), r * math.sin(theta_total), -g * r * theta_total])
    # exact helix length: r·θ·sqrt(1 + g²)
    helix_len = r * theta_total * math.sqrt(1 + g**2)
    h = decline_heuristic_distance(start, end, g)
    assert h <= helix_len + 1e-9
    # at maximum grade the bound is tight, which is what makes it a good heuristic
    assert h == pytest.approx(helix_len)
