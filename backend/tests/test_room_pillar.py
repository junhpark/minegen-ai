"""Phase 21C Room & Pillar acceptance (directive §41: RP-1 … RP-10, RP-13, RP-14).

RP-11 / RP-12 (schedule) live in ``tests/test_production_timeline.py``.
"""

from __future__ import annotations

import json
import math
from itertools import pairwise
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from minegen.core.enums import MiningMethodType, OrebodyType
from minegen.core.models import MiningConfig, RoomPillarParameters, Scenario
from minegen.geometry.mesh_qa import mesh_qa
from minegen.mining.methods.contracts import FixedAccessPattern
from minegen.mining.methods.registry import plan_for
from minegen.mining.methods.room_pillar import (
    RoomPillarPlan,
    band_intervals,
    generate_room_pillar,
    thickness_stages,
)
from minegen.mining.models import parse_production_payload
from minegen.world.orebody import TabularOrebody
from minegen.world.synthetic_world import SyntheticWorld, generate_world
from tests.conftest import small_scenario
from tests.phase21a_parity_support import canonical, layout_chain, with_method


def _rp_scenario(**params: Any) -> Scenario:
    sc = with_method(small_scenario(), MiningMethodType.ROOM_AND_PILLAR)
    if not params:
        return sc
    mining = sc.mining.model_dump(by_alias=True, exclude={"method_parameters"})
    mining["methodParameters"] = params
    return sc.model_copy(update={"mining": MiningConfig.model_validate(mining)})


@pytest.fixture(scope="module")
def rp_world() -> tuple[Scenario, SyntheticWorld]:
    sc = _rp_scenario()
    return sc, generate_world(sc)


@pytest.fixture(scope="module")
def rp_chain(rp_world: tuple[Scenario, SyntheticWorld]) -> dict[str, Any]:
    sc, world = rp_world
    return layout_chain(sc, world)


def _plan_overlap(a: dict[str, float], b: dict[str, float]) -> float:
    du = min(a["uMax"], b["uMax"]) - max(a["uMin"], b["uMin"])
    dv = min(a["vMax"], b["vMax"]) - max(a["vMin"], b["vMin"])
    return max(0.0, du) * max(0.0, dv)


def test_rp1_registry_resolves_the_implemented_room_pillar_plan() -> None:
    plan = plan_for(MiningMethodType.ROOM_AND_PILLAR)
    assert isinstance(plan, RoomPillarPlan) and plan.implementation_status == "IMPLEMENTED"
    sc = _rp_scenario()
    assert isinstance(sc.mining.method_parameters, RoomPillarParameters)
    assert isinstance(plan.production_access_pattern(sc), FixedAccessPattern)


def test_rp2_central_access_reaches_the_ore_on_every_level(
    rp_world: tuple[Scenario, SyntheticWorld], rp_chain: dict[str, Any]
) -> None:
    _, world = rp_world
    ob = world.orebody
    assert isinstance(ob, TabularOrebody)
    levels = rp_chain["levels"]
    assert levels["status"] == "SUCCESS", levels["failureReason"]
    crosscuts = [d for d in levels["developments"] if d["kind"] == "CROSSCUT"]
    assert len(crosscuts) == len(levels["levels"])
    for d in crosscuts:
        assert d["stationIndex"] == 0 and d["report"]["valid"]
        pts = np.asarray(d["centerline"]["points"]).reshape(-1, 3)
        local = ob.to_local(pts[-1][None, :])[0]
        assert abs(abs(float(local[2])) - ob.half_thickness) < 1e-6  # on the ore face
        assert abs(float(local[0])) < 1e-6  # at u = 0
    assert levels["metrics"]["stationPitch"] == 0.0 and levels["metrics"]["stationsPerLevel"] == 1


