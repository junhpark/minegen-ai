"""Phase 21A — the mining-method registry is the ONE method authority
(directive §8 / §9 / §38, rule 192).

* every ``MiningMethodType`` resolves EXPLICITLY (no ``None``);
* LONGHOLE_OPEN_STOPING is the implemented plan; every reserved method is
  an unsupported plan whose development intent and production are the
  typed UNSUPPORTED_METHOD outcomes with the pre-21A wording;
* no method — registered or not — can fall back to the longhole plan;
* the only remaining method dispatch sites are the registry consumers.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from minegen.core.enums import MiningMethodType
from minegen.core.models import MiningConfig, Scenario, ScenarioCreate
from minegen.mining.methods.contracts import (
    FixedAccessPattern,
    ProductionLattice,
    StationLatticeAccessPattern,
    station_margin,
    station_pitch,
)
from minegen.mining.methods.longhole import LongholeOpenStopingPlan
from minegen.mining.methods.registry import (
    DISPLAY_NAMES,
    UnknownMiningMethodError,
    all_plans,
    plan_for,
)
from minegen.mining.methods.unsupported import UnsupportedMethodPlan

SRC = Path(__file__).resolve().parents[1] / "src" / "minegen"
#: Phase 21B/C: CUT_AND_FILL and ROOM_AND_PILLAR are implemented; the reserved
#: boundary is SUBLEVEL_CAVING / SHRINKAGE_STOPING
IMPLEMENTED = [
    MiningMethodType.LONGHOLE_OPEN_STOPING,
    MiningMethodType.CUT_AND_FILL,
    MiningMethodType.ROOM_AND_PILLAR,
]
RESERVED = [m for m in MiningMethodType if m not in IMPLEMENTED]


def _scenario(method: MiningMethodType) -> Scenario:
    sc = Scenario(**ScenarioCreate(name="registry").model_dump())
    return sc.model_copy(update={"mining": sc.mining.model_copy(update={"method": method})})


def test_every_method_resolves_explicitly() -> None:
    plans = all_plans()
    assert set(plans) == set(MiningMethodType)
    for m in MiningMethodType:
        plan = plan_for(m)
        assert plan is plans[m]
        assert plan.method is m
        assert plan.display_name == DISPLAY_NAMES[m]
        assert plan.implementation_status in ("IMPLEMENTED", "UNSUPPORTED_METHOD")
    assert set(DISPLAY_NAMES) == set(MiningMethodType)


def test_longhole_is_the_implemented_plan() -> None:
    plan = plan_for(MiningMethodType.LONGHOLE_OPEN_STOPING)
    assert isinstance(plan, LongholeOpenStopingPlan)
    assert plan.implementation_status == "IMPLEMENTED"
    sc = _scenario(MiningMethodType.LONGHOLE_OPEN_STOPING)
    pd = plan.production_development(sc)
    assert pd.method == "LONGHOLE_OPEN_STOPING" and pd.status == "IMPLEMENTED" and pd.reason is None
    lattice = plan.production_access_pattern(sc)
    assert isinstance(lattice, StationLatticeAccessPattern)
    assert ProductionLattice is StationLatticeAccessPattern
    assert (
        lattice.pitch
        == station_pitch(sc.mining)
        == sc.mining.stope_length + sc.mining.minimum_pillar
    )
    assert lattice.margin == station_margin(sc.mining)


@pytest.mark.parametrize("method", RESERVED, ids=[m.value for m in RESERVED])
def test_reserved_methods_are_explicit_unsupported_plans(method: MiningMethodType) -> None:
    plan = plan_for(method)
    assert isinstance(plan, UnsupportedMethodPlan)
    assert plan.implementation_status == "UNSUPPORTED_METHOD"
    sc = _scenario(method)
    pd = plan.production_development(sc)
    # the pre-21A ``levels.json`` wording is kept verbatim (no regression noise)
    assert pd.method == method.value and pd.status == "UNSUPPORTED_METHOD"
    assert pd.reason == (
        f"{method.value} production development (ore drives, lift / fill "
        "accesses, raises) is reserved and not implemented; only the generic "
        "footwall backbone drift is developed — no longhole crosscut lattice "
        "is substituted (rule 159)"
    )
    assert plan.production_access_pattern(sc) is None
    stopes = plan.generate_production(sc, None, {}, None, "rev")  # type: ignore[arg-type]
    assert stopes.status == "FAILED" and stopes.method == method.value
    assert stopes.stopes == [] and stopes.metrics is None
    assert stopes.failure_reason == (
        f"UNSUPPORTED_METHOD: {method.value} is reserved but not implemented in "
        "v0.1 — no silent fallback to LONGHOLE_OPEN_STOPING (rule 78)"
    )


def test_no_reserved_plan_is_the_longhole_plan() -> None:
    longhole = plan_for(MiningMethodType.LONGHOLE_OPEN_STOPING)
    for m in RESERVED:
        assert plan_for(m) is not longhole
        assert not isinstance(plan_for(m), LongholeOpenStopingPlan)


def test_registry_final_table_phase_21bc() -> None:
    """The directive §1 registry table: three IMPLEMENTED plans, two reserved;
    every implemented non-Longhole plan develops ONE fixed central access and
    is never the Longhole plan or a Longhole-derived object."""
    from minegen.mining.methods.cut_fill import CutFillPlan
    from minegen.mining.methods.room_pillar import RoomPillarPlan

    table = {m: plan_for(m).implementation_status for m in MiningMethodType}
    assert table == {
        MiningMethodType.LONGHOLE_OPEN_STOPING: "IMPLEMENTED",
        MiningMethodType.CUT_AND_FILL: "IMPLEMENTED",
        MiningMethodType.ROOM_AND_PILLAR: "IMPLEMENTED",
        MiningMethodType.SUBLEVEL_CAVING: "UNSUPPORTED_METHOD",
        MiningMethodType.SHRINKAGE_STOPING: "UNSUPPORTED_METHOD",
    }
    assert isinstance(plan_for(MiningMethodType.CUT_AND_FILL), CutFillPlan)
    assert isinstance(plan_for(MiningMethodType.ROOM_AND_PILLAR), RoomPillarPlan)
    for m in (MiningMethodType.CUT_AND_FILL, MiningMethodType.ROOM_AND_PILLAR):
        sc = _scenario(m)
        pattern = plan_for(m).production_access_pattern(sc)
        assert isinstance(pattern, FixedAccessPattern)
        assert pattern.offsets(100.0) == [0.0] and pattern.station_index(0.0) == 0
        assert pattern.pitch == 0.0 and pattern.defines_drift_extent is False
        assert plan_for(m).production_development(sc).status == "IMPLEMENTED"


def test_unregistered_method_is_a_typed_lookup_error_never_a_default() -> None:
    with pytest.raises(UnknownMiningMethodError):
        plan_for("BLOCK_CAVING")  # type: ignore[arg-type]
    with pytest.raises(UnknownMiningMethodError):
        plan_for(None)  # type: ignore[arg-type]


def test_production_lattice_arithmetic_is_the_phase_08_formula() -> None:
    lat = ProductionLattice(pitch=35.0, margin=20.0)
    # default 600 m body: half_length 300 → k_max = floor(280/35) = 8 → 17 stations
    assert lat.offsets(300.0) == [k * 35.0 for k in range(-8, 9)]
    # too short for one station → empty, never a clamped station
    assert lat.offsets(19.0) == []
    assert lat.offsets(20.0) == [0.0]


def test_method_dispatch_lives_only_in_the_registry() -> None:
    """Directive §13: no ``if method == LONGHOLE`` survives outside the
    registry package — the level builder and the design service consume
    ``plan_for`` and decide nothing themselves."""
    consumers = {
        SRC / "levels" / "builder.py",
        SRC / "services" / "design_service.py",
    }
    for path in consumers:
        text = path.read_text(encoding="utf-8")
        assert "plan_for(" in text, path
        assert not re.search(r"MiningMethodType\.LONGHOLE_OPEN_STOPING", text), path
        assert "strategy_for" not in text, path
    assert not (SRC / "mining" / "methods" / "base.py").exists()


# --------------------------------------------------------------------------- #
# Phase 21A frontend contract: the scene's read-only method card block
# --------------------------------------------------------------------------- #


def test_scene_mining_method_block_echoes_the_registry() -> None:
    from minegen.export.scene_manifest import build_scene, mining_method_summary
    from minegen.world.synthetic_world import generate_world
    from tests.conftest import small_scenario

    sc = small_scenario()
    world = generate_world(sc)
    block = build_scene(sc, world)["miningMethod"]
    assert block == mining_method_summary(sc)
    table = block.pop("availableMethods")
    assert block == {
        "method": "LONGHOLE_OPEN_STOPING",
        "displayName": "Longhole Open Stoping",
        "implementationStatus": "IMPLEMENTED",
        "sublevelInterval": float(sc.mining.sublevel_interval),
        "stopeLength": float(sc.mining.stope_length),
        "minimumPillar": float(sc.mining.minimum_pillar),
        "methodParameters": None,
        "productionKind": "STOPES",
    }
    # Phase 21B/C: the registry's whole method table, with canonical defaults
    assert [row["method"] for row in table] == [m.value for m in MiningMethodType]
    by_method = {row["method"]: row for row in table}
    assert by_method["CUT_AND_FILL"] == {
        "method": "CUT_AND_FILL",
        "displayName": "Cut & Fill",
        "implementationStatus": "IMPLEMENTED",
        "productionKind": "CUT_FILL",
        "defaultParameters": {"kind": "CUT_AND_FILL", "liftHeightM": 4.0, "cutLengthM": 15.0},
    }
    assert by_method["ROOM_AND_PILLAR"]["productionKind"] == "ROOM_PILLAR"
    assert by_method["ROOM_AND_PILLAR"]["defaultParameters"]["benchCount"] == 1
    assert by_method["SUBLEVEL_CAVING"]["defaultParameters"] is None
    assert by_method["SUBLEVEL_CAVING"]["implementationStatus"] == "UNSUPPORTED_METHOD"
    cf_block = mining_method_summary(
        sc.model_copy(update={"mining": MiningConfig(method=MiningMethodType.CUT_AND_FILL)})
    )
    assert cf_block["methodParameters"] == by_method["CUT_AND_FILL"]["defaultParameters"]
    assert cf_block["productionKind"] == "CUT_FILL"
    reserved = sc.model_copy(
        update={"mining": sc.mining.model_copy(update={"method": MiningMethodType.SUBLEVEL_CAVING})}
    )
    block = mining_method_summary(reserved)
    assert block["method"] == "SUBLEVEL_CAVING"
    assert block["displayName"] == "Sublevel Caving"
    assert block["implementationStatus"] == "UNSUPPORTED_METHOD"
    # the frontend never maps a method to a status: every enum member is covered here
    statuses = {
        m: mining_method_summary(
            sc.model_copy(update={"mining": sc.mining.model_copy(update={"method": m})})
        )["implementationStatus"]
        for m in MiningMethodType
    }
    assert all(statuses[m] == "IMPLEMENTED" for m in IMPLEMENTED)
    assert all(statuses[m] == "UNSUPPORTED_METHOD" for m in RESERVED)
