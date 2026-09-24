"""Authoritative centerline entities with STABLE ids (never list indices).

Id rule: ``<kind-prefix>:<authoritative id>`` where the prefix is the
lower-case kebab form of the MineGen kind and the remainder is the
artifact's own id::

    ramp:main                     the Effective Ramp (AGGREGATE, one per mine)
    ramp:main:<segmentId>         its segments (layout_v2_selected / decline_smoothed)
    level-access:<levelId>        level_accesses.json accesses[levelId]
    drift:<levelId>               the level drift (AGGREGATE of its pieces)
    drift:<levelId>:<nn>          levels.json development ``DRIFT:<levelId>:<nn>``
    crosscut:<levelId>:<station>  levels.json development ``CROSSCUT:<levelId>:<S±kk>``
    shaft:<shaftId>               shafts.json shafts[shaftId] (AGGREGATE, no geometry)
    shaft:<centerlineId>          shafts.json SHAFT_SEGMENT centerlines (parent shaft:<shaftId>)
    shaft-station-access:<id>     shafts.json STATION_ACCESS centerlines

Aggregates list their authoritative members in ``sourceMemberIds`` (PR #44
correction S1) and never own a polyline of their own. Synthetic aggregates
(``ramp:main``, ``drift:<levelId>``) have no single authoritative id and
carry ``sourceId = null``; the shaft aggregate is an AUTHORITATIVE record
(``shafts.json`` ``shafts[shaftId]``) and carries ``sourceId = shaftId``. A
development id that does not follow the persisted
``<KIND>:<rest>`` convention is a typed ``ExchangeExportError`` (correction
B4), never a KeyError / ValueError escaping the projection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.core.artifacts import LEVEL_ACCESSES_ARTIFACT, LEVELS_ARTIFACT, SHAFTS_ARTIFACT
from minegen.exchange.errors import ExchangeExportError

FloatArray = npt.NDArray[np.float64]

RAMP_ENTITY_ID = "ramp:main"
KIND_PREFIX: dict[str, str] = {
    "RAMP": "ramp",
    "LEVEL_ACCESS": "level-access",
    "DRIFT": "drift",
    "CROSSCUT": "crosscut",
    "SHAFT_SEGMENT": "shaft",
    "STATION_ACCESS": "shaft-station-access",
}
#: the development kinds ``levels.json`` may persist (rule 71 / 180)
LEVEL_DEVELOPMENT_KINDS: frozenset[str] = frozenset({"DRIFT", "CROSSCUT"})


@dataclass(frozen=True)
class CenterlineEntity:
    entity_id: str
    #: RAMP_SEGMENT | LEVEL_ACCESS | DRIFT_PIECE | CROSSCUT | SHAFT_SEGMENT |
    #: SHAFT_STATION_ACCESS
    kind: str
    level_id: str | None
    source_artifact: str
    source_index: int
    source_id: str
    parent_entity_id: str | None
    points: FloatArray  # (N, 3) in authoritative order


@dataclass(frozen=True)
class AggregateEntity:
    """A parent entity with NO geometry of its own (ramp:main, drift:<level>,
    shaft:<shaftId>): identity + authoritative member ids only."""

    entity_id: str
    kind: str  # RAMP | DRIFT | SHAFT
    level_id: str | None
    source_artifact: str
    source_id: str | None  # the authoritative id when one exists (shaftId), else None
    member_source_ids: list[str]


def shaft_aggregate_entity_id(shaft_id: str) -> str:
    return f"shaft:{shaft_id}"


def _pts(flat: Any, what: str) -> FloatArray:
    if not isinstance(flat, list) or len(flat) < 6 or len(flat) % 3 != 0:
        raise ExchangeExportError(
            f"{what}: centerline is missing, has < 2 points or is not a flat "
            "multiple-of-3 coordinate list"
        )
    try:
        pts = np.asarray(flat, dtype=np.float64).reshape(-1, 3)
    except (TypeError, ValueError):
        raise ExchangeExportError(f"{what}: centerline contains non-numeric values") from None
    if not np.all(np.isfinite(pts)):
        raise ExchangeExportError(f"{what}: centerline has non-finite points")
    return pts


def _centerline_points(record: Any, key: str, what: str) -> FloatArray:
    centerline = record.get(key) if isinstance(record, dict) else None
    return _pts(centerline.get("points") if isinstance(centerline, dict) else None, what)


def development_entity_id(development_id: str) -> str:
    """``DRIFT:L01:00`` → ``drift:L01:00``; ``CROSSCUT:L01:S-02`` →
    ``crosscut:L01:S-02`` (kind prefix lower-cased, remainder verbatim).
    Anything else is a typed projection failure."""
    kind, _, rest = development_id.partition(":")
    prefix = KIND_PREFIX.get(kind)
    if prefix is None or not rest:
        raise ExchangeExportError(
            f"unrecognised development id {development_id!r} "
            "(expected <KIND>:<rest> with a known MineGen kind)"
        )
    return f"{prefix}:{rest}"


def ramp_segment_id(segment: dict[str, Any], index: int) -> str:
    return str(segment.get("segmentId") or segment.get("levelId") or f"segment-{index:02d}")


def ramp_centerlines(ramp_payload: dict[str, Any], owning_artifact: str) -> list[CenterlineEntity]:
    out: list[CenterlineEntity] = []
    for i, seg in enumerate(ramp_payload.get("segments", [])):
        sid = ramp_segment_id(seg, i)
        out.append(
            CenterlineEntity(
                entity_id=f"{RAMP_ENTITY_ID}:{sid}",
                kind="RAMP_SEGMENT",
                level_id=seg.get("levelId"),
                source_artifact=owning_artifact,
                source_index=i,
                source_id=sid,
                parent_entity_id=RAMP_ENTITY_ID,
                points=_centerline_points(
                    seg, "effectiveCenterline", f"{owning_artifact} segments[{i}]"
                ),
            )
        )
    return out


def ramp_aggregate(ramp_payload: dict[str, Any], owning_artifact: str) -> AggregateEntity:
    return AggregateEntity(
        entity_id=RAMP_ENTITY_ID,
        kind="RAMP",
        level_id=None,
        source_artifact=owning_artifact,
        source_id=None,
        member_source_ids=[
            ramp_segment_id(s, i) for i, s in enumerate(ramp_payload.get("segments", []))
        ],
    )


def access_centerlines(accesses_payload: dict[str, Any]) -> list[CenterlineEntity]:
    out: list[CenterlineEntity] = []
    for i, a in enumerate(accesses_payload.get("accesses", [])):
        if a.get("status") != "OK" or not a.get("centerline"):
            continue
        level = str(a["levelId"])
        out.append(
            CenterlineEntity(
                entity_id=f"level-access:{level}",
                kind="LEVEL_ACCESS",
                level_id=level,
                source_artifact=LEVEL_ACCESSES_ARTIFACT,
                source_index=i,
                source_id=level,
                parent_entity_id=None,
                points=_centerline_points(
                    a, "centerline", f"{LEVEL_ACCESSES_ARTIFACT} accesses[{i}]"
                ),
            )
        )
    return out


def level_centerlines(levels_payload: dict[str, Any]) -> list[CenterlineEntity]:
    out: list[CenterlineEntity] = []
    for i, d in enumerate(levels_payload.get("developments", [])):
        dev_id = str(d.get("id"))
        kind = str(d.get("kind"))
        if kind not in LEVEL_DEVELOPMENT_KINDS or not dev_id.startswith(f"{kind}:"):
            raise ExchangeExportError(
                f"{LEVELS_ARTIFACT} developments[{i}]: id {dev_id!r} / kind {kind!r} "
                "is not a DRIFT / CROSSCUT development of this artifact"
            )
        level = str(d.get("levelId"))
        out.append(
            CenterlineEntity(
                entity_id=development_entity_id(dev_id),
                kind="DRIFT_PIECE" if kind == "DRIFT" else "CROSSCUT",
                level_id=level,
                source_artifact=LEVELS_ARTIFACT,
                source_index=i,
                source_id=dev_id,
                parent_entity_id=f"drift:{level}" if kind == "DRIFT" else None,
                points=_centerline_points(d, "centerline", f"{LEVELS_ARTIFACT} developments[{i}]"),
            )
        )
    return out


def drift_aggregates(levels_payload: dict[str, Any]) -> list[AggregateEntity]:
    """One ``drift:<levelId>`` aggregate per level that persists DRIFT pieces,
    members in ``fromU`` order (the order the production sweep chains them)."""
    by_level: dict[str, list[dict[str, Any]]] = {}
    for d in levels_payload.get("developments", []):
        if d.get("kind") == "DRIFT":
            by_level.setdefault(str(d.get("levelId")), []).append(d)
    return [
        AggregateEntity(
            entity_id=f"drift:{level}",
            kind="DRIFT",
            level_id=level,
            source_artifact=LEVELS_ARTIFACT,
            source_id=None,
            member_source_ids=[
                str(d["id"]) for d in sorted(pieces, key=lambda d: float(d.get("fromU", 0.0)))
            ],
        )
        for level, pieces in by_level.items()
    ]


def shaft_centerlines(shafts_payload: dict[str, Any]) -> list[CenterlineEntity]:
    out: list[CenterlineEntity] = []
    for i, c in enumerate(shafts_payload.get("centerlines", [])):
        kind = str(c.get("kind"))
        if kind not in ("SHAFT_SEGMENT", "STATION_ACCESS"):
            raise ExchangeExportError(
                f"{SHAFTS_ARTIFACT} centerlines[{i}]: unknown centerline kind {kind!r}"
            )
        prefix = KIND_PREFIX[kind]
        out.append(
            CenterlineEntity(
                entity_id=f"{prefix}:{c['id']}",
                kind="SHAFT_SEGMENT" if kind == "SHAFT_SEGMENT" else "SHAFT_STATION_ACCESS",
                level_id=c.get("levelId"),
                source_artifact=SHAFTS_ARTIFACT,
                source_index=i,
                source_id=str(c["id"]),
                parent_entity_id=(
                    shaft_aggregate_entity_id(str(c["shaftId"]))
                    if kind == "SHAFT_SEGMENT"
                    else None
                ),
                points=_centerline_points(c, "centerline", f"{SHAFTS_ARTIFACT} centerlines[{i}]"),
            )
        )
    return out


def shaft_aggregates(shafts_payload: dict[str, Any]) -> list[AggregateEntity]:
    """One ``shaft:<shaftId>`` aggregate per successful shaft (PR #44
    correction B3): identity + its axis segment ids in collar → bottom order.
    The aggregate owns NO geometry — the segments and station drives are the
    exported centerlines; no shaft solid is invented (centerline-only)."""
    centerlines = shafts_payload.get("centerlines", [])
    out: list[AggregateEntity] = []
    for s in shafts_payload.get("shafts", []):
        if s.get("status") != "OK":
            continue
        members: list[str] = []
        for idx in s.get("segmentIndices", []):
            if not isinstance(idx, int) or idx < 0 or idx >= len(centerlines):
                raise ExchangeExportError(
                    f"{SHAFTS_ARTIFACT} shaft {s.get('shaftId')!r}: segment index {idx!r} "
                    "is not a valid centerlines index"
                )
            members.append(str(centerlines[idx]["id"]))
        out.append(
            AggregateEntity(
                entity_id=shaft_aggregate_entity_id(str(s["shaftId"])),
                kind="SHAFT",
                level_id=None,
                source_artifact=SHAFTS_ARTIFACT,
                source_id=str(s["shaftId"]),
                member_source_ids=members,
            )
        )
    return out


def geometry_ref_index(entities: list[CenterlineEntity]) -> dict[tuple[str, int], str]:
    """``(owning artifact, segmentIndex) → entity id`` — how a MineNetwork
    edge's ``geometryRef`` resolves to an exported centerline."""
    return {(e.source_artifact, e.source_index): e.entity_id for e in entities}
