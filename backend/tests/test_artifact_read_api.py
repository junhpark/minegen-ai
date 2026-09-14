"""AC-01F T2–T5 / T8 / T13 / T14 — the read contract through the real API.

The permanent successor of the commit-1 characterization test: where that one
asserted OLD-vs-NEW side by side, this one pins the AFTER of the same literal
tables (Stage A §2.2–2.5 malformed columns, §4.1/§4.2 "one stale state per
artifact", §3 I-1/I-6/I-10/I-11/I-12, §7.2/§7.4) — each row carrying the Stage
A reference it was transcribed from.

    ABSENT     expected and quiet: the artifact's own ``*_NOT_GENERATED``
               code, ``null`` in the scene, ``LEGACY`` for the ramp source.
    MALFORMED  409 ``ARTIFACT_MALFORMED`` naming the FILE — on its route, in
               the scene aggregate, on every dependent builder and in the
               async job's error code.
    STALE      409 with the rule-named code where one exists
               (``SHAFTS_STALE``, ``CAPABILITY_GRAPH_STALE``,
               ``LAYOUT_V2_SELECTION_STALE``), ``ARTIFACT_STALE`` otherwise.

Oracles (§29): every expectation below is a LITERAL written from the approved
contract and the Stage A measurements; staleness is produced the way the
probes produced it (``os.utime`` on the pinned input, a byte append, ``"{"``,
``{"hello":"world"}``, GLB truncation), never with ``file_revision``.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
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
    CAPABILITY_GRAPH_ARTIFACT,
    COMMUNICATION_ARTIFACT,
    DECLINE_ARTIFACT,
    DEVELOPMENT_MESH_ARTIFACT,
    DEVELOPMENT_MESH_GLB,
    LAYOUT_V2_ARTIFACT,
    LAYOUT_V2_SELECTED_ARTIFACT,
    LEGACY_RAMP_ARTIFACT,
    LEVEL_ACCESSES_ARTIFACT,
    LEVELS_ARTIFACT,
    NETWORK_ARTIFACT,
    RAMP_SOURCE_FILE,
    SENSORS_ARTIFACT,
    SHAFTS_ARTIFACT,
    STOPES_ARTIFACT,
    TARGETS_ARTIFACT,
    TIMELINE_ARTIFACT,
    TUNNEL_MESH_ARTIFACT,
    TUNNEL_MESH_GLB,
)
from minegen.layout.certification import ClearancePolicyReconstructionError
from minegen.main import create_app
from minegen.services.artifact_errors import (
    ArtifactMalformedError,
    LayoutSelectionStaleError,
    StaleInputsError,
)
from minegen.services.design_service import DesignService
from minegen.services.infrastructure_service import InfrastructureService
from minegen.services.job_service import JobService
from minegen.services.scenario_service import ScenarioStore
from minegen.services.world_service import WorldService
from tests.conftest import small_scenario

API = "/api/v1/scenarios"


# --------------------------------------------------------------------------- #
# the two stacks (ac01f_A/oracle/README.md call order, verbatim)
# --------------------------------------------------------------------------- #


@dataclass
class Stack:
    store: ScenarioStore
    worlds: WorldService
    design: DesignService
    infra: InfrastructureService
    client: TestClient
    jobs: JobService
    sid: str

    @property
    def derived(self) -> Path:
        return self.store.derived_dir(self.sid)

    def get(self, route: str) -> tuple[int, str | None]:
        return _answer(self.client.get(f"{API}/{self.sid}{route}"))

    def post(self, route: str, **kwargs: Any) -> tuple[int, str | None]:
        return _answer(self.client.post(f"{API}/{self.sid}{route}", **kwargs))

    def scene(self) -> Any:
        return self.client.get(f"{API}/{self.sid}/scene")


def _answer(response: Any) -> tuple[int, str | None]:
    """``(status, detail.code)`` — a bare unhandled 500 has no code at all,
    exactly as the Stage A probes observed it
    (``raise_server_exceptions=False``)."""
    try:
        body = response.json()
    except ValueError:
        return response.status_code, None
    if isinstance(body, dict) and isinstance(body.get("detail"), dict):
        return response.status_code, str(body["detail"].get("code"))
    return response.status_code, None


def _make_stack(root: Path) -> tuple[Stack, Any]:
    store = ScenarioStore(root / "scenarios")
    worlds = WorldService(store)
    design = DesignService(store, worlds)
    infra = InfrastructureService(store, design)
    jobs = JobService(max_workers=2)
    app = create_app()
    app.dependency_overrides[get_scenario_store] = lambda: store
    app.dependency_overrides[get_world_service] = lambda: worlds
    app.dependency_overrides[get_design_service] = lambda: design
    app.dependency_overrides[get_infrastructure_service] = lambda: infra
    app.dependency_overrides[get_job_service] = lambda: jobs
    import minegen.api.jobs as jobs_module

    jobs_module.get_job_service = lambda: jobs  # type: ignore[assignment]
    context = TestClient(app, raise_server_exceptions=False)
    client = context.__enter__()
    scenario = small_scenario(with_fault=True)
    payload = scenario.model_dump(by_alias=True, exclude={"id", "schema_version"})
    created = client.post(API, json=payload)
    assert created.status_code == 201, created.text
    sid = str(created.json()["id"])
    document = client.get(f"{API}/{sid}").json()
    document.pop("id")
    document.pop("schemaVersion")
    document["design"]["candidateCount"] = 1
    document["design"]["search"]["maxExpansionsPerCandidate"] = 20000
    document["shafts"] = {"specs": [{"shaftId": "SHAFT-01", "role": "PRODUCTION"}]}
    assert client.put(f"{API}/{sid}", json=document).status_code == 200
    return Stack(store, worlds, design, infra, client, jobs, sid), context


def _build(root: Path, source: str) -> tuple[Stack, Any]:
    stack, context = _make_stack(root)

    def step(method: str, route: str, **kwargs: Any) -> Any:
        response = stack.client.request(method, f"{API}/{stack.sid}{route}", **kwargs)
        assert response.status_code in (200, 201), (
            route,
            response.status_code,
            response.text[:400],
        )
        return response

    step("POST", "/world/generate")
    if source == "LEGACY":
        step("POST", "/design/targets")
        step("POST", "/design/decline", params={"maxLevels": 2, "sync": "true"})
        step("POST", "/design/decline/smooth", params={"sync": "true"})
        step("POST", "/design/tunnel", params={"sync": "true"})
        step("POST", "/design/levels")
        step("POST", "/design/development-mesh", params={"sync": "true"})
    else:
        catalogue = step("POST", "/design/layout-v2", params={"sync": "true"}).json()
        winner = catalogue["winnerId"]
        assert winner, "the fixture must produce a winner"
        step("POST", "/design/layout-v2/activate", json={"candidateId": winner})
        step("POST", "/design/levels")
        step("POST", "/design/tunnel", params={"sync": "true"})
        step("POST", "/design/development-mesh", params={"sync": "true"})
    step("POST", "/design/shafts")
    step("POST", "/network/generate")
    step("POST", "/design/capability-graph")
    step("POST", "/design/stopes")
    step("POST", "/design/timeline")
    step("POST", "/infrastructure/communication")
    step("POST", "/infrastructure/sensors")
    return stack, context


@pytest.fixture(scope="module")
def legacy(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    stack, context = _build(tmp_path_factory.mktemp("legacy"), "LEGACY")
    yield stack
    context.__exit__(None, None, None)
    stack.jobs.shutdown()


@pytest.fixture(scope="module")
def layout_v2(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    stack, context = _build(tmp_path_factory.mktemp("layout_v2"), "LAYOUT_V2")
    yield stack
    context.__exit__(None, None, None)
    stack.jobs.shutdown()


@pytest.fixture(scope="module")
def bare(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    """World generated, nothing derived — the ABSENT contract (T2)."""
    stack, context = _make_stack(tmp_path_factory.mktemp("bare"))
    assert stack.client.post(f"{API}/{stack.sid}/world/generate").status_code == 200
    yield stack
    context.__exit__(None, None, None)
    stack.jobs.shutdown()


# --------------------------------------------------------------------------- #
# mutation helpers (the Stage A probe recipes)
# --------------------------------------------------------------------------- #


@contextmanager
def mutated(*paths: Path) -> Iterator[None]:
    """Restore bytes AND ``st_mtime_ns``. Stage A C-12: rewriting the bytes
    alone silently changes ``file_revision`` (``name:size:mtime_ns``) and
    contaminates every later case in the same module-scoped fixture."""
    saved = [
        (p, p.read_bytes() if p.exists() else None, os.stat(p) if p.exists() else None)
        for p in paths
    ]
    try:
        yield
    finally:
        for path, data, st in saved:
            if data is None:
                if path.exists():
                    path.unlink()
                continue
            path.write_bytes(data)
            assert st is not None
            os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))


def bump(path: Path, seconds: float = 5.0) -> None:
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + int(seconds * 1e9)))


@contextmanager
def derived_restored(stack: Stack) -> Iterator[None]:
    """An exact undo for rows whose builders really write: every file under
    ``derived/`` is saved with its bytes AND ``st_mtime_ns`` and put back,
    files a build created are removed, and the in-memory service caches for
    this scenario are dropped."""
    derived = stack.derived
    saved = {
        path.name: (path.read_bytes(), os.stat(path))
        for path in sorted(derived.iterdir())
        if path.is_file()
    }
    try:
        yield
    finally:
        for path in sorted(derived.iterdir()):
            if path.is_file() and path.name not in saved:
                path.unlink()
        for name, (data, st) in saved.items():
            path = derived / name
            path.write_bytes(data)
            os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
        for cache in (
            stack.design._targets,
            stack.design._layouts,
            stack.design._selected_policies,
            stack.design._evaluators,
        ):
            cache.pop(stack.sid, None)
        stack.worlds._cache.pop(stack.sid, None)


#: the direct GET route of every artifact (``ac01f_A/oracle/README.md``)
ROUTES: dict[str, str] = {
    TARGETS_ARTIFACT: "/design/targets",
    DECLINE_ARTIFACT: "/design/decline",
    LEGACY_RAMP_ARTIFACT: "/design/decline/smooth",
    LAYOUT_V2_ARTIFACT: "/design/layout-v2",
    LAYOUT_V2_SELECTED_ARTIFACT: "/design/layout-v2/selected",
    LEVEL_ACCESSES_ARTIFACT: "/design/level-accesses",
    RAMP_SOURCE_FILE: "/design/ramp-source",
    TUNNEL_MESH_ARTIFACT: "/design/tunnel",
    DEVELOPMENT_MESH_ARTIFACT: "/design/development-mesh",
    LEVELS_ARTIFACT: "/design/levels",
    SHAFTS_ARTIFACT: "/design/shafts",
    NETWORK_ARTIFACT: "/network",
    CAPABILITY_GRAPH_ARTIFACT: "/design/capability-graph",
    STOPES_ARTIFACT: "/design/stopes",
    TIMELINE_ARTIFACT: "/design/timeline",
    COMMUNICATION_ARTIFACT: "/infrastructure/communication",
    SENSORS_ARTIFACT: "/infrastructure/sensors",
}

#: the ``GET /scene`` key each artifact is projected into
SCENE_SLOT: dict[str, str] = {
    TARGETS_ARTIFACT: "accessTargets",
    DECLINE_ARTIFACT: "decline",
    LEGACY_RAMP_ARTIFACT: "smoothedDecline",
    TUNNEL_MESH_ARTIFACT: "tunnelMesh",
    DEVELOPMENT_MESH_ARTIFACT: "developmentMesh",
    LEVELS_ARTIFACT: "levels",
    SHAFTS_ARTIFACT: "shafts",
    NETWORK_ARTIFACT: "network",
    CAPABILITY_GRAPH_ARTIFACT: "capabilityGraph",
    STOPES_ARTIFACT: "stopes",
    TIMELINE_ARTIFACT: "timeline",
    COMMUNICATION_ARTIFACT: "communication",
    SENSORS_ARTIFACT: "sensors",
    LAYOUT_V2_ARTIFACT: "layoutV2",
    LAYOUT_V2_SELECTED_ARTIFACT: "layoutV2Selected",
    LEVEL_ACCESSES_ARTIFACT: "levelAccesses",
    RAMP_SOURCE_FILE: "rampSource",
}

LEGACY_ABSENT = (
    LAYOUT_V2_ARTIFACT,
    LAYOUT_V2_SELECTED_ARTIFACT,
    LEVEL_ACCESSES_ARTIFACT,
    RAMP_SOURCE_FILE,
)
LAYOUT_V2_ABSENT = (TARGETS_ARTIFACT, DECLINE_ARTIFACT, LEGACY_RAMP_ARTIFACT)


def assert_scene_refuses(stack: Stack, artifact: str, code: str) -> None:
    """A14: the whole scene is refused, and the aggregate NAMES the artifact
    with its own specific code — never a filesystem path or a traceback."""
    response = stack.scene()
    assert response.status_code == 409, (artifact, response.status_code)
    detail = response.json()["detail"]
    assert detail["code"] == "SCENE_ARTIFACT_INVALID", detail
    rows = {row["artifact"]: row for row in detail["artifacts"]}
    assert artifact in rows, (artifact, sorted(rows))
    assert rows[artifact]["code"] == code, (artifact, rows[artifact])
    for row in detail["artifacts"]:
        # A14: the public detail names FILES — never an absolute filesystem
        # path (the store root, the derived dir, the tmp prefix), never a
        # traceback, never an exception repr
        assert not re.search(r"(?<![\w…])/(?:tmp|home|var|usr|private)\b", row["message"]), row
        assert str(stack.derived) not in row["message"], row
        assert "Traceback" not in row["message"] and "object at 0x" not in row["message"], row


# --------------------------------------------------------------------------- #
# T2 — ABSENT is expected and quiet
# --------------------------------------------------------------------------- #

#: the literal absence answer of every direct route (Stage A §2 / §13 I-13):
#: 14 × 409, 3 × 404 (the recorded I-8 drift, unchanged by AC-01F) and the ONE
#: route with a documented absent DEFAULT.
ABSENT_ANSWERS: dict[str, tuple[int, str | None]] = {
    "/design/targets": (409, "TARGETS_NOT_GENERATED"),
    "/design/decline": (409, "DECLINE_NOT_GENERATED"),
    "/design/decline/smooth": (409, "SMOOTHED_NOT_GENERATED"),
    "/design/layout-v2": (409, "LAYOUT_V2_NOT_GENERATED"),
    "/design/layout-v2/selected": (409, "LAYOUT_V2_NOT_SELECTED"),
    "/design/level-accesses": (409, "LEVEL_ACCESSES_NOT_GENERATED"),
    "/design/ramp": (409, "SMOOTHED_NOT_GENERATED"),
    "/design/tunnel": (409, "TUNNEL_NOT_GENERATED"),
    "/design/development-mesh": (409, "DEVELOPMENT_MESH_NOT_GENERATED"),
    "/design/levels": (409, "LEVELS_NOT_GENERATED"),
    "/design/stopes": (409, "STOPES_NOT_GENERATED"),
    "/design/timeline": (409, "TIMELINE_NOT_GENERATED"),
    "/infrastructure/communication": (409, "COMMUNICATION_NOT_GENERATED"),
    "/infrastructure/sensors": (409, "SENSORS_NOT_GENERATED"),
    "/design/shafts": (404, "SHAFTS_NOT_GENERATED"),
    "/network": (404, "NETWORK_NOT_GENERATED"),
    "/design/capability-graph": (404, "CAPABILITY_GRAPH_NOT_GENERATED"),
    "/design/ramp-source": (200, None),
}

#: the 12-field summary a never-generated LEGACY scenario answers, transcribed
#: field by field from ``EffectiveRampResolution.summary()`` (A8: expected
#: absence may be reported unavailable — a persisted inconsistency may not)
ABSENT_RAMP_SOURCE: dict[str, Any] = {
    "activeSource": "LEGACY",
    "owningArtifact": "decline_smoothed.json",
    "available": False,
    "legacyAvailable": False,
    "layoutV2Available": False,
    "layoutV2Selected": False,
    "sourceKind": None,
    "sourceRevision": None,
    "candidateId": None,
    "family": None,
    "status": None,
    "segmentCount": 0,
}


def test_absent_artifacts_answer_their_own_code(bare: Stack) -> None:
    assert sum(1 for s, _ in ABSENT_ANSWERS.values() if s == 409) == 14
    assert sum(1 for s, _ in ABSENT_ANSWERS.values() if s == 404) == 3
    for route, expected in ABSENT_ANSWERS.items():
        assert bare.get(route) == expected, route
    # the two GLB routes answer their report's own absence code
    assert bare.get("/design/tunnel/mesh.glb") == (409, "TUNNEL_NOT_GENERATED")
    assert bare.get("/design/development-mesh/mesh.glb") == (409, "DEVELOPMENT_MESH_NOT_GENERATED")


def test_absent_artifacts_are_null_in_the_scene(bare: Stack) -> None:
    response = bare.scene()
    assert response.status_code == 200
    scene = response.json()
    for artifact, key in SCENE_SLOT.items():
        if artifact == RAMP_SOURCE_FILE:
            continue
        assert scene[key] is None, (artifact, key)
    assert scene["legacySmoothedDecline"] is None
    assert scene["rampSource"] == ABSENT_RAMP_SOURCE


def test_the_absent_ramp_source_is_the_documented_legacy_default(bare: Stack) -> None:
    assert not (bare.derived / RAMP_SOURCE_FILE).exists()
    body = bare.client.get(f"{API}/{bare.sid}/design/ramp-source").json()
    assert body == ABSENT_RAMP_SOURCE


# --------------------------------------------------------------------------- #
# T3 / T4 — MALFORMED: unparseable bytes and a valid document of the wrong shape
# --------------------------------------------------------------------------- #

MALFORMED = "ARTIFACT_MALFORMED"
SELECTION_STALE = "LAYOUT_V2_SELECTION_STALE"
CLEARANCE_MISMATCH = "LAYOUT_V2_CLEARANCE_MISMATCH"


@dataclass(frozen=True)
class Corrupt:
    """One artifact's MALFORMED contract. ``ms_code`` is ``None`` where the
    wrong-shaped document stays VALID (``targets.json`` has no first-level
    precondition: no consumer subscripts it, Stage B §8.2)."""

    artifact: str
    #: the code the direct GET answers for ``{`` (Stage A: 500 at HEAD)
    mj_code: str = MALFORMED
    #: the code for ``{"hello":"world"}`` (Stage A: 200 serving the junk, or 500)
    ms_code: str | None = MALFORMED
    #: one dependent builder POST and the code it must answer for ``{``
    builder: tuple[str, str] | None = None
    builder_params: dict[str, Any] = field(default_factory=dict)


#: present on BOTH stacks (Stage A §2.3–2.5)
CORRUPT_SHARED: tuple[Corrupt, ...] = (
    Corrupt(TUNNEL_MESH_ARTIFACT),
    Corrupt(DEVELOPMENT_MESH_ARTIFACT),
    Corrupt(LEVELS_ARTIFACT, builder=("/design/stopes", MALFORMED)),
    Corrupt(SHAFTS_ARTIFACT, builder=("/network/generate", MALFORMED)),
    Corrupt(NETWORK_ARTIFACT, builder=("/design/capability-graph", MALFORMED)),
    Corrupt(CAPABILITY_GRAPH_ARTIFACT),
    Corrupt(STOPES_ARTIFACT, builder=("/design/timeline", MALFORMED)),
    Corrupt(TIMELINE_ARTIFACT),
    Corrupt(COMMUNICATION_ARTIFACT),
    Corrupt(SENSORS_ARTIFACT),
)

#: LEGACY-only files (Stage A §2.2 legacy chain)
CORRUPT_LEGACY: tuple[Corrupt, ...] = (
    Corrupt(
        TARGETS_ARTIFACT,
        ms_code=None,  # VALID: no declared first-level precondition
        builder=("/design/decline", MALFORMED),
        builder_params={"maxLevels": 2, "sync": "true"},
    ),
    Corrupt(
        DECLINE_ARTIFACT,
        builder=("/design/decline/smooth", MALFORMED),
        builder_params={"sync": "true"},
    ),
    Corrupt(LEGACY_RAMP_ARTIFACT, builder=("/design/levels", MALFORMED)),
)

#: LAYOUT_V2-only files. The M-S column of the two certification-bearing
#: documents is the A1 order: a document with no ``layoutRevision`` is bound to
#: another catalogue revision, so it is STALE before any certification or shape
#: check. The CATALOGUE's builder cell is the same order one level up and is
#: UNCHANGED from HEAD (Stage A §2.2, ``layout_v2.json`` row: "the stat check
#: fires BEFORE any parse"): corrupting the catalogue changes its size, so its
#: ``file_revision`` moves and the selection that names the old one is STALE
#: before anything is parsed.
CORRUPT_LAYOUT_V2: tuple[Corrupt, ...] = (
    Corrupt(LAYOUT_V2_ARTIFACT, builder=("/design/levels", SELECTION_STALE)),
    Corrupt(
        LAYOUT_V2_SELECTED_ARTIFACT,
        ms_code=SELECTION_STALE,
        builder=("/design/levels", MALFORMED),
    ),
    Corrupt(
        LEVEL_ACCESSES_ARTIFACT,
        ms_code=SELECTION_STALE,
        # C5: the builder reads the ACTIVE RAMP first, and the selection's own
        # read now observes its co-published half — an unusable
        # ``level_accesses.json`` makes the PAIR incomplete, which is
        # ``LAYOUT_V2_SELECTION_STALE`` (pre-change literal on this cell:
        # ``ARTIFACT_MALFORMED``, from the accesses read one step later). The
        # artifact's OWN GET is still ``ARTIFACT_MALFORMED`` (``mj_code``).
        builder=("/design/levels", SELECTION_STALE),
    ),
    Corrupt(RAMP_SOURCE_FILE, builder=("/design/levels", MALFORMED)),
)


def _corrupt_case(stack: Stack, case: Corrupt, junk: str, expected: str | None) -> None:
    path = stack.derived / case.artifact
    with mutated(path):
        path.write_text(junk, encoding="utf-8")
        if expected is None:
            assert stack.get(ROUTES[case.artifact])[0] == 200, case.artifact
            assert stack.scene().status_code == 200, case.artifact
            return
        status, code = stack.get(ROUTES[case.artifact])
        assert (status, code) == (409, expected), (case.artifact, junk, status, code)
        assert_scene_refuses(stack, case.artifact, expected)
        if case.builder is not None and junk == "{":
            route, builder_code = case.builder
            with derived_restored(stack):
                assert stack.post(route, params=case.builder_params) == (409, builder_code), (
                    case.artifact,
                    route,
                )
    assert stack.get(ROUTES[case.artifact])[0] == 200, case.artifact


@pytest.mark.parametrize("case", CORRUPT_SHARED + CORRUPT_LEGACY, ids=lambda c: c.artifact)
def test_malformed_json_is_typed_on_every_surface_legacy(case: Corrupt, legacy: Stack) -> None:
    _corrupt_case(legacy, case, "{", case.mj_code)


@pytest.mark.parametrize("case", CORRUPT_SHARED + CORRUPT_LAYOUT_V2, ids=lambda c: c.artifact)
def test_malformed_json_is_typed_on_every_surface_layout_v2(
    case: Corrupt, layout_v2: Stack
) -> None:
    _corrupt_case(layout_v2, case, "{", case.mj_code)


@pytest.mark.parametrize("case", CORRUPT_SHARED + CORRUPT_LEGACY, ids=lambda c: c.artifact)
def test_wrong_shape_is_typed_on_every_surface_legacy(case: Corrupt, legacy: Stack) -> None:
    _corrupt_case(legacy, case, json.dumps({"hello": "world"}), case.ms_code)


@pytest.mark.parametrize("case", CORRUPT_SHARED + CORRUPT_LAYOUT_V2, ids=lambda c: c.artifact)
def test_wrong_shape_is_typed_on_every_surface_layout_v2(case: Corrupt, layout_v2: Stack) -> None:
    _corrupt_case(layout_v2, case, json.dumps({"hello": "world"}), case.ms_code)


def test_the_corrupt_tables_cover_every_registered_artifact() -> None:
    covered = {c.artifact for c in CORRUPT_SHARED + CORRUPT_LEGACY + CORRUPT_LAYOUT_V2}
    assert covered == set(ROUTES)
    assert len(covered) == 17


def test_an_async_job_reports_the_read_state_code(legacy: Stack) -> None:
    """Surface 4 == surface 1 (Stage A §1.8): a corrupt upstream artifact used
    to surface as ``code: "JOB_FAILED"``; every read-state exception now
    carries its own code, which ``JobService`` transports unchanged."""
    path = legacy.derived / TARGETS_ARTIFACT
    with mutated(path), derived_restored(legacy):
        path.write_text("{", encoding="utf-8")
        response = legacy.client.post(f"{API}/{legacy.sid}/design/decline", params={"maxLevels": 2})
        # the route's precondition refuses before a job is even submitted
        assert _answer(response) == (409, MALFORMED)
        job = legacy.jobs.submit(
            legacy.sid, "DECLINE", lambda on_progress: legacy.design.generate_decline(legacy.sid)
        )
        deadline = time.time() + 60
        while time.time() < deadline:
            record = legacy.jobs.get(job.id)
            if record.status.value in ("SUCCEEDED", "FAILED", "CANCELLED"):
                break
            time.sleep(0.02)
        record = legacy.jobs.get(job.id)
        assert record.status.value == "FAILED"
        assert record.error is not None and record.error["code"] == MALFORMED


# --------------------------------------------------------------------------- #
# T5 — STALE: the rule-named codes, on every surface
# --------------------------------------------------------------------------- #


def test_the_shafts_canary_is_refused_everywhere(legacy: Stack) -> None:
    """Stage A I-1 / §4.1, the canary of the whole step: with
    ``shafts.levelsRevision`` no longer matching ``levels.json``, the GET used
    to answer 200 SUCCESS while three builders answered 409 ``SHAFTS_STALE``
    and the two infrastructure builders leaked 500 ``INTERNAL_ERROR`` (I-6).
    One authority now: every surface refuses with the same code."""
    levels = legacy.derived / LEVELS_ARTIFACT
    with mutated(levels), derived_restored(legacy):
        bump(levels)
        assert legacy.get("/design/shafts") == (409, "SHAFTS_STALE")
        assert_scene_refuses(legacy, SHAFTS_ARTIFACT, "SHAFTS_STALE")
        for route in (
            "/network/generate",
            "/design/capability-graph",
            "/design/timeline",
            "/infrastructure/communication",
            "/infrastructure/sensors",
        ):
            assert legacy.post(route) == (409, "SHAFTS_STALE"), route
    assert legacy.get("/design/shafts")[0] == 200


def test_a_stale_capability_graph_is_refused_by_the_scene_too(legacy: Stack) -> None:
    """Stage A I-2: ``GET …/design/capability-graph`` already answered 409
    ``CAPABILITY_GRAPH_STALE`` while the scene served the same artifact with
    ``validation.networkRevisionMatches: true``. The mutation is the pinned
    recipe of ``tests/test_shafts_api.py``: a space appended to
    ``network.json`` (still valid JSON, new revision)."""
    network = legacy.derived / NETWORK_ARTIFACT
    with mutated(network):
        network.write_bytes(network.read_bytes() + b" ")
        assert legacy.get("/design/capability-graph") == (409, "CAPABILITY_GRAPH_STALE")
        assert legacy.get("/network")[0] == 200  # the network itself is fine
        assert_scene_refuses(legacy, CAPABILITY_GRAPH_ARTIFACT, "CAPABILITY_GRAPH_STALE")
    assert legacy.get("/design/capability-graph")[0] == 200


#: Stage A §3 I-10, verbatim: ONE ``os.utime(layout_v2.json)`` split one
#: request family — four builders refused with ``LAYOUT_V2_SELECTION_STALE``
#: while five built happily ON the stale selection. After AC-01F the four
#: readers of the ACTIVE ramp join the refusal; ``POST …/design/stopes`` does
#: NOT, and that is not an oversight: stopes reads no ramp at all (the registry
#: declares ``scenario + arrays + levels`` as its inputs, rule 79), so no read
#: authority can make it stale — giving it one would be an engineering change,
#: not a read-trust change (Stage B §11, "stopes reads no ramp").
STALE_SELECTION_BUILDERS: tuple[tuple[str, dict[str, Any], int, str | None], ...] = (
    ("/design/levels", {}, 409, SELECTION_STALE),
    ("/design/tunnel", {"sync": "true"}, 409, SELECTION_STALE),
    ("/design/development-mesh", {"sync": "true"}, 409, SELECTION_STALE),
    ("/design/shafts", {}, 409, SELECTION_STALE),
    ("/network/generate", {}, 409, SELECTION_STALE),
    ("/design/timeline", {}, 409, SELECTION_STALE),
    ("/infrastructure/communication", {}, 409, SELECTION_STALE),
    ("/infrastructure/sensors", {}, 409, SELECTION_STALE),
    ("/design/stopes", {}, 200, None),
)


def test_a_stale_selection_is_refused_by_every_reader_of_the_ramp(layout_v2: Stack) -> None:
    catalogue = layout_v2.derived / LAYOUT_V2_ARTIFACT
    with mutated(catalogue), derived_restored(layout_v2):
        bump(catalogue)
        for route in (
            "/design/layout-v2/selected",
            "/design/level-accesses",
            "/design/ramp",
            "/design/ramp-source",
        ):
            assert layout_v2.get(route) == (409, SELECTION_STALE), route
        assert layout_v2.get("/design/layout-v2")[0] == 200  # the catalogue itself is fine
        assert_scene_refuses(layout_v2, LAYOUT_V2_SELECTED_ARTIFACT, SELECTION_STALE)
        assert_scene_refuses(layout_v2, LEVEL_ACCESSES_ARTIFACT, SELECTION_STALE)
        for route, params, status, code in STALE_SELECTION_BUILDERS:
            assert layout_v2.post(route, params=params) == (status, code), route
    assert layout_v2.get("/design/layout-v2/selected")[0] == 200


def test_a_disagreeing_level_access_pair_is_typed_by_the_defect(layout_v2: Stack) -> None:
    """Stage A §7.4 / §4.4: the two halves of the selection are written under
    ONE capture (rule 157) but were read by nobody together, and
    ``level_accesses.layoutRevision`` was written and never read at all.

    Stage-B checkpoint decision C1 splits the disagreement by DEFECT CLASS,
    applying A1's third row literally: ``candidateId`` and the certification
    (provenance key / error bound) are a "candidate identity / clearance
    recipe defect" → ``LAYOUT_V2_CLEARANCE_MISMATCH``; ``sourceRevision`` /
    ``layoutRevision`` and an orphaned half are a capture-freshness fact →
    ``LAYOUT_V2_SELECTION_STALE``. The state is STALE in both cases."""
    accesses = layout_v2.derived / LEVEL_ACCESSES_ARTIFACT
    for key, value, code in (
        ("candidateId", "SPIRAL-n1-CCW-e+0-g0.120", CLEARANCE_MISMATCH),
        ("clearanceErrorBound", 123.5, CLEARANCE_MISMATCH),
        ("layoutRevision", "DELIBERATELY-WRONG", SELECTION_STALE),
        ("sourceRevision", "DELIBERATELY-WRONG", SELECTION_STALE),
    ):
        with mutated(accesses):
            document = json.loads(accesses.read_text(encoding="utf-8"))
            document[key] = value
            accesses.write_text(json.dumps(document), encoding="utf-8")
            assert layout_v2.get("/design/level-accesses") == (409, code), key
            assert_scene_refuses(layout_v2, LEVEL_ACCESSES_ARTIFACT, code)
        assert layout_v2.get("/design/level-accesses")[0] == 200, key


#: C1: the builders that read ``level_accesses.json`` but restore NO clearance
#: policy. Before C1 the implementer's D3 gave them one (a policy restore on
#: four builders that never needed one); now the co-published pair read is what
#: refuses a value-tampered selection, and the pinned AC-01D code is unchanged.
ACCESSES_ONLY_BUILDERS: tuple[str, ...] = (
    "/network/generate",
    "/design/timeline",
    "/infrastructure/communication",
    "/infrastructure/sensors",
)


@pytest.mark.parametrize("key", ["clearanceErrorBound", "requiredClearance"])
def test_a_value_tampered_selection_is_refused_through_the_pair_read(
    key: str, layout_v2: Stack
) -> None:
    """C1 on the wire, as amended by C5/C6. The selection is SHAPE-valid and
    REVISION-valid — only ONE recorded certification number was moved — and
    the co-published ``level_accesses.json`` still carries the true one, so
    the accesses GET, the scene and every accesses-reading builder answer
    ``LAYOUT_V2_CLEARANCE_MISMATCH``: A1's third row, the AC-01D pinned code,
    decided in ONE place.

    Two Stage D corrections are pinned here.

    C5: the selection's OWN GET is 409 too. The pair is one read unit in BOTH
    directions now; the pre-change literal for this line was ``(200, None)``
    — the documented C1 asymmetry, which is gone.

    C6: ``requiredClearance`` is compared. It is the fourth key
    ``CandidateCertification`` parses and the pair check omitted it, so moving
    it (measured: 10.590169943749475 → 999.0) left ``GET
    …/design/layout-v2/selected``, ``GET …/design/level-accesses``,
    ``GET …/scene`` and ``POST …/network/generate`` all 200 while
    ``POST …/design/levels`` answered 409 — the scene mixing what a builder
    refuses with what it accepts."""
    selection = layout_v2.derived / LAYOUT_V2_SELECTED_ARTIFACT
    with mutated(selection), derived_restored(layout_v2):
        document = json.loads(selection.read_text(encoding="utf-8"))
        document["clearance"][key] = (document["clearance"][key] or 0.0) + 1e-3
        selection.write_text(json.dumps(document), encoding="utf-8")
        # C5: the OWNER's own read carries the pair check too (was 200)
        assert layout_v2.get("/design/layout-v2/selected") == (409, CLEARANCE_MISMATCH)
        assert layout_v2.get("/design/ramp") == (409, CLEARANCE_MISMATCH)
        assert layout_v2.get("/design/ramp-source") == (409, CLEARANCE_MISMATCH)
        # the pair makes the residue visible on the other half as well
        assert layout_v2.get("/design/level-accesses") == (409, CLEARANCE_MISMATCH)
        assert_scene_refuses(layout_v2, LEVEL_ACCESSES_ARTIFACT, CLEARANCE_MISMATCH)
        assert_scene_refuses(layout_v2, LAYOUT_V2_SELECTED_ARTIFACT, CLEARANCE_MISMATCH)
        for route in ACCESSES_ONLY_BUILDERS:
            assert layout_v2.post(route) == (409, CLEARANCE_MISMATCH), route
        assert layout_v2.post("/design/levels") == (409, CLEARANCE_MISMATCH)
        # rule 79 / D1: stopes reads no ramp at all, so nothing makes it stale
        assert layout_v2.post("/design/stopes") == (200, None)
    assert layout_v2.get("/design/level-accesses")[0] == 200
    assert layout_v2.get("/design/layout-v2/selected")[0] == 200


def test_a_wrong_shaped_targets_marker_is_valid_and_the_decline_still_builds(
    legacy: Stack,
) -> None:
    """``targets.json`` is the ONE artifact with no declared first-level
    precondition: no consumer subscripts it (``_targets_object`` requires a
    VALID document and then rebuilds the set deterministically). So a
    wrong-shaped document is VALID by spec — only UNPARSEABLE bytes are
    refused — and ``POST …/design/decline`` still answers 200. That is a
    deliberate honesty limit of the read authority, not an oversight: the
    resolver claims nothing about a shape no consumer reads."""
    path = legacy.derived / TARGETS_ARTIFACT
    with mutated(path), derived_restored(legacy):
        path.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
        assert legacy.get("/design/targets") == (200, None)
        assert legacy.post("/design/decline", params={"maxLevels": 2, "sync": "true"}) == (
            200,
            None,
        )
        # and unparseable bytes in the same file ARE refused
        path.write_text("{", encoding="utf-8")
        assert legacy.post("/design/decline", params={"maxLevels": 2, "sync": "true"}) == (
            409,
            MALFORMED,
        )
    assert legacy.get("/design/targets")[0] == 200


def test_each_artifact_reports_its_own_state_when_the_network_is_unparseable(
    legacy: Stack,
) -> None:
    """The capability graph records ``networkSourceRevision`` and AC-01F
    cross-checks it against the network payload's own ``sourceRevision``. That
    cross-check DEFERS when ``network.json`` cannot be parsed — the network's
    own read is the ``ARTIFACT_MALFORMED`` report, and one artifact never
    reports another's defect. In practice the graph is refused anyway, one
    check earlier: rewriting the file changed its ``file_revision``, so the
    ``networkRevision`` relation fires first with ``CAPABILITY_GRAPH_STALE``."""
    network = legacy.derived / NETWORK_ARTIFACT
    with mutated(network):
        network.write_text("{", encoding="utf-8")
        assert legacy.get("/network") == (409, MALFORMED)
        assert legacy.get("/design/capability-graph") == (409, "CAPABILITY_GRAPH_STALE")
    assert legacy.get("/design/capability-graph")[0] == 200


def test_a_development_mesh_swept_under_another_ramp_source_is_stale(layout_v2: Stack) -> None:
    """``development_mesh.sources.rampSource`` is persisted evidence no reader
    compared; a switch would have DELETED the mesh (rule 151), so a mismatch is
    residue. No rule-named stale code exists for it → ``ARTIFACT_STALE``."""
    report = layout_v2.derived / DEVELOPMENT_MESH_ARTIFACT
    with mutated(report):
        document = json.loads(report.read_text(encoding="utf-8"))
        assert document["sources"]["rampSource"] == "LAYOUT_V2"
        document["sources"]["rampSource"] = "LEGACY"
        report.write_text(json.dumps(document), encoding="utf-8")
        assert layout_v2.get("/design/development-mesh") == (409, "ARTIFACT_STALE")
        assert_scene_refuses(layout_v2, DEVELOPMENT_MESH_ARTIFACT, "ARTIFACT_STALE")
    assert layout_v2.get("/design/development-mesh")[0] == 200


# --------------------------------------------------------------------------- #
# T8 — the two-file units
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fraction", [0.5, 0.001, 0.0], ids=["half", "0.1%", "empty"])
def test_a_torn_glb_is_refused_instead_of_served_immutable(legacy: Stack, fraction: float) -> None:
    """Stage A §7.2: a truncated GLB was served **200 ``model/gltf-binary``
    with ``Cache-Control: …immutable``** — a corrupt asset the browser caches
    for a year. The report's own ``artifactRevision`` (the sha256 of the GLB
    the writer computed) now decides."""
    glb = legacy.derived / TUNNEL_MESH_GLB
    with mutated(glb):
        original = glb.read_bytes()
        glb.write_bytes(original[: int(len(original) * fraction)])
        response = legacy.client.get(f"{API}/{legacy.sid}/design/tunnel/mesh.glb")
        assert _answer(response) == (409, MALFORMED)
        assert "immutable" not in response.headers.get("cache-control", "")
        assert response.headers["content-type"].startswith("application/json")
    assert legacy.client.get(f"{API}/{legacy.sid}/design/tunnel/mesh.glb").status_code == 200


def test_a_success_report_without_its_glb_is_refused_on_both_routes(legacy: Stack) -> None:
    """Stage A §7.4: the report answered 200 SUCCESS while its own GLB route
    answered 409 — a half-published two-file unit (rule 67) presented as a
    finished artifact."""
    glb = legacy.derived / TUNNEL_MESH_GLB
    with mutated(glb):
        glb.unlink()
        assert legacy.get("/design/tunnel") == (409, MALFORMED)
        assert legacy.get("/design/tunnel/mesh.glb") == (409, MALFORMED)
        assert_scene_refuses(legacy, TUNNEL_MESH_ARTIFACT, MALFORMED)
    assert legacy.get("/design/tunnel")[0] == 200


def test_the_glb_served_is_the_one_the_report_hashes(legacy: Stack) -> None:
    import hashlib

    report = json.loads((legacy.derived / TUNNEL_MESH_ARTIFACT).read_text(encoding="utf-8"))
    served = legacy.client.get(f"{API}/{legacy.sid}/design/tunnel/mesh.glb")
    assert served.status_code == 200
    assert served.headers["content-type"] == "model/gltf-binary"
    assert hashlib.sha256(served.content).hexdigest() == report["artifactRevision"]


# --------------------------------------------------------------------------- #
# T13 — a malformed ramp_source.json: strict reads, conservative cleanup
# --------------------------------------------------------------------------- #


def test_a_malformed_ramp_source_is_refused_by_every_read(layout_v2: Stack) -> None:
    """Stage A I-12: a corrupt ``ramp_source.json`` silently answered
    ``activeSource: LEGACY`` — with a LAYOUT_V2 mine built, that silently
    re-pointed the whole mine at an artifact that does not exist."""
    path = layout_v2.derived / RAMP_SOURCE_FILE
    for junk in ("{", json.dumps({"hello": "world"}), json.dumps({"activeSource": "NOT_A_SOURCE"})):
        with mutated(path):
            path.write_text(junk, encoding="utf-8")
            assert layout_v2.get("/design/ramp-source") == (409, MALFORMED), junk
            assert layout_v2.get("/design/ramp") == (409, MALFORMED), junk
            assert_scene_refuses(layout_v2, RAMP_SOURCE_FILE, MALFORMED)
            for route in ("/design/levels", "/design/shafts"):
                assert layout_v2.post(route) == (409, MALFORMED), (junk, route)
    assert layout_v2.get("/design/ramp-source")[0] == 200


#: A7: a writer that has ALREADY persisted its artifact and meets a malformed
#: ``ramp_source.json`` at its cascade must not raise (that would leave a
#: published file with no cascade) and must not guess LEGACY. It deletes
#: ``union(invalidated_by(written, LEGACY), invalidated_by(written,
#: LAYOUT_V2))`` — strictly more, never less. For ``targets.json`` the LEGACY
#: closure is the whole legacy chain and everything derived from the effective
#: ramp, while the LAYOUT_V2 closure stops at ``decline_smoothed.json``; the
#: literal file set below is what survives the union.
AFTER_UNION_CASCADE: set[str] = {
    "world.json",  # unregistered stats snapshot, never in a cascade
    TARGETS_ARTIFACT,  # the artifact the writer just published
    LAYOUT_V2_ARTIFACT,
    LAYOUT_V2_SELECTED_ARTIFACT,
    LEVEL_ACCESSES_ARTIFACT,
    RAMP_SOURCE_FILE,
}


def test_a_cascade_that_meets_a_malformed_source_deletes_the_union(layout_v2: Stack) -> None:
    path = layout_v2.derived / RAMP_SOURCE_FILE
    with derived_restored(layout_v2), mutated(path):
        path.write_text("{", encoding="utf-8")
        # POST …/design/targets reads no ramp, so it writes and then cascades
        assert layout_v2.post("/design/targets")[0] == 200
        remaining = {p.name for p in layout_v2.derived.iterdir() if p.is_file()}
        assert remaining == AFTER_UNION_CASCADE, sorted(remaining)
    assert layout_v2.get("/design/ramp-source")[0] == 200


#: the ten artifacts a LEGACY GUESS would have KEPT when the layout-v2
#: catalogue writer meets an unusable ``ramp_source.json``:
#: ``invalidated_by([layout_v2.json], "LEGACY")`` is only the selection and
#: its level accesses, while ``invalidated_by([layout_v2.json], "LAYOUT_V2")``
#: is those two plus these ten. The union deletes strictly more, never less.
LAYOUT_V2_ONLY_CLOSURE: set[str] = {
    LEVELS_ARTIFACT,
    TUNNEL_MESH_ARTIFACT,
    DEVELOPMENT_MESH_ARTIFACT,
    SHAFTS_ARTIFACT,
    NETWORK_ARTIFACT,
    CAPABILITY_GRAPH_ARTIFACT,
    STOPES_ARTIFACT,
    TIMELINE_ARTIFACT,
    COMMUNICATION_ARTIFACT,
    SENSORS_ARTIFACT,
}


def test_the_catalogue_writer_also_deletes_the_union_on_a_malformed_source(
    layout_v2: Stack,
) -> None:
    """A7 / C3 bullet 5, the OTHER writer: ``POST …/design/layout-v2`` reads no
    ramp either, so it publishes ``layout_v2.json`` and then meets the corrupt
    ``ramp_source.json`` at its cascade. Guessing LEGACY there would keep the
    ten LAYOUT_V2-only closure members below — a whole mine derived from a
    ramp the catalogue has just invalidated. The union deletes them."""
    assert len(LAYOUT_V2_ONLY_CLOSURE) == 10
    path = layout_v2.derived / RAMP_SOURCE_FILE
    with derived_restored(layout_v2), mutated(path):
        before = {p.name for p in layout_v2.derived.iterdir() if p.is_file()}
        assert before >= LAYOUT_V2_ONLY_CLOSURE, sorted(before)
        path.write_text("{", encoding="utf-8")
        assert layout_v2.post("/design/layout-v2", params={"sync": "true"})[0] == 200
        remaining = {p.name for p in layout_v2.derived.iterdir() if p.is_file()}
        assert remaining == AFTER_CATALOGUE_REGENERATION, sorted(remaining)
        assert not (LAYOUT_V2_ONLY_CLOSURE & remaining)
        # the two-file units went whole: no orphaned GLB beside a deleted report
        assert not {TUNNEL_MESH_GLB, DEVELOPMENT_MESH_GLB} & remaining
    assert layout_v2.get("/design/ramp-source")[0] == 200


def test_the_explicit_put_repairs_a_malformed_source(layout_v2: Stack) -> None:
    """A7 write side: the explicit ``PUT …/ramp-source`` treats an unusable
    source as "differs", writes and cascades — the repair is always the user's
    explicit write, never a read-side fixup."""
    path = layout_v2.derived / RAMP_SOURCE_FILE
    with derived_restored(layout_v2), mutated(path):
        path.write_text("{", encoding="utf-8")
        response = layout_v2.client.put(
            f"{API}/{layout_v2.sid}/design/ramp-source", json={"activeSource": "LAYOUT_V2"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["activeSource"] == "LAYOUT_V2"
        assert json.loads(path.read_text(encoding="utf-8")) == {"activeSource": "LAYOUT_V2"}
        assert layout_v2.get("/design/ramp-source")[0] == 200
    assert layout_v2.get("/design/ramp-source")[0] == 200


# --------------------------------------------------------------------------- #
# T14 — the three ramp-source cases of A8
# --------------------------------------------------------------------------- #


def test_ramp_source_expected_absence_stays_available_false(bare: Stack) -> None:
    """A8 case 1: LEGACY with no ``decline_smoothed.json`` is the normal
    pre-generation state, byte-equal to today's summary."""
    assert bare.client.get(f"{API}/{bare.sid}/design/ramp-source").json() == ABSENT_RAMP_SOURCE


