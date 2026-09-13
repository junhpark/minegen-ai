"""AC-01F COMMIT 1 ONLY — the OLD live readers against the NEW resolver.

The AC-01E ``test_artifact_registry_transition.py`` pattern: commit 1 adds the
resolver WITHOUT switching a single consumer, so this module can execute the
OLD reader and the NEW one side by side on the SAME store and prove what
changed and what did not. Commit 2 switches the consumers and DELETES this
module (the PR history carries the proof).

Three halves:

1. **VALID equality.** On both oracle stacks (LEGACY and LAYOUT_V2, built
   through the real API exactly as ``ac01f_A/oracle/README.md`` records),
   every artifact: ``json.dumps(OLD reader result) ==
   json.dumps(NEW require(...))`` with key ORDER preserved
   (``sort_keys=False``). ABSENT artifacts must raise the same class on both
   sides.
2. **Scene equality.** ``WorldService.scene(sid)`` (the live 18-read,
   lock-free assembly at HEAD) against an assembly built from ONE resolver
   snapshot, in the same key order — byte for byte on the same files.
3. **The stale-state difference table.** Every row of the Stage A §2 / §4.2
   matrix, transcribed as LITERALS with its Stage A reference: the mutation is
   applied, the OLD outcome is OBSERVED through the real ``TestClient``
   (``raise_server_exceptions=False``, so a bare 500 is a response) and the
   NEW ``ArtifactRead.state`` + error code is asserted beside it. Mutations
   are undone with the ORIGINAL bytes AND the original ``st_mtime_ns``
   (Stage A C-12: rewriting bytes without restoring the mtime silently
   changes the revision and contaminates the next case).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
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
from minegen.export.scene_manifest import build_scene
from minegen.main import create_app
from minegen.services.artifact_errors import (
    ArtifactMalformedError,
    DeclineNotGeneratedError,
    LayoutV2NotGeneratedError,
    LayoutV2NotSelectedError,
    LevelAccessesNotGeneratedError,
    SmoothedNotGeneratedError,
    TargetsNotGeneratedError,
    WorldNotGeneratedError,
)
from minegen.services.artifact_reader import READ_SPECS, ArtifactReader, ArtifactSnapshot
from minegen.services.design_service import DesignService
from minegen.services.effective_ramp import (
    legacy_adapter,
    read_ramp_source,
    resolve_effective_ramp,
)
from minegen.services.infrastructure_service import InfrastructureService
from minegen.services.job_service import JobService
from minegen.services.scenario_service import ScenarioStore
from minegen.services.world_service import WorldService, _layout_summary
from tests.conftest import small_scenario

API = "/api/v1/scenarios"


# --------------------------------------------------------------------------- #
# the two oracle stacks (ac01f_A/oracle/README.md, verbatim call order)
# --------------------------------------------------------------------------- #


@dataclass
class Stack:
    store: ScenarioStore
    worlds: WorldService
    design: DesignService
    infra: InfrastructureService
    client: TestClient
    sid: str

    @property
    def derived(self) -> Path:
        return self.store.derived_dir(self.sid)

    @property
    def reader(self) -> ArtifactReader:
        return ArtifactReader(self.store)


def _build_stack(root: Path, source: str) -> tuple[Stack, Any]:
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

    # tests/test_shafts_api.py::_prepare_with_shaft + test_smoothing_api::_prepare
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

    def step(method: str, path: str, **kwargs: Any) -> Any:
        response = client.request(method, f"{API}/{sid}{path}", **kwargs)
        assert response.status_code in (200, 201), (path, response.status_code, response.text[:400])
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
        assert winner, "the oracle fixture must produce a winner"
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
    return Stack(store, worlds, design, infra, client, sid), (context, jobs)


@pytest.fixture(scope="module")
def legacy(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    stack, (context, jobs) = _build_stack(tmp_path_factory.mktemp("legacy"), "LEGACY")
    yield stack
    context.__exit__(None, None, None)
    jobs.shutdown()


@pytest.fixture(scope="module")
def layout_v2(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    stack, (context, jobs) = _build_stack(tmp_path_factory.mktemp("layout_v2"), "LAYOUT_V2")
    yield stack
    context.__exit__(None, None, None)
    jobs.shutdown()


# --------------------------------------------------------------------------- #
# OLD readers (the LIVE service methods at HEAD) and the direct GET routes
# --------------------------------------------------------------------------- #

OldReader = Callable[[Stack], Any]

OLD_READERS: dict[str, OldReader] = {
    # raw readers (dict artifacts)
    TARGETS_ARTIFACT: lambda s: s.design.targets(s.sid),  # design_service.py:1415-1425
    DECLINE_ARTIFACT: lambda s: s.design.decline(s.sid),  # :1403-1413
    LEGACY_RAMP_ARTIFACT: lambda s: s.design.smoothed(s.sid),  # :524-534
    LAYOUT_V2_ARTIFACT: lambda s: s.design.layout_v2(s.sid),  # :581-591
    LAYOUT_V2_SELECTED_ARTIFACT: lambda s: s.design.layout_selected(s.sid),  # :773-778
    LEVEL_ACCESSES_ARTIFACT: lambda s: s.design.level_accesses(s.sid),  # :780-786
    TUNNEL_MESH_ARTIFACT: lambda s: s.design.tunnel(s.sid),  # :1384-1394
    DEVELOPMENT_MESH_ARTIFACT: lambda s: s.design.development_mesh(s.sid),  # :1365-1375
    # validated readers (the eight ApiModel artifacts)
    LEVELS_ARTIFACT: lambda s: s.design.levels(s.sid),  # :888-893
    SHAFTS_ARTIFACT: lambda s: s.design.shafts(s.sid),  # :1050-1055
    NETWORK_ARTIFACT: lambda s: s.design.network(s.sid),  # :1176-1181
    CAPABILITY_GRAPH_ARTIFACT: lambda s: s.design.capability_graph(s.sid),  # :1102-1114
    STOPES_ARTIFACT: lambda s: s.design.stopes(s.sid),  # :939-944
    TIMELINE_ARTIFACT: lambda s: s.design.timeline(s.sid),  # :992-997
    COMMUNICATION_ARTIFACT: lambda s: s.infra.communication(s.sid),  # infra:85-90
    SENSORS_ARTIFACT: lambda s: s.infra.sensors(s.sid),  # infra:138-143
}

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

#: which artifacts each oracle stack carries (Stage A §10: LEGACY writes 16
#: files and NO ramp_source.json — LEGACY IS the absence of the file)
LEGACY_ABSENT = (
    LAYOUT_V2_ARTIFACT,
    LAYOUT_V2_SELECTED_ARTIFACT,
    LEVEL_ACCESSES_ARTIFACT,
    RAMP_SOURCE_FILE,
)
LAYOUT_V2_ABSENT = (TARGETS_ARTIFACT, DECLINE_ARTIFACT, LEGACY_RAMP_ARTIFACT)

#: the SPECIFIC class every absent artifact must raise on BOTH sides — one row
#: per name in ``LEGACY_ABSENT`` ∪ ``LAYOUT_V2_ABSENT`` (``ramp_source.json``
#: excluded: it has no OLD dict reader and a documented absent DEFAULT). There
#: is deliberately NO ``Exception`` fallback: a missing row must fail loudly
#: with ``KeyError`` rather than let ``pytest.raises(Exception)`` accept any
#: failure at all.
ABSENT_ERRORS: dict[str, type[Exception]] = {
    LAYOUT_V2_ARTIFACT: LayoutV2NotGeneratedError,
    LAYOUT_V2_SELECTED_ARTIFACT: LayoutV2NotSelectedError,
    LEVEL_ACCESSES_ARTIFACT: LevelAccessesNotGeneratedError,
    TARGETS_ARTIFACT: TargetsNotGeneratedError,
    DECLINE_ARTIFACT: DeclineNotGeneratedError,
    LEGACY_RAMP_ARTIFACT: SmoothedNotGeneratedError,
}
assert set(ABSENT_ERRORS) == (set(LEGACY_ABSENT) | set(LAYOUT_V2_ABSENT)) - {RAMP_SOURCE_FILE}


def _json(value: Any) -> str:
    """Serialization that preserves key ORDER (``sort_keys=False``)."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", by_alias=True)
    return json.dumps(value, sort_keys=False)


