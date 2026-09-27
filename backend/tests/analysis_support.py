"""Hand-built, hand-checkable sources for the Phase 22A/B analysis tests.

ONE small mine whose every quantity is a round number, so the expected
lengths, volumes, tonnes, costs, bucket allocations and NPV are computed
independently in the tests (directive §60–64: hand-calculated fixtures).

    edges   RAMP:1  P→J1   100 m × 20 m²   RAMP:2  J1→R  50 m × 20 m²
            LEVEL_ACCESS:L01  J1→E1  30 m × 20 m²
            DRIFT:L01  E1→X1  40 m × 16 m²   CROSSCUT:L01:0  X1→S1  10 m × 16 m²
    totals  230 m, 4 400 m³ gross
    stopes  STOPE:A 1 000 t / 400 m³ / grade 4.0   STOPE:B 3 000 t / 1 200 m³ / 2.0
    tasks   development 0–45 d, production 45–120 d (see ``timeline_doc``)
"""

from __future__ import annotations

import copy
from typing import Any

from minegen.analysis.builder import AnalysisInputs, SourceRead
from minegen.analysis.economics import EconomicsConfig
from minegen.core.enums import EdgeType, MiningMethodType
from minegen.core.models import Scenario, ScenarioCreate
from minegen.mining.models import parse_production_payload
from minegen.network.models import NetworkPayload
from minegen.scheduling.models import TimelinePayload

REV = "rev-analysis-support"

EDGES: list[tuple[str, str, str, str, float, float]] = [
    ("RAMP:1", "RAMP", "P", "J1", 100.0, 20.0),
    ("RAMP:2", "RAMP", "J1", "R", 50.0, 20.0),
    ("LEVEL_ACCESS:L01", "LEVEL_ACCESS", "J1", "E1", 30.0, 20.0),
    ("DRIFT:L01", "DRIFT", "E1", "X1", 40.0, 16.0),
    ("CROSSCUT:L01:0", "CROSSCUT", "X1", "S1", 10.0, 16.0),
]
NODES: list[tuple[str, str]] = [
    ("P", "PORTAL"),
    ("J1", "RAMP_JUNCTION"),
    ("R", "RAMP_END"),
    ("E1", "LEVEL_ENTRY"),
    ("X1", "JUNCTION"),
    ("S1", "STOPE_ACCESS"),
]
#: development task windows (days)
DEV_WINDOWS: dict[str, tuple[float, float]] = {
    "RAMP:1": (0.0, 20.0),
    "RAMP:2": (20.0, 30.0),
    "LEVEL_ACCESS:L01": (20.0, 30.0),
    "DRIFT:L01": (30.0, 40.0),
    "CROSSCUT:L01:0": (40.0, 45.0),
}
DEV_TASK_TYPE = {
    "RAMP": "DEVELOP_RAMP",
    "LEVEL_ACCESS": "DEVELOP_LEVEL_ACCESS",
    "DRIFT": "DEVELOP_LEVEL",
    "CROSSCUT": "DEVELOP_CROSSCUT",
}
STOPES: list[tuple[str, float, float, float]] = [
    ("STOPE:A", 1000.0, 400.0, 4.0),
    ("STOPE:B", 3000.0, 1200.0, 2.0),
]
#: (PREP, STOPING, MUCKING, BACKFILL, CURE) windows per stope
PROD_WINDOWS: dict[str, list[tuple[float, float]]] = {
    "STOPE:A": [(45.0, 50.0), (50.0, 60.0), (60.0, 70.0), (70.0, 75.0), (75.0, 80.0)],
    "STOPE:B": [(70.0, 75.0), (75.0, 90.0), (90.0, 100.0), (100.0, 110.0), (110.0, 120.0)],
}
END_DAY = 120.0


def scenario(method: MiningMethodType = MiningMethodType.LONGHOLE_OPEN_STOPING) -> Scenario:
    sc = Scenario(**ScenarioCreate(name="analysis-support").model_dump())
    return sc.model_copy(update={"mining": sc.mining.model_copy(update={"method": method})})


