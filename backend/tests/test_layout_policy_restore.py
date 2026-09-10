"""AC-01D: the selected candidate's stage-4 clearance certification is
RESTORED from its recipe (shared search setup + the catalogue centerline of
the selected candidate) and VERIFIED against the recorded certification —
never re-run, never restored from the recorded numbers.

Proofs: restore ≡ the search's own ``candidate_policy`` bit for bit (warm
world object and a freshly built world), typed fail-closed on every recipe
mismatch, catalogue-point normalisation (contiguous float64 — a strided view
changes bits in ``Frame.world_to_local``), ``layout.setup`` /
``layout.certification`` are leaves, ``run()`` uses the shared setup, and a
COLD service chain (fresh WorldService + fresh DesignService, search re-run
forbidden) produces byte-equal downstream artifacts.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from minegen.core.models import Scenario, ScenarioCreate
from minegen.layout import certification
from minegen.layout.certification import (
    CandidateCertification,
    ClearancePolicyReconstructionError,
    candidate_points_from_catalogue,
    restore_candidate_policy,
)
from minegen.layout.materialize import materialize_effective_ramp, materialize_level_accesses
from minegen.layout.search import LayoutSearchResult, LayoutV2Search
from minegen.layout.setup import build_search_setup
from minegen.services.design_service import DesignService
from minegen.services.scenario_service import ScenarioStore
from minegen.services.world_service import WorldService
from minegen.world.orebody import build_orebody
from minegen.world.synthetic_world import SyntheticWorld, generate_world

from .conftest import small_scenario

# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

WALL_CLOCK_KEYS = {"sourceRevision"}


def _strip(obj: Any) -> Any:
    """Drop wall-clock / stat-fingerprint keys (``sourceRevision``,
    ``*Seconds``) recursively; everything else — including
    ``artifactRevision`` (sha256 of the GLB) — is compared."""
    if isinstance(obj, dict):
        return {
            k: _strip(v)
            for k, v in obj.items()
            if k not in WALL_CLOCK_KEYS and not str(k).endswith("Seconds")
        }
    if isinstance(obj, list):
        return [_strip(v) for v in obj]
    return obj


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(_strip(obj), sort_keys=True).encode()).hexdigest()


def _forbidden_run(*_args: Any, **_kwargs: Any) -> LayoutSearchResult:
    pytest.fail("LayoutV2Search.run() was called downstream of a selection (AC-01D)")


def _create_of(sc: Scenario) -> ScenarioCreate:
    extra = set(Scenario.model_fields) - set(ScenarioCreate.model_fields)
    return ScenarioCreate.model_validate(sc.model_dump(exclude=extra))


def _access_points(payload: dict[str, Any]) -> list[np.ndarray]:  # type: ignore[type-arg]
    return [
        np.ascontiguousarray(np.asarray(a["centerline"]["points"], dtype=np.float64).reshape(-1, 3))
        for a in payload["accesses"]
        if a["status"] == "OK"
    ]


@pytest.fixture(scope="module")
def tabular_search() -> tuple[Scenario, SyntheticWorld, LayoutV2Search, LayoutSearchResult]:
    sc = small_scenario()
    world = generate_world(sc)
    s = LayoutV2Search(sc, world)
    res = s.run()
    assert res.winner_id is not None, res.to_dict()["status"]
    return sc, world, s, res


def _assert_restore_equals(
    sc: Scenario,
    worlds: list[SyntheticWorld],
    cert: CandidateCertification,
    pts: np.ndarray,  # type: ignore[type-arg]
    p_ref: Any,
    r_ref: dict[str, Any],
    extra_points: list[np.ndarray],  # type: ignore[type-arg]
) -> None:
    probe = pts + np.array([7.0, -3.0, 2.0])
    for w in worlds:
        _, pol, ref = restore_candidate_policy(sc, w, certification=cert, points=pts)
        assert pol.basis == p_ref.basis
        assert float(pol.error_bound) == float(p_ref.error_bound)  # exact, never approx
        assert ref == r_ref
        for p in (pts, probe, *extra_points):
            assert np.array_equal(pol.signed_clearance(p), p_ref.signed_clearance(p))


# --------------------------------------------------------------------------- #
# restore ≡ stage-4 policy
# --------------------------------------------------------------------------- #


def test_restore_equals_stage4_policy_tabular_small(
    tabular_search: tuple[Scenario, SyntheticWorld, LayoutV2Search, LayoutSearchResult],
) -> None:
    sc, world, s, res = tabular_search
    wid = res.winner_id
    assert wid is not None
    cand = res.candidate(wid)
    assert cand is not None and cand.points is not None
    cat = json.loads(json.dumps(res.to_dict()))
    pts = candidate_points_from_catalogue(cat, wid)
    assert np.array_equal(pts, cand.points)  # the JSON round trip is exact
    assert pts.flags.c_contiguous and pts.dtype == np.float64 and pts.shape == cand.points.shape
    sel = json.loads(json.dumps(materialize_effective_ramp(res, cand, s.evaluator, "REV")))
    cert = CandidateCertification.from_selection(sel)
    _, p_ref, r_ref = s.candidate_policy(res, wid)
    assert p_ref.basis == "EXACT" and float(p_ref.error_bound) == 0.0
    assert r_ref == {
        "applied": False,
        "factor": int(sc.layout.clearance_refinement_factor),
        "reason": "NOT_APPLICABLE_EXACT_BASIS",
    }
    _assert_restore_equals(sc, [world, generate_world(sc)], cert, pts, p_ref, r_ref, [])


def test_restore_equals_stage4_policy_warped_301(
    warped_301: tuple[Scenario, SyntheticWorld],
    warped_301_search: tuple[LayoutV2Search, LayoutSearchResult],
) -> None:
    """Read-only use of the shared fixture: the restore builds its own
    LevelSections / track / policy and never touches the search's."""
    sc, world = warped_301
    s, res = warped_301_search
    wid = res.winner_id
    assert wid is not None
    cand = res.candidate(wid)
    assert cand is not None and cand.points is not None
    cat = json.loads(json.dumps(res.to_dict()))
    pts = candidate_points_from_catalogue(cat, wid)
    assert np.array_equal(pts, cand.points)
    sel = json.loads(json.dumps(materialize_effective_ramp(res, cand, s.evaluator, "REV")))
    cert = CandidateCertification.from_selection(sel)
    accesses = json.loads(
        json.dumps(materialize_level_accesses(res, cand, "REV", sc.mining.method.value))
    )
    access_pts = _access_points(accesses)
    assert access_pts
    _, p_ref, r_ref = s.candidate_policy(res, wid)
    assert p_ref.basis == "REFINED_CONSERVATIVE"
    assert r_ref["applied"] is True and r_ref["factor"] == 2 and r_ref["reason"] == "APPLIED"
    assert {"latticeSpacing", "shape", "cellCount", "errorBound"} <= set(r_ref)
    # cold variant: a freshly built orebody (derived lattice + EDT recomputed)
    cold_world = SyntheticWorld(
        terrain=world.terrain,
        orebody=build_orebody(sc.orebody),
        faults=world.faults,
        fields=world.fields,
    )
    assert cold_world.orebody is not world.orebody
    _assert_restore_equals(sc, [world, cold_world], cert, pts, p_ref, r_ref, access_pts)


