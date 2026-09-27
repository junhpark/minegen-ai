"""Method-specific SEMANTIC integrity of the persisted production payload
(Phase 21B/C review, blocker 4).

The ``ArtifactReader`` parses ``derived/stopes.json`` STRUCTURALLY (READ ≠
TRUST); the cross-record relations a method's schedule depends on are the
CONSUMER's to verify before it derives anything from them. Every check here
is the same contract the geometry generator persisted and MineExchange
re-verifies on export — evaluated at the entry of ``production_schedule`` so
a corrupted artifact yields a typed FAILED timeline, never a schedule the
plan invented from the surviving half of a relation (a cut whose backfill
record is missing must not receive a BACKFILL task).

Returns a failure reason (``str``) or ``None``; the timeline builder turns
the reason into its typed FAILED payload.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

#: relative agreement of a backfill's persisted volume with its cut's
BACKFILL_VOLUME_REL_TOL = 1e-9

CUT_FILL_TAG = "CUT_AND_FILL production integrity"
ROOM_PILLAR_TAG = "ROOM_AND_PILLAR production integrity"


def _duplicates(ids: list[str]) -> list[str]:
    return sorted(i for i, n in Counter(ids).items() if n > 1)[:3]


def cut_fill_integrity(payload: dict[str, Any]) -> str | None:
    """Cut ids unique, backfill ids unique, exactly one backfill per cut with
    a bijective ``sourceCutId`` map, and every backfill volume equal to its
    cut's geometric volume."""
    cuts: list[dict[str, Any]] = list(payload["cuts"])
    backfills: list[dict[str, Any]] = list(payload["backfills"])
    cut_ids = [str(c["id"]) for c in cuts]
    if dup := _duplicates(cut_ids):
        return f"{CUT_FILL_TAG}: duplicate cut ids {dup}"
    backfill_ids = [str(b["id"]) for b in backfills]
    if dup := _duplicates(backfill_ids):
        return f"{CUT_FILL_TAG}: duplicate backfill ids {dup}"
    if len(backfills) != len(cuts):
        return (
            f"{CUT_FILL_TAG}: {len(cuts)} cuts but {len(backfills)} backfills "
            "(one cut : one backfill)"
        )
    sources = [str(b["sourceCutId"]) for b in backfills]
    if dup := _duplicates(sources):
        return f"{CUT_FILL_TAG}: cuts with two backfills {dup}"
    cut_by_id = {str(c["id"]): c for c in cuts}
    unknown = sorted(s for s in sources if s not in cut_by_id)[:3]
    if unknown:
        return f"{CUT_FILL_TAG}: backfills reference unknown cuts {unknown}"
    missing = sorted(set(cut_by_id) - set(sources))[:3]
    if missing:
        return f"{CUT_FILL_TAG}: cuts without a backfill {missing}"
    for b in backfills:
        cut = cut_by_id[str(b["sourceCutId"])]
        declared = float(cut["geometricVolumeM3"])
        vol = float(b["volumeM3"])
        if not (
            math.isfinite(vol)
            and math.isfinite(declared)
            and math.isclose(vol, declared, rel_tol=BACKFILL_VOLUME_REL_TOL, abs_tol=0.0)
        ):
            return (
                f"{CUT_FILL_TAG}: backfill {b['id']} volume {vol!r} m³ disagrees with its "
                f"cut's geometric volume {declared!r} m³"
            )
    return None


def room_pillar_integrity(payload: dict[str, Any]) -> str | None:
    """Room / extraction-unit / pillar ids unique; ``RoomCell.extractionUnitIds``
    and ``ExtractionUnit.roomId`` agree EXACTLY (every unit in exactly one
    room, every declared member exists, no unit outside a room)."""
    rooms: list[dict[str, Any]] = list(payload["rooms"])
    units: list[dict[str, Any]] = list(payload["extractionUnits"])
    pillars: list[dict[str, Any]] = list(payload["pillars"])
    if dup := _duplicates([str(r["id"]) for r in rooms]):
        return f"{ROOM_PILLAR_TAG}: duplicate room ids {dup}"
    if dup := _duplicates([str(u["id"]) for u in units]):
        return f"{ROOM_PILLAR_TAG}: duplicate extraction unit ids {dup}"
    if dup := _duplicates([str(p["id"]) for p in pillars]):
        return f"{ROOM_PILLAR_TAG}: duplicate pillar ids {dup}"
    unit_ids = {str(u["id"]) for u in units}
    room_ids = {str(r["id"]) for r in rooms}
    # every unit names an existing room
    unknown_rooms = sorted({str(u["roomId"]) for u in units} - room_ids)[:3]
    if unknown_rooms:
        return f"{ROOM_PILLAR_TAG}: extraction units reference unknown rooms {unknown_rooms}"
    # declared membership is a partition of the units
    declared_all = [str(uid) for r in rooms for uid in r["extractionUnitIds"]]
    if dup := _duplicates(declared_all):
        return f"{ROOM_PILLAR_TAG}: extraction units declared by two rooms {dup}"
    dangling = sorted(set(declared_all) - unit_ids)[:3]
    if dangling:
        return f"{ROOM_PILLAR_TAG}: rooms declare missing extraction units {dangling}"
    undeclared = sorted(unit_ids - set(declared_all))[:3]
    if undeclared:
        return f"{ROOM_PILLAR_TAG}: extraction units declared by no room {undeclared}"
    # and the two directions agree unit by unit
    units_by_room: dict[str, set[str]] = {}
    for u in units:
        units_by_room.setdefault(str(u["roomId"]), set()).add(str(u["id"]))
    for r in rooms:
        rid = str(r["id"])
        declared = {str(x) for x in r["extractionUnitIds"]}
        referencing = units_by_room.get(rid, set())
        if declared != referencing:
            return (
                f"{ROOM_PILLAR_TAG}: room {rid} declares {sorted(declared)} but the units "
                f"referencing it are {sorted(referencing)}"
            )
    return None