def _new_payload(stack: Stack, name: str) -> Any:
    read = stack.reader.require(stack.sid, name)
    if READ_SPECS[name].model is not None:
        assert read.model is not None
        return read.model
    return read.raw


# --------------------------------------------------------------------------- #
# 1. VALID equality — OLD reader == NEW resolver on every artifact
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("source", ["LEGACY", "LAYOUT_V2"])
def test_new_resolver_returns_exactly_what_the_old_readers_return(
    source: str, legacy: Stack, layout_v2: Stack
) -> None:
    stack = legacy if source == "LEGACY" else layout_v2
    absent = LEGACY_ABSENT if source == "LEGACY" else LAYOUT_V2_ABSENT
    compared = 0
    for name, old_reader in OLD_READERS.items():
        if name in absent:
            # the SPECIFIC class, never a bare Exception: KeyError here means a
            # row is missing from the table, which must fail the test loudly
            expected = ABSENT_ERRORS[name]
            with pytest.raises(expected):
                old_reader(stack)
            with pytest.raises(expected):
                stack.reader.require(stack.sid, name)
            continue
        old = old_reader(stack)
        new = _new_payload(stack, name)
        assert _json(old) == _json(new), name  # key order included
        compared += 1
    # the ramp source has no OLD dict reader — its OLD authority is the
    # silent ``read_ramp_source`` (effective_ramp.py:75-84)
    old_source = read_ramp_source(stack.derived)
    new_source = stack.reader.resolve_ramp_source(stack.reader.snapshot(stack.sid))
    assert old_source == new_source == source
    # 16 OLD reader methods (``ramp_source.json`` has no dict reader) minus
    # the 3 artifacts this source never writes
    assert compared == len(OLD_READERS) - len(set(absent) & set(OLD_READERS)) == 13


# --------------------------------------------------------------------------- #
# 2. Scene equality — one snapshot assembles exactly today's scene
# --------------------------------------------------------------------------- #

#: ``world_service.py:132-146``, verbatim order
SCENE_SLOTS: tuple[tuple[str, str], ...] = (
    ("accessTargets", TARGETS_ARTIFACT),
    ("decline", DECLINE_ARTIFACT),
    ("smoothedDecline", LEGACY_RAMP_ARTIFACT),
    ("tunnelMesh", TUNNEL_MESH_ARTIFACT),
    ("developmentMesh", DEVELOPMENT_MESH_ARTIFACT),
    ("levels", LEVELS_ARTIFACT),
    ("shafts", SHAFTS_ARTIFACT),
    ("network", NETWORK_ARTIFACT),
    ("capabilityGraph", CAPABILITY_GRAPH_ARTIFACT),
    ("stopes", STOPES_ARTIFACT),
    ("timeline", TIMELINE_ARTIFACT),
    ("communication", COMMUNICATION_ARTIFACT),
    ("sensors", SENSORS_ARTIFACT),
)


