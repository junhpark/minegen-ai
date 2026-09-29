"""Shared synthetic MineExchange fixtures (Phase 23B): a TOPOLOGICALLY
CONSISTENT network over the hand-written owning artifacts of
``test_exchange_corrections`` (every edge's end nodes ARE its polyline's end
points, lengths measured from the points, cross-sections present, one RAISE
edge without geometry) and a development-only MineTimeline over that network
(rule 83 chainage fractions, rule 174 start node / direction). Used by the
MineExchange 1.3 timeline tests and by every adapter test — FAST, no layout
search, exported through the REAL exporter."""

from __future__ import annotations

from typing import Any

import numpy as np

from minegen.core.artifacts import LEGACY_RAMP_ARTIFACT, LEVELS_ARTIFACT, SHAFTS_ARTIFACT
from minegen.exchange.builder import ArtifactInput, ExchangeInputs, build_exchange
from minegen.exchange.bundle import write_bundle
from tests.test_exchange_corrections import SyntheticMine, levels_doc, ramp_doc, shafts_doc


def pts(flat: list[float]) -> np.ndarray:
    return np.asarray(flat, dtype=np.float64).reshape(-1, 3)


def polyline_length(points: np.ndarray) -> float:
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


def _node(node_id: str, node_type: str, pos: np.ndarray, level: str | None) -> dict[str, Any]:
    return {"id": node_id, "type": node_type, "position": [float(v) for v in pos], "levelId": level}