# --------------------------------------------------------------------------- #
# typed fail-closed
# --------------------------------------------------------------------------- #


def test_catalogue_points_fail_closed() -> None:
    good = {"candidateId": "SPIRAL-x", "status": "FEASIBLE", "centerline": None}

    def cat(**row: Any) -> dict[str, Any]:
        return {"candidates": [{**good, **row}]}

    cases = {
        "missing": ({"candidates": [{**good, "candidateId": "OTHER"}]}, "no candidate"),
        "infeasible": (cat(status="INFEASIBLE"), "INFEASIBLE, not FEASIBLE"),
        "no-centerline": (cat(), "no usable centerline"),
        "not-a-dict": (cat(centerline=[1.0, 2.0, 3.0]), "no usable centerline"),
        "wrong-length": (
            cat(centerline={"points": [0.0] * 7, "pointCount": 2}),
            "no usable centerline",
        ),
        "one-point": (
            cat(centerline={"points": [0.0, 0.0, 0.0], "pointCount": 1}),
            "no usable centerline",
        ),
        "non-finite": (
            cat(centerline={"points": [0.0, 0.0, 0.0, 1.0, float("nan"), 2.0], "pointCount": 2}),
            "no usable centerline",
        ),
        "not-numeric": (
            cat(centerline={"points": [0.0, 0.0, 0.0, "a", 1.0, 2.0], "pointCount": 2}),
            "no usable centerline",
        ),
    }
    for name, (doc, expected) in cases.items():
        with pytest.raises(ClearancePolicyReconstructionError) as info:
            candidate_points_from_catalogue(doc, "SPIRAL-x")
        assert info.value.code == "LAYOUT_V2_CLEARANCE_MISMATCH", name
        assert info.value.candidate_id == "SPIRAL-x", name
        assert "SPIRAL-x" in str(info.value) and expected in str(info.value), name
    ok = candidate_points_from_catalogue(
        cat(centerline={"points": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0], "pointCount": 2}), "SPIRAL-x"
    )
    assert ok.shape == (2, 3) and ok.flags.c_contiguous and ok.dtype == np.float64


