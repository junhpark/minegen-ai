"""Phase 08 level-development tests (rules 71–74): orebody-derived station
lattice, exact LEVEL_ENTRY anchoring, non-zero drift gradient, first-contact
crosscut terminals, prerequisite gating, determinism."""

from __future__ import annotations

import itertools
import json
import math

import numpy as np
import pytest

from minegen.core.models import ScenarioCreate
from minegen.design.constraints import DesignContext
from minegen.design.cost_field import DesignCostEvaluator
from minegen.levels.builder import LevelDevelopmentBuilder
from minegen.levels.models import DevelopmentKind
from minegen.services.scenario_service import ScenarioStore
from minegen.world.orebody import TabularOrebody
from minegen.world.synthetic_world import generate_world


def _setup(tmp_path, **scenario_overrides):  # type: ignore[no-untyped-def]
    store = ScenarioStore(root=tmp_path)
    sc = store.get(store.create(ScenarioCreate(**scenario_overrides)).id)
    world = generate_world(sc)
    drift_ev = DesignCostEvaluator(world, sc.design)
    crosscut_ev = DesignCostEvaluator(world, sc.design, DesignContext.crosscut(sc.design))
    builder = LevelDevelopmentBuilder(sc, world.orebody, drift_ev, crosscut_ev)
    return sc, world, builder


def _entry_segment(world, sc, u_entry: float, level_z: float) -> dict:  # type: ignore[no-untyped-def]
    """A synthetic smoothed segment ending exactly on the footwall-offset
    plane at (u_entry, level_z) — the shape Phase 05 guarantees."""
    ob = world.orebody
    assert isinstance(ob, TabularOrebody)
    # solve local v so the world z equals level_z at the offset plane
    q = ob.half_thickness + sc.ramp.footwall_access_offset
    v_local = (level_z - float(ob.center[2]) - q * float(ob.w[2])) / float(ob.v[2])
    entry = ob.footwall_point(u_entry, v_local, sc.ramp.footwall_access_offset)
    start = entry + np.array([0.0, -60.0, 6.0])
    pts = np.linspace(start, entry, 31)
    return {
        "levelId": "L01",
        "candidateId": "L01-C01",
        "effectiveSource": "SMOOTHED",
        "effectiveCenterline": {"points": pts.ravel().tolist()},
        "report": {"fieldCostSmoothed": 1.0, "fieldCostRaw": 2.0},
    }


def _smoothed(*segments: dict, status: str = "SUCCESS") -> dict:  # type: ignore[type-arg]
    return {"status": status, "failureReason": None, "segments": list(segments), "totals": {}}


