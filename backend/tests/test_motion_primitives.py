"""Phase 04 gate tests: motion primitives and goal connectors (rules 47–51)."""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest

from minegen.core.coordinates import wrap_angle_rad
from minegen.design.motion_primitives import (
    Pose,
    PrimitiveSet,
    Steering,
    azimuth_between,
    dubins_cs_length,
)

R, BINS, GMAX = 18.0, 16, 0.12
PS = PrimitiveSet(R, BINS, GMAX, (0.0, 0.5, 1.0), 2.0)
DTHETA = 2 * math.pi / BINS
LH = R * DTHETA


def test_primitive_geometry_constants() -> None:
    assert PS.heading_bins == 16
    assert PS.heading_step == pytest.approx(math.radians(22.5))
    assert PS.horizontal_length == pytest.approx(7.0686, abs=1e-4)
    assert PS.grades == (0.0, -0.06, -0.12)
    assert PS.branching_factor == 9
    assert len(PS.expand(Pose(0, 0, 0, 0))) == 9


@pytest.mark.parametrize("heading_deg", [0.0, 37.0, 90.0, 200.0, -45.0])
def test_straight_primitive_endpoint(heading_deg: float) -> None:
    pose = Pose(12.3, -4.5, 80.0, math.radians(heading_deg))
    prims = [p for p in PS.expand(pose) if p.steering is Steering.STRAIGHT]
    for p in prims:
        expected = pose.position + np.array(
            [LH * math.sin(pose.heading), LH * math.cos(pose.heading), p.grade * LH]
        )
        err = float(np.linalg.norm(p.end.position - expected))
        assert err < 1e-12
        assert wrap_angle_rad(p.end.heading - pose.heading) == pytest.approx(0.0, abs=1e-12)
        assert p.samples.shape[0] == 5  # 7.07 m / 2 m → 5 samples incl. both ends
        assert np.allclose(p.samples[0], pose.position) and np.allclose(p.samples[-1], expected)


@pytest.mark.parametrize("heading_deg", [0.0, 37.0, 123.0])
def test_turn_primitive_endpoint_and_heading(heading_deg: float) -> None:
    pose = Pose(5.0, 5.0, 10.0, math.radians(heading_deg))
    f, r = pose.forward, pose.right
    for p in PS.expand(pose):
        if p.steering is Steering.STRAIGHT:
            continue
        side = float(p.steering)
        expected_xy = (
            pose.position[:2] + R * math.sin(DTHETA) * f + side * R * (1 - math.cos(DTHETA)) * r
        )
        assert float(np.linalg.norm(p.end.position[:2] - expected_xy)) < 1e-12
        # exactly one heading bin, in the turn direction (right = clockwise = +azimuth)
        assert wrap_angle_rad(p.end.heading - pose.heading) == pytest.approx(
            side * DTHETA, abs=1e-12
        )
        assert p.radius == pytest.approx(R)
        # every sample lies on the turning circle
        center = pose.position[:2] + side * R * r
        assert np.allclose(np.linalg.norm(p.samples[:, :2] - center, axis=1), R, atol=1e-9)


def test_max_grade_dz_is_continuous_not_rounded() -> None:
    p = next(
        q
        for q in PS.expand(Pose(0, 0, 0, 0))
        if q.steering is Steering.STRAIGHT and q.grade == -GMAX
    )
    assert p.end.z == pytest.approx(-GMAX * LH, abs=1e-12)
    assert p.end.z == pytest.approx(-0.848230, abs=1e-6)
    assert p.end.z != -1.0
    assert p.length_3d == pytest.approx(LH * math.sqrt(1 + GMAX**2))
    # z samples are linear in horizontal arc length
    assert np.allclose(np.diff(p.samples[:, 2]), p.samples[1, 2] - p.samples[0, 2])


def test_goal_shot_exact_endpoint_radius_and_grade() -> None:
    rng = np.random.default_rng(3)
    n_ok = 0
    for _ in range(3000):
        d = rng.uniform(5, 35)
        ang = rng.uniform(-math.pi, math.pi)
        psi = rng.uniform(-math.radians(45), math.radians(45))
        pos = np.array([d * math.sin(ang), d * math.cos(ang)])
        heading = math.atan2(-pos[0], -pos[1]) + psi
        pose = Pose(pos[0], pos[1], rng.uniform(0, 4), heading)
        target = np.array([0.0, 0.0, 0.0])
        prims, _reason = PS.goal_shot(pose, target, math.radians(45))
        if prims is None:
            continue
        n_ok += 1
        assert float(np.linalg.norm(prims[-1].samples[-1] - target)) < 1e-9
        assert float(np.linalg.norm(prims[-1].end.position - target)) < 1e-9
        total_turn = 0.0
        for p in prims:
            assert p.radius >= R - 1e-9
            assert -GMAX - 1e-9 <= p.grade <= 0.0
            total_turn += abs(p.horizontal_length * p.curvature)
        assert total_turn <= math.radians(45) + 1e-9
        # continuity between connector pieces
        for a, b in itertools.pairwise(prims):
            assert np.allclose(a.samples[-1], b.samples[0])
            assert (
                wrap_angle_rad(a.end.heading - b.end.heading) == pytest.approx(0.0, abs=1e-9)
                or b.curvature == 0
            )
    assert n_ok > 1000  # connector exists for a substantial share of the window


def test_goal_shot_rejects_upward_and_too_steep() -> None:
    pose = Pose(0.0, -20.0, 0.0, 0.0)  # facing north, target 20 m ahead
    assert PS.goal_shot(pose, np.array([0.0, 0.0, 1.0]), math.pi)[0] is None  # above
    assert PS.goal_shot(pose, np.array([0.0, 0.0, -10.0]), math.pi)[0] is None  # 50 % grade
    prims, _ = PS.goal_shot(pose, np.array([0.0, 0.0, -2.0]), math.pi)
    assert prims is not None and prims[0].grade == pytest.approx(-0.1)


def test_dubins_cs_lower_bound_matches_connector_and_distance() -> None:
    rng = np.random.default_rng(1)
    for _ in range(500):
        d = rng.uniform(40, 200)
        ang = rng.uniform(-math.pi, math.pi)
        psi = rng.uniform(-math.pi, math.pi)
        pos = np.array([d * math.sin(ang), d * math.cos(ang)])
        pose = Pose(pos[0], pos[1], 0.0, math.atan2(-pos[0], -pos[1]) + psi)
        length = dubins_cs_length(pose, np.zeros(2), R)
        assert length >= d - 1e-9
        prims, _ = PS.goal_shot_arc_straight(pose, np.zeros(3), math.pi)
        if prims is not None:
            assert length == pytest.approx(sum(p.horizontal_length for p in prims), abs=1e-6)
    # straight ahead → plain distance, for every heading (regression: rounding once
    # wrapped a −1e-16 turn into a full circle)
    for deg in (0.0, 90.0, 37.0, 180.0, -45.0):
        h = math.radians(deg)
        ahead = np.array([152.93 * math.sin(h), 152.93 * math.cos(h)])
        assert dubins_cs_length(Pose(0, 0, 0, h), ahead, R) == pytest.approx(152.93, abs=1e-9)


def test_azimuth_between_is_clockwise_from_north() -> None:
    assert azimuth_between(np.zeros(3), np.array([0.0, 1.0, 0.0])) == pytest.approx(0.0)
    assert azimuth_between(np.zeros(3), np.array([1.0, 0.0, 0.0])) == pytest.approx(math.pi / 2)
