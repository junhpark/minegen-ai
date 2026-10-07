"""Phase 21B/C — plan-driven production timeline (Cut & Fill, Room & Pillar).

CF-9  every cut has PREP→STOPING→MUCKING→BACKFILL→CURE, states
      PLANNED→ACTIVE→MINED→VOID→BACKFILLED bound to task boundaries
CF-10 lift precedence: a cut's PREP starts at/after the previous cut's CURE
      end (single conservative chain) and after its production access
CF-11 the method-specific ``production`` block replaces ``stopes`` (empty)
      and the Longhole ``stopes`` payload never carries ``production``
RP-10 pillars are never scheduled (no task, no unit references a pillar)
RP-11 every extraction unit runs PREP→STOPING→MUCKING, states
      PLANNED→ACTIVE→MINED→VOID; HEADING before BENCH within a room
RP-12 single-front order: rooms by Manhattan index distance from the central
      room, then row, then column
Also: the builder never inspects the method (a mismatching payload is refused
through the plan's identity contract), and a missing production access is a
typed failure.

Review blocker 4 — method-specific SEMANTIC integrity is verified at the entry
of ``production_schedule`` (``mining/methods/integrity.py``): a structurally
valid but corrupted artifact (a cut whose backfill record is gone, a duplicate
room id, a room ↔ unit membership mismatch, a backfill volume disagreeing with
its cut) yields a typed FAILED timeline, never a schedule the plan invents.
"""

from __future__ import annotations

import json
from itertools import pairwise
from typing import Any

import pytest

from minegen.core.enums import MiningMethodType, TaskType
from minegen.core.models import MiningConfig, Scenario
from minegen.scheduling.models import TimelinePayload
from minegen.world.synthetic_world import generate_world
from tests.conftest import small_scenario
from tests.phase21a_parity_support import with_method
from tests.phase21bc_baseline_support import layout_full_chain

CF_CHAIN = ("STOPE_PREPARATION", "STOPING", "MUCKING", "BACKFILL", "CURE_BACKFILL")
RP_CHAIN = ("STOPE_PREPARATION", "STOPING", "MUCKING")
_PREFIX = {
    "STOPE_PREPARATION": "PREP",
    "STOPING": "STOPING",
    "MUCKING": "MUCKING",
    "BACKFILL": "BACKFILL",
    "CURE_BACKFILL": "CURE",
}


@pytest.fixture(scope="module")
def cf_case() -> dict[str, Any]:
    sc = with_method(small_scenario(), MiningMethodType.CUT_AND_FILL)
    return layout_full_chain(sc, generate_world(sc))


def _rp_scenario() -> Scenario:
    sc = with_method(small_scenario(), MiningMethodType.ROOM_AND_PILLAR)
    mining = sc.mining.model_dump(by_alias=True, exclude={"method_parameters"})
    # a coarser grid keeps the module fixture fast while exercising benches
    mining["methodParameters"] = {
        "kind": "ROOM_AND_PILLAR",
        "roomWidthM": 12.0,
        "pillarWidthM": 8.0,
        "headingHeightM": 4.0,
        "benchCount": 2,
        "boundaryPillarM": 6.0,
    }
    return sc.model_copy(update={"mining": MiningConfig.model_validate(mining)})


@pytest.fixture(scope="module")
def rp_case() -> dict[str, Any]:
    sc = _rp_scenario()
    return layout_full_chain(sc, generate_world(sc))


