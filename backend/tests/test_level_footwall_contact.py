"""Hardening H0 §3.1 (rule 141): the TABULAR footwall-contact guard.

The rule 141 generator measures its top level from the bounding-box top —
the HANGING-WALL top edge of a dipping slab — while the footwall top edge
sits ``thickness·cos(dip)`` lower. A level inside that band has ore above
it and no footwall contact next to it. The legacy access targets already
rejected such a level (``OUTSIDE_OREBODY_DIP_EXTENT``); layout-v2 anchors
only looked at the (non-empty) section and let the level through, where
every crosscut then missed the slab by the same |sdf|.

FAST tests: the analytic helpers on the plan's reproduction case
(RANDOM_TABULAR seed 42 — no world needed), the serviceable set, the
stage-2 screen record, the catalogue shape, the level builder's report and
the guard parity on a small world. The full seed-42 layout-v2 chain and the
12-seed golden parity live in ``test_level_footwall_contact_chain.py``.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from minegen.core.enums import ScenarioPreset
from minegen.core.models import (
    OrebodyConfig,
    Point3D,
    Scenario,
    TerrainConfig,
    WorldConfig,
)
from minegen.design.constraints import RejectionReason
from minegen.design.cost_field import DesignCostEvaluator
from minegen.design.targets import (
    footwall_contact_overshoot,
    generate_access_targets,
    has_footwall_contact,
    minimum_top_margin_for_footwall_contact,
    resolve_portal,
)
from minegen.layout.families import InfeasibleReason
from minegen.layout.levels import (
    NO_FOOTWALL_CONTACT_AT_LEVEL,
    NO_OREBODY_SECTION_AT_LEVEL,
    LevelExclusion,
    LevelSections,
    RequiredLevel,
    required_levels,
    tabular_level_exclusion,
)
from minegen.layout.results import LayoutSearchResult
from minegen.layout.stages import level_service
from minegen.levels.builder import LevelDevelopmentBuilder
from minegen.services.scenario_realizer import realize_scenario
from minegen.world.orebody import TabularOrebody
from minegen.world.synthetic_world import generate_world

from .conftest import small_scenario
from .test_levels import _entry_segment, _setup, _smoothed

#: the plan's reproduction case: dip 61.594°, thickness 24.942 m,
#: T·cos(dip) = 11.865 m > top margin 10 m → L01 overshoots by 2.1206 m
SEED = 42
EXPECTED_OVERSHOOT = 2.1206
EXPECTED_MIN_TOP_MARGIN = 11.865


@pytest.fixture(scope="module")
def seed_42() -> tuple[Scenario, TabularOrebody, list[RequiredLevel]]:
    sc = Scenario(**realize_scenario(ScenarioPreset.RANDOM_TABULAR, SEED, None).model_dump())
    ob = TabularOrebody(sc.orebody)
    levels = required_levels(
        ob, sc.mining.sublevel_interval, sc.design.top_mining_margin, sc.design.bottom_mining_margin
    )
    return sc, ob, levels


def _overshooting_scenario_overrides() -> dict[str, object]:
    """The small test world with a slab thick enough that
    ``thickness·cos(dip)`` (35 × cos 70° = 11.97 m) exceeds the 10 m top
    margin, so L01 lies above the footwall top edge."""
    base = small_scenario().model_dump()
    return {
        "name": "overshoot",
        "seed": base["seed"],
        "world": WorldConfig(**base["world"]),
        "terrain": TerrainConfig(**base["terrain"]),
        "orebody": OrebodyConfig(
            center=Point3D(x=40.0, y=20.0, z=-50.0),
            strike_deg=35.0,
            dip_deg=70.0,
            length=200.0,
            height=120.0,
            thickness=35.0,
            mean_grade=4.2,
            grade_variability=0.3,
        ),
        "field_sampling": base["field_sampling"],
    }


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def test_helpers_reproduce_the_seed_42_census(
    seed_42: tuple[Scenario, TabularOrebody, list[RequiredLevel]],
) -> None:
    sc, ob, levels = seed_42
    assert len(levels) == 13
    top = levels[0]
    assert not has_footwall_contact(ob, top.elevation)
    assert footwall_contact_overshoot(ob, top.elevation) == pytest.approx(
        EXPECTED_OVERSHOOT, abs=1e-3
    )
    assert minimum_top_margin_for_footwall_contact(ob) == pytest.approx(
        EXPECTED_MIN_TOP_MARGIN, abs=1e-2
    )
    # the hint IS thickness·cos(dip): dip-aware, in metres
    assert minimum_top_margin_for_footwall_contact(ob) == pytest.approx(
        sc.orebody.thickness * math.cos(math.radians(sc.orebody.dip_deg))
    )
    # every lower level has its contact; the overshoot sign agrees with the guard
    for lv in levels[1:]:
        assert has_footwall_contact(ob, lv.elevation)
        assert footwall_contact_overshoot(ob, lv.elevation) <= 0.0
    # the hint is the BOUNDARY: at exactly thickness·cos(dip) the top level
    # sits on the footwall top edge (overshoot 0 within float noise), and any
    # margin above it restores the contact on L01
    hint = minimum_top_margin_for_footwall_contact(ob)
    boundary = required_levels(
        ob, sc.mining.sublevel_interval, hint, sc.design.bottom_mining_margin
    )
    assert footwall_contact_overshoot(ob, boundary[0].elevation) == pytest.approx(0.0, abs=1e-9)
    raised = required_levels(
        ob, sc.mining.sublevel_interval, hint + 1e-6, sc.design.bottom_mining_margin
    )
    assert has_footwall_contact(ob, raised[0].elevation)


def test_tabular_level_exclusion_is_typed_and_none_on_contact(
    seed_42: tuple[Scenario, TabularOrebody, list[RequiredLevel]],
) -> None:
    _, ob, levels = seed_42
    exc = tabular_level_exclusion(ob, levels[0])
    assert isinstance(exc, LevelExclusion)
    assert exc.reason == NO_FOOTWALL_CONTACT_AT_LEVEL
    assert exc.level_id == "L01" and exc.index == 0
    assert exc.overshoot_m == pytest.approx(EXPECTED_OVERSHOOT, abs=1e-3)
    assert exc.minimum_top_mining_margin_m == pytest.approx(EXPECTED_MIN_TOP_MARGIN, abs=1e-2)
    assert exc.to_dict()["reason"] == InfeasibleReason.NO_FOOTWALL_CONTACT_AT_LEVEL.value
    assert tabular_level_exclusion(ob, levels[1]) is None


# --------------------------------------------------------------------------- #
# serviceable set (layout-v2)
# --------------------------------------------------------------------------- #


def test_level_sections_exclude_the_level_without_footwall_contact(
    seed_42: tuple[Scenario, TabularOrebody, list[RequiredLevel]],
) -> None:
    sc, ob, levels = seed_42
    sections = LevelSections(ob, levels, sc.layout.section_sampling_spacing)
    # the section itself is NOT empty: ore exists above the level
    assert not sections.section(levels[0]).empty
    assert [lv.level_id for lv in sections.serviceable()] == [lv.level_id for lv in levels[1:]]
    excluded = sections.excluded()
    assert [e.level_id for e in excluded] == ["L01"]
    assert excluded[0].reason == NO_FOOTWALL_CONTACT_AT_LEVEL
    assert sections.exclusion(levels[0]) is excluded[0]
    assert all(sections.exclusion(lv) is None for lv in levels[1:])


def test_level_sections_keep_every_level_when_the_contact_exists() -> None:
    sc = small_scenario()
    ob = TabularOrebody(sc.orebody)
    levels = required_levels(
        ob, sc.mining.sublevel_interval, sc.design.top_mining_margin, sc.design.bottom_mining_margin
    )
    sections = LevelSections(ob, levels, sc.layout.section_sampling_spacing)
    assert sections.excluded() == []
    assert [lv.level_id for lv in sections.serviceable()] == [lv.level_id for lv in levels]


def test_section_emptiness_wins_over_the_footwall_guard(
    seed_42: tuple[Scenario, TabularOrebody, list[RequiredLevel]],
) -> None:
    """A level plane that misses the solid is NO_OREBODY_SECTION_AT_LEVEL
    (the existing rule 141 reason) whatever the footwall arithmetic says."""
    sc, ob, levels = seed_42
    fake = RequiredLevel("L99", 98, -5000.0)
    sections = LevelSections(ob, [*levels, fake], sc.layout.section_sampling_spacing)
    exc = sections.exclusion(fake)
    assert exc is not None and exc.reason == NO_OREBODY_SECTION_AT_LEVEL
    assert exc.overshoot_m is None and exc.minimum_top_mining_margin_m is None


def test_stage2_level_service_records_the_footwall_exclusion(
    seed_42: tuple[Scenario, TabularOrebody, list[RequiredLevel]],
) -> None:
    sc, ob, levels = seed_42
    sections = LevelSections(ob, levels, sc.layout.section_sampling_spacing)
    top, second = levels[0], levels[1]
    c = sections.section(second).centroid
    pts = np.array([[c[0], c[1], top.elevation + 20.0], [c[0] + 1.0, c[1], second.elevation - 5.0]])
    records, _ = level_service(pts, [top, second], sections, sc.layout.access_reach)
    assert records[0].unserved_reason == InfeasibleReason.NO_FOOTWALL_CONTACT_AT_LEVEL.value
    assert not records[0].within_reach
    assert records[1].unserved_reason is None and records[1].within_reach


def test_catalogue_required_levels_carry_the_typed_exclusion(
    seed_42: tuple[Scenario, TabularOrebody, list[RequiredLevel]],
) -> None:
    sc, ob, levels = seed_42
    sections = LevelSections(ob, levels, sc.layout.section_sampling_spacing)
    res = LayoutSearchResult(
        levels=levels,
        serviceable_ids=[lv.level_id for lv in sections.serviceable()],
        level_exclusions={e.level_id: e for e in sections.excluded()},
        track=None,
        portal=np.zeros(3),
        portal_generated=True,
        candidates=[],
        shortlist=[],
        ranking=[],
        winner_id=None,
        clearance_basis="EXACT",
        clearance_error_bound=0.0,
        required_clearance=0.0,
        access_reach=0.0,
        standoff=0.0,
        performance={},
        config={},
    )
    d = res.to_dict()
    assert d["serviceableLevelCount"] == 12
    top, second = d["requiredLevels"][0], d["requiredLevels"][1]
    assert top["levelId"] == "L01"
    assert top["hasOrebodySection"] is True  # ore above the level — the plane cuts the slab
    assert top["serviceable"] is False
    assert top["exclusionReason"] == NO_FOOTWALL_CONTACT_AT_LEVEL
    assert top["overshootM"] == pytest.approx(EXPECTED_OVERSHOOT, abs=1e-3)
    assert top["minimumTopMiningMarginM"] == pytest.approx(EXPECTED_MIN_TOP_MARGIN, abs=1e-2)
    assert second["serviceable"] is True and second["exclusionReason"] is None
    assert second["overshootM"] is None and second["minimumTopMiningMarginM"] is None
    assert res.serviceable_levels == levels[1:]


# --------------------------------------------------------------------------- #
# the one guard: legacy targets == layout-v2 serviceable set
# --------------------------------------------------------------------------- #


def test_legacy_targets_and_layout_v2_apply_the_same_guard(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sc, world, _ = _setup(tmp_path, **_overshooting_scenario_overrides())
    ob = world.orebody
    assert isinstance(ob, TabularOrebody)
    portal, generated = resolve_portal(sc, world)
    targets = generate_access_targets(
        world,
        sc.design,
        sc.ramp,
        sc.mining.sublevel_interval,
        DesignCostEvaluator(world, sc.design),
        portal,
        generated,
    )
    legacy_dip_valid = [
        lv.level_id
        for lv in targets.levels
        if not all(
            RejectionReason.OUTSIDE_OREBODY_DIP_EXTENT in c.rejection_reasons for c in lv.candidates
        )
    ]
    levels = required_levels(
        ob, sc.mining.sublevel_interval, sc.design.top_mining_margin, sc.design.bottom_mining_margin
    )
    sections = LevelSections(ob, levels, sc.layout.section_sampling_spacing)
    assert [lv.level_id for lv in sections.serviceable()] == legacy_dip_valid
    assert [e.level_id for e in sections.excluded()] == ["L01"]
    assert all(
        RejectionReason.OUTSIDE_OREBODY_DIP_EXTENT in c.rejection_reasons
        for c in targets.levels[0].candidates
    )


# --------------------------------------------------------------------------- #
# levels.json report
# --------------------------------------------------------------------------- #


def _levels_for(sc: Scenario, world: object) -> list[RequiredLevel]:
    ob = world.orebody  # type: ignore[attr-defined]
    return required_levels(
        ob, sc.mining.sublevel_interval, sc.design.top_mining_margin, sc.design.bottom_mining_margin
    )


def _segments(world: object, sc: Scenario, levels: list[RequiredLevel]) -> list[dict]:  # type: ignore[type-arg]
    segs = []
    for lv in levels:
        seg = _entry_segment(world, sc, u_entry=0.0, level_z=lv.elevation)
        seg["levelId"] = lv.level_id
        seg["candidateId"] = f"{lv.level_id}-C01"
        segs.append(seg)
    return segs


def test_level_builder_reports_the_excluded_level_and_its_interval(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sc, world, builder = _setup(tmp_path, **_overshooting_scenario_overrides())
    levels = _levels_for(sc, world)
    assert len(levels) >= 3
    ob = world.orebody
    assert isinstance(ob, TabularOrebody)
    assert not has_footwall_contact(ob, levels[0].elevation)
    # the active source serves L02 … Lnn (the guard removed L01 upstream)
    payload = builder.build(_smoothed(*_segments(world, sc, levels[1:])), "rev")
    assert payload.status == "SUCCESS", payload.failure_reason
    assert [lv.level_id for lv in payload.levels] == [lv.level_id for lv in levels[1:]]
    (excluded,) = payload.excluded_levels
    assert excluded.level_id == "L01" and excluded.index == 0
    assert excluded.elevation == pytest.approx(levels[0].elevation)
    assert excluded.reason == "NO_FOOTWALL_CONTACT_AT_LEVEL"
    assert excluded.overshoot_m == pytest.approx(
        footwall_contact_overshoot(ob, levels[0].elevation)
    )
    assert excluded.minimum_top_mining_margin_m == pytest.approx(
        minimum_top_margin_for_footwall_contact(ob)
    )
    (interval,) = payload.unserved_intervals
    assert (interval.upper_level_id, interval.lower_level_id) == ("L01", "L02")
    assert interval.reason == "NO_FOOTWALL_CONTACT_AT_LEVEL"
    assert interval.upper_elevation == pytest.approx(levels[0].elevation)
    assert interval.lower_elevation == pytest.approx(levels[1].elevation)
    # the report is persisted in camelCase and round-trips through the model
    doc = payload.model_dump(mode="json", by_alias=True)
    assert doc["excludedLevels"][0]["overshootM"] == pytest.approx(excluded.overshoot_m)
    assert doc["unservedIntervals"][0]["upperLevelId"] == "L01"
    assert type(payload).model_validate(doc).excluded_levels == payload.excluded_levels


def test_level_builder_names_the_footwall_exclusion_once_when_an_entry_is_forced(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A persisted pre-hardening selection can still hand the builder an L01
    entry: the level fails with ONE typed reason up front (not eleven
    terminal-sdf station failures), the geometry stays inspectable and
    nothing is relaxed."""
    sc, world, builder = _setup(tmp_path, **_overshooting_scenario_overrides())
    levels = _levels_for(sc, world)
    payload = builder.build(_smoothed(*_segments(world, sc, levels)), "rev")
    assert payload.status == "FAILED"
    assert payload.failure_reason is not None
    assert payload.failure_reason.startswith("L01: NO_FOOTWALL_CONTACT_AT_LEVEL")
    assert "topMiningMargin" in payload.failure_reason
    assert payload.excluded_levels == [] and payload.unserved_intervals == []
    l01 = payload.levels[0]
    assert l01.level_id == "L01" and not l01.valid
    # every L01 crosscut still misses the slab by the overshoot (unchanged hard validation)
    ob = world.orebody
    assert isinstance(ob, TabularOrebody)
    overshoot = footwall_contact_overshoot(ob, levels[0].elevation)
    for dev in payload.developments:
        if dev.level_id == "L01" and dev.kind.value == "CROSSCUT":
            assert dev.report.terminal_sdf == pytest.approx(overshoot, abs=1e-6)
            assert not dev.report.valid
    assert all(lv.valid for lv in payload.levels[1:])


