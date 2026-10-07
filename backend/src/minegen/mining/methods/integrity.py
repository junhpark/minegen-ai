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
    a bijective ``sourceCutId`` map, every backfill volume equal to its
    cut's geometric volume; and the H2-CF structure — every cut in exactly
    one panel and one block, every panel in exactly one block, the cemented
    flag exactly on the bottom lift of a sill-mat block, rib pillars disjoint
    from cuts, and the persisted start orders permutations of the panels /
    blocks they order."""
    cuts: list[dict[str, Any]] = list(payload["cuts"])
    backfills: list[dict[str, Any]] = list(payload["backfills"])
    cut_ids = [str(c["id"]) for c in cuts]
    if dup := _duplicates(cut_ids):
        return f"{CUT_FILL_TAG}: duplicate cut ids {dup}"
    structure = _cut_fill_structure(payload, cuts, backfills)
    if structure is not None:
        return structure
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


def _cut_fill_structure(
    payload: dict[str, Any], cuts: list[dict[str, Any]], backfills: list[dict[str, Any]]
) -> str | None:
    """The block / panel / sequencing relations of the H2-CF payload."""
    blocks: list[dict[str, Any]] = list(payload["blocks"])
    panels: list[dict[str, Any]] = list(payload["panels"])
    pillars: list[dict[str, Any]] = list(payload["ribPillars"])
    sequencing = payload.get("sequencing")
    if dup := _duplicates([str(b["id"]) for b in blocks]):
        return f"{CUT_FILL_TAG}: duplicate block ids {dup}"
    if dup := _duplicates([str(p["id"]) for p in panels]):
        return f"{CUT_FILL_TAG}: duplicate panel ids {dup}"
    if dup := _duplicates([str(p["id"]) for p in pillars]):
        return f"{CUT_FILL_TAG}: duplicate rib pillar ids {dup}"
    cut_id_set = {str(c["id"]) for c in cuts}
    if overlap := sorted({str(p["id"]) for p in pillars} & cut_id_set)[:3]:
        return f"{CUT_FILL_TAG}: rib pillar ids collide with cut ids {overlap}"
    block_by_id = {str(b["id"]): b for b in blocks}
    panel_by_id = {str(p["id"]): p for p in panels}
    # panels partition: every panel in exactly one block, declared both ways
    declared_panels = [str(pid) for b in blocks for pid in b["panelIds"]]
    if dup := _duplicates(declared_panels):
        return f"{CUT_FILL_TAG}: panels declared by two blocks {dup}"
    if sorted(declared_panels) != sorted(panel_by_id):
        return f"{CUT_FILL_TAG}: block panelIds do not partition the panels"
    for p in panels:
        if str(p["blockId"]) not in block_by_id:
            return f"{CUT_FILL_TAG}: panel {p['id']} references unknown block {p['blockId']}"
        if str(p["id"]) not in {str(x) for x in block_by_id[str(p["blockId"])]["panelIds"]}:
            return f"{CUT_FILL_TAG}: panel {p['id']} is not listed by its block {p['blockId']}"
    # cuts partition: every cut in exactly one panel and that panel's block
    declared_cuts = [str(cid) for p in panels for cid in p["cutIds"]]
    if dup := _duplicates(declared_cuts):
        return f"{CUT_FILL_TAG}: cuts declared by two panels {dup}"
    if sorted(declared_cuts) != sorted(cut_id_set):
        return f"{CUT_FILL_TAG}: panel cutIds do not partition the cuts"
    for c in cuts:
        panel = panel_by_id.get(str(c["panelId"]))
        if panel is None or str(c["id"]) not in {str(x) for x in panel["cutIds"]}:
            return f"{CUT_FILL_TAG}: cut {c['id']} is not listed by its panel {c['panelId']}"
        if str(panel["blockId"]) != str(c["blockId"]):
            return (
                f"{CUT_FILL_TAG}: cut {c['id']} names block {c['blockId']} but its panel "
                f"belongs to {panel['blockId']}"
            )
    # cemented sill mat: exactly the bottom lift of a sill-mat block
    cut_by_id = {str(c["id"]): c for c in cuts}
    for b in backfills:
        cut = cut_by_id.get(str(b["sourceCutId"]))
        if cut is None:
            continue  # reported by the 1:1 relation check
        block = block_by_id.get(str(cut["blockId"]))
        if block is None:
            return f"{CUT_FILL_TAG}: cut {cut['id']} references unknown block {cut['blockId']}"
        expected = bool(block["sillMatRequired"]) and int(cut["liftIndexInBlock"]) == 0
        if bool(b["cemented"]) != expected:
            return (
                f"{CUT_FILL_TAG}: backfill {b['id']} cemented={b['cemented']!r} but its cut is "
                f"{'the bottom lift of a sill-mat block' if expected else 'not a sill mat'}"
            )
    # rib pillars reference adjacent panels of their block
    for p in pillars:
        for key in ("leftPanelId", "rightPanelId"):
            panel = panel_by_id.get(str(p[key]))
            if panel is None or str(panel["blockId"]) != str(p["blockId"]):
                return f"{CUT_FILL_TAG}: rib pillar {p['id']} {key} is not a panel of its block"
    # sequencing: start orders are permutations consistent with the records
    if sequencing is None:
        return f"{CUT_FILL_TAG}: SUCCESS payload carries no sequencing block"
    order = [str(x) for x in sequencing["panelStartOrder"]]
    if sorted(order) != sorted(panel_by_id) or _duplicates(order):
        return f"{CUT_FILL_TAG}: panelStartOrder is not a permutation of the panels"
    for rank, pid in enumerate(order):
        if int(panel_by_id[pid]["startOrder"]) != rank:
            return f"{CUT_FILL_TAG}: panel {pid} startOrder disagrees with panelStartOrder"
    border = [str(x) for x in sequencing["blockOrderIds"]]
    if sorted(border) != sorted(block_by_id) or _duplicates(border):
        return f"{CUT_FILL_TAG}: blockOrderIds is not a permutation of the blocks"
    for rank, bid in enumerate(border):
        if int(block_by_id[bid]["startOrder"]) != rank:
            return f"{CUT_FILL_TAG}: block {bid} startOrder disagrees with blockOrderIds"
    if int(sequencing["maxConcurrentPanels"]) < 1:
        return f"{CUT_FILL_TAG}: maxConcurrentPanels must be ≥ 1"
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
