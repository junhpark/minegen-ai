"""Phase 09 stope tests (rules 75–80): explicit method gating, access-pair
integrity, pillar/overlap contract, anchor gates, determinism."""

from __future__ import annotations

import itertools
import json

import numpy as np
import pytest

from minegen.core.enums import MiningMethodType
from minegen.design.constraints import DesignContext
from minegen.design.cost_field import DesignCostEvaluator
from minegen.mining.methods.base import strategy_for, unsupported_method_payload
from minegen.mining.methods.longhole import LongholeOpenStopingStrategy
from minegen.world.orebody import TabularOrebody
from tests.test_levels import _entry_segment, _setup, _smoothed


def _levels_for(builder, world, sc, level_zs):  # type: ignore[no-untyped-def]
    segs = []
    for i, z in enumerate(level_zs, start=1):
        seg = _entry_segment(world, sc, u_entry=0.0, level_z=z)
        seg = json.loads(json.dumps(seg))
        seg["levelId"] = f"L{i:02d}"
        seg["candidateId"] = f"L{i:02d}-C01"
        segs.append(seg)
    payload = builder.build(_smoothed(*segs), "rev")
    assert payload.status == "SUCCESS", payload.failure_reason
    return payload.model_dump(mode="json", by_alias=True)


def _stopes(tmp_path, level_zs=(60.0, 35.0, 10.0), mutate=None):  # type: ignore[no-untyped-def]
    sc, world, builder = _setup(tmp_path)
    levels = _levels_for(builder, world, sc, level_zs)
    if mutate is not None:
        mutate(levels)
    hard_ev = DesignCostEvaluator(world, sc.design, DesignContext.crosscut(sc.design))
    strategy = LongholeOpenStopingStrategy()
    return sc, world, strategy.generate(sc, world, levels, hard_ev, "rev")


def test_unsupported_method_fails_explicitly() -> None:
    """Rule 78: reserved methods never silently fall back to longhole."""
    assert strategy_for(MiningMethodType.LONGHOLE_OPEN_STOPING) is not None
    for m in MiningMethodType:
        if m is MiningMethodType.LONGHOLE_OPEN_STOPING:
            continue
        assert strategy_for(m) is None
        payload = unsupported_method_payload(m, "rev")
        assert payload.status == "FAILED"
        assert payload.failure_reason is not None
        assert payload.failure_reason.startswith("UNSUPPORTED_METHOD")
        assert payload.method == m.value
        assert payload.stopes == [] and payload.metrics is None


