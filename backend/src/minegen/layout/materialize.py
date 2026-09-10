"""Layout-v2 selection materialization (AC-01C, rules 149 / 155 / 157).

Turns a FEASIBLE ``CandidateResult`` into the two backend-authored
artifacts downstream consumers read — the Effective Ramp
(``layout_v2_selected.json``) and the ramp junctions + level-access
branches (``level_accesses.json``). Moved from ``layout.search`` — every
body verbatim except ``materialize_level_accesses``, whose four
certification keys now come from ``CandidateCertification.to_dict()``
spliced at the same position (and whose unreachable ``clearance is None``
fallback became an explicit ``ValueError``). Every dict literal keeps its
insertion order because the persisted files are written with
``json.dumps`` in that order.

This module must not import ``layout.search``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.design.cost_field import DesignCostEvaluator
from minegen.layout.certification import CandidateCertification
from minegen.layout.geometry import Crossing, analyze_centerline, insert_vertices, split_at
from minegen.layout.results import CandidateResult, CandidateStatus, LayoutSearchResult

FloatArray = npt.NDArray[np.float64]

SOURCE_KIND_PARAMETRIC_V2 = "PARAMETRIC_V2"
#: owning artifact name of a materialized layout-v2 effective ramp
LAYOUT_V2_SELECTED_ARTIFACT = "layout_v2_selected.json"
#: owning artifact of the ramp junctions + level access branches (Phase 20B)
LEVEL_ACCESSES_ARTIFACT = "level_accesses.json"
#: segment id of the main-ramp tail below the last turnout
RAMP_END_SEGMENT_ID = "RAMP_END"


# --------------------------------------------------------------------------- #
# Effective ramp materialization (rule 149)
# --------------------------------------------------------------------------- #


def materialize_effective_ramp(
    result: LayoutSearchResult,
    cand: CandidateResult,
    evaluator: DesignCostEvaluator,
    source_revision: str,
) -> dict[str, Any]:
    """Materialize the MAIN RAMP of a FEASIBLE candidate as the Effective Ramp
    (rule 149). Phase 20B (rule 157): the validated delivered centerline is
    split at the EXACT ramp-junction points of its level-access plan — the
    turnouts are the RAMP segment boundaries (network RAMP_JUNCTION nodes);
    a tail below the last turnout is the ``RAMP_END`` segment. A level's RL
    crossing is recorded only as a diagnostic reference; it is never a
    segment boundary, never a level entry. Level accesses are NOT ramp
    segments — they live in ``level_accesses.json``. No smoothing, no
    re-sampling: the geometry is the validated candidate centerline itself.
    """
    if cand.status != CandidateStatus.FEASIBLE or cand.points is None:
        raise ValueError(f"candidate {cand.candidate_id} is not FEASIBLE")
    plan = cand.access_plan
    if plan is None or not plan.feasible:
        raise ValueError(f"candidate {cand.candidate_id} has no feasible level-access plan")
    pts_raw = cand.points
    ch = chainage_of(pts_raw)
    junctions = [
        _JunctionMark(a.level_id, float(a.junction_chainage or 0.0), a.junction_position)
        for a in plan.accesses
    ]
    junctions.sort(key=lambda j: j.chainage)
    crossings = [_crossing_at_chainage(pts_raw, ch, j.chainage) for j in junctions]
    pts, idx = insert_vertices(pts_raw, crossings)
    for j, i in zip(junctions, idx, strict=True):
        # exact weld: the inserted vertex IS the planned junction position
        if j.position is not None:
            pts[i] = np.asarray(j.position, dtype=np.float64)
    pieces = split_at(pts, idx)
    # tail below the last turnout
    tail = pts[idx[-1] :].copy() if idx and idx[-1] < pts.shape[0] - 1 else None
    labels: list[tuple[str, str | None, dict[str, Any] | None]] = [
        (
            f"RAMP_JUNCTION:{j.level_id}",
            j.level_id,
            {"levelId": j.level_id, "chainage": j.chainage, "position": [float(v) for v in pts[i]]},
        )
        for j, i in zip(junctions, idx, strict=True)
    ]
    if tail is not None and tail.shape[0] >= 2:
        pieces.append(tail)
        labels.append((RAMP_END_SEGMENT_ID, None, None))
    segments: list[dict[str, Any]] = []
    raw_total = 0.0
    cost_total = 0.0
    max_grade = 0.0
    radii: list[float] = []
    bounds = [*idx, pts.shape[0] - 1] if tail is not None and tail.shape[0] >= 2 else list(idx)
    for k, (piece, (segment_id, level_id, junction)) in enumerate(zip(pieces, labels, strict=True)):
        start_t = _tangent(pts, bounds[k - 1] if k > 0 else 0, shared=k > 0)
        end_t = _tangent(pts, bounds[k], shared=k < len(pieces) - 1)
        diag = analyze_centerline(piece) if piece.shape[0] >= 2 else None
        ev = evaluator.evaluate_points(piece)
        finite = ev.base_cost + ev.rock_penalty + ev.fault_penalty + ev.orebody_penalty
        seg_len = np.linalg.norm(np.diff(piece, axis=0), axis=1)
        mid_cost = 0.5 * (finite[:-1] + finite[1:])
        field_cost = float(np.sum(mid_cost * seg_len))
        length = float(np.sum(seg_len))
        raw_total += length
        cost_total += field_cost
        if diag is not None:
            max_grade = max(max_grade, diag.max_abs_gradient)
            if diag.min_plan_radius is not None:
                radii.append(diag.min_plan_radius)
        segments.append(
            {
                "segmentId": segment_id,
                "levelId": level_id,
                "candidateId": cand.candidate_id,
                "smoothed": None,
                "effectiveSource": SOURCE_KIND_PARAMETRIC_V2,
                "effectiveCenterline": {
                    "points": [float(v) for v in piece.ravel()],
                    "pointCount": int(piece.shape[0]),
                },
                "boundaryTangents": {
                    "start": [float(v) for v in start_t],
                    "end": [float(v) for v in end_t],
                },
                "terminalKind": "RAMP_JUNCTION" if junction else "RAMP_END",
                "rampJunction": junction,
                "report": {
                    "rawLength": length,
                    "smoothedLength": None,
                    "fieldCostRaw": field_cost,
                    "fieldCostSmoothed": None,
                    "fieldCostDeltaPct": None,
                    "maxGradient": diag.max_abs_gradient if diag else 0.0,
                    "minPlanRadius": diag.min_plan_radius if diag else None,
                    "maxDeviationFromRaw": 0.0,
                    "endpointPositionError": 0.0,
                    "startHeadingErrorDeg": 0.0,
                    "endHeadingErrorDeg": 0.0,
                    "invalidSampleCount": 0,
                    "rejectionReasonCounts": {},
                    "monotonicityViolations": 0,
                    "gradeViolations": 0,
                    "radiusViolations": 0,
                    "corridorViolations": 0,
                    "repairs": 0,
                    "valid": True,
                    "effectiveSource": SOURCE_KIND_PARAMETRIC_V2,
                    "fallbackReason": None,
                },
            }
        )
    references = [
        {
            "levelId": r.level_id,
            "elevation": r.elevation,
            "position": [float(v) for v in r.connection_position]
            if r.connection_position is not None
            else None,
            "chainage": r.connection_chainage,
            "footprintDistance": r.access_distance,
        }
        for r in cand.level_service
    ]
    return {
        "status": "SUCCESS",
        "sourceKind": SOURCE_KIND_PARAMETRIC_V2,
        "sourceRevision": source_revision,
        "candidateId": cand.candidate_id,
        "family": cand.params.family.value,
        "failureReason": None,
        "portal": [float(v) for v in result.portal],
        "segments": segments,
        "rampJunctions": [s["rampJunction"] for s in segments if s["rampJunction"]],
        "rampLevelReferences": references,
        "levelAccessArtifact": LEVEL_ACCESSES_ARTIFACT,
        "totals": {
            "segments": len(segments),
            "smoothedSegments": 0,
            "fallbackSegments": 0,
            "rawLength": raw_total,
            "effectiveLength": raw_total,
            "fieldCostRaw": cost_total,
            "fieldCostEffective": cost_total,
            "fieldCostDeltaPct": None,
            "maxGradient": max_grade,
            "minimumPlanRadius": float(min(radii)) if radii else None,
            "maxDeviation": 0.0,
        },
        "diagnostics": cand.diagnostics.to_dict() if cand.diagnostics else None,
        "clearance": cand.clearance.to_dict() if cand.clearance else None,
        "scores": cand.scores.to_dict() if cand.scores else None,
        "access": plan.summary(),
    }


def materialize_level_accesses(
    result: LayoutSearchResult,
    cand: CandidateResult,
    source_revision: str,
    mining_method: str,
) -> dict[str, Any]:
    """``level_accesses.json`` (rule 157): the ramp junctions and level-access
    branches of the selected candidate — the ONLY owner of that geometry.
    Every ``levelEntry`` is the authoritative LEVEL_ENTRY the level
    development starts from."""
    if (
        cand.status != CandidateStatus.FEASIBLE
        or cand.access_plan is None
        or cand.clearance is None
    ):
        raise ValueError(f"candidate {cand.candidate_id} is not FEASIBLE")
    plan = cand.access_plan
    return {
        "status": "SUCCESS" if plan.feasible else "FAILED",
        "failureReason": None
        if plan.feasible
        else "; ".join(f"{a.level_id}: {a.failure_reason}" for a in plan.accesses if not a.ok),
        "sourceRevision": source_revision,
        "rampSource": "LAYOUT_V2",
        "rampArtifact": LAYOUT_V2_SELECTED_ARTIFACT,
        "candidateId": cand.candidate_id,
        "family": cand.params.family.value,
        "miningMethod": mining_method,
        # the basis the candidate's accesses were actually validated under
        # (stage-4 REFINED_CONSERVATIVE when refinement applied), never the
        # catalogue's whole-body search basis (Phase 20B.1-v2 1.1)
        **CandidateCertification.from_report(cand.candidate_id, cand.clearance).to_dict(),
        "anchors": [a.to_dict() if a else None for a in cand.anchors],
        "accesses": [a.to_dict(include_points=True) for a in plan.accesses],
        "summary": plan.summary(),
    }


@dataclass(frozen=True)
class _JunctionMark:
    level_id: str
    chainage: float
    position: FloatArray | None


def chainage_of(points: FloatArray) -> FloatArray:
    seg = np.linalg.norm(np.diff(points, axis=0), axis=1)
    return np.asarray(np.concatenate([[0.0], np.cumsum(seg)]))


def _crossing_at_chainage(points: FloatArray, ch: FloatArray, s: float) -> Crossing:
    """Exact vertex position at 3-D chainage ``s`` as a Crossing so the
    shared ``insert_vertices`` machinery can split there."""
    i = int(np.searchsorted(ch, s, side="right") - 1)
    i = min(max(i, 0), points.shape[0] - 2)
    seg = float(ch[i + 1] - ch[i])
    t = (s - float(ch[i])) / seg if seg > 1e-12 else 0.0
    t = min(max(t, 0.0), 1.0)
    p = points[i] + t * (points[i + 1] - points[i])
    return Crossing(float(p[2]), i, float(t), np.asarray(p, dtype=np.float64), float(s))


def _tangent(pts: FloatArray, vertex: int, *, shared: bool) -> FloatArray:
    """Unit 3-D tangent at a vertex: mean of the incoming and outgoing chord
    directions when the vertex is shared by two segments, otherwise the
    single available chord (portal start / terminal end)."""
    n = pts.shape[0]
    dirs: list[FloatArray] = []
    if vertex > 0:
        d = pts[vertex] - pts[vertex - 1]
        dirs.append(d / max(float(np.linalg.norm(d)), 1e-12))
    if vertex < n - 1:
        d = pts[vertex + 1] - pts[vertex]
        dirs.append(d / max(float(np.linalg.norm(d)), 1e-12))
    if not shared and vertex == 0 and len(dirs) > 1:
        dirs = dirs[1:]
    if not shared and vertex == n - 1 and len(dirs) > 1:
        dirs = dirs[:1]
    t = np.sum(np.asarray(dirs), axis=0)
    return np.asarray(t / max(float(np.linalg.norm(t)), 1e-12))