#: what survives ``POST …/design/layout-v2?sync=true`` on a fully built
#: LAYOUT_V2 stack: the catalogue the writer just published, the unregistered
#: stats snapshot, and ``ramp_source.json`` — which lies OUTSIDE every cascade
#: (Stage A §1.3 / §4.3), which is exactly why the state below is reachable.
AFTER_CATALOGUE_REGENERATION: set[str] = {
    "world.json",
    LAYOUT_V2_ARTIFACT,
    RAMP_SOURCE_FILE,
}


def test_layout_v2_active_without_a_selection_is_an_expected_absence(layout_v2: Stack) -> None:
    """A8's third case, AMENDED by the Stage-B checkpoint decision C2.

    A8 assumed ``activeSource = LAYOUT_V2`` with no ``layout_v2_selected.json``
    could not be produced by the normal API flow and must therefore fail
    closed. Stage A §1.3 / §4.3 prove it CAN be: ``ramp_source.json`` is in no
    cascade, so regenerating the catalogue under an active LAYOUT_V2 deletes
    the selection and the level accesses while ``activeSource`` stays
    LAYOUT_V2 until the user re-selects and re-activates. This test does not
    assert that from a hand-edited store — it REACHES the state through the
    real API and then pins A8's own principle ("expected absence may be
    unavailable"): 200 ``available: false``, byte-equal to the pre-AC-01F
    summary, with ``GET …/design/ramp`` still 409 ``LAYOUT_V2_NOT_SELECTED``
    and the scene's ``rampSource`` slot saying the same thing the endpoint
    says (the frontend reads that slot)."""
    with derived_restored(layout_v2):
        assert layout_v2.get("/design/ramp-source")[0] == 200
        assert layout_v2.post("/design/layout-v2", params={"sync": "true"})[0] == 200
        remaining = {p.name for p in layout_v2.derived.iterdir() if p.is_file()}
        assert remaining == AFTER_CATALOGUE_REGENERATION, sorted(remaining)
        source = json.loads((layout_v2.derived / RAMP_SOURCE_FILE).read_text(encoding="utf-8"))
        assert source == {"activeSource": "LAYOUT_V2"}

        response = layout_v2.client.get(f"{API}/{layout_v2.sid}/design/ramp-source")
        assert response.status_code == 200, response.text
        summary = response.json()
        assert summary == {
            **ABSENT_RAMP_SOURCE,
            "activeSource": "LAYOUT_V2",
            "owningArtifact": LAYOUT_V2_SELECTED_ARTIFACT,
            "layoutV2Available": True,
        }
        assert summary["available"] is False
        assert layout_v2.get("/design/ramp") == (409, "LAYOUT_V2_NOT_SELECTED")

        scene = layout_v2.scene()
        assert scene.status_code == 200, scene.text
        assert scene.json()["rampSource"] == summary
        assert scene.json()["smoothedDecline"] is None
    assert layout_v2.get("/design/ramp-source")[0] == 200