def test_rp3_grid_phase_puts_the_centre_in_a_room(rp_chain: dict[str, Any]) -> None:
    bands = band_intervals(-100.0, 100.0, 8.0, 6.0)
    centre = [b for b in bands if b[0] <= 0.0 <= b[1]]
    assert centre and all(kind == "ROOM" for _, _, kind in centre)
    assert [k for _, _, k in bands][::2] != [k for _, _, k in bands][1::2]  # alternating
    kinds = [k for _, _, k in bands]
    assert all(a != b for a, b in pairwise(kinds))
    prod = rp_chain["stopes"]
    assert prod["status"] == "SUCCESS", prod["failureReason"]
    rooms_at_origin = [
        r
        for r in prod["rooms"]
        if r["localPlanBounds"]["uMin"] <= 0.0 <= r["localPlanBounds"]["uMax"]
        and r["localPlanBounds"]["vMin"] <= 0.0 <= r["localPlanBounds"]["vMax"]
    ]
    assert rooms_at_origin
    assert not any(
        p["localBounds"]["uMin"] <= 0.0 <= p["localBounds"]["uMax"]
        and p["localBounds"]["vMin"] <= 0.0 <= p["localBounds"]["vMax"]
        for p in prod["pillars"]
    )


def test_rp4_rooms_and_pillars_never_overlap(rp_chain: dict[str, Any]) -> None:
    prod = rp_chain["stopes"]
    cells = [(r["id"], r["localPlanBounds"]) for r in prod["rooms"]] + [
        (
            p["id"],
            {k: p["localBounds"][k] for k in ("uMin", "uMax", "vMin", "vMax")},
        )
        for p in prod["pillars"]
    ]
    for i, (ida, a) in enumerate(cells):
        for idb, b in cells[i + 1 :]:
            assert _plan_overlap(a, b) < 1e-9, (ida, idb)
    # extraction stages of one room never overlap along w and never leave the room
    by_room: dict[str, list[dict[str, Any]]] = {}
    for u in prod["extractionUnits"]:
        by_room.setdefault(u["roomId"], []).append(u)
    for room in prod["rooms"]:
        units = sorted(by_room[room["id"]], key=lambda u: u["localBounds"]["wMin"])
        for a, b in pairwise(units):
            assert a["localBounds"]["wMax"] <= b["localBounds"]["wMin"] + 1e-9
        assert set(room["extractionUnitIds"]) == {u["id"] for u in units}


def test_rp5_mined_plus_pillar_volume_is_the_panel_volume(
    rp_world: tuple[Scenario, SyntheticWorld], rp_chain: dict[str, Any]
) -> None:
    sc, world = rp_world
    ob = world.orebody
    assert isinstance(ob, TabularOrebody)
    params = sc.mining.method_parameters
    assert isinstance(params, RoomPillarParameters)
    prod = rp_chain["stopes"]
    m = prod["metrics"]
    hu = ob.half_length - params.boundary_pillar_m
    hv = ob.half_height - params.boundary_pillar_m
    panel = 4.0 * hu * hv * 2.0 * ob.half_thickness
    mined = math.fsum(u["geometricVolumeM3"] for u in prod["extractionUnits"])
    pillar = math.fsum(p["geometricVolumeM3"] for p in prod["pillars"])
    assert abs(m["panelVolumeM3"] - panel) <= 1e-9 * panel
    assert abs(mined + pillar - panel) <= 1e-9 * panel
    assert abs(m["totalMinedVolumeM3"] - mined) <= 1e-9 * panel
    assert abs(m["totalPillarVolumeM3"] - pillar) <= 1e-9 * panel
    assert m["geometricExtractionFraction"] == pytest.approx(mined / panel)
    assert 0.5 < m["geometricExtractionFraction"] < 1.0


def test_rp6_boundary_pillar_shell_is_never_mined(
    rp_world: tuple[Scenario, SyntheticWorld], rp_chain: dict[str, Any]
) -> None:
    sc, world = rp_world
    ob = world.orebody
    assert isinstance(ob, TabularOrebody)
    params = sc.mining.method_parameters
    assert isinstance(params, RoomPillarParameters)
    b = params.boundary_pillar_m
    prod = rp_chain["stopes"]
    for u in prod["extractionUnits"]:
        lb = u["localBounds"]
        assert lb["uMin"] >= -ob.half_length + b - 1e-9 and lb["uMax"] <= ob.half_length - b + 1e-9
        assert lb["vMin"] >= -ob.half_height + b - 1e-9 and lb["vMax"] <= ob.half_height - b + 1e-9
    us = [u["localBounds"]["uMin"] for u in prod["extractionUnits"]]
    assert abs(min(us) - (-ob.half_length + b)) < 1e-9  # the panel edge IS the inset


