"""Layout-v2 candidate clearance certification (AC-01C).

The stage-4 clearance certification of ONE layout-v2 candidate as an
explicit, search-object-free recipe: the level-entry stand-off rule, the
per-candidate REFINED_CONSERVATIVE policy construction (Phase 20B.1 C-2) and
the recorded-vs-rebuilt provenance check (Phase 20B.1-v2 1.1) that makes
every downstream consumer judge the selected design under the SAME
certification that made it FEASIBLE (rule 172). ``LayoutV2Search`` delegates
here; the numerics, dict keys, reason strings and error messages are the
ones the search carried before the extraction.

This module must not import ``layout.search`` or ``layout.results``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.core.models import LayoutV2Config, RampConstraints, Scenario
from minegen.design.constraints import DesignContext
from minegen.design.cost_field import (
    ClearancePolicy,
    ConservativeClearance,
    DesignCostEvaluator,
    RefinedConservativeClearance,
)
from minegen.layout.access import AnchorFailure, build_anchor
from minegen.layout.families import FootwallTrack
from minegen.layout.levels import LevelSections, RequiredLevel
from minegen.world.synthetic_world import SyntheticWorld

FloatArray = npt.NDArray[np.float64]


class ClearancePolicyReconstructionError(RuntimeError):
    """The candidate-specific clearance policy could not be rebuilt to match
    the candidate's recorded stage-4 report (Phase 20B.1-v2 1.1). Downstream
    consumers fail closed instead of silently judging the design under a
    different certification."""

    code = "LAYOUT_V2_CLEARANCE_MISMATCH"

    def __init__(self, candidate_id: str, detail: str) -> None:
        super().__init__(
            f"cannot reconstruct the stage-4 clearance policy of layout-v2 candidate "
            f"'{candidate_id}': {detail}; regenerate the layout catalogue"
        )
        self.candidate_id = candidate_id


def _refinement_key(refinement: dict[str, Any] | None) -> tuple[Any, ...]:
    """Provenance of one stage-4 refinement decision, rounded so a rebuilt
    window compares equal to its recorded (JSON round-tripped) report."""
    r = refinement or {}
    spacing = r.get("latticeSpacing")
    return (
        bool(r.get("applied")),
        r.get("reason"),
        int(r["factor"]) if r.get("factor") is not None else None,
        tuple(round(float(v), 9) for v in spacing) if spacing else None,
        tuple(int(v) for v in r["shape"]) if r.get("shape") else None,
        int(r["cellCount"]) if r.get("cellCount") is not None else None,
        round(float(r["errorBound"]), 9) if r.get("errorBound") is not None else None,
    )


@dataclass
class ClearanceReport:
    basis: str
    required: float
    conservative_minimum: float
    approximate_minimum: float | None
    error_bound: float | None
    satisfied: bool
    #: Phase 20B.1 C-2: what the stage-4 local refinement actually did for
    #: THIS candidate ({applied, factor, reason, windowCells, latticeSpacing})
    refinement: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "clearanceBasis": self.basis,
            "requiredClearance": self.required,
            "conservativeMinimumClearance": self.conservative_minimum,
            "approximateMinimumClearance": self.approximate_minimum,
            "clearanceErrorBound": self.error_bound,
            "satisfied": self.satisfied,
            "refinement": self.refinement,
        }


def anchor_standoff(
    cfg: LayoutV2Config, ramp: RampConstraints, required: float, policy: ClearancePolicy
) -> float:
    """Level-entry stand-off from the footwall edge: the configured /
    ramp value, raised for a conservative clearance policy so the entry
    itself satisfies ``required + errorBound`` (rule 146 honesty). With a
    stage-4 REFINED_CONSERVATIVE policy the smaller refined bound is what
    raises it (C-2), so entries move back toward the configured value."""
    base = (
        cfg.access.anchor_standoff
        if cfg.access.anchor_standoff is not None
        else ramp.footwall_access_offset
    )
    if policy.basis != "EXACT":
        return max(base, required + float(policy.error_bound) + 1.0)
    return base


def build_candidate_policy(
    world: SyntheticWorld,
    scenario: Scenario,
    cfg: LayoutV2Config,
    *,
    world_policy: ClearancePolicy,
    world_evaluator: DesignCostEvaluator,
    points: FloatArray,
    levels: list[RequiredLevel],
    sections: LevelSections,
    track: FootwallTrack,
    required_clearance: float,
) -> tuple[DesignCostEvaluator, ClearancePolicy, dict[str, Any]]:
    """Stage-4 evaluator for ONE candidate (Phase 20B.1 C-2): the shared
    policy, or a per-candidate REFINED_CONSERVATIVE policy built from one
    LOCAL refined window covering (a) the centerline samples whose COARSE
    certification falls below the requirement and (b) the level-entry
    corridor (preliminary anchors under the coarse stand-off — the
    refined bound moves the entries). Points outside the window keep the
    coarse certification, so refinement can only certify MORE, never
    admit an optimistic distance. A window over the cell budget skips
    refinement with an explicit diagnostic.

    On every non-refined branch the returned evaluator / policy are the very
    ``world_evaluator`` / ``world_policy`` objects (identity, not equality —
    the offset-trace cache token is chosen by ``policy is world_policy``)."""
    policy: ClearancePolicy = world_policy
    factor = int(cfg.clearance_refinement_factor)
    refinement: dict[str, Any] = {"applied": False, "factor": factor, "reason": None}
    if not isinstance(policy, ConservativeClearance):
        refinement["reason"] = "NOT_APPLICABLE_EXACT_BASIS"
        return world_evaluator, policy, refinement
    if factor <= 1:
        refinement["reason"] = "DISABLED"
        return world_evaluator, policy, refinement
    builder = getattr(world.orebody, "refined_clearance_window", None)
    if builder is None:
        refinement["reason"] = "UNSUPPORTED_OREBODY"
        return world_evaluator, policy, refinement
    coarse = policy.signed_clearance(points)
    needy = [points[coarse < required_clearance + 1e-9]]
    standoff_coarse = anchor_standoff(cfg, scenario.ramp, required_clearance, policy)
    for lv in levels:
        a = build_anchor(
            world.orebody,
            lv,
            sections,
            track,
            points,
            standoff_coarse,
            scenario.mining.method.value,
            clearance=policy.signed_clearance,
            policy_token="WORLD",
            minimum_clearance=required_clearance,
        )
        if a is not None and not isinstance(a, AnchorFailure):
            needy.append(a.position[None, :])
    pts = np.vstack([p for p in needy if p.shape[0]])
    pad = required_clearance + float(policy.error_bound) + 2.0
    window = builder(pts, pad, factor, int(cfg.clearance_refinement_max_cells))
    if window is None:
        refinement["reason"] = "BUDGET_EXCEEDED"
        return world_evaluator, policy, refinement
    refined = RefinedConservativeClearance(
        coarse=policy, window=window, error_bound=float(window.error_bound)
    )
    refinement.update({"applied": True, "reason": "APPLIED", **window.info()})
    evaluator = DesignCostEvaluator(
        world,
        scenario.design,
        DesignContext.decline(scenario.design),
        clearance=refined,
    )
    return evaluator, refined, refinement


@dataclass(frozen=True)
class CandidateCertification:
    """The recorded stage-4 clearance certification of ONE candidate — what
    the catalogue, the selection and ``level_accesses.json`` all carry about
    the basis the candidate was judged under, and the single producer of the
    four certification keys ``materialize_level_accesses`` writes.

    In-memory only: the refinement window recipe (coarse anchors, window
    origin) is persisted nowhere, so this DTO records provenance and checks a
    REBUILT policy against it; it never restores a policy by itself.
    ``refinement`` is held by reference — never copied or re-ordered."""

    candidate_id: str
    basis: str
    error_bound: float | None
    required_clearance: float
    refinement: dict[str, Any] | None

    @classmethod
    def from_report(cls, candidate_id: str, report: ClearanceReport) -> CandidateCertification:
        return cls(
            candidate_id=candidate_id,
            basis=report.basis,
            error_bound=report.error_bound,
            required_clearance=report.required,
            refinement=report.refinement,
        )

    @classmethod
    def from_level_accesses(cls, payload: dict[str, Any]) -> CandidateCertification:
        """From a ``level_accesses.json`` payload (top-level certification keys)."""
        return cls(
            candidate_id=payload["candidateId"],
            basis=payload["clearanceBasis"],
            error_bound=payload["clearanceErrorBound"],
            required_clearance=payload["requiredClearance"],
            refinement=payload["clearanceRefinement"],
        )

    @classmethod
    def from_selection(cls, payload: dict[str, Any]) -> CandidateCertification:
        """From a ``layout_v2_selected.json`` payload (its ``clearance`` block
        is the candidate's ``ClearanceReport.to_dict()``)."""
        clearance = payload["clearance"]
        return cls(
            candidate_id=payload["candidateId"],
            basis=clearance["clearanceBasis"],
            error_bound=clearance["clearanceErrorBound"],
            required_clearance=clearance["requiredClearance"],
            refinement=clearance["refinement"],
        )

    def to_dict(self) -> dict[str, Any]:
        """Exactly the four ``level_accesses.json`` certification keys, in
        their persisted insertion order."""
        return {
            "clearanceBasis": self.basis,
            "clearanceErrorBound": self.error_bound,
            "clearanceRefinement": self.refinement,
            "requiredClearance": self.required_clearance,
        }

    @property
    def provenance_key(self) -> tuple[Any, ...]:
        return (self.basis, _refinement_key(self.refinement))

    def verify(self, policy: ClearancePolicy, refinement: dict[str, Any] | None) -> None:
        """Fail closed when a REBUILT policy's basis / refinement provenance
        disagrees with this recorded certification.

        This is the search-side check verbatim: basis plus the refinement
        provenance key, and nothing else. It deliberately does NOT compare
        ``error_bound`` — the separate service-side comparison in
        ``DesignService._selected_candidate_policy`` still owns that, so
        ``verify`` is not yet a drop-in replacement for it (AC-01D)."""
        if policy.basis != self.basis or _refinement_key(refinement) != _refinement_key(
            self.refinement
        ):
            raise ClearancePolicyReconstructionError(
                self.candidate_id,
                f"rebuilt policy {policy.basis} {_refinement_key(refinement)} != recorded "
                f"{self.basis} {_refinement_key(self.refinement)}",
            )