def test_longhole_pairing_bounds_and_metrics(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sc, world, payload = _stopes(tmp_path)
    assert payload.status == "SUCCESS", payload.failure_reason
    m = payload.metrics
    assert m is not None
    ob = world.orebody
    assert isinstance(ob, TabularOrebody)
    # 3 levels → 2 intervals × 17 stations
    assert m.level_interval_count == 2 and m.stations_per_interval == 17
    assert m.stope_count == 34 and len(payload.stopes) == 34
    for s in payload.stopes:
        b = s.local_bounds
        # rule 75: anchored prism in the analytic local frame
        assert b.u_max - b.u_min == pytest.approx(sc.mining.stope_length)
        assert (b.u_min + b.u_max) / 2.0 == pytest.approx(s.station_u, abs=1e-9)
        assert (b.w_min, b.w_max) == (
            pytest.approx(-ob.half_thickness),
            pytest.approx(ob.half_thickness),
        )
        assert s.down_dip_span > 0 and s.vertical_height > 0
        assert s.vertical_height == pytest.approx(s.down_dip_span * abs(ob.v[2]), abs=1e-9)
        assert s.geometric_volume_m3 == pytest.approx(
            s.strike_length * s.down_dip_span * s.thickness
        )
        assert s.tonnes == pytest.approx(s.geometric_volume_m3 * sc.orebody.density)
        assert s.report.upper_anchor_error <= 1e-6
        assert s.report.lower_anchor_error <= 1e-6
        assert s.report.hard_invalid_samples == 0
        assert s.planned_state == "PLANNED"
        assert s.upper_access_node_id == f"STOPE_ACCESS:{s.upper_level_id}:S{s.station_index:+03d}"
        assert s.report.valid
    # signed mesh volume of the emitted prism equals the analytic volume
    s0 = payload.stopes[0]
    verts = np.asarray(s0.geometry.vertices).reshape(-1, 3)
    tris = np.asarray(s0.geometry.triangle_indices).reshape(-1, 3)
    v = float(sum(np.dot(verts[a], np.cross(verts[b], verts[c])) / 6.0 for a, b, c in tris))
    assert v == pytest.approx(s0.geometric_volume_m3, rel=1e-9)
    # strike pillar exactly minimum_pillar between neighbours (rule 77)
    interval = [s for s in payload.stopes if s.upper_level_id == "L01"]
    interval.sort(key=lambda s: s.local_bounds.u_min)
    gaps = [b.local_bounds.u_min - a.local_bounds.u_max for a, b in itertools.pairwise(interval)]
    assert all(g == pytest.approx(sc.mining.minimum_pillar, abs=1e-9) for g in gaps)
    # extraction fraction is bounded and consistent
    orebody_v = 8.0 * ob.half_length * ob.half_height * ob.half_thickness
    assert m.geometric_extraction_fraction_of_orebody == pytest.approx(
        m.total_geometric_volume_m3 / orebody_v
    )
    assert 0.0 < m.geometric_extraction_fraction_of_orebody < 1.0


def test_missing_paired_station_fails(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Rule 76: a station missing on ONE level is caught by the artifact
    completeness gate (declared crosscutCount / stationsPerLevel) before
    pairing even starts."""

    def drop_one(levels):  # type: ignore[no-untyped-def]
        idx = next(
            i
            for i, d in enumerate(levels["developments"])
            if d["kind"] == "CROSSCUT" and d["levelId"] == "L02" and d["stationIndex"] == 3
        )
        del levels["developments"][idx]

    _, _, payload = _stopes(tmp_path, mutate=drop_one)
    assert payload.status == "FAILED"
    assert payload.failure_reason is not None
    # the aggregate-count or per-level completeness gate fires (both rule 76)
    assert "rule 76" in payload.failure_reason
    assert payload.stopes == []


def test_station_set_mismatch_fails_pairing(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Rule 76: a count-preserving corruption (station 3 renamed to 99 on
    L02) slips past the completeness gate and must be caught by the
    adjacent-level station-set equality gate."""

    def rename(levels):  # type: ignore[no-untyped-def]
        d = next(
            d
            for d in levels["developments"]
            if d["kind"] == "CROSSCUT" and d["levelId"] == "L02" and d["stationIndex"] == 3
        )
        d["stationIndex"] = 99
        d["id"] = "CROSSCUT:L02:S+99"

    _, _, payload = _stopes(tmp_path, mutate=rename)
    assert payload.status == "FAILED"
    assert payload.failure_reason is not None
    assert "unpaired stations [3, 99]" in payload.failure_reason
    assert payload.stopes == []


def test_station_removed_from_every_level_fails(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Blocker-2 regression: the SAME station removed from EVERY level keeps
    all pairwise sets equal, so only the artifact-declared lattice can catch
    it — never a silent 16-station SUCCESS."""

    def drop_everywhere(levels):  # type: ignore[no-untyped-def]
        levels["developments"] = [
            d
            for d in levels["developments"]
            if not (d["kind"] == "CROSSCUT" and d["stationIndex"] == 3)
        ]

    _, _, payload = _stopes(tmp_path, mutate=drop_everywhere)
    assert payload.status == "FAILED"
    assert payload.failure_reason is not None
    assert "rule 76" in payload.failure_reason
    assert payload.stopes == []


def test_all_crosscuts_removed_fails(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Blocker-2 regression: zero CROSSCUT developments in a nominally
    SUCCESS levels artifact must FAIL — never SUCCESS with zero stopes."""

    def strip(levels):  # type: ignore[no-untyped-def]
        levels["developments"] = [d for d in levels["developments"] if d["kind"] != "CROSSCUT"]

    _, _, payload = _stopes(tmp_path, mutate=strip)
    assert payload.status == "FAILED"
    assert payload.stopes == [] and payload.metrics is None
    assert payload.failure_reason is not None
    assert "rule 76" in payload.failure_reason


def test_thirteen_level_default_lattice_yields_204(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Default-acceptance pin without the Hybrid-A* pipeline: 13 synthetic
    Phase 08 levels × 17 stations ⇒ 12 × 17 = 204 planned stopes."""
    zs = tuple(60.0 - i * (200.0 / 12.0) for i in range(13))
    _, _, payload = _stopes(tmp_path, level_zs=zs)
    assert payload.status == "SUCCESS", payload.failure_reason
    m = payload.metrics
    assert m is not None
    assert m.level_interval_count == 12
    assert m.stations_per_interval == 17
    assert m.stope_count == 204 and len(payload.stopes) == 204
    assert all(s.report.valid for s in payload.stopes)


def _proxy_world(grade_values, terrain_z: float):  # type: ignore[no-untyped-def]
    """Minimal world for the proxy: a grade field, a flat terrain and no
    lattice classification of any kind."""
    from types import SimpleNamespace

    from minegen.world.field_grid import FieldGrid
    from minegen.world.spatial_fields import RegularScalarField
    from minegen.world.terrain import Terrain

    grid = FieldGrid(origin=(-60.0, -60.0, -60.0), spacing=(4.0, 4.0, 4.0), shape=(30, 30, 30))
    values = grade_values(grid).astype(np.float32)
    terrain = Terrain(x0=-100.0, y0=-100.0, spacing=200.0, z=np.full((2, 2), terrain_z))
    return SimpleNamespace(
        fields=SimpleNamespace(grade=RegularScalarField("grade", grid, values), grid=grid),
        terrain=terrain,
    )


def _proxy_orebody_and_bounds():  # type: ignore[no-untyped-def]
    from minegen.core.models import OrebodyConfig
    from minegen.mining.models import StopeLocalBounds

    ob = TabularOrebody(
        OrebodyConfig(
            orebody_type="TABULAR",
            center={"x": 0.0, "y": 0.0, "z": 0.0},
            strike_deg=35.0,
            dip_deg=70.0,
            length=600.0,
            height=350.0,
            thickness=12.0,
        )
    )
    bounds = StopeLocalBounds(
        u_min=-15.0, u_max=15.0, v_min=-10.0, v_max=10.0, w_min=-6.0, w_max=6.0
    )
    return ob, bounds


def test_grade_proxy_is_geometry_bounded_field_sampling(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Rule 130: the proxy samples the grade FIELD only inside the stope
    prism ∩ orebody solid ∩ below terrain. Field values just outside the
    local bounds (a strike neighbour) — however extreme — never leak in,
    and there is no ore_fraction / cell weighting anywhere."""
    from minegen.mining.methods.longhole import _grade_proxy

    ob, bounds = _proxy_orebody_and_bounds()

    def grade(grid):  # type: ignore[no-untyped-def]
        centers = grid.centers().reshape(-1, 3)
        local = ob.to_local(centers)
        g = np.full(centers.shape[0], 3.0)
        neighbour = (local[:, 0] > 15.0) & (local[:, 0] < 40.0)
        g[neighbour] = 100.0  # absurd grade just past uMax
        return g.reshape(grid.shape)

    world = _proxy_world(grade, terrain_z=1000.0)  # everything below ground
    proxy = _grade_proxy(world, ob, bounds)  # type: ignore[arg-type]
    assert proxy is not None
    # trilinear blending toward the neighbour only touches the last ≤ 2.5 m
    # of quadrature cells; the bulk of the prism must read the 3.0 plateau
    assert 3.0 <= proxy < 3.0 + 0.5 * (100.0 - 3.0) * (2.5 / 30.0)


def test_grade_proxy_excludes_the_part_of_the_prism_above_terrain(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from minegen.mining.methods.longhole import _grade_proxy

    ob, bounds = _proxy_orebody_and_bounds()

    def grade(grid):  # type: ignore[no-untyped-def]
        centers = grid.centers().reshape(-1, 3)
        return np.where(centers[:, 2] < 0.0, 3.0, 100.0).reshape(grid.shape)

    buried = _grade_proxy(_proxy_world(grade, terrain_z=1000.0), ob, bounds)  # type: ignore[arg-type]
    outcrop = _grade_proxy(_proxy_world(grade, terrain_z=0.0), ob, bounds)  # type: ignore[arg-type]
    assert buried is not None and outcrop is not None
    # buried: both halves count → close to the (3 + 100) / 2 midpoint;
    # outcrop: only the below-ground half counts → the 3.0 plateau plus the
    # trilinear blend across the z = 0 step (one 4 m lattice cell of the
    # ~9 m below-ground span), far from any 100-grade contribution
    assert buried > 30.0
    assert 3.0 <= outcrop < 15.0
    assert outcrop < 0.25 * buried
    # a prism entirely above ground has no planning proxy at all
    assert _grade_proxy(_proxy_world(grade, terrain_z=-1000.0), ob, bounds) is None  # type: ignore[arg-type]


def test_grade_proxy_is_deterministic_and_equal_weight(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Equal-volume midpoint quadrature: a linear field in local u averages
    to its value at the prism centre, independent of the sampling budget."""
    from minegen.mining.methods.longhole import _grade_proxy

    ob, bounds = _proxy_orebody_and_bounds()

    def grade(grid):  # type: ignore[no-untyped-def]
        local = ob.to_local(grid.centers().reshape(-1, 3))
        return (5.0 + 0.1 * local[:, 0]).reshape(grid.shape)

    world = _proxy_world(grade, terrain_z=1000.0)
    a = _grade_proxy(world, ob, bounds)  # type: ignore[arg-type]
    b = _grade_proxy(world, ob, bounds)  # type: ignore[arg-type]
    fine = _grade_proxy(world, ob, bounds, spacing=1.0)  # type: ignore[arg-type]
    assert a == b
    assert a == pytest.approx(5.0, abs=0.05)
    assert fine == pytest.approx(5.0, abs=0.05)


def test_duplicate_station_fails(tmp_path) -> None:  # type: ignore[no-untyped-def]
    def duplicate(levels):  # type: ignore[no-untyped-def]
        d = next(
            d
            for d in levels["developments"]
            if d["kind"] == "CROSSCUT" and d["levelId"] == "L01" and d["stationIndex"] == 0
        )
        levels["developments"].append(json.loads(json.dumps(d)))

    _, _, payload = _stopes(tmp_path, mutate=duplicate)
    assert payload.status == "FAILED"
    assert payload.failure_reason is not None and "duplicate crosscut station" in (
        payload.failure_reason
    )


def test_perturbed_terminal_fails_anchor_gate(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Rule 75: an access terminal off the footwall face / station plane by
    more than 1e-6 m invalidates the stope and fails the artifact."""

    def perturb(levels):  # type: ignore[no-untyped-def]
        d = next(
            d
            for d in levels["developments"]
            if d["kind"] == "CROSSCUT" and d["levelId"] == "L02" and d["stationIndex"] == -2
        )
        d["centerline"]["points"][-3] += 0.01  # 1 cm off in world x

    _, _, payload = _stopes(tmp_path, mutate=perturb)
    assert payload.status == "FAILED"
    bad = next(s for s in payload.stopes if not s.report.valid)
    assert bad.station_index == -2
    assert max(bad.report.upper_anchor_error, bad.report.lower_anchor_error) > 1e-6
    assert payload.failure_reason is not None and "footwall face" in payload.failure_reason


def test_pillar_violation_fails(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Rule 77: corrupting a stationU so two stopes close the strike pillar
    below minimum_pillar fails the artifact with the pillar reason."""

    def shift(levels):  # type: ignore[no-untyped-def]
        for d in levels["developments"]:
            if d["kind"] == "CROSSCUT" and d["stationIndex"] == 1:
                d["stationU"] = 32.0  # 35 → 32: gap 5 → 2 m
                # keep the terminal on the station plane: shift the whole
                # centerline by −3 m along strike (u is horizontal)
                pts = np.asarray(d["centerline"]["points"]).reshape(-1, 3)
                u_hat = np.array([0.5735764363510261, 0.8191520442889918, 0.0])
                d["centerline"]["points"] = (pts - 3.0 * u_hat).ravel().tolist()

    _, _, payload = _stopes(tmp_path, mutate=shift)
    assert payload.status == "FAILED"
    assert payload.failure_reason is not None and "strike pillar" in payload.failure_reason
    clr = [
        s.report.strike_pillar_clearance
        for s in payload.stopes
        if s.station_index in (0, 1) and s.report.strike_pillar_clearance is not None
    ]
    assert min(clr) == pytest.approx(2.0, abs=1e-6)


def test_stopes_determinism_and_prerequisite(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sc, world, builder = _setup(tmp_path)
    levels = _levels_for(builder, world, sc, (60.0, 35.0))
    hard_ev = DesignCostEvaluator(world, sc.design, DesignContext.crosscut(sc.design))
    strategy = LongholeOpenStopingStrategy()
    a = strategy.generate(sc, world, levels, hard_ev, "rev")
    b = strategy.generate(sc, world, json.loads(json.dumps(levels)), hard_ev, "rev")
    assert json.dumps(a.model_dump(mode="json", by_alias=True)) == json.dumps(
        b.model_dump(mode="json", by_alias=True)
    )
    failed = json.loads(json.dumps(levels))
    failed["status"] = "FAILED"
    p = strategy.generate(sc, world, failed, hard_ev, "rev")
    assert p.status == "FAILED" and p.stopes == []
    assert p.failure_reason is not None and "prerequisite" in p.failure_reason


def test_stopes_api_lifecycle_and_invalidation(client, design_service) -> None:  # type: ignore[no-untyped-def]
    """Rule 79 chain: stopes require levels; levels regeneration deletes
    stopes + network; stope regeneration touches nothing else; upstream
    regeneration clears everything downstream."""
    from tests.test_network_api import _levels, _network
    from tests.test_smoothing_api import _decline, _prepare
    from tests.test_tunnel_api import _smooth, _tunnel

    sid = _prepare(client)
    _decline(client, sid)
    # the DIRECT prerequisite of stopes is the levels artifact (rule 79):
    # without it the guard answers LEVELS_NOT_GENERATED regardless of how far
    # upstream the chain is actually broken
    r = client.post(f"/api/v1/scenarios/{sid}/design/stopes")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "LEVELS_NOT_GENERATED"
    _smooth(client, sid)
    r = client.post(f"/api/v1/scenarios/{sid}/design/stopes")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "LEVELS_NOT_GENERATED"
    r = client.get(f"/api/v1/scenarios/{sid}/design/stopes")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "STOPES_NOT_GENERATED"

    _levels(client, sid)
    _tunnel(client, sid)
    _network(client, sid)
    r = client.post(f"/api/v1/scenarios/{sid}/design/stopes")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "SUCCESS", body["failureReason"]
    assert body["metrics"]["stopeCount"] == (
        body["metrics"]["levelIntervalCount"] * body["metrics"]["stationsPerInterval"]
    )
    assert all(s["plannedState"] == "PLANNED" for s in body["stopes"])
    got = client.get(f"/api/v1/scenarios/{sid}/design/stopes")
    assert got.status_code == 200 and got.json() == body

    tunnel_path = design_service.tunnel_report_path(sid)
    network_path = design_service.network_path(sid)
    stopes_path = design_service.stopes_path(sid)
    tunnel_bytes = tunnel_path.read_bytes()
    network_bytes = network_path.read_bytes()

    # stope regeneration leaves everything else untouched (rule 79)
    r = client.post(f"/api/v1/scenarios/{sid}/design/stopes")
    assert r.status_code == 200
    assert tunnel_path.read_bytes() == tunnel_bytes
    assert network_path.read_bytes() == network_bytes

    # levels regeneration deletes stopes + network, never the tunnel
    _levels(client, sid)
    assert not stopes_path.exists() and not network_path.exists()
    assert tunnel_path.read_bytes() == tunnel_bytes

    # upstream (smoothed) regeneration clears the whole branch
    r = client.post(f"/api/v1/scenarios/{sid}/design/stopes")
    assert r.status_code == 200
    _smooth(client, sid)
    assert not stopes_path.exists()
    r = client.get(f"/api/v1/scenarios/{sid}/design/stopes")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "STOPES_NOT_GENERATED"


def test_whole_level_removed_fails(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Residual-blocker regression: deleting a COMPLETE middle LevelSummary
    plus every development of that level (Phase 08 metrics untouched) leaves
    all per-level and pairwise gates satisfied among the survivors — only the
    levelCount gate can stop L01→L03 from being paired across the gap."""

    def drop_level(levels):  # type: ignore[no-untyped-def]
        levels["levels"] = [lv for lv in levels["levels"] if lv["levelId"] != "L02"]
        levels["developments"] = [d for d in levels["developments"] if d["levelId"] != "L02"]

    _, _, payload = _stopes(tmp_path, mutate=drop_level)
    assert payload.status == "FAILED"
    assert payload.stopes == []
    assert payload.failure_reason is not None
    assert "whole level is missing" in payload.failure_reason
    # in particular no fabricated L01-L03 interval exists anywhere
    assert not any("L01-L03" in s.id for s in payload.stopes)


def test_foreign_level_crosscut_fails_aggregate_gate(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Residual-blocker regression: an extra CROSSCUT whose levelId is not
    represented in levels[] escapes every per-summary check and must be
    caught by the aggregate crosscutCount consistency gate."""

    def add_foreign(levels):  # type: ignore[no-untyped-def]
        d = json.loads(
            json.dumps(
                next(
                    d
                    for d in levels["developments"]
                    if d["kind"] == "CROSSCUT" and d["levelId"] == "L01"
                )
            )
        )
        d["levelId"] = "L99"
        d["id"] = "CROSSCUT:L99:S+00"
        levels["developments"].append(d)

    _, _, payload = _stopes(tmp_path, mutate=add_foreign)
    assert payload.status == "FAILED"
    assert payload.failure_reason is not None
    assert "aggregate artifact inconsistency" in payload.failure_reason
    assert payload.stopes == []
