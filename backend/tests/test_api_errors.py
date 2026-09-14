"""AC-01F — the ONE wire mapping (``api/errors.py``) against the four router
``_guard`` ladders as they stood at HEAD ``12d7725``.

The four ladders are GONE from the routers in commit 2 (C3): every route now
hands its exception to ``api/errors.guard`` through the router's ``_fail``.
Keeping the dead ladders in the shipped modules so a test could call them was
the wrong place for a characterization oracle — the oracle belongs in the
test, frozen, like AC-01E's census. So the oracle here is a LITERAL table:

* ``HEAD_GUARD_ANSWERS`` — the ``(status, code, message)`` each router's
  ``_guard`` answered at HEAD ``12d7725``, transcribed by hand from the
  bodies, one row per (exception class, router), each naming the
  ``file:line`` it came from. ``None`` means the router had no row and fell
  through (``raise exc`` on design / world / network, ``500
  {"code": "INTERNAL_ERROR"}`` on infrastructure). ``message=None`` means the
  ladder answered ``str(exc)``.
* ``api/errors.guard`` is asserted to answer exactly that, per router, in
  status, code AND message — except the ONE approved deviation,
  ``StaleInputsError``'s literal ``STALE_INPUTS`` on three routers (AC-01F A9:
  the canonical ``JOB_INPUTS_CHANGED`` the same exception already answers on
  the five ``?sync=true`` branches and on the async job path).

Reproducing the transcription::

    git show 12d7725:backend/src/minegen/api/design.py         | sed -n '76,209p'
    git show 12d7725:backend/src/minegen/api/world.py          | sed -n '31,51p'
    git show 12d7725:backend/src/minegen/api/network.py        | sed -n '41,76p'
    git show 12d7725:backend/src/minegen/api/infrastructure.py | sed -n '34,74p'
"""

from __future__ import annotations

from typing import Any

import pytest

from minegen.api import errors as api_errors
from minegen.services.artifact_errors import (
    ArtifactMalformedError,
    ArtifactStaleError,
    CapabilityGraphNotGeneratedError,
    CapabilityGraphStaleError,
    CommunicationNotGeneratedError,
    DeclineNotGeneratedError,
    DevelopmentMeshNotGeneratedError,
    LayoutSelectionStaleError,
    LayoutV2NotGeneratedError,
    LayoutV2NotSelectedError,
    LevelAccessesNotGeneratedError,
    LevelsNotGeneratedError,
    NetworkNotFoundError,
    ReadSnapshotChangedError,
    SceneArtifactInvalidError,
    SensorsNotGeneratedError,
    ShaftsNotGeneratedError,
    ShaftsStaleError,
    SmoothedNotGeneratedError,
    StaleInputsError,
    StopesNotGeneratedError,
    TargetsNotGeneratedError,
    TimelineNotGeneratedError,
    TunnelNotGeneratedError,
    WorldNotGeneratedError,
)

SID = "guarded"

#: every exception class AC-01F relocates into ``services/artifact_errors.py``
RELOCATED: tuple[type[Exception], ...] = (
    WorldNotGeneratedError,
    TargetsNotGeneratedError,
    DeclineNotGeneratedError,
    SmoothedNotGeneratedError,
    TunnelNotGeneratedError,
    DevelopmentMeshNotGeneratedError,
    LevelsNotGeneratedError,
    ShaftsNotGeneratedError,
    CapabilityGraphNotGeneratedError,
    NetworkNotFoundError,
    StopesNotGeneratedError,
    TimelineNotGeneratedError,
    LayoutV2NotGeneratedError,
    LayoutV2NotSelectedError,
    LevelAccessesNotGeneratedError,
    CommunicationNotGeneratedError,
    SensorsNotGeneratedError,
    ShaftsStaleError,
    CapabilityGraphStaleError,
    LayoutSelectionStaleError,
    StaleInputsError,
)

#: ``(status, code, message, file:line at 12d7725)``. ``message=None`` = the
#: ladder answered ``str(exc)``.
HeadAnswer = tuple[int, str, str | None, str]