def assemble_scene_from_snapshot(stack: Stack) -> dict[str, Any]:
    """The scene, assembled from ONE resolver snapshot in today's key order.
    Lives in the TEST (never in production) — commit 2 owns the production
    assembly; this is only the equality partner of ``WorldService.scene``."""
    reader = stack.reader
    scenario, world = stack.worlds.load(stack.sid)
    scene = build_scene(scenario, world)
    snapshot: ArtifactSnapshot = reader.snapshot(stack.sid)
    reads = {name: reader.read(snapshot, name) for name in READ_SPECS}
    for key, name in SCENE_SLOTS:
        read = reads[name]
        assert read.state in ("VALID", "ABSENT"), (name, read.state, read.error)
        scene[key] = read.raw
    # the Effective Ramp, resolved from the SAME observations
    source = reader.resolve_ramp_source(snapshot)
    legacy_read = reads[LEGACY_RAMP_ARTIFACT]
    selected_read = reads[LAYOUT_V2_SELECTED_ARTIFACT]
    if source == "LEGACY":
        owning, payload = LEGACY_RAMP_ARTIFACT, None
        if legacy_read.state == "VALID":
            payload = legacy_adapter(dict(legacy_read.raw or {}), legacy_read.revision)
    else:
        owning, payload = LAYOUT_V2_SELECTED_ARTIFACT, None
        if selected_read.state == "VALID":
            payload = {
                **(selected_read.raw or {}),
                "owningArtifact": LAYOUT_V2_SELECTED_ARTIFACT,
                "activeSource": "LAYOUT_V2",
            }
    scene["legacySmoothedDecline"] = reads[LEGACY_RAMP_ARTIFACT].raw
    scene["smoothedDecline"] = payload
    scene["rampSource"] = {
        "activeSource": source,
        "owningArtifact": owning,
        "available": payload is not None,
        "legacyAvailable": legacy_read.state != "ABSENT",
        "layoutV2Available": reads[LAYOUT_V2_ARTIFACT].state != "ABSENT",
        "layoutV2Selected": selected_read.state != "ABSENT",
        "sourceKind": payload.get("sourceKind") if payload else None,
        "sourceRevision": payload.get("sourceRevision") if payload else None,
        "candidateId": payload.get("candidateId") if payload else None,
        "family": payload.get("family") if payload else None,
        "status": payload.get("status") if payload else None,
        "segmentCount": len(payload.get("segments", [])) if payload else 0,
    }
    catalogue = reads[LAYOUT_V2_ARTIFACT].raw
    scene["layoutV2"] = _layout_summary(catalogue) if catalogue is not None else None
    scene["layoutV2Selected"] = selected_read.raw
    scene["levelAccesses"] = reads[LEVEL_ACCESSES_ARTIFACT].raw
    return scene


@pytest.mark.parametrize("source", ["LEGACY", "LAYOUT_V2"])
def test_one_snapshot_assembles_exactly_todays_scene(
    source: str, legacy: Stack, layout_v2: Stack
) -> None:
    stack = legacy if source == "LEGACY" else layout_v2
    old = stack.worlds.scene(stack.sid)  # world_service.py:128-176, unchanged
    new = assemble_scene_from_snapshot(stack)
    assert list(old.keys()) == list(new.keys())
    assert json.dumps(old, sort_keys=False) == json.dumps(new, sort_keys=False)
    # the live scene is also what the API serves
    served = stack.client.get(f"{API}/{stack.sid}/scene")
    assert served.status_code == 200
    assert json.dumps(served.json(), sort_keys=False) == json.dumps(new, sort_keys=False)


def test_the_active_ramp_owner_is_observed_once_per_snapshot(layout_v2: Stack) -> None:
    """R4 (Stage A §5.3): today the active owner is read TWICE per scene and
    probed a third time (``effective_ramp.py:157``). One snapshot has ONE
    observation, and it agrees with the live resolution."""
    stack = layout_v2
    snapshot = stack.reader.snapshot(stack.sid)
    observation = snapshot.observation(LAYOUT_V2_SELECTED_ARTIFACT)
    assert observation is not None and observation.present
    live = resolve_effective_ramp(stack.derived)
    assert live.layout_v2_selected is True
    assert live.payload is not None
    assert live.payload["candidateId"] == json.loads(observation.data or b"{}")["candidateId"]


# --------------------------------------------------------------------------- #
# 3. the stale-state difference table
# --------------------------------------------------------------------------- #


@contextmanager
def mutated(paths: list[Path]) -> Iterator[None]:
    """Restore bytes AND ``st_mtime_ns`` afterwards. Stage A C-12: rewriting
    bytes without restoring the mtime silently changes the revision and
    contaminates every later case."""
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


def observe(stack: Stack, route: str) -> tuple[int, str | None]:
    """What the API answers TODAY (``raise_server_exceptions=False``, so an
    unhandled exception is observed as a 500 response, exactly as the Stage A
    probes observed it)."""
    response = stack.client.get(f"{API}/{stack.sid}{route}")
    code: str | None = None
    try:
        body = response.json()
        if isinstance(body, dict) and isinstance(body.get("detail"), dict):
            code = str(body["detail"].get("code"))
    except ValueError:
        code = None
    return response.status_code, code