def test_rp7_single_bench_hierarchy(
    rp_world: tuple[Scenario, SyntheticWorld], rp_chain: dict[str, Any]
) -> None:
    _, world = rp_world
    ob = world.orebody
    assert isinstance(ob, TabularOrebody)
    prod = rp_chain["stopes"]
    for room in prod["rooms"]:
        stages = [u for u in prod["extractionUnits"] if u["roomId"] == room["id"]]
        stages.sort(key=lambda u: u["benchIndex"])
        assert [u["stage"] for u in stages] == ["HEADING", "BENCH_1"]
        heading, bench = stages
        assert heading["localBounds"]["wMax"] == pytest.approx(ob.half_thickness)
        assert heading["localBounds"]["wMax"] - heading["localBounds"]["wMin"] == pytest.approx(5.0)
        assert bench["localBounds"]["wMin"] == pytest.approx(-ob.half_thickness)
        assert bench["localBounds"]["wMax"] == pytest.approx(heading["localBounds"]["wMin"])
        assert room["accessDevelopmentId"].startswith("CROSSCUT:") and room[
            "accessDevelopmentId"
        ].endswith(":S+00")
    assert prod["metrics"]["headingCount"] == prod["metrics"]["roomCount"]
    assert prod["metrics"]["benchCount"] == prod["metrics"]["roomCount"]


def test_rp8_double_bench_hierarchy(rp_world: tuple[Scenario, SyntheticWorld]) -> None:
    _, world = rp_world
    ob = world.orebody
    assert isinstance(ob, TabularOrebody)
    double = _rp_scenario(benchCount=2)
    prod = layout_chain(double, world)["stopes"]
    assert prod["status"] == "SUCCESS", prod["failureReason"]
    for room in prod["rooms"]:
        stages = sorted(
            (u for u in prod["extractionUnits"] if u["roomId"] == room["id"]),
            key=lambda u: u["benchIndex"],
        )
        assert [u["stage"] for u in stages] == ["HEADING", "BENCH_1", "BENCH_2"]
        h, b1, b2 = (u["localBounds"] for u in stages)
        assert h["wMax"] - h["wMin"] == pytest.approx(5.0)
        assert b1["wMax"] - b1["wMin"] == pytest.approx((2 * ob.half_thickness - 5.0) / 2)
        assert b2["wMax"] - b2["wMin"] == pytest.approx((2 * ob.half_thickness - 5.0) / 2)
        assert b1["wMax"] == pytest.approx(h["wMin"]) and b2["wMax"] == pytest.approx(b1["wMin"])
        assert b2["wMin"] == pytest.approx(-ob.half_thickness)
    assert prod["metrics"]["benchCount"] == 2 * prod["metrics"]["roomCount"]
    # heading not thinner than the thickness → ONE heading stage, no invalid geometry
    assert thickness_stages(-6.0, 6.0, 12.0, 2) == [("HEADING", -6.0, 6.0)]
    assert thickness_stages(-6.0, 6.0, 20.0, 1) == [("HEADING", -6.0, 6.0)]
    assert thickness_stages(-6.0, 6.0, 5.0, 1) == [("HEADING", 1.0, 6.0), ("BENCH_1", -6.0, 1.0)]


def test_rp9_stage_volumes_sum_to_the_room_cell_volume(
    rp_world: tuple[Scenario, SyntheticWorld], rp_chain: dict[str, Any]
) -> None:
    _, world = rp_world
    ob = world.orebody
    assert isinstance(ob, TabularOrebody)
    prod = rp_chain["stopes"]
    for room in prod["rooms"]:
        pb = room["localPlanBounds"]
        cell = (pb["uMax"] - pb["uMin"]) * (pb["vMax"] - pb["vMin"]) * 2.0 * ob.half_thickness
        total = math.fsum(
            u["geometricVolumeM3"] for u in prod["extractionUnits"] if u["roomId"] == room["id"]
        )
        assert abs(total - cell) <= 1e-9 * cell
    for u in prod["extractionUnits"] + prod["pillars"]:
        r = u["report"]
        assert r["valid"] and r["meshClosedSolid"] and r["volumeAgreement"] and r["finite"]