def test_ramp_source_refuses_a_present_but_invalid_owner(layout_v2: Stack) -> None:
    """A8 case 2: the status endpoint must never report ``available: true``
    for a ramp every builder refuses (Stage A I-11)."""
    selection = layout_v2.derived / LAYOUT_V2_SELECTED_ARTIFACT
    with mutated(selection):
        selection.write_text("{", encoding="utf-8")
        assert layout_v2.get("/design/ramp-source") == (409, MALFORMED)
    catalogue = layout_v2.derived / LAYOUT_V2_ARTIFACT
    with mutated(catalogue):
        bump(catalogue)
        assert layout_v2.get("/design/ramp-source") == (409, SELECTION_STALE)
    assert layout_v2.get("/design/ramp-source")[0] == 200


# --------------------------------------------------------------------------- #
# C3 — a MALFORMED artifact first met INSIDE a sync build is typed, not a 500
# --------------------------------------------------------------------------- #

#: the ONLY exception classes the ``if sync:`` blocks of ``POST …/design/tunnel``
#: and ``POST …/design/development-mesh`` caught before C3
#: (``api/design.py``: ``except StaleInputsError`` and
#: ``except (LayoutSelectionStaleError, ClearancePolicyReconstructionError)``).
#: Anything else left the branch unmapped — ``raise exc`` — and reached the
#: client as a bare 500 with no ``detail.code``. That literal tuple is the
#: pre-change oracle below: a read-state error is not an instance of it.
SYNC_HANDLERS_BEFORE_C3: tuple[type[Exception], ...] = (
    StaleInputsError,
    LayoutSelectionStaleError,
    ClearancePolicyReconstructionError,
)