def observe_post(stack: Stack, path: str, **kwargs: Any) -> tuple[int, str | None]:
    """What a dependent BUILDER answers today for the same mutation
    (``raise_server_exceptions=False``: the infrastructure catch-all's
    ``500 INTERNAL_ERROR`` is a response, a bare unhandled 500 has no code)."""
    response = stack.client.post(f"{API}/{stack.sid}{path}", **kwargs)
    code: str | None = None
    try:
        body = response.json()
        if isinstance(body, dict) and isinstance(body.get("detail"), dict):
            code = str(body["detail"].get("code"))
    except ValueError:
        code = None
    return response.status_code, code


@contextmanager
def derived_restored(stack: Stack) -> Iterator[None]:
    """An exact undo for the rows whose Stage A observation includes
    SUCCESSFUL builder POSTs (§4.1 / §3 I-10): every file under ``derived/`` is
    saved with its bytes AND ``st_mtime_ns`` and put back afterwards, files a
    build created are removed, and the in-memory service caches for this
    scenario are dropped — so a module-scoped fixture survives a row that
    really regenerates artifacts."""
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


#: the ``GET /scene`` key each artifact is projected into
#: (``world_service.py:132-176``) — the SCENE column of the Stage A §4.2 table
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


def read_new(stack: Stack, name: str, *, glb_bytes: bool = False) -> Any:
    read_spec = READ_SPECS[name]
    snapshot = stack.reader.snapshot(
        stack.sid,
        [name, *read_spec.provenance_inputs, *read_spec.agreement_inputs],
        glb_bytes=glb_bytes,
    )
    return stack.reader.read(snapshot, name)


@dataclass(frozen=True)
class BuilderPost:
    """ONE dependent-builder observation of the SAME mutation, transcribed from
    the "DOWNSTREAM BUILDER" column of Stage A §4.2 (and §4.1 for the shafts
    canary / §3 I-10 for the stale selection)."""

    path: str
    status: int
    code: str | None
    params: dict[str, Any] | None = None
    #: ``POST …/design/layout-v2/select`` needs the catalogue's own winner id
    winner_body: bool = False


@dataclass(frozen=True)
class StaleCase:
    artifact: str
    #: the input whose revision alone is bumped (Stage A §4: ``os.utime``)
    input_file: str
    old_status: int
    old_code: str | None
    new_state: str
    new_code: str | None
    stage_a: str
    #: Stage A §4.2 SCENE column — "the scene refused nothing in all 17 rows":
    #: 200, and the artifact's own slot is SERVED (non-null)
    scene_status: int = 200
    scene_served: bool = True
    #: the recorded downstream builders; empty where §4.2 records none, or
    #: where it records one measured on a chain this fixture does not have
    builder_posts: tuple[BuilderPost, ...] = ()


#: Stage A §4.2 "one stale state per artifact", transcribed verbatim. Every
#: OLD cell below is the OBSERVED HEAD behaviour, not a derivation, and every
#: ``BuilderPost`` is that row's own "DOWNSTREAM BUILDER" cell.
STALE_CASES: tuple[StaleCase, ...] = (
    StaleCase(
        TARGETS_ARTIFACT,
        "arrays.npz",
        200,
        None,
        "VALID",
        None,
        "§4.2 row 1",
        builder_posts=(
            # "decline 200 SUCCESS"
            BuilderPost("/design/decline", 200, None, params={"maxLevels": 2, "sync": "true"}),
        ),
    ),
    StaleCase(
        DECLINE_ARTIFACT,
        TARGETS_ARTIFACT,
        200,
        None,
        "VALID",
        None,
        "§4.2 row 2",
        # "smooth 200 SUCCESS"
        builder_posts=(BuilderPost("/design/decline/smooth", 200, None, params={"sync": "true"}),),
    ),
    StaleCase(
        LEGACY_RAMP_ARTIFACT,
        DECLINE_ARTIFACT,
        200,
        None,
        "VALID",
        None,
        "§4.2 row 3",
        # "tunnel 200, levels 200" — the cheaper of the two
        builder_posts=(BuilderPost("/design/levels", 200, None),),
    ),
    StaleCase(TUNNEL_MESH_ARTIFACT, LEGACY_RAMP_ARTIFACT, 200, None, "VALID", None, "§4.2 row 4"),
    StaleCase(
        LEVELS_ARTIFACT,
        LEGACY_RAMP_ARTIFACT,
        200,
        None,
        "VALID",
        None,
        "§4.2 row 5",
        # "shafts 200, network 200, stopes 200"
        builder_posts=(BuilderPost("/design/stopes", 200, None),),
    ),
    StaleCase(DEVELOPMENT_MESH_ARTIFACT, LEVELS_ARTIFACT, 200, None, "VALID", None, "§4.2 row 6"),
    # the canary: the ONE artifact whose GET serves what its builders refuse.
    # The five POSTs are Stage A §4.1 verbatim — and they ARE the I-6 asymmetry:
    # the same ShaftsStaleError is a typed 409 on design/network and a leaked
    # 500 INTERNAL_ERROR on both infrastructure routes.
    StaleCase(
        SHAFTS_ARTIFACT,
        LEVELS_ARTIFACT,
        200,
        None,
        "STALE",
        "SHAFTS_STALE",
        "§4.1 / §4.2 row 7 / §3 I-6",
        builder_posts=(
            BuilderPost("/network/generate", 409, "SHAFTS_STALE"),
            BuilderPost("/design/capability-graph", 409, "SHAFTS_STALE"),
            BuilderPost("/design/timeline", 409, "SHAFTS_STALE"),
            BuilderPost("/infrastructure/communication", 500, "INTERNAL_ERROR"),
            BuilderPost("/infrastructure/sensors", 500, "INTERNAL_ERROR"),
        ),
    ),
    # §4.2 rows 8 and 10 record their downstream builders on a chain measured
    # "WITHOUT shafts" / "no shafts"; this fixture HAS a shaft spec, so bumping
    # levels.json also makes shafts.json stale and those cells do not transfer
    # (that interaction is row 7's own I-6 observation). No POST is asserted.
    StaleCase(NETWORK_ARTIFACT, LEVELS_ARTIFACT, 200, None, "VALID", None, "§4.2 row 8"),
    StaleCase(
        CAPABILITY_GRAPH_ARTIFACT,
        NETWORK_ARTIFACT,
        409,
        "CAPABILITY_GRAPH_STALE",
        "STALE",
        "CAPABILITY_GRAPH_STALE",
        "§4.2 row 9",
    ),
    StaleCase(STOPES_ARTIFACT, LEVELS_ARTIFACT, 200, None, "VALID", None, "§4.2 row 10"),
    # rows 11-13 are leaves: §4.2 records no downstream builder at all
    StaleCase(TIMELINE_ARTIFACT, NETWORK_ARTIFACT, 200, None, "VALID", None, "§4.2 row 11"),
    StaleCase(COMMUNICATION_ARTIFACT, NETWORK_ARTIFACT, 200, None, "VALID", None, "§4.2 row 12"),
    StaleCase(SENSORS_ARTIFACT, NETWORK_ARTIFACT, 200, None, "VALID", None, "§4.2 row 13"),
)

