"""Phase 17 — deterministic scenario realization (rules 119–122)."""

from __future__ import annotations

import numpy as np
import pytest

from minegen.core.enums import OrebodyType, ScenarioPreset
from minegen.core.models import Scenario, ScenarioCreate
from minegen.services.scenario_realizer import (
    FAULT_REALIZATION_STREAM,
    OREBODY_REALIZATION_STREAM,
    ScenarioRealizationError,
    realize_scenario,
)
from minegen.world.geology import FaultPlane
from minegen.world.synthetic_world import generate_world

# -- BASELINE -------------------------------------------------------------- #


def test_baseline_matches_phase16_user_facing_mine() -> None:
    """BASELINE == the Phase 16 ScenarioPanel default ('one fault' ON):
    backend-default orebody + the exact explicit geology numbers."""
    sc = realize_scenario(ScenarioPreset.BASELINE, 42)
    default = ScenarioCreate()
    assert sc.seed == 42
    assert sc.orebody == default.orebody  # untouched backend default orebody
    assert sc.world == default.world and sc.terrain == default.terrain
    rq = sc.geology.rock_quality
    assert (rq.mean, rq.std, rq.correlation_length_xy, rq.correlation_length_z) == (
        65.0,
        12.0,
        80.0,
        40.0,
    )
    assert (rq.minimum, rq.maximum) == (20.0, 90.0)
    [f] = sc.geology.faults
    assert (f.origin.x, f.origin.y, f.origin.z) == (-100.0, -200.0, 0.0)
    assert (f.strike_deg, f.dip_deg) == (120.0, 65.0)
    assert (f.core_half_width, f.influence_half_width) == (2.5, 20.0)
    assert (f.core_penalty, f.damage_zone_penalty) == (50.0, 10.0)


def test_backend_empty_body_baseline_unchanged() -> None:
    """POST /scenarios with {} must stay exactly the pre-Phase-17 contract:
    no faults, default orebody — realization never leaks into defaults."""
    default = ScenarioCreate()
    assert default.geology.faults == []
    assert default.orebody.orebody_type is OrebodyType.TABULAR
    assert default.orebody.center.x == 200.0 and default.orebody.length == 600.0
    assert default.seed == 42


# -- determinism / isolation (rule 121) ------------------------------------ #


def test_same_seed_same_realization() -> None:
    a = realize_scenario(ScenarioPreset.RANDOM_TABULAR, 12345)
    b = realize_scenario(ScenarioPreset.RANDOM_TABULAR, 12345)
    assert a == b


def test_different_seed_changes_realization() -> None:
    a = realize_scenario(ScenarioPreset.RANDOM_TABULAR, 12345)
    c = realize_scenario(ScenarioPreset.RANDOM_TABULAR, 12346)
    assert a.orebody != c.orebody or a.geology.faults != c.geology.faults


def test_stream_isolation_fault_count_never_moves_orebody() -> None:
    base = realize_scenario(ScenarioPreset.RANDOM_TABULAR, 999, fault_count=0)
    for count in (1, 3, 6):
        again = realize_scenario(ScenarioPreset.RANDOM_TABULAR, 999, fault_count=count)
        assert again.orebody == base.orebody
        assert len(again.geology.faults) == count
    assert len(base.geology.faults) == 0


def test_stream_isolation_orebody_preset_never_moves_faults() -> None:
    t = realize_scenario(ScenarioPreset.RANDOM_TABULAR, 999, fault_count=3)
    e = realize_scenario(ScenarioPreset.RANDOM_ELLIPSOID, 999, fault_count=3)
    assert t.geology.faults == e.geology.faults


def test_stream_keys_are_distinct_and_documented() -> None:
    existing = {0x20C4, 0x6A4D, 0x7E44A1}  # rock, grade, terrain
    assert OREBODY_REALIZATION_STREAM not in existing
    assert FAULT_REALIZATION_STREAM not in existing
    assert OREBODY_REALIZATION_STREAM != FAULT_REALIZATION_STREAM


# -- fault generator (rule 122) -------------------------------------------- #


def test_every_generated_fault_intersects_the_model_volume() -> None:
    for seed in (1, 7, 12345, 999_999):
        sc = realize_scenario(ScenarioPreset.RANDOM_TABULAR, seed, fault_count=6)
        box = sc.world.bounds(sc.terrain.base_elevation)
        lo = np.array(box.min.as_tuple())
        hi = np.array(box.max.as_tuple())
        for f in sc.geology.faults:
            assert FaultPlane.from_config(f).clip_to_box(lo, hi).shape[0] >= 3


def test_invalid_options_rejected() -> None:
    with pytest.raises(ScenarioRealizationError):
        realize_scenario(ScenarioPreset.RANDOM_TABULAR, 1, fault_count=7)
    with pytest.raises(ScenarioRealizationError):
        realize_scenario(ScenarioPreset.RANDOM_TABULAR, 1, fault_count=-1)
    with pytest.raises(ScenarioRealizationError):
        realize_scenario(ScenarioPreset.BASELINE, 1, fault_count=3)


# -- persisted reproduction (spec §20 D) ----------------------------------- #


def test_persisted_realization_reproduces_identical_world() -> None:
    sc = realize_scenario(ScenarioPreset.RANDOM_ELLIPSOID, 4242, fault_count=1)
    dumped = sc.model_dump_json()
    restored = ScenarioCreate.model_validate_json(dumped)
    assert restored == sc
    w1 = generate_world(Scenario(**sc.model_dump()))
    w2 = generate_world(Scenario(**restored.model_dump()))
    assert np.array_equal(w1.block_model.grade, w2.block_model.grade)
    assert np.array_equal(w1.block_model.rock_quality, w2.block_model.rock_quality)
    assert w1.orebody.to_dict() == w2.orebody.to_dict()