def network_doc() -> dict[str, Any]:
    by_type = {t: [e for e in EDGES if e[1] == t.value] for t in EdgeType}
    nodes = [
        {"id": nid, "type": ntype, "position": [float(i), 0.0, -float(i)]}
        for i, (nid, ntype) in enumerate(NODES)
    ]
    edges = [
        {
            "id": eid,
            "type": etype,
            "fromNode": a,
            "toNode": b,
            "length3d": length,
            "meanGradientSigned": -0.1,
            "maxAbsGradient": 0.1,
            "crossSection": {"width": 5.0, "height": 5.0, "analyticArea": area},
            "effectiveSource": "PARAMETRIC_V2",
            "fieldCost": length,
            "geometryRef": {"artifact": "layout_v2_selected.json", "segmentIndex": i},
            "simulation": {},
        }
        for i, (eid, etype, a, b, length, area) in enumerate(EDGES)
    ]
    metrics = {
        "nodeCount": len(nodes),
        "edgeCount": len(edges),
        "levelCount": 1,
        "junctionCount": 1,
        "rampJunctionCount": 1,
        "levelAccessEdgeCount": len(by_type[EdgeType.LEVEL_ACCESS]),
        "totalLevelAccessLength3d": sum(e[4] for e in by_type[EdgeType.LEVEL_ACCESS]),
        "stopeAccessCount": 1,
        "driftEdgeCount": len(by_type[EdgeType.DRIFT]),
        "crosscutEdgeCount": len(by_type[EdgeType.CROSSCUT]),
        "totalRampLength3d": sum(e[4] for e in by_type[EdgeType.RAMP]),
        "totalDriftLength3d": sum(e[4] for e in by_type[EdgeType.DRIFT]),
        "totalCrosscutLength3d": sum(e[4] for e in by_type[EdgeType.CROSSCUT]),
        "minimumElevation": -5.0,
        "verticalDropFromPortal": 5.0,
    }
    return {
        "status": "SUCCESS",
        "failureReason": None,
        "sourceRevision": REV,
        "nodes": nodes,
        "edges": edges,
        "metrics": metrics,
        "validation": {
            "maxNodeSyncError": 0.0,
            "syncTolerance": 1e-6,
            "synchronized": True,
            "connected": True,
            "connectedComponents": 1,
        },
        "surfacePathAdvisory": [],
    }


def _stope(sid: str, tonnes: float, volume: float, grade: float) -> dict[str, Any]:
    return {
        "id": sid,
        "method": "LONGHOLE_OPEN_STOPING",
        "stationIndex": 0,
        "stationU": 0.0,
        "upperLevelId": "L01",
        "lowerLevelId": "L02",
        "upperAccessNodeId": "S1",
        "lowerAccessNodeId": "S2",
        "localBounds": {"uMin": 0, "uMax": 1, "vMin": 0, "vMax": 1, "wMin": 0, "wMax": 1},
        "geometry": {"vertices": [0.0] * 24, "triangleIndices": [0] * 36},
        "strikeLength": 10.0,
        "downDipSpan": 10.0,
        "verticalHeight": 10.0,
        "thickness": 4.0,
        "geometricVolumeM3": volume,
        "tonnes": tonnes,
        "meanGradeProxy": grade,
        "report": {
            "upperAnchorError": 0.0,
            "lowerAnchorError": 0.0,
            "hardInvalidSamples": 0,
            "finite": True,
            "valid": True,
        },
    }


def stopes_doc() -> dict[str, Any]:
    return {
        "status": "SUCCESS",
        "failureReason": None,
        "sourceRevision": REV,
        "method": "LONGHOLE_OPEN_STOPING",
        "stopes": [_stope(*s) for s in STOPES],
        "metrics": {
            "stopeCount": len(STOPES),
            "levelIntervalCount": 1,
            "stationsPerInterval": 2,
            "totalGeometricVolumeM3": sum(s[2] for s in STOPES),
            "totalTonnes": sum(s[1] for s in STOPES),
            "geometricExtractionFractionOfOrebody": 0.5,
            "weightedMeanGradeProxy": 2.5,
        },
    }


def _task(
    tid: str,
    ttype: str,
    kind: str,
    target: str,
    window: tuple[float, float],
    quantity: float,
    unit: str,
    deps: list[str],
) -> dict[str, Any]:
    start, end = window
    return {
        "id": tid,
        "taskType": ttype,
        "targetKind": kind,
        "targetId": target,
        "durationDays": end - start,
        "startDay": start,
        "endDay": end,
        "dependencies": deps,
        "basis": {
            "quantity": quantity,
            "quantityUnit": unit,
            "rate": 1.0,
            "rateUnit": f"{unit}/day",
        },
    }


