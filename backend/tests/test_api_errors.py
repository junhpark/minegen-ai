"""AC-01F — the ONE wire mapping (``api/errors.py``) against the four router
``_guard`` functions at HEAD.

``api/errors.guard`` is NOT wired in commit 1: the routers keep their own
ladders, which is exactly what lets this module compare the table against the
LIVE functions. The oracle is twofold and neither half is the new code:

* ``LEGACY_GUARD_ANSWERS`` — the literal ``(status, code, message)`` each
  router answers TODAY, transcribed by hand from the router bodies with their
  ``file:line`` provenance;
* the live ``api/design.py::_guard`` / ``api/world.py::_guard`` /
  ``api/network.py::_guard`` / ``api/infrastructure.py::_guard`` functions,
  executed here on an instance of every relocated exception class.

The literal table and the live functions are asserted to agree, and then the
new table is asserted to agree with BOTH — except for the ONE approved
deviation, ``StaleInputsError``'s literal ``STALE_INPUTS`` on three routers
(AC-01F A9: the canonical ``JOB_INPUTS_CHANGED`` the same exception already
answers on the five ``?sync=true`` branches and on the async job path).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from minegen.api import errors as api_errors
from minegen.api.design import _guard as design_guard
from minegen.api.infrastructure import _guard as infrastructure_guard
from minegen.api.network import _guard as network_guard
from minegen.api.world import _guard as world_guard
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

#: (status, code) each router ``_guard`` answers TODAY for each relocated
#: class — transcribed by hand from the bodies at HEAD 12d7725. ``None`` means
#: the router has no row: it falls through (``raise exc`` on design / world /
#: network, ``500 INTERNAL_ERROR`` on infrastructure).
LEGACY_GUARD_ANSWERS: dict[str, dict[str, tuple[int, str] | None]] = {
    # class name: {router: (status, code)}
    "WorldNotGeneratedError": {
        "design": (409, "WORLD_NOT_GENERATED"),  # api/design.py:95-100
        "world": (409, "WORLD_NOT_GENERATED"),  # api/world.py:45-50
        "network": (409, "WORLD_NOT_GENERATED"),  # api/network.py:44-49
        "infrastructure": None,  # falls through to :74 INTERNAL_ERROR
    },
    "TargetsNotGeneratedError": {
        "design": (409, "TARGETS_NOT_GENERATED"),  # api/design.py:101-106
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "DeclineNotGeneratedError": {
        "design": (409, "DECLINE_NOT_GENERATED"),  # api/design.py:107-112
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "SmoothedNotGeneratedError": {
        "design": (409, "SMOOTHED_NOT_GENERATED"),  # api/design.py:113-118
        "world": None,
        "network": (409, "SMOOTHED_NOT_GENERATED"),  # api/network.py:50-55
        "infrastructure": (409, "SMOOTHED_NOT_GENERATED"),  # api/infrastructure.py:43-48
    },
    "TunnelNotGeneratedError": {
        "design": (409, "TUNNEL_NOT_GENERATED"),  # api/design.py:119-124
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "DevelopmentMeshNotGeneratedError": {
        "design": (409, "DEVELOPMENT_MESH_NOT_GENERATED"),  # api/design.py:125-131
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "LevelsNotGeneratedError": {
        "design": (409, "LEVELS_NOT_GENERATED"),  # api/design.py:132-137
        "world": None,
        "network": (409, "LEVELS_NOT_GENERATED"),  # api/network.py:56-61
        "infrastructure": (409, "LEVELS_NOT_GENERATED"),  # api/infrastructure.py:49-54
    },
    "ShaftsNotGeneratedError": {
        "design": (404, "SHAFTS_NOT_GENERATED"),  # api/design.py:138-143 (I-8 drift)
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "CapabilityGraphNotGeneratedError": {
        "design": (404, "CAPABILITY_GRAPH_NOT_GENERATED"),  # api/design.py:146-152 (I-8)
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "NetworkNotFoundError": {
        "design": (409, "NETWORK_NOT_GENERATED"),  # api/design.py:163-168
        "world": None,
        "network": (404, "NETWORK_NOT_GENERATED"),  # api/network.py:62-67 (I-8 drift)
        "infrastructure": (409, "NETWORK_NOT_GENERATED"),  # api/infrastructure.py:37-42
    },
    "StopesNotGeneratedError": {
        "design": (409, "STOPES_NOT_GENERATED"),  # api/design.py:157-162
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "TimelineNotGeneratedError": {
        "design": (409, "TIMELINE_NOT_GENERATED"),  # api/design.py:169-174
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "LayoutV2NotGeneratedError": {
        "design": (409, "LAYOUT_V2_NOT_GENERATED"),  # api/design.py:175-180
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "LayoutV2NotSelectedError": {
        "design": (409, "LAYOUT_V2_NOT_SELECTED"),  # api/design.py:181-187
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "LevelAccessesNotGeneratedError": {
        "design": (409, "LEVEL_ACCESSES_NOT_GENERATED"),  # api/design.py:188-194
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "CommunicationNotGeneratedError": {
        "design": None,
        "world": None,
        "network": None,
        "infrastructure": (409, "COMMUNICATION_NOT_GENERATED"),  # api/infrastructure.py:61-67
    },
    "SensorsNotGeneratedError": {
        "design": None,
        "world": None,
        "network": None,
        "infrastructure": (409, "SENSORS_NOT_GENERATED"),  # api/infrastructure.py:55-60
    },
    "ShaftsStaleError": {
        "design": (409, "SHAFTS_STALE"),  # api/design.py:144-145
        "world": None,
        "network": (409, "SHAFTS_STALE"),  # api/network.py:74-75
        "infrastructure": None,  # I-6: 500 INTERNAL_ERROR today
    },
    "CapabilityGraphStaleError": {
        "design": (409, "CAPABILITY_GRAPH_STALE"),  # api/design.py:153-154
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "LayoutSelectionStaleError": {
        "design": (409, "LAYOUT_V2_SELECTION_STALE"),  # api/design.py:195-196
        "world": None,
        "network": None,
        "infrastructure": None,
    },
    "StaleInputsError": {
        "design": (409, "STALE_INPUTS"),  # api/design.py:203-208 — A9 replaces it
        "world": None,
        "network": (409, "STALE_INPUTS"),  # api/network.py:68-73 — A9 replaces it
        "infrastructure": (409, "STALE_INPUTS"),  # api/infrastructure.py:68-73 — A9
    },
}

#: A9: the ONE approved deviation of the new table from today's literals. The
#: status is unchanged; the code becomes the exception's canonical one, which
#: the five ?sync=true branches (api/design.py:249) and the async job path
#: (job_service.py:111) already answer. ``grep -rn "STALE_INPUTS"
#: backend/tests`` → 0 hits at HEAD: no test pins the literal.
APPROVED_CODE_CHANGES: dict[str, tuple[str, str]] = {
    "StaleInputsError": ("STALE_INPUTS", "JOB_INPUTS_CHANGED"),
}

#: A9 replaces the CODE and, because ``ERRORS["JOB_INPUTS_CHANGED"]`` carries
#: ``message=None`` (i.e. ``str(exc)``), the MESSAGE too. The three literals it
#: replaces are recorded here verbatim, transcribed from the router bodies at
#: HEAD 12d7725, so commit 2's report can state the message change instead of
#: discovering it: nothing else in the table changes a message.
STALE_INPUTS_MESSAGES_REPLACED: dict[str, str] = {
    "design": "inputs changed during generation; retry",  # api/design.py:203-208
    "network": "network inputs changed during generation; retry",  # api/network.py:68-73
    "infrastructure": "inputs changed while generating; retry",  # api/infrastructure.py:68-73
}

GUARDS = {
    "design": design_guard,
    "world": world_guard,
    "network": network_guard,
    "infrastructure": infrastructure_guard,
}


def _instance(exc_type: type[Exception]) -> Exception:
    return exc_type(SID)


def _live_answer(router: str, exc: Exception) -> tuple[int, str, str] | None:
    """What the router's own ``_guard`` answers today, or ``None`` when it
    falls through (design / world / network re-raise; infrastructure's
    catch-all answers 500 INTERNAL_ERROR)."""
    try:
        result = GUARDS[router](SID, exc)
    except Exception as raised:  # the `raise exc` fall-through
        assert raised is exc
        return None
    assert isinstance(result, HTTPException)
    detail: Any = result.detail
    if router == "infrastructure" and detail["code"] == "INTERNAL_ERROR":
        return None
    return (result.status_code, str(detail["code"]), str(detail["message"]))


@pytest.mark.parametrize("exc_type", RELOCATED, ids=[t.__name__ for t in RELOCATED])
def test_the_literal_table_matches_the_live_router_guards(exc_type: type[Exception]) -> None:
    """Half 1: the hand-transcribed oracle equals the LIVE guards at HEAD."""
    expected = LEGACY_GUARD_ANSWERS[exc_type.__name__]
    for router in api_errors.ROUTERS:
        live = _live_answer(router, _instance(exc_type))
        if expected[router] is None:
            assert live is None, (exc_type.__name__, router, live)
        else:
            assert live is not None, (exc_type.__name__, router)
            assert (live[0], live[1]) == expected[router], (exc_type.__name__, router, live)


@pytest.mark.parametrize("exc_type", RELOCATED, ids=[t.__name__ for t in RELOCATED])
def test_the_new_table_answers_what_the_routers_answer_today(exc_type: type[Exception]) -> None:
    """Half 2: ``api/errors.guard`` == the live guards, per router, in status,
    code AND message — except the one A9-approved code replacement."""
    name = exc_type.__name__
    for router in api_errors.ROUTERS:
        exc = _instance(exc_type)
        new = api_errors.guard(SID, exc, router=router)
        assert new is not None, (name, router)  # the table maps every relocated class
        detail: Any = new.detail
        live = _live_answer(router, exc)
        if live is None:
            continue  # the router has no row today; the new table is additive there
        assert new.status_code == live[0], (name, router, new.status_code, live)
        if name in APPROVED_CODE_CHANGES:
            today, approved = APPROVED_CODE_CHANGES[name]
            assert live[1] == today, (name, router, live)
            assert detail["code"] == approved, (name, router, detail)
            continue
        assert detail["code"] == live[1], (name, router, detail, live)
        assert detail["message"] == live[2], (name, router, detail, live)


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
    isinstance ladder of ``api/design.py:88-100`` does."""
    from minegen.services.world_service import WorldArtifactIncompatibleError

    exc = WorldArtifactIncompatibleError("field artifact version 1")
    assert api_errors.code_of(exc) == "WORLD_ARTIFACT_INCOMPATIBLE"
    response = api_errors.guard(SID, exc, router="design")
    assert response is not None
    live = _live_answer("design", exc)
    assert live is not None
    detail: Any = response.detail
    assert (response.status_code, detail["code"], detail["message"]) == live


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
        live = _live_answer(router, exc)
        assert live is not None, router
        assert live == (409, "STALE_INPUTS", literal), (router, live)
        new = api_errors.guard(SID, exc, router=router)
        assert new is not None
        detail: Any = new.detail
        assert (new.status_code, detail["code"], detail["message"]) == (
            409,
            "JOB_INPUTS_CHANGED",
            str(exc),
        )
        assert detail["message"] != literal
    # the world router has no StaleInputsError row at HEAD
    assert _live_answer("world", exc) is None
