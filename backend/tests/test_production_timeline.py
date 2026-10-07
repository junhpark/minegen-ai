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


def test_cf10_single_conservative_chain_lift_precedence_and_access_dependency(
    cf_case: dict[str, Any],
) -> None:
    stopes, tl = cf_case["stopes"], cf_case["timeline"]
    cuts = stopes["cuts"]
    previous_cure: dict[str, Any] | None = None
    for c in cuts:
        prep, _, _, _, cure = _unit_tasks(tl, c["id"], CF_CHAIN)
        access = _dev_task_of(tl, c["accessDevelopmentId"])
        assert access["id"] in prep["dependencies"]
        assert prep["startDay"] >= access["endDay"] - 1e-9
        if previous_cure is not None:
            assert previous_cure["id"] in prep["dependencies"]
            assert prep["startDay"] >= previous_cure["endDay"] - 1e-9
        previous_cure = cure
    # lift precedence follows from the chain: inside a panel every cut of lift
    # k+1 starts after the last cure of lift k (persisted order is the panel
    # start order, then the panel's lifts bottom → top)
    lifts = stopes["lifts"]
    assert len(lifts) >= 2
    by_lift: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for c in cuts:
        by_lift.setdefault((c["panelId"], c["liftIndex"]), []).append(c)
    ordered = sorted(by_lift, key=lambda k: min(cuts.index(c) for c in by_lift[k]))
    for lo, hi in pairwise(ordered):
        last_cure_lo = max(_unit_tasks(tl, c["id"], CF_CHAIN)[-1]["endDay"] for c in by_lift[lo])
        first_prep_hi = min(_unit_tasks(tl, c["id"], CF_CHAIN)[0]["startDay"] for c in by_lift[hi])
        assert first_prep_hi >= last_cure_lo - 1e-9
    # exactly one cut is worked at a time: STOPING windows never overlap
    windows = sorted(
        (
            _unit_tasks(tl, c["id"], CF_CHAIN)[1]["startDay"],
            _unit_tasks(tl, c["id"], CF_CHAIN)[1]["endDay"],
        )
        for c in cuts
    )
    for (_, e0), (s1, _) in pairwise(windows):
        assert s1 >= e0 - 1e-9
    assert tl["metrics"]["firstStopingDay"] == pytest.approx(windows[0][0])


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
    stopes = {**cf_case["stopes"], "cuts": [dict(c) for c in cf_case["stopes"]["cuts"]]}
    stopes["cuts"][0]["accessDevelopmentId"] = "CROSSCUT:L99:S+00"
    out = MineTimelineBuilder(sc).build(
        cf_case["network"], stopes, {}, cf_case["levels"], "rev", accesses_payload=None
    )
    assert out.status == "FAILED"
    assert "CROSSCUT:L99:S+00" in (out.failure_reason or "")
    assert "no development task" in (out.failure_reason or "")


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
