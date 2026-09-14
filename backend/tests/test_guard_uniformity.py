"""AC-01F T9/T16 — ONE wire answer per read-state error, on all four routers.

Stage A I-6 and I-7: the SAME typed refusal was a 409 on three routers and a
500 on the fourth (``api/infrastructure.py``'s ``INTERNAL_ERROR`` catch-all,
which also leaked ``str(exc)`` into the body), and several routes never
reached a guard at all because their ``except`` clause was a narrow tuple.
After commit 2 every route hands every exception to ``api/errors.guard``.

Oracle (§29 — never ``resolver == resolver``): ``EXPECTED`` below is a LITERAL
table written from the approved contract (each class's own wire code, its
status, and the ONE recorded per-router drift A6 keeps), and every answer is
observed through the real ``TestClient``, not computed from ``api/errors``.
The injected failure is a monkeypatched service method raising a known
instance, so no artifact, world or search is needed: FAST tier.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from minegen.services.artifact_errors import (
    ArtifactMalformedError,
    ArtifactStaleError,
    CapabilityGraphNotGeneratedError,
    CapabilityGraphStaleError,
    LayoutSelectionStaleError,
    LayoutV2NotSelectedError,
    LevelsNotGeneratedError,
    NetworkNotFoundError,
    ReadSnapshotChangedError,
    SceneArtifactInvalidError,
    ShaftsStaleError,
    StaleInputsError,
)
from minegen.services.design_service import DesignService
from minegen.services.infrastructure_service import InfrastructureService
from minegen.services.job_service import JobService
from minegen.services.scenario_service import ScenarioNotFoundError, ScenarioStore
from minegen.services.world_service import WorldService
from tests.conftest import small_scenario

API = "/api/v1/scenarios"

#: one route per router, and the service method it calls. Monkeypatching that
#: method is the injected failure; the scenario is never generated, so nothing
#: but the guard decides the answer.
ROUTES: dict[str, tuple[type, str, str, str]] = {
    "design": (DesignService, "levels", "GET", "/design/levels"),
    "world": (WorldService, "scene", "GET", "/scene"),
    "network": (DesignService, "network", "GET", "/network"),
    "infrastructure": (
        InfrastructureService,
        "communication",
        "GET",
        "/infrastructure/communication",
    ),
}

#: the LITERAL expected (status, code) for every read-state error, per router.
#: Written from the AC-01F contract, not read from ``api/errors``:
#:   * every AC-01F read-state error is 409 with its own code (A1/A9/A14);
#:   * every relocated ABSENT / STALE class keeps the code and status its
#:     class attribute records — including the two recorded 404s (I-8);
#:   * the ONE per-router drift A6 preserves is ``NETWORK_NOT_GENERATED``,
#:     404 on ``api/network.py`` and 409 on the other three.
EXPECTED: dict[str, tuple[int, str]] = {
    "ScenarioNotFoundError": (404, "SCENARIO_NOT_FOUND"),
    "LevelsNotGeneratedError": (409, "LEVELS_NOT_GENERATED"),
    "LayoutV2NotSelectedError": (409, "LAYOUT_V2_NOT_SELECTED"),
    "CapabilityGraphNotGeneratedError": (404, "CAPABILITY_GRAPH_NOT_GENERATED"),
    "NetworkNotFoundError": (409, "NETWORK_NOT_GENERATED"),
    "ShaftsStaleError": (409, "SHAFTS_STALE"),
    "CapabilityGraphStaleError": (409, "CAPABILITY_GRAPH_STALE"),
    "LayoutSelectionStaleError": (409, "LAYOUT_V2_SELECTION_STALE"),
    "StaleInputsError": (409, "JOB_INPUTS_CHANGED"),
    "ArtifactMalformedError": (409, "ARTIFACT_MALFORMED"),
    "ArtifactStaleError": (409, "ARTIFACT_STALE"),
    "SceneArtifactInvalidError": (409, "SCENE_ARTIFACT_INVALID"),
    "ReadSnapshotChangedError": (409, "READ_SNAPSHOT_CHANGED"),
}

#: A6, verbatim: the recorded 404/409 drift AC-01I owns, kept as a per-router
#: override so AC-01F normalizes nothing.
DRIFT: dict[tuple[str, str], tuple[int, str]] = {
    ("network", "NetworkNotFoundError"): (404, "NETWORK_NOT_GENERATED"),
}


def _instances() -> list[Exception]:
    sid = "guarded"
    return [
        ScenarioNotFoundError(sid),
        LevelsNotGeneratedError(sid),
        LayoutV2NotSelectedError(sid),
        CapabilityGraphNotGeneratedError(sid),
        NetworkNotFoundError(sid),
        ShaftsStaleError(sid),
        CapabilityGraphStaleError(sid),
        LayoutSelectionStaleError(sid),
        StaleInputsError(sid),
        ArtifactMalformedError("levels.json", "invalid JSON (JSONDecodeError)"),
        ArtifactStaleError("development_mesh.json", "swept under another ramp source"),
        SceneArtifactInvalidError(
            sid,
            [
                {
                    "artifact": "shafts.json",
                    "state": "STALE",
                    "code": "SHAFTS_STALE",
                    "message": "belongs to a previous level-development revision",
                }
            ],
        ),
        ReadSnapshotChangedError(sid),
    ]


@pytest.fixture
def sid(client: TestClient) -> str:
    scenario = small_scenario()
    payload = scenario.model_dump(by_alias=True, exclude={"id", "schema_version"})
    created = client.post(API, json=payload)
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _observe(client: TestClient, sid: str, router: str) -> tuple[int, str | None]:
    _, _, method, path = ROUTES[router]
    response = client.request(method, f"{API}/{sid}{path}")
    code: str | None = None
    body: Any = None
    try:
        body = response.json()
    except ValueError:
        return response.status_code, None
    if isinstance(body, dict) and isinstance(body.get("detail"), dict):
        code = str(body["detail"].get("code"))
    return response.status_code, code


@pytest.mark.parametrize("exc", _instances(), ids=[type(e).__name__ for e in _instances()])
def test_every_router_answers_the_same_status_and_code(
    client: TestClient, sid: str, monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    name = type(exc).__name__
    for router, (service, method, _, _) in ROUTES.items():

        def raise_it(self: Any, *args: Any, **kwargs: Any) -> Any:
            raise exc

        monkeypatch.setattr(service, method, raise_it)
        observed = _observe(client, sid, router)
        expected = DRIFT.get((router, name), EXPECTED[name])
        assert observed == expected, (router, name, observed, expected)
        monkeypatch.undo()


def test_the_scene_aggregate_carries_its_artifact_list_on_the_wire(
    client: TestClient, sid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    failures = [
        {
            "artifact": "shafts.json",
            "state": "STALE",
            "code": "SHAFTS_STALE",
            "message": "belongs to a previous level-development revision",
        },
        {
            "artifact": "levels.json",
            "state": "MALFORMED",
            "code": "ARTIFACT_MALFORMED",
            "message": "invalid JSON (JSONDecodeError)",
        },
    ]

    def raise_it(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise SceneArtifactInvalidError(sid, failures)

    monkeypatch.setattr(WorldService, "scene", raise_it)
    response = client.get(f"{API}/{sid}/scene")
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "SCENE_ARTIFACT_INVALID"
    assert detail["artifacts"] == failures
    assert "Traceback" not in detail["message"] and "object at 0x" not in detail["message"]


def test_an_unmapped_exception_is_a_bare_500_without_a_code_on_every_router(
    client: TestClient, sid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The infrastructure router's ``500 INTERNAL_ERROR`` catch-all is gone
    (Stage A I-6): an exception no router maps falls through to ``raise exc``
    on all four, so the engineering message is no longer leaked in a
    ``detail.code`` body."""
    from fastapi.testclient import TestClient as RawClient

    raw = RawClient(client.app, raise_server_exceptions=False)
    for router, (service, method, http_method, path) in ROUTES.items():

        def raise_it(self: Any, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("an engineering message that must not reach the client")

        monkeypatch.setattr(service, method, raise_it)
        response = raw.request(http_method, f"{API}/{sid}{path}")
        assert response.status_code == 500, router
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict) and isinstance(body.get("detail"), dict):
            assert "code" not in body["detail"], (router, body)
        monkeypatch.undo()