def _edge(
    edge_id: str,
    edge_type: str,
    artifact: str | None,
    index: int | None,
    a: str,
    b: str,
    points: np.ndarray | None,
    *,
    orientation: str = "DEVELOPMENT",
    cross_section: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if cross_section is None:
        cross_section = {"width": 5.0, "height": 5.5, "analyticArea": 24.0, "shape": "HORSESHOE"}
    return {
        "id": edge_id,
        "type": edge_type,
        "fromNode": a,
        "toNode": b,
        "geometryRef": None if artifact is None else {"artifact": artifact, "segmentIndex": index},
        "length3d": polyline_length(points) if points is not None else 12.0,
        "orientation": orientation,
        "crossSection": cross_section,
    }


def consistent_network() -> dict[str, Any]:
    ramp = [pts(s["effectiveCenterline"]["points"]) for s in ramp_doc()["segments"]]
    devs = [pts(d["centerline"]["points"]) for d in levels_doc()["developments"]]
    shafts = [pts(c["centerline"]["points"]) for c in shafts_doc()["centerlines"]]
    circular = {"width": 5.0, "height": 5.0, "analyticArea": 19.6, "shape": "CIRCULAR"}
    nodes = [
        _node("PORTAL", "PORTAL", ramp[0][0], None),
        _node("LEVEL_ENTRY:L01", "LEVEL_ENTRY", ramp[0][-1], "L01"),
        _node("LEVEL_ENTRY:L02", "LEVEL_ENTRY", ramp[1][-1], "L02"),
        _node("JUNCTION:L01:A", "JUNCTION", devs[0][0], "L01"),
        _node("JUNCTION:L01:B", "JUNCTION", devs[0][-1], "L01"),
        _node("JUNCTION:L01:C", "JUNCTION", devs[1][-1], "L01"),
        _node("JUNCTION:L01:S+00", "JUNCTION", devs[2][0], "L01"),
        _node("STOPE_ACCESS:L01:S+00", "STOPE_ACCESS", devs[2][-1], "L01"),
        _node("SHAFT_COLLAR:SHAFT-01", "SHAFT_COLLAR", shafts[0][0], None),
        _node("SHAFT_STATION:SHAFT-01:L01", "SHAFT_STATION", shafts[0][-1], "L01"),
        _node("SHAFT_BOTTOM:SHAFT-01", "SHAFT_BOTTOM", shafts[1][-1], None),
    ]
    edges = [
        _edge("RAMP:S01", "RAMP", LEGACY_RAMP_ARTIFACT, 0, "PORTAL", "LEVEL_ENTRY:L01", ramp[0]),
        _edge(
            "RAMP:S02",
            "RAMP",
            LEGACY_RAMP_ARTIFACT,
            1,
            "LEVEL_ENTRY:L01",
            "LEVEL_ENTRY:L02",
            ramp[1],
        ),
        _edge(
            "DRIFT:L01:00", "DRIFT", LEVELS_ARTIFACT, 0, "JUNCTION:L01:A", "JUNCTION:L01:B", devs[0]
        ),
        _edge(
            "DRIFT:L01:01", "DRIFT", LEVELS_ARTIFACT, 1, "JUNCTION:L01:B", "JUNCTION:L01:C", devs[1]
        ),
        _edge(
            "CROSSCUT:L01:S+00",
            "CROSSCUT",
            LEVELS_ARTIFACT,
            2,
            "JUNCTION:L01:S+00",
            "STOPE_ACCESS:L01:S+00",
            devs[2],
        ),
        _edge(
            "SHAFT:SHAFT-01:SEG00",
            "SHAFT",
            SHAFTS_ARTIFACT,
            0,
            "SHAFT_COLLAR:SHAFT-01",
            "SHAFT_STATION:SHAFT-01:L01",
            shafts[0],
            orientation="VERTICAL",
            cross_section=circular,
        ),
        _edge(
            "SHAFT:SHAFT-01:SEG01",
            "SHAFT",
            SHAFTS_ARTIFACT,
            1,
            "SHAFT_STATION:SHAFT-01:L01",
            "SHAFT_BOTTOM:SHAFT-01",
            shafts[1],
            orientation="VERTICAL",
            cross_section=circular,
        ),
        _edge(
            "SHAFT_STATION_ACCESS:SHAFT-01:L01",
            "SHAFT_STATION_ACCESS",
            SHAFTS_ARTIFACT,
            2,
            "SHAFT_STATION:SHAFT-01:L01",
            "STOPE_ACCESS:L01:S+00",
            shafts[2],
        ),
        # the ONE edge type without an owning centerline (rule 184)
        _edge("RAISE:L01:X", "RAISE", None, None, "JUNCTION:L01:C", "LEVEL_ENTRY:L02", None),
    ]
    return {"status": "SUCCESS", "failureReason": None, "nodes": nodes, "edges": edges}


_TASK_TYPE = {
    "RAMP": "DEVELOP_RAMP",
    "LEVEL_ACCESS": "DEVELOP_LEVEL_ACCESS",
    "DRIFT": "DEVELOP_LEVEL",
    "CROSSCUT": "DEVELOP_CROSSCUT",
    "SHAFT": "DEVELOP_SHAFT",
    "SHAFT_STATION_ACCESS": "DEVELOP_SHAFT_STATION_ACCESS",
}


def _points_of(edge: dict[str, Any]) -> np.ndarray:
    ref = edge["geometryRef"]
    owners = {
        LEGACY_RAMP_ARTIFACT: [s["effectiveCenterline"] for s in ramp_doc()["segments"]],
        LEVELS_ARTIFACT: [d["centerline"] for d in levels_doc()["developments"]],
        SHAFTS_ARTIFACT: [c["centerline"] for c in shafts_doc()["centerlines"]],
    }
    return pts(owners[ref["artifact"]][ref["segmentIndex"]]["points"])


def development_timeline(network: dict[str, Any], rate: float = 4.0) -> dict[str, Any]:
    """A development-only MineTimeline over ``network``: one task per edge
    with geometry, chained in edge order, chainage fractions from the owning
    points, start node = fromNode, direction +1."""
    tasks: list[dict[str, Any]] = []
    developments: list[dict[str, Any]] = []
    day = 0.0
    prev: str | None = None
    total_len = 0.0
    for e in network["edges"]:
        if e["geometryRef"] is None:
            continue
        points = _points_of(e)
        seg = np.linalg.norm(np.diff(points, axis=0), axis=1)
        cum = np.concatenate([[0.0], np.cumsum(seg)])
        fractions = (cum / cum[-1]).tolist()
        length = float(cum[-1])
        total_len += length
        duration = length / rate
        task_id = f"TASK:DEVELOP:{e['id']}"
        tasks.append(
            {
                "id": task_id,
                "taskType": _TASK_TYPE[e["type"]],
                "targetKind": "DEVELOPMENT",
                "targetId": e["id"],
                "durationDays": duration,
                "startDay": day,
                "endDay": day + duration,
                "dependencies": [prev] if prev else [],
                "basis": {
                    "quantity": length,
                    "quantityUnit": "m",
                    "rate": rate,
                    "rateUnit": "m/day",
                },
            }
        )
        developments.append(
            {
                "edgeId": e["id"],
                "edgeType": e["type"],
                "geometryRef": dict(e["geometryRef"]),
                "taskId": task_id,
                "initialState": "NOT_BUILT",
                "transitions": [
                    {"day": day, "state": "DEVELOPING"},
                    {"day": day + duration, "state": "ACTIVE"},
                ],
                "progressStartDay": day,
                "progressEndDay": day + duration,
                "pointChainageFractions": fractions,
                "excavationStartNode": e["fromNode"],
                "progressDirection": 1,
            }
        )
        day += duration
        prev = task_id
    return {
        "status": "SUCCESS",
        "failureReason": None,
        "sourceRevision": "r-net",
        "startDay": 0.0,
        "endDay": day,
        "tasks": tasks,
        "developments": developments,
        "stopes": [],
        "metrics": {
            "taskCount": len(tasks),
            "developmentTaskCount": len(tasks),
            "stopeTaskCount": 0,
            "developmentObjectCount": len(developments),
            "stopeObjectCount": 0,
            "totalDevelopmentLength3d": total_len,
            "totalScheduledTonnes": 0.0,
            "rampCompletionDay": tasks[1]["endDay"],
            "firstStopingDay": None,
            "endDay": day,
        },
        "production": None,
    }


def synthetic_bundle(mine: SyntheticMine, *, with_timeline: bool = True, **overrides: Any) -> bytes:
    """The synthetic LEGACY mine exported through the real exporter as ZIP
    bytes (consistent network; a development-only timeline unless disabled)."""
    net = consistent_network()
    kwargs: dict[str, Any] = {"network": ArtifactInput(net, "r-net")}
    if with_timeline:
        kwargs["timeline"] = ArtifactInput(development_timeline(net), "r-tl")
    kwargs.update(overrides)
    inputs: ExchangeInputs = mine.inputs(**kwargs)
    data, _ = write_bundle(build_exchange(inputs))
    return data
