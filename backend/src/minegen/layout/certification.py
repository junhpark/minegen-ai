"""Layout-v2 candidate clearance certification (AC-01C).

The stage-4 clearance certification of ONE layout-v2 candidate as an
explicit, search-object-free recipe: the level-entry stand-off rule, the
per-candidate REFINED_CONSERVATIVE policy construction (Phase 20B.1 C-2) and
the recorded-vs-rebuilt provenance check (Phase 20B.1-v2 1.1) that makes
every downstream consumer judge the selected design under the SAME
certification that made it FEASIBLE (rule 172). ``LayoutV2Search`` delegates
here; the numerics, dict keys, reason strings and error messages are the
ones the search carried before the extraction.

``restore_candidate_policy`` (AC-01D) is the search-object-free restore of
the selected certification: rebuilt from the shared search setup
(``layout.setup.build_search_setup``) + the candidate's persisted catalogue
centerline, then verified against the recorded certification — never
restored from the recorded numbers, never a re-run of the search.

This module must not import ``layout.search`` or ``layout.results``
(``layout.setup`` is a permitted leaf import).
"""

from __future__ import annotations

import math
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
    clearance_policy_for,
)
from minegen.layout.access import AnchorFailure, build_anchor
from minegen.layout.families import FootwallTrack
from minegen.layout.levels import LevelSections, RequiredLevel
from minegen.layout.setup import build_search_setup
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


def world_search_policy(
    scenario: Scenario, world: SyntheticWorld
) -> tuple[ClearancePolicy, DesignCostEvaluator]:
    """The whole-body search clearance policy and the search evaluator built
    over it — the two statements of ``LayoutV2Search.__init__`` (AC-01D:
    shared with the certification restore so the world side of the recipe
    has ONE definition)."""
    policy: ClearancePolicy = clearance_policy_for(world.orebody)
    evaluator = DesignCostEvaluator(
        world,
        scenario.design,
        DesignContext.decline(scenario.design),
        clearance=policy,
    )
    return policy, evaluator


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


def _candidate_id_of(payload: Any, source: str) -> str:
    """The ``candidateId`` of a persisted certification document, or the
    typed error when the document has no usable one."""
    cid = payload.get("candidateId") if isinstance(payload, dict) else None
    if not isinstance(cid, str) or not cid:
        raise ClearancePolicyReconstructionError(
            str(cid), f"{source} carries no usable clearance certification (candidateId)"
        )
    return cid


