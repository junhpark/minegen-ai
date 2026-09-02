"""Phase 17 — deterministic scenario realization (rules 119–122)."""

from __future__ import annotations

import numpy as np
import pytest

from minegen.core.enums import OrebodyType, ScenarioPreset
from minegen.core.models import OrebodyConfig, Point3D, Scenario, ScenarioCreate
from minegen.services.scenario_realizer import (
    FAULT_REALIZATION_STREAM,
    OREBODY_REALIZATION_STREAM,
    ScenarioRealizationError,
    orebody_within_world,
    realize_scenario,
)
from minegen.world.geology import FaultPlane
from minegen.world.orebody import build_orebody
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
    assert np.array_equal(w1.fields.grade.values, w2.fields.grade.values)
    assert np.array_equal(w1.fields.rock_quality.values, w2.fields.rock_quality.values)
    assert w1.orebody.to_dict() == w2.orebody.to_dict()


# -- actual-geometry world bounds gate (rule 125) --------------------------- #


def _world_box(sc: ScenarioCreate) -> tuple[np.ndarray, np.ndarray]:
    box = sc.world.bounds(sc.terrain.base_elevation)
    return np.array(box.min.as_tuple()), np.array(box.max.as_tuple())


def assert_geometry_inside_world(sc: ScenarioCreate) -> None:
    """Independent assertion: rebuild the orebody and compare its ANALYTIC
    AABB with the world box. Deliberately does not call the production
    predicate, so the gate cannot pass by validating itself."""
    lo, hi = _world_box(sc)
    bbox_min, bbox_max = build_orebody(sc.orebody).bounding_box()
    assert bbox_min[0] >= lo[0] + 80.0, f"west escape: {bbox_min[0]}"
    assert bbox_max[0] <= hi[0] - 80.0, f"east escape: {bbox_max[0]}"
    assert bbox_min[1] >= lo[1] + 80.0, f"south escape: {bbox_min[1]}"
    assert bbox_max[1] <= hi[1] - 80.0, f"north escape: {bbox_max[1]}"
    assert bbox_min[2] >= lo[2], f"below model floor: {bbox_min[2]}"
    assert bbox_max[2] <= hi[2] - 40.0, f"insufficient cover: {bbox_max[2]}"


@pytest.mark.parametrize("preset", [ScenarioPreset.RANDOM_TABULAR, ScenarioPreset.RANDOM_ELLIPSOID])
def test_randomized_orebody_geometry_stays_inside_world(preset: ScenarioPreset) -> None:
    """A rotated slab/ellipsoid can reach far beyond its centre, so every
    realization is checked as BUILT geometry over a wide seed sample."""
    for seed in range(150):
        assert_geometry_inside_world(realize_scenario(preset, seed, fault_count=0))


def test_seed_2411_regression_rotated_body_no_longer_escapes_x_boundary() -> None:
    """Pinned regression: with the old centre-only gate this seed's first
    accepted candidate reached x = +602.6 m — outside the 1200 m world
    (±600) and far past the 80 m margin. The seed itself is unchanged; the
    AABB gate must reject that candidate and take a later deterministic
    draw."""
    sc = realize_scenario(ScenarioPreset.RANDOM_TABULAR, 2411)
    assert_geometry_inside_world(sc)
    bbox_max = build_orebody(sc.orebody).bounding_box()[1]
    assert bbox_max[0] <= 520.0  # 600 - 80


def test_rejected_candidates_do_not_break_determinism() -> None:
    """Retries consume the orebody sub-stream, so the same seed must still
    reproduce the same accepted candidate exactly."""
    for seed in (2411, 7, 88_888):
        a = realize_scenario(ScenarioPreset.RANDOM_TABULAR, seed)
        b = realize_scenario(ScenarioPreset.RANDOM_TABULAR, seed)
        assert a.orebody == b.orebody


def test_bounds_gate_rejects_a_deliberately_escaping_config() -> None:
    """The predicate itself: a body pushed against the world edge fails."""
    base = ScenarioCreate()
    escaping = OrebodyConfig(
        orebody_type=OrebodyType.TABULAR,
        center=Point3D(x=560.0, y=0.0, z=-50.0),
        strike_deg=0.0,
        dip_deg=60.0,
        length=600.0,
        height=300.0,
        thickness=12.0,
    )
    assert not orebody_within_world(escaping, base)
    fitting = OrebodyConfig(
        orebody_type=OrebodyType.TABULAR,
        center=Point3D(x=0.0, y=0.0, z=-120.0),
        strike_deg=0.0,
        dip_deg=60.0,
        length=400.0,
        height=250.0,
        thickness=12.0,
    )
    assert orebody_within_world(fitting, base)


def test_orebody_retries_do_not_disturb_other_streams() -> None:
    """Extra orebody draws must not shift fault/rock/grade realization."""
    tab = realize_scenario(ScenarioPreset.RANDOM_TABULAR, 2411, fault_count=3)
    ell = realize_scenario(ScenarioPreset.RANDOM_ELLIPSOID, 2411, fault_count=3)
    assert tab.geology.faults == ell.geology.faults
    assert tab.geology.rock_quality == ell.geology.rock_quality
