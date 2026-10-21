"""Hardening PR-5 round 2 (rule 227 f) — capped end planes and jump-robust
chord fidelity.

The PR-6 acceptance tour built the default "Create mine" scenario and its
development mesh FAILED (``JUNCTION_CLIP_TOPOLOGY: JUNCTION:L01:S-08: floor
quad (1, 10) boundary not representable after 10 subdivisions``): a crosscut
on a drift EXTREMITY has its floor centre line IN the drift's end plane, the
judging envelope reported every point beyond its ring span as +inf, so the
plane read "inside" or "outside" at floating-point whim and a quad edge lying
in it never converged. These tests pin the two contracts that close it — a
judging envelope's declared REAL ends are continuous capped planes
(``TubeEnvelope.with_end_planes``), and a fidelity sample failing ON a
remaining jump is re-judged a vertex-merge distance inside its loop — and
rebuild the extremity crosscut synthetically in 16 poses (rotations and
non-round coordinates, so the plane is read by floating point, never by an
exact zero). Measured under 4b6236e: pose 12 of this set raised the production
error (``T12: floor quad (1, 10) boundary not representable``), the other 15
happened to read the plane on one side — the same luck as the TABULAR
fixture's 8 extremity stations. Recorded, never tuned.
"""

from __future__ import annotations

import numpy as np
import pytest

from minegen.design.junctions import (
    CHILD_JUDGE_LEVEL,
    JUNCTION_RING_SPACING_FRACTION,
    JUNCTION_SURFACE_TOLERANCE_FRACTION,
    JUNCTION_WINDOW_WIDTHS,
    Junction,
    TubeEnvelope,
    _edges_stay,
    cut_cap,
    cut_mouth_cap,
    cut_tube,
)
from minegen.design.profile import build_profile, secondary_profile
from minegen.design.tunnel_mesh import (
    _envelope_segment,
    build_ring_chain,
    cap_fan_corners,
    sweep_rings,
)
from tests.conftest import small_scenario


def _tube(points: np.ndarray, shape, spacing: float, near: np.ndarray | None, width: float):
    chain = build_ring_chain(
        [_envelope_segment(points.ravel().tolist())],
        spacing,
        refine_near=near,
        refine_radius=JUNCTION_WINDOW_WIDTHS * width,
        refine_spacing=JUNCTION_RING_SPACING_FRACTION * width,
    )
    rings = sweep_rings(chain, shape)
    return TubeEnvelope.build(chain.centers, chain.tangents, shape), rings


@pytest.fixture(scope="module")
def profile():
    sc = small_scenario(with_fault=False)
    dev_profile = secondary_profile(sc.tunnel_profile)
    return (
        build_profile(sc.ramp, dev_profile),
        float(sc.ramp.tunnel_width),
        float(dev_profile.ring_max_spacing),
    )


@pytest.fixture(scope="module")
def straight(profile):
    """A straight tube along +X from x = 0 to x = 20 (floor centre line at z = 0)."""
    shape, width, spacing = profile
    pts = np.array([[0.0, 0.0, 0.0], [20.0, 0.0, 0.0]])
    env, rings = _tube(pts, shape, spacing, None, width)
    return env, rings, width


def test_declared_end_plane_is_a_continuous_cap_and_undeclared_ends_stay_inf(straight):
    env, _rings, _ = straight
    r = int(env.centers.shape[0])
    full = (0, r)
    beyond = np.array([[20.5, 0.0, 1.0]])
    on = np.array([[20.0, 0.0, 1.0]])
    inside = np.array([[19.7, 0.0, 1.0]])
    # the default envelope (every measurement instrument): beyond the span is +inf
    assert env.end_planes == (False, False)
    assert np.isinf(env.signed_distance(beyond, full)[0])
    capped = env.with_end_planes(False, True)
    assert capped.end_planes == (False, True)
    # the end plane joins the half-planes: 0.5 m beyond reads +0.5, the plane 0,
    # 0.3 m inside −0.3 (the profile is 1 m away, the plane nearer)
    assert capped.signed_distance(beyond, full)[0] == pytest.approx(0.5, abs=1e-9)
    assert abs(capped.signed_distance(on, full)[0]) <= 1e-9
    assert capped.signed_distance(inside, full)[0] == pytest.approx(-0.3, abs=1e-9)
    # deep inside the profile is unchanged by the cap
    mid = np.array([[10.0, 0.0, 1.0]])
    assert capped.signed_distance(mid, full)[0] == pytest.approx(
        env.signed_distance(mid, full)[0], abs=1e-12
    )
    # a WINDOW end is not a real end: beyond it stays +inf even when declared
    window = (0, r - 3)
    assert np.isinf(capped.signed_distance(beyond, window)[0])
    # the start plane, symmetric; the lowered floor keeps the declaration
    start = env.with_end_planes(True, False)
    assert start.signed_distance(np.array([[-0.5, 0.0, 1.0]]), full)[0] == pytest.approx(0.5)
    assert abs(start.signed_distance(np.array([[0.0, 0.0, 1.0]]), full)[0]) <= 1e-9
    assert np.isinf(start.signed_distance(beyond, full)[0])
    assert start.floor_lowered(1.0).end_planes == (True, False)
    # the plain envelope is NOT changed by the declaration elsewhere
    assert np.isinf(env.signed_distance(beyond, full)[0])


