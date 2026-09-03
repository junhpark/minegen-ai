"""Phase 20A — layout-v2 (parametric family search) golden suite.

Companion of the LEGACY golden harness (``golden.py``, which stays
untouched): fixed deterministic scenarios are realized, their world is
generated and the layout-v2 search is run end to end; the winner is then
materialized as the Effective Ramp. Nothing here runs the legacy decline.

HARD CONTRACT (exact): orebody type, clearance basis, required /
serviceable level ids, enumerated candidate count and ids, per-candidate
family, parameters, status and typed failure reasons, served-level counts,
shortlist, ranking order, winner, winner segment count.

QUALITY metrics (tolerance, reported): winner length / drop / max gradient
/ min plan radius / family-signature diagnostics / clearance / scores /
level-connection coordinates and chainages; per-candidate scores and
diagnostics are kept in the JSON for inspection.

RUNTIME (advisory): realize, world, search stages, materialization.

    python -m minegen.regression layout-v2 --label phase20a_layout_v2 --out golden
    python -m minegen.regression layout-v2-compare golden/a.json golden/b.json
"""

from __future__ import annotations

import csv
import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from minegen.core.enums import ScenarioPreset
from minegen.core.models import Scenario
from minegen.layout.search import CandidateStatus, LayoutV2Search, materialize_effective_ramp
from minegen.services.scenario_realizer import ScenarioRealizationError, realize_scenario
from minegen.world.synthetic_world import generate_world

SUITE_VERSION = 1


@dataclass(frozen=True)
class LayoutCase:
    key: str
    preset: ScenarioPreset
    seed: int
    fault_count: int | None = None
    #: dotted-path overrides applied to the realized Scenario (deterministic,
    #: documented per case) — e.g. {"mining.sublevel_interval": 15.0}
    overrides: tuple[tuple[str, float], ...] = field(default_factory=tuple)
    note: str = ""

    def realize(self) -> Scenario:
        create = realize_scenario(self.preset, self.seed, self.fault_count)
        sc = Scenario(**create.model_dump())
        for path, value in self.overrides:
            section, name = path.split(".", 1)
            block = getattr(sc, section).model_copy(update={name: value})
            sc = sc.model_copy(update={section: block})
        return sc


#: mandatory cases (directive §47): the TABULAR reference mine, a fixed-seed
#: WARPED_VEIN (CONSERVATIVE clearance) and a geometry-stress variant of the
#: reference with tight level spacing and a larger minimum turning radius
#: (spiral radius coupling near its limit, short switchback legs)
FULL_SUITE: tuple[LayoutCase, ...] = (
    LayoutCase("TABULAR-REFERENCE", ScenarioPreset.BASELINE, 42, note="Phase 16 baseline mine"),
    LayoutCase(
        "WARPED_VEIN-301",
        ScenarioPreset.RANDOM_WARPED_VEIN,
        301,
        1,
        note="implicit body, CONSERVATIVE clearance",
    ),
    LayoutCase(
        "GEOMETRY-STRESS",
        ScenarioPreset.BASELINE,
        42,
        overrides=(("mining.sublevel_interval", 15.0), ("ramp.min_turn_radius", 20.0)),
        note="15 m levels + R_min 20 m: derived spiral radius and switchback legs near limits",
    ),
    LayoutCase(
        "WARPED_VEIN-307",
        ScenarioPreset.RANDOM_WARPED_VEIN,
        307,
        1,
        note="implicit body where the search honestly finds no feasible candidate",
    ),
)
SMOKE_KEYS: tuple[str, ...] = ("TABULAR-REFERENCE", "WARPED_VEIN-301", "GEOMETRY-STRESS")


def suite(name: str) -> list[LayoutCase]:
    if name == "full":
        return list(FULL_SUITE)
    if name == "smoke":
        return [c for c in FULL_SUITE if c.key in SMOKE_KEYS]
    raise ValueError(f"unknown suite {name!r} (expected 'full' or 'smoke')")


def case_by_key(key: str) -> LayoutCase:
    for c in FULL_SUITE:
        if c.key == key:
            return c
    raise KeyError(key)


def _f(v: Any) -> float | None:
    if v is None:
        return None
    x = float(v)
    return x if math.isfinite(x) else None


def _r(v: Any, nd: int = 6) -> float | None:
    x = _f(v)
    return None if x is None else round(x, nd)