def timeline_doc() -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    for eid, etype, _a, _b, length, _area in EDGES:
        tasks.append(
            _task(
                f"TASK:DEVELOP:{eid}",
                DEV_TASK_TYPE[etype],
                "DEVELOPMENT",
                eid,
                DEV_WINDOWS[eid],
                length,
                "m",
                [],
            )
        )
    chain = ("PREP", "STOPING", "MUCKING", "BACKFILL", "CURE")
    types = ("STOPE_PREPARATION", "STOPING", "MUCKING", "BACKFILL", "CURE_BACKFILL")
    for sid, tonnes, volume, _grade in STOPES:
        windows = PROD_WINDOWS[sid]
        quantities = [5.0, tonnes, tonnes, volume, 5.0]
        units = ["day", "t", "t", "m3", "day"]
        prev: list[str] = ["TASK:DEVELOP:CROSSCUT:L01:0"]
        for name, ttype, window, q, unit in zip(
            chain, types, windows, quantities, units, strict=True
        ):
            tid = f"TASK:{name}:{sid}"
            tasks.append(_task(tid, ttype, "STOPE", sid, window, q, unit, prev))
            prev = [tid]
    stoping_starts = [t["startDay"] for t in tasks if t["taskType"] == "STOPING"]
    dev = [t for t in tasks if t["targetKind"] == "DEVELOPMENT"]
    return {
        "status": "SUCCESS",
        "failureReason": None,
        "sourceRevision": REV,
        "startDay": 0.0,
        "endDay": END_DAY,
        "tasks": tasks,
        "developments": [],
        "stopes": [],
        "metrics": {
            "taskCount": len(tasks),
            "developmentTaskCount": len(dev),
            "stopeTaskCount": len(tasks) - len(dev),
            "developmentObjectCount": len(dev),
            "stopeObjectCount": len(STOPES),
            "totalDevelopmentLength3d": sum(e[4] for e in EDGES),
            "totalScheduledTonnes": sum(s[1] for s in STOPES),
            "rampCompletionDay": 30.0,
            "firstStopingDay": min(stoping_starts),
            "endDay": END_DAY,
        },
    }


def config_doc() -> dict[str, Any]:
    """Round rates: dev 10/8/6/5 per m (shaft 0), Longhole 2/t, processing
    1/t, backfill 0.5/m³, fixed 10/day, capex 500, revenue 5/t, 10 %."""
    return {
        "version": 1,
        "currencyCode": "USD",
        "developmentCosts": {
            "rampPerM": 10.0,
            "levelAccessPerM": 8.0,
            "driftPerM": 6.0,
            "crosscutPerM": 5.0,
            "shaftPerM": 0.0,
            "shaftStationAccessPerM": 0.0,
        },
        "productionCosts": {
            "longholeOpenStopingPerTonne": 2.0,
            "cutAndFillPerTonne": 3.0,
            "roomAndPillarPerTonne": 4.0,
        },
        "processingCostPerTonne": 1.0,
        "backfillCostPerM3": 0.5,
        "fixedOperatingCostPerDay": 10.0,
        "grossRevenuePerMinedTonne": 5.0,
        "initialCapitalCost": 500.0,
        "annualDiscountRate": 0.1,
        "cashflowBucketDays": 30.0,
    }


def source(doc: dict[str, Any], parse: Any, revision: str) -> SourceRead:
    return SourceRead(model=parse(doc), raw=copy.deepcopy(doc), revision=revision)


def inputs(
    *,
    network: dict[str, Any] | None = None,
    stopes: dict[str, Any] | None = None,
    timeline: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    world_generated: bool = True,
    method: MiningMethodType = MiningMethodType.LONGHOLE_OPEN_STOPING,
    with_network: bool = True,
    with_stopes: bool = True,
    with_timeline: bool = True,
) -> AnalysisInputs:
    """The default is the COMPLETE consistent mine with the round config;
    pass a document to replace one source, ``with_* = False`` to drop it."""
    net = network if network is not None else network_doc()
    st = stopes if stopes is not None else stopes_doc()
    tl = timeline if timeline is not None else timeline_doc()
    cfg = EconomicsConfig.model_validate(config if config is not None else config_doc())
    return AnalysisInputs(
        scenario=scenario(method),
        scenario_revision="scenario-rev",
        world_generated=world_generated,
        network=source(net, NetworkPayload.model_validate, "net-rev") if with_network else None,
        production=source(st, parse_production_payload, "prod-rev") if with_stopes else None,
        timeline=source(tl, TimelinePayload.model_validate, "tl-rev") if with_timeline else None,
        economics=cfg if config is not None or config is None else None,
        economics_revision="eco-rev",
    )


def inputs_without_config(**kw: Any) -> AnalysisInputs:
    base = inputs(**kw)
    return AnalysisInputs(
        scenario=base.scenario,
        scenario_revision=base.scenario_revision,
        world_generated=base.world_generated,
        network=base.network,
        production=base.production,
        timeline=base.timeline,
        economics=None,
        economics_revision=None,
    )