def test_certification_parsers_fail_closed_on_malformed_documents() -> None:
    """A selection / level-access document whose certification block is
    PRESENT but malformed (null, a list, a non-numeric bound, a refinement
    the provenance key cannot digest, …) is the typed
    ClearancePolicyReconstructionError — never a bare KeyError / TypeError /
    ValueError that would surface as a 500 (AC-01D fail-closed lens)."""
    refinement = {"applied": False, "factor": 2, "reason": "NOT_APPLICABLE_EXACT_BASIS"}
    selection = {
        "candidateId": "SPIRAL-x",
        "clearance": {
            "clearanceBasis": "EXACT",
            "requiredClearance": 10.5,
            "conservativeMinimumClearance": 19.6,
            "approximateMinimumClearance": None,
            "clearanceErrorBound": None,
            "satisfied": True,
            "refinement": refinement,
        },
    }
    accesses = {
        "candidateId": "SPIRAL-x",
        "clearanceBasis": "EXACT",
        "clearanceErrorBound": None,
        "clearanceRefinement": refinement,
        "requiredClearance": 10.5,
    }
    good_sel = CandidateCertification.from_selection(json.loads(json.dumps(selection)))
    good_acc = CandidateCertification.from_level_accesses(json.loads(json.dumps(accesses)))
    assert good_sel == good_acc
    assert good_sel.to_dict() == {
        "clearanceBasis": "EXACT",
        "clearanceErrorBound": None,
        "clearanceRefinement": refinement,
        "requiredClearance": 10.5,
    }

    def sel(mutate: Any) -> dict[str, Any]:
        doc = json.loads(json.dumps(selection))
        mutate(doc)
        return doc

    def acc(mutate: Any) -> dict[str, Any]:
        doc = json.loads(json.dumps(accesses))
        mutate(doc)
        return doc

    def _set(path: list[str], value: Any) -> Any:
        def mutate(doc: dict[str, Any]) -> None:
            node = doc
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = value

        return mutate

    def _pop(path: list[str]) -> Any:
        def mutate(doc: dict[str, Any]) -> None:
            node = doc
            for key in path[:-1]:
                node = node[key]
            node.pop(path[-1])

        return mutate

    selection_cases: dict[str, tuple[Any, str]] = {
        "clearance=null": (_set(["clearance"], None), "clearance"),
        "clearance=list": (_set(["clearance"], []), "clearance"),
        "no candidateId": (_pop(["candidateId"]), "candidateId"),
        "candidateId=int": (_set(["candidateId"], 7), "candidateId"),
        "no basis": (_pop(["clearance", "clearanceBasis"]), "clearanceBasis"),
        "basis=int": (_set(["clearance", "clearanceBasis"], 5), "clearanceBasis"),
        "bound=str": (_set(["clearance", "clearanceErrorBound"], "abc"), "clearanceErrorBound"),
        "bound=bool": (_set(["clearance", "clearanceErrorBound"], True), "clearanceErrorBound"),
        "required=str": (_set(["clearance", "requiredClearance"], "abc"), "requiredClearance"),
        "required=null": (_set(["clearance", "requiredClearance"], None), "requiredClearance"),
        "refinement=list": (_set(["clearance", "refinement"], ["x"]), "refinement"),
        "refinement.factor=str": (
            _set(["clearance", "refinement"], {"applied": True, "factor": "abc", "reason": "x"}),
            "refinement",
        ),
        "refinement.shape=str": (
            _set(["clearance", "refinement"], {"applied": True, "factor": 2, "shape": "x"}),
            "refinement",
        ),
    }
    for name, (mutate, key) in selection_cases.items():
        with pytest.raises(ClearancePolicyReconstructionError) as info:
            CandidateCertification.from_selection(sel(mutate))
        assert info.value.code == "LAYOUT_V2_CLEARANCE_MISMATCH", name
        assert key in str(info.value), (name, str(info.value))
    access_cases: dict[str, tuple[Any, str]] = {
        "no refinement": (_pop(["clearanceRefinement"]), "clearanceRefinement"),
        "bound=str": (_set(["clearanceErrorBound"], "abc"), "clearanceErrorBound"),
        "required=nan-string": (_set(["requiredClearance"], "nan"), "requiredClearance"),
        "candidateId=empty": (_set(["candidateId"], ""), "candidateId"),
    }
    for name, (mutate, key) in access_cases.items():
        with pytest.raises(ClearancePolicyReconstructionError) as info:
            CandidateCertification.from_level_accesses(acc(mutate))
        assert info.value.code == "LAYOUT_V2_CLEARANCE_MISMATCH", name
        assert key in str(info.value), (name, str(info.value))
    # a document that is not a dict at all
    with pytest.raises(ClearancePolicyReconstructionError):
        CandidateCertification.from_selection([selection])  # type: ignore[arg-type]