def _tasks_by_id(tl: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {t["id"]: t for t in tl["tasks"]}


def _unit_tasks(tl: dict[str, Any], unit_id: str, chain: tuple[str, ...]) -> list[dict[str, Any]]:
    by_id = _tasks_by_id(tl)
    return [by_id[f"TASK:{_PREFIX[k]}:{unit_id}"] for k in chain]


def _dev_task_of(tl: dict[str, Any], edge_id: str) -> dict[str, Any]:
    return next(
        t for t in tl["tasks"] if t["targetKind"] == "DEVELOPMENT" and t["targetId"] == edge_id
    )


# --------------------------------------------------------------------------- #
# Cut & Fill
# --------------------------------------------------------------------------- #


def test_cf9_every_cut_has_the_five_task_chain_and_the_four_state_transitions(
    cf_case: dict[str, Any],
) -> None:
    stopes, tl = cf_case["stopes"], cf_case["timeline"]
    assert stopes["status"] == "SUCCESS" and tl["status"] == "SUCCESS", tl.get("failureReason")
    TimelinePayload.model_validate(tl)  # the payload round-trips through the typed model
    cuts = stopes["cuts"]
    assert cuts
    prod = tl["production"]
    assert prod["method"] == "CUT_AND_FILL" and prod["targetKind"] == "CUT"
    units = {u["unitId"]: u for u in prod["units"]}
    assert set(units) == {c["id"] for c in cuts}
    for c in cuts:
        chain = _unit_tasks(tl, c["id"], CF_CHAIN)
        assert [t["taskType"] for t in chain] == list(CF_CHAIN)
        assert all(t["targetKind"] == "CUT" and t["targetId"] == c["id"] for t in chain)
        _prep, stoping, mucking, backfill, _cure = chain
        # transparent bases: quantity / rate, from the typed schedule config
        assert stoping["basis"]["quantity"] == pytest.approx(c["tonnes"])
        assert stoping["basis"]["quantityUnit"] == "t"
        assert backfill["basis"]["quantity"] == pytest.approx(c["geometricVolumeM3"])
        assert backfill["basis"]["quantityUnit"] == "m3"
        for t in chain:
            assert t["durationDays"] > 0.0
            assert t["endDay"] == pytest.approx(t["startDay"] + t["durationDays"])
        # in-chain precedence
        for a, b in pairwise(chain):
            assert a["id"] in b["dependencies"]
            assert b["startDay"] >= a["endDay"] - 1e-9
        # states bound EXACTLY to task boundaries (rule 84)
        u = units[c["id"]]
        assert u["initialState"] == "PLANNED"
        assert [(tr["state"], tr["day"]) for tr in u["transitions"]] == [
            ("ACTIVE", stoping["startDay"]),
            ("MINED", stoping["endDay"]),
            ("VOID", mucking["endDay"]),
            ("BACKFILLED", backfill["endDay"]),
        ]
    assert tl["metrics"]["productionTaskCount"] == 5 * len(cuts)
    assert tl["metrics"]["productionObjectCount"] == len(cuts)
    assert tl["metrics"]["productionTargetKind"] == "CUT"
    assert tl["metrics"]["stopeTaskCount"] == 0 and tl["metrics"]["stopeObjectCount"] == 0
    assert tl["metrics"]["totalScheduledTonnes"] == pytest.approx(sum(c["tonnes"] for c in cuts))


def _panel_window(tl: dict[str, Any], panel: dict[str, Any]) -> tuple[float, float]:
    """A panel is IN PRODUCTION from its first PREP start to its last CURE end."""
    by_id = _tasks_by_id(tl)
    starts = [by_id[f"TASK:PREP:{cid}"]["startDay"] for cid in panel["cutIds"]]
    ends = [by_id[f"TASK:CURE:{cid}"]["endDay"] for cid in panel["cutIds"]]
    return min(starts), max(ends)


def _max_active_panels(tl: dict[str, Any], panels: list[dict[str, Any]]) -> int:
    """The largest number of panels in production at any instant (windows are
    half-open ``[start, end)``; evaluated at every window boundary)."""
    windows = [_panel_window(tl, p) for p in panels]
    days = sorted({d for w in windows for d in w})
    return max(sum(1 for s, e in windows if s <= d < e) for d in days)


def test_cf10_panel_chains_block_access_and_concurrency_precedence(
    cf_case: dict[str, Any],
) -> None:
    """H2-CF: cuts are serial INSIDE a panel (previous CURE → next PREP),
    every PREP depends on the panel's own access crosscut, panel k + N
    depends on panel k's last CURE (N = maxConcurrentPanels) and there is
    no global previous-cure chain."""
    stopes, tl = cf_case["stopes"], cf_case["timeline"]
    assert tl["status"] == "SUCCESS", tl.get("failureReason")
    seq = stopes["sequencing"]
    n_max = seq["maxConcurrentPanels"]
    assert n_max == 2
    panels = {p["id"]: p for p in stopes["panels"]}
    order = seq["panelStartOrder"]
    last_cure: dict[str, dict[str, Any]] = {}
    for rank, pid in enumerate(order):
        panel = panels[pid]
        access = _dev_task_of(tl, panel["accessDevelopmentId"])
        previous_cure: dict[str, Any] | None = None
        for cid in panel["cutIds"]:
            prep, _, _, _, cure = _unit_tasks(tl, cid, CF_CHAIN)
            assert access["id"] in prep["dependencies"]
            assert prep["startDay"] >= access["endDay"] - 1e-9
            if previous_cure is not None:
                assert previous_cure["id"] in prep["dependencies"]
                assert prep["startDay"] >= previous_cure["endDay"] - 1e-9
            elif rank >= n_max:
                gate = last_cure[order[rank - n_max]]
                assert gate["id"] in prep["dependencies"]
                assert prep["startDay"] >= gate["endDay"] - 1e-9
            previous_cure = cure
        assert previous_cure is not None
        last_cure[pid] = previous_cure
    # no global chain: the first cut of panel 2 (rank 1) does NOT wait for
    # panel 1 (rank 0) — the two start panels overlap in time
    w0, w1 = _panel_window(tl, panels[order[0]]), _panel_window(tl, panels[order[1]])
    assert w1[0] < w0[1] and w0[0] < w1[1]
    first_prep_rank1 = _unit_tasks(tl, panels[order[1]]["cutIds"][0], CF_CHAIN)[0]
    assert not any(d.startswith("TASK:CURE:") for d in first_prep_rank1["dependencies"])
    # lift precedence inside a panel: lift k+1 starts after lift k's last cure
    for panel in panels.values():
        by_lift: dict[int, list[str]] = {}
        for cid in panel["cutIds"]:
            cut = next(c for c in stopes["cuts"] if c["id"] == cid)
            by_lift.setdefault(cut["liftIndexInBlock"], []).append(cid)
        for lo, hi in pairwise(sorted(by_lift)):
            last_cure_lo = max(_unit_tasks(tl, c, CF_CHAIN)[-1]["endDay"] for c in by_lift[lo])
            first_prep_hi = min(_unit_tasks(tl, c, CF_CHAIN)[0]["startDay"] for c in by_lift[hi])
            assert first_prep_hi >= last_cure_lo - 1e-9
    assert tl["metrics"]["firstStopingDay"] == pytest.approx(
        min(_unit_tasks(tl, c["id"], CF_CHAIN)[1]["startDay"] for c in stopes["cuts"])
    )


def test_cf13_active_panels_never_exceed_the_concurrency_bound(cf_case: dict[str, Any]) -> None:
    stopes, tl = cf_case["stopes"], cf_case["timeline"]
    n_max = stopes["sequencing"]["maxConcurrentPanels"]
    observed = _max_active_panels(tl, stopes["panels"])
    assert observed <= n_max
    assert observed == n_max, "the bound must actually be used by the fixture"


def test_cf14_first_production_precedes_ramp_completion_under_shallow_to_deep(
    cf_case: dict[str, Any],
) -> None:
    stopes, tl = cf_case["stopes"], cf_case["timeline"]
    assert stopes["sequencing"]["blockOrder"] == "SHALLOW_TO_DEEP"
    m = tl["metrics"]
    assert m["firstStopingDay"] is not None
    assert m["firstStopingDay"] < m["rampCompletionDay"]
    # the first panel started belongs to the TOP block
    first = stopes["sequencing"]["panelStartOrder"][0]
    top_block = stopes["sequencing"]["blockOrderIds"][0]
    assert next(p for p in stopes["panels"] if p["id"] == first)["blockId"] == top_block
    level_ids = [lv["levelId"] for lv in cf_case["levels"]["levels"]]
    assert top_block == f"BLOCK:{level_ids[1]}-{level_ids[0]}"


def test_cf15_cemented_sill_mats_cure_with_sill_mat_cure_days_and_gate_the_block_below(
    cf_case: dict[str, Any],
) -> None:
    stopes, tl = cf_case["stopes"], cf_case["timeline"]
    sc = with_method(small_scenario(), MiningMethodType.CUT_AND_FILL)
    sill_days = stopes["sequencing"]["sillMatCureDays"]
    assert sill_days == 28.0 and sc.schedule.backfill_cure_days == 7.0
    cuts = {c["id"]: c for c in stopes["cuts"]}
    blocks = {b["id"]: b for b in stopes["blocks"]}
    cemented = {b["sourceCutId"] for b in stopes["backfills"] if b["cemented"]}
    assert cemented
    for c in stopes["cuts"]:
        cure = _unit_tasks(tl, c["id"], CF_CHAIN)[-1]
        expected = sill_days if c["id"] in cemented else sc.schedule.backfill_cure_days
        assert cure["durationDays"] == pytest.approx(expected), c["id"]
        assert cure["basis"]["quantity"] == pytest.approx(expected)
    # vertical precedence: the lower block's TOP lift (same panel index) waits
    # for every cemented sill-mat cure of the block directly above
    panels = {p["id"]: p for p in stopes["panels"]}
    gated = 0
    for lower in blocks.values():
        above = next(
            (b for b in blocks.values() if b["lowerLevelId"] == lower["upperLevelId"]), None
        )
        if above is None:
            continue
        assert above["sillMatRequired"]
        for pid in lower["panelIds"]:
            p_index = panels[pid]["panelIndex"]
            top = max(cuts[c]["liftIndexInBlock"] for c in panels[pid]["cutIds"])
            first_top_cut = next(
                c for c in panels[pid]["cutIds"] if cuts[c]["liftIndexInBlock"] == top
            )
            prep = _unit_tasks(tl, first_top_cut, CF_CHAIN)[0]
            above_panel = next(
                panels[x] for x in above["panelIds"] if panels[x]["panelIndex"] == p_index
            )
            sill_cures = [
                f"TASK:CURE:{c}" for c in above_panel["cutIds"] if cuts[c]["liftIndexInBlock"] == 0
            ]
            assert sill_cures and all(x in prep["dependencies"] for x in sill_cures)
            for x in sill_cures:
                assert prep["startDay"] >= _tasks_by_id(tl)[x]["endDay"] - 1e-9
            gated += 1
    assert gated > 0


def _rebuild(cf_case: dict[str, Any], **params: Any) -> tuple[dict[str, Any], TimelinePayload]:
    """Regenerate production over the SAME levels / network for a parameter
    variant (panel length unchanged → the per-panel accesses stay valid) and
    schedule it."""
    from minegen.mining.methods.cut_fill import generate_cut_fill
    from minegen.scheduling.builder import MineTimelineBuilder
    from tests.test_cut_fill import cf_scenario

    sc = cf_scenario(with_method(small_scenario(), MiningMethodType.CUT_AND_FILL), **params)
    world = generate_world(sc)
    prod = generate_cut_fill(sc, world, cf_case["levels"], None, "rev").model_dump(  # type: ignore[arg-type]
        mode="json", by_alias=True
    )
    assert prod["status"] == "SUCCESS", prod["failureReason"]
    tl = MineTimelineBuilder(sc).build(
        cf_case["network"],
        prod,
        cf_case["ramp"],
        cf_case["levels"],
        "rev",
        accesses_payload=cf_case["accesses"],
    )
    return prod, tl


def test_cf16_deep_to_shallow_gates_a_block_on_the_backfilled_block_below(
    cf_case: dict[str, Any],
) -> None:
    prod, out = _rebuild(cf_case, blockOrder="DEEP_TO_SHALLOW")
    assert out.status == "SUCCESS", out.failure_reason
    tl = out.model_dump(mode="json", by_alias=True)
    assert not any(b["cemented"] for b in prod["backfills"])
    sc = with_method(small_scenario(), MiningMethodType.CUT_AND_FILL)
    for c in prod["cuts"]:
        cure = _unit_tasks(tl, c["id"], CF_CHAIN)[-1]
        assert cure["durationDays"] == pytest.approx(sc.schedule.backfill_cure_days)
    panels = {p["id"]: p for p in prod["panels"]}
    blocks = {b["id"]: b for b in prod["blocks"]}
    cuts = {c["id"]: c for c in prod["cuts"]}
    deepest = prod["sequencing"]["blockOrderIds"][0]
    level_ids = [lv["levelId"] for lv in cf_case["levels"]["levels"]]
    assert deepest == f"BLOCK:{level_ids[-1]}-{level_ids[-2]}"
    gated = 0
    for upper in blocks.values():
        below = next(
            (b for b in blocks.values() if b["upperLevelId"] == upper["lowerLevelId"]), None
        )
        if below is None:
            continue
        for pid in upper["panelIds"]:
            p_index = panels[pid]["panelIndex"]
            first_cut = panels[pid]["cutIds"][0]
            assert cuts[first_cut]["liftIndexInBlock"] == 0
            prep = _unit_tasks(tl, first_cut, CF_CHAIN)[0]
            below_panel = next(
                panels[x] for x in below["panelIds"] if panels[x]["panelIndex"] == p_index
            )
            last_cure = f"TASK:CURE:{below_panel['cutIds'][-1]}"
            assert last_cure in prep["dependencies"]
            assert prep["startDay"] >= _tasks_by_id(tl)[last_cure]["endDay"] - 1e-9
            gated += 1
    assert gated > 0
    # the first panel started belongs to the DEEPEST block: production waits
    # for the ramp to reach the bottom
    assert tl["metrics"]["firstStopingDay"] >= tl["metrics"]["rampCompletionDay"] - 1e-9


def test_cf17_single_concurrent_panel_is_one_serial_front(cf_case: dict[str, Any]) -> None:
    prod, out = _rebuild(cf_case, maxConcurrentPanels=1)
    assert out.status == "SUCCESS", out.failure_reason
    tl = out.model_dump(mode="json", by_alias=True)
    order = prod["sequencing"]["panelStartOrder"]
    panels = {p["id"]: p for p in prod["panels"]}
    assert _max_active_panels(tl, prod["panels"]) == 1
    for prev, nxt in pairwise(order):
        last_cure = f"TASK:CURE:{panels[prev]['cutIds'][-1]}"
        first_prep = _unit_tasks(tl, panels[nxt]["cutIds"][0], CF_CHAIN)[0]
        assert last_cure in first_prep["dependencies"]
    # STOPING windows never overlap anywhere in the mine
    windows = sorted(
        (
            _unit_tasks(tl, c["id"], CF_CHAIN)[1]["startDay"],
            _unit_tasks(tl, c["id"], CF_CHAIN)[1]["endDay"],
        )
        for c in prod["cuts"]
    )
    for (_, e0), (s1, _) in pairwise(windows):
        assert s1 >= e0 - 1e-9


def test_cf18_rib_pillars_are_never_scheduled(cf_case: dict[str, Any]) -> None:
    prod, out = _rebuild(cf_case, ribPillarWidthM=6.0)
    assert out.status == "SUCCESS", out.failure_reason
    tl = out.model_dump(mode="json", by_alias=True)
    pillar_ids = {p["id"] for p in prod["ribPillars"]}
    assert pillar_ids
    assert not any(t["targetId"] in pillar_ids for t in tl["tasks"])
    assert not any(u["unitId"] in pillar_ids for u in tl["production"]["units"])
    assert not any("PILLAR" in t["id"] for t in tl["tasks"])
    assert tl["metrics"]["productionObjectCount"] == len(prod["cuts"])
    assert tl["metrics"]["totalScheduledTonnes"] == pytest.approx(prod["metrics"]["totalTonnes"])


def test_cf19_underhand_payload_is_refused_by_the_schedule_too(cf_case: dict[str, Any]) -> None:
    """READ ≠ TRUST: a persisted payload claiming UNDERHAND sequencing never
    receives an OVERHAND schedule."""
    out = _cf_timeline(
        cf_case, lambda d: d["sequencing"].__setitem__("stopingDirection", "UNDERHAND")
    )
    assert out.status == "FAILED"
    assert (out.failure_reason or "").startswith("UNSUPPORTED_STOPING_DIRECTION")


def test_cf11_production_block_replaces_stopes_and_is_absent_for_longhole(
    cf_case: dict[str, Any],
) -> None:
    tl = cf_case["timeline"]
    assert tl["stopes"] == []
    assert tl["production"]["method"] == "CUT_AND_FILL"
    # the Longhole payload keeps its stopes block and carries NO production
    # block / production metrics keys (byte-compatible with Phase 10)
    sc = small_scenario()
    lh = layout_full_chain(sc, generate_world(sc))
    lt = lh["timeline"]
    assert lt["status"] == "SUCCESS" and lt["stopes"]
    assert "production" not in lt
    assert not any(k.startswith("production") for k in lt["metrics"])
    assert all(t["targetKind"] in ("DEVELOPMENT", "STOPE") for t in lt["tasks"])


def test_cf_missing_production_access_is_a_typed_failure(cf_case: dict[str, Any]) -> None:
    """The builder never guesses an access: a cut referencing a production
    access with no development task fails the timeline explicitly."""
    from minegen.scheduling.builder import MineTimelineBuilder

    sc = with_method(small_scenario(), MiningMethodType.CUT_AND_FILL)
    stopes = json.loads(json.dumps(cf_case["stopes"]))
    victim = stopes["panels"][0]
    victim["accessDevelopmentId"] = "CROSSCUT:L99:S+00"
    for c in stopes["cuts"]:
        if c["panelId"] == victim["id"]:
            c["accessDevelopmentId"] = "CROSSCUT:L99:S+00"
    out = MineTimelineBuilder(sc).build(
        cf_case["network"], stopes, {}, cf_case["levels"], "rev", accesses_payload=None
    )
    assert out.status == "FAILED"
    assert "CROSSCUT:L99:S+00" in (out.failure_reason or "")
    assert "no development task" in (out.failure_reason or "")
    # a cut disagreeing with its panel's access is an integrity defect
    stopes = json.loads(json.dumps(cf_case["stopes"]))
    stopes["cuts"][0]["accessDevelopmentId"] = "CROSSCUT:L99:S+00"
    out = MineTimelineBuilder(sc).build(
        cf_case["network"], stopes, {}, cf_case["levels"], "rev", accesses_payload=None
    )
    assert out.status == "FAILED"
    assert "CUT_AND_FILL production integrity" in (out.failure_reason or "")
    assert "mined from" in (out.failure_reason or "")


def test_builder_refuses_a_payload_of_another_method_through_the_plan(
    cf_case: dict[str, Any],
) -> None:
    """The builder holds no ``if method ==`` branch: a Longhole-shaped payload
    handed to a Cut & Fill scenario is refused by the plan's identity
    contract (a structural KeyError surfaces as no silent schedule)."""
    from minegen.scheduling.builder import MineTimelineBuilder

    sc = with_method(small_scenario(), MiningMethodType.CUT_AND_FILL)
    longhole_shaped = {"status": "SUCCESS", "stopes": [], "method": "LONGHOLE_OPEN_STOPING"}
    with pytest.raises(KeyError):
        MineTimelineBuilder(sc).build(
            cf_case["network"], longhole_shaped, {}, cf_case["levels"], "rev"
        )


# --------------------------------------------------------------------------- #
# Room & Pillar
# --------------------------------------------------------------------------- #


def test_rp10_pillars_are_never_scheduled(rp_case: dict[str, Any]) -> None:
    stopes, tl = rp_case["stopes"], rp_case["timeline"]
    assert stopes["status"] == "SUCCESS" and tl["status"] == "SUCCESS", tl.get("failureReason")
    TimelinePayload.model_validate(tl)
    pillar_ids = {p["id"] for p in stopes["pillars"]}
    assert pillar_ids
    assert not any(t["targetId"] in pillar_ids for t in tl["tasks"])
    assert not any(u["unitId"] in pillar_ids for u in tl["production"]["units"])
    assert not any("PILLAR" in t["id"] for t in tl["tasks"])


def test_rp11_every_extraction_unit_has_the_three_task_chain_and_states(
    rp_case: dict[str, Any],
) -> None:
    stopes, tl = rp_case["stopes"], rp_case["timeline"]
    units_src = stopes["extractionUnits"]
    prod = tl["production"]
    assert prod["method"] == "ROOM_AND_PILLAR" and prod["targetKind"] == "ROOM_EXTRACTION"
    units = {u["unitId"]: u for u in prod["units"]}
    assert set(units) == {u["id"] for u in units_src}
    for u_src in units_src:
        chain = _unit_tasks(tl, u_src["id"], RP_CHAIN)
        assert [t["taskType"] for t in chain] == list(RP_CHAIN)
        assert all(t["targetKind"] == "ROOM_EXTRACTION" for t in chain)
        prep, stoping, mucking = chain
        assert stoping["basis"]["quantity"] == pytest.approx(u_src["tonnes"])
        for a, b in pairwise(chain):
            assert a["id"] in b["dependencies"] and b["startDay"] >= a["endDay"] - 1e-9
        assert [(tr["state"], tr["day"]) for tr in units[u_src["id"]]["transitions"]] == [
            ("ACTIVE", stoping["startDay"]),
            ("MINED", stoping["endDay"]),
            ("VOID", mucking["endDay"]),
        ]
        room = next(r for r in stopes["rooms"] if r["id"] == u_src["roomId"])
        access = _dev_task_of(tl, room["accessDevelopmentId"])
        assert access["id"] in prep["dependencies"]
    # no BACKFILL / CURE tasks exist for Room & Pillar
    assert not any(
        t["taskType"] in (TaskType.BACKFILL.value, TaskType.CURE_BACKFILL.value)
        for t in tl["tasks"]
    )
    # HEADING precedes the benches inside every room
    by_room: dict[str, list[dict[str, Any]]] = {}
    for u_src in units_src:
        by_room.setdefault(u_src["roomId"], []).append(u_src)
    assert any(len(v) > 1 for v in by_room.values()), "fixture must exercise benches"
    for members in by_room.values():
        members.sort(key=lambda u: u["benchIndex"])
        for lo, hi in pairwise(members):
            prep_hi = _unit_tasks(tl, hi["id"], RP_CHAIN)[0]
            muck_lo = _unit_tasks(tl, lo["id"], RP_CHAIN)[2]
            assert muck_lo["id"] in prep_hi["dependencies"]
    assert tl["metrics"]["productionTaskCount"] == 3 * len(units_src)
    assert tl["metrics"]["productionObjectCount"] == len(units_src)
    assert tl["metrics"]["productionTargetKind"] == "ROOM_EXTRACTION"
    assert tl["stopes"] == []


def test_rp12_single_front_order_from_the_central_room(rp_case: dict[str, Any]) -> None:
    stopes, tl = rp_case["stopes"], rp_case["timeline"]
    rooms = stopes["rooms"]

    # central room = the plan cell containing (u, v) = (0, 0) (or nearest)
    def dist(r: dict[str, Any]) -> float:
        b = r["localPlanBounds"]
        return max(0.0, b["uMin"], -b["uMax"]) + max(0.0, b["vMin"], -b["vMax"])

    central = min(rooms, key=lambda r: (dist(r), r["rowIndex"], r["columnIndex"]))
    r0, c0 = central["rowIndex"], central["columnIndex"]
    expected_rooms = sorted(
        rooms,
        key=lambda r: (
            abs(r["rowIndex"] - r0) + abs(r["columnIndex"] - c0),
            r["rowIndex"],
            r["columnIndex"],
        ),
    )
    expected_units: list[str] = []
    for r in expected_rooms:
        members = sorted(
            (u for u in stopes["extractionUnits"] if u["roomId"] == r["id"]),
            key=lambda u: u["benchIndex"],
        )
        expected_units.extend(u["id"] for u in members)
    # the schedule's PREP start order IS the single front
    preps = sorted(
        (t for t in tl["tasks"] if t["taskType"] == "STOPE_PREPARATION"),
        key=lambda t: (t["startDay"], t["id"]),
    )
    assert [t["targetId"] for t in preps] == expected_units
    # the first unit is the central room's HEADING
    assert preps[0]["targetId"].startswith(central["id"])
    assert preps[0]["targetId"].endswith(":HEADING")
    # the front never overlaps: unit k+1 PREP depends on unit k MUCKING
    for a, b in pairwise(expected_units):
        assert f"TASK:MUCKING:{a}" in _unit_tasks(tl, b, RP_CHAIN)[0]["dependencies"]
    # the timeline references geometry by id only (rule 81)
    assert "geometry" not in tl["production"]["units"][0]


# --------------------------------------------------------------------------- #
# review blocker 4: semantic integrity of the persisted production payload
# --------------------------------------------------------------------------- #


def _cf_timeline(cf_case: dict[str, Any], mutate: Any) -> TimelinePayload:
    from minegen.scheduling.builder import MineTimelineBuilder

    sc = with_method(small_scenario(), MiningMethodType.CUT_AND_FILL)
    stopes = json.loads(json.dumps(cf_case["stopes"]))
    mutate(stopes)
    return MineTimelineBuilder(sc).build(
        cf_case["network"],
        stopes,
        cf_case["ramp"],
        cf_case["levels"],
        "rev",
        accesses_payload=cf_case["accesses"],
    )


def _rp_timeline(rp_case: dict[str, Any], mutate: Any) -> TimelinePayload:
    from minegen.scheduling.builder import MineTimelineBuilder

    stopes = json.loads(json.dumps(rp_case["stopes"]))
    mutate(stopes)
    return MineTimelineBuilder(_rp_scenario()).build(
        rp_case["network"],
        stopes,
        rp_case["ramp"],
        rp_case["levels"],
        "rev",
        accesses_payload=rp_case["accesses"],
    )


def test_cf_integrity_missing_backfill_record_fails_instead_of_inventing_a_task(
    cf_case: dict[str, Any],
) -> None:
    """The persisted 1:1 backfill relation is the authority: dropping cut B's
    backfill record must not leave a SUCCESS timeline carrying a BACKFILL
    task for cut B."""
    victim = cf_case["stopes"]["cuts"][1]["id"]

    def drop(doc: dict[str, Any]) -> None:
        doc["backfills"] = [b for b in doc["backfills"] if b["sourceCutId"] != victim]

    out = _cf_timeline(cf_case, drop)
    assert out.status == "FAILED"
    reason = out.failure_reason or ""
    assert "CUT_AND_FILL production integrity" in reason
    assert "one cut : one backfill" in reason or "without a backfill" in reason
    assert not any(t.id == f"TASK:BACKFILL:{victim}" for t in out.tasks)
    # the untouched artifact still schedules
    assert _cf_timeline(cf_case, lambda d: None).status == "SUCCESS"


@pytest.mark.parametrize(
    ("label", "mutate", "needle"),
    [
        (
            "duplicate backfill id",
            lambda d: d["backfills"].__setitem__(
                1, {**d["backfills"][1], "id": d["backfills"][0]["id"]}
            ),
            "duplicate backfill ids",
        ),
        (
            "two backfills for one cut",
            lambda d: d["backfills"].__setitem__(
                1, {**d["backfills"][1], "sourceCutId": d["backfills"][0]["sourceCutId"]}
            ),
            "two backfills",
        ),
        (
            "orphan backfill",
            lambda d: d["backfills"].__setitem__(
                0, {**d["backfills"][0], "sourceCutId": "CUT:NOPE"}
            ),
            "unknown cuts",
        ),
        (
            "backfill volume disagrees with its cut",
            lambda d: d["backfills"].__setitem__(
                0, {**d["backfills"][0], "volumeM3": d["backfills"][0]["volumeM3"] * 1.001}
            ),
            "disagrees with its cut's geometric volume",
        ),
        (
            "duplicate cut id",
            lambda d: d["cuts"].__setitem__(1, {**d["cuts"][1], "id": d["cuts"][0]["id"]}),
            "duplicate",
        ),
    ],
)
def test_cf_integrity_corruptions_are_typed_failures(
    cf_case: dict[str, Any], label: str, mutate: Any, needle: str
) -> None:
    out = _cf_timeline(cf_case, mutate)
    assert out.status == "FAILED", label
    assert needle in (out.failure_reason or ""), (label, out.failure_reason)
    assert out.tasks == [] and out.production is None


def test_rp_integrity_duplicate_room_id_is_never_a_silent_overwrite(
    rp_case: dict[str, Any],
) -> None:
    def dup_room(doc: dict[str, Any]) -> None:
        doc["rooms"][1] = {**doc["rooms"][1], "id": doc["rooms"][0]["id"]}

    out = _rp_timeline(rp_case, dup_room)
    assert out.status == "FAILED"
    assert "ROOM_AND_PILLAR production integrity" in (out.failure_reason or "")
    assert "duplicate room ids" in (out.failure_reason or "")
    assert _rp_timeline(rp_case, lambda d: None).status == "SUCCESS"


@pytest.mark.parametrize(
    ("label", "mutate", "needle"),
    [
        (
            "unit names a room that does not declare it",
            lambda d: d["extractionUnits"].__setitem__(
                0, {**d["extractionUnits"][0], "roomId": d["rooms"][1]["id"]}
            ),
            "declares",
        ),
        (
            "room declares a unit that does not exist",
            lambda d: d["rooms"].__setitem__(
                0,
                {
                    **d["rooms"][0],
                    "extractionUnitIds": [*d["rooms"][0]["extractionUnitIds"], "UNIT:NOPE"],
                },
            ),
            "missing extraction units",
        ),
        (
            "unit of an unknown room",
            lambda d: d["extractionUnits"].__setitem__(
                0, {**d["extractionUnits"][0], "roomId": "ROOM:R999:C999"}
            ),
            "unknown rooms",
        ),
        (
            "duplicate extraction unit id",
            lambda d: d["extractionUnits"].__setitem__(
                1, {**d["extractionUnits"][1], "id": d["extractionUnits"][0]["id"]}
            ),
            "duplicate",
        ),
        (
            "duplicate pillar id",
            lambda d: d["pillars"].__setitem__(1, {**d["pillars"][1], "id": d["pillars"][0]["id"]}),
            "duplicate pillar ids",
        ),
        (
            "room declares a unit twice",
            lambda d: d["rooms"].__setitem__(
                0,
                {
                    **d["rooms"][0],
                    "extractionUnitIds": [
                        *d["rooms"][0]["extractionUnitIds"],
                        d["rooms"][0]["extractionUnitIds"][0],
                    ],
                },
            ),
            "declared by two rooms",
        ),
    ],
)
def test_rp_integrity_corruptions_are_typed_failures(
    rp_case: dict[str, Any], label: str, mutate: Any, needle: str
) -> None:
    out = _rp_timeline(rp_case, mutate)
    assert out.status == "FAILED", label
    assert needle in (out.failure_reason or ""), (label, out.failure_reason)
    assert out.tasks == [] and out.production is None
