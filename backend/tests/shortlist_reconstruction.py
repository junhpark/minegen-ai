"""Pure re-implementation of the layout-v2 stage-3 shortlist selection.

Used by the contract tests to compare the production `result.shortlist`
against an independent reconstruction from the candidate results. Kept out
of the test modules so the same reconstruction is checked against both an
EXACT case (`test_level_access.py`) and a CONSERVATIVE one whose shortlist
contains detailed-INFEASIBLE candidates (`test_layout_v2.py`).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from minegen.layout.families import FAMILY_ORDER
from minegen.layout.search import (
    CandidateResult,
    CandidateStatus,
    LayoutSearchResult,
    Stage,
    shortlist_key,
)

ShortlistKey = Callable[[CandidateResult], Any]


def stage3_survivors(res: LayoutSearchResult) -> list[CandidateResult]:
    """The candidates stage 3 chose from — the cheap-feasible set.

    A candidate that reached DETAILED was necessarily a cheap survivor,
    whatever stage 4 later decided: filtering on "no failure reasons" would
    silently drop every shortlisted candidate that stage 4 marked
    INFEASIBLE (Phase 20C.1 closeout follow-up §2). A candidate that stopped
    at CHEAP survived only if it is NOT_VALIDATED; CHEAP + INFEASIBLE failed
    the cheap checks and CONSTRUCT never produced geometry.
    """
    return [
        c
        for c in res.candidates
        if c.stage_reached == Stage.DETAILED
        or (c.stage_reached == Stage.CHEAP and c.status == CandidateStatus.NOT_VALIDATED)
    ]


def reconstruct_shortlist(
    res: LayoutSearchResult,
    bound: int,
    key: ShortlistKey | None = None,
    *,
    survivors: list[CandidateResult] | None = None,
) -> list[str]:
    """Stage 3 from its inputs: order by the shortlist key, cut at ``bound``,
    give every declared family its reserved slot (rule 165) by displacing the
    tail, then re-sort by the same key. ``key`` / ``survivors`` are the test
    seams for the red-fixture proofs."""
    k: ShortlistKey = key or shortlist_key
    pool = stage3_survivors(res) if survivors is None else survivors
    cheap_ok = sorted(pool, key=k)
    base = cheap_ok[:bound]
    missing = [f for f in FAMILY_ORDER if not any(c.params.family is f for c in base)]
    extras = [
        best
        for f in missing
        if (best := next((c for c in cheap_ok if c.params.family is f), None)) is not None
    ]
    if extras:
        base = sorted(base[: max(0, bound - len(extras))] + extras, key=k)
    return [c.candidate_id for c in base]


def survivors_without_failed_detailed(res: LayoutSearchResult) -> list[CandidateResult]:
    """The DISCARDED pre-follow-up filter, kept so a regression test can show
    it drops shortlisted candidates that stage 4 marked INFEASIBLE."""
    return [
        c
        for c in res.candidates
        if c.stage_reached in (Stage.CHEAP, Stage.DETAILED) and not c.failure_reasons
    ]
