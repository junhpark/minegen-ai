"""Golden-scenario regression harness.

A core-representation migration (Phase 18: BlockModel → SpatialFieldSet)
cannot be trusted on unit tests alone. This harness runs the complete
TABULAR design pipeline on a FIXED set of deterministic scenarios and
records two kinds of results:

HARD CONTRACT
    Success / failure of every stage and its integer structure (level,
    candidate, segment, development, node, edge, stope and task counts).
    A change here is a regression unless a phase explicitly re-records
    the baseline.

QUALITY / PERFORMANCE METRICS
    Lengths, costs, gradients, radii, fault interaction, poor-rock
    exposure, stope tonnage, grade proxy, runtimes. These are compared
    with tolerances and REPORTED, never required to be byte-identical —
    a later phase may intentionally improve the design. Runtime is
    advisory only.

A deterministic failure (e.g. an ELLIPSOID scenario that the legacy
layout rejects with UNSUPPORTED_OREBODY_FOR_LEGACY_LAYOUT) is itself a
baseline result and is recorded, never discarded.

Everything here consumes the ordinary service layer plus the public
``DesignCostEvaluator.rock_quality`` batch query and the analytic
``FaultPlane`` objects, so the SAME harness runs on both sides of the
migration.
"""

from __future__ import annotations

import csv
import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.core.enums import ScenarioPreset
from minegen.core.models import Scenario
from minegen.design.exposure import (
    DIAGNOSTIC_POOR_ROCK_THRESHOLD as _DIAGNOSTIC_POOR_ROCK_THRESHOLD,
)
from minegen.design.exposure import POLYLINE_SAMPLE_SPACING as _POLYLINE_SAMPLE_SPACING
from minegen.design.exposure import (
    DevelopmentExposure,
    measure_exposure,
    resample_polyline,
)
from minegen.services.design_service import DesignService, UnsupportedOrebodyError
from minegen.services.scenario_realizer import realize_scenario
from minegen.services.scenario_service import ScenarioStore
from minegen.services.world_service import WorldService

FloatArray = npt.NDArray[np.float64]

HARNESS_VERSION = 1

__all__ = [
    "DIAGNOSTIC_POOR_ROCK_THRESHOLD",
    "FULL_SUITE",
    "POLYLINE_SAMPLE_SPACING",
    "SMOKE_KEYS",
    "DevelopmentExposure",
    "GoldenCase",
    "case_by_key",
    "compare_reports",
    "format_comparison",
    "load_report",
    "measure_exposure",
    "resample_polyline",
    "run_case",
    "run_suite",
    "suite",
    "write_report",
]

#: SYNTHETIC diagnostic threshold on the 0–100 synthetic rock-quality field
#: used ONLY to report "development length in poor rock". It is not an RMR
#: class boundary, not a support-design threshold and not a regulatory limit.
#: (Definitions live in ``design/exposure.py`` since Phase 20A; re-exported.)
DIAGNOSTIC_POOR_ROCK_THRESHOLD = _DIAGNOSTIC_POOR_ROCK_THRESHOLD
POLYLINE_SAMPLE_SPACING = _POLYLINE_SAMPLE_SPACING

STAGES = (
    "world",
    "targets",
    "decline",
    "smooth",
    "tunnel",
    "levels",
    "network",
    "stopes",
    "timeline",
)


@dataclass(frozen=True)
class GoldenCase:
    key: str
    preset: ScenarioPreset
    seed: int
    fault_count: int | None = None

    def realize(self) -> Scenario:
        create = realize_scenario(self.preset, self.seed, self.fault_count)
        return Scenario(**create.model_dump())


def _cases() -> list[GoldenCase]:
    baseline = [
        GoldenCase(f"BASELINE-{s}", ScenarioPreset.BASELINE, s) for s in (42, 7, 1234, 2026, 99)
    ]
    tabular_specs = [
        (101, 0),
        (102, 1),
        (103, 2),
        (104, 3),
        (105, 2),
        (106, 1),
        (107, 2),
        (108, 0),
        (109, 3),
        (110, 2),
        (111, 1),
        (112, 2),
    ]
    tabular = [
        GoldenCase(f"RANDOM_TABULAR-{s}", ScenarioPreset.RANDOM_TABULAR, s, n)
        for s, n in tabular_specs
    ]
    # world-only: the legacy layout rejects these deterministically (rule 123)
    ellipsoid = [
        GoldenCase(f"RANDOM_ELLIPSOID-{s}", ScenarioPreset.RANDOM_ELLIPSOID, s, 1)
        for s in (201, 202, 203, 204, 205)
    ]
    return [*baseline, *tabular, *ellipsoid]