def test_restore_fails_closed_on_recipe_mismatch(
    tabular_search: tuple[Scenario, SyntheticWorld, LayoutV2Search, LayoutSearchResult],
) -> None:
    sc, world, s, res = tabular_search
    wid = res.winner_id
    assert wid is not None
    cand = res.candidate(wid)
    assert cand is not None and cand.points is not None
    cert = CandidateCertification.from_selection(
        json.loads(json.dumps(materialize_effective_ramp(res, cand, s.evaluator, "REV")))
    )
    pts = candidate_points_from_catalogue(json.loads(json.dumps(res.to_dict())), wid)
    # a correct certification passes
    restore_candidate_policy(sc, world, certification=cert, points=pts)
    assert cert.refinement is not None
    tampered = {
        "basis": dataclasses.replace(cert, basis="COARSE_CONSERVATIVE"),
        "error-bound": dataclasses.replace(cert, error_bound=1e-3),
        "refinement-reason": dataclasses.replace(
            cert, refinement={**cert.refinement, "reason": "DISABLED"}
        ),
        "required-clearance": dataclasses.replace(
            cert, required_clearance=cert.required_clearance + 1e-3
        ),
    }
    for name, bad in tampered.items():
        with pytest.raises(ClearancePolicyReconstructionError) as info:
            restore_candidate_policy(sc, world, certification=bad, points=pts)  # never returns
        assert info.value.code == "LAYOUT_V2_CLEARANCE_MISMATCH", name
        assert info.value.candidate_id == wid, name