def run_case(case: LayoutCase) -> dict[str, Any]:
    """Never raises for a search outcome: NO_FEASIBLE_CANDIDATE is a result."""
    contract: dict[str, Any] = {"key": case.key}
    metrics: dict[str, Any] = {}
    runtime: dict[str, float] = {}
    notes: list[str] = [case.note] if case.note else []
    candidates_out: list[dict[str, Any]] = []
    t_all = time.perf_counter()
    try:
        t0 = time.perf_counter()
        sc = case.realize()
        runtime["realize"] = time.perf_counter() - t0
        contract["realized"] = True
    except ScenarioRealizationError as exc:
        contract["realized"] = False
        contract["realizationError"] = str(exc)
        runtime["total"] = time.perf_counter() - t_all
        return _record(case, contract, metrics, runtime, notes, candidates_out)
    contract["orebodyType"] = sc.orebody.orebody_type.value
    t0 = time.perf_counter()
    world = generate_world(sc)
    runtime["world"] = time.perf_counter() - t0
    t0 = time.perf_counter()
    search = LayoutV2Search(sc, world)
    res = search.run()
    runtime["search"] = time.perf_counter() - t0
    for k, v in res.performance.items():
        if isinstance(v, float):
            runtime[f"search.{k}"] = v

    contract["clearanceBasis"] = res.clearance_basis
    contract["requiredLevelIds"] = [lv.level_id for lv in res.levels]
    contract["serviceableLevelIds"] = list(res.serviceable_ids)
    contract["requiredLevelCount"] = len(res.levels)
    contract["serviceableLevelCount"] = len(res.serviceable_ids)
    contract["candidateCount"] = len(res.candidates)
    contract["candidateIds"] = [c.candidate_id for c in res.candidates]
    contract["candidateStatuses"] = {c.candidate_id: c.status for c in res.candidates}
    contract["candidateFailureReasons"] = {
        c.candidate_id: list(c.failure_reasons) for c in res.candidates if c.failure_reasons
    }
    contract["servedLevels"] = {
        c.candidate_id: c.served_count for c in res.candidates if c.level_service
    }
    contract["familyCounts"] = {
        f: sum(1 for c in res.candidates if c.params.family.value == f)
        for f in ("SPIRAL", "LONGITUDINAL", "SWITCHBACK")
    }
    contract["feasibleCount"] = sum(
        1 for c in res.candidates if c.status == CandidateStatus.FEASIBLE
    )
    contract["shortlist"] = list(res.shortlist)
    contract["ranking"] = list(res.ranking)
    contract["winnerId"] = res.winner_id
    contract["status"] = "SUCCESS" if res.winner_id else "NO_FEASIBLE_CANDIDATE"
    metrics["requiredLevelElevations"] = [_r(lv.elevation, 6) for lv in res.levels]
    metrics["clearanceErrorBound"] = _r(res.clearance_error_bound)
    metrics["requiredClearance"] = _r(res.required_clearance)
    metrics["accessReach"] = _r(res.access_reach)
    metrics["portal"] = [_r(v) for v in res.portal]

    for c in res.candidates:
        d = c.diagnostics
        s = c.scores
        cl = c.clearance
        candidates_out.append(
            {
                "candidateId": c.candidate_id,
                "family": c.params.family.value,
                "parameters": c.params.to_dict(),
                "status": c.status,
                "stageReached": c.stage_reached,
                "failureReasons": list(c.failure_reasons),
                "rank": c.rank,
                "servedLevels": c.served_count if c.level_service else None,
                "levelConnections": [
                    {
                        "levelId": r.level_id,
                        "served": r.served,
                        "position": (
                            [_r(v) for v in r.connection_position]
                            if r.connection_position is not None
                            else None
                        ),
                        "chainage": _r(r.connection_chainage),
                        "accessDistance": _r(r.access_distance),
                        "unservedReason": r.unserved_reason,
                    }
                    for r in c.level_service
                ],
                "diagnostics": (
                    {
                        "length3d": _r(d.length3d),
                        "verticalDrop": _r(d.vertical_drop),
                        "maxAbsGradient": _r(d.max_abs_gradient),
                        "minPlanRadius": _r(d.min_plan_radius),
                        "cumulativeHeadingChangeDeg": _r(d.cumulative_heading_change_deg),
                        "signedHeadingChangeDeg": _r(d.signed_heading_change_deg),
                        "headingReversalCount": d.heading_reversal_count,
                        "hairpinRunCount": d.hairpin_run_count,
                        "dominantAzimuthsDeg": d.dominant_azimuths_deg,
                        "turnDirectionConsistency": _r(d.turn_direction_consistency),
                    }
                    if d
                    else None
                ),
                "scores": (
                    {
                        "development": _r(s.development),
                        "geology": _r(s.geology),
                        "geometry": _r(s.geometry),
                        "total": _r(s.total),
                    }
                    if s
                    else None
                ),
                "clearance": cl.to_dict() if cl else None,
                "exposure": c.exposure,
            }
        )

    winner = res.candidate(res.winner_id) if res.winner_id else None
    if winner is not None and winner.diagnostics and winner.scores and winner.clearance:
        d = winner.diagnostics
        t0 = time.perf_counter()
        ramp = materialize_effective_ramp(res, winner, search.evaluator, "golden")
        runtime["materialize"] = time.perf_counter() - t0
        contract["winnerFamily"] = winner.params.family.value
        contract["winnerSegments"] = len(ramp["segments"])
        contract["winnerServedLevels"] = winner.served_count
        contract["winnerReversals"] = d.heading_reversal_count
        metrics["winnerLength3d"] = _r(d.length3d)
        metrics["winnerVerticalDrop"] = _r(d.vertical_drop)
        metrics["winnerMaxGradient"] = _r(d.max_abs_gradient)
        metrics["winnerMinPlanRadius"] = _r(d.min_plan_radius)
        metrics["winnerCumulativeHeadingDeg"] = _r(d.cumulative_heading_change_deg)
        metrics["winnerTurnConsistency"] = _r(d.turn_direction_consistency)
        metrics["winnerTotalScore"] = _r(winner.scores.total)
        metrics["winnerDevelopment"] = _r(winner.scores.development)
        metrics["winnerGeology"] = _r(winner.scores.geology)
        metrics["winnerGeometry"] = _r(winner.scores.geometry)
        metrics["winnerConservativeClearance"] = _r(winner.clearance.conservative_minimum)
        metrics["winnerApproximateClearance"] = _r(winner.clearance.approximate_minimum)
        metrics["winnerMeanAccessDistance"] = _r(
            sum(r.access_distance or 0.0 for r in winner.level_service)
            / max(len(winner.level_service), 1)
        )
        metrics["winnerConnectionChainages"] = [
            _r(lc["chainage"]) for lc in ramp["levelConnections"]
        ]
        metrics["winnerConnectionPositions"] = [
            [_r(v) for v in lc["position"]] for lc in ramp["levelConnections"]
        ]
        metrics["winnerFaultCrossings"] = (winner.exposure or {}).get("faultCrossings")
        metrics["winnerLengthFaultCore"] = _r((winner.exposure or {}).get("lengthFaultCore"))
        metrics["winnerLengthPoorRock"] = _r((winner.exposure or {}).get("lengthPoorRock"))
    else:
        contract["winnerFamily"] = None
        contract["winnerSegments"] = 0
        contract["winnerServedLevels"] = 0
        contract["winnerReversals"] = None
    runtime["total"] = time.perf_counter() - t_all
    return _record(case, contract, metrics, runtime, notes, candidates_out)


