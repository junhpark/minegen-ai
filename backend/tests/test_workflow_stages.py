"""Hardening H1 §4.4 — the "Reset from here" closure has ONE definition.

A stage's reset set is its own artifacts plus the registry invalidation
closure the write cascade uses (``invalidated_by``); the preview and the
delete are two outputs of ``reset_plan``. These tests pin the stage table,
the closure algebra under both ramp sources, the WORLD preview-only root and
the on-disk plan.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from minegen.core.artifact_registry import derived_artifacts, invalidated_by, spec
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
from minegen.services.workflow_stages import (
    STAGE_ARTIFACTS,
    WORKFLOW_STAGES,
    ResetStageNotDeletableError,
    ResetTargetNotGeneratedError,
    reset_closure,
    reset_plan,
)

SOURCES = ("LEGACY", "LAYOUT_V2")


def _names(closure: tuple[object, ...]) -> list[str]:
    return [f.name for a in closure for f in a.files]  # type: ignore[attr-defined]


def test_every_stage_owns_registered_derived_artifacts_in_workflow_order() -> None:
    assert tuple(STAGE_ARTIFACTS) == WORKFLOW_STAGES
    assert STAGE_ARTIFACTS["WORLD"] == ()
    for stage, own in STAGE_ARTIFACTS.items():
        for name in own:
            assert spec(name).fingerprint_file.location == "DERIVED", (stage, name)
    # every derived artifact except the ramp-source root and the selection
    # pair (owned by the LAYOUT stage through its closure) is owned by one stage
    owned = {n for own in STAGE_ARTIFACTS.values() for n in own}
    registered = {a.name for a in derived_artifacts()}
    assert registered - owned == {
        RAMP_SOURCE_FILE,
        LAYOUT_V2_SELECTED_ARTIFACT,
        LEVEL_ACCESSES_ARTIFACT,
    }


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("stage", [s for s in WORKFLOW_STAGES if s != "WORLD"])
def test_reset_closure_is_own_plus_the_registry_cascade(stage: str, source: str) -> None:
    own = STAGE_ARTIFACTS[stage]  # type: ignore[index]
    expected = {n for n in own} | {a.name for a in invalidated_by(own, source)}  # type: ignore[arg-type]
    closure = reset_closure(stage, source)  # type: ignore[arg-type]
    assert {a.name for a in closure} == expected
    # registry declaration order, no duplicates
    order = [a.name for a in derived_artifacts()]
    names = [a.name for a in closure]
    assert names == sorted(names, key=order.index) and len(set(names)) == len(names)
    # the ramp-source root is never part of a stage reset (rule 162)
    assert RAMP_SOURCE_FILE not in names


def test_world_is_every_derived_artifact_and_never_deletable(tmp_path: Path) -> None:
    for source in SOURCES:
        assert reset_closure("WORLD", source) == derived_artifacts()  # type: ignore[arg-type]
        assert RAMP_SOURCE_FILE in _names(reset_closure("WORLD", source))  # type: ignore[arg-type]
    err = ResetStageNotDeletableError("WORLD")
    assert err.code == "RESET_STAGE_NOT_DELETABLE" and err.http_status == 409
    plan = reset_plan("WORLD", "LEGACY", tmp_path)
    assert plan.present is False and plan.stage_artifacts == ()


def test_levels_reset_keeps_the_tunnel_and_takes_the_level_chain() -> None:
    names = _names(reset_closure("LEVELS", "LAYOUT_V2"))
    assert TUNNEL_MESH_ARTIFACT not in names and TUNNEL_MESH_GLB not in names  # rule 74
    for expected in (
        LEVELS_ARTIFACT,
        DEVELOPMENT_MESH_ARTIFACT,
        DEVELOPMENT_MESH_GLB,
        SHAFTS_ARTIFACT,
        STOPES_ARTIFACT,
        NETWORK_ARTIFACT,
        CAPABILITY_GRAPH_ARTIFACT,
        TIMELINE_ARTIFACT,
        COMMUNICATION_ARTIFACT,
        SENSORS_ARTIFACT,
    ):
        assert expected in names, expected
    assert LAYOUT_V2_ARTIFACT not in names and LAYOUT_V2_SELECTED_ARTIFACT not in names


def test_the_ramp_source_gates_the_two_chains() -> None:
    # resetting the legacy smoothed ramp under LAYOUT_V2 removes only itself
    assert _names(reset_closure("SMOOTH", "LAYOUT_V2")) == [LEGACY_RAMP_ARTIFACT]
    legacy = _names(reset_closure("SMOOTH", "LEGACY"))
    assert TUNNEL_MESH_ARTIFACT in legacy and LEVELS_ARTIFACT in legacy
    # resetting the catalogue always drops the selection pair; its downstream
    # chain only while LAYOUT_V2 is active
    under_legacy = _names(reset_closure("LAYOUT", "LEGACY"))
    assert under_legacy == [
        LAYOUT_V2_ARTIFACT,
        LAYOUT_V2_SELECTED_ARTIFACT,
        LEVEL_ACCESSES_ARTIFACT,
    ]
    under_v2 = _names(reset_closure("LAYOUT", "LAYOUT_V2"))
    assert LEVELS_ARTIFACT in under_v2 and NETWORK_ARTIFACT in under_v2
    assert TARGETS_ARTIFACT not in under_v2 and DECLINE_ARTIFACT not in under_v2


def test_excavation_owns_both_meshes_and_their_glbs() -> None:
    names = _names(reset_closure("EXCAVATION", "LAYOUT_V2"))
    assert names == [
        TUNNEL_MESH_ARTIFACT,
        TUNNEL_MESH_GLB,
        DEVELOPMENT_MESH_ARTIFACT,
        DEVELOPMENT_MESH_GLB,
    ]


def test_reset_plan_lists_exactly_the_closure_files_present_on_disk(tmp_path: Path) -> None:
    for name in (LEVELS_ARTIFACT, NETWORK_ARTIFACT, TUNNEL_MESH_ARTIFACT, LAYOUT_V2_ARTIFACT):
        (tmp_path / name).write_text("{}")
    plan = reset_plan("LEVELS", "LAYOUT_V2", tmp_path)
    assert plan.present is True
    assert plan.will_delete == (LEVELS_ARTIFACT, NETWORK_ARTIFACT)  # deletion order
    assert plan.closure[0] == LEVELS_ARTIFACT and SENSORS_ARTIFACT in plan.closure
    d = plan.to_dict()
    assert d["from"] == "LEVELS" and d["willDelete"] == [LEVELS_ARTIFACT, NETWORK_ARTIFACT]
    # nothing of the stage's own → not present, downstream residue still listed
    (tmp_path / LEVELS_ARTIFACT).unlink()
    plan = reset_plan("LEVELS", "LAYOUT_V2", tmp_path)
    assert plan.present is False and plan.will_delete == (NETWORK_ARTIFACT,)
    err = ResetTargetNotGeneratedError("scn", "LEVELS", plan.stage_artifacts)
    assert err.code == "RESET_TARGET_NOT_GENERATED" and err.http_status == 404
    assert "levels.json not generated" in str(err)


def test_unknown_stage_is_an_error_never_an_empty_closure() -> None:
    with pytest.raises(KeyError):
        reset_closure("STOPES", "LEGACY")
