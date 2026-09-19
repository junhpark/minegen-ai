"""AC-01C boundary proofs for the ``layout.search`` extraction.

Mechanical contracts of the three new modules (``layout.results``,
``layout.certification``, ``layout.materialize``): the certification DTO
reproduces the persisted ``level_accesses.json`` keys in order, its
provenance check is the fail-closed one the search performs, every name
that was importable from ``layout.search`` still is (and IS the owning
module's object), the leaf modules never import the search, the sanctioned
``context`` accessor exposes the very post-run objects, and the lifted
``anchor_standoff`` recipe equals the method it delegates for.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

import pytest

from minegen.core.models import Scenario
from minegen.design import profile as design_profile
from minegen.layout import certification, materialize, provider, results, search, stages
from minegen.layout.certification import (
    CandidateCertification,
    ClearancePolicyReconstructionError,
)
from minegen.layout.materialize import materialize_effective_ramp, materialize_level_accesses
from minegen.layout.search import LayoutSearchResult, LayoutV2Search
from minegen.world.synthetic_world import SyntheticWorld, generate_world

from .conftest import small_scenario

CERT_KEYS = ("clearanceBasis", "clearanceErrorBound", "clearanceRefinement", "requiredClearance")


@pytest.fixture(scope="module")
def tabular_small() -> tuple[Scenario, SyntheticWorld]:
    sc = small_scenario()
    return sc, generate_world(sc)


@pytest.fixture(scope="module")
def boundary_search(
    tabular_small: tuple[Scenario, SyntheticWorld],
) -> tuple[LayoutV2Search, LayoutSearchResult]:
    sc, world = tabular_small
    s = LayoutV2Search(sc, world)
    return s, s.run()


def test_certification_dto_reproduces_the_level_access_keys_in_order(
    tabular_small: tuple[Scenario, SyntheticWorld],
    boundary_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    sc, _ = tabular_small
    s, res = boundary_search
    assert res.winner_id is not None
    cand = res.candidate(res.winner_id)
    assert cand is not None and cand.clearance is not None
    evaluator, _, _ = s.candidate_policy(res, res.winner_id)
    ramp = materialize_effective_ramp(res, cand, evaluator, "REV")
    acc = materialize_level_accesses(res, cand, "REV", sc.mining.method.value)
    dto = CandidateCertification.from_report(cand.candidate_id, cand.clearance)
    persisted = {k: acc[k] for k in CERT_KEYS}
    assert dto.to_dict() == persisted
    assert list(dto.to_dict().keys()) == list(CERT_KEYS)
    # the four keys sit contiguously between miningMethod and anchors
    keys = list(acc.keys())
    i = keys.index("miningMethod")
    assert keys[i + 1 : i + 5] == list(CERT_KEYS) and keys[i + 5] == "anchors"
    assert CandidateCertification.from_level_accesses(acc) == dto
    assert CandidateCertification.from_selection(ramp) == dto
    assert dto.required_clearance == res.required_clearance
    assert acc["requiredClearance"] == res.required_clearance


def test_certification_verify_is_the_fail_closed_provenance_check(
    boundary_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    s, res = boundary_search
    assert res.winner_id is not None
    cand = res.candidate(res.winner_id)
    assert cand is not None and cand.clearance is not None
    _, policy, refinement = s.candidate_policy(res, res.winner_id)
    dto = CandidateCertification.from_report(cand.candidate_id, cand.clearance)
    dto.verify(policy, refinement)  # the search's own output passes
    other = CandidateCertification(
        candidate_id=cand.candidate_id,
        basis="COARSE_CONSERVATIVE",
        error_bound=1.0,
        required_clearance=dto.required_clearance,
        refinement=dto.refinement,
    )
    with pytest.raises(ClearancePolicyReconstructionError) as info:
        other.verify(policy, refinement)
    assert info.value.code == "LAYOUT_V2_CLEARANCE_MISMATCH"
    assert info.value.candidate_id == cand.candidate_id
    assert "rebuilt policy" in str(info.value) and "!= recorded" in str(info.value)
    # provenance survives the JSON round trip the persisted artifacts take
    round_tripped = CandidateCertification.from_report(
        cand.candidate_id,
        certification.ClearanceReport(**json.loads(json.dumps(cand.clearance.__dict__))),
    )
    assert round_tripped.provenance_key == dto.provenance_key
    round_tripped.verify(policy, refinement)


@pytest.mark.parametrize(
    ("name", "owner"),
    [
        ("CandidateStatus", results),
        ("Stage", results),
        ("LevelServiceRecord", results),
        ("Scores", results),
        ("CandidateResult", results),
        ("LayoutSearchResult", results),
        ("LAYOUT_V2_VERSION", results),
        ("FloatArray", results),
        ("ClearanceReport", certification),
        ("ClearancePolicyReconstructionError", certification),
        ("SOURCE_KIND_PARAMETRIC_V2", materialize),
        ("LAYOUT_V2_SELECTED_ARTIFACT", materialize),
        ("LEVEL_ACCESSES_ARTIFACT", materialize),
        ("RAMP_END_SEGMENT_ID", materialize),
        ("materialize_effective_ramp", materialize),
        ("materialize_level_accesses", materialize),
        ("chainage_of", materialize),
        ("required_clearance", design_profile),
        # AC-01G commit 3: the stage helpers and the score coefficients moved
        # to ``layout.stages``; ``layout.search`` re-exports the owning
        # module's own object, so every established import path still resolves
        # to the one definition the search itself uses
        ("level_service", stages),
        ("cheap_checks", stages),
        ("level_screen_problems", stages),
        ("cheap_proxy", stages),
        ("score_candidate", stages),
        ("screen_authority", stages),
        ("DEV_ACCESS_COEF", stages),
        ("GEO_CORE_COEF", stages),
        ("GEO_DAMAGE_COEF", stages),
        ("GEO_POOR_ROCK_COEF", stages),
        ("GEO_CROSSING_COEF", stages),
        ("GEOM_TURNING_COEF", stages),
        ("GEOM_CLEARANCE_COEF", stages),
        ("GEOM_CURVATURE_COEF", stages),
        ("GEOM_REVERSAL_COEF", stages),
        ("GEOM_HAIRPIN_COEF", stages),
        ("GEOM_HALF_TURN_COEF", stages),
        ("SCORE_TIE_TOLERANCE", stages),
        ("RADIUS_TOLERANCE", stages),
        ("GRADIENT_TOLERANCE", stages),
    ],
)
def test_search_re_exports_the_owning_module_object(name: str, owner: object) -> None:
    assert name in search.__all__
    assert getattr(search, name) is getattr(owner, name)


def test_search_public_names_are_declared_and_the_shortlist_key_is_shared() -> None:
    for name in search.__all__:
        assert hasattr(search, name), name
    assert search.shortlist_key is search._shortlist_key
    # exactly one exception class object: the API router dispatches on isinstance
    from minegen.api import design as design_api

    assert (
        design_api.ClearancePolicyReconstructionError
        is search.ClearancePolicyReconstructionError
        is certification.ClearancePolicyReconstructionError
    )


def test_leaf_modules_never_import_the_search() -> None:
    code = (
        "import sys, minegen.layout.results, minegen.layout.certification, "
        "minegen.layout.materialize; assert 'minegen.layout.search' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_context_accessor_exposes_the_post_run_objects(
    tabular_small: tuple[Scenario, SyntheticWorld],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-01G: identity across the ACTUAL construction and stage call sites.

    ``_sections`` / ``_track`` / ``_reference`` are gone — the section
    provider owns them — so the proof is no longer that two private fields of
    one object alias each other (which ``run()`` made true by construction).
    Use-site spies capture the ``SearchSetup`` the provider built, the
    ``ServiceReference`` it returned, the ``ctx`` the FIRST family
    construction received and the ``StageContext`` the FIRST cheap stage ran
    under; ``context`` must expose exactly those objects."""
    sc, world = tabular_small
    with pytest.raises(RuntimeError, match="has not built a stage context"):
        _ = LayoutV2Search(sc, world).context

    seen: dict[str, Any] = {}
    real_setup = provider.build_search_setup
    real_reference = provider.build_service_reference
    real_family = search.build_family
    real_cheap = search.cheap_stage

    def spy_setup(*a: Any, **k: Any) -> Any:
        out = real_setup(*a, **k)
        seen.setdefault("setup", out)
        return out

    def spy_reference(*a: Any, **k: Any) -> Any:
        out = real_reference(*a, **k)
        seen.setdefault("reference", out)
        return out

    def spy_family(params: Any, ctx: Any) -> Any:
        seen.setdefault("family_ctx", ctx)
        return real_family(params, ctx)

    def spy_cheap(stage_ctx: Any, candidate_id: str, built: Any) -> Any:
        # AC-01G commit 3: the stage RETURNS its outcome (``apply_cheap`` is
        # the only writer), so the spy must pass it through
        seen.setdefault("stage_ctx", stage_ctx)
        return real_cheap(stage_ctx, candidate_id, built)

    monkeypatch.setattr(provider, "build_search_setup", spy_setup)
    monkeypatch.setattr(provider, "build_service_reference", spy_reference)
    monkeypatch.setattr(search, "build_family", spy_family)
    monkeypatch.setattr(search, "cheap_stage", spy_cheap)

    s = LayoutV2Search(sc, world)
    s.run()

    assert set(seen) == {"setup", "reference", "family_ctx", "stage_ctx"}
    assert s.context is s._ctx
    # the construction context IS the object the families were built against
    assert s.context is seen["family_ctx"]
    # and it carries the setup's / provider's objects, not copies
    assert s.context.sections is seen["setup"].sections
    assert s.context.track is seen["setup"].track
    assert s.context.reference is seen["reference"]
    # the stage saw the same context and the same section geometry
    stage_ctx = seen["stage_ctx"]
    assert stage_ctx.ctx is s.context
    assert stage_ctx.provider.sections is s.context.sections
    assert stage_ctx.provider.track is s.context.track
    assert stage_ctx.provider.reference is s.context.reference
    assert stage_ctx.provider.serviceable is s.context.levels
    # AC-01G Stage D (D5): the clearance-policy identity the offset-trace cache
    # token is decided by (``policy is world_policy``) reaches the stage as the
    # search's own constructor objects, not a rebuilt equal-looking pair
    assert stage_ctx.world_policy is s.policy
    assert stage_ctx.world_evaluator is s.evaluator
    # AC-01G: `_ctx` is the ONLY run state left on the search object
    # the COMPLETE instance dict, not just its private half (AC-01G Stage D,
    # D1: a public ``self.sections`` would have passed the old filter)
    assert set(vars(s)) == {
        "scenario",
        "world",
        "cfg",
        "policy",
        "evaluator",
        "shape",
        "station_merge_bound",
        "_ctx",
    }, sorted(vars(s))


def test_lifted_anchor_standoff_equals_the_search_method(
    tabular_small: tuple[Scenario, SyntheticWorld],
    boundary_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    sc, _ = tabular_small
    s, res = boundary_search
    req = res.required_clearance
    assert certification.anchor_standoff(s.cfg, sc.ramp, req, s.policy) == s.anchor_standoff(req)
    assert certification.anchor_standoff(s.cfg, sc.ramp, req, s.policy) == s.anchor_standoff(
        req, s.policy
    )