#: the LAYOUT_V2-only rows of the same table
STALE_CASES_LAYOUT_V2: tuple[StaleCase, ...] = (
    StaleCase(
        LAYOUT_V2_ARTIFACT,
        "arrays.npz",
        200,
        None,
        "VALID",
        None,
        "§4.2 row 14",
        # "select 200"
        builder_posts=(BuilderPost("/design/layout-v2/select", 200, None, winner_body=True),),
    ),
    # §3 I-10, verbatim: ONE `os.utime(layout_v2.json)` splits one request
    # family — the four builders that call `_active_clearance_policy` refuse
    # with LAYOUT_V2_SELECTION_STALE while five others build happily ON the
    # stale selection. The order below is I-10's own order.
    StaleCase(
        LAYOUT_V2_SELECTED_ARTIFACT,
        LAYOUT_V2_ARTIFACT,
        200,
        None,
        "STALE",
        "LAYOUT_V2_SELECTION_STALE",
        "§4.2 row 15 / §3 I-10",
        builder_posts=(
            BuilderPost("/design/levels", 409, "LAYOUT_V2_SELECTION_STALE"),
            BuilderPost(
                "/design/tunnel", 409, "LAYOUT_V2_SELECTION_STALE", params={"sync": "true"}
            ),
            BuilderPost(
                "/design/development-mesh",
                409,
                "LAYOUT_V2_SELECTION_STALE",
                params={"sync": "true"},
            ),
            BuilderPost("/design/shafts", 409, "LAYOUT_V2_SELECTION_STALE"),
            BuilderPost("/design/stopes", 200, None),
            BuilderPost("/network/generate", 200, None),
            BuilderPost("/design/timeline", 200, None),
            BuilderPost("/infrastructure/communication", 200, None),
            BuilderPost("/infrastructure/sensors", 200, None),
        ),
    ),
    StaleCase(
        LEVEL_ACCESSES_ARTIFACT,
        LAYOUT_V2_ARTIFACT,
        200,
        None,
        "STALE",
        "LAYOUT_V2_SELECTION_STALE",
        "§4.2 row 16 / §4.4",
    ),
    StaleCase(
        RAMP_SOURCE_FILE, LAYOUT_V2_SELECTED_ARTIFACT, 200, None, "VALID", None, "§4.2 row 17"
    ),
)


def _run_builder_posts(stack: Stack, case: StaleCase) -> None:
    """The row's recorded DOWNSTREAM BUILDER cell. A successful build really
    writes and cascades, so the whole ``derived/`` tree is captured and put
    back byte- and mtime-exact afterwards."""
    if not case.builder_posts:
        return
    with derived_restored(stack):
        for post in case.builder_posts:
            kwargs: dict[str, Any] = {}
            if post.params is not None:
                kwargs["params"] = post.params
            if post.winner_body:
                catalogue = json.loads(
                    (stack.derived / LAYOUT_V2_ARTIFACT).read_text(encoding="utf-8")
                )
                kwargs["json"] = {"candidateId": catalogue["winnerId"]}
            observed = observe_post(stack, post.path, **kwargs)
            assert observed == (post.status, post.code), (case.artifact, post.path, observed)


def _run_stale_case(stack: Stack, case: StaleCase) -> None:
    target = (
        stack.store.arrays_path(stack.sid)
        if case.input_file == "arrays.npz"
        else stack.derived / case.input_file
    )
    with mutated([target]):
        bump(target)
        status, code = observe(stack, ROUTES[case.artifact])
        assert (status, code) == (case.old_status, case.old_code), (case, status, code)
        # Stage A §4.2 SCENE column: "The scene refused nothing in all 17 rows."
        scene_status, _ = observe(stack, "/scene")
        assert scene_status == case.scene_status, (case, scene_status)
        if scene_status == 200:
            slot = stack.client.get(f"{API}/{stack.sid}/scene").json()[SCENE_SLOT[case.artifact]]
            assert (slot is not None) == case.scene_served, (case, slot)
        _run_builder_posts(stack, case)
        read = read_new(stack, case.artifact)
        assert read.state == case.new_state, (case, read.state, read.error)
        if case.new_code is None:
            assert read.error is None, case
        else:
            assert read.error is not None and type(read.error).code == case.new_code, case


