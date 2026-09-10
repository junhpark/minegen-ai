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

import pytest

from minegen.core.models import Scenario
from minegen.design import profile as design_profile
from minegen.layout import certification, materialize, results, search
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
    boundary_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    sc, world = tabular_small
    with pytest.raises(RuntimeError, match="has not built a stage context"):
        _ = LayoutV2Search(sc, world).context
    s, _ = boundary_search
    assert s.context is s._ctx
    assert s.context.sections is s._sections
    assert s.context.track is s._track
    assert s.context.reference is s._reference


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