def test_restore_normalises_points_to_a_contiguous_float64_array(
    tabular_search: tuple[Scenario, SyntheticWorld, LayoutV2Search, LayoutSearchResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The determinism probe measured that a strided (N, 3) view changes
    bits in ``Frame.world_to_local``; the recipe must only ever see a
    C-contiguous float64 copy, equal in value to the catalogue points."""
    sc, world, s, res = tabular_search
    wid = res.winner_id
    assert wid is not None
    cand = res.candidate(wid)
    assert cand is not None and cand.points is not None
    cert = CandidateCertification.from_selection(
        json.loads(json.dumps(materialize_effective_ramp(res, cand, s.evaluator, "REV")))
    )
    pts = candidate_points_from_catalogue(json.loads(json.dumps(res.to_dict())), wid)
    wide = np.zeros((pts.shape[0], 6), dtype=np.float64)
    wide[:, ::2] = pts
    strided = wide[:, ::2]
    assert not strided.flags.c_contiguous and np.array_equal(strided, pts)
    seen: list[np.ndarray] = []  # type: ignore[type-arg]
    real = certification.build_candidate_policy

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(kwargs["points"])
        return real(*args, **kwargs)

    monkeypatch.setattr(certification, "build_candidate_policy", spy)
    restore_candidate_policy(sc, world, certification=cert, points=strided)
    assert len(seen) == 1
    got = seen[0]
    assert got.flags.c_contiguous and got.dtype == np.float64 and got.shape == pts.shape
    assert not np.shares_memory(got, strided)
    assert np.array_equal(got, pts)


# --------------------------------------------------------------------------- #
# leaf modules + ONE setup definition
# --------------------------------------------------------------------------- #


def test_setup_module_is_a_leaf(
    tabular_search: tuple[Scenario, SyntheticWorld, LayoutV2Search, LayoutSearchResult],
) -> None:
    code = (
        "import sys, minegen.layout.setup, minegen.layout.certification; "
        "assert 'minegen.layout.search' not in sys.modules; "
        "assert 'minegen.layout.results' not in sys.modules; "
        "assert not any(m.startswith('minegen.services') for m in sys.modules)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
    # setup.py never imports certification (certification imports setup)
    code = (
        "import sys, minegen.layout.setup; assert 'minegen.layout.certification' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
    # run() uses the shared setup: its products are the ones the result carries
    sc, world, _, res = tabular_search
    setup = build_search_setup(sc, world)
    assert setup.section_error is None
    assert [lv.level_id for lv in setup.levels] == [lv.level_id for lv in res.levels]
    assert [lv.level_id for lv in setup.sections.serviceable()] == list(res.serviceable_ids)
    assert setup.required_clearance == res.required_clearance
    assert np.array_equal(setup.portal, res.portal)
    assert setup.portal_generated == res.portal_generated
    assert setup.track is not None and setup.track.to_dict() == res.track


# --------------------------------------------------------------------------- #
# COLD service chain: zero run() calls, byte-equal artifacts
# --------------------------------------------------------------------------- #


def _downstream(svc: DesignService, sid: str) -> dict[str, Any]:
    svc.generate_levels(sid)
    svc.generate_tunnel(sid)
    svc.generate_development_mesh(sid)
    svc.generate_network(sid)
    return {
        "levels": _sha(json.loads(svc.levels_path(sid).read_text())),
        "tunnel": _sha(json.loads(svc.tunnel_report_path(sid).read_text())),
        "tunnelGlb": hashlib.sha256(svc.tunnel_glb_path(sid).read_bytes()).hexdigest(),
        "developmentMesh": _sha(json.loads(svc.development_mesh_report_path(sid).read_text())),
        "developmentGlb": hashlib.sha256(
            svc.development_mesh_glb_path(sid).read_bytes()
        ).hexdigest(),
        "network": _sha(json.loads(svc.network_path(sid).read_text())),
    }


def _layout_artifact_hashes(svc: DesignService, sid: str) -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (
            svc.layout_path(sid),
            svc.layout_selected_path(sid),
            svc.level_accesses_path(sid),
        )
    }


def test_restore_equals_stage4_policy_on_the_tabular_service_chain_cold(
    store: ScenarioStore,
    world_service: WorldService,
    design_service: DesignService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = store.create(_create_of(small_scenario())).id
    world_service.generate(sid)
    cat = design_service.generate_layout_v2(sid)
    winner = cat["winnerId"]
    assert winner is not None, cat["status"]
    design_service.activate_layout_candidate(sid, winner)
    layout_before = _layout_artifact_hashes(design_service, sid)

    # WARM: the generating service
    warm = _downstream(design_service, sid)
    for p in (
        design_service.levels_path(sid),
        design_service.tunnel_report_path(sid),
        design_service.tunnel_glb_path(sid),
        design_service.development_mesh_report_path(sid),
        design_service.development_mesh_glb_path(sid),
        design_service.network_path(sid),
    ):
        Path(p).unlink()

    # COLD: fresh WorldService (npz reload, new orebody object) + fresh
    # DesignService, with the search re-run forbidden outright
    monkeypatch.setattr(LayoutV2Search, "run", _forbidden_run)
    cold = DesignService(store, WorldService(store))
    assert cold._layouts == {}
    cold_hashes = _downstream(cold, sid)
    assert cold_hashes == warm
    assert cold._layouts == {}  # restore populated no search object
    assert _layout_artifact_hashes(cold, sid) == layout_before  # nothing rewritten
    # the restore is served from the identity-keyed cache within one process
    _, w = cold.worlds.load(sid)
    p1 = cold._active_clearance_policy(sid, w)
    p2 = cold._active_clearance_policy(sid, w)
    assert p1 is p2
    # idempotent re-select / re-activate of the selected candidate: no run()
    assert cold.select_layout_candidate(sid, winner) == design_service.layout_selected(sid)
    assert cold.activate_layout_candidate(sid, winner)["selected"] == (
        design_service.layout_selected(sid)
    )
    assert cold._layouts == {}
    assert _layout_artifact_hashes(cold, sid) == layout_before


# --------------------------------------------------------------------------- #
# sync API branches: typed 409, never 500
# --------------------------------------------------------------------------- #


def test_sync_tunnel_and_development_mesh_fail_closed_with_typed_409(
    client: TestClient, design_service: DesignService, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_smoothing_api import _prepare

    sid = _prepare(client)
    base = f"/api/v1/scenarios/{sid}/design"
    r = client.post(f"{base}/layout-v2", params={"sync": "true"})
    assert r.status_code == 200, r.text
    winner = r.json()["winnerId"]
    assert winner is not None
    assert client.post(f"{base}/layout-v2/activate", json={"candidateId": winner}).status_code == (
        200
    )
    monkeypatch.setattr(LayoutV2Search, "run", _forbidden_run)
    path = design_service.layout_selected_path(sid)
    pristine = path.read_text(encoding="utf-8")

    def tamper(mutate: Any) -> None:
        doc = json.loads(pristine)
        mutate(doc)
        path.write_text(json.dumps(doc), encoding="utf-8")

    def bump_bound(doc: dict[str, Any]) -> None:
        bound = doc["clearance"]["clearanceErrorBound"]
        doc["clearance"]["clearanceErrorBound"] = (bound or 0.0) + 1e-3

    def stale_revision(doc: dict[str, Any]) -> None:
        doc["layoutRevision"] = "0000000000000000"

    def null_clearance(doc: dict[str, Any]) -> None:
        doc["clearance"] = None

    def list_clearance(doc: dict[str, Any]) -> None:
        doc["clearance"] = []

    def str_bound(doc: dict[str, Any]) -> None:
        doc["clearance"]["clearanceErrorBound"] = "abc"

    def str_required(doc: dict[str, Any]) -> None:
        doc["clearance"]["requiredClearance"] = "abc"

    def list_refinement(doc: dict[str, Any]) -> None:
        doc["clearance"]["refinement"] = ["x"]

    def no_candidate_id(doc: dict[str, Any]) -> None:
        doc.pop("candidateId")

    def unknown_candidate(doc: dict[str, Any]) -> None:
        doc["candidateId"] = "NO-SUCH-CANDIDATE"

    for mutate, code in (
        (bump_bound, "LAYOUT_V2_CLEARANCE_MISMATCH"),
        (stale_revision, "LAYOUT_V2_SELECTION_STALE"),
        # present-but-malformed documents: the fail-closed lens found these
        # leaking as untyped exceptions (500); they are typed 409s now
        (null_clearance, "LAYOUT_V2_CLEARANCE_MISMATCH"),
        (list_clearance, "LAYOUT_V2_CLEARANCE_MISMATCH"),
        (str_bound, "LAYOUT_V2_CLEARANCE_MISMATCH"),
        (str_required, "LAYOUT_V2_CLEARANCE_MISMATCH"),
        (list_refinement, "LAYOUT_V2_CLEARANCE_MISMATCH"),
        (no_candidate_id, "LAYOUT_V2_CLEARANCE_MISMATCH"),
        (unknown_candidate, "LAYOUT_V2_CLEARANCE_MISMATCH"),
    ):
        tamper(mutate)
        for endpoint, params in (
            ("levels", {}),
            ("tunnel", {"sync": "true"}),
            ("development-mesh", {"sync": "true"}),
        ):
            r = client.post(f"{base}/{endpoint}", params=params)
            assert r.status_code == 409, (endpoint, code, r.status_code, r.text)
            assert r.json()["detail"]["code"] == code, (endpoint, r.text)
            assert not design_service.levels_path(sid).exists()
            assert not design_service.tunnel_report_path(sid).exists()
            assert not design_service.development_mesh_report_path(sid).exists()
            # nothing is cached on a failed restore
            assert not design_service._selected_policies
    path.write_text(pristine, encoding="utf-8")
    r = client.post(f"{base}/tunnel", params={"sync": "true"})
    assert r.status_code == 200, r.text