FULL_SUITE: tuple[GoldenCase, ...] = tuple(_cases())
#: representative subset that runs inside ordinary CI: the baseline mine, a
#: fast full-pipeline randomized tabular mine with two faults (≈ 80 s; the
#: other tabular seeds take up to 25 min and stay in the explicit full run)
#: and one world-only ellipsoid whose typed legacy-layout rejection is itself
#: a contract
SMOKE_KEYS: tuple[str, ...] = ("BASELINE-42", "RANDOM_TABULAR-107", "RANDOM_ELLIPSOID-201")


def suite(name: str) -> list[GoldenCase]:
    if name == "full":
        return list(FULL_SUITE)
    if name == "smoke":
        return [c for c in FULL_SUITE if c.key in SMOKE_KEYS]
    raise ValueError(f"unknown suite {name!r} (expected 'full' or 'smoke')")


def case_by_key(key: str) -> GoldenCase:
    for c in FULL_SUITE:
        if c.key == key:
            return c
    raise KeyError(key)


# --------------------------------------------------------------------------- #
# Along-development measurements
# --------------------------------------------------------------------------- #


def _polyline(points: list[float]) -> FloatArray:
    return np.asarray(points, dtype=np.float64).reshape(-1, 3)


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #


def _f(v: Any) -> float | None:
    if v is None:
        return None
    x = float(v)
    return x if math.isfinite(x) else None


def _error_code(exc: BaseException) -> str:
    if isinstance(exc, UnsupportedOrebodyError):
        return "UNSUPPORTED_OREBODY_FOR_LEGACY_LAYOUT"
    return f"ERROR:{type(exc).__name__}"