@pytest.mark.parametrize("case", STALE_CASES, ids=[c.artifact for c in STALE_CASES])
def test_stale_state_difference_table_legacy(case: StaleCase, legacy: Stack) -> None:
    _run_stale_case(legacy, case)


@pytest.mark.parametrize(
    "case", STALE_CASES_LAYOUT_V2, ids=[c.artifact for c in STALE_CASES_LAYOUT_V2]
)
def test_stale_state_difference_table_layout_v2(case: StaleCase, layout_v2: Stack) -> None:
    _run_stale_case(layout_v2, case)


#: Stage A §2.2-2.5 malformed columns for the DIRECT GET reader, transcribed.
#: ``(old status, old detail code)`` for ``{`` and for ``{"hello":"world"}``,
#: then the NEW ``(state, code)``. ``500`` with ``None`` = a bare unhandled
#: exception (non-JSON body); ``500 INTERNAL_ERROR`` = the infrastructure
#: catch-all (``api/infrastructure.py:74``) which leaks ``str(exc)``.
Observed = tuple[int, str | None]
NewRead = tuple[str, str | None]
INTERNAL: Observed = (500, "INTERNAL_ERROR")
UNHANDLED: Observed = (500, None)
SERVED: Observed = (200, None)
MALFORMED: NewRead = ("MALFORMED", "ARTIFACT_MALFORMED")


@dataclass(frozen=True)
class MalformedCase:
    artifact: str
    old_mj: Observed
    old_ms: Observed
    new_mj: NewRead
    new_ms: NewRead
    stage_a: str


#: present on BOTH oracle stacks — the reader is the same object either way
MALFORMED_SHARED: tuple[MalformedCase, ...] = (
    MalformedCase(TUNNEL_MESH_ARTIFACT, UNHANDLED, SERVED, MALFORMED, MALFORMED, "§2.3"),
    MalformedCase(DEVELOPMENT_MESH_ARTIFACT, UNHANDLED, SERVED, MALFORMED, MALFORMED, "§2.3"),
    MalformedCase(LEVELS_ARTIFACT, UNHANDLED, UNHANDLED, MALFORMED, MALFORMED, "§2.4"),
    MalformedCase(SHAFTS_ARTIFACT, UNHANDLED, UNHANDLED, MALFORMED, MALFORMED, "§2.4"),
    MalformedCase(NETWORK_ARTIFACT, UNHANDLED, UNHANDLED, MALFORMED, MALFORMED, "§2.4"),
    MalformedCase(CAPABILITY_GRAPH_ARTIFACT, UNHANDLED, UNHANDLED, MALFORMED, MALFORMED, "§2.4"),
    MalformedCase(STOPES_ARTIFACT, UNHANDLED, UNHANDLED, MALFORMED, MALFORMED, "§2.5"),
    MalformedCase(TIMELINE_ARTIFACT, UNHANDLED, UNHANDLED, MALFORMED, MALFORMED, "§2.5"),
    MalformedCase(COMMUNICATION_ARTIFACT, INTERNAL, INTERNAL, MALFORMED, MALFORMED, "§2.5"),
    MalformedCase(SENSORS_ARTIFACT, INTERNAL, INTERNAL, MALFORMED, MALFORMED, "§2.5"),
)

#: LEGACY-only files (§2.2 legacy chain)
MALFORMED_LEGACY_ONLY: tuple[MalformedCase, ...] = (
    # targets.json has NO first-level precondition: no consumer subscripts it,
    # so a wrong-shaped document stays VALID for the resolver too (§8.2)
    MalformedCase(TARGETS_ARTIFACT, UNHANDLED, SERVED, MALFORMED, ("VALID", None), "§2.2"),
    MalformedCase(DECLINE_ARTIFACT, UNHANDLED, SERVED, MALFORMED, MALFORMED, "§2.2"),
    MalformedCase(LEGACY_RAMP_ARTIFACT, UNHANDLED, SERVED, MALFORMED, MALFORMED, "§2.2"),
)

#: LAYOUT_V2-only files (§2.2 layout-v2 rows). The M-S column of the two
#: certification-bearing documents is the A1 order: no ``layoutRevision`` ⇒
#: ``LAYOUT_V2_SELECTION_STALE`` before any certification or shape check.
MALFORMED_LAYOUT_V2_ONLY: tuple[MalformedCase, ...] = (
    MalformedCase(LAYOUT_V2_ARTIFACT, UNHANDLED, SERVED, MALFORMED, MALFORMED, "§2.2"),
    MalformedCase(
        LAYOUT_V2_SELECTED_ARTIFACT,
        UNHANDLED,
        SERVED,
        MALFORMED,
        ("STALE", "LAYOUT_V2_SELECTION_STALE"),
        "§2.2",
    ),
    MalformedCase(
        LEVEL_ACCESSES_ARTIFACT,
        UNHANDLED,
        SERVED,
        MALFORMED,
        ("STALE", "LAYOUT_V2_SELECTION_STALE"),
        "§2.2",
    ),
)

MALFORMED_CASES: dict[str, tuple[MalformedCase, ...]] = {
    "LEGACY": MALFORMED_SHARED + MALFORMED_LEGACY_ONLY,
    "LAYOUT_V2": MALFORMED_SHARED + MALFORMED_LAYOUT_V2_ONLY,
}


