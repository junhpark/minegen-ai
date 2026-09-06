"""Phase 20A/20B — layout-v2 (parametric family search + level access) golden suite.

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
from minegen.layout.search import (
    CandidateStatus,
    LayoutV2Search,
    materialize_effective_ramp,
    materialize_level_accesses,
)
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
    #: documented per case) — e.g. ("mining.sublevel_interval", 15.0) or
    #: ("layout.access.maximum_access_length", 20.0)
    overrides: tuple[tuple[str, Any], ...] = field(default_factory=tuple)
    note: str = ""

    def realize(self) -> Scenario:
        create = realize_scenario(self.preset, self.seed, self.fault_count)
        raw = create.model_dump()
        for path, value in self.overrides:
            node: dict[str, Any] = raw
            *parents, leaf = path.split(".")
            for key in parents:
                node = node[key]
            node[leaf] = value
        return Scenario(**raw)


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
    # Phase 20B mandatory cases (directive §23)
    LayoutCase(
        "ACCESS-INFEASIBLE",
        ScenarioPreset.BASELINE,
        42,
        overrides=(
            ("layout.access.maximum_access_length", 16.0),
            ("layout.access.minimum_access_length", 15.0),
        ),
        note="deliberate access infeasibility: no branch can fit the 15-16 m length window",
    ),
    LayoutCase(
        "CUT_AND_FILL",
        ScenarioPreset.BASELINE,
        42,
        overrides=(("mining.method", "CUT_AND_FILL"),),
        note="generic ramp junctions + level accesses for a reserved production method",
    ),
    # closeout v3 §3.F: the same-RL direct reach (a heuristic) is exceeded on
    # the deeper levels of the irregular body, yet explicit ramp junctions +
    # graded level accesses exist → stage 4 SUCCESS. Under the Phase 20A/20B
    # hard reach gate this case had no feasible candidate.
    LayoutCase(
        "IRREGULAR-REACH-EXCEEDED",
        ScenarioPreset.RANDOM_WARPED_VEIN,
        301,
        1,
        overrides=(("layout.access_reach", 30.0),),
        note="direct same-RL reach exceeded (heuristic only); explicit level accesses feasible",
    ),
)
SMOKE_KEYS: tuple[str, ...] = (
    "TABULAR-REFERENCE",
    "WARPED_VEIN-301",
    "IRREGULAR-REACH-EXCEEDED",
    "GEOMETRY-STRESS",
    "ACCESS-INFEASIBLE",
    "CUT_AND_FILL",
)


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
    contract["screenedLevels"] = {
        c.candidate_id: c.screened_count for c in res.candidates if c.level_service
    }
    contract["accessibleLevels"] = {
        c.candidate_id: c.accessible_count for c in res.candidates if c.accessible_count is not None
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
    contract["cheapFeasibleCount"] = int(res.performance.get("cheapFeasibleCount", 0))
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
                "screenedLevels": c.screened_count if c.level_service else None,
                "accessibleLevels": c.accessible_count,
                "access": c.access_plan.summary() if c.access_plan else None,
                "rampLevelReferences": [
                    {
                        "levelId": r.level_id,
                        "withinReach": r.within_reach,
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
                "accessScreen": (
                    {
                        "blockedCount": c.access_screen["blockedCount"],
                        "blockedLevelIds": list(c.access_screen["blockedLevelIds"]),
                        "reasons": {
                            k: v["reason"]
                            for k, v in c.access_screen["levels"].items()
                            if v["blocked"]
                        },
                    }
                    if c.access_screen is not None
                    else None
                ),
            }
        )

    winner = res.candidate(res.winner_id) if res.winner_id else None
    if winner is not None and winner.diagnostics and winner.scores and winner.clearance:
        d = winner.diagnostics
        t0 = time.perf_counter()
        ramp = materialize_effective_ramp(res, winner, search.evaluator, "golden")
        accesses = materialize_level_accesses(res, winner, "golden", sc.mining.method.value)
        runtime["materialize"] = time.perf_counter() - t0
        plan = winner.access_plan
        assert plan is not None
        summary = plan.summary()
        contract["winnerFamily"] = winner.params.family.value
        contract["winnerSegments"] = len(ramp["segments"])
        contract["winnerAccessibleLevels"] = winner.accessible_count
        contract["winnerReversals"] = d.heading_reversal_count
        contract["winnerJunctionLevels"] = [j["levelId"] for j in ramp["rampJunctions"]]
        contract["winnerAccessConnectors"] = [a.connector_word for a in plan.accesses]
        contract["winnerAccessFailures"] = summary["failures"]
        contract["miningMethod"] = sc.mining.method.value
        contract["winnerPreferredAccessSource"] = summary["preferredAccessSource"]
        contract["winnerReachExceededLevels"] = [
            r.level_id for r in winner.level_service if not r.within_reach
        ]
        metrics["winnerPreferredAccessLength"] = _r(summary["effectivePreferredAccessLength"])
        metrics["winnerMeanAbsDeviationFromPreferred"] = _r(
            summary["meanAbsDeviationFromPreferred"]
        )
        metrics["winnerAccessDeviations"] = [_r(a.length_deviation) for a in plan.accesses]
        metrics["winnerTotalAccessLength"] = _r(summary["totalAccessLength"])
        metrics["winnerWorstAccessLength"] = _r(summary["worstAccessLength"])
        metrics["winnerMaxAccessGradient"] = _r(summary["maxAccessGradient"])
        metrics["winnerMinAccessPlanRadius"] = _r(summary["minAccessPlanRadius"])
        metrics["winnerJunctionChainages"] = [_r(j["chainage"]) for j in ramp["rampJunctions"]]
        metrics["winnerJunctionPositions"] = [
            [_r(v) for v in j["position"]] for j in ramp["rampJunctions"]
        ]
        metrics["winnerLevelEntries"] = [
            [_r(v) for v in a["levelEntry"]] if a["levelEntry"] else None
            for a in accesses["accesses"]
        ]
        metrics["winnerAccessLengths"] = [_r(a.length3d) for a in plan.accesses]
        # Phase 20B.2-A one-turn CS observability (per level, winner)
        metrics["winnerAccessTerminalHeadingMismatchDeg"] = [
            _r(a.terminal_heading_mismatch_deg) for a in plan.accesses
        ]
        metrics["winnerAccessTurnoutArcLengths"] = [_r(a.turnout_arc_length) for a in plan.accesses]
        metrics["winnerAccessStraightLengths"] = [_r(a.straight_length) for a in plan.accesses]
        metrics["winnerAccessPathToChordRatios"] = [
            _r(a.path_to_chord_ratio) for a in plan.accesses
        ]
        metrics["winnerAccessGradients"] = [_r(a.max_gradient) for a in plan.accesses]
        # Phase 20B.1 O-1/O-2 separation observability (per level, winner)
        metrics["winnerAccessPlanSeparations"] = [
            _r(a.junction_to_entry_plan_sep) for a in plan.accesses
        ]
        metrics["winnerAccessDist3d"] = [_r(a.junction_to_entry_dist3d) for a in plan.accesses]
        metrics["winnerExcavationSeparations"] = [
            _r(a.excavation_separation) for a in plan.accesses
        ]
        metrics["winnerTurnoutHeadingChangesDeg"] = [
            _r(a.turnout_heading_change_deg) for a in plan.accesses
        ]
        metrics["winnerLength3d"] = _r(d.length3d)
        metrics["winnerVerticalDrop"] = _r(d.vertical_drop)
        metrics["winnerMaxGradient"] = _r(d.max_abs_gradient)
        metrics["winnerMinPlanRadius"] = _r(d.min_plan_radius)
        metrics["winnerCumulativeHeadingDeg"] = _r(d.cumulative_heading_change_deg)
        metrics["winnerMeanCurvatureRadPerM"] = _r(
            math.radians(d.cumulative_heading_change_deg) / max(d.length3d, 1e-9)
        )
        metrics["winnerHairpinRuns"] = d.hairpin_run_count
        metrics["winnerEquivalentHalfTurns"] = _r(
            math.radians(d.cumulative_heading_change_deg) / math.pi
        )
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
        metrics["winnerReferenceChainages"] = [
            _r(lc["chainage"]) for lc in ramp["rampLevelReferences"]
        ]
        metrics["winnerFaultCrossings"] = (winner.exposure or {}).get("faultCrossings")
        metrics["winnerLengthFaultCore"] = _r((winner.exposure or {}).get("lengthFaultCore"))
        metrics["winnerLengthPoorRock"] = _r((winner.exposure or {}).get("lengthPoorRock"))
    else:
        contract["winnerFamily"] = None
        contract["winnerSegments"] = 0
        contract["winnerAccessibleLevels"] = None
        contract["winnerReversals"] = None
        contract["winnerJunctionLevels"] = []
        contract["winnerAccessConnectors"] = []
        contract["winnerAccessFailures"] = {}
        contract["miningMethod"] = sc.mining.method.value
        contract["winnerPreferredAccessSource"] = None
        contract["winnerReachExceededLevels"] = []
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
    "winnerAccessibleLevels",
    "winnerReversals",
    "miningMethod",
    "cheapFeasibleCount",
    "winnerPreferredAccessSource",
)
#: exact-compared nested contract members (lists / dicts)
CONTRACT_NESTED = (
    "winnerReachExceededLevels",
    "requiredLevelIds",
    "serviceableLevelIds",
    "candidateIds",
    "candidateStatuses",
    "candidateFailureReasons",
    "screenedLevels",
    "accessibleLevels",
    "familyCounts",
    "shortlist",
    "ranking",
    "winnerJunctionLevels",
    "winnerAccessConnectors",
    "winnerAccessFailures",
)
METRIC_COLUMNS = (
    "clearanceErrorBound",
    "requiredClearance",
    "winnerLength3d",
    "winnerVerticalDrop",
    "winnerMaxGradient",
    "winnerMinPlanRadius",
    "winnerCumulativeHeadingDeg",
    "winnerMeanCurvatureRadPerM",
    "winnerHairpinRuns",
    "winnerEquivalentHalfTurns",
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
    "winnerTotalAccessLength",
    "winnerWorstAccessLength",
    "winnerMaxAccessGradient",
    "winnerMinAccessPlanRadius",
    "winnerPreferredAccessLength",
    "winnerMeanAbsDeviationFromPreferred",
)
METRIC_NESTED = (
    "winnerAccessDeviations",
    "requiredLevelElevations",
    "portal",
    "winnerReferenceChainages",
    "winnerJunctionChainages",
    "winnerJunctionPositions",
    "winnerLevelEntries",
    "winnerAccessLengths",
    "winnerAccessGradients",
    # Phase 20B.1 O: separation observability (added fields; their first
    # appearance against an older baseline reports as drift "None -> values")
    "winnerAccessPlanSeparations",
    "winnerAccessDist3d",
    "winnerExcavationSeparations",
    "winnerTurnoutHeadingChangesDeg",
)
RUNTIME_COLUMNS = ("realize", "world", "search", "materialize", "total")


def audit_shortlist(cases: list[LayoutCase], label: str) -> dict[str, Any]:
    """Closeout v3 §3.E shortlist-starvation audit (diagnostic, never part
    of the production search): the normal bounded-shortlist run against an
    exhaustive run that validates EVERY cheap-feasible candidate. Reports,
    per case, the feasible candidates the shortlist never validated and
    whether the exhaustive winner (or any feasible family) is missed."""
    records: list[dict[str, Any]] = []
    t_all = time.perf_counter()
    for case in cases:
        rec: dict[str, Any] = {"key": case.key, "note": case.note}
        try:
            sc = case.realize()
        except ScenarioRealizationError as exc:
            rec["realized"] = False
            rec["realizationError"] = str(exc)
            records.append(rec)
            continue
        world = generate_world(sc)
        t0 = time.perf_counter()
        normal = LayoutV2Search(sc, world).run()
        t_normal = time.perf_counter() - t0
        t0 = time.perf_counter()
        exhaustive = LayoutV2Search(sc, world).run(detailed_all=True)
        t_exh = time.perf_counter() - t0
        feasible_n = [c.candidate_id for c in normal.candidates if c.status == "FEASIBLE"]
        feasible_x = [c.candidate_id for c in exhaustive.candidates if c.status == "FEASIBLE"]
        fam = {c.candidate_id: c.params.family.value for c in exhaustive.candidates}
        missed = [cid for cid in feasible_x if cid not in feasible_n]
        rec.update(
            {
                "realized": True,
                "candidateCount": len(normal.candidates),
                "cheapFeasibleCount": int(normal.performance.get("cheapFeasibleCount", 0)),
                "shortlistSize": len(normal.shortlist),
                "shortlist": list(normal.shortlist),
                "feasibleNormal": feasible_n,
                "feasibleExhaustive": feasible_x,
                "missedFeasible": missed,
                "missedFamilies": sorted({fam[c] for c in missed} - {fam[c] for c in feasible_n}),
                "winnerNormal": normal.winner_id,
                "winnerExhaustive": exhaustive.winner_id,
                "winnerMissedByShortlist": (
                    exhaustive.winner_id is not None
                    and exhaustive.winner_id not in normal.shortlist
                ),
                "rankingExhaustive": list(exhaustive.ranking),
                "secondsNormal": t_normal,
                "secondsExhaustive": t_exh,
            }
        )
        records.append(rec)
    return {
        "suiteVersion": SUITE_VERSION,
        "label": label,
        "semantics": (
            "diagnostic shortlist-starvation audit: exhaustive detailed validation "
            "of every cheap-feasible candidate versus the bounded production "
            "shortlist; the production search is unchanged by this report"
        ),
        "caseCount": len(records),
        "anyWinnerMissed": any(r.get("winnerMissedByShortlist") for r in records),
        "anyFamilyMissed": any(r.get("missedFamilies") for r in records),
        "totalRuntimeSeconds": time.perf_counter() - t_all,
        "cases": records,
    }


# --------------------------------------------------------------------------- #
# Phase 20C.1-Q: shortlist YIELD audit (family-internal cheap rank vs detailed
# pass) — diagnostic instrument for the rule 165 conditional action
# --------------------------------------------------------------------------- #

#: a priori decision rule of the Q audit (documented BEFORE the numbers were
#: seen, never tuned to them): the cheap proxy is "correlated" with the
#: detailed outcome of a family when the pooled rank AUC — the probability
#: that a detailed-PASS candidate has a better family-internal cheap rank
#: than a detailed-FAIL candidate of the same family and case — is at least
#: this value over at least ``YIELD_MIN_PAIRS`` pass/fail pairs
YIELD_AUC_CORRELATED = 0.6
YIELD_MIN_PAIRS = 5


def _rank_auc(pass_ranks: list[int], fail_ranks: list[int]) -> tuple[float | None, int]:
    """Mann–Whitney rank AUC: P(pass rank < fail rank) with ties counted ½."""
    pairs = len(pass_ranks) * len(fail_ranks)
    if pairs == 0:
        return None, 0
    wins = 0.0
    for a in pass_ranks:
        for b in fail_ranks:
            wins += 1.0 if a < b else (0.5 if a == b else 0.0)
    return wins / pairs, pairs


def _spearman(x: list[float], y: list[float]) -> float | None:
    """Spearman rank correlation (average ranks for ties); None below 3 pairs."""
    n = len(x)
    if n < 3 or len(y) != n:
        return None

    def ranks(v: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = ranks(x), ranks(y)
    mx, my = sum(rx) / n, sum(ry) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx <= 0.0 or syy <= 0.0:
        return None
    return sxy / math.sqrt(sxx * syy)


def _level_failure_histogram(cand: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    if cand.access_plan is None:
        return out
    for a in cand.access_plan.accesses:
        if a.status != "OK" and a.failure_reason:
            out[a.failure_reason] = out.get(a.failure_reason, 0) + 1
    return out


def audit_yield(cases: list[LayoutCase], label: str) -> dict[str, Any]:
    """Phase 20C.1-Q shortlist-YIELD audit (diagnostic, never part of the
    production search). For every case and every family: each cheap-feasible
    candidate's FAMILY-INTERNAL cheap rank (by the stage-3 proxy) against its
    exhaustive detailed outcome, the production shortlist membership, the
    typed detailed failure reasons and the per-level access failure reasons;
    per family a rank AUC (proxy vs detailed pass), the Spearman correlation
    of proxy vs detailed total among passes, and the family-internal rank at
    which the family's best feasible candidate sits — the number an audited
    per-family top-N reservation would have to reach."""
    records: list[dict[str, Any]] = []
    pooled: dict[str, dict[str, list[int]]] = {}
    t_all = time.perf_counter()
    for case in cases:
        rec: dict[str, Any] = {"key": case.key, "note": case.note}
        try:
            sc = case.realize()
        except ScenarioRealizationError as exc:
            rec["realized"] = False
            rec["realizationError"] = str(exc)
            records.append(rec)
            continue
        world = generate_world(sc)
        t0 = time.perf_counter()
        normal = LayoutV2Search(sc, world).run()
        t_normal = time.perf_counter() - t0
        t0 = time.perf_counter()
        exhaustive = LayoutV2Search(sc, world).run(detailed_all=True)
        t_exh = time.perf_counter() - t0
        shortlisted = set(normal.shortlist)
        feasible_normal = {c.candidate_id for c in normal.candidates if c.status == "FEASIBLE"}
        cheap_ok = [c for c in exhaustive.candidates if c.stage_reached == "DETAILED"]
        cheap_ok.sort(key=lambda c: (c.cheap_proxy or math.inf, c.candidate_id))
        global_rank = {c.candidate_id: i + 1 for i, c in enumerate(cheap_ok)}
        families: dict[str, Any] = {}
        for fam in ("SPIRAL", "LONGITUDINAL", "SWITCHBACK"):
            members = [c for c in cheap_ok if c.params.family.value == fam]
            rows: list[dict[str, Any]] = []
            pass_ranks: list[int] = []
            fail_ranks: list[int] = []
            fail_hist: dict[str, int] = {}
            level_hist: dict[str, int] = {}
            for r, c in enumerate(members, start=1):
                passed = c.status == "FEASIBLE"
                (pass_ranks if passed else fail_ranks).append(r)
                if not passed:
                    for reason in c.failure_reasons:
                        fail_hist[reason] = fail_hist.get(reason, 0) + 1
                    for k, v in _level_failure_histogram(c).items():
                        level_hist[k] = level_hist.get(k, 0) + v
                rows.append(
                    {
                        "candidateId": c.candidate_id,
                        "familyRank": r,
                        "globalRank": global_rank[c.candidate_id],
                        "cheapProxy": _r(c.cheap_proxy),
                        "shortlisted": c.candidate_id in shortlisted,
                        "detailedPass": passed,
                        "failureReasons": list(c.failure_reasons),
                        "levelFailures": _level_failure_histogram(c),
                        "accessibleLevels": c.accessible_count,
                        "requiredLevels": len(c.level_service),
                        "total": _r(c.scores.total) if c.scores else None,
                        "stationLengthM": float(c.params.station_length_m or 0.0),
                    }
                )
            passes = [x for x in rows if x["detailedPass"]]
            best = min(passes, key=lambda x: (x["total"], x["candidateId"])) if passes else None
            auc, pairs = _rank_auc(pass_ranks, fail_ranks)
            spear = _spearman(
                [float(x["cheapProxy"]) for x in passes if x["cheapProxy"] is not None],
                [float(x["total"]) for x in passes if x["cheapProxy"] is not None],
            )
            pooled.setdefault(fam, {"pass": [], "fail": []})
            pooled[fam]["pass"] += pass_ranks
            pooled[fam]["fail"] += fail_ranks
            families[fam] = {
                "cheapFeasible": len(members),
                "shortlisted": sum(1 for x in rows if x["shortlisted"]),
                "shortlistedPass": sum(1 for x in rows if x["shortlisted"] and x["detailedPass"]),
                "detailedPass": len(passes),
                "missedFeasible": [
                    x["candidateId"] for x in passes if x["candidateId"] not in feasible_normal
                ],
                "bestFeasibleId": best["candidateId"] if best else None,
                "bestFeasibleFamilyRank": best["familyRank"] if best else None,
                "bestFeasibleGlobalRank": best["globalRank"] if best else None,
                "maxPassFamilyRank": max(pass_ranks) if pass_ranks else None,
                "rankAuc": _r(auc),
                "rankPairs": pairs,
                "spearmanProxyVsTotalAmongPasses": _r(spear),
                "detailedFailureReasons": fail_hist,
                "levelAccessFailureReasons": level_hist,
                "rows": rows,
            }
        exh_winner = exhaustive.candidate(exhaustive.winner_id) if exhaustive.winner_id else None
        exh_fam = exh_winner.params.family.value if exh_winner else None
        rec.update(
            {
                "realized": True,
                "candidateCount": len(normal.candidates),
                "cheapFeasibleCount": len(cheap_ok),
                "shortlistSize": len(normal.shortlist),
                "shortlist": list(normal.shortlist),
                "winnerNormal": normal.winner_id,
                "winnerExhaustive": exhaustive.winner_id,
                "winnerExhaustiveFamily": exh_fam,
                "winnerExhaustiveFamilyRank": (
                    next(
                        x["familyRank"]
                        for x in families[exh_fam]["rows"]
                        if x["candidateId"] == exhaustive.winner_id
                    )
                    if exh_fam
                    else None
                ),
                "winnerExhaustiveGlobalRank": (
                    global_rank.get(exhaustive.winner_id) if exhaustive.winner_id else None
                ),
                "winnerMissedByShortlist": (
                    exhaustive.winner_id is not None and exhaustive.winner_id not in shortlisted
                ),
                "missedFamilies": sorted(
                    fam
                    for fam, f in families.items()
                    if f["detailedPass"] > 0
                    and not any(
                        c.params.family.value == fam and c.status == "FEASIBLE"
                        for c in normal.candidates
                    )
                ),
                "families": families,
                "secondsNormal": t_normal,
                "secondsExhaustive": t_exh,
            }
        )
        records.append(rec)
    pooled_out: dict[str, Any] = {}
    for fam, pf in pooled.items():
        auc, pairs = _rank_auc(pf["pass"], pf["fail"])
        pooled_out[fam] = {
            "rankAuc": _r(auc),
            "rankPairs": pairs,
            "correlated": (
                auc is not None and pairs >= YIELD_MIN_PAIRS and auc >= YIELD_AUC_CORRELATED
            ),
            "passCount": len(pf["pass"]),
            "failCount": len(pf["fail"]),
        }
    realized = [r for r in records if r.get("realized")]
    top_n_needed = max(
        (
            f["bestFeasibleFamilyRank"]
            for r in realized
            for f in r["families"].values()
            if f["bestFeasibleFamilyRank"] is not None
        ),
        default=None,
    )
    return {
        "suiteVersion": SUITE_VERSION,
        "label": label,
        "semantics": (
            "Phase 20C.1-Q diagnostic shortlist-yield audit: family-internal cheap rank "
            "(stage-3 proxy) versus exhaustive detailed outcome; the production search "
            "is unchanged by this report"
        ),
        "decisionRule": {
            "correlatedIfPooledRankAucAtLeast": YIELD_AUC_CORRELATED,
            "minimumPairs": YIELD_MIN_PAIRS,
            "ifCorrelated": "audited per-family top-N reservation (N = topNNeededForBestFeasible)",
            "ifNotCorrelated": "fix the mis-ordering proxy term",
        },
        "caseCount": len(records),
        "pooled": pooled_out,
        "topNNeededForBestFeasible": top_n_needed,
        "anyWinnerMissed": any(r.get("winnerMissedByShortlist") for r in records),
        "anyFamilyMissed": any(r.get("missedFamilies") for r in records),
        "totalRuntimeSeconds": time.perf_counter() - t_all,
        "cases": records,
    }


# --------------------------------------------------------------------------- #
# Phase 20C.1-W: WARPED_VEIN multi-seed feasibility diagnosis (diagnostic only)
# --------------------------------------------------------------------------- #

#: the fixed deterministic seed list of the W survey (never sampled at run
#: time; a new seed is a code change). 301 and 307 are the golden seeds.
WARPED_SURVEY_SEEDS: tuple[int, ...] = tuple(range(301, 333))
WARPED_SURVEY_FAULT_COUNT = 1


def warped_seed_survey(seeds: tuple[int, ...], label: str) -> dict[str, Any]:
    """Run the production layout-v2 search on RANDOM_WARPED_VEIN scenarios of
    the fixed seed list and record, per seed: outcome, funnel counts, the
    dominant typed failure reason with its stage, the clearance picture
    (required vs certified conservative minimum vs error bound, COARSE /
    REFINED basis) and the serviceable / accessible level counts. Nothing
    is changed, tuned or persisted by this survey."""
    rows: list[dict[str, Any]] = []
    t_all = time.perf_counter()
    for seed in seeds:
        row: dict[str, Any] = {"seed": seed}
        t0 = time.perf_counter()
        try:
            create = realize_scenario(
                ScenarioPreset.RANDOM_WARPED_VEIN, seed, WARPED_SURVEY_FAULT_COUNT
            )
        except ScenarioRealizationError as exc:
            row.update({"realized": False, "realizationError": str(exc)})
            row["seconds"] = time.perf_counter() - t0
            rows.append(row)
            continue
        sc = Scenario(**create.model_dump())
        world = generate_world(sc)
        res = LayoutV2Search(sc, world).run()
        detailed = [c for c in res.candidates if c.stage_reached == "DETAILED"]
        feasible = [c for c in detailed if c.status == "FEASIBLE"]
        # failure histogram: (stage, first typed reason) over every candidate
        # that FAILED a stage (NOT_VALIDATED is the shortlist bound, not a
        # failure, and is counted separately)
        hist: dict[str, int] = {}
        not_validated = 0
        for c in res.candidates:
            if c.status == "FEASIBLE":
                continue
            if c.status == "NOT_VALIDATED":
                not_validated += 1
                continue
            reason = c.failure_reasons[0] if c.failure_reasons else c.status
            k = f"{c.stage_reached}:{reason}"
            hist[k] = hist.get(k, 0) + 1
        level_hist: dict[str, int] = {}
        for c in detailed:
            for k, v in _level_failure_histogram(c).items():
                level_hist[k] = level_hist.get(k, 0) + v
        # dominant failure: among DETAILED (stage-4) failures when any candidate
        # reached stage 4, else among stage-1/2 failures
        detailed_hist = {k: v for k, v in hist.items() if k.startswith("DETAILED:")}
        pool = detailed_hist or hist
        dominant = max(pool.items(), key=lambda kv: (kv[1], kv[0]))[0] if pool else None
        dominant_level = (
            max(level_hist.items(), key=lambda kv: (kv[1], kv[0]))[0] if level_hist else None
        )
        validated = [(c, c.clearance) for c in detailed if c.clearance is not None]
        best_pair = (
            max(validated, key=lambda cc: (cc[1].conservative_minimum, cc[0].candidate_id))
            if validated
            else None
        )
        best_clear = best_pair[0] if best_pair else None
        best_rep = best_pair[1] if best_pair else None
        winner = res.candidate(res.winner_id) if res.winner_id else None
        best_access = max((c.accessible_count or 0 for c in detailed), default=None)
        row.update(
            {
                "realized": True,
                "status": "SUCCESS" if res.winner_id else "NO_FEASIBLE_CANDIDATE",
                "winnerId": res.winner_id,
                "winnerFamily": winner.params.family.value if winner else None,
                "candidateCount": len(res.candidates),
                "cheapFeasibleCount": int(res.performance.get("cheapFeasibleCount", 0)),
                "shortlistSize": len(res.shortlist),
                "detailedFeasibleCount": len(feasible),
                "dominantFailure": dominant,
                "dominantLevelAccessFailure": dominant_level,
                "failureHistogram": hist,
                "notValidatedCount": not_validated,
                "detailedCount": len(detailed),
                "levelAccessFailureReasons": level_hist,
                "requiredLevelCount": len(res.levels),
                "serviceableLevelCount": len(res.serviceable_ids),
                "bestAccessibleLevels": best_access,
                "winnerAccessibleLevels": winner.accessible_count if winner else None,
                "clearanceBasisSearch": res.clearance_basis,
                "clearanceErrorBoundSearch": _r(res.clearance_error_bound),
                "requiredClearance": _r(res.required_clearance),
                "bestConservativeClearance": (
                    _r(best_rep.conservative_minimum) if best_rep else None
                ),
                "bestApproximateClearance": (
                    _r(best_rep.approximate_minimum) if best_rep else None
                ),
                "bestClearanceBasis": best_rep.basis if best_rep else None,
                "bestClearanceErrorBound": _r(best_rep.error_bound) if best_rep else None,
                "bestClearanceRefinement": best_rep.refinement if best_rep else None,
                "bestClearanceCandidateId": best_clear.candidate_id if best_clear else None,
                "orebodyVolumeM3": _r(world.orebody.volume(), 1),
                "seconds": time.perf_counter() - t0,
            }
        )
        rows.append(row)
    realized = [r for r in rows if r.get("realized")]
    success = [r for r in realized if r["status"] == "SUCCESS"]
    dom_hist: dict[str, int] = {}
    for r in realized:
        if r["status"] != "SUCCESS" and r["dominantFailure"]:
            dom_hist[r["dominantFailure"]] = dom_hist.get(r["dominantFailure"], 0) + 1
    return {
        "suiteVersion": SUITE_VERSION,
        "label": label,
        "semantics": (
            "Phase 20C.1-W diagnostic WARPED_VEIN multi-seed feasibility survey on the "
            "production layout-v2 search; nothing is tuned, changed or persisted"
        ),
        "seeds": list(seeds),
        "faultCount": WARPED_SURVEY_FAULT_COUNT,
        "seedCount": len(seeds),
        "realizedCount": len(realized),
        "successCount": len(success),
        "noFeasibleCount": len(realized) - len(success),
        "dominantFailureHistogram": dom_hist,
        "totalRuntimeSeconds": time.perf_counter() - t_all,
        "rows": rows,
    }


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