def _record(
    case: LayoutCase,
    contract: dict[str, Any],
    metrics: dict[str, Any],
    runtime: dict[str, float],
    notes: list[str],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "key": case.key,
        "preset": case.preset.value,
        "seed": case.seed,
        "faultCount": case.fault_count,
        "overrides": [list(o) for o in case.overrides],
        "contract": contract,
        "metrics": metrics,
        "runtime": runtime,
        "notes": notes,
        "candidates": candidates,
    }


def run_suite(cases: list[LayoutCase], label: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    records = [run_case(c) for c in cases]
    return {
        "suiteVersion": SUITE_VERSION,
        "label": label,
        "semantics": (
            "layout-v2 parametric family search over synthetic worlds; candidate "
            "scores are interpretable planning group totals, never an optimality "
            "claim, never a cost estimate; runtimes are advisory"
        ),
        "caseCount": len(records),
        "totalRuntimeSeconds": time.perf_counter() - t0,
        "cases": records,
    }


CONTRACT_COLUMNS = (
    "realized",
    "orebodyType",
    "clearanceBasis",
    "requiredLevelCount",
    "serviceableLevelCount",
    "candidateCount",
    "feasibleCount",
    "status",
    "winnerId",
    "winnerFamily",
    "winnerSegments",
    "winnerServedLevels",
    "winnerReversals",
)
#: exact-compared nested contract members (lists / dicts)
CONTRACT_NESTED = (
    "requiredLevelIds",
    "serviceableLevelIds",
    "candidateIds",
    "candidateStatuses",
    "candidateFailureReasons",
    "servedLevels",
    "familyCounts",
    "shortlist",
    "ranking",
)
METRIC_COLUMNS = (
    "clearanceErrorBound",
    "requiredClearance",
    "winnerLength3d",
    "winnerVerticalDrop",
    "winnerMaxGradient",
    "winnerMinPlanRadius",
    "winnerCumulativeHeadingDeg",
    "winnerTurnConsistency",
    "winnerTotalScore",
    "winnerDevelopment",
    "winnerGeology",
    "winnerGeometry",
    "winnerConservativeClearance",
    "winnerApproximateClearance",
    "winnerMeanAccessDistance",
    "winnerFaultCrossings",
    "winnerLengthFaultCore",
    "winnerLengthPoorRock",
)
METRIC_NESTED = (
    "requiredLevelElevations",
    "portal",
    "winnerConnectionChainages",
    "winnerConnectionPositions",
)
RUNTIME_COLUMNS = ("realize", "world", "search", "materialize", "total")


def write_report(report: dict[str, Any], out_dir: Path, name: str) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{name}.json"
    csv_path = out_dir / f"{name}.csv"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "key",
                *(f"contract.{c}" for c in CONTRACT_COLUMNS),
                *(f"metric.{m}" for m in METRIC_COLUMNS),
                *(f"runtime.{r}" for r in RUNTIME_COLUMNS),
            ]
        )
        for rec in report["cases"]:
            row: list[Any] = [rec["key"]]
            row += [rec["contract"].get(c) for c in CONTRACT_COLUMNS]
            row += [rec["metrics"].get(m) for m in METRIC_COLUMNS]
            row += [rec["runtime"].get(r) for r in RUNTIME_COLUMNS]
            w.writerow(["" if v is None else v for v in row])
    return json_path, csv_path


