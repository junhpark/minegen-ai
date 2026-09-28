"""Phase 22C — Layout Development Economics (rules 204–206).

C-1  formula over persisted candidate quantities
C-2  ranking / winner / selection preservation (never re-sorted by cost)
C-3  no hidden economics (NOT_CONFIGURED carries geometry facts, no cost)
C-4  scope: LEGACY active + catalogue → INACTIVE_LAYOUT_V2
C-5  malformed candidate quantities → typed 409 through the shared grammar
C-6  snapshot race on every consumed source → READ_SNAPSHOT_CHANGED
C-7  read-only proof (scenario, arrays, derived, economics untouched)
C-8  no generation entry point runs
C-9  no whole-mine economics vocabulary in the payload
C-10 determinism

The unit half drives the pure builder with the hand-written catalogue of
``tests/test_design_assessment.py`` (the SAME documents the Phase 20D.3
assessment is proven on); the API half writes those documents beside a real
generated world and one test runs the REAL layout-v2 catalogue.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import minegen.services.analysis_service as analysis_service_module
from minegen.analysis.economics import EconomicsConfig
from minegen.analysis.layout_comparison import (
    COMPARISON_DISCLAIMER,
    EXCLUDED_COST_KINDS,
    INCLUDED_COST_KINDS,
    LayoutComparisonPayload,
    build_layout_comparison,
    validate_layout_economics_shape,
)
from minegen.assessment.builder import (
    CatalogueShapeError,
    build_design_assessment,
    validate_catalogue_shape,
)
from minegen.assessment.models import DesignAssessmentSources
from minegen.core.artifacts import (
    LAYOUT_V2_ARTIFACT,
    LAYOUT_V2_SELECTED_ARTIFACT,
    LEVEL_ACCESSES_ARTIFACT,
    RAMP_SOURCE_FILE,
)
from minegen.core.models import ScenarioCreate
from minegen.layout.search import LayoutV2Search
from minegen.services.artifact_reader import ArtifactReader
from minegen.services.design_service import DesignService
from minegen.services.scenario_service import ScenarioStore
from minegen.services.world_service import WorldService
from tests import analysis_support as fx
from tests.test_artifact_reader import _accesses, _selection
from tests.test_design_assessment import (
    RANK2,
    RANK3,
    RANKING,
    WINNER,
    _cand,
    _rev,
    _write,
    catalogue,
    selection,
)
from tests.test_layout_v2_api import _generate_layout, _winner
from tests.test_smoothing_api import _prepare
from tests.test_world_api import _create

ROUTE = "/analysis/layout-comparison"
CONFIG = "/analysis/economics-config"

#: whole-mine economics that must NEVER appear in the comparison payload (C-9)
FORBIDDEN_KEYS = (
    "npv",
    "revenue",
    "processingCost",
    "productionMiningCost",
    "fixedOperatingCost",
    "initialCapitalCost",
    "backfillCost",
    "plannedMinedTonnes",
)
FORBIDDEN_WORDS = (
    "recommended",
    "optimal",
    "best option",
    "economic winner",
    "bankable",
    "feasible project",
    "economically viable",
    "profitable",
    "total mine development cost",
)


def _economics(ramp: float = 10.0, access: float = 5.0) -> EconomicsConfig:
    doc = fx.config_doc()
    doc["developmentCosts"]["rampPerM"] = ramp
    doc["developmentCosts"]["levelAccessPerM"] = access
    return EconomicsConfig.model_validate(doc)


def _quantities(cat: dict[str, Any], lengths: dict[str, tuple[float, float]]) -> dict[str, Any]:
    """Override ``(length3d, totalAccessLength)`` per candidate id."""
    for cand in cat["candidates"]:
        if cand["candidateId"] in lengths:
            ramp, access = lengths[cand["candidateId"]]
            cand["diagnostics"] = {**cand["diagnostics"], "length3d": ramp}
            cand["access"] = {**cand["access"], "totalAccessLength": access}
    return cat


def build(
    cat: dict[str, Any] | None = None,
    sel: dict[str, Any] | None = None,
    *,
    active_source: str = "LAYOUT_V2",
    economics: EconomicsConfig | None = None,
    world_generated: bool = True,
) -> LayoutComparisonPayload:
    return build_layout_comparison(
        catalogue=cat,
        selected=sel,
        active_source=active_source,
        world_generated=world_generated,
        economics=economics,
        economics_revision=None if economics is None else "eco-rev",
        layout_revision=None if cat is None else "layout-rev",
        selection_revision=None if sel is None else "sel-rev",
    )


def _dump(payload: LayoutComparisonPayload) -> str:
    return payload.model_dump_json(by_alias=True)


# --------------------------------------------------------------------------- #
# C-1 formula
# --------------------------------------------------------------------------- #


def test_c1_comparable_cost_is_persisted_length_times_rate() -> None:
    cat = _quantities(catalogue(), {WINNER: (1000.0, 200.0)})
    payload = build(cat, selection(WINNER), economics=_economics(10.0, 5.0))
    assert payload.availability == "AVAILABLE" and payload.reason is None
    row = next(r for r in payload.rows if r.candidate_id == WINNER)
    assert row.main_ramp_length_m == 1000.0
    assert row.level_access_length_m == 200.0
    assert row.comparable_development_length_m == 1200.0
    assert row.ramp_cost == 10000.0
    assert row.level_access_cost == 1000.0
    assert row.comparable_development_cost == 11000.0
    assert row.winner and row.selected and row.catalogue_rank == 1
    assert row.cost_delta_from_winner == 0.0 and row.cost_delta_from_selected == 0.0
    assert payload.ramp_rate_per_m == 10.0 and payload.level_access_rate_per_m == 5.0
    assert payload.currency_code == "USD"
    assert (
        payload.comparison_basis.included == list(INCLUDED_COST_KINDS) == ["RAMP", "LEVEL_ACCESS"]
    )
    assert payload.comparison_basis.excluded == list(EXCLUDED_COST_KINDS)
    assert {"DRIFT", "CROSSCUT", "SHAFT", "PRODUCTION", "REVENUE", "NPV"} <= set(
        payload.comparison_basis.excluded
    )
    assert payload.disclaimer == COMPARISON_DISCLAIMER
    assert "Comparable" in payload.disclaimer and "not total mine cost" in payload.disclaimer


def test_c1_every_row_quantity_is_the_candidate_field_and_scores_are_the_assessment_scores() -> (
    None
):
    cat = catalogue()
    payload = build(cat, selection(RANK2), economics=_economics(3.0, 7.0))
    by_id = {c["candidateId"]: c for c in cat["candidates"]}
    assessment = build_design_assessment(
        catalogue=cat,
        selected=selection(RANK2),
        capability=None,
        sources=DesignAssessmentSources(
            active_source="LAYOUT_V2",
            layout_v2_revision="x",
            selected_layout_revision="y",
            level_accesses_revision=None,
            network_revision=None,
            capability_graph_revision=None,
        ),
        max_comparison_rows=len(RANKING),
    )
    assessed = {r.candidate_id: r for r in assessment.candidate_comparison}
    for row in payload.rows:
        cand = by_id[row.candidate_id]
        assert row.main_ramp_length_m == cand["diagnostics"]["length3d"]
        assert row.level_access_length_m == cand["access"]["totalAccessLength"]
        assert row.ramp_cost == row.main_ramp_length_m * 3.0
        assert row.level_access_cost == row.level_access_length_m * 7.0
        assert row.comparable_development_cost == row.ramp_cost + row.level_access_cost
        assert row.catalogue_rank == cand["rank"] and row.family == cand["family"]
        # ONE score semantics with the Phase 20D.3 assessment (rule 203 / 206)
        assert row.scores == assessed[row.candidate_id].scores
        assert row.score_delta_from_winner == assessed[row.candidate_id].deltas
    assert payload.selected_candidate_id == RANK2
    sel = next(r for r in payload.rows if r.selected)
    assert sel.candidate_id == RANK2 and not sel.winner
    assert sel.cost_delta_from_selected == 0.0
    win = next(r for r in payload.rows if r.winner)
    assert win.cost_delta_from_winner == 0.0
    assert sel.cost_delta_from_winner == pytest.approx(
        sel.comparable_development_cost - win.comparable_development_cost
    )


# --------------------------------------------------------------------------- #
# C-2 ranking preservation
# --------------------------------------------------------------------------- #


def test_c2_rows_follow_the_persisted_ranking_even_when_cost_disagrees() -> None:
    # ranking [WINNER, RANK2, RANK3]: make RANK2 the CHEAPEST and the winner
    # the most EXPENSIVE — the order, winner and selection must not move
    cat = _quantities(
        catalogue(), {WINNER: (3000.0, 300.0), RANK2: (1000.0, 100.0), RANK3: (2000.0, 200.0)}
    )
    payload = build(cat, selection(WINNER), economics=_economics(1.0, 1.0))
    ids = [r.candidate_id for r in payload.rows]
    assert ids == RANKING  # the persisted order, six FEASIBLE ranked candidates
    costs = {r.candidate_id: r.comparable_development_cost for r in payload.rows}
    assert costs[RANK2] < costs[RANK3] < costs[WINNER]
    assert payload.winner_id == WINNER and payload.selected_candidate_id == WINNER
    assert [r.catalogue_rank for r in payload.rows] == [1, 2, 3, 4, 5, 6]
    assert next(r for r in payload.rows if r.winner).candidate_id == WINNER
    # no cost rank, no cheapest flag, no recommendation anywhere in the DTO
    dumped = json.loads(_dump(payload))
    for row in dumped["rows"]:
        assert "costRank" not in row and "cheapest" not in row and "recommended" not in row
    # a NON-ranked candidate (INFEASIBLE / NOT_VALIDATED) is never a row
    assert all(r.status == "FEASIBLE" for r in payload.rows)
    assert len(payload.rows) == len(RANKING) < len(cat["candidates"])


def test_c2_the_catalogue_and_selection_documents_are_not_mutated() -> None:
    cat = catalogue()
    sel = selection(RANK2)
    before = json.dumps(cat, sort_keys=True), json.dumps(sel, sort_keys=True)
    build(cat, sel, economics=_economics())
    build(cat, sel)
    assert (json.dumps(cat, sort_keys=True), json.dumps(sel, sort_keys=True)) == before


# --------------------------------------------------------------------------- #
# C-3 no hidden economics
# --------------------------------------------------------------------------- #


def test_c3_without_economics_the_geometry_rows_stay_and_every_cost_is_null() -> None:
    payload = build(catalogue(), selection(WINNER), economics=None)
    assert payload.availability == "NOT_CONFIGURED"
    assert payload.reason == "planning economics not configured"
    assert payload.currency_code is None
    assert payload.ramp_rate_per_m is None and payload.level_access_rate_per_m is None
    assert payload.economics_revision is None
    assert [r.candidate_id for r in payload.rows] == RANKING
    for row in payload.rows:
        assert row.main_ramp_length_m > 0 and row.level_access_length_m > 0
        assert row.ramp_cost is None and row.level_access_cost is None
        assert row.comparable_development_cost is None
        assert row.cost_delta_from_winner is None and row.cost_delta_from_selected is None
        assert row.scores is not None  # engineering facts are still shown
    dumped = json.loads(_dump(payload))
    numeric_cost_fields = [
        row[k]
        for row in dumped["rows"]
        for k in ("rampCost", "levelAccessCost", "comparableDevelopmentCost")
    ]
    assert all(v is None for v in numeric_cost_fields)  # no demo default sneaks in


# --------------------------------------------------------------------------- #
# C-4 scope
# --------------------------------------------------------------------------- #


def test_c4_scope_follows_the_active_source_and_the_catalogue_presence() -> None:
    inactive = build(catalogue(), selection(WINNER), active_source="LEGACY", economics=_economics())
    assert inactive.scope == "INACTIVE_LAYOUT_V2" and inactive.active_source == "LEGACY"
    assert inactive.availability == "AVAILABLE"
    assert inactive.selected_candidate_id == WINNER and inactive.winner_id == WINNER
    assert [r.candidate_id for r in inactive.rows] == RANKING
    active = build(
        catalogue(), selection(WINNER), active_source="LAYOUT_V2", economics=_economics()
    )
    assert active.scope == "ACTIVE_DESIGN"
    assert [json.loads(_dump(r)) for r in active.rows] == [
        json.loads(_dump(r)) for r in inactive.rows
    ]  # the scope changes nothing in the rows
    none = build(None, None, active_source="LEGACY", economics=_economics())
    assert none.scope == "NONE" and none.availability == "NOT_AVAILABLE"
    assert none.reason == "layout-v2 catalogue not generated"
    assert none.rows == [] and none.winner_id is None and none.layout_revision is None
    assert none.ramp_rate_per_m == 10.0  # the configured rates are still reported
    no_world = build(None, None, world_generated=False)
    assert no_world.availability == "NOT_AVAILABLE" and no_world.reason == "world not generated"


# --------------------------------------------------------------------------- #
# C-5 malformed quantities
# --------------------------------------------------------------------------- #


def _corrupt(kind: str) -> dict[str, Any]:
    cat = catalogue()
    target = next(c for c in cat["candidates"] if c["candidateId"] == RANK3)
    if kind == "missing_length3d":
        target["diagnostics"] = {"maxAbsGradient": 0.12}
    elif kind == "no_diagnostics":
        target["diagnostics"] = None
    elif kind == "nan_length3d":
        target["diagnostics"] = {**target["diagnostics"], "length3d": math.nan}
    elif kind == "negative_length3d":
        target["diagnostics"] = {**target["diagnostics"], "length3d": -1.0}
    elif kind == "string_length3d":
        target["diagnostics"] = {**target["diagnostics"], "length3d": "1485.86"}
    elif kind == "missing_total_access":
        target["access"] = {k: v for k, v in target["access"].items() if k != "totalAccessLength"}
    elif kind == "no_access":
        target["access"] = None
    elif kind == "negative_total_access":
        target["access"] = {**target["access"], "totalAccessLength": -5.0}
    elif kind == "duplicate_id":
        cat["candidates"].append(_cand(RANK3))
    elif kind == "ranking_unknown_id":
        cat["ranking"] = [*cat["ranking"], "SPIRAL-n9-CW-e+0-g0.999"]
    else:  # pragma: no cover
        raise AssertionError(kind)
    return cat


CORRUPTIONS = (
    "missing_length3d",
    "no_diagnostics",
    "nan_length3d",
    "negative_length3d",
    "string_length3d",
    "missing_total_access",
    "no_access",
    "negative_total_access",
    "duplicate_id",
    "ranking_unknown_id",
)


@pytest.mark.parametrize("kind", CORRUPTIONS)
def test_c5_malformed_candidate_quantities_are_a_typed_shape_error(kind: str) -> None:
    cat = _corrupt(kind)
    with pytest.raises(CatalogueShapeError) as err:
        build(cat, selection(WINNER), economics=_economics())
    msg = str(err.value)
    assert msg.startswith("$.")  # the JSON path is named
    if kind in ("duplicate_id", "ranking_unknown_id"):
        return  # the shared grammar refused first (no second grammar)
    assert RANK3 in msg or "candidates[2]" in msg


def test_c5_the_extension_never_widens_the_assessment_requirements() -> None:
    # a catalogue whose ranked candidate carries no diagnostics / access still
    # passes the shared grammar (the assessment keeps answering) — only THIS
    # consumer refuses it
    cat = _corrupt("no_diagnostics")
    validate_catalogue_shape(cat, selection(WINNER))
    with pytest.raises(CatalogueShapeError, match=r"\$\.candidates\[2\]\.diagnostics"):
        validate_layout_economics_shape(cat)
    cat = _corrupt("no_access")
    validate_catalogue_shape(cat, selection(WINNER))
    with pytest.raises(CatalogueShapeError, match=r"\$\.candidates\[2\]\.access"):
        validate_layout_economics_shape(cat)
    # an UNRANKED candidate without quantities is fine: it is never a row
    cat = catalogue()
    nv = next(c for c in cat["candidates"] if c["status"] == "NOT_VALIDATED")
    assert nv["diagnostics"] is not None and nv["access"] is None
    build(cat, selection(WINNER), economics=_economics())


# --------------------------------------------------------------------------- #
# C-9 vocabulary, C-10 determinism (unit)
# --------------------------------------------------------------------------- #


def _assert_vocabulary(text: str) -> None:
    lower = text.lower()
    for key in FORBIDDEN_KEYS:
        assert f'"{key}"' not in text, key
    for word in FORBIDDEN_WORDS:
        assert word not in lower, word


def test_c9_payload_carries_no_whole_mine_economics_vocabulary() -> None:
    for payload in (
        build(catalogue(), selection(WINNER), economics=_economics()),
        build(catalogue(), None),
        build(None, None, active_source="LEGACY", economics=_economics()),
    ):
        _assert_vocabulary(_dump(payload))


def test_c10_the_projection_is_deterministic_and_carries_no_timestamp() -> None:
    a = _dump(build(catalogue(), selection(WINNER), economics=_economics()))
    b = _dump(build(catalogue(), selection(WINNER), economics=_economics()))
    assert a == b

    def keys(node: Any) -> set[str]:
        out: set[str] = set()
        if isinstance(node, dict):
            for k, v in node.items():
                out.add(str(k))
                out |= keys(v)
        elif isinstance(node, list):
            for v in node:
                out |= keys(v)
        return out

    for key in keys(json.loads(a)):
        low = key.lower()
        assert "time" not in low and "stamp" not in low and not low.endswith("at"), key


# --------------------------------------------------------------------------- #
# API half — hand-written catalogue beside a REAL generated world
# --------------------------------------------------------------------------- #


def _file_state(*dirs: Path) -> dict[str, tuple[int, int, str]]:
    state: dict[str, tuple[int, int, str]] = {}
    for d in dirs:
        for p in sorted(d.iterdir()):
            if p.is_file():
                st = p.stat()
                state[str(p)] = (
                    st.st_size,
                    st.st_mtime_ns,
                    hashlib.sha256(p.read_bytes()).hexdigest(),
                )
    return state


def _get(client: TestClient, sid: str, status: int = 200) -> dict[str, Any]:
    r = client.get(f"/api/v1/scenarios/{sid}{ROUTE}")
    assert r.status_code == status, r.text
    body: dict[str, Any] = r.json()
    return body


def _stack(
    client: TestClient,
    store: ScenarioStore,
    *,
    cat: dict[str, Any] | None = None,
    selected_id: str | None = None,
    ramp_source: str | None = None,
) -> str:
    sid = _prepare(client)
    derived = store.derived_dir(sid)
    if cat is not None:
        _write(derived / LAYOUT_V2_ARTIFACT, cat)
    if selected_id is not None:
        rev = _rev(derived / LAYOUT_V2_ARTIFACT)
        _write(
            derived / LAYOUT_V2_SELECTED_ARTIFACT, {**_selection(rev), "candidateId": selected_id}
        )
        _write(derived / LEVEL_ACCESSES_ARTIFACT, {**_accesses(rev), "candidateId": selected_id})
    if ramp_source is not None:
        _write(derived / RAMP_SOURCE_FILE, {"activeSource": ramp_source})
    return sid


def test_api_availability_ladder_no_world_no_catalogue_not_configured(
    client: TestClient, store: ScenarioStore
) -> None:
    sid = _create(client)
    body = _get(client, sid)
    assert body["status"] == "SUCCESS" and body["availability"] == "NOT_AVAILABLE"
    assert body["reason"] == "world not generated" and body["rows"] == []
    assert body["scope"] == "NONE" and body["activeSource"] == "LEGACY"
    assert client.get(f"/api/v1/scenarios/NOPE{ROUTE}").status_code == 404
    assert client.post(f"/api/v1/scenarios/{sid}/world/generate").status_code == 200
    body = _get(client, sid)
    assert body["availability"] == "NOT_AVAILABLE"
    assert body["reason"] == "layout-v2 catalogue not generated" and body["rows"] == []
    assert body["layoutRevision"] is None and body["economicsRevision"] is None
    # a hand-written catalogue, no economics: geometry facts, null costs (C-3)
    derived = store.derived_dir(sid)
    _write(derived / LAYOUT_V2_ARTIFACT, catalogue())
    body = _get(client, sid)
    assert body["availability"] == "NOT_CONFIGURED"
    assert body["reason"] == "planning economics not configured"
    assert body["scope"] == "INACTIVE_LAYOUT_V2"  # LEGACY default + catalogue
    assert body["layoutRevision"] == _rev(derived / LAYOUT_V2_ARTIFACT)
    assert body["selectionRevision"] is None and body["selectedCandidateId"] is None
    assert [r["candidateId"] for r in body["rows"]] == RANKING
    assert all(r["comparableDevelopmentCost"] is None for r in body["rows"])
    assert all(r["mainRampLengthM"] == 1485.86 for r in body["rows"])
    _assert_vocabulary(json.dumps(body))


def test_api_configured_costs_read_only_and_deterministic(
    client: TestClient, store: ScenarioStore
) -> None:
    cat = _quantities(catalogue(), {WINNER: (1000.0, 200.0)})
    sid = _stack(client, store, cat=cat, selected_id=RANK2, ramp_source="LAYOUT_V2")
    doc = fx.config_doc()  # rampPerM 10, levelAccessPerM 8
    put = client.put(f"/api/v1/scenarios/{sid}{CONFIG}", json=doc)
    assert put.status_code == 200, put.text
    scenario_dir = store.scenario_dir(sid)
    derived = store.derived_dir(sid)
    before = _file_state(scenario_dir, derived)
    body = _get(client, sid)
    assert body["availability"] == "AVAILABLE" and body["reason"] is None
    assert body["scope"] == "ACTIVE_DESIGN" and body["activeSource"] == "LAYOUT_V2"
    assert body["winnerId"] == WINNER and body["selectedCandidateId"] == RANK2
    assert body["economicsRevision"] == put.json()["revision"]
    assert body["layoutRevision"] == _rev(derived / LAYOUT_V2_ARTIFACT)
    assert body["selectionRevision"] == _rev(derived / LAYOUT_V2_SELECTED_ARTIFACT)
    assert body["currencyCode"] == "USD"
    assert body["rampRatePerM"] == 10.0 and body["levelAccessRatePerM"] == 8.0
    rows = {r["candidateId"]: r for r in body["rows"]}
    assert list(rows) == RANKING
    win = rows[WINNER]
    assert (win["rampCost"], win["levelAccessCost"], win["comparableDevelopmentCost"]) == (
        10000.0,
        1600.0,
        11600.0,
    )
    assert win["winner"] is True and win["selected"] is False
    assert rows[RANK2]["selected"] is True and rows[RANK2]["winner"] is False
    assert rows[RANK2]["costDeltaFromSelected"] == 0.0
    assert rows[RANK2]["costDeltaFromWinner"] == pytest.approx(
        rows[RANK2]["comparableDevelopmentCost"] - 11600.0
    )
    assert body["comparisonBasis"] == {
        "included": list(INCLUDED_COST_KINDS),
        "excluded": list(EXCLUDED_COST_KINDS),
    }
    # C-7 read-only: nothing under the scenario moved, nothing new appeared
    assert _file_state(scenario_dir, derived) == before
    assert not (derived / "layout_comparison.json").exists()
    # C-10 determinism: byte-identical repeat
    assert client.get(f"/api/v1/scenarios/{sid}{ROUTE}").json() == body
    _assert_vocabulary(json.dumps(body))
    # the catalogue itself is untouched by the route (never modified, §3)
    assert json.loads((derived / LAYOUT_V2_ARTIFACT).read_text()) == cat


def test_api_c4_legacy_active_with_a_dormant_selection_is_inactive_scope(
    client: TestClient, store: ScenarioStore
) -> None:
    sid = _stack(client, store, cat=catalogue(), selected_id=WINNER, ramp_source="LEGACY")
    client.put(f"/api/v1/scenarios/{sid}{CONFIG}", json=fx.config_doc())
    body = _get(client, sid)
    assert body["scope"] == "INACTIVE_LAYOUT_V2" and body["activeSource"] == "LEGACY"
    assert body["availability"] == "AVAILABLE"
    assert body["selectedCandidateId"] == WINNER and body["winnerId"] == WINNER
    assert [r["candidateId"] for r in body["rows"]] == RANKING
    # the assessment agrees on the scope from the same artifacts
    a = client.get(f"/api/v1/scenarios/{sid}/design/assessment").json()
    assert a["layoutScope"] == "INACTIVE_LAYOUT_V2" and a["selectedCandidateId"] == WINNER


@pytest.mark.parametrize("kind", ("missing_length3d", "nan_length3d", "duplicate_id"))
def test_api_c5_malformed_catalogue_is_artifact_malformed_never_500(
    client: TestClient, store: ScenarioStore, kind: str
) -> None:
    sid = _stack(client, store, cat=_corrupt(kind))
    r = client.get(f"/api/v1/scenarios/{sid}{ROUTE}")
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "ARTIFACT_MALFORMED"
    assert LAYOUT_V2_ARTIFACT in r.json()["detail"]["message"]
    if kind == "missing_length3d":
        # the assessment does not read length3d: it still answers (§14)
        assert client.get(f"/api/v1/scenarios/{sid}/design/assessment").status_code == 200


def test_api_c5_stale_selection_fails_closed(client: TestClient, store: ScenarioStore) -> None:
    sid = _stack(client, store, cat=catalogue(), selected_id=WINNER)
    derived = store.derived_dir(sid)
    # the catalogue is rewritten → the selection belongs to another revision
    _write(derived / LAYOUT_V2_ARTIFACT, {**catalogue(), "performance": {"totalSeconds": 9.9}})
    r = client.get(f"/api/v1/scenarios/{sid}{ROUTE}")
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "LAYOUT_V2_SELECTION_STALE"


def test_api_c6_scenario_put_between_bound_read_and_snapshot_is_read_snapshot_changed(
    client: TestClient, store: ScenarioStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = _stack(client, store, cat=catalogue())
    original_snapshot = ArtifactReader.snapshot
    raced = {"n": 0}

    def racing_snapshot(self: ArtifactReader, scenario_id: str, *args: Any, **kw: Any) -> Any:
        if raced["n"] == 0:
            raced["n"] += 1
            doc = store.get(scenario_id)
            body = doc.model_dump(exclude={"id", "schema_version"})
            body["name"] = "renamed by a concurrent PUT"
            store.replace(scenario_id, ScenarioCreate.model_validate(body))
        return original_snapshot(self, scenario_id, *args, **kw)

    projections = {"n": 0}
    real_build = analysis_service_module.build_layout_comparison

    def counting_build(**kw: Any) -> Any:
        projections["n"] += 1
        return real_build(**kw)

    monkeypatch.setattr(ArtifactReader, "snapshot", racing_snapshot)
    monkeypatch.setattr(analysis_service_module, "build_layout_comparison", counting_build)
    r = client.get(f"/api/v1/scenarios/{sid}{ROUTE}")
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "READ_SNAPSHOT_CHANGED"
    assert raced["n"] == 1 and projections["n"] == 0


@pytest.mark.parametrize(
    "moved",
    ("scenario.json", LAYOUT_V2_ARTIFACT, LAYOUT_V2_SELECTED_ARTIFACT, "economics.json"),
)
def test_api_c6_a_source_moving_during_the_projection_is_read_snapshot_changed(
    client: TestClient, store: ScenarioStore, monkeypatch: pytest.MonkeyPatch, moved: str
) -> None:
    sid = _stack(client, store, cat=catalogue(), selected_id=WINNER)
    client.put(f"/api/v1/scenarios/{sid}{CONFIG}", json=fx.config_doc())
    derived = store.derived_dir(sid)
    real_build = analysis_service_module.build_layout_comparison

    def mutating_build(**kw: Any) -> Any:
        out = real_build(**kw)
        if moved == "scenario.json":
            doc = store.get(sid)
            body = doc.model_dump(exclude={"id", "schema_version"})
            body["name"] = "moved during the projection"
            store.replace(sid, ScenarioCreate.model_validate(body))
        elif moved == "economics.json":
            doc = fx.config_doc()
            doc["developmentCosts"]["rampPerM"] = 99.0
            r = client.put(f"/api/v1/scenarios/{sid}{CONFIG}", json=doc)
            assert r.status_code == 200
        else:
            path = derived / moved
            text = json.loads(path.read_text())
            text["_moved"] = True
            path.write_text(json.dumps(text))
        return out

    monkeypatch.setattr(analysis_service_module, "build_layout_comparison", mutating_build)
    r = client.get(f"/api/v1/scenarios/{sid}{ROUTE}")
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "READ_SNAPSHOT_CHANGED"


def test_api_c8_no_generation_entry_point_runs(
    client: TestClient, store: ScenarioStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = _stack(client, store, cat=catalogue(), selected_id=WINNER, ramp_source="LAYOUT_V2")
    client.put(f"/api/v1/scenarios/{sid}{CONFIG}", json=fx.config_doc())

    def forbidden(*_: Any, **__: Any) -> Any:
        raise AssertionError("a generation entry point ran during a read-only comparison")

    for target, name in (
        (WorldService, "generate"),
        (DesignService, "layout_v2"),
        (DesignService, "generate_levels"),
        (DesignService, "generate_production"),
        (DesignService, "generate_network"),
        (DesignService, "generate_timeline"),
        (LayoutV2Search, "run"),
    ):
        monkeypatch.setattr(target, name, forbidden)
    body = _get(client, sid)
    assert body["availability"] == "AVAILABLE" and len(body["rows"]) == len(RANKING)


# --------------------------------------------------------------------------- #
# the REAL layout-v2 catalogue (e2e — registered in conftest TEST_MARKERS)
# --------------------------------------------------------------------------- #


def test_real_catalogue_rows_are_the_persisted_candidate_quantities(
    client: TestClient, store: ScenarioStore
) -> None:
    sid = _prepare(client)
    cat = _generate_layout(client, sid)
    winner = _winner(cat)
    base = f"/api/v1/scenarios/{sid}/design"
    assert client.post(f"{base}/layout-v2/select", json={"candidateId": winner}).status_code == 200
    assert client.put(f"{base}/ramp-source", json={"activeSource": "LAYOUT_V2"}).status_code == 200
    doc = fx.config_doc()
    doc["developmentCosts"]["rampPerM"] = 10.0
    doc["developmentCosts"]["levelAccessPerM"] = 5.0
    assert client.put(f"/api/v1/scenarios/{sid}{CONFIG}", json=doc).status_code == 200
    derived = store.derived_dir(sid)
    before = _file_state(store.scenario_dir(sid), derived)
    body = _get(client, sid)
    assert body["availability"] == "AVAILABLE" and body["scope"] == "ACTIVE_DESIGN"
    assert body["winnerId"] == winner == body["selectedCandidateId"]
    persisted = json.loads((derived / LAYOUT_V2_ARTIFACT).read_text())
    by_id = {c["candidateId"]: c for c in persisted["candidates"]}
    assert [r["candidateId"] for r in body["rows"]] == persisted["ranking"]
    assert len(body["rows"]) == persisted["feasibleCount"] >= 1
    for row in body["rows"]:
        cand = by_id[row["candidateId"]]
        assert cand["status"] == "FEASIBLE"
        assert row["mainRampLengthM"] == cand["diagnostics"]["length3d"]
        assert row["levelAccessLengthM"] == cand["access"]["totalAccessLength"]
        assert row["rampCost"] == pytest.approx(row["mainRampLengthM"] * 10.0)
        assert row["levelAccessCost"] == pytest.approx(row["levelAccessLengthM"] * 5.0)
        assert row["comparableDevelopmentCost"] == pytest.approx(
            row["rampCost"] + row["levelAccessCost"]
        )
        assert row["scores"]["total"] == cand["scores"]["total"]
        assert row["catalogueRank"] == cand["rank"]
    assert _file_state(store.scenario_dir(sid), derived) == before  # C-7 on the real chain
    # the design assessment and the comparison agree on winner / selection / ranking
    a = client.get(f"{base}/assessment").json()
    assert (
        a["winnerId"] == body["winnerId"]
        and a["selectedCandidateId"] == body["selectedCandidateId"]
    )
    assert [r["candidateId"] for r in a["candidateComparison"]] == [
        r["candidateId"] for r in body["rows"][: len(a["candidateComparison"])]
    ]
