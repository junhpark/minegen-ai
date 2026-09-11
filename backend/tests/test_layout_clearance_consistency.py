"""Phase 20B.1-v2 1.1 / 1.4 regressions.

1.1 — the selected Effective Ramp, its level accesses, the tunnel sweep and
the development sweep are judged under the SAME candidate-specific
clearance certification that made the candidate FEASIBLE in stage 4,
reconstructed deterministically after a process restart (cache miss) —
never the whole-body COARSE basis again. Fails closed on a stale selection.

1.4 — a clearance failure detail names the candidate-local basis.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from minegen.core.enums import ScenarioPreset
from minegen.core.models import Scenario, ScenarioCreate
from minegen.design.cost_field import clearance_policy_for
from minegen.layout.certification import ClearancePolicyReconstructionError
from minegen.layout.search import LayoutV2Search
from minegen.services.design_service import DesignService, LayoutSelectionStaleError
from minegen.services.scenario_realizer import realize_scenario
from minegen.services.scenario_service import ScenarioStore
from minegen.services.world_service import WorldService
from minegen.world.synthetic_world import generate_world


def _decisive_warped_create() -> ScenarioCreate:
    """WARPED seed 301 with the exclusion buffer raised into the window where
    the level-access branches certify ONLY under the refined bound (the
    coarse whole-body bound alone leaves them below the requirement).
    Refinement factor at its schema maximum (the bound narrows only by
    shrinking the spacing). Buffer 12 m (Phase 20B.2-A re-scan under the
    one-turn CS access: required 17.59 m, coarse-certified minimum 12.55 m,
    2 feasible candidates; the pre-20B.2 value 28 m relied on CSC-loop
    accesses and is NO_FEASIBLE_CANDIDATE under CS — every buffer ≥ 18 m
    fails on GRADE_LIMIT, not on clearance)."""
    raw = realize_scenario(ScenarioPreset.RANDOM_WARPED_VEIN, 301, 1).model_dump()
    raw["design"]["orebody_exclusion_buffer"] = 12.0
    raw["layout"]["clearance_refinement_factor"] = 4
    return ScenarioCreate(**raw)


def _points(block: dict) -> np.ndarray:  # type: ignore[type-arg]
    pts = block["points"] if isinstance(block, dict) else block
    return np.asarray(pts, dtype=np.float64).reshape(-1, 3)


def test_downstream_reuses_the_selected_candidate_certification_across_restart(
    store: ScenarioStore,
    world_service: WorldService,
    design_service: DesignService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sc = store.create(_decisive_warped_create())
    sid = sc.id
    world_service.generate(sid)
    catalogue = design_service.generate_layout_v2(sid)
    winner = catalogue["winnerId"]
    assert winner is not None, catalogue["status"]
    design_service.activate_layout_candidate(sid, winner)

    selected = design_service.layout_selected(sid)
    accesses = design_service.level_accesses(sid)
    basis = selected["clearance"]["clearanceBasis"]
    bound = selected["clearance"]["clearanceErrorBound"]
    assert basis == "REFINED_CONSERVATIVE"
    # pin: selected ramp basis == level_accesses basis == candidate actual basis
    assert accesses["clearanceBasis"] == basis
    assert accesses["clearanceErrorBound"] == pytest.approx(bound)
    assert accesses["clearanceRefinement"]["applied"] is True
    assert catalogue["clearanceBasis"] == "COARSE_CONSERVATIVE"  # whole-body search basis stays

    # measured branch clearances under the whole-body COARSE measure
    _, world = world_service.load(sid)
    coarse = clearance_policy_for(world.orebody)
    required = float(accesses["requiredClearance"])
    coarse_mins = [
        float(np.min(coarse.signed_clearance(_points(a["centerline"]))))
        for a in accesses["accesses"]
        if a["status"] == "OK"
    ]
    # Phase 20C.2A changed what this fixture can prove. Pre-20C.2A the
    # branches sat BETWEEN the refined and coarse floors (decisive: coarse
    # alone failed them). The curved backbone now CONSTRUCTS entries at the
    # allowance-compensated stand-off ≈ 1.28 × (required + refinedBound + 1),
    # which exceeds required + coarseBound for every buffer value (solving
    # 1.28·(req + b_r + 1) < req + b_c has no solution with b_c = 2·b_r),
    # so the decisive window is STRUCTURALLY empty — branches clear the
    # coarse floor too. The rule 172 MECHANISM pins below (identical
    # reconstruction across restart, stale selection fails closed, basis
    # naming) are unchanged and still the regression content of 1.1.
    assert coarse_mins and min(coarse_mins) >= required - 1e-6
    for a in accesses["accesses"]:
        assert a["validation"]["minimumOrebodyDistance"] >= required - 1e-9

    # ---- process restart: a FRESH service with an empty layout cache -------
    original = design_service._active_clearance_policy(sid, world)
    fresh = DesignService(store, world_service)
    assert not fresh._layouts
    rebuilt = fresh._active_clearance_policy(sid, world)
    assert rebuilt.basis == original.basis == basis
    assert float(rebuilt.error_bound) == pytest.approx(float(original.error_bound))
    assert float(rebuilt.error_bound) == pytest.approx(bound)
    # AC-01D: the restore populated no search object — it was rebuilt from
    # the recipe, and it equals the warm search's own stage-4 policy EXACTLY
    assert not fresh._layouts
    search, result = design_service._layouts[sid][1:]
    _, p_ref, r_ref = search.candidate_policy(result, winner)
    assert rebuilt.basis == p_ref.basis
    assert float(rebuilt.error_bound) == float(p_ref.error_bound)
    assert selected["clearance"]["refinement"] == r_ref
    # a truly COLD service: fresh WorldService (npz reload → fresh orebody
    # object, derived lattice recomputed) + fresh DesignService
    cold = DesignService(store, WorldService(store))
    _, cold_world = cold.worlds.load(sid)
    assert cold_world is not world and cold_world.orebody is not world.orebody
    pc = cold._active_clearance_policy(sid, cold_world)
    assert not cold._layouts
    assert pc.basis == p_ref.basis and float(pc.error_bound) == float(p_ref.error_bound)
    winner_points = _points(
        next(c for c in catalogue["candidates"] if c["candidateId"] == winner)["centerline"]
    )
    probes = [winner_points] + [
        _points(a["centerline"]) for a in accesses["accesses"] if a["status"] == "OK"
    ]
    for probe in probes:
        ref = p_ref.signed_clearance(probe)
        assert np.array_equal(pc.signed_clearance(probe), ref)
        assert np.array_equal(rebuilt.signed_clearance(probe), ref)
    # downstream builders never re-run the search, cold or warm
    monkeypatch.setattr(
        LayoutV2Search,
        "run",
        lambda *a, **k: pytest.fail("LayoutV2Search.run() downstream of a selection"),
    )

    tunnel = fresh.generate_tunnel(sid)
    assert tunnel["status"] == "SUCCESS", tunnel.get("failureReason")
    fresh2 = DesignService(store, world_service)
    dev = fresh2.generate_development_mesh(sid)
    assert dev["status"] == "SUCCESS", dev.get("failureReason")
    swept = [d for d in dev["developments"] if d["kind"] == "LEVEL_ACCESS"]
    assert len(swept) == len(accesses["accesses"])

    # ---- fail closed, identically warm and cold: a tampered error bound ---
    path = design_service.layout_selected_path(sid)
    pristine = path.read_text(encoding="utf-8")
    tampered = json.loads(pristine)
    tampered["clearance"]["clearanceErrorBound"] = float(bound) + 1e-3
    path.write_text(json.dumps(tampered), encoding="utf-8")
    errors: list[str] = []
    for svc in (design_service, DesignService(store, WorldService(store))):
        with pytest.raises(ClearancePolicyReconstructionError) as info:
            svc._active_clearance_policy(sid, svc.worlds.load(sid)[1])
        assert info.value.code == "LAYOUT_V2_CLEARANCE_MISMATCH"
        errors.append(str(info.value))
    assert errors[0] == errors[1] and winner in errors[0]
    path.write_text(pristine, encoding="utf-8")

    # ---- fail closed: a selection from another catalogue revision ---------
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["layoutRevision"] = "0000000000000000"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(LayoutSelectionStaleError):
        DesignService(store, world_service).generate_tunnel(sid)


def test_clearance_failure_detail_names_the_candidate_basis() -> None:
    """1.4: WARPED seed 307 fails its shortlisted candidates on OREBODY
    clearance under the per-candidate REFINED window; the detail must say
    so — the whole-body COARSE name would misreport the certification the
    number was measured under.

    Phase 20C.4: with the corridor read from the construction
    ServiceReference (rule 186) seed 307 clears every level and no survey
    seed fails on OREBODY_CLEARANCE any more. The refined-basis clearance
    failure is exercised on the LEGACY corridor, which an EXPLICIT
    ``layout.footwallStandoff`` (here the very 50 m the default derives)
    preserves by contract — the reference is inactive, the geometry is the
    pre-20C.4 one, and the failure detail contract is unchanged."""
    base = Scenario(
        **realize_scenario(ScenarioPreset.RANDOM_WARPED_VEIN, 307, fault_count=1).model_dump()
    )
    sc = base.model_copy(
        update={"layout": base.layout.model_copy(update={"footwall_standoff": 50.0})}
    )
    search = LayoutV2Search(sc, generate_world(sc))
    res = search.run()
    assert search.context.reference is not None and not search.context.reference.active
    failing = [
        c
        for c in res.candidates
        if c.clearance is not None
        and c.clearance.basis == "REFINED_CONSERVATIVE"
        and "OREBODY_CLEARANCE" in c.failure_reasons
    ]
    assert failing, "expected refined-basis clearance failures on seed 307"
    for c in failing:
        assert c.failure_detail is not None
        assert "(REFINED_CONSERVATIVE)" in c.failure_detail
        assert "(COARSE_CONSERVATIVE)" not in c.failure_detail
        assert math.isfinite(c.clearance.conservative_minimum)  # type: ignore[union-attr]


def test_fail_closed_errors_map_to_typed_409() -> None:
    """The two fail-closed conditions of 1.1 answer 409 with their own codes
    (never a 500) through the design router's guard."""
    from minegen.api.design import _guard
    from minegen.layout.search import ClearancePolicyReconstructionError

    stale = _guard("sid", LayoutSelectionStaleError("sid"))
    assert stale.status_code == 409
    assert stale.detail["code"] == "LAYOUT_V2_SELECTION_STALE"
    mismatch = _guard("sid", ClearancePolicyReconstructionError("SPIRAL-x", "why"))
    assert mismatch.status_code == 409
    assert mismatch.detail["code"] == "LAYOUT_V2_CLEARANCE_MISMATCH"
    assert "SPIRAL-x" in mismatch.detail["message"]