def test_fidelity_samples_on_a_jump_are_rejudged_inside_the_loop(straight):
    env, _rings, width = straight
    r = int(env.centers.shape[0])
    tol = JUNCTION_SURFACE_TOLERANCE_FRACTION * width
    window = (0, r)
    # a quad beyond the undeclared end whose near edge lies IN the end plane:
    # the edge samples read the inside value at x = 20 exactly, the nudge
    # toward the quad interior reads the +inf side — the quad is outside
    outside = np.array([[20.0, -1.0, 0.5], [21.0, -1.0, 0.5], [21.0, 1.0, 0.5], [20.0, 1.0, 0.5]])
    assert _edges_stay(outside, env, window, tol, outside=True, level=CHILD_JUDGE_LEVEL)
    # the mirror quad inside the span is inside-or-on
    inside = np.array([[19.0, -1.0, 0.5], [20.0, -1.0, 0.5], [20.0, 1.0, 0.5], [19.0, 1.0, 0.5]])
    assert _edges_stay(inside, env, window, tol, outside=False, level=CHILD_JUDGE_LEVEL)
    # a genuine half-metre intrusion keeps failing: the nudge is a tie-break,
    # never a tolerance
    intruding = np.array([[19.5, -1.0, 0.5], [21.0, -1.0, 0.5], [21.0, 1.0, 0.5], [19.5, 1.0, 0.5]])
    assert not _edges_stay(intruding, env, window, tol, outside=True, level=CHILD_JUDGE_LEVEL)


POSES = list(range(16))


@pytest.mark.parametrize("k", POSES)
def test_extremity_crosscut_floor_is_clipped_on_the_drift_end_plane(profile, k: int) -> None:
    """A drift ending AT the station, a crosscut leaving it perpendicularly:
    the crosscut's floor centre line lies in the drift's end plane. Every kept
    child floor remainder vertex must lie on or outside the drift (judged on
    the drift envelope with BOTH ends capped, so the end plane reads 0 instead
    of +inf / "inside" at random), every chord ON the drift's surface (its end
    plane along the crosscut axis, its side wall where the crosscut leaves the
    drift), no wall quad left unclipped, and the parent's end cap / the
    child's mouth cap must clip without a topology error."""
    shape, width, spacing = profile
    theta = 0.37 + 0.41 * k
    d = np.array([np.cos(theta), np.sin(theta), 0.0])
    n = np.array([-np.sin(theta), np.cos(theta), 0.0])
    p = np.array([-29.183, -81.341, 156.498]) + k * np.array([0.731, -0.517, 0.0])
    drift_pts = np.array([p - (30.0 - s) * d for s in np.linspace(0.0, 30.0, 31)])
    cross_pts = np.array([p + s * n for s in np.linspace(0.0, 12.0, 13)])
    near = p[None, :]
    drift_env, drift_rings = _tube(drift_pts, shape, spacing, near, width)
    cross_env, cross_rings = _tube(cross_pts, shape, spacing, near, width)
    junction = Junction(
        type="DRIFT_CROSSCUT",
        node_id=f"DRIFT_STATION:T{k}",
        parent_id="DRIFT",
        child_id="CROSSCUT",
        point=p,
        child_end="start",
        level_id="L01",
    )
    child = cut_tube(cross_env, cross_rings, drift_env, junction, "CHILD", width)
    assert child.unclipped_wall_quads == 0
    assert len(child.floor_clips) >= 1
    judge = drift_env.with_end_planes(True, True)
    full = (0, int(drift_env.centers.shape[0]))
    on_plane = 0
    for clip in child.floor_clips:
        for poly in clip.polygons:
            sd = judge.signed_distance(np.asarray(poly).reshape(-1, 3), full)
            assert float(sd.min()) >= -1e-6, (k, clip.interval, sd.min())
        for chord in clip.chords:
            pts = np.asarray(chord).reshape(-1, 3)
            sd = judge.signed_distance(pts, full)
            assert float(np.abs(sd).max()) <= 1e-6, (k, clip.interval, sd)
            if float(np.abs((pts - p[None, :]) @ d).max()) <= 1e-6:
                on_plane += 1
    # the degenerate seam exists: at least one chord runs IN the end plane
    assert on_plane >= 1, k
    parent = cut_tube(drift_env, drift_rings, cross_env, junction, "PARENT", width)
    assert parent.removed_quads + parent.clipped_wall_quads > 0
    apex = drift_rings[-1].mean(axis=0)
    cap = cut_cap(cap_fan_corners(drift_rings[-1], apex, False), cross_env, junction, "end", width)
    assert int(cap.omitted_triangles) + len(cap.clips) > 0
    mouth = cut_mouth_cap(
        cap_fan_corners(cross_rings[0], cross_rings[0].mean(axis=0), True),
        drift_env,
        junction,
        "start",
        width,
    )
    assert mouth is not None
    for clip in mouth.clips.values():
        for poly in clip.polygons:
            sd = judge.signed_distance(np.asarray(poly).reshape(-1, 3), full)
            assert float(sd.min()) >= -1e-6, (k, sd.min())
