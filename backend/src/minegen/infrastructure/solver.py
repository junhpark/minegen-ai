"""Phase 11 deterministic connected-greedy placement solver (rule 90).

``CONNECTED_GREEDY_PATH_SET_COVER_V0_1``: starting from the mandatory
root set, repeatedly add the whole shortest candidate-hop PATH to the
candidate with the best (gain/cost, gain, -cost, id) score, where gain is
the newly covered demand of ALL new routers on that path — a relay router
that covers nothing by itself can still be added as part of a path to a
useful downstream router. Deterministic: BFS neighbours and tie-breaks are
ordered by candidate id; no RNG. This is a feasible/connected baseline and
explicitly NOT a global optimum (``optimalityClaim = false``).
"""

from __future__ import annotations

from collections import deque

from minegen.infrastructure.models import (
    CoveragePlacementProblem,
    PlacementProblem,
    PlacementSolution,
)

INFEASIBLE_REASON = "INFEASIBLE_COMMUNICATION_COVERAGE"


def _or_mask(demand_ids: list[str], demand_bit: dict[str, int]) -> int:
    """Bitwise-OR flag mask: idempotent under duplicates — arithmetic sum
    would carry bits and corrupt the coverage mask."""
    mask = 0
    for did in demand_ids:
        mask |= demand_bit[did]
    return mask


def validate_coverage_relations(
    coverage_sets: dict[str, list[str]],
    candidate_ids: list[str],
    demand_ids: list[str],
) -> str | None:
    """Pre-solver relation gate shared by both builders: coverage-model
    output must reference only known candidates/demands with unique demand
    ids per set. Returns the typed failure reason, or None if valid."""
    known_candidates = set(candidate_ids)
    known_demands = set(demand_ids)
    for cid in sorted(coverage_sets):  # deterministic reporting order
        if cid not in known_candidates:
            return f"coverage model references unknown candidate {cid}"
        dids = coverage_sets[cid]
        if len(set(dids)) != len(dids):
            dup = sorted({d for d in dids if dids.count(d) > 1})[:3]
            return f"coverage model repeats demand ids {dup} for candidate {cid}"
        for did in dids:
            if did not in known_demands:
                return f"coverage model references unknown demand {did}"
    return None


def solve_connected_greedy(problem: PlacementProblem) -> PlacementSolution:
    demand_ids = [d.id for d in problem.demands]
    demand_bit = {did: 1 << i for i, did in enumerate(demand_ids)}
    all_candidates = sorted(c.id for c in problem.candidates)
    cover_mask = {
        cid: _or_mask(problem.candidate_coverage_sets.get(cid, []), demand_bit)
        for cid in all_candidates
    }
    neighbours = {
        cid: sorted(problem.candidate_backhaul_graph.get(cid, [])) for cid in all_candidates
    }

    selected: set[str] = set()
    covered_mask = 0
    for cid in sorted(problem.mandatory_candidate_ids):
        if cid not in cover_mask:
            return PlacementSolution(
                status="FAILED",
                failure_reason=f"mandatory candidate {cid} does not exist",
                selected_candidate_ids=[],
                covered_demand_ids=[],
            )
        selected.add(cid)
        covered_mask |= cover_mask[cid]

    total = len(demand_ids)
    target = problem.required_coverage_fraction

    def fraction() -> float:
        return (covered_mask.bit_count() / total) if total else 1.0

    while fraction() < target - 1e-12:
        # deterministic multi-source BFS over the candidate backhaul graph:
        # shortest candidate-hop path from the selected component outward,
        # neighbours visited in candidate-id order, first discovery wins
        parent: dict[str, str | None] = {cid: None for cid in sorted(selected)}
        queue = deque(sorted(selected))
        order: list[str] = []
        while queue:
            cur = queue.popleft()
            for nxt in neighbours.get(cur, []):
                if nxt in parent:
                    continue
                parent[nxt] = cur
                queue.append(nxt)
                order.append(nxt)

        best: tuple[float, int, int, str] | None = None
        best_path: list[str] | None = None
        uncovered = ~covered_mask
        for cid in order:  # every reachable not-yet-selected candidate
            path: list[str] = []
            walk: str | None = cid
            while walk is not None and walk not in selected:
                path.append(walk)
                walk = parent[walk]
            path.reverse()  # new routers from the selected component outward
            union = 0
            for pid in path:
                union |= cover_mask[pid]
            gain = (union & uncovered).bit_count()
            if gain <= 0:
                continue
            cost = len(path)
            score = gain / cost
            key = (-score, -gain, cost, cid)
            if best is None or key < best:
                best = key
                best_path = path
        if best_path is None:
            return PlacementSolution(
                status="FAILED",
                failure_reason=INFEASIBLE_REASON,
                selected_candidate_ids=sorted(selected),
                covered_demand_ids=sorted(
                    did for did in demand_ids if covered_mask & demand_bit[did]
                ),
            )
        for pid in best_path:
            selected.add(pid)
            covered_mask |= cover_mask[pid]

    return PlacementSolution(
        status="SUCCESS",
        failure_reason=None,
        selected_candidate_ids=sorted(selected),
        covered_demand_ids=sorted(did for did in demand_ids if covered_mask & demand_bit[did]),
    )


SENSOR_INFEASIBLE_REASON = "INFEASIBLE_SENSOR_COVERAGE"


def solve_greedy_set_cover(problem: CoveragePlacementProblem) -> PlacementSolution:
    """``GREEDY_SET_COVER_V0_1`` (rule 96): deterministic greedy set cover
    with unit sensor cost, no connectivity requirement and no
    global-optimality claim. Starting from the EMPTY set, repeatedly select
    the candidate with the highest uncovered-demand gain, ties broken by
    lexicographically smallest candidate id. No RNG."""
    demand_ids = [d.id for d in problem.demands]
    demand_bit = {did: 1 << i for i, did in enumerate(demand_ids)}
    all_candidates = sorted(c.id for c in problem.candidates)
    cover_mask = {
        cid: _or_mask(problem.candidate_coverage_sets.get(cid, []), demand_bit)
        for cid in all_candidates
    }
    selected: set[str] = set()
    covered_mask = 0
    total = len(demand_ids)
    target = problem.required_coverage_fraction

    def fraction() -> float:
        return (covered_mask.bit_count() / total) if total else 1.0

    while fraction() < target - 1e-12:
        uncovered = ~covered_mask
        best_cid: str | None = None
        best_gain = 0
        for cid in all_candidates:  # id-ordered => deterministic tie-break
            if cid in selected:
                continue
            gain = (cover_mask[cid] & uncovered).bit_count()
            if gain > best_gain:
                best_gain = gain
                best_cid = cid
        if best_cid is None:
            return PlacementSolution(
                status="FAILED",
                failure_reason=SENSOR_INFEASIBLE_REASON,
                selected_candidate_ids=sorted(selected),
                covered_demand_ids=sorted(
                    did for did in demand_ids if covered_mask & demand_bit[did]
                ),
            )
        selected.add(best_cid)
        covered_mask |= cover_mask[best_cid]

    return PlacementSolution(
        status="SUCCESS",
        failure_reason=None,
        selected_candidate_ids=sorted(selected),
        covered_demand_ids=sorted(did for did in demand_ids if covered_mask & demand_bit[did]),
    )
