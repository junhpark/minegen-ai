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
    store: ScenarioStore, world_service: WorldService, design_service: DesignService
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

    # the fixture is DECISIVE: under the coarse certification alone at least
    # one validated access branch falls below the required clearance
    _, world = world_service.load(sid)
    coarse = clearance_policy_for(world.orebody)
    required = float(accesses["requiredClearance"])
    coarse_mins = [
        float(np.min(coarse.signed_clearance(_points(a["centerline"]))))
        for a in accesses["accesses"]
        if a["status"] == "OK"
    ]
    assert coarse_mins and min(coarse_mins) < required - 1e-6
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

    tunnel = fresh.generate_tunnel(sid)
    assert tunnel["status"] == "SUCCESS", tunnel.get("failureReason")
    fresh2 = DesignService(store, world_service)
    dev = fresh2.generate_development_mesh(sid)
    assert dev["status"] == "SUCCESS", dev.get("failureReason")
    swept = [d for d in dev["developments"] if d["kind"] == "LEVEL_ACCESS"]
    assert len(swept) == len(accesses["accesses"])

    # ---- fail closed: a selection from another catalogue revision ---------
    path = design_service.layout_selected_path(sid)
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["layoutRevision"] = "0000000000000000"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(LayoutSelectionStaleError):
        DesignService(store, world_service).generate_tunnel(sid)


def test_clearance_failure_detail_names_the_candidate_basis() -> None:
    """1.4: WARPED seed 307 fails its shortlisted candidates on OREBODY
    clearance under the per-candidate REFINED window; the detail must say
    so — the whole-body COARSE name would misreport the certification the
    number was measured under."""
    sc = Scenario(
        **realize_scenario(ScenarioPreset.RANDOM_WARPED_VEIN, 307, fault_count=1).model_dump()
    )
    res = LayoutV2Search(sc, generate_world(sc)).run()
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