def test_station_lattice_from_orebody_extent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Rule 72: pitch = stope_length + minimum_pillar, symmetric about u=0,
    planned stope proxy + end pillar inside the strike extent — NOT the
    Phase 03 candidate span (100 m) — so the default 600 m body gives 17."""
    sc, world, builder = _setup(tmp_path)
    ob = world.orebody
    assert isinstance(ob, TabularOrebody)
    stations = builder.station_us(ob)
    pitch = builder.station_pitch()
    assert pitch == pytest.approx(sc.mining.stope_length + sc.mining.minimum_pillar)
    assert len(stations) == 17
    assert stations == sorted(stations)
    assert stations[len(stations) // 2] == pytest.approx(0.0)
    margin = sc.mining.stope_length / 2.0 + sc.mining.minimum_pillar
    assert max(abs(u) for u in stations) + margin <= ob.half_length + 1e-9
    # candidate span (100 m default) would give only ±1 station — proof the
    # lattice is orebody-derived
    assert max(abs(u) for u in stations) > sc.design.candidate_along_strike_span


def test_entry_anchor_and_flat_drift(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sc, world, builder = _setup(tmp_path)
    seg = _entry_segment(world, sc, u_entry=12.5, level_z=40.0)
    entry = np.asarray(seg["effectiveCenterline"]["points"]).reshape(-1, 3)[-1]
    payload = builder.build(_smoothed(seg), "rev")
    assert payload.status == "SUCCESS", payload.failure_reason
    (level,) = payload.levels
    # rule 71: the access endpoint is never moved
    assert level.entry == pytest.approx(tuple(entry), abs=1e-12)
    assert level.entry_u == pytest.approx(12.5, abs=1e-9)
    drifts = [d for d in payload.developments if d.kind is DevelopmentKind.DRIFT]
    crosscuts = [d for d in payload.developments if d.kind is DevelopmentKind.CROSSCUT]
    assert len(crosscuts) == 17
    # entry (12.5) is not on the 35 m lattice → 18 breakpoints → 17 pieces
    assert len(drifts) == 17
    # default gradient 0: every drift point at the entry elevation, and every
    # drift piece endpoint welds to its neighbour exactly
    for d in drifts:
        pts = np.asarray(d.centerline.points).reshape(-1, 3)
        assert pts[:, 2] == pytest.approx(np.full(len(pts), entry[2]), abs=1e-9)
        assert d.report.valid, d.report.failure_reason
    for a, b in itertools.pairwise(drifts):
        pa = np.asarray(a.centerline.points).reshape(-1, 3)[-1]
        pb = np.asarray(b.centerline.points).reshape(-1, 3)[0]
        assert float(np.linalg.norm(pa - pb)) <= 1e-9
    # deterministic ordering: drift pieces ascending u, then crosscuts by u
    assert [d.from_u for d in drifts] == sorted(d.from_u for d in drifts)


def test_nonzero_gradient_regression(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Mandated regression: z(u) = z_entry − g·(u − u_entry) in the canonical
    +u direction; the entry itself never moves."""
    g = 0.01
    sc, world, builder = _setup(tmp_path, ramp={"levelDriftGradient": g})
    seg = _entry_segment(world, sc, u_entry=0.0, level_z=35.0)
    entry = np.asarray(seg["effectiveCenterline"]["points"]).reshape(-1, 3)[-1]
    payload = builder.build(_smoothed(seg), "rev")
    assert payload.status == "SUCCESS", payload.failure_reason
    ob = world.orebody
    assert isinstance(ob, TabularOrebody)
    u_hat = np.asarray(ob.u)
    for d in payload.developments:
        if d.kind is not DevelopmentKind.DRIFT:
            continue
        pts = np.asarray(d.centerline.points).reshape(-1, 3)
        u_vals = (pts - entry) @ u_hat  # (u − u_entry)
        assert pts[:, 2] == pytest.approx(entry[2] - g * u_vals, abs=1e-9)
        assert d.mean_gradient_signed == pytest.approx(-g, abs=1e-12)
        assert d.max_abs_gradient == pytest.approx(g, abs=1e-9)
    # exact anchor preserved: the drift passes through the entry point
    at_entry = min(
        float(
            np.min(np.linalg.norm(np.asarray(d.centerline.points).reshape(-1, 3) - entry, axis=1))
        )
        for d in payload.developments
        if d.kind is DevelopmentKind.DRIFT
    )
    assert at_entry <= 1e-9
    # crosscuts remain horizontal regardless of the drift gradient
    for d in payload.developments:
        if d.kind is DevelopmentKind.CROSSCUT:
            assert d.mean_gradient_signed == pytest.approx(0.0, abs=1e-12)


def test_crosscut_first_contact_terminals(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sc, world, builder = _setup(tmp_path)
    seg = _entry_segment(world, sc, u_entry=0.0, level_z=30.0)
    payload = builder.build(_smoothed(seg), "rev")
    assert payload.status == "SUCCESS", payload.failure_reason
    ob = world.orebody
    assert isinstance(ob, TabularOrebody)
    for d in payload.developments:
        if d.kind is not DevelopmentKind.CROSSCUT:
            continue
        pts = np.asarray(d.centerline.points).reshape(-1, 3)
        # horizontal toward the ore (never the full 3D −w vector)
        assert pts[0][2] == pytest.approx(pts[-1][2], abs=1e-9)
        assert d.report.terminal_sdf is not None and d.report.terminal_sdf <= 1e-6
        assert d.report.interior_breach_samples == 0
        assert d.report.start_weld_error <= 1e-6
        # terminal sits on the footwall FACE: local w == +half_thickness
        local = ob.to_local(pts[-1][None, :])[0]
        assert local[2] == pytest.approx(ob.half_thickness, abs=1e-6)
        assert d.report.valid, d.report.failure_reason


def test_failed_smoothed_never_yields_levels(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sc, world, builder = _setup(tmp_path)
    seg = _entry_segment(world, sc, u_entry=0.0, level_z=30.0)
    payload = builder.build(_smoothed(seg, status="FAILED"), "rev")
    assert payload.status == "FAILED"
    assert payload.developments == [] and payload.levels == []
    assert payload.metrics is None
    assert payload.failure_reason is not None and "prerequisite" in payload.failure_reason


def test_levels_payload_determinism(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sc, world, builder = _setup(tmp_path)
    seg = _entry_segment(world, sc, u_entry=7.0, level_z=45.0)
    a = builder.build(_smoothed(seg), "rev")
    b = builder.build(json.loads(json.dumps(_smoothed(seg))), "rev")
    assert json.dumps(a.model_dump(mode="json", by_alias=True)) == json.dumps(
        b.model_dump(mode="json", by_alias=True)
    )
    m = a.metrics
    assert m is not None
    assert m.station_pitch == pytest.approx(35.0)
    assert m.stations_per_level == 17
    assert m.crosscut_count == 17
    assert m.total_crosscut_length3d == pytest.approx(
        math.fsum(d.length3d for d in a.developments if d.kind is DevelopmentKind.CROSSCUT)
    )