def run_case(case: GoldenCase, root: Path) -> dict[str, Any]:
    """Run the full pipeline for one case against a scenario store rooted at
    ``root``. Never raises for a pipeline failure: failures are recorded."""
    store = ScenarioStore(root)
    worlds = WorldService(store)
    design = DesignService(store, worlds)
    contract: dict[str, Any] = {}
    metrics: dict[str, Any] = {}
    runtime: dict[str, float | None] = {s: None for s in STAGES}
    notes: list[str] = []

    scenario = case.realize()
    sid = store.create(scenario).id
    record: dict[str, Any] = {
        "key": case.key,
        "preset": case.preset.value,
        "seed": case.seed,
        "faultCount": len(scenario.geology.faults),
        "orebodyType": scenario.orebody.orebody_type.value,
        "contract": contract,
        "metrics": metrics,
        "runtime": runtime,
        "notes": notes,
    }
    t_all = time.perf_counter()

    def timed(stage: str, fn: Callable[[], Any]) -> Any:
        t0 = time.perf_counter()
        try:
            return fn()
        finally:
            runtime[stage] = time.perf_counter() - t0

    # -- world -------------------------------------------------------------- #
    try:
        timed("world", lambda: worlds.generate(sid))
        contract["worldGenerated"] = True
    except Exception as exc:  # a failure IS a baseline result
        contract["worldGenerated"] = False
        contract["worldError"] = _error_code(exc)
        notes.append(f"world: {exc}")
        runtime["total"] = time.perf_counter() - t_all
        return record

    # -- targets ------------------------------------------------------------ #
    try:
        targets = timed("targets", lambda: design.generate_targets(sid))
    except Exception as exc:
        contract["targetsStatus"] = _error_code(exc)
        notes.append(f"targets: {exc}")
        runtime["total"] = time.perf_counter() - t_all
        return record
    contract["targetsStatus"] = "SUCCESS"
    contract["targetsLevels"] = int(targets["nLevels"])
    contract["targetsValid"] = int(targets["nValid"])
    contract["targetsRejected"] = int(targets["nRejected"])

    # -- decline ------------------------------------------------------------ #
    try:
        decline = timed("decline", lambda: design.generate_decline(sid))
    except Exception as exc:
        contract["declineStatus"] = _error_code(exc)
        notes.append(f"decline: {exc}")
        runtime["total"] = time.perf_counter() - t_all
        return record
    contract["declineStatus"] = str(decline["status"])
    contract["declineLevels"] = int(decline["nLevels"])
    contract["declineCompletedLevels"] = int(decline["completedLevels"])
    tot = decline["totals"]
    metrics["rawDeclineLength"] = _f(tot["rawLength"])
    metrics["generalizedCost"] = _f(tot["generalizedCost"])
    metrics["expandedStates"] = int(tot["expandedStates"])
    metrics["maxGradient"] = _f(tot["maxGrade"])
    metrics["minimumRadius"] = _f(tot["minimumRadius"])
    if decline["completedLevels"] == 0:
        runtime["total"] = time.perf_counter() - t_all
        return record

    # -- smoothing ---------------------------------------------------------- #
    try:
        smoothed = timed("smooth", lambda: design.generate_smoothed(sid))
    except Exception as exc:
        contract["smoothedStatus"] = _error_code(exc)
        notes.append(f"smooth: {exc}")
        runtime["total"] = time.perf_counter() - t_all
        return record
    contract["smoothedStatus"] = str(smoothed["status"])
    stot = smoothed["totals"]
    contract["smoothedSegments"] = int(stot.get("segments", 0))
    contract["smoothedFallbackSegments"] = int(stot.get("fallbackSegments", 0))
    metrics["effectiveDeclineLength"] = _f(stot.get("effectiveLength"))
    radii = [
        s["report"]["minPlanRadius"]
        for s in smoothed["segments"]
        if s["report"].get("minPlanRadius") is not None
    ]
    grads = [
        s["report"]["maxGradient"]
        for s in smoothed["segments"]
        if s["report"].get("maxGradient") is not None
    ]
    metrics["effectiveMinPlanRadius"] = _f(min(radii)) if radii else None
    metrics["effectiveMaxGradient"] = _f(max(grads)) if grads else None
    if smoothed["status"] == "FAILED":
        runtime["total"] = time.perf_counter() - t_all
        return record
    decline_lines = [_polyline(s["effectiveCenterline"]["points"]) for s in smoothed["segments"]]

    # -- tunnel ------------------------------------------------------------- #
    try:
        tunnel = timed("tunnel", lambda: design.generate_tunnel(sid))
        contract["tunnelStatus"] = str(tunnel["status"])
    except Exception as exc:
        contract["tunnelStatus"] = _error_code(exc)
        notes.append(f"tunnel: {exc}")

    # -- levels ------------------------------------------------------------- #
    level_lines: list[FloatArray] = []
    try:
        levels = timed("levels", lambda: design.generate_levels(sid))
    except Exception as exc:
        contract["levelsStatus"] = _error_code(exc)
        notes.append(f"levels: {exc}")
        levels = None
    if levels is not None:
        contract["levelsStatus"] = levels.status
        if levels.metrics is not None:
            contract["levelsDriftPieces"] = levels.metrics.drift_piece_count
            contract["levelsCrosscuts"] = levels.metrics.crosscut_count
            metrics["totalDriftLength"] = _f(levels.metrics.total_drift_length3d)
            metrics["totalCrosscutLength"] = _f(levels.metrics.total_crosscut_length3d)
        level_lines = [_polyline(d.centerline.points) for d in levels.developments]

    # -- exposure along every development ------------------------------------ #
    _, world, ev = design.evaluator(sid)
    exposure = measure_exposure(decline_lines + level_lines, world.faults, ev.rock_quality)
    metrics["faultCrossings"] = exposure.fault_crossings
    metrics["developmentLengthFaultCore"] = exposure.length_fault_core
    metrics["developmentLengthFaultDamage"] = exposure.length_fault_damage
    metrics["developmentLengthPoorRock"] = exposure.length_poor_rock
    metrics["totalDevelopmentLength"] = exposure.total_length

    if levels is None or levels.status != "SUCCESS":
        runtime["total"] = time.perf_counter() - t_all
        return record

    # -- network ------------------------------------------------------------ #
    try:
        network = timed("network", lambda: design.generate_network(sid))
        contract["networkStatus"] = network.status
        if network.metrics is not None:
            contract["networkNodes"] = network.metrics.node_count
            contract["networkEdges"] = network.metrics.edge_count
        if network.validation is not None:
            contract["networkConnected"] = network.validation.connected
    except Exception as exc:
        contract["networkStatus"] = _error_code(exc)
        notes.append(f"network: {exc}")

    # -- stopes ------------------------------------------------------------- #
    try:
        stopes = timed("stopes", lambda: design.generate_stopes(sid))
        contract["stopesStatus"] = stopes.status
        if stopes.metrics is not None:
            contract["stopeCount"] = stopes.metrics.stope_count
            metrics["plannedStopeTonnes"] = _f(stopes.metrics.total_tonnes)
            metrics["gradeProxy"] = _f(stopes.metrics.weighted_mean_grade_proxy)
    except Exception as exc:
        contract["stopesStatus"] = _error_code(exc)
        notes.append(f"stopes: {exc}")

    # -- timeline ----------------------------------------------------------- #
    if contract.get("networkStatus") == "SUCCESS" and contract.get("stopesStatus") == "SUCCESS":
        try:
            timeline = timed("timeline", lambda: design.generate_timeline(sid))
            contract["timelineStatus"] = timeline.status
            if timeline.metrics is not None:
                contract["timelineTasks"] = timeline.metrics.task_count
                metrics["timelineEndDay"] = _f(timeline.metrics.end_day)
        except Exception as exc:
            contract["timelineStatus"] = _error_code(exc)
            notes.append(f"timeline: {exc}")

    runtime["total"] = time.perf_counter() - t_all
    return record