def test_rp10_pillars_are_retained_material_not_production_units(
    rp_chain: dict[str, Any],
) -> None:
    prod = rp_chain["stopes"]
    unit_ids = {u["id"] for u in prod["extractionUnits"]}
    for p in prod["pillars"]:
        assert p["id"].startswith("PILLAR:") and p["id"] not in unit_ids
        assert p["tonnesEquivalent"] == pytest.approx(p["geometricVolumeM3"] * 2.8)
        assert "plannedState" not in p  # never a production state machine
    assert prod["metrics"]["pillarCount"] == len(prod["pillars"]) > 0
    assert all(p["report"]["hardInvalidSamples"] == 0 for p in prod["pillars"])


def test_rp12_generation_is_deterministic(rp_world: tuple[Scenario, SyntheticWorld]) -> None:
    sc, world = rp_world
    assert canonical(layout_chain(sc, world)["stopes"]) == canonical(
        layout_chain(sc, world)["stopes"]
    )


def test_rp13_corrupted_geometry_is_refused(rp_chain: dict[str, Any]) -> None:
    prod = rp_chain["stopes"]
    doc = json.loads(json.dumps(prod))
    doc["pillars"][0]["geometry"]["vertices"][3] = float("inf")
    with pytest.raises(ValidationError):
        parse_production_payload(doc)
    unit = prod["extractionUnits"][0]
    positions = np.asarray(unit["geometry"]["vertices"]).reshape(-1, 3)
    tris = np.asarray(unit["geometry"]["triangleIndices"]).reshape(-1, 3)
    assert mesh_qa(positions, tris).closed_solid
    bad = tris.copy()
    bad[5, 1] = bad[5, 2]  # degenerate triangle → boundary edges
    assert not mesh_qa(positions, bad).closed_solid


def test_rp14_non_tabular_orebody_is_a_typed_geometry_boundary() -> None:
    sc = _rp_scenario()
    ell = sc.model_copy(
        update={"orebody": sc.orebody.model_copy(update={"orebody_type": OrebodyType.ELLIPSOID})}
    )
    world = generate_world(ell)
    payload = generate_room_pillar(
        ell,
        world,
        {"status": "SUCCESS", "levels": [], "developments": []},
        None,
        "rev",  # type: ignore[arg-type]
    )
    assert payload.status == "FAILED" and payload.method == "ROOM_AND_PILLAR"
    assert payload.failure_reason is not None
    assert payload.failure_reason.startswith("METHOD_GEOMETRY_NOT_IMPLEMENTED")
    assert payload.rooms == payload.extraction_units == payload.pillars == []


def test_rp_complexity_budget_is_typed(
    rp_world: tuple[Scenario, SyntheticWorld], rp_chain: dict[str, Any]
) -> None:
    _, world = rp_world
    tiny = _rp_scenario(roomWidthM=0.5, pillarWidthM=0.5)
    payload = generate_room_pillar(tiny, world, rp_chain["levels"], None, "rev")  # type: ignore[arg-type]
    assert payload.status == "FAILED" and payload.failure_reason is not None
    assert payload.failure_reason.startswith("PRODUCTION_COMPLEXITY_LIMIT")


def test_rp_boundary_pillar_larger_than_the_body_is_typed(
    rp_world: tuple[Scenario, SyntheticWorld], rp_chain: dict[str, Any]
) -> None:
    _, world = rp_world
    huge = _rp_scenario(boundaryPillarM=500.0)
    payload = generate_room_pillar(huge, world, rp_chain["levels"], None, "rev")  # type: ignore[arg-type]
    assert payload.status == "FAILED" and "boundaryPillarM" in (payload.failure_reason or "")
