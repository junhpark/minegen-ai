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
from minegen.core.models import Scenario, ScenarioCreate
from minegen.mining.methods.contracts import ProductionLattice, station_margin, station_pitch
from minegen.mining.methods.longhole import LongholeOpenStopingPlan
from minegen.mining.methods.registry import (
    DISPLAY_NAMES,
    UnknownMiningMethodError,
    all_plans,
    plan_for,
)
from minegen.mining.methods.unsupported import UnsupportedMethodPlan

SRC = Path(__file__).resolve().parents[1] / "src" / "minegen"
RESERVED = [m for m in MiningMethodType if m is not MiningMethodType.LONGHOLE_OPEN_STOPING]


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
    lattice = plan.production_lattice(sc)
    assert isinstance(lattice, ProductionLattice)
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
    assert plan.production_lattice(sc) is None
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
    assert block == {
        "method": "LONGHOLE_OPEN_STOPING",
        "displayName": "Longhole Open Stoping",
        "implementationStatus": "IMPLEMENTED",
        "sublevelInterval": float(sc.mining.sublevel_interval),
        "stopeLength": float(sc.mining.stope_length),
        "minimumPillar": float(sc.mining.minimum_pillar),
    }
    reserved = sc.model_copy(
        update={"mining": sc.mining.model_copy(update={"method": MiningMethodType.CUT_AND_FILL})}
    )
    block = mining_method_summary(reserved)
    assert block["method"] == "CUT_AND_FILL"
    assert block["displayName"] == "Cut & Fill"
    assert block["implementationStatus"] == "UNSUPPORTED_METHOD"
    # the frontend never maps a method to a status: every enum member is covered here
    statuses = {
        m: mining_method_summary(
            sc.model_copy(update={"mining": sc.mining.model_copy(update={"method": m})})
        )["implementationStatus"]
        for m in MiningMethodType
    }
    assert statuses[MiningMethodType.LONGHOLE_OPEN_STOPING] == "IMPLEMENTED"
    assert all(
        v == "UNSUPPORTED_METHOD"
        for m, v in statuses.items()
        if m is not MiningMethodType.LONGHOLE_OPEN_STOPING
    )