def test_level_builder_reports_missing_entries_as_no_level_entry(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A legacy decline that stopped early delivers fewer entries: the
    undeveloped required levels are reported typed, never silently absent."""
    sc, world, builder = _setup(tmp_path)
    levels = _levels_for(sc, world)
    assert len(levels) >= 4
    payload = builder.build(_smoothed(*_segments(world, sc, levels[:2])), "rev")
    assert payload.status == "SUCCESS", payload.failure_reason
    assert [e.level_id for e in payload.excluded_levels] == [lv.level_id for lv in levels[2:]]
    assert {e.reason for e in payload.excluded_levels} == {"NO_LEVEL_ENTRY"}
    assert all(e.overshoot_m is None for e in payload.excluded_levels)
    assert [(i.upper_level_id, i.lower_level_id) for i in payload.unserved_intervals] == [
        (levels[k].level_id, levels[k + 1].level_id) for k in range(1, len(levels) - 1)
    ]


def test_level_builder_report_is_empty_when_every_level_is_developed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sc, world, builder = _setup(tmp_path)
    levels = _levels_for(sc, world)
    payload = builder.build(_smoothed(*_segments(world, sc, levels)), "rev")
    assert payload.status == "SUCCESS", payload.failure_reason
    assert payload.excluded_levels == [] and payload.unserved_intervals == []
    doc = payload.model_dump(mode="json", by_alias=True)
    assert doc["excludedLevels"] == [] and doc["unservedIntervals"] == []


def test_source_exclusion_reasons_are_consulted_only_for_non_tabular_bodies(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """For a TABULAR body the analytic guard decides; a recorded section
    exclusion for a level the guard would develop is NOT trusted over it
    (READ ≠ TRUST at the builder's boundary)."""
    sc, world, builder = _setup(tmp_path)
    levels = _levels_for(sc, world)
    payload = builder.build(
        _smoothed(*_segments(world, sc, levels[1:])),
        "rev",
        level_exclusion_reasons={"L01": NO_OREBODY_SECTION_AT_LEVEL},
    )
    (excluded,) = payload.excluded_levels
    assert excluded.level_id == "L01" and excluded.reason == "NO_LEVEL_ENTRY"


def test_builder_report_is_pure_and_deterministic(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sc, world, builder = _setup(tmp_path, **_overshooting_scenario_overrides())
    levels = _levels_for(sc, world)
    segs = _segments(world, sc, levels[1:])
    a = builder.build(_smoothed(*segs), "rev").model_dump(mode="json", by_alias=True)
    b = builder.build(_smoothed(*segs), "rev").model_dump(mode="json", by_alias=True)
    assert a == b
    assert isinstance(builder, LevelDevelopmentBuilder)
    gen = generate_world(sc)
    assert gen.orebody.bounding_box()[1][2] == pytest.approx(world.orebody.bounding_box()[1][2])