def _run_malformed_case(stack: Stack, case: MalformedCase) -> None:
    path = stack.derived / case.artifact
    for junk, old_expected, new_expected in (
        ("{", case.old_mj, case.new_mj),
        (json.dumps({"hello": "world"}), case.old_ms, case.new_ms),
    ):
        with mutated([path]):
            path.write_text(junk, encoding="utf-8")
            assert observe(stack, ROUTES[case.artifact]) == old_expected, (case.artifact, junk)
            read = read_new(stack, case.artifact)
            state, code = new_expected
            assert read.state == state, (case.artifact, junk, read.state, read.error)
            if code is None:
                assert read.error is None, (case.artifact, junk, read.error)
            else:
                assert read.error is not None
                assert type(read.error).code == code, (case.artifact, junk, read.error)
            if state == "MALFORMED":
                assert isinstance(read.error, ArtifactMalformedError)
        assert read_new(stack, case.artifact).state == "VALID", case.artifact


@pytest.mark.parametrize(
    "case", MALFORMED_CASES["LEGACY"], ids=[c.artifact for c in MALFORMED_CASES["LEGACY"]]
)
def test_malformed_difference_table_legacy(case: MalformedCase, legacy: Stack) -> None:
    _run_malformed_case(legacy, case)


@pytest.mark.parametrize(
    "case", MALFORMED_CASES["LAYOUT_V2"], ids=[c.artifact for c in MALFORMED_CASES["LAYOUT_V2"]]
)
def test_malformed_difference_table_layout_v2(case: MalformedCase, layout_v2: Stack) -> None:
    _run_malformed_case(layout_v2, case)


def test_the_world_guard_is_the_resolvers_and_not_the_routes(legacy: Stack) -> None:
    """Stage A §2.1 / §2.6: **13 readers carry no world guard** — with
    ``arrays.npz`` renamed away ``GET /design/levels`` still answers **200**
    and serves a derived artifact whose world is gone. A1: the resolver
    refuses first, because a derived artifact is never trusted without a
    world. The rename preserves size and ``st_mtime_ns``, so putting the file
    back restores the exact revision."""
    arrays = legacy.store.arrays_path(legacy.sid)
    hidden = arrays.parent / (arrays.name + ".hidden")
    assert observe(legacy, ROUTES[LEVELS_ARTIFACT]) == (200, None)
    arrays.rename(hidden)
    try:
        assert observe(legacy, ROUTES[LEVELS_ARTIFACT]) == (200, None)  # no world guard today
        with pytest.raises(WorldNotGeneratedError):
            legacy.reader.require(legacy.sid, LEVELS_ARTIFACT)
    finally:
        hidden.rename(arrays)
    assert legacy.reader.require(legacy.sid, LEVELS_ARTIFACT).state == "VALID"


def test_malformed_scene_difference(legacy: Stack) -> None:
    """Stage A §2.2: ONE corrupt artifact makes the whole scene a bare 500
    today (I-5), and a wrong-shaped one is projected as if it were a payload
    — except ``decline_smoothed.json``, where the scene is STRICTER than its
    own GET (``KeyError: 'segments'`` at ``effective_ramp.py:98``)."""
    path = legacy.derived / LEVELS_ARTIFACT
    with mutated([path]):
        path.write_text("{", encoding="utf-8")
        assert observe(legacy, "/scene") == (500, None)
        assert read_new(legacy, LEVELS_ARTIFACT).state == "MALFORMED"
    with mutated([path]):
        path.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
        status, _ = observe(legacy, "/scene")
        assert status == 200  # the junk is projected into scene["levels"]
        assert legacy.client.get(f"{API}/{legacy.sid}/scene").json()["levels"] == {"hello": "world"}
        assert read_new(legacy, LEVELS_ARTIFACT).state == "MALFORMED"
    smoothed = legacy.derived / LEGACY_RAMP_ARTIFACT
    with mutated([smoothed]):
        smoothed.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
        assert observe(legacy, "/scene") == (500, None)  # KeyError 'segments'
        assert read_new(legacy, LEGACY_RAMP_ARTIFACT).state == "MALFORMED"