@pytest.mark.parametrize("artifact", [LEVEL_ACCESSES_ARTIFACT, RAMP_SOURCE_FILE])
def test_a_malformed_artifact_inside_the_development_mesh_sync_build_is_typed(
    layout_v2: Stack, artifact: str
) -> None:
    """C3, the blocking case: ``POST …/design/development-mesh?sync=true``
    checks ``levels.json`` as its precondition, so on a LAYOUT_V2 stack with
    VALID levels the FIRST reader of ``level_accesses.json`` /
    ``ramp_source.json`` is the build itself — inside the ``if sync:`` block.

    Pre-change oracle (no ``raise_server_exceptions`` guesswork): the service
    raises ``ArtifactMalformedError``, which is NOT an instance of
    ``SYNC_HANDLERS_BEFORE_C3`` — the only clauses that branch had — so the
    branch re-raised and the client got a bare 500. It is 409
    ``ARTIFACT_MALFORMED`` now."""
    path = layout_v2.derived / artifact
    with mutated(path), derived_restored(layout_v2):
        path.write_text("{", encoding="utf-8")
        # the precondition passes: levels.json is VALID and present
        assert layout_v2.get("/design/levels")[0] == 200
        with pytest.raises(ArtifactMalformedError) as raised:
            layout_v2.design.generate_development_mesh(layout_v2.sid)
        assert not isinstance(raised.value, SYNC_HANDLERS_BEFORE_C3), (
            "the pre-C3 sync branch would have re-raised this into a bare 500"
        )
        assert layout_v2.post("/design/development-mesh", params={"sync": "true"}) == (
            409,
            MALFORMED,
        )
    assert layout_v2.get("/design/development-mesh")[0] == 200