#: the HEAD ``12d7725`` answer of every (class, router) pair. ``None`` = the
#: router had no row for that class and fell through.
HEAD_GUARD_ANSWERS: dict[str, dict[str, HeadAnswer | None]] = {
    "WorldNotGeneratedError": {
        "design": (
            409,
            "WORLD_NOT_GENERATED",
            "scenario 'guarded' has no generated world; POST …/world/generate first",
            "api/design.py:95-100",
        ),
        "world": (
            409,
            "WORLD_NOT_GENERATED",
            "scenario 'guarded' has no generated world; POST …/world/generate first",
            "api/world.py:45-50",
        ),
        "network": (
            409,
            "WORLD_NOT_GENERATED",
            "scenario 'guarded' has no generated world; POST …/world/generate first",
            "api/network.py:44-49",
        ),
        "infrastructure": None,  # fell through to :74 500 INTERNAL_ERROR
    },
    "TargetsNotGeneratedError": {
        "design": (
            409,
            "TARGETS_NOT_GENERATED",
            "scenario 'guarded' has no access targets; POST …/design/targets first",
            "api/design.py:101-106",
        ),
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "DeclineNotGeneratedError": {
        "design": (
            409,
            "DECLINE_NOT_GENERATED",
            "scenario 'guarded' has no decline; POST …/design/decline first",
            "api/design.py:107-112",
        ),
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "SmoothedNotGeneratedError": {
        "design": (
            409,
            "SMOOTHED_NOT_GENERATED",
            "scenario 'guarded' has no smoothed decline; POST …/design/decline/smooth first",
            "api/design.py:113-118",
        ),
        "world": None,
        "network": (
            409,
            "SMOOTHED_NOT_GENERATED",
            "scenario 'guarded' has no smoothed decline; POST …/design/decline/smooth first",
            "api/network.py:50-55",
        ),
        "infrastructure": (
            409,
            "SMOOTHED_NOT_GENERATED",
            "scenario 'guarded' has no smoothed decline; POST …/design/smooth first",
            "api/infrastructure.py:43-48",
        ),
    },
    "TunnelNotGeneratedError": {
        "design": (
            409,
            "TUNNEL_NOT_GENERATED",
            "scenario 'guarded' has no tunnel mesh; POST …/design/tunnel first",
            "api/design.py:119-124",
        ),
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "DevelopmentMeshNotGeneratedError": {
        "design": (
            409,
            "DEVELOPMENT_MESH_NOT_GENERATED",
            "scenario 'guarded' has no development mesh; POST …/design/development-mesh first",
            "api/design.py:125-131",
        ),
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "LevelsNotGeneratedError": {
        "design": (
            409,
            "LEVELS_NOT_GENERATED",
            "scenario 'guarded' has no level developments; POST …/design/levels first",
            "api/design.py:132-137",
        ),
        "world": None,
        "network": (
            409,
            "LEVELS_NOT_GENERATED",
            "scenario 'guarded' has no level developments; POST …/design/levels first",
            "api/network.py:56-61",
        ),
        "infrastructure": (
            409,
            "LEVELS_NOT_GENERATED",
            "scenario 'guarded' has no levels; POST …/design/levels first",
            "api/infrastructure.py:49-54",
        ),
    },
    "ShaftsNotGeneratedError": {
        "design": (  # 404: the recorded I-8 drift, unchanged by AC-01F
            404,
            "SHAFTS_NOT_GENERATED",
            "scenario 'guarded' has no shaft artifact; POST …/design/shafts first",
            "api/design.py:138-143",
        ),
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "CapabilityGraphNotGeneratedError": {
        "design": (  # 404: the recorded I-8 drift
            404,
            "CAPABILITY_GRAPH_NOT_GENERATED",
            "scenario 'guarded' has no capability graph; POST …/design/capability-graph first",
            "api/design.py:146-152",
        ),
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "NetworkNotFoundError": {
        "design": (
            409,
            "NETWORK_NOT_GENERATED",
            "scenario 'guarded' has no MineNetwork; POST …/network/generate first",
            "api/design.py:163-168",
        ),
        "world": None,
        "network": (  # 404 + its own message: the recorded I-8 drift
            404,
            "NETWORK_NOT_GENERATED",
            "scenario 'guarded' has no network; POST …/network/generate first",
            "api/network.py:62-67",
        ),
        "infrastructure": (
            409,
            "NETWORK_NOT_GENERATED",
            "scenario 'guarded' has no MineNetwork; POST …/network/generate first",
            "api/infrastructure.py:37-42",
        ),
    },
    "StopesNotGeneratedError": {
        "design": (
            409,
            "STOPES_NOT_GENERATED",
            "scenario 'guarded' has no planned stopes; POST …/design/stopes first",
            "api/design.py:157-162",
        ),
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "TimelineNotGeneratedError": {
        "design": (
            409,
            "TIMELINE_NOT_GENERATED",
            "scenario 'guarded' has no timeline; POST …/design/timeline first",
            "api/design.py:169-174",
        ),
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "LayoutV2NotGeneratedError": {
        "design": (
            409,
            "LAYOUT_V2_NOT_GENERATED",
            "scenario 'guarded' has no layout-v2 catalogue; POST …/design/layout-v2 first",
            "api/design.py:175-180",
        ),
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "LayoutV2NotSelectedError": {
        "design": (
            409,
            "LAYOUT_V2_NOT_SELECTED",
            "scenario 'guarded' has no selected layout-v2 candidate; "
            "POST …/design/layout-v2/select first",
            "api/design.py:181-187",
        ),
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "LevelAccessesNotGeneratedError": {
        "design": (
            409,
            "LEVEL_ACCESSES_NOT_GENERATED",
            "scenario 'guarded' has no level-access artifact; select a layout-v2 "
            "candidate first (POST …/design/layout-v2/select)",
            "api/design.py:188-194",
        ),
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "CommunicationNotGeneratedError": {
        "design": None,
        "world": None,
        "network": None,
        "infrastructure": (
            409,
            "COMMUNICATION_NOT_GENERATED",
            "scenario 'guarded' has no communication plan; "
            "POST …/infrastructure/communication first",
            "api/infrastructure.py:61-67",
        ),
    },
    "SensorsNotGeneratedError": {
        "design": None,
        "world": None,
        "network": None,
        "infrastructure": (
            409,
            "SENSORS_NOT_GENERATED",
            "scenario 'guarded' has no sensor plan; POST …/infrastructure/sensors first",
            "api/infrastructure.py:55-60",
        ),
    },
    "ShaftsStaleError": {
        "design": (409, "SHAFTS_STALE", None, "api/design.py:144-145"),
        "world": None,
        "network": (409, "SHAFTS_STALE", None, "api/network.py:74-75"),
        "infrastructure": None,  # I-6: 500 INTERNAL_ERROR at HEAD
    },
    "CapabilityGraphStaleError": {
        "design": (409, "CAPABILITY_GRAPH_STALE", None, "api/design.py:153-154"),
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "LayoutSelectionStaleError": {
        "design": (409, "LAYOUT_V2_SELECTION_STALE", None, "api/design.py:195-196"),
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "StaleInputsError": {
        "design": (
            409,
            "STALE_INPUTS",  # A9 replaces the code AND the literal message
            "inputs changed during generation; retry",
            "api/design.py:203-208",
        ),
        "world": None,
        "network": (
            409,
            "STALE_INPUTS",
            "network inputs changed during generation; retry",
            "api/network.py:68-73",
        ),
        "infrastructure": (
            409,
            "STALE_INPUTS",
            "inputs changed while generating; retry",
            "api/infrastructure.py:68-73",
        ),
    },
}

#: the subclass row the ladder ORDER decided at HEAD: transcribed from
#: ``api/design.py:88-94`` for ``WorldArtifactIncompatibleError("field
#: artifact version 1")``, which is a SUBCLASS of ``WorldNotGeneratedError``.
HEAD_WORLD_ARTIFACT_INCOMPATIBLE: HeadAnswer = (
    409,
    "WORLD_ARTIFACT_INCOMPATIBLE",
    "scenario 'guarded' has a world artifact from an older schema "
    "(field artifact version 1); POST …/world/generate to regenerate it",
    "api/design.py:88-94",
)

#: A9: the ONE approved deviation of the new table from HEAD's literals. The
#: status is unchanged; the code becomes the exception's canonical one, which
#: the five ?sync=true branches (api/design.py:249) and the async job path
#: (job_service.py:111) already answered at HEAD. ``grep -rn "STALE_INPUTS"
#: backend/tests`` → 0 hits at HEAD: no test pinned the literal.
APPROVED_CODE_CHANGES: dict[str, tuple[str, str]] = {
    "StaleInputsError": ("STALE_INPUTS", "JOB_INPUTS_CHANGED"),
}

#: A9 replaces the CODE and, because ``ERRORS["JOB_INPUTS_CHANGED"]`` carries
#: ``message=None`` (i.e. ``str(exc)``), the MESSAGE too. The three literals it
#: replaces are the ``StaleInputsError`` rows above; they are repeated here so
#: the commit report can quote the message change instead of discovering it.
#: Nothing else in the table changes a message.
STALE_INPUTS_MESSAGES_REPLACED: dict[str, str] = {
    "design": "inputs changed during generation; retry",  # api/design.py:203-208
    "network": "network inputs changed during generation; retry",  # api/network.py:68-73
    "infrastructure": "inputs changed while generating; retry",  # api/infrastructure.py:68-73
}


def _instance(exc_type: type[Exception]) -> Exception:
    return exc_type(SID)


def _head_answer(router: str, exc: Exception) -> tuple[int, str, str] | None:
    """What the router's own ``_guard`` answered at HEAD ``12d7725``, read
    from the literal table above (``None`` = it fell through)."""
    row = HEAD_GUARD_ANSWERS[type(exc).__name__][router]
    if row is None:
        return None
    status, code, message, _source = row
    return (status, code, str(exc) if message is None else message)


def test_the_head_table_is_complete_and_carries_its_provenance() -> None:
    """Half 1: the frozen census covers every relocated class on every router
    and every non-fall-through row names the ``file:line`` at HEAD ``12d7725``
    it was transcribed from. (The live ladders it was transcribed from are
    deleted in this commit — C3; this table is what replaces them.)"""
    assert set(HEAD_GUARD_ANSWERS) == {t.__name__ for t in RELOCATED}
    for name, rows in HEAD_GUARD_ANSWERS.items():
        assert set(rows) == set(api_errors.ROUTERS), name
        for router, row in rows.items():
            if row is None:
                continue
            status, code, _message, source = row
            assert status in (404, 409, 422), (name, router, status)
            assert code and source.startswith(f"api/{router}.py:"), (name, router, row)
    status, code, _m, source = HEAD_WORLD_ARTIFACT_INCOMPATIBLE
    assert (status, code, source) == (409, "WORLD_ARTIFACT_INCOMPATIBLE", "api/design.py:88-94")


@pytest.mark.parametrize("exc_type", RELOCATED, ids=[t.__name__ for t in RELOCATED])
def test_the_new_table_answers_what_the_routers_answered_at_head(
    exc_type: type[Exception],
) -> None:
    """Half 2: ``api/errors.guard`` == the HEAD ladders, per router, in status,
    code AND message — except the one A9-approved code replacement."""
    name = exc_type.__name__
    for router in api_errors.ROUTERS:
        exc = _instance(exc_type)
        new = api_errors.guard(SID, exc, router=router)
        assert new is not None, (name, router)  # the table maps every relocated class
        detail: Any = new.detail
        head = _head_answer(router, exc)
        if head is None:
            continue  # the router had no row at HEAD; the new table is additive there
        assert new.status_code == head[0], (name, router, new.status_code, head)
        if name in APPROVED_CODE_CHANGES:
            today, approved = APPROVED_CODE_CHANGES[name]
            assert head[1] == today, (name, router, head)
            assert detail["code"] == approved, (name, router, detail)
            continue
        assert detail["code"] == head[1], (name, router, detail, head)
        assert detail["message"] == head[2], (name, router, detail, head)


def test_every_relocated_class_carries_its_wire_code_and_status() -> None:
    for exc_type in RELOCATED:
        code = getattr(exc_type, "code", None)
        status = getattr(exc_type, "http_status", None)
        assert isinstance(code, str) and code, exc_type
        assert status in (404, 409, 422), (exc_type, status)
        assert api_errors.code_of(_instance(exc_type)) == code
        # the class attribute agrees with the table's base row
        assert api_errors.ERRORS[code].status == status, exc_type


def test_the_new_codes_are_409_and_carry_their_own_message() -> None:
    cases: list[Exception] = [
        ArtifactMalformedError("levels.json", "invalid JSON (JSONDecodeError)"),
        ArtifactStaleError("development_mesh.json", "swept under another ramp source"),
        ReadSnapshotChangedError(SID),
    ]
    for exc in cases:
        response = api_errors.guard(SID, exc, router="design")
        assert response is not None
        detail: Any = response.detail
        assert response.status_code == 409
        assert detail["code"] == type(exc).code
        assert detail["message"] == str(exc)


def test_the_scene_aggregate_lists_every_failure_without_paths() -> None:
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
    response = api_errors.guard(SID, SceneArtifactInvalidError(SID, failures), router="design")
    assert response is not None
    detail: Any = response.detail
    assert response.status_code == 409
    assert detail["code"] == "SCENE_ARTIFACT_INVALID"
    assert detail["artifacts"] == failures
    assert "shafts.json" in detail["message"] and "levels.json" in detail["message"]
    assert "/" not in detail["message"].replace("…/", "")


def test_unmapped_exceptions_fall_through() -> None:
    assert api_errors.guard(SID, RuntimeError("something else"), router="design") is None
    assert api_errors.code_of(RuntimeError("something else")) is None


def test_the_ladder_order_keeps_the_world_artifact_subclass_specific() -> None:
    """``WorldArtifactIncompatibleError`` is a SUBCLASS of
    ``WorldNotGeneratedError``; the ladder order decides, exactly as the
    isinstance ladder of ``api/design.py:88-100`` did at HEAD."""
    from minegen.services.world_service import WorldArtifactIncompatibleError

    exc = WorldArtifactIncompatibleError("field artifact version 1")
    assert api_errors.code_of(exc) == "WORLD_ARTIFACT_INCOMPATIBLE"
    response = api_errors.guard(SID, exc, router="design")
    assert response is not None
    status, code, message, _source = HEAD_WORLD_ARTIFACT_INCOMPATIBLE
    detail: Any = response.detail
    assert (response.status_code, detail["code"], detail["message"]) == (status, code, message)


def test_every_table_row_is_reachable_and_documented() -> None:
    codes_in_ladder = {code for _, code in api_errors.CODE_LADDER}
    assert codes_in_ladder == set(api_errors.ERRORS)
    for code, spec in api_errors.ERRORS.items():
        assert spec.source, code  # every row names where it was transcribed from
        assert spec.status in (404, 409, 422), (code, spec.status)
    for router, rows in api_errors.ROUTER_OVERRIDES.items():
        assert router in api_errors.ROUTERS
        for code, spec in rows.items():
            assert code in api_errors.ERRORS and spec.source, (router, code)


def test_guard_requires_an_explicit_router() -> None:
    """A6: ``router`` is keyword-only AND has NO default. A wiring that forgets
    it must fail loudly instead of silently answering the design router's
    ladder — which would turn ``api/network.py``'s recorded 404
    ``NETWORK_NOT_GENERATED`` (I-8) into a 409 that AC-01I, not AC-01F, owns."""
    import inspect

    parameter = inspect.signature(api_errors.guard).parameters["router"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        api_errors.guard(SID, NetworkNotFoundError(SID))  # type: ignore[call-arg]
    # and the drift the missing default protects is real
    assert api_errors.guard(SID, NetworkNotFoundError(SID), router="network").status_code == 404
    assert api_errors.guard(SID, NetworkNotFoundError(SID), router="design").status_code == 409


def test_the_stale_inputs_messages_the_a9_row_replaces_are_recorded() -> None:
    """The JOB_INPUTS_CHANGED row keeps ``message=None`` (``str(exc)``), so the
    three router literals it replaces are pinned here — the literal oracle a
    commit-2 report quotes for the message change."""
    assert api_errors.ERRORS["JOB_INPUTS_CHANGED"].message is None
    exc = StaleInputsError(SID)
    for router, literal in STALE_INPUTS_MESSAGES_REPLACED.items():
        head = _head_answer(router, exc)
        assert head is not None, router
        assert head == (409, "STALE_INPUTS", literal), (router, head)
        new = api_errors.guard(SID, exc, router=router)
        assert new is not None
        detail: Any = new.detail
        assert (new.status_code, detail["code"], detail["message"]) == (
            409,
            "JOB_INPUTS_CHANGED",
            str(exc),
        )
        assert detail["message"] != literal
    # the world router had no StaleInputsError row at HEAD
    assert _head_answer("world", exc) is None


def test_no_router_carries_its_own_error_ladder_any_more() -> None:
    """C3: the four ``_guard`` ladders are removed from the shipped routers —
    ONE mapping, and the characterization oracle lives here as a literal
    table, not as dead code in the request-handling modules."""
    from minegen.api import design, infrastructure, network, world

    for module in (design, world, network, infrastructure):
        assert not hasattr(module, "_guard"), module.__name__
        assert hasattr(module, "_fail"), module.__name__
