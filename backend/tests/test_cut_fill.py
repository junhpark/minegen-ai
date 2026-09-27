"""Phase 21B Cut & Fill acceptance (directive §40: CF-1 … CF-8, CF-12).

CF-9 … CF-11 (schedule) live in ``tests/test_production_timeline.py``.
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
from minegen.mining.methods.contracts import FixedAccessPattern
from minegen.mining.methods.cut_fill import CutFillPlan, generate_cut_fill
from minegen.mining.methods.registry import plan_for
from minegen.mining.methods.solids import MAX_PRODUCTION_SOLIDS, equal_partition
from minegen.mining.models import CutFillPayload, parse_production_payload
from minegen.world.orebody import TabularOrebody
from minegen.world.synthetic_world import SyntheticWorld, generate_world
from tests.conftest import small_scenario
from tests.phase21a_parity_support import canonical, layout_chain, with_method


@pytest.fixture(scope="module")
def cf_world() -> tuple[Scenario, SyntheticWorld]:
    sc = with_method(small_scenario(), MiningMethodType.CUT_AND_FILL)
    return sc, generate_world(sc)


@pytest.fixture(scope="module")
def cf_chain(cf_world: tuple[Scenario, SyntheticWorld]) -> dict[str, Any]:
    sc, world = cf_world
    return layout_chain(sc, world)


def test_cf1_registry_resolves_the_implemented_cut_fill_plan() -> None:
    plan = plan_for(MiningMethodType.CUT_AND_FILL)
    assert isinstance(plan, CutFillPlan) and plan.implementation_status == "IMPLEMENTED"
    sc = with_method(small_scenario(), MiningMethodType.CUT_AND_FILL)
    assert isinstance(sc.mining.method_parameters, CutFillParameters)
    assert isinstance(plan.production_access_pattern(sc), FixedAccessPattern)
    assert plan.production_development(sc).status == "IMPLEMENTED"


def test_cf2_production_development_is_the_backbone_plus_one_central_access(
    cf_chain: dict[str, Any],
) -> None:
    levels = cf_chain["levels"]
    assert levels["status"] == "SUCCESS", levels["failureReason"]
    assert levels["productionDevelopment"] == {
        "method": "CUT_AND_FILL",
        "status": "IMPLEMENTED",
        "reason": None,
    }
    crosscuts = [d for d in levels["developments"] if d["kind"] == "CROSSCUT"]
    drifts = [d for d in levels["developments"] if d["kind"] == "DRIFT"]
    assert len(crosscuts) == len(levels["levels"]) >= 2
    assert all(d["stationIndex"] == 0 and abs(d["stationU"]) < 1e-9 for d in crosscuts)
    assert all(d["id"] == f"CROSSCUT:{d['levelId']}:S+00" for d in crosscuts)
    assert drifts  # the generic footwall backbone is still developed
    m = levels["metrics"]
    assert m["crosscutCount"] == len(levels["levels"])
    assert m["stationsPerLevel"] == 1 and m["stationPitch"] == 0.0
    assert all(lv["crosscutCount"] == 1 for lv in levels["levels"])


def test_cf3_generation_is_deterministic(cf_world: tuple[Scenario, SyntheticWorld]) -> None:
    sc, world = cf_world
    a = layout_chain(sc, world)
    b = layout_chain(sc, world)
    assert canonical(a["stopes"]) == canonical(b["stopes"])
    assert canonical(a["levels"]) == canonical(b["levels"])
    prod = a["stopes"]
    assert prod["status"] == "SUCCESS", prod["failureReason"]
    assert [c["id"] for c in prod["cuts"]] == sorted(
        (c["id"] for c in prod["cuts"]), key=lambda i: [c["id"] for c in prod["cuts"]].index(i)
    )


def test_cf4_lifts_are_ordered_bottom_to_top_in_world_z(
    cf_world: tuple[Scenario, SyntheticWorld], cf_chain: dict[str, Any]
) -> None:
    _, world = cf_world
    ob = world.orebody
    assert isinstance(ob, TabularOrebody)
    prod = cf_chain["stopes"]
    zs = []
    for lift in prod["lifts"]:
        mid = ob.to_world(np.array([[0.0, 0.5 * (lift["vMin"] + lift["vMax"]), 0.0]]))[0]
        zs.append(float(mid[2]))
    assert [lf["liftIndex"] for lf in prod["lifts"]] == list(range(len(prod["lifts"])))
    assert all(b > a for a, b in pairwise(zs)), "lift z must increase"
    # the first lift is the deepest of the deepest interval
    lowest = prod["lifts"][0]
    assert lowest["lowerLevelId"] == cf_chain["levels"]["levels"][-1]["levelId"]
    # cuts reference their lift and the lower level's central access
    by_lift = {lf["liftIndex"]: lf for lf in prod["lifts"]}
    for c in prod["cuts"]:
        lf = by_lift[c["liftIndex"]]
        assert c["id"] in lf["cutIds"]
        assert c["accessDevelopmentId"] == f"CROSSCUT:{c['lowerLevelId']}:S+00"
        assert c["lowerLevelId"] == lf["lowerLevelId"] and c["upperLevelId"] == lf["upperLevelId"]


def test_cf5_equal_partition_leaves_no_gap_overlap_or_residual(
    cf_world: tuple[Scenario, SyntheticWorld], cf_chain: dict[str, Any]
) -> None:
    sc, world = cf_world
    ob = world.orebody
    assert isinstance(ob, TabularOrebody)
    params = sc.mining.method_parameters
    assert isinstance(params, CutFillParameters)
    prod = cf_chain["stopes"]
    for lift in prod["lifts"]:
        cuts = sorted(
            (c for c in prod["cuts"] if c["liftIndex"] == lift["liftIndex"]),
            key=lambda c: c["localBounds"]["uMin"],
        )
        assert abs(cuts[0]["localBounds"]["uMin"] + ob.half_length) < 1e-9
        assert abs(cuts[-1]["localBounds"]["uMax"] - ob.half_length) < 1e-9
        for a, b in pairwise(cuts):
            assert abs(a["localBounds"]["uMax"] - b["localBounds"]["uMin"]) < 1e-9
        lengths = [c["strikeLength"] for c in cuts]
        assert max(lengths) - min(lengths) < 1e-9  # EQUAL partition, no residual
        assert max(lengths) <= params.cut_length_m + 1e-9
        assert min(lengths) > 0.5 * params.cut_length_m
        assert lift["verticalHeight"] <= params.lift_height_m + 1e-9
        assert lift["verticalHeight"] > 0.5 * params.lift_height_m
        # snake: even lifts −u → +u, odd lifts +u → −u
        seq = sorted(
            (c for c in prod["cuts"] if c["liftIndex"] == lift["liftIndex"]),
            key=lambda c: c["cutIndex"],
        )
        us = [c["localBounds"]["uMin"] for c in seq]
        assert us == (sorted(us) if lift["liftIndex"] % 2 == 0 else sorted(us, reverse=True))
    # lifts of one interval are equal partitions too
    for (up, lo), group in {
        (lf["upperLevelId"], lf["lowerLevelId"]): [
            x
            for x in prod["lifts"]
            if (x["upperLevelId"], x["lowerLevelId"]) == (lf["upperLevelId"], lf["lowerLevelId"])
        ]
        for lf in prod["lifts"]
    }.items():
        heights = [g["verticalHeight"] for g in group]
        assert max(heights) - min(heights) < 1e-9, (up, lo)
    assert equal_partition(0.0, 10.0, 4.0) == [
        (0.0, 10.0 / 3),
        (10.0 / 3, 20.0 / 3),
        (20.0 / 3, 10.0),
    ]
    assert equal_partition(0.0, 8.0, 4.0) == [(0.0, 4.0), (4.0, 8.0)]
    assert equal_partition(1.0, 1.0, 4.0) == []


def test_cf6_backfill_is_one_to_one_and_references_the_cut_void(cf_chain: dict[str, Any]) -> None:
    prod = cf_chain["stopes"]
    cuts = {c["id"]: c for c in prod["cuts"]}
    assert len(prod["backfills"]) == len(prod["cuts"]) == prod["metrics"]["cutCount"]
    assert prod["metrics"]["backfillCount"] == len(prod["backfills"])
    seen = set()
    for bf in prod["backfills"]:
        assert bf["sourceCutId"] in cuts and bf["sourceCutId"] not in seen
        seen.add(bf["sourceCutId"])
        assert bf["id"] == "BACKFILL:" + bf["sourceCutId"].removeprefix("CUT:")
        assert bf["volumeM3"] == cuts[bf["sourceCutId"]]["geometricVolumeM3"]
        assert "geometry" not in bf and "vertices" not in bf  # never a second copy


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


def test_cf_complexity_budget_is_a_typed_failure_never_a_decimation(
    cf_world: tuple[Scenario, SyntheticWorld], cf_chain: dict[str, Any]
) -> None:
    sc, world = cf_world
    tiny = sc.model_copy(
        update={
            "mining": MiningConfig.model_validate(
                {
                    **sc.mining.model_dump(by_alias=True, exclude={"method_parameters"}),
                    "methodParameters": {"liftHeightM": 0.05, "cutLengthM": 0.05},
                }
            )
        }
    )
    payload = generate_cut_fill(tiny, world, cf_chain["levels"], None, "rev")  # type: ignore[arg-type]
    assert payload.status == "FAILED" and payload.cuts == []
    assert payload.failure_reason is not None
    assert payload.failure_reason.startswith("PRODUCTION_COMPLEXITY_LIMIT")
    assert str(MAX_PRODUCTION_SOLIDS) in payload.failure_reason


def test_cf_method_parameters_contract() -> None:
    # method alone → canonical defaults, serialized; Longhole never carries the block
    cf = MiningConfig.model_validate({"method": "CUT_AND_FILL"})
    assert cf.model_dump(mode="json", by_alias=True)["methodParameters"] == {
        "kind": "CUT_AND_FILL",
        "liftHeightM": 4.0,
        "cutLengthM": 15.0,
    }
    assert "methodParameters" not in MiningConfig().model_dump(mode="json", by_alias=True)
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
