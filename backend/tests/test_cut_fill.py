"""Cut & Fill acceptance — Phase 21B (CF-1 … CF-8, CF-12) under the H2-CF
block / panel structure (hardening PR-2, C1).

Schedule tests (CF-9 … CF-11 and the H2-CF concurrency / sill-mat timing)
live in ``tests/test_production_timeline.py``.
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
from minegen.core.models import CutFillParameters, MiningConfig, Scenario
from minegen.geometry.mesh_qa import mesh_qa
from minegen.mining.methods.contracts import PanelAccessPattern
from minegen.mining.methods.cut_fill import (
    CutFillPlan,
    generate_cut_fill,
    panel_access_by_level,
)
from minegen.mining.methods.integrity import cut_fill_integrity
from minegen.mining.methods.registry import plan_for
from minegen.mining.methods.solids import MAX_PRODUCTION_SOLIDS, equal_partition
from minegen.mining.models import CutFillPayload, parse_production_payload
from minegen.world.orebody import TabularOrebody
from minegen.world.synthetic_world import SyntheticWorld, generate_world
from tests.conftest import small_scenario
from tests.phase21a_parity_support import canonical, layout_chain, with_method

#: the canonical registry defaults (rule 194) — H2-CF planning defaults
CF_DEFAULTS = {
    "kind": "CUT_AND_FILL",
    "liftHeightM": 4.0,
    "cutLengthM": 15.0,
    "stopingDirection": "OVERHAND",
    "blockOrder": "SHALLOW_TO_DEEP",
    "panelLengthM": 60.0,
    "ribPillarWidthM": 0.0,
    "maxConcurrentPanels": 2,
    "sillMatCureDays": 28.0,
}


@pytest.fixture(scope="module")
def cf_world() -> tuple[Scenario, SyntheticWorld]:
    sc = with_method(small_scenario(), MiningMethodType.CUT_AND_FILL)
    return sc, generate_world(sc)


@pytest.fixture(scope="module")
def cf_chain(cf_world: tuple[Scenario, SyntheticWorld]) -> dict[str, Any]:
    sc, world = cf_world
    return layout_chain(sc, world)


def cf_scenario(sc: Scenario, **params: Any) -> Scenario:
    """The scenario with explicit Cut & Fill parameter overrides (re-validated
    exactly as a client PUT would be)."""
    mining = sc.mining.model_dump(by_alias=True, exclude={"method_parameters"})
    mining["methodParameters"] = {**CF_DEFAULTS, **params}
    return sc.model_copy(update={"mining": MiningConfig.model_validate(mining)})


def regenerate(cf_world: tuple[Scenario, SyntheticWorld], levels: dict[str, Any], **params: Any):
    """Production geometry of a parameter variant over the SAME levels
    artifact (the panel length is unchanged unless overridden, so the
    per-panel accesses stay valid)."""
    sc, world = cf_world
    return generate_cut_fill(cf_scenario(sc, **params), world, levels, None, "rev")  # type: ignore[arg-type]


def test_cf1_registry_resolves_the_implemented_cut_fill_plan() -> None:
    plan = plan_for(MiningMethodType.CUT_AND_FILL)
    assert isinstance(plan, CutFillPlan) and plan.implementation_status == "IMPLEMENTED"
    sc = with_method(small_scenario(), MiningMethodType.CUT_AND_FILL)
    assert isinstance(sc.mining.method_parameters, CutFillParameters)
    pattern = plan.production_access_pattern(sc)
    assert isinstance(pattern, PanelAccessPattern) and pattern.panel_length == 60.0
    assert plan.production_development(sc).status == "IMPLEMENTED"
    # the pattern IS the rule-194 partition: 200 m of strike → 4 panels of 50 m
    assert pattern.panels(100.0) == [(-100.0, -50.0), (-50.0, 0.0), (0.0, 50.0), (50.0, 100.0)]
    assert pattern.offsets(100.0) == [-75.0, -25.0, 25.0, 75.0]
    assert [pattern.station_index(o, 100.0) for o in pattern.offsets(100.0)] == [0, 1, 2, 3]
    with pytest.raises(ValueError):
        pattern.station_index(0.0, 100.0)


def test_cf2_production_development_is_the_backbone_plus_one_access_per_panel(
    cf_world: tuple[Scenario, SyntheticWorld], cf_chain: dict[str, Any]
) -> None:
    _, world = cf_world
    ob = world.orebody
    assert isinstance(ob, TabularOrebody)
    levels = cf_chain["levels"]
    assert levels["status"] == "SUCCESS", levels["failureReason"]
    assert levels["productionDevelopment"] == {
        "method": "CUT_AND_FILL",
        "status": "IMPLEMENTED",
        "reason": None,
    }
    centres = PanelAccessPattern(60.0).offsets(ob.half_length)
    n = len(centres)
    assert n == 4
    crosscuts = [d for d in levels["developments"] if d["kind"] == "CROSSCUT"]
    drifts = [d for d in levels["developments"] if d["kind"] == "DRIFT"]
    assert len(crosscuts) == n * len(levels["levels"]) and len(levels["levels"]) >= 2
    for d in crosscuts:
        k = d["stationIndex"]
        assert 0 <= k < n and abs(d["stationU"] - centres[k]) < 1e-9
        assert d["id"] == f"CROSSCUT:{d['levelId']}:S{k:+03d}"
    assert drifts  # the generic footwall backbone is still developed
    m = levels["metrics"]
    assert m["crosscutCount"] == n * len(levels["levels"])
    assert m["stationsPerLevel"] == n and m["stationPitch"] == 0.0
    assert all(lv["crosscutCount"] == n for lv in levels["levels"])


def test_cf3_generation_is_deterministic(cf_world: tuple[Scenario, SyntheticWorld]) -> None:
    sc, world = cf_world
    a = layout_chain(sc, world)
    b = layout_chain(sc, world)
    assert canonical(a["stopes"]) == canonical(b["stopes"])
    assert canonical(a["levels"]) == canonical(b["levels"])
    prod = a["stopes"]
    assert prod["status"] == "SUCCESS", prod["failureReason"]


def test_cf4_blocks_panels_and_lifts_are_consistent_and_ordered(
    cf_world: tuple[Scenario, SyntheticWorld], cf_chain: dict[str, Any]
) -> None:
    _, world = cf_world
    ob = world.orebody
    assert isinstance(ob, TabularOrebody)
    prod = cf_chain["stopes"]
    level_ids = [lv["levelId"] for lv in cf_chain["levels"]["levels"]]  # top → bottom
    # global lift index increases with world z (deepest block first)
    zs = []
    for lift in prod["lifts"]:
        mid = ob.to_world(np.array([[0.0, 0.5 * (lift["vMin"] + lift["vMax"]), 0.0]]))[0]
        zs.append(float(mid[2]))
    assert [lf["liftIndex"] for lf in prod["lifts"]] == list(range(len(prod["lifts"])))
    assert all(b > a for a, b in pairwise(zs)), "lift z must increase"
    assert prod["lifts"][0]["lowerLevelId"] == level_ids[-1]
    assert prod["lifts"][0]["liftIndexInBlock"] == 0
    # blocks: one per adjacent level pair, ids and lifts consistent
    blocks = {b["id"]: b for b in prod["blocks"]}
    assert set(blocks) == {f"BLOCK:{lo}-{up}" for up, lo in pairwise(level_ids)}
    by_index = {lf["liftIndex"]: lf for lf in prod["lifts"]}
    for b in blocks.values():
        lifts = [by_index[i] for i in b["liftIndices"]]
        assert [lf["liftIndexInBlock"] for lf in lifts] == list(range(len(lifts)))
        assert all(lf["blockId"] == b["id"] for lf in lifts)
        # v grows DOWN-dip: the bottom lift (index 0) ends at the block's vMax
        assert (
            abs(lifts[0]["vMax"] - b["vMax"]) < 1e-9 and abs(lifts[-1]["vMin"] - b["vMin"]) < 1e-9
        )
        assert b["panelIds"] == [
            f"PANEL:{b['lowerLevelId']}-{b['upperLevelId']}:P{i:02d}" for i in range(4)
        ]
    # every cut: in its panel's cutIds, its lift's cutIds, its block; access = its panel's crosscut
    panels = {p["id"]: p for p in prod["panels"]}
    for c in prod["cuts"]:
        p = panels[c["panelId"]]
        assert c["id"] in p["cutIds"] and c["id"] in by_index[c["liftIndex"]]["cutIds"]
        assert p["blockId"] == c["blockId"] == by_index[c["liftIndex"]]["blockId"]
        assert c["panelIndex"] == p["panelIndex"]
        assert c["accessDevelopmentId"] == f"CROSSCUT:{c['lowerLevelId']}:S{c['panelIndex']:+03d}"
        assert p["accessDevelopmentId"] == c["accessDevelopmentId"]
        assert c["id"] == (
            f"CUT:{c['lowerLevelId']}-{c['upperLevelId']}:P{c['panelIndex']:02d}:"
            f"LF{c['liftIndexInBlock']:02d}:C{c['cutIndex']:02d}"
        )
    assert prod["metrics"]["blockCount"] == len(blocks) == len(level_ids) - 1
    assert prod["metrics"]["panelCount"] == len(panels) == 4 * len(blocks)


def test_cf5_equal_partitions_leave_no_gap_overlap_or_residual(
    cf_world: tuple[Scenario, SyntheticWorld], cf_chain: dict[str, Any]
) -> None:
    sc, world = cf_world
    ob = world.orebody
    assert isinstance(ob, TabularOrebody)
    params = sc.mining.method_parameters
    assert isinstance(params, CutFillParameters)
    prod = cf_chain["stopes"]
    panels = {p["id"]: p for p in prod["panels"]}
    # panels partition the strike extent of every block (rib pillar 0)
    for b in prod["blocks"]:
        ps = [panels[pid] for pid in b["panelIds"]]
        assert abs(ps[0]["uMin"] + ob.half_length) < 1e-9
        assert abs(ps[-1]["uMax"] - ob.half_length) < 1e-9
        for x, y in pairwise(ps):
            assert abs(x["uMax"] - y["uMin"]) < 1e-9
        lengths = [p["strikeLength"] for p in ps]
        assert max(lengths) - min(lengths) < 1e-9 and max(lengths) <= params.panel_length_m + 1e-9
    for lift in prod["lifts"]:
        for pid in [p["id"] for p in prod["panels"] if p["blockId"] == lift["blockId"]]:
            cuts = sorted(
                (
                    c
                    for c in prod["cuts"]
                    if c["liftIndex"] == lift["liftIndex"] and c["panelId"] == pid
                ),
                key=lambda c: c["localBounds"]["uMin"],
            )
            assert cuts
            assert abs(cuts[0]["localBounds"]["uMin"] - panels[pid]["uMin"]) < 1e-9
            assert abs(cuts[-1]["localBounds"]["uMax"] - panels[pid]["uMax"]) < 1e-9
            for a, b in pairwise(cuts):
                assert abs(a["localBounds"]["uMax"] - b["localBounds"]["uMin"]) < 1e-9
            lengths = [c["strikeLength"] for c in cuts]
            assert max(lengths) - min(lengths) < 1e-9  # EQUAL partition, no residual
            assert max(lengths) <= params.cut_length_m + 1e-9
            assert min(lengths) > 0.5 * params.cut_length_m
            # snake inside the panel: even lifts-in-block −u → +u, odd +u → −u
            seq = sorted(cuts, key=lambda c: c["cutIndex"])
            us = [c["localBounds"]["uMin"] for c in seq]
            expected = sorted(us) if lift["liftIndexInBlock"] % 2 == 0 else sorted(us, reverse=True)
            assert us == expected
        assert lift["verticalHeight"] <= params.lift_height_m + 1e-9
        assert lift["verticalHeight"] > 0.5 * params.lift_height_m
    # lifts of one block are equal partitions too
    for b in prod["blocks"]:
        heights = [lf["verticalHeight"] for lf in prod["lifts"] if lf["blockId"] == b["id"]]
        assert max(heights) - min(heights) < 1e-9, b["id"]
    assert equal_partition(0.0, 10.0, 4.0) == [
        (0.0, 10.0 / 3),
        (10.0 / 3, 20.0 / 3),
        (20.0 / 3, 10.0),
    ]
    assert equal_partition(0.0, 8.0, 4.0) == [(0.0, 4.0), (4.0, 8.0)]
    assert equal_partition(1.0, 1.0, 4.0) == []


def test_cf6_backfill_is_one_to_one_and_cemented_exactly_on_sill_mats(
    cf_chain: dict[str, Any],
) -> None:
    prod = cf_chain["stopes"]
    cuts = {c["id"]: c for c in prod["cuts"]}
    blocks = {b["id"]: b for b in prod["blocks"]}
    assert len(prod["backfills"]) == len(prod["cuts"]) == prod["metrics"]["cutCount"]
    assert prod["metrics"]["backfillCount"] == len(prod["backfills"])
    seen = set()
    cemented_volume = 0.0
    for bf in prod["backfills"]:
        assert bf["sourceCutId"] in cuts and bf["sourceCutId"] not in seen
        seen.add(bf["sourceCutId"])
        assert bf["id"] == "BACKFILL:" + bf["sourceCutId"].removeprefix("CUT:")
        assert bf["volumeM3"] == cuts[bf["sourceCutId"]]["geometricVolumeM3"]
        assert "geometry" not in bf and "vertices" not in bf  # never a second copy
        cut = cuts[bf["sourceCutId"]]
        # SHALLOW_TO_DEEP (default): the bottom lift of every block ABOVE an
        # unmined block is a cemented sill mat; the deepest block never is
        expected = blocks[cut["blockId"]]["sillMatRequired"] and cut["liftIndexInBlock"] == 0
        assert bf["cemented"] is expected
        if bf["cemented"]:
            cemented_volume += bf["volumeM3"]
    deepest = prod["lifts"][0]["blockId"]
    assert blocks[deepest]["sillMatRequired"] is False
    assert all(b["sillMatRequired"] for bid, b in blocks.items() if bid != deepest)
    cemented = [b for b in prod["backfills"] if b["cemented"]]
    assert cemented and prod["metrics"]["cementedBackfillCount"] == len(cemented)
    assert prod["metrics"]["cementedBackfillVolumeM3"] == pytest.approx(cemented_volume)
    assert prod["sequencing"]["stopingDirection"] == "OVERHAND"
    assert prod["sequencing"]["blockOrder"] == "SHALLOW_TO_DEEP"


def test_cf7_cut_volumes_sum_to_the_lifted_interval_volume(
    cf_world: tuple[Scenario, SyntheticWorld], cf_chain: dict[str, Any]
) -> None:
    _, world = cf_world
    ob = world.orebody
    assert isinstance(ob, TabularOrebody)
    prod = cf_chain["stopes"]
    expected = math.fsum(
        (lf["vMax"] - lf["vMin"]) * 2.0 * ob.half_length * 2.0 * ob.half_thickness
        for lf in prod["lifts"]
    )
    total = math.fsum(c["geometricVolumeM3"] for c in prod["cuts"])
    assert abs(total - expected) <= 1e-9 * expected
    assert abs(prod["metrics"]["totalGeometricVolumeM3"] - total) <= 1e-9 * total
    assert prod["ribPillars"] == [] and prod["metrics"]["ribPillarCount"] == 0
    assert prod["metrics"]["totalRibPillarVolumeM3"] == 0.0
    for c in prod["cuts"]:
        r = c["report"]
        assert r["valid"] and r["meshClosedSolid"] and r["volumeAgreement"] and r["finite"]
        assert r["hardInvalidSamples"] == 0
        assert abs(r["meshVolumeM3"] - c["geometricVolumeM3"]) <= 1e-6 * c["geometricVolumeM3"]
        assert c["tonnes"] == pytest.approx(c["geometricVolumeM3"] * 2.8)
        assert c["meanGradeProxy"] is None or c["meanGradeProxy"] > 0


def test_cf8_corrupted_geometry_is_refused_never_trusted(cf_chain: dict[str, Any]) -> None:
    prod = cf_chain["stopes"]
    # NaN vertex: the typed parse refuses the whole artifact (rule 34)
    doc = json.loads(json.dumps(prod))
    doc["cuts"][0]["geometry"]["vertices"][0] = float("nan")
    with pytest.raises(ValidationError):
        parse_production_payload(doc)
    # a bad triangle index / an inverted face / a non-manifold soup fail the
    # SAME independent QA the generator recorded as ``meshClosedSolid``
    cut = prod["cuts"][0]
    positions = np.asarray(cut["geometry"]["vertices"]).reshape(-1, 3)
    tris = np.asarray(cut["geometry"]["triangleIndices"]).reshape(-1, 3)
    assert mesh_qa(positions, tris).closed_solid
    bad = tris.copy()
    bad[0, 0] = 99
    assert not mesh_qa(positions, bad).closed_solid
    flipped = tris.copy()
    flipped[0] = flipped[0][::-1]
    assert not mesh_qa(positions, flipped).closed_solid
    inward = tris[:, ::-1]
    assert (
        mesh_qa(positions, inward).signed_volume < 0 and not mesh_qa(positions, inward).closed_solid
    )
    # a payload of the wrong method under the Cut & Fill class is malformed
    with pytest.raises(ValidationError):
        CutFillPayload.model_validate({**doc, "method": "LONGHOLE_OPEN_STOPING"})
    # a Longhole-shaped document claiming CUT_AND_FILL is refused by the parser
    with pytest.raises(ValidationError):
        parse_production_payload(
            {
                "status": "FAILED",
                "failureReason": "x",
                "sourceRevision": "r",
                "method": "CUT_AND_FILL",
                "stopes": [],
                "metrics": None,
            }
        )
    # a pre-H2-CF document (no blocks / panels / cemented) is a different
    # shape, refused — never reinterpreted
    legacy = {
        k: v for k, v in doc.items() if k not in ("blocks", "panels", "ribPillars", "sequencing")
    }
    with pytest.raises(ValidationError):
        parse_production_payload(legacy)


def test_cf12_non_tabular_orebody_is_a_typed_geometry_boundary_never_a_fallback() -> None:
    sc = with_method(small_scenario(), MiningMethodType.CUT_AND_FILL)
    ell = sc.model_copy(
        update={"orebody": sc.orebody.model_copy(update={"orebody_type": OrebodyType.ELLIPSOID})}
    )
    world = generate_world(ell)
    payload = generate_cut_fill(
        ell,
        world,
        {"status": "SUCCESS", "levels": [], "developments": []},
        None,
        "rev",  # type: ignore[arg-type]
    )
    assert payload.status == "FAILED" and payload.method == "CUT_AND_FILL"
    assert payload.failure_reason is not None
    assert payload.failure_reason.startswith("METHOD_GEOMETRY_NOT_IMPLEMENTED")
    assert payload.cuts == [] and payload.backfills == [] and payload.metrics is None
    assert payload.blocks == [] and payload.panels == [] and payload.sequencing is None


def test_cf_complexity_budget_is_a_typed_failure_never_a_decimation(
    cf_world: tuple[Scenario, SyntheticWorld], cf_chain: dict[str, Any]
) -> None:
    payload = regenerate(cf_world, cf_chain["levels"], liftHeightM=0.05, cutLengthM=0.05)
    assert payload.status == "FAILED" and payload.cuts == []
    assert payload.failure_reason is not None
    assert payload.failure_reason.startswith("PRODUCTION_COMPLEXITY_LIMIT")
    assert str(MAX_PRODUCTION_SOLIDS) in payload.failure_reason


def test_cf_method_parameters_contract() -> None:
    # method alone → canonical defaults, serialized; Longhole never carries the block
    cf = MiningConfig.model_validate({"method": "CUT_AND_FILL"})
    assert cf.model_dump(mode="json", by_alias=True)["methodParameters"] == CF_DEFAULTS
    assert "methodParameters" not in MiningConfig().model_dump(mode="json", by_alias=True)
    # a pre-H2-CF document (lift + cut only) resolves the new planning
    # defaults — the two historic fields keep their meaning
    old = MiningConfig.model_validate(
        {"method": "CUT_AND_FILL", "methodParameters": {"liftHeightM": 3.5, "cutLengthM": 12}}
    )
    assert old.model_dump(mode="json", by_alias=True)["methodParameters"] == {
        **CF_DEFAULTS,
        "liftHeightM": 3.5,
        "cutLengthM": 12.0,
    }
    with pytest.raises(ValidationError):
        MiningConfig.model_validate(
            {"method": "CUT_AND_FILL", "methodParameters": {"roomWidthM": 8}}
        )
    with pytest.raises(ValidationError):
        MiningConfig.model_validate(
            {"method": "LONGHOLE_OPEN_STOPING", "methodParameters": {"liftHeightM": 4}}
        )
    with pytest.raises(ValidationError):
        MiningConfig.model_validate(
            {"method": "CUT_AND_FILL", "methodParameters": {"liftHeightM": 0}}
        )
    # the two sequencing axes are closed enumerations; "top-down" vocabulary
    # is never accepted (it names the UNDERHAND slice direction elsewhere)
    for bad in (
        {"stopingDirection": "TOP_DOWN"},
        {"blockOrder": "BOTTOM_UP"},
        {"maxConcurrentPanels": 0},
        {"panelLengthM": 0},
        {"ribPillarWidthM": -1},
        {"sillMatCureDays": 0},
        {"ribPillarWidthM": 60.0, "panelLengthM": 60.0},  # no mined span left
    ):
        with pytest.raises(ValidationError):
            MiningConfig.model_validate({"method": "CUT_AND_FILL", "methodParameters": bad})
    # UNDERHAND is a DECLARED axis: the schema accepts it (rule 78 pattern —
    # the refusal is the generator's typed failure, test_cf_underhand…)
    uh = MiningConfig.model_validate(
        {"method": "CUT_AND_FILL", "methodParameters": {"stopingDirection": "UNDERHAND"}}
    )
    assert isinstance(uh.method_parameters, CutFillParameters)
    assert uh.method_parameters.stoping_direction == "UNDERHAND"


# --------------------------------------------------------------------------- #
# H2-CF (hardening PR-2 C1)
# --------------------------------------------------------------------------- #


def test_cf_underhand_is_a_typed_unsupported_stoping_direction(
    cf_world: tuple[Scenario, SyntheticWorld], cf_chain: dict[str, Any]
) -> None:
    for order in ("SHALLOW_TO_DEEP", "DEEP_TO_SHALLOW"):
        payload = regenerate(
            cf_world, cf_chain["levels"], stopingDirection="UNDERHAND", blockOrder=order
        )
        assert payload.status == "FAILED"
        assert payload.failure_reason is not None
        assert payload.failure_reason.startswith("UNSUPPORTED_STOPING_DIRECTION")
        assert "no fallback" in payload.failure_reason
        assert payload.cuts == [] and payload.blocks == [] and payload.sequencing is None


def test_cf_panel_start_order_is_block_order_then_centre_out(
    cf_world: tuple[Scenario, SyntheticWorld], cf_chain: dict[str, Any]
) -> None:
    prod = cf_chain["stopes"]
    level_ids = [lv["levelId"] for lv in cf_chain["levels"]["levels"]]
    # SHALLOW_TO_DEEP: the top interval first
    shallow_first = [f"BLOCK:{lo}-{up}" for up, lo in pairwise(level_ids)]
    assert prod["sequencing"]["blockOrderIds"] == shallow_first
    assert [b["id"] for b in prod["blocks"]] == shallow_first
    assert [b["startOrder"] for b in prod["blocks"]] == list(range(len(shallow_first)))
    # centres −75, −25, 25, 75 → centre-out with the −u tie-break: 1, 2, 0, 3
    centre_out = [1, 2, 0, 3]
    expected = [
        f"PANEL:{bid.removeprefix('BLOCK:')}:P{i:02d}" for bid in shallow_first for i in centre_out
    ]
    assert prod["sequencing"]["panelStartOrder"] == expected
    assert [p["id"] for p in prod["panels"]] == expected
    assert [p["startOrder"] for p in prod["panels"]] == list(range(len(expected)))
    # persisted cuts follow the panel start order, then the panel's own order
    panel_of = [c["panelId"] for c in prod["cuts"]]
    assert panel_of == [pid for pid in expected for _ in range(len(panel_of) // len(expected))]
    for p in prod["panels"]:
        own = [c["id"] for c in prod["cuts"] if c["panelId"] == p["id"]]
        assert own == p["cutIds"]
        keys = [
            (c["liftIndexInBlock"], c["cutIndex"]) for c in prod["cuts"] if c["panelId"] == p["id"]
        ]
        assert keys == sorted(keys)  # lifts bottom → top, cuts in mining order
    # DEEP_TO_SHALLOW reverses the block order and makes no sill mat
    deep = regenerate(cf_world, cf_chain["levels"], blockOrder="DEEP_TO_SHALLOW")
    assert deep.status == "SUCCESS", deep.failure_reason
    assert deep.sequencing is not None
    assert deep.sequencing.block_order_ids == shallow_first[::-1]
    assert all(not b.sill_mat_required for b in deep.blocks)
    assert all(not b.cemented for b in deep.backfills)
    assert deep.metrics is not None and deep.metrics.cemented_backfill_count == 0
    assert deep.sequencing.panel_start_order == [
        f"PANEL:{bid.removeprefix('BLOCK:')}:P{i:02d}"
        for bid in shallow_first[::-1]
        for i in centre_out
    ]
    # the GEOMETRY is identical under both block orders — only the sequencing differs
    assert [c.id for c in deep.cuts] != [c["id"] for c in prod["cuts"]]  # persisted order
    assert {c.id: c.local_bounds.model_dump() for c in deep.cuts} == {
        c["id"]: {
            "u_min": c["localBounds"]["uMin"],
            "u_max": c["localBounds"]["uMax"],
            "v_min": c["localBounds"]["vMin"],
            "v_max": c["localBounds"]["vMax"],
            "w_min": c["localBounds"]["wMin"],
            "w_max": c["localBounds"]["wMax"],
        }
        for c in prod["cuts"]
    }


def test_cf_rib_pillars_are_retained_material_carved_from_the_panels(
    cf_world: tuple[Scenario, SyntheticWorld], cf_chain: dict[str, Any]
) -> None:
    _, world = cf_world
    ob = world.orebody
    assert isinstance(ob, TabularOrebody)
    prod = regenerate(cf_world, cf_chain["levels"], ribPillarWidthM=6.0)
    assert prod.status == "SUCCESS", prod.failure_reason
    n_blocks = len(prod.blocks)
    assert len(prod.rib_pillars) == 3 * n_blocks  # (4 panels − 1) per block
    panels = {p.id: p for p in prod.panels}
    pillar_v = 0.0
    for r in prod.rib_pillars:
        left, right = panels[r.left_panel_id], panels[r.right_panel_id]
        assert left.block_id == right.block_id == r.block_id
        assert right.panel_index == left.panel_index + 1
        # the pillar sits exactly between the two MINED spans and is 6 m wide
        assert abs(r.local_bounds.u_min - left.u_max) < 1e-9
        assert abs(r.local_bounds.u_max - right.u_min) < 1e-9
        assert abs((r.local_bounds.u_max - r.local_bounds.u_min) - 6.0) < 1e-9
        # full block height and thickness
        block = next(b for b in prod.blocks if b.id == r.block_id)
        assert abs(r.local_bounds.v_min - block.v_min) < 1e-9
        assert abs(r.local_bounds.v_max - block.v_max) < 1e-9
        assert r.report.valid and r.report.mesh_closed_solid
        assert r.tonnes_equivalent == pytest.approx(r.geometric_volume_m3 * 2.8)
        assert r.id == f"PILLAR:{r.block_id.removeprefix('BLOCK:')}:R{left.panel_index:02d}"
        pillar_v += r.geometric_volume_m3
    assert prod.rib_pillars
    # mined spans: outer panels lose half a pillar on one side, inner on both
    for p in prod.panels:
        inner = 0 < p.panel_index < 3
        assert p.strike_length == pytest.approx(50.0 - (6.0 if inner else 3.0))
    # cuts + pillars tile the strike extent of every block
    for b in prod.blocks:
        ps = sorted((panels[pid] for pid in b.panel_ids), key=lambda p: p.u_min)
        assert (
            abs(ps[0].u_min + ob.half_length) < 1e-9 and abs(ps[-1].u_max - ob.half_length) < 1e-9
        )
    assert prod.metrics is not None
    assert prod.metrics.rib_pillar_count == len(prod.rib_pillars)
    assert prod.metrics.total_rib_pillar_volume_m3 == pytest.approx(pillar_v)
    assert prod.metrics.total_rib_pillar_tonnes_equivalent == pytest.approx(pillar_v * 2.8)
    # retained material is never a cut, never planned tonnes
    assert not ({r.id for r in prod.rib_pillars} & {c.id for c in prod.cuts})
    assert prod.metrics.total_tonnes == pytest.approx(math.fsum(c.tonnes for c in prod.cuts))
    base = cf_chain["stopes"]["metrics"]["totalGeometricVolumeM3"]
    assert prod.metrics.total_geometric_volume_m3 + pillar_v == pytest.approx(base)
    # a rib wider than the ACTUAL 50 m panel (but < the 60 m target, so the
    # schema accepts it) is a typed generation failure — never clamped
    wide = regenerate(cf_world, cf_chain["levels"], ribPillarWidthM=55.0)
    assert wide.status == "FAILED" and wide.failure_reason is not None
    assert wide.failure_reason.startswith("RIB_PILLAR_TOO_WIDE")
    assert "clamped" in wide.failure_reason


def test_cf_levels_with_another_panel_partition_are_refused(
    cf_world: tuple[Scenario, SyntheticWorld], cf_chain: dict[str, Any]
) -> None:
    """The levels artifact must carry EXACTLY the panel partition's
    accesses: a stale / different partition is a typed failure, never a
    nearest-access guess."""
    levels = cf_chain["levels"]
    # another panel length → the persisted 4 accesses do not match 2 panels
    other = regenerate(cf_world, levels, panelLengthM=100.0)
    assert other.status == "FAILED" and other.failure_reason is not None
    assert "panel" in other.failure_reason
    # a missing panel access on one level
    doc = json.loads(json.dumps(levels))
    victim = next(d for d in doc["developments"] if d["kind"] == "CROSSCUT")
    doc["developments"] = [d for d in doc["developments"] if d["id"] != victim["id"]]
    _, reason = panel_access_by_level(doc, PanelAccessPattern(60.0).offsets(100.0))
    assert reason is not None and victim["levelId"] in reason
    # a Longhole station lattice (negative station index)
    doc = json.loads(json.dumps(levels))
    next(d for d in doc["developments"] if d["kind"] == "CROSSCUT")["stationIndex"] = -1
    _, reason = panel_access_by_level(doc, PanelAccessPattern(60.0).offsets(100.0))
    assert reason is not None and "outside the panel partition" in reason
    # an access that moved away from its panel centre
    doc = json.loads(json.dumps(levels))
    next(d for d in doc["developments"] if d["kind"] == "CROSSCUT")["stationU"] += 0.5
    _, reason = panel_access_by_level(doc, PanelAccessPattern(60.0).offsets(100.0))
    assert reason is not None and "stale panel partition" in reason


@pytest.mark.parametrize(
    ("label", "mutate", "needle"),
    [
        (
            "cut listed by two panels",
            lambda d: d["panels"][1]["cutIds"].append(d["panels"][0]["cutIds"][0]),
            "declared by two panels",
        ),
        (
            "cut names another panel",
            lambda d: d["cuts"][0].__setitem__("panelId", d["panels"][1]["id"]),
            "is not listed by its panel",
        ),
        (
            "cut names another block",
            lambda d: d["cuts"][0].__setitem__("blockId", d["blocks"][1]["id"]),
            "names block",
        ),
        (
            "cemented flag flipped",
            lambda d: d["backfills"][0].__setitem__("cemented", not d["backfills"][0]["cemented"]),
            "cemented=",
        ),
        (
            "panel start order permuted",
            lambda d: d["sequencing"]["panelStartOrder"].reverse(),
            "startOrder disagrees",
        ),
        (
            "block missing from blockOrderIds",
            lambda d: d["sequencing"]["blockOrderIds"].pop(),
            "not a permutation of the blocks",
        ),
        (
            "panel declared by no block",
            lambda d: d["blocks"][0]["panelIds"].pop(),
            "do not partition the panels",
        ),
        (
            "sequencing missing",
            lambda d: d.__setitem__("sequencing", None),
            "no sequencing block",
        ),
    ],
)
def test_cf_structural_integrity_is_verified_not_trusted(
    cf_chain: dict[str, Any], label: str, mutate: Any, needle: str
) -> None:
    doc = json.loads(json.dumps(cf_chain["stopes"]))
    assert cut_fill_integrity(doc) is None
    mutate(doc)
    reason = cut_fill_integrity(doc)
    assert reason is not None and needle in reason, (label, reason)
