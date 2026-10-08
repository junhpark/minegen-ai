"""PR #54 review B2 — legacy Cut & Fill derived artifacts are MIGRATED, never
served, never refused as corruption.

The fixture ``tests/fixtures/h2cf/legacy_pr53_cut_fill/`` is a REAL PR #53
scenario directory (captured on the pinned PR-2 base ``1bd68c8`` by
``scripts/h2cf_capture_legacy_cut_fill_fixture.py`` through that code's own
routes: world → layout-v2 → activate → levels → network → production →
timeline). Its ``stopes.json`` is the pre-H2-CF ``CutFillPayload`` (no
``cutFillModelVersion``, no blocks / panels / rib pillars / sill mats) and its
``levels.json`` was developed with the central ``FixedAccessPattern`` crosscut
(``productionDevelopment`` without ``modelVersion``). Under the PR-2 code that
document fails today's parser, so before this migration ``GET …/scene`` was
refused whole with ``SCENE_ARTIFACT_INVALID`` / ``ARTIFACT_MALFORMED``.

Contract under test (the review's acceptance list):

* the reader classifies both artifacts ``LEGACY`` with the typed
  ``CUT_FILL_LEGACY_ARTIFACT`` (never MALFORMED; the parser is not loosened);
* every artifact route answers that typed 409 — no bare failure;
* ``GET …/scene`` migrates EXPLICITLY: the LEVELS closure (levels, network,
  production, timeline …) is discarded under the scenario lock and reported in
  ``migrations[]``; world, layout catalogue, selection, level accesses and
  the ramp source are preserved; the next read migrates nothing;
* the migration never races a running job (409 RESET_JOB_RUNNING, nothing
  deleted) and never writes a baked demo;
* Levels → Production → Schedule regenerate normally afterwards, stamped with
  the current model version;
* a current Cut & Fill artifact and every Longhole / Room & Pillar artifact
  are never classified legacy (the Longhole ``levels.json`` stays
  byte-identical: no ``modelVersion`` key is serialized for it).

The world commit record (rule 60) and the layout revisions bind by STAT
identity (size + ``mtime_ns``), which git does not keep, so the fixture's
``stat.json`` is restored onto every copy.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from minegen.api.deps import (
    get_design_service,
    get_infrastructure_service,
    get_job_service,
    get_scenario_store,
    get_world_service,
)
from minegen.core.artifacts import (
    LAYOUT_V2_ARTIFACT,
    LAYOUT_V2_SELECTED_ARTIFACT,
    LEVEL_ACCESSES_ARTIFACT,
    LEVELS_ARTIFACT,
    NETWORK_ARTIFACT,
    RAMP_SOURCE_FILE,
    STOPES_ARTIFACT,
    TIMELINE_ARTIFACT,
)
from minegen.levels.models import ProductionDevelopment
from minegen.main import create_app
from minegen.mining.models import CUT_FILL_MODEL_VERSION
from minegen.services.artifact_errors import CutFillLegacyArtifactError
from minegen.services.artifact_reader import (
    CUT_FILL_LEGACY_ARTIFACTS,
    LEGACY_DOWNSTREAM_FILES,
    PR53_CUT_FILL_KEYS,
    STATE_LEGACY,
    STATE_MALFORMED,
    STATE_VALID,
    ArtifactReader,
    _levels_cut_fill_legacy_check,
    _stopes_cut_fill_legacy_check,
)
from minegen.services.design_service import DesignService
from minegen.services.infrastructure_service import InfrastructureService
from minegen.services.job_service import JobService
from minegen.services.scenario_service import ScenarioStore
from minegen.services.workflow_stages import ResetJobRunningError
from minegen.services.world_service import WorldService

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "h2cf" / "legacy_pr53_cut_fill"
#: the PR #53 merge commit the fixture was captured on (the capture script
#: refuses any other HEAD)
PR53_HEAD = "1bd68c807730d12053d723d1189c4b901a18cf3e"
API = "/api/v1/scenarios"
LEGACY_CODE = "CUT_FILL_LEGACY_ARTIFACT"
MIGRATION_CODE = "CUT_FILL_LEGACY_ARTIFACTS_DISCARDED"


def restore_fixture(target: Path) -> str:
    """Copy the fixture scenario directory to ``target/<sid>`` and restore the
    size / mtime_ns identity of every file; returns the scenario id."""
    meta = json.loads((FIXTURE / "meta.json").read_text(encoding="utf-8"))
    stat = json.loads((FIXTURE / "stat.json").read_text(encoding="utf-8"))
    sid = str(meta["scenarioId"])
    root = target / sid
    shutil.copytree(FIXTURE / "scenario", root)
    for rel, identity in stat.items():
        path = root / rel
        assert path.stat().st_size == identity["size"], rel
        os.utime(path, ns=(int(identity["mtimeNs"]), int(identity["mtimeNs"])))
    return sid


@dataclass
class Stack:
    store: ScenarioStore
    worlds: WorldService
    design: DesignService
    jobs: JobService
    client: TestClient
    sid: str

    @property
    def derived(self) -> Path:
        return self.store.derived_dir(self.sid)

    def get(self, route: str) -> Any:
        return self.client.get(f"{API}/{self.sid}{route}")

    def post(self, route: str, **kw: Any) -> Any:
        return self.client.post(f"{API}/{self.sid}{route}", **kw)


def _stack(root: Path, *, demo: bool = False) -> tuple[Stack, Any]:
    scenarios = root / "scenarios"
    scenarios.mkdir(parents=True)
    demos = root / "demos"
    sid = restore_fixture(demos if demo else scenarios)
    store = ScenarioStore(scenarios, demo_root=demos if demo else None)
    worlds = WorldService(store)
    design = DesignService(store, worlds)
    jobs = JobService(max_workers=1)
    app = create_app()
    app.dependency_overrides[get_scenario_store] = lambda: store
    app.dependency_overrides[get_world_service] = lambda: worlds
    app.dependency_overrides[get_design_service] = lambda: design
    app.dependency_overrides[get_infrastructure_service] = lambda: InfrastructureService(
        store, design
    )
    app.dependency_overrides[get_job_service] = lambda: jobs
    context = TestClient(app, raise_server_exceptions=False)
    client = context.__enter__()
    return Stack(store, worlds, design, jobs, client, sid), context


@pytest.fixture
def legacy(tmp_path: Path) -> Iterator[Stack]:
    stack, context = _stack(tmp_path)
    yield stack
    context.__exit__(None, None, None)
    stack.jobs.shutdown()


def _code(response: Any) -> str | None:
    body = response.json()
    detail = body.get("detail") if isinstance(body, dict) else None
    return str(detail.get("code")) if isinstance(detail, dict) else None


# --------------------------------------------------------------------------- #
# the fixture IS the PR #53 shape
# --------------------------------------------------------------------------- #


def test_fixture_is_the_pr53_cut_fill_shape(legacy: Stack) -> None:
    meta = json.loads((FIXTURE / "meta.json").read_text(encoding="utf-8"))
    assert meta["generatedFromGitSha"] == PR53_HEAD
    assert meta["cutFillModelVersion"] is None
    stopes = json.loads((legacy.derived / STOPES_ARTIFACT).read_text(encoding="utf-8"))
    assert stopes["method"] == "CUT_AND_FILL" and stopes["status"] == "SUCCESS"
    assert "cutFillModelVersion" not in stopes
    assert "blocks" not in stopes and "panels" not in stopes and "ribPillars" not in stopes
    levels = json.loads((legacy.derived / LEVELS_ARTIFACT).read_text(encoding="utf-8"))
    assert levels["productionDevelopment"] == {
        "method": "CUT_AND_FILL",
        "status": "IMPLEMENTED",
        "reason": None,
    }
    # PR #53 developed ONE central production crosscut per level
    assert levels["metrics"]["stationsPerLevel"] == 1
    # the restored stat identity reproduces the world commit record: the
    # world guard passes, so what follows is a derived-artifact decision and
    # never a WORLD_PUBLICATION_STALE side effect of the copy
    reader = ArtifactReader(legacy.store)
    reader.require_world(reader.snapshot(legacy.sid, ()))
    document = legacy.get("")
    assert document.status_code == 200, document.text
    assert document.json()["mining"]["method"] == "CUT_AND_FILL"


# --------------------------------------------------------------------------- #
# classification: LEGACY, typed, never MALFORMED
# --------------------------------------------------------------------------- #


def test_reader_classifies_legacy_artifacts_typed(legacy: Stack) -> None:
    reader = ArtifactReader(legacy.store)
    snapshot = reader.snapshot(legacy.sid)
    for name in CUT_FILL_LEGACY_ARTIFACTS:
        read = reader.read(snapshot, name)
        assert read.state == STATE_LEGACY, name
        assert isinstance(read.error, CutFillLegacyArtifactError), name
        assert read.error.code == LEGACY_CODE
        assert read.error.found_version is None
        assert read.error.required_version == CUT_FILL_MODEL_VERSION
        assert read.raw is None and read.model is None  # never served
    # the well-formed network / timeline of the same mine are LEGACY BY
    # DERIVATION (built on the legacy level development): typed, naming the
    # source, never served as a current artifact …
    for name in (NETWORK_ARTIFACT, TIMELINE_ARTIFACT):
        assert name in LEGACY_DOWNSTREAM_FILES
        read = reader.read(snapshot, name)
        assert read.state == STATE_LEGACY, name
        assert isinstance(read.error, CutFillLegacyArtifactError)
        assert read.error.artifact == name
        assert read.error.source_artifact == LEVELS_ARTIFACT
    # … while the design ABOVE the levels stays VALID
    for name in (LAYOUT_V2_ARTIFACT, LAYOUT_V2_SELECTED_ARTIFACT, LEVEL_ACCESSES_ARTIFACT):
        assert name not in LEGACY_DOWNSTREAM_FILES
        assert reader.read(snapshot, name).state == STATE_VALID, name
    # a partial snapshot of a downstream artifact alone decides the same way
    # (the version-carrying sources are observed beside it, one snapshot)
    partial = reader.snapshot(legacy.sid, [TIMELINE_ARTIFACT])
    assert partial.observation(LEVELS_ARTIFACT) is not None
    assert reader.read(partial, TIMELINE_ARTIFACT).state == STATE_LEGACY


def test_every_artifact_route_answers_the_typed_409_before_migration(legacy: Stack) -> None:
    for route in ("/design/production", "/design/levels", "/design/timeline", "/network"):
        r = legacy.get(route)
        assert r.status_code == 409, (route, r.text)
        assert _code(r) == LEGACY_CODE, (route, r.text)
    # the Longhole-only route keeps its own typed refusal for a Cut & Fill
    # scenario (rule 194) — it never reaches the artifact
    r = legacy.get("/design/stopes")
    assert r.status_code == 409 and _code(r) == "PRODUCTION_METHOD_MISMATCH", r.text
    # nothing was deleted by a read that is not the scene
    assert (legacy.derived / LEVELS_ARTIFACT).exists()
    assert (legacy.derived / STOPES_ARTIFACT).exists()


# --------------------------------------------------------------------------- #
# the migration: scene read discards the Levels closure, keeps the design
# --------------------------------------------------------------------------- #


def test_scene_migrates_the_levels_closure_and_the_chain_rebuilds(legacy: Stack) -> None:
    before = {p.name for p in legacy.derived.iterdir()}
    r = legacy.get("/scene")
    assert r.status_code == 200, r.text
    scene = r.json()
    assert len(scene["migrations"]) == 1
    migration = scene["migrations"][0]
    assert migration["code"] == MIGRATION_CODE
    assert migration["artifacts"] == list(CUT_FILL_LEGACY_ARTIFACTS)
    assert set(migration["derivedArtifacts"]) == {NETWORK_ARTIFACT, TIMELINE_ARTIFACT}
    assert migration["resetFrom"] == "LEVELS"
    assert LEGACY_CODE in migration["reason"] or "legacy Cut & Fill" in migration["reason"]
    deleted = set(migration["deleted"])
    assert {LEVELS_ARTIFACT, STOPES_ARTIFACT, NETWORK_ARTIFACT, TIMELINE_ARTIFACT} <= deleted
    # the design above the levels is preserved — world, catalogue, selection,
    # accesses, ramp source
    kept = {LAYOUT_V2_ARTIFACT, LAYOUT_V2_SELECTED_ARTIFACT, LEVEL_ACCESSES_ARTIFACT}
    kept.add(RAMP_SOURCE_FILE)
    assert kept <= before and not (kept & deleted)
    assert {p.name for p in legacy.derived.iterdir()} == before - deleted
    assert scene["layoutV2"] is not None and scene["layoutV2"]["status"] == "SUCCESS"
    assert scene["layoutV2Selected"] is not None
    assert scene["levelAccesses"] is not None
    assert scene["rampSource"]["available"] and scene["rampSource"]["activeSource"] == "LAYOUT_V2"
    assert scene["miningMethod"]["method"] == "CUT_AND_FILL"
    for slot in ("levels", "network", "stopes", "timeline"):
        assert scene[slot] is None, slot
    # the next read has nothing to migrate
    again = legacy.get("/scene")
    assert again.status_code == 200 and again.json()["migrations"] == []
    # … and the chain regenerates normally from Levels on, stamped with the
    # current Cut & Fill model version
    levels = legacy.post("/design/levels")
    assert levels.status_code == 200, levels.text
    assert levels.json()["status"] == "SUCCESS", levels.json()["failureReason"]
    assert levels.json()["productionDevelopment"]["modelVersion"] == CUT_FILL_MODEL_VERSION
    production = legacy.post("/design/production")
    assert production.status_code == 200, production.text
    assert production.json()["status"] == "SUCCESS", production.json()["failureReason"]
    assert production.json()["cutFillModelVersion"] == CUT_FILL_MODEL_VERSION
    assert production.json()["metrics"]["panelCount"] >= 1
    network = legacy.post("/network/generate")
    assert network.status_code == 200, network.text
    timeline = legacy.post("/design/timeline")
    assert timeline.status_code == 200, timeline.text
    assert timeline.json()["status"] == "SUCCESS", timeline.json()["failureReason"]
    final = legacy.get("/scene")
    assert final.status_code == 200 and final.json()["migrations"] == []
    for slot in ("levels", "network", "stopes", "timeline"):
        assert final.json()[slot] is not None, slot
    # the regenerated artifacts are VALID to the reader (never legacy again)
    reader = ArtifactReader(legacy.store)
    snapshot = reader.snapshot(legacy.sid)
    for name in CUT_FILL_LEGACY_ARTIFACTS:
        assert reader.read(snapshot, name).state == STATE_VALID, name


def test_migration_never_races_a_running_job(legacy: Stack) -> None:
    before = {p.name: p.stat().st_mtime_ns for p in legacy.derived.iterdir()}
    with pytest.raises(ResetJobRunningError) as info:
        legacy.worlds.scene(legacy.sid, running_job=lambda _sid: "job-legacy-1")
    assert info.value.code == "RESET_JOB_RUNNING"
    assert {p.name: p.stat().st_mtime_ns for p in legacy.derived.iterdir()} == before


def test_a_baked_demo_is_never_migrated(tmp_path: Path) -> None:
    """A demo is read-only: the scene read answers the typed legacy 409
    instead of writing the demo directory (a demo baked by the current code
    is never legacy — this pins the contract, not a path)."""
    stack, context = _stack(tmp_path, demo=True)
    try:
        assert stack.store.is_demo(stack.sid)
        before = {
            str(p.relative_to(stack.derived)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in stack.derived.iterdir()
        }
        r = stack.get("/scene")
        assert r.status_code == 409, r.text
        assert _code(r) == LEGACY_CODE, r.text
        after = {
            str(p.relative_to(stack.derived)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in stack.derived.iterdir()
        }
        assert after == before
    finally:
        context.__exit__(None, None, None)
        stack.jobs.shutdown()


# --------------------------------------------------------------------------- #
# current artifacts and the other methods are never legacy
# --------------------------------------------------------------------------- #


def test_detection_is_scoped_to_cut_and_fill_and_its_version() -> None:
    snapshot: Any = None
    current_levels = {
        "productionDevelopment": {
            "method": "CUT_AND_FILL",
            "status": "IMPLEMENTED",
            "reason": None,
            "modelVersion": CUT_FILL_MODEL_VERSION,
        }
    }
    assert _levels_cut_fill_legacy_check(current_levels, snapshot) is None
    for block in (
        {"method": "LONGHOLE_OPEN_STOPING", "status": "IMPLEMENTED", "reason": None},
        {"method": "ROOM_AND_PILLAR", "status": "IMPLEMENTED", "reason": None},
        {"method": "SUBLEVEL_CAVING", "status": "UNSUPPORTED_METHOD", "reason": "x"},
        None,
    ):
        assert _levels_cut_fill_legacy_check({"productionDevelopment": block}, snapshot) is None
    assert _levels_cut_fill_legacy_check({}, snapshot) is None
    legacy_levels = {
        "productionDevelopment": {"method": "CUT_AND_FILL", "status": "IMPLEMENTED", "reason": None}
    }
    outcome = _levels_cut_fill_legacy_check(legacy_levels, snapshot)
    assert outcome is not None and outcome[0] == STATE_LEGACY
    assert isinstance(outcome[1], CutFillLegacyArtifactError)
    # another EXPLICIT version is legacy too — never reinterpreted
    older = {"productionDevelopment": {**legacy_levels["productionDevelopment"], "modelVersion": 1}}
    outcome = _levels_cut_fill_legacy_check(older, snapshot)
    assert outcome is not None and isinstance(outcome[1], CutFillLegacyArtifactError)
    assert outcome[1].found_version == 1

    assert (
        _stopes_cut_fill_legacy_check(
            {"method": "CUT_AND_FILL", "cutFillModelVersion": CUT_FILL_MODEL_VERSION}, snapshot
        )
        is None
    )
    assert _stopes_cut_fill_legacy_check({"method": "LONGHOLE_OPEN_STOPING"}, snapshot) is None
    assert _stopes_cut_fill_legacy_check({"method": "ROOM_AND_PILLAR"}, snapshot) is None
    pr53 = {key: None for key in PR53_CUT_FILL_KEYS} | {"method": "CUT_AND_FILL"}
    outcome = _stopes_cut_fill_legacy_check(pr53, snapshot)
    assert outcome is not None and outcome[0] == STATE_LEGACY
    # a boolean is not a version
    outcome = _stopes_cut_fill_legacy_check({**pr53, "cutFillModelVersion": True}, snapshot)
    assert outcome is not None and isinstance(outcome[1], CutFillLegacyArtifactError)
    assert outcome[1].found_version is None
    # a CUT_AND_FILL document WITHOUT the recognized PR #53 shape is not a
    # known earlier model: the method name alone never triggers a migration
    # (a Longhole-shaped document claiming CUT_AND_FILL, a truncated file —
    # they fall through to the parser and stay MALFORMED)
    assert _stopes_cut_fill_legacy_check({"method": "CUT_AND_FILL"}, snapshot) is None
    longhole_shaped = {
        "status": "SUCCESS",
        "failureReason": None,
        "sourceRevision": "r",
        "method": "CUT_AND_FILL",
        "stopes": [],
        "metrics": None,
    }
    assert _stopes_cut_fill_legacy_check(longhole_shaped, snapshot) is None


def test_an_unrecognized_cut_and_fill_document_stays_malformed(legacy: Stack) -> None:
    """The reader's ladder for a CUT_AND_FILL ``stopes.json`` that is neither
    the current model nor the PR #53 shape: MALFORMED through the parser —
    never LEGACY, so no scene read deletes anything for it (the MineExchange
    authority guard, ``test_exchange_production_methods``, relies on it)."""
    longhole_shaped = {
        "status": "SUCCESS",
        "failureReason": None,
        "sourceRevision": "r",
        "method": "CUT_AND_FILL",
        "stopes": [],
        "metrics": None,
    }
    (legacy.derived / STOPES_ARTIFACT).write_text(json.dumps(longhole_shaped), encoding="utf-8")
    reader = ArtifactReader(legacy.store)
    read = reader.read(reader.snapshot(legacy.sid), STOPES_ARTIFACT)
    assert read.state == STATE_MALFORMED
    assert read.error is not None and read.error.code == "ARTIFACT_MALFORMED"  # type: ignore[attr-defined]
    r = legacy.get("/design/production")
    assert r.status_code == 409 and _code(r) == "ARTIFACT_MALFORMED", r.text


def test_longhole_production_development_serializes_without_a_version_key() -> None:
    """Rule 193: the Longhole / Room & Pillar ``levels.json`` is byte-identical
    — the C&F-only marker is omitted, not serialized as ``null``."""
    block = ProductionDevelopment(method="LONGHOLE_OPEN_STOPING", status="IMPLEMENTED")
    assert block.model_dump(mode="json", by_alias=True) == {
        "method": "LONGHOLE_OPEN_STOPING",
        "status": "IMPLEMENTED",
        "reason": None,
    }
    stamped = ProductionDevelopment(
        method="CUT_AND_FILL", status="IMPLEMENTED", model_version=CUT_FILL_MODEL_VERSION
    )
    assert stamped.model_dump(mode="json", by_alias=True)["modelVersion"] == CUT_FILL_MODEL_VERSION
    # the persisted PR #53 block round-trips through the model unchanged
    legacy = ProductionDevelopment.model_validate(
        {"method": "CUT_AND_FILL", "status": "IMPLEMENTED", "reason": None}
    )
    assert legacy.model_version is None