def run_suite(
    cases: list[GoldenCase],
    root: Path,
    label: str,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    for i, case in enumerate(cases, start=1):
        if on_progress:
            on_progress(f"[{i}/{len(cases)}] {case.key} …")
        rec = run_case(case, root / case.key)
        records.append(rec)
        if on_progress:
            c = rec["contract"]
            on_progress(
                f"    targets={c.get('targetsStatus')} decline={c.get('declineStatus')} "
                f"smooth={c.get('smoothedStatus')} levels={c.get('levelsStatus')} "
                f"stopes={c.get('stopesStatus')} timeline={c.get('timelineStatus')} "
                f"({rec['runtime'].get('total') or 0.0:.1f} s)"
            )
    return {
        "harnessVersion": HARNESS_VERSION,
        "label": label,
        "poorRockThreshold": DIAGNOSTIC_POOR_ROCK_THRESHOLD,
        "poorRockThresholdSemantics": (
            "synthetic diagnostic threshold on the 0-100 synthetic rock-quality "
            "field; not an RMR class, not a regulatory limit"
        ),
        "polylineSampleSpacing": POLYLINE_SAMPLE_SPACING,
        "caseCount": len(records),
        "totalRuntimeSeconds": time.perf_counter() - t0,
        "cases": records,
    }


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #

CONTRACT_COLUMNS = (
    "worldGenerated",
    "worldError",
    "targetsStatus",
    "targetsLevels",
    "targetsValid",
    "targetsRejected",
    "declineStatus",
    "declineLevels",
    "declineCompletedLevels",
    "smoothedStatus",
    "smoothedSegments",
    "smoothedFallbackSegments",
    "tunnelStatus",
    "levelsStatus",
    "levelsDriftPieces",
    "levelsCrosscuts",
    "networkStatus",
    "networkNodes",
    "networkEdges",
    "networkConnected",
    "stopesStatus",
    "stopeCount",
    "timelineStatus",
    "timelineTasks",
)
METRIC_COLUMNS = (
    "rawDeclineLength",
    "generalizedCost",
    "expandedStates",
    "maxGradient",
    "minimumRadius",
    "effectiveDeclineLength",
    "effectiveMinPlanRadius",
    "effectiveMaxGradient",
    "faultCrossings",
    "developmentLengthFaultCore",
    "developmentLengthFaultDamage",
    "developmentLengthPoorRock",
    "totalDriftLength",
    "totalCrosscutLength",
    "totalDevelopmentLength",
    "plannedStopeTonnes",
    "gradeProxy",
    "timelineEndDay",
)


def write_report(report: dict[str, Any], out_dir: Path, name: str) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{name}.json"
    csv_path = out_dir / f"{name}.csv"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    header = [
        "key",
        "preset",
        "seed",
        "faultCount",
        "orebodyType",
        *(f"contract.{c}" for c in CONTRACT_COLUMNS),
        *(f"metric.{m}" for m in METRIC_COLUMNS),
        *(f"runtime.{s}" for s in (*STAGES, "total")),
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for rec in report["cases"]:
            row: list[Any] = [
                rec["key"],
                rec["preset"],
                rec["seed"],
                rec["faultCount"],
                rec["orebodyType"],
            ]
            row += [rec["contract"].get(c) for c in CONTRACT_COLUMNS]
            row += [rec["metrics"].get(m) for m in METRIC_COLUMNS]
            row += [rec["runtime"].get(s) for s in (*STAGES, "total")]
            w.writerow(["" if v is None else v for v in row])
    return json_path, csv_path


def load_report(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


# --------------------------------------------------------------------------- #
# Comparison
# --------------------------------------------------------------------------- #


def _same_number(a: Any, b: Any, rel: float, abs_tol: float) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    if isinstance(a, int | float) and isinstance(b, int | float):
        return math.isclose(float(a), float(b), rel_tol=rel, abs_tol=abs_tol)
    return bool(a == b)


def compare_reports(
    baseline: dict[str, Any],
    current: dict[str, Any],
    expected_metric_changes: set[str] | None = None,
    rel_tol: float = 1e-9,
    abs_tol: float = 1e-9,
) -> dict[str, Any]:
    """Contract fields must match exactly; metrics are reported with deltas.
    ``expected_metric_changes`` names metrics whose change is an intended
    consequence of the phase (e.g. ``gradeProxy`` in Phase 18); they are
    still listed, flagged ``expected``."""
    expected = expected_metric_changes or set()
    base_by = {c["key"]: c for c in baseline["cases"]}
    cur_by = {c["key"]: c for c in current["cases"]}
    regressions: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    for key in sorted(set(base_by) & set(cur_by)):
        b, c = base_by[key], cur_by[key]
        fields = sorted(set(b["contract"]) | set(c["contract"]))
        for f in fields:
            bv, cv = b["contract"].get(f), c["contract"].get(f)
            if not _same_number(bv, cv, 0.0, 0.0):
                regressions.append({"key": key, "field": f, "baseline": bv, "current": cv})
        mfields = sorted(set(b["metrics"]) | set(c["metrics"]))
        for f in mfields:
            bv, cv = b["metrics"].get(f), c["metrics"].get(f)
            if _same_number(bv, cv, rel_tol, abs_tol):
                continue
            entry: dict[str, Any] = {
                "key": key,
                "field": f,
                "baseline": bv,
                "current": cv,
                "expected": f in expected,
            }
            if isinstance(bv, int | float) and isinstance(cv, int | float):
                entry["absDelta"] = float(cv) - float(bv)
                entry["relDelta"] = (
                    (float(cv) - float(bv)) / abs(float(bv)) if float(bv) != 0.0 else None
                )
            changes.append(entry)
    runtime_rows = [
        {
            "key": key,
            "baseline": base_by[key]["runtime"].get("total"),
            "current": cur_by[key]["runtime"].get("total"),
        }
        for key in sorted(set(base_by) & set(cur_by))
    ]
    return {
        "baselineLabel": baseline.get("label"),
        "currentLabel": current.get("label"),
        "missingCases": sorted(set(base_by) - set(cur_by)),
        "newCases": sorted(set(cur_by) - set(base_by)),
        "contractRegressions": regressions,
        "metricChanges": changes,
        "runtimeAdvisory": {
            "baselineTotalSeconds": baseline.get("totalRuntimeSeconds"),
            "currentTotalSeconds": current.get("totalRuntimeSeconds"),
            "perCase": runtime_rows,
        },
        "summary": {
            "comparedCases": len(set(base_by) & set(cur_by)),
            "contractRegressions": len(regressions),
            "metricChanges": len(changes),
            "unexpectedMetricChanges": sum(1 for c in changes if not c["expected"]),
            "expectedMetricChanges": sum(1 for c in changes if c["expected"]),
        },
    }


def format_comparison(cmp: dict[str, Any]) -> str:
    s = cmp["summary"]
    lines = [
        f"# Golden comparison: {cmp['baselineLabel']} → {cmp['currentLabel']}",
        "",
        f"- compared cases: {s['comparedCases']}",
        f"- HARD CONTRACT regressions: {s['contractRegressions']}",
        f"- metric changes: {s['metricChanges']} "
        f"(expected {s['expectedMetricChanges']}, unexpected {s['unexpectedMetricChanges']})",
        f"- missing cases: {cmp['missingCases']}  new cases: {cmp['newCases']}",
        "",
    ]
    if cmp["contractRegressions"]:
        lines.append("## Contract regressions")
        lines.append("")
        lines.append("| case | field | baseline | current |")
        lines.append("| --- | --- | --- | --- |")
        for r in cmp["contractRegressions"]:
            lines.append(f"| {r['key']} | {r['field']} | {r['baseline']} | {r['current']} |")
        lines.append("")
    if cmp["metricChanges"]:
        lines.append("## Metric changes")
        lines.append("")
        lines.append("| case | metric | baseline | current | Δ | rel Δ | expected |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for c in cmp["metricChanges"]:
            rel = c.get("relDelta")
            lines.append(
                f"| {c['key']} | {c['field']} | {c['baseline']} | {c['current']} | "
                f"{c.get('absDelta', '')} | "
                f"{'' if rel is None else f'{rel * 100:+.3f} %'} | "
                f"{'yes' if c['expected'] else 'NO'} |"
            )
        lines.append("")
    ra = cmp["runtimeAdvisory"]
    lines.append("## Runtime (advisory only)")
    lines.append("")
    lines.append(
        f"total: {ra['baselineTotalSeconds']:.1f} s → {ra['currentTotalSeconds']:.1f} s"
        if ra["baselineTotalSeconds"] is not None and ra["currentTotalSeconds"] is not None
        else "total: n/a"
    )
    return "\n".join(lines) + "\n"