def load_report(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _flatten(v: Any) -> list[float | None]:
    out: list[float | None] = []
    if isinstance(v, list):
        for x in v:
            out.extend(_flatten(x))
    else:
        out.append(_f(v) if isinstance(v, int | float) else None)
    return out


def _close(a: Any, b: Any, rel: float, abs_tol: float) -> bool:
    fa, fb = _flatten(a), _flatten(b)
    if len(fa) != len(fb):
        return False
    for x, y in zip(fa, fb, strict=True):
        if x is None or y is None:
            if x != y:
                return False
            continue
        if not math.isclose(x, y, rel_tol=rel, abs_tol=abs_tol):
            return False
    return True


def compare_reports(
    baseline: dict[str, Any], current: dict[str, Any], rel: float = 1e-6, abs_tol: float = 1e-6
) -> dict[str, Any]:
    """Exact contract comparison (scalar and nested); metric drift reported
    with tolerance; runtime never compared."""
    base = {c["key"]: c for c in baseline["cases"]}
    cur = {c["key"]: c for c in current["cases"]}
    regressions: list[str] = []
    drifts: list[str] = []
    for key in sorted(set(base) | set(cur)):
        if key not in base or key not in cur:
            regressions.append(f"{key}: present in only one report")
            continue
        bc, cc = base[key]["contract"], cur[key]["contract"]
        for c in (*CONTRACT_COLUMNS, *CONTRACT_NESTED):
            if bc.get(c) != cc.get(c):
                regressions.append(f"{key}.{c}: {bc.get(c)!r} -> {cc.get(c)!r}")
        bm, cm = base[key]["metrics"], cur[key]["metrics"]
        for m in (*METRIC_COLUMNS, *METRIC_NESTED):
            if not _close(bm.get(m), cm.get(m), rel, abs_tol):
                drifts.append(f"{key}.{m}: {bm.get(m)!r} -> {cm.get(m)!r}")
    return {
        "baseline": baseline["label"],
        "current": current["label"],
        "contractRegressions": regressions,
        "metricDrift": drifts,
    }