def test_a_malformed_smoothed_decline_is_typed_on_the_tunnel_sync_route(legacy: Stack) -> None:
    """C3, the tunnel half. ``POST …/design/tunnel?sync=true`` answers 409
    ``ARTIFACT_MALFORMED`` for a corrupt ``decline_smoothed.json`` — today
    through the route's ACTIVE-RAMP precondition, which runs before ``sync``;
    the fall-through added to the ``if sync:`` block is the defence for the
    same defect met INSIDE the build (a file corrupted between the
    precondition's snapshot and the build's). The route contract is one
    answer either way: never a bare 500."""
    path = legacy.derived / LEGACY_RAMP_ARTIFACT
    with mutated(path), derived_restored(legacy):
        path.write_text("{", encoding="utf-8")
        assert legacy.post("/design/tunnel", params={"sync": "true"}) == (409, MALFORMED)
    assert legacy.get("/design/tunnel")[0] == 200


# --------------------------------------------------------------------------- #
# C3 — the scene's world guard is DISK-authoritative
# --------------------------------------------------------------------------- #


def test_the_scene_refuses_a_warm_cache_without_arrays(legacy: Stack) -> None:
    """C3 bullet 1 / Stage A probe 2 §4.9, whose measured pre-change literal
    was **200**: with the world cached in memory, deleting ``arrays.npz``
    left ``GET /scene`` serving a full manifest for a scenario that has no
    generated world. The snapshot's own ``arrays.npz`` stat decides now — the
    same DISK-authoritative guard every ``ArtifactReader.require`` applies."""
    arrays = legacy.store.arrays_path(legacy.sid)
    assert legacy.get("/scene") == (200, None)  # this read warms the world cache
    assert legacy.sid in legacy.worlds._cache
    with mutated(arrays):
        arrays.unlink()
        assert legacy.sid in legacy.worlds._cache  # still warm: nothing invalidated it
        assert legacy.get("/scene") == (409, "WORLD_NOT_GENERATED")
    assert legacy.get("/scene") == (200, None)