def _certification_fields(
    candidate_id: str, block: Any, keys: tuple[str, str, str, str], source: str
) -> tuple[str, float | None, float, dict[str, Any] | None]:
    """Typed reader of the four certification fields of a persisted block
    (basis, error bound, required clearance, refinement). A missing key, a
    wrong type, a non-finite number or a refinement dict the provenance key
    cannot digest is the typed ``ClearancePolicyReconstructionError`` naming
    the offending key — the fail-closed half of the contract is always kept
    by the callers; this keeps the TYPED half for tampered documents too."""

    def bad(what: str) -> ClearancePolicyReconstructionError:
        return ClearancePolicyReconstructionError(
            candidate_id, f"{source} carries no usable clearance certification ({what})"
        )

    if not isinstance(block, dict):
        raise bad("clearance")
    basis_key, bound_key, required_key, refinement_key = keys
    for key in keys:
        if key not in block:
            raise bad(key)
    basis = block[basis_key]
    if not isinstance(basis, str) or not basis:
        raise bad(basis_key)
    bound = block[bound_key]
    if bound is not None and not _is_finite_number(bound):
        raise bad(bound_key)
    required = block[required_key]
    if not _is_finite_number(required):
        raise bad(required_key)
    refinement = block[refinement_key]
    if refinement is not None:
        if not isinstance(refinement, dict):
            raise bad(refinement_key)
        try:
            _refinement_key(refinement)
        except (TypeError, ValueError) as err:
            raise bad(refinement_key) from err
    return basis, (None if bound is None else float(bound)), float(required), refinement


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


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
    def from_level_accesses(cls, payload: Any) -> CandidateCertification:
        """From a ``level_accesses.json`` payload (top-level certification
        keys). Every shape defect of the persisted document is the typed
        ``ClearancePolicyReconstructionError`` — never a bare KeyError /
        TypeError / ValueError (AC-01D fail-closed contract)."""
        candidate_id = _candidate_id_of(payload, "level accesses")
        basis, bound, required, refinement = _certification_fields(
            candidate_id,
            payload,
            ("clearanceBasis", "clearanceErrorBound", "requiredClearance", "clearanceRefinement"),
            "level accesses",
        )
        return cls(candidate_id, basis, bound, required, refinement)

    @classmethod
    def from_selection(cls, payload: Any) -> CandidateCertification:
        """From a ``layout_v2_selected.json`` payload (its ``clearance`` block
        is the candidate's ``ClearanceReport.to_dict()``). Every shape defect
        of the persisted document is the typed
        ``ClearancePolicyReconstructionError``."""
        candidate_id = _candidate_id_of(payload, "selection")
        clearance = payload.get("clearance") if isinstance(payload, dict) else None
        basis, bound, required, refinement = _certification_fields(
            candidate_id,
            clearance,
            ("clearanceBasis", "clearanceErrorBound", "requiredClearance", "refinement"),
            "selection",
        )
        return cls(candidate_id, basis, bound, required, refinement)

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
        """Fail closed when a REBUILT policy disagrees with this recorded
        certification — the single fail-closed provenance check (AC-01D):
        basis, refinement provenance key, then the recorded error bound
        (``None`` → 0.0, isclose 1e-9). A recorded number is never turned
        into a policy; a mismatch is typed and never repaired."""
        if policy.basis != self.basis or _refinement_key(refinement) != _refinement_key(
            self.refinement
        ):
            raise ClearancePolicyReconstructionError(
                self.candidate_id,
                f"rebuilt policy {policy.basis} {_refinement_key(refinement)} != recorded "
                f"{self.basis} {_refinement_key(self.refinement)}",
            )
        if not math.isclose(
            float(self.error_bound if self.error_bound is not None else 0.0),
            float(policy.error_bound),
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise ClearancePolicyReconstructionError(
                self.candidate_id,
                f"recorded {self.basis} (bound {self.error_bound}) but the rebuilt policy "
                f"is {policy.basis} (bound {policy.error_bound})",
            )


def candidate_points_from_catalogue(catalogue: dict[str, Any], candidate_id: str) -> FloatArray:
    """The persisted centerline of ONE FEASIBLE candidate, read from a
    ``layout_v2.json`` document (a pure function of the persisted bytes):
    every FEASIBLE candidate is shortlisted and therefore carries its
    ``centerline.points`` as exact float repr, so the JSON round trip is
    bit-exact. Returned as a C-contiguous float64 ``(N, 3)`` array — a
    strided view changes bits in ``Frame.world_to_local`` (AC-01D
    determinism probe), so the normalisation is part of the contract.
    Every inconsistency is a typed ``ClearancePolicyReconstructionError``;
    nothing is repaired or guessed."""
    if not isinstance(catalogue, dict):
        raise ClearancePolicyReconstructionError(candidate_id, "the catalogue is not a document")
    candidates = catalogue.get("candidates")
    if not isinstance(candidates, list):
        raise ClearancePolicyReconstructionError(
            candidate_id, "the catalogue carries no candidate list"
        )
    row: dict[str, Any] | None = None
    for c in candidates:
        if isinstance(c, dict) and c.get("candidateId") == candidate_id:
            row = c
            break
    if row is None:
        raise ClearancePolicyReconstructionError(
            candidate_id, f"the catalogue has no candidate '{candidate_id}'"
        )
    if row.get("status") != "FEASIBLE":
        raise ClearancePolicyReconstructionError(
            candidate_id, f"catalogue row is {row.get('status')}, not FEASIBLE"
        )
    cl = row.get("centerline")
    unusable = ClearancePolicyReconstructionError(
        candidate_id, f"catalogue carries no usable centerline for '{candidate_id}'"
    )
    if not isinstance(cl, dict) or not isinstance(cl.get("points"), list):
        raise unusable
    raw = cl["points"]
    count = cl.get("pointCount")
    if not isinstance(count, int) or count < 2 or len(raw) != 3 * count:
        raise unusable
    try:
        points = np.ascontiguousarray(np.asarray(raw, dtype=np.float64).reshape(-1, 3))
    except (TypeError, ValueError) as err:
        raise unusable from err
    if not np.all(np.isfinite(points)):
        raise unusable
    return points


def restore_candidate_policy(
    scenario: Scenario,
    world: SyntheticWorld,
    *,
    certification: CandidateCertification,
    points: FloatArray,
) -> tuple[DesignCostEvaluator, ClearancePolicy, dict[str, Any]]:
    """Rebuild the stage-4 clearance policy of the SELECTED candidate without
    the search object (AC-01D): the shared search setup
    (``build_search_setup`` — the very block ``LayoutV2Search.run()``
    executes), the world search policy / evaluator, and the persisted
    catalogue centerline go through the SAME ``build_candidate_policy``
    recipe stage 4 used, with the SERVICEABLE required levels (what the
    stage context carries). The result is then CHECKED against the recorded
    certification (basis, refinement provenance, error bound). Every branch
    either returns the verified policy or raises a typed
    ``ClearancePolicyReconstructionError``: never the whole-body policy on a
    mismatch, never a search re-run, never a file write."""
    candidate_id = certification.candidate_id
    points = np.ascontiguousarray(np.asarray(points, dtype=np.float64).reshape(-1, 3))
    setup = build_search_setup(scenario, world)
    if setup.section_error is not None:
        raise ClearancePolicyReconstructionError(
            candidate_id, f"{setup.section_error.code}: {setup.section_error.detail}"
        )
    serviceable = setup.sections.serviceable()
    if not serviceable or setup.track is None:
        raise ClearancePolicyReconstructionError(
            candidate_id,
            "no serviceable required level / footwall track — the catalogue cannot hold a "
            "FEASIBLE candidate",
        )
    if not math.isclose(
        setup.required_clearance,
        float(certification.required_clearance),
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        raise ClearancePolicyReconstructionError(
            candidate_id,
            f"rebuilt required clearance {setup.required_clearance} != recorded "
            f"{certification.required_clearance}",
        )
    world_policy, world_evaluator = world_search_policy(scenario, world)
    evaluator, policy, refinement = build_candidate_policy(
        world,
        scenario,
        scenario.layout,
        world_policy=world_policy,
        world_evaluator=world_evaluator,
        points=points,
        levels=serviceable,
        sections=setup.sections,
        track=setup.track,
        required_clearance=setup.required_clearance,
    )
    certification.verify(policy, refinement)
    return evaluator, policy, refinement
