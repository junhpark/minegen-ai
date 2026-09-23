"""Authoritative centerline entities with STABLE ids (never list indices).

Id rule: ``<kind-prefix>:<authoritative id>`` where the prefix is the
lower-case kebab form of the MineGen kind and the remainder is the
artifact's own id::

    ramp:main                     the Effective Ramp (one per mine)
    ramp:main:<segmentId>         its segments (layout_v2_selected / decline_smoothed)
    level-access:<levelId>        level_accesses.json accesses[levelId]
    drift:<levelId>               the level drift (chain of pieces)
    drift:<levelId>:<nn>          levels.json development ``DRIFT:<levelId>:<nn>``
    crosscut:<levelId>:<station>  levels.json development ``CROSSCUT:<levelId>:<S±kk>``
    shaft:<centerlineId>          shafts.json SHAFT_SEGMENT centerlines
    shaft-station-access:<id>     shafts.json STATION_ACCESS centerlines
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.core.artifacts import LEVEL_ACCESSES_ARTIFACT, LEVELS_ARTIFACT, SHAFTS_ARTIFACT

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


@dataclass(frozen=True)
class CenterlineEntity:
    entity_id: str
    kind: str  # RAMP_SEGMENT | LEVEL_ACCESS | DRIFT_PIECE | CROSSCUT | SHAFT | SHAFT_STATION_ACCESS
    level_id: str | None
    source_artifact: str
    source_index: int
    source_id: str
    parent_entity_id: str | None
    points: FloatArray  # (N, 3) in authoritative order


def _pts(flat: list[float]) -> FloatArray:
    return np.asarray(flat, dtype=np.float64).reshape(-1, 3)


def development_entity_id(development_id: str) -> str:
    """``DRIFT:L01:00`` → ``drift:L01:00``; ``CROSSCUT:L01:S-02`` →
    ``crosscut:L01:S-02`` (kind prefix lower-cased, remainder verbatim)."""
    kind, _, rest = development_id.partition(":")
    prefix = KIND_PREFIX.get(kind)
    if prefix is None or not rest:
        raise ValueError(f"unrecognised development id {development_id!r}")
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
                points=_pts(seg["effectiveCenterline"]["points"]),
            )
        )
    return out


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
                points=_pts(a["centerline"]["points"]),
            )
        )
    return out


def level_centerlines(levels_payload: dict[str, Any]) -> list[CenterlineEntity]:
    out: list[CenterlineEntity] = []
    for i, d in enumerate(levels_payload.get("developments", [])):
        dev_id = str(d["id"])
        kind = str(d["kind"])
        level = str(d["levelId"])
        out.append(
            CenterlineEntity(
                entity_id=development_entity_id(dev_id),
                kind="DRIFT_PIECE" if kind == "DRIFT" else "CROSSCUT",
                level_id=level,
                source_artifact=LEVELS_ARTIFACT,
                source_index=i,
                source_id=dev_id,
                parent_entity_id=f"drift:{level}" if kind == "DRIFT" else None,
                points=_pts(d["centerline"]["points"]),
            )
        )
    return out


def shaft_centerlines(shafts_payload: dict[str, Any]) -> list[CenterlineEntity]:
    out: list[CenterlineEntity] = []
    for i, c in enumerate(shafts_payload.get("centerlines", [])):
        kind = str(c["kind"])
        prefix = KIND_PREFIX[kind]
        out.append(
            CenterlineEntity(
                entity_id=f"{prefix}:{c['id']}",
                kind="SHAFT" if kind == "SHAFT_SEGMENT" else "SHAFT_STATION_ACCESS",
                level_id=c.get("levelId"),
                source_artifact=SHAFTS_ARTIFACT,
                source_index=i,
                source_id=str(c["id"]),
                parent_entity_id=f"shaft:{c['shaftId']}" if kind == "SHAFT_SEGMENT" else None,
                points=_pts(c["centerline"]["points"]),
            )
        )
    return out


def geometry_ref_index(entities: list[CenterlineEntity]) -> dict[tuple[str, int], str]:
    """``(owning artifact, segmentIndex) → entity id`` — how a MineNetwork
    edge's ``geometryRef`` resolves to an exported centerline."""
    return {(e.source_artifact, e.source_index): e.entity_id for e in entities}