# --------------------------------------------------------------------------- #
# C3 — a MALFORMED catalogue can no longer be selected
# --------------------------------------------------------------------------- #


def test_a_malformed_catalogue_cannot_be_selected(layout_v2: Stack) -> None:
    """C3 bullet 3: ``_layout_object``'s precondition was
    ``self.layout_path(sid).is_file()`` — presence only — so a corrupt
    ``layout_v2.json`` went straight to the deterministic search re-run, which
    rebuilds the result from scenario + world and never parses the catalogue.

    Pre-change literal, MEASURED at HEAD ``12d7725``
    (``scratchpad/ac01f_C/select_malformed_probe.py``; this is NOT the bare
    500 of the Stage A §2.2 GET row — the write path was worse): with
    ``layout_v2.json`` = ``"{"``, ``POST …/design/layout-v2/select`` answered
    **200** and wrote ``layout_v2_selected.json`` + ``level_accesses.json``
    carrying the corrupt catalogue's own ``layoutRevision``, and
    ``…/activate`` answered **200**. The precondition is the VALIDATED read
    now: 409, and nothing is written."""
    catalogue = layout_v2.derived / LAYOUT_V2_ARTIFACT
    selected = json.loads(
        (layout_v2.derived / LAYOUT_V2_SELECTED_ARTIFACT).read_text(encoding="utf-8")
    )
    candidate_id = selected["candidateId"]
    with mutated(catalogue), derived_restored(layout_v2):
        before = {p.name for p in layout_v2.derived.iterdir() if p.is_file()}
        catalogue.write_text("{", encoding="utf-8")
        for route in ("/design/layout-v2/select", "/design/layout-v2/activate"):
            assert layout_v2.post(route, json={"candidateId": candidate_id}) == (
                409,
                MALFORMED,
            ), route
        after = {p.name for p in layout_v2.derived.iterdir() if p.is_file()}
        assert after == before, sorted(after ^ before)  # nothing written, nothing cascaded
    assert layout_v2.get("/design/layout-v2")[0] == 200


# --------------------------------------------------------------------------- #
# C3 — PUT …/design/ramp-source guards BEFORE it writes
# --------------------------------------------------------------------------- #


def test_a_refused_ramp_source_switch_writes_nothing(layout_v2: Stack) -> None:
    """C3 bullet 6: the VALID-selection requirement is evaluated before the
    lock is entered, so a refused activation leaves ``ramp_source.json``
    byte-identical AND mtime-identical — it never mutates and then answers
    409. The switch is driven to LEGACY first so the refused PUT is a real
    state CHANGE, not a no-op that would pass trivially."""
    source_file = layout_v2.derived / RAMP_SOURCE_FILE
    catalogue = layout_v2.derived / LAYOUT_V2_ARTIFACT
    with derived_restored(layout_v2):
        legacy_switch = layout_v2.client.put(
            f"{API}/{layout_v2.sid}/design/ramp-source", json={"activeSource": "LEGACY"}
        )
        assert legacy_switch.status_code == 200, legacy_switch.text
        before_bytes = source_file.read_bytes()
        before_stat = os.stat(source_file)
        assert json.loads(before_bytes) == {"activeSource": "LEGACY"}

        bump(catalogue)  # the selection now names a foreign catalogue revision
        response = layout_v2.client.put(
            f"{API}/{layout_v2.sid}/design/ramp-source", json={"activeSource": "LAYOUT_V2"}
        )
        assert _answer(response) == (409, SELECTION_STALE), response.text
        assert source_file.read_bytes() == before_bytes
        assert os.stat(source_file).st_mtime_ns == before_stat.st_mtime_ns
    assert layout_v2.get("/design/ramp-source")[0] == 200


# --------------------------------------------------------------------------- #
# A3 — the targets writer captures its inputs before the evaluator
# --------------------------------------------------------------------------- #