#: A9, the three router literals the canonical ``JOB_INPUTS_CHANGED``
#: replaces — transcribed from the bodies at HEAD 12d7725 (the same table
#: ``tests/test_api_errors.py::STALE_INPUTS_MESSAGES_REPLACED`` records).
STALE_INPUTS_MESSAGES_REPLACED: dict[str, str] = {
    "design": "inputs changed during generation; retry",
    "network": "network inputs changed during generation; retry",
    "infrastructure": "inputs changed while generating; retry",
}

#: the generation route of each of the three routers whose guard carried the
#: literal ``STALE_INPUTS`` code
GENERATION_ROUTES: dict[str, tuple[type, str, str]] = {
    "design": (DesignService, "generate_levels", "/design/levels"),
    "network": (DesignService, "generate_network", "/network/generate"),
    "infrastructure": (
        InfrastructureService,
        "generate_communication",
        "/infrastructure/communication",
    ),
}


@pytest.mark.parametrize("router", sorted(GENERATION_ROUTES))
def test_a_generation_whose_inputs_moved_answers_job_inputs_changed(
    client: TestClient, sid: str, monkeypatch: pytest.MonkeyPatch, router: str
) -> None:
    """T16 / A9: ``StaleInputsError`` answers its own canonical code on all
    three routers, replacing the untested ``STALE_INPUTS`` literal (0 hits in
    ``backend/tests`` at HEAD). The message becomes ``str(exc)`` — the
    replaced literals are recorded above."""
    service, method, path = GENERATION_ROUTES[router]
    exc = StaleInputsError(sid)

    def raise_it(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise exc

    monkeypatch.setattr(service, method, raise_it)
    response = client.post(f"{API}/{sid}{path}")
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "JOB_INPUTS_CHANGED"
    assert detail["message"] == str(exc)
    assert detail["message"] != STALE_INPUTS_MESSAGES_REPLACED[router]


def test_the_async_job_reports_the_same_code_as_the_sync_route(
    client: TestClient, sid: str, monkeypatch: pytest.MonkeyPatch, job_service: JobService
) -> None:
    """Surface 4 == surface 1: ``JobService`` transports
    ``getattr(exc, "code", "JOB_FAILED")`` unchanged, so a read-state failure
    inside a job now reports ``ARTIFACT_MALFORMED`` (it used to report
    ``JOB_FAILED``, Stage A §1.8) — the very code the synchronous route
    answers for the same injected failure."""
    exc = ArtifactMalformedError("levels.json", "invalid JSON (JSONDecodeError)")

    def raise_it(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise exc

    monkeypatch.setattr(DesignService, "levels", raise_it)
    sync = _observe(client, sid, "design")
    assert sync == (409, "ARTIFACT_MALFORMED")

    def work(_on_progress: Any) -> dict[str, Any]:
        raise exc

    job = job_service.submit(sid, "MESH", work)
    deadline = time.time() + 30
    while time.time() < deadline:
        record = job_service.get(job.id)
        if record.status.value in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(0.02)
    record = job_service.get(job.id)
    assert record.status.value == "FAILED"
    assert record.error is not None
    assert record.error["code"] == sync[1] == "ARTIFACT_MALFORMED"


def test_the_store_is_untouched_by_every_refusal(
    store: ScenarioStore, client: TestClient, sid: str
) -> None:
    """A refusal is a read answer, never a repair: no derived file appears and
    none disappears while the guards answer."""
    derived = store.derived_dir(sid)
    before = sorted(p.name for p in derived.iterdir()) if derived.is_dir() else []
    for router in ROUTES:
        _observe(client, sid, router)
    after = sorted(p.name for p in derived.iterdir()) if derived.is_dir() else []
    assert before == after