def test_torn_glb_difference(legacy: Stack) -> None:
    """Stage A §7.2 / §7.4: a torn GLB is served 200 ``model/gltf-binary``
    with ``Cache-Control: immutable``; a SUCCESS report whose GLB is gone
    answers 200 on the report route and 409 on the GLB route."""
    glb = legacy.derived / TUNNEL_MESH_GLB
    report = json.loads((legacy.derived / TUNNEL_MESH_ARTIFACT).read_text(encoding="utf-8"))
    assert report["status"] == "SUCCESS"
    with mutated([glb]):
        original = glb.read_bytes()
        glb.write_bytes(original[: len(original) // 2])
        served = legacy.client.get(f"{API}/{legacy.sid}/design/tunnel/mesh.glb")
        assert served.status_code == 200
        assert served.headers["content-type"] == "model/gltf-binary"
        assert "immutable" in served.headers.get("cache-control", "")
        assert len(served.content) == len(original) // 2
        read = read_new(legacy, TUNNEL_MESH_ARTIFACT, glb_bytes=True)
        assert read.state == "MALFORMED"
        assert isinstance(read.error, ArtifactMalformedError)
        assert "artifactRevision" in str(read.error)
    with mutated([glb]):
        glb.unlink()
        assert observe(legacy, ROUTES[TUNNEL_MESH_ARTIFACT]) == (200, None)  # the report
        glb_status, glb_code = observe(legacy, "/design/tunnel/mesh.glb")
        assert (glb_status, glb_code) == (409, "TUNNEL_NOT_GENERATED")
        read = read_new(legacy, TUNNEL_MESH_ARTIFACT)
        assert read.state == "MALFORMED" and TUNNEL_MESH_GLB in str(read.error)


def test_half_published_selection_pair_difference(layout_v2: Stack) -> None:
    """Stage A §7.4 / §4.4: the two halves of the selection are written in one
    lock but read by nobody together — a pair that disagrees on the candidate
    is served 200 on both routes and only fails two builders later; and
    ``level_accesses.layoutRevision`` is written and never read."""
    accesses_path = layout_v2.derived / LEVEL_ACCESSES_ARTIFACT
    with mutated([accesses_path]):
        document = json.loads(accesses_path.read_text(encoding="utf-8"))
        document["candidateId"] = "SPIRAL-n1-CCW-e+0-g0.120"
        accesses_path.write_text(json.dumps(document), encoding="utf-8")
        assert observe(layout_v2, ROUTES[LEVEL_ACCESSES_ARTIFACT]) == (200, None)
        assert observe(layout_v2, ROUTES[LAYOUT_V2_SELECTED_ARTIFACT]) == (200, None)
        read = read_new(layout_v2, LEVEL_ACCESSES_ARTIFACT)
        assert read.state == "STALE"
        assert read.error is not None
        assert type(read.error).code == "LAYOUT_V2_SELECTION_STALE"
    with mutated([accesses_path]):
        document = json.loads(accesses_path.read_text(encoding="utf-8"))
        document["layoutRevision"] = "DELIBERATELY-WRONG"
        accesses_path.write_text(json.dumps(document), encoding="utf-8")
        assert observe(layout_v2, ROUTES[LEVEL_ACCESSES_ARTIFACT]) == (200, None)
        read = read_new(layout_v2, LEVEL_ACCESSES_ARTIFACT)
        assert read.state == "STALE"


def test_corrupt_ramp_source_difference(layout_v2: Stack) -> None:
    """Stage A I-12: a corrupt ``ramp_source.json`` is silently LEGACY on
    every read today (``effective_ramp.py:79-84``) — with a LAYOUT_V2 ramp
    active, that silently switches the mine's ramp. A7 read side: typed."""
    path = layout_v2.derived / RAMP_SOURCE_FILE
    with mutated([path]):
        path.write_text("{", encoding="utf-8")
        status, _ = observe(layout_v2, ROUTES[RAMP_SOURCE_FILE])
        assert status == 200
        body = layout_v2.client.get(f"{API}/{layout_v2.sid}/design/ramp-source").json()
        assert body["activeSource"] == "LEGACY"  # the silent fallback
        assert read_ramp_source(layout_v2.derived) == "LEGACY"
        snapshot = layout_v2.reader.snapshot(layout_v2.sid, [RAMP_SOURCE_FILE])
        assert layout_v2.reader.read(snapshot, RAMP_SOURCE_FILE).state == "MALFORMED"
        with pytest.raises(ArtifactMalformedError):
            layout_v2.reader.resolve_ramp_source(snapshot)


def test_development_mesh_records_a_ramp_source_nobody_rechecks(layout_v2: Stack) -> None:
    """``development_mesh.sources.rampSource`` (``design_service.py:1338``) is
    persisted evidence no reader compares today; the resolver does (A12)."""
    path = layout_v2.derived / RAMP_SOURCE_FILE
    report = json.loads((layout_v2.derived / DEVELOPMENT_MESH_ARTIFACT).read_text("utf-8"))
    assert report["sources"]["rampSource"] == "LAYOUT_V2"
    with mutated([path]):
        path.write_text(json.dumps({"activeSource": "LEGACY"}), encoding="utf-8")
        assert observe(layout_v2, ROUTES[DEVELOPMENT_MESH_ARTIFACT]) == (200, None)
        read = read_new(layout_v2, DEVELOPMENT_MESH_ARTIFACT)
        assert read.state == "STALE"
        assert read.error is not None and type(read.error).code == "ARTIFACT_STALE"


def test_the_oracle_stacks_hold_the_recorded_file_sets(legacy: Stack, layout_v2: Stack) -> None:
    """Stage A §10: LEGACY writes 16 files (no ``ramp_source.json``),
    LAYOUT_V2 writes 17."""
    legacy_files = sorted(p.name for p in legacy.derived.iterdir())
    layout_files = sorted(p.name for p in layout_v2.derived.iterdir())
    assert RAMP_SOURCE_FILE not in legacy_files
    assert len(legacy_files) == 16, legacy_files
    assert sorted(layout_files) == sorted(
        [
            CAPABILITY_GRAPH_ARTIFACT,
            COMMUNICATION_ARTIFACT,
            DEVELOPMENT_MESH_GLB,
            DEVELOPMENT_MESH_ARTIFACT,
            LAYOUT_V2_ARTIFACT,
            LAYOUT_V2_SELECTED_ARTIFACT,
            LEVEL_ACCESSES_ARTIFACT,
            LEVELS_ARTIFACT,
            NETWORK_ARTIFACT,
            RAMP_SOURCE_FILE,
            SENSORS_ARTIFACT,
            SHAFTS_ARTIFACT,
            STOPES_ARTIFACT,
            TIMELINE_ARTIFACT,
            TUNNEL_MESH_GLB,
            TUNNEL_MESH_ARTIFACT,
            "world.json",
        ]
    )