def test_a_world_that_moves_during_target_generation_fails_the_write_closed(
    legacy: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A3 / Stage A §5.4: ``POST …/design/targets`` was the last derived
    writer with NO rule-60 fingerprint, so a world regeneration or scenario
    PUT that landed while the targets were being generated was silently
    overwritten by targets built for the replaced inputs (measured: 4 levels
    persisted where 3 were correct). The fingerprint is captured before the
    evaluator and re-checked under the publish lock now.

    The race is made deterministic exactly as the probe made it: the target
    generator is paused with a ``threading.Event`` between the capture and
    the write, ``arrays.npz`` is bumped, and the write is released."""
    import minegen.services.design_service as design_service_module

    targets_path = legacy.derived / TARGETS_ARTIFACT
    arrays = legacy.store.arrays_path(legacy.sid)
    original = design_service_module.generate_access_targets
    inside = threading.Event()
    release = threading.Event()

    def paused(*args: Any, **kwargs: Any) -> Any:
        inside.set()
        assert release.wait(60), "the test never released the paused generation"
        return original(*args, **kwargs)

    monkeypatch.setattr(design_service_module, "generate_access_targets", paused)

    arrays_stat = os.stat(arrays)
    with mutated(targets_path), derived_restored(legacy):
        before = targets_path.read_bytes()
        answer: dict[str, Any] = {}

        def post() -> None:
            answer["value"] = legacy.post("/design/targets")

        worker = threading.Thread(target=post, daemon=True)
        worker.start()
        assert inside.wait(60), "the target generation never started"
        os.utime(arrays, ns=(arrays_stat.st_atime_ns, arrays_stat.st_mtime_ns + 5_000_000_000))
        release.set()
        worker.join(120)
        assert answer.get("value") == (409, "JOB_INPUTS_CHANGED"), answer
        assert targets_path.read_bytes() == before  # nothing was persisted

        # and the normal path, with nothing moving, still answers 200
        monkeypatch.setattr(design_service_module, "generate_access_targets", original)
        assert legacy.post("/design/targets") == (200, None)
    os.utime(arrays, ns=(arrays_stat.st_atime_ns, arrays_stat.st_mtime_ns))


def test_the_valid_stacks_still_answer_200_everywhere(legacy: Stack, layout_v2: Stack) -> None:
    """The success path is untouched: every present artifact of both stacks
    reads 200 and the scene assembles."""
    for stack, absent in ((legacy, LEGACY_ABSENT), (layout_v2, LAYOUT_V2_ABSENT)):
        for artifact, route in ROUTES.items():
            status, code = stack.get(route)
            if artifact == RAMP_SOURCE_FILE:
                # the ONE artifact with a documented absent DEFAULT (rule 150)
                assert status == 200, (route, status, code)
                continue
            if artifact in absent:
                assert status in (404, 409), (route, status)
                continue
            assert status == 200, (route, status, code)
        assert stack.scene().status_code == 200


# --------------------------------------------------------------------------- #
# T9 — a restarted process reads exactly what the warm one serves
# --------------------------------------------------------------------------- #

#: every READ surface of a built stack: the 17 artifact routes, the Effective
#: Ramp, both GLB routes and the scene aggregate
COLD_ROUTES: tuple[str, ...] = (
    *ROUTES.values(),
    "/design/ramp",
    "/design/tunnel/mesh.glb",
    "/design/development-mesh/mesh.glb",
    "/scene",
)


@contextmanager
def cold_services(stack: Stack) -> Iterator[TestClient]:
    """A RESTARTED process over the same ``data/scenarios`` tree: brand-new
    ``WorldService`` / ``DesignService`` / ``InfrastructureService`` with empty
    in-memory caches, sharing the ``ScenarioStore`` (and therefore the same
    per-scenario locks, since a process boundary is what the store lock does
    NOT cross — Q-PROCESS-SCOPE stays a recorded residual)."""
    worlds = WorldService(stack.store)
    design = DesignService(stack.store, worlds)
    infra = InfrastructureService(stack.store, design)
    jobs = JobService(max_workers=1)
    app = create_app()
    app.dependency_overrides[get_scenario_store] = lambda: stack.store
    app.dependency_overrides[get_world_service] = lambda: worlds
    app.dependency_overrides[get_design_service] = lambda: design
    app.dependency_overrides[get_infrastructure_service] = lambda: infra
    app.dependency_overrides[get_job_service] = lambda: jobs
    assert not worlds._cache and not design._targets and not design._layouts
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        jobs.shutdown()


def test_a_cold_process_reads_exactly_what_the_warm_one_serves(
    legacy: Stack, layout_v2: Stack
) -> None:
    """T9 (Stage B §28). Every read is a function of the FILES, never of
    process state: a service constructed over the same store answers the same
    bytes on every route and the same typed code on a mutation. This is the
    property the revision-bound world cache (AC-01F commit 3) restores — Stage
    A probe 2 §4.9 measured the opposite, a warm process answering 200 for a
    world a cold one refused."""
    for stack in (legacy, layout_v2):
        warm_bodies = {
            route: stack.client.get(f"{API}/{stack.sid}{route}") for route in COLD_ROUTES
        }
        with cold_services(stack) as cold:
            for route in COLD_ROUTES:
                warm = warm_bodies[route]
                fresh = cold.get(f"{API}/{stack.sid}{route}")
                assert fresh.status_code == warm.status_code, (route, fresh.status_code)
                assert fresh.content == warm.content, route

        # and the same typed refusal on a STALE mutation (the shafts canary)
        levels = stack.derived / LEVELS_ARTIFACT
        with mutated(levels):
            bump(levels)
            for route in ("/design/shafts", "/scene"):
                warm = stack.client.get(f"{API}/{stack.sid}{route}")
                with cold_services(stack) as cold:
                    fresh = cold.get(f"{API}/{stack.sid}{route}")
                assert warm.status_code == fresh.status_code == 409, (route, warm.status_code)
                assert fresh.content == warm.content, route

        # … and on a MALFORMED one
        network = stack.derived / NETWORK_ARTIFACT
        with mutated(network):
            network.write_text("{", encoding="utf-8")
            for route in ("/network", "/scene"):
                warm = stack.client.get(f"{API}/{stack.sid}{route}")
                with cold_services(stack) as cold:
                    fresh = cold.get(f"{API}/{stack.sid}{route}")
                assert warm.status_code == fresh.status_code == 409, (route, warm.status_code)
                assert fresh.content == warm.content, route


# --------------------------------------------------------------------------- #
# T10 — a read never writes
# --------------------------------------------------------------------------- #


def _tree_state(stack: Stack) -> dict[str, tuple[str, int, int]]:
    """``name -> (sha256, size, st_mtime_ns)`` for ``scenario.json``,
    ``arrays.npz`` and every file under ``derived/``."""
    import hashlib

    paths = [
        stack.store.scenario_path(stack.sid),
        stack.store.arrays_path(stack.sid),
        *sorted(p for p in stack.derived.iterdir() if p.is_file()),
    ]
    state: dict[str, tuple[str, int, int]] = {}
    for path in paths:
        st = os.stat(path)
        state[path.name] = (
            hashlib.sha256(path.read_bytes()).hexdigest(),
            st.st_size,
            st.st_mtime_ns,
        )
    return state


def test_no_read_surface_writes_anything(legacy: Stack, layout_v2: Stack) -> None:
    """T10: READ ≠ WRITE. After every read surface of a built stack — the 17
    artifact routes, the Effective Ramp, both GLB routes and the scene — every
    byte AND every ``st_mtime_ns`` under the scenario directory is unchanged.

    The read authority performs no repair, no migration and no regeneration
    (§10.2 item 6); the ONE documented exception is ``ScenarioStore.get``'s
    Phase 18 migration-on-read (A10), which cannot fire here because both
    fixtures persist a current-schema document."""
    for stack in (legacy, layout_v2):
        before = _tree_state(stack)
        assert len(before) > 10, sorted(before)
        for route in COLD_ROUTES:
            assert stack.client.get(f"{API}/{stack.sid}{route}").status_code in (200, 404, 409)
        assert _tree_state(stack) == before


# --------------------------------------------------------------------------- #
# Stage D B2 — a first-level precondition is the subscript the consumer PERFORMS
# --------------------------------------------------------------------------- #

#: artifact → (the list key, the route whose GET must refuse it, the builder
#: POST that used to leak a bare 500). Every consumer here subscripts the
#: ELEMENTS of the list, so ``isinstance(value, list)`` was not the
#: precondition it claimed to be: a present, parseable document with a list of
#: NON-objects passed the check and crashed one step later.
#:
#: Pre-change literals, measured at commit 3 through this very API:
#:   decline.json  = {"levels":[1,2]}         GET 200 | scene 200 |
#:                   POST /design/decline/smooth?sync=true  -> 500, no detail.code
#:   level_accesses.json accesses=[1,2]       GET 200 | scene 200 |
#:                   POST /design/levels                    -> 500, no detail.code
#:   layout_v2.json = {"candidates":[1,2]}    GET 200 | GET …/selected 200 |
#:                   GET /scene                             -> 500 "Internal Server Error"
#: ``(artifact, list key, dependent POST, params, json body)`` — the POST is a
#: CONSUMER of the artifact, never its own regeneration.
LIST_OF_NON_DICTS: tuple[tuple[str, str, str, dict[str, Any], Any], ...] = (
    (DECLINE_ARTIFACT, "levels", "/design/decline/smooth", {"sync": "true"}, None),
    (LEVEL_ACCESSES_ARTIFACT, "accesses", "/design/levels", {}, None),
    (
        LAYOUT_V2_ARTIFACT,
        "candidates",
        "/design/layout-v2/select",
        {},
        {"candidateId": "SPIRAL-n1-g0.100"},
    ),
)


@pytest.mark.parametrize(
    "artifact,key,builder,params,body", LIST_OF_NON_DICTS, ids=lambda v: str(v)
)
def test_a_list_of_non_objects_is_malformed_on_every_surface(
    artifact: str,
    key: str,
    builder: str,
    params: dict[str, Any],
    body: Any,
    legacy: Stack,
    layout_v2: Stack,
) -> None:
    """B2. The three preconditions that tested the LIST and not its ELEMENTS.
    ``_is_dict_list`` — the correct helper, already used by two other specs —
    is the precondition now, so the document is 409 ``ARTIFACT_MALFORMED`` on
    its own route, in the scene aggregate and on the builder, instead of a
    bare 500 with no ``detail.code``."""
    stack = legacy if artifact == DECLINE_ARTIFACT else layout_v2
    path = stack.derived / artifact
    with mutated(path), derived_restored(stack):
        document = json.loads(path.read_text(encoding="utf-8"))
        document[key] = [1, 2]
        path.write_text(json.dumps(document), encoding="utf-8")
        assert stack.get(ROUTES[artifact]) == (409, MALFORMED), artifact
        assert_scene_refuses(stack, artifact, MALFORMED)
        kwargs: dict[str, Any] = {"params": params}
        if body is not None:
            kwargs["json"] = body
        status, code = stack.post(builder, **kwargs)
        assert (status, code) == (409, MALFORMED), (artifact, builder, status, code)
    assert stack.get(ROUTES[artifact])[0] == 200, artifact


# --------------------------------------------------------------------------- #
# Stage D C5 — the selection ↔ level-access pair is ONE read unit
# --------------------------------------------------------------------------- #

#: every surface C5 names, plus the two builders that read the pair
PAIR_GETS: tuple[str, ...] = (
    "/design/layout-v2/selected",
    "/design/level-accesses",
    "/design/ramp",
    "/design/ramp-source",
)
PAIR_POSTS: tuple[str, ...] = ("/design/levels", "/network/generate")


def _pair_answers(stack: Stack) -> dict[str, tuple[int, str | None]]:
    answers = {route: stack.get(route) for route in PAIR_GETS}
    answers["/scene"] = _answer(stack.scene())
    for route in PAIR_POSTS:
        answers[route] = stack.post(route)
    return answers


def test_a_selection_without_its_level_accesses_is_refused_everywhere(
    layout_v2: Stack,
) -> None:
    """C5, the direction the crash window actually produces:
    ``select_layout_candidate`` writes the selection FIRST and the accesses
    second, and only the accesses → selection direction used to be checked.

    Pre-change literals, measured at commit 3 with the accesses DELETED:
    ``GET …/design/ramp-source`` **200 available:true activeSource:LAYOUT_V2
    layoutV2Selected:true**, ``GET …/design/ramp`` **200 (PARAMETRIC_V2)**,
    ``GET …/scene`` **200** with ``levelAccesses: null`` — while
    ``POST …/design/levels`` and ``POST …/network/generate`` answered 409
    ``LEVEL_ACCESSES_NOT_GENERATED``. That is exactly the split
    ``design_service.ramp_source`` and the scene docstring promise never to
    report."""
    accesses = layout_v2.derived / LEVEL_ACCESSES_ARTIFACT
    for junk in (None, "{", json.dumps([1, 2])):
        with mutated(accesses), derived_restored(layout_v2):
            if junk is None:
                accesses.unlink()
            else:
                accesses.write_text(junk, encoding="utf-8")
            answers = _pair_answers(layout_v2)
            for route, (status, code) in answers.items():
                assert status == 409, (junk, route, status, code)
                assert code is not None, (junk, route)
            # the SELECTION's own read reports the incomplete pair as STALE
            for route in ("/design/layout-v2/selected", "/design/ramp", "/design/ramp-source"):
                assert answers[route] == (409, SELECTION_STALE), (junk, route)
            # the accesses' own read reports its own state
            expected = {
                None: "LEVEL_ACCESSES_NOT_GENERATED",
                "{": MALFORMED,
                json.dumps([1, 2]): MALFORMED,
            }[junk]
            assert answers["/design/level-accesses"] == (409, expected), junk
            assert_scene_refuses(layout_v2, LAYOUT_V2_SELECTED_ARTIFACT, SELECTION_STALE)
    assert layout_v2.get("/design/layout-v2/selected")[0] == 200


def test_a_selection_naming_another_candidate_than_its_accesses_is_a_mismatch(
    layout_v2: Stack,
) -> None:
    """C5's value half in the SELECTION's direction: a candidateId
    disagreement is A1's third row — the pinned AC-01D
    ``LAYOUT_V2_CLEARANCE_MISMATCH`` — on BOTH halves now."""
    selection = layout_v2.derived / LAYOUT_V2_SELECTED_ARTIFACT
    with mutated(selection), derived_restored(layout_v2):
        document = json.loads(selection.read_text(encoding="utf-8"))
        document["candidateId"] = "NO-SUCH-CANDIDATE"
        selection.write_text(json.dumps(document), encoding="utf-8")
        answers = _pair_answers(layout_v2)
        # the scene is the AGGREGATE: its top-level code names the scene, and
        # each artifact's own code is a row (A14)
        assert answers.pop("/scene") == (409, "SCENE_ARTIFACT_INVALID")
        for route, (status, code) in answers.items():
            assert (status, code) == (409, CLEARANCE_MISMATCH), (route, status, code)
        assert_scene_refuses(layout_v2, LAYOUT_V2_SELECTED_ARTIFACT, CLEARANCE_MISMATCH)
        assert_scene_refuses(layout_v2, LEVEL_ACCESSES_ARTIFACT, CLEARANCE_MISMATCH)
    assert layout_v2.get("/design/layout-v2/selected")[0] == 200


def test_accesses_without_their_selection_are_refused_everywhere(layout_v2: Stack) -> None:
    """The other orphan direction, which C1 already covered — pinned here
    beside its new twin so the pair contract is one readable table."""
    selection = layout_v2.derived / LAYOUT_V2_SELECTED_ARTIFACT
    with mutated(selection), derived_restored(layout_v2):
        selection.unlink()
        assert layout_v2.get("/design/level-accesses") == (409, SELECTION_STALE)
        assert layout_v2.get("/design/layout-v2/selected") == (409, "LAYOUT_V2_NOT_SELECTED")
        assert layout_v2.get("/design/ramp") == (409, "LAYOUT_V2_NOT_SELECTED")
        # C2 is unchanged: an ABSENT selection stays the EXPECTED absence
        assert layout_v2.get("/design/ramp-source") == (200, None)
        assert_scene_refuses(layout_v2, LEVEL_ACCESSES_ARTIFACT, SELECTION_STALE)
        # the builders read the ACTIVE RAMP first, and an ABSENT selection is
        # C2's expected absence there — the ramp is not selected, not stale
        for route in PAIR_POSTS:
            assert layout_v2.post(route) == (409, "LAYOUT_V2_NOT_SELECTED"), route
    assert layout_v2.get("/design/level-accesses")[0] == 200


def test_re_selecting_the_same_candidate_repairs_a_damaged_pair(layout_v2: Stack) -> None:
    """S5. "Repair is always an explicit user write" was a measured no-op: the
    idempotency short-circuit snapshotted only the selection, so for the same
    candidate at the same catalogue revision ``select`` and ``activate``
    answered **200** and restored NOTHING whatever state the co-published half
    was in (measured: accesses deleted → ``level_accesses.json`` restored:
    False; accesses = ``{`` → bytes still ``b'{'``). The no-op now requires
    BOTH halves VALID."""
    accesses = layout_v2.derived / LEVEL_ACCESSES_ARTIFACT
    selection = layout_v2.derived / LAYOUT_V2_SELECTED_ARTIFACT
    candidate = json.loads(selection.read_text(encoding="utf-8"))["candidateId"]
    pristine_accesses = accesses.read_bytes()
    wrong_shape = json.dumps({**json.loads(pristine_accesses), "accesses": [1, 2]})
    # the third row is a PARSEABLE, revision- and identity-consistent half that
    # only the explicit ``accesses_half.state == "VALID"`` conjunct of the
    # idempotent no-op can see (C5's pair check reads presence, parseability
    # and identity, never the shape) — it is what pins S5 on its own
    for damage in (None, "{", wrong_shape):
        with mutated(accesses, selection), derived_restored(layout_v2):
            if damage is None:
                accesses.unlink()
            else:
                accesses.write_text(damage, encoding="utf-8")
            assert layout_v2.post("/design/layout-v2/select", json={"candidateId": candidate}) == (
                200,
                None,
            ), damage
            assert accesses.is_file(), damage
            assert json.loads(accesses.read_text(encoding="utf-8")) == json.loads(
                pristine_accesses
            ), damage
            assert layout_v2.get("/design/level-accesses")[0] == 200, damage
            assert layout_v2.get("/design/layout-v2/selected")[0] == 200, damage


# --------------------------------------------------------------------------- #
# Stage D S1 — an unresolvable ramp source never SKIPS the mesh provenance check
# --------------------------------------------------------------------------- #


def test_an_unreadable_ramp_source_refuses_the_development_mesh(layout_v2: Stack) -> None:
    """S1 on the wire. ``ramp_source.json`` present but UNREADABLE (its stat
    succeeds, its bytes do not) used to make ``_development_mesh_source_check``
    ``return None`` — a silently skipped provenance check.

    Pre-change literals, measured at commit 3 with the file replaced by a
    DIRECTORY (``stat`` succeeds, ``read_bytes`` raises ``IsADirectoryError``):
    ``GET …/design/development-mesh`` **200** and its GLB route **200**, while
    ``POST …/design/development-mesh?sync=true`` answered 409
    ``ARTIFACT_MALFORMED`` — the reader serving what the writer refused. The
    control (``ramp_source.json`` = ``{``) answered 409 on the mesh even then,
    but with the WRONG code and the WRONG file: 409 ``ARTIFACT_STALE`` naming
    ``development_mesh.json`` for a defect that belongs to ``ramp_source.json``
    ("one artifact never reports another's defect"). Unreadable and
    unparseable are ONE outcome now, and both name the source file."""
    source = layout_v2.derived / RAMP_SOURCE_FILE
    with mutated(source), derived_restored(layout_v2):
        source.unlink()
        source.mkdir()
        try:
            assert layout_v2.get("/design/development-mesh") == (409, MALFORMED)
            assert layout_v2.get("/design/development-mesh/mesh.glb") == (409, MALFORMED)
            assert layout_v2.get("/design/ramp-source") == (409, MALFORMED)
            assert_scene_refuses(layout_v2, RAMP_SOURCE_FILE, MALFORMED)
            assert_scene_refuses(layout_v2, DEVELOPMENT_MESH_ARTIFACT, MALFORMED)
        finally:
            source.rmdir()
    # the UNPARSEABLE control, whose code changed with it (was ARTIFACT_STALE
    # on development_mesh.json)
    for junk in ("{", json.dumps({"activeSource": "NOT_A_SOURCE"})):
        with mutated(source), derived_restored(layout_v2):
            source.write_text(junk, encoding="utf-8")
            assert layout_v2.get("/design/development-mesh") == (409, MALFORMED), junk
            assert layout_v2.get("/design/development-mesh/mesh.glb") == (409, MALFORMED), junk
            assert_scene_refuses(layout_v2, DEVELOPMENT_MESH_ARTIFACT, MALFORMED)
    assert layout_v2.get("/design/development-mesh")[0] == 200


# --------------------------------------------------------------------------- #
# Stage D S2 — the one two-artifact read endpoint has a linearization point
# --------------------------------------------------------------------------- #


def test_the_capability_path_reads_its_two_artifacts_from_one_snapshot(
    legacy: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S2. ``GET …/design/capability-graph/path`` used to read
    ``capability_graph.json`` in one ``ArtifactReader`` snapshot and
    ``network.json`` in a SECOND one, and it is not a builder, so no rule-60
    fingerprint re-check could fail it closed.

    Pre-change literal, measured at commit 3 with a timing hook between the
    two reads and a real ``POST …/design/levels`` + ``POST …/network/generate``
    landing in it: **500 Internal Server Error** with no ``detail.code``
    (``KeyError`` in ``capability/builder.py``: the endpoints were built from
    the NEW network and the capability payload came from the OLD snapshot).

    The hook here changes TIMING only: an unmodified ``ArtifactReader.read``
    pauses AFTER it has classified the capability graph."""
    from minegen.services.artifact_reader import ArtifactReader as Reader

    nodes = legacy.client.get(f"{API}/{legacy.sid}/network").json()["nodes"]
    portal = next(n["id"] for n in nodes if n["type"] == "PORTAL")
    target = next(n["id"] for n in nodes if n["type"] != "PORTAL")
    route = f"{API}/{legacy.sid}/design/capability-graph/path"
    params = {"source": portal, "target": target, "capability": "PERSONNEL_ACCESS"}
    assert legacy.client.get(route, params=params).status_code == 200

    inside = threading.Event()
    release = threading.Event()
    original = Reader.read
    armed = [True]

    def patched(self: Reader, snapshot: Any, name: str) -> Any:
        result = original(self, snapshot, name)
        if armed[0] and name == CAPABILITY_GRAPH_ARTIFACT:
            armed[0] = False
            inside.set()
            assert release.wait(60), "the test never released the paused read"
        return result

    with derived_restored(legacy):
        monkeypatch.setattr(Reader, "read", patched)
        box: dict[str, Any] = {}

        def run() -> None:
            box["answer"] = _answer(legacy.client.get(route, params=params))

        reader = threading.Thread(target=run, daemon=True)
        reader.start()
        assert inside.wait(60), "the path read never reached its pause"
        assert legacy.post("/design/levels") == (200, None)
        assert legacy.post("/network/generate") == (200, None)
        release.set()
        reader.join(120)
        monkeypatch.undo()
        status, code = box["answer"]
        assert status != 500, box["answer"]
        assert status == 200 or code is not None, box["answer"]


# --------------------------------------------------------------------------- #
# Stage D S7 — Q-WORLD-GUARD, observed on the wire
# --------------------------------------------------------------------------- #

#: the 21 derived read routes of ``docs/api.md``'s Q-WORLD-GUARD table,
#: transcribed as literals. 11 of the answers changed at AC-01F commit 2, of
#: which 4 changed STATUS — the four marked below.
Q_WORLD_GUARD: tuple[tuple[str, str], ...] = (
    ("/design/targets", "unchanged"),
    ("/design/decline", "unchanged"),
    ("/design/decline/smooth", "unchanged"),
    ("/design/layout-v2", "unchanged"),
    ("/design/ramp", "unchanged"),
    ("/design/tunnel", "unchanged"),
    ("/design/tunnel/mesh.glb", "unchanged"),
    ("/design/development-mesh", "unchanged"),
    ("/design/development-mesh/mesh.glb", "unchanged"),
    ("/scene", "unchanged"),
    ("/design/layout-v2/selected", "409 LAYOUT_V2_NOT_SELECTED"),
    ("/design/level-accesses", "409 LEVEL_ACCESSES_NOT_GENERATED"),
    ("/design/levels", "409 LEVELS_NOT_GENERATED"),
    ("/design/stopes", "409 STOPES_NOT_GENERATED"),
    ("/design/timeline", "409 TIMELINE_NOT_GENERATED"),
    ("/infrastructure/communication", "409 COMMUNICATION_NOT_GENERATED"),
    ("/infrastructure/sensors", "409 SENSORS_NOT_GENERATED"),
    ("/design/ramp-source", "200 summary"),  # STATUS CHANGE
    ("/design/shafts", "404 SHAFTS_NOT_GENERATED"),  # STATUS CHANGE
    ("/network", "404 NETWORK_NOT_GENERATED"),  # STATUS CHANGE
    ("/design/capability-graph", "404 CAPABILITY_GRAPH_NOT_GENERATED"),  # STATUS CHANGE
)


@pytest.fixture(scope="module")
def no_world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    """A scenario CREATED but never world-generated — the state the
    Q-WORLD-GUARD table describes."""
    stack, context = _make_stack(tmp_path_factory.mktemp("no_world"))
    assert not stack.store.arrays_path(stack.sid).exists()
    yield stack
    context.__exit__(None, None, None)
    stack.jobs.shutdown()


def test_every_derived_read_route_answers_world_not_generated_without_a_world(
    no_world: Stack,
) -> None:
    """S7. Q-WORLD-GUARD is the largest documented observable change of
    commit 2 and had no wire-level test: every existing ``WORLD_NOT_GENERATED``
    assertion in the suite covered a row the table marks UNCHANGED, so the 11
    changed answers — and the 4 changed STATUSES — were pinned nowhere. A
    derived artifact is never trusted without a world (the snapshot's own
    ``arrays.npz`` stat), so all 21 routes answer 409 ``WORLD_NOT_GENERATED``;
    the HEAD ``12d7725`` answer of each row is quoted beside it."""
    assert len(Q_WORLD_GUARD) == 21
    assert sum(1 for _, head in Q_WORLD_GUARD if head != "unchanged") == 11
    assert sum(1 for _, head in Q_WORLD_GUARD if head.startswith(("200", "404"))) == 4
    for route, head_answer in Q_WORLD_GUARD:
        assert no_world.get(route) == (409, "WORLD_NOT_GENERATED"), (route, head_answer)
