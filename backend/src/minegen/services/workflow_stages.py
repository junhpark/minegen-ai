"""Workflow stages and the "Reset from here" closure (hardening H1 §4.4).

ONE backend definition of which derived artifacts a user-facing workflow
STAGE owns, and ONE function that turns a stage into the set of files a
reset deletes: the stage's own artifacts plus their registry invalidation
closure (``core.artifact_registry.invalidated_by`` — the very cascade every
writer runs after persisting). The reset preview
(``GET …/design/reset-plan?from=<stage>``) and the reset itself
(``DELETE …/design/stages/{stage}``) are two outputs of the same function:
the preview lists what the delete will remove, the delete removes exactly
what the preview listed. The frontend sends a stage id and renders the
answer; it never carries a dependency graph of its own.

``WORLD`` is a PREVIEW-ONLY root: its closure is every registered derived
artifact (what a scenario PUT / world regeneration clears through
``ScenarioStore.clear_derived``, rules 40 / 46). It is never deleted here —
the scenario PUT and ``POST …/world/generate`` own that path.

``ramp_source.json`` is a root of the ramp downstream (rule 162 — a source
switch keeps the selection): it is never in a stage closure except under
``WORLD``. STALE / MALFORMED artifacts are deletable — a reset is the one
recovery path that never reads the document it removes.

Leaf module: standard library + ``core.artifacts`` + ``core.artifact_registry``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, get_args

from minegen.core.artifact_registry import (
    ArtifactSpec,
    derived_artifacts,
    invalidated_by,
    spec,
)
from minegen.core.artifacts import (
    CAPABILITY_GRAPH_ARTIFACT,
    COMMUNICATION_ARTIFACT,
    DECLINE_ARTIFACT,
    DEVELOPMENT_MESH_ARTIFACT,
    LAYOUT_V2_ARTIFACT,
    LEGACY_RAMP_ARTIFACT,
    LEVELS_ARTIFACT,
    NETWORK_ARTIFACT,
    SENSORS_ARTIFACT,
    SHAFTS_ARTIFACT,
    STOPES_ARTIFACT,
    TARGETS_ARTIFACT,
    TIMELINE_ARTIFACT,
    TUNNEL_MESH_ARTIFACT,
    RampSource,
)

__all__ = [
    "STAGE_ARTIFACTS",
    "WORKFLOW_STAGES",
    "ResetPlan",
    "ResetStageNotDeletableError",
    "ResetTargetNotGeneratedError",
    "WorkflowStage",
    "reset_closure",
    "reset_plan",
]

WorkflowStage = Literal[
    "WORLD",
    "TARGETS",
    "DECLINE",
    "SMOOTH",
    "LAYOUT",
    "LEVELS",
    "EXCAVATION",
    "SHAFTS",
    "NETWORK",
    "CAPABILITY",
    "PRODUCTION",
    "SCHEDULE",
    "COMMUNICATION",
    "SENSORS",
]

WORKFLOW_STAGES: Final[tuple[WorkflowStage, ...]] = get_args(WorkflowStage)

#: what each stage OWNS (fingerprint-file names of the registry). Workflow
#: order; the two Setup stages (Scenario, Method) are scenario-document
#: edits (rule 40 full invalidation), not derived artifacts, and ``WORLD``
#: owns nothing of its own (preview-only root, see the module docstring).
STAGE_ARTIFACTS: Final[Mapping[WorkflowStage, tuple[str, ...]]] = {
    "WORLD": (),
    # legacy Phase 03–05 chain (Hybrid-A*)
    "TARGETS": (TARGETS_ARTIFACT,),
    "DECLINE": (DECLINE_ARTIFACT,),
    "SMOOTH": (LEGACY_RAMP_ARTIFACT,),
    # layout-v2: the catalogue; the selection and the level accesses follow
    # through the registry closure (rule 151)
    "LAYOUT": (LAYOUT_V2_ARTIFACT,),
    "LEVELS": (LEVELS_ARTIFACT,),
    "EXCAVATION": (TUNNEL_MESH_ARTIFACT, DEVELOPMENT_MESH_ARTIFACT),
    "SHAFTS": (SHAFTS_ARTIFACT,),
    "NETWORK": (NETWORK_ARTIFACT,),
    "CAPABILITY": (CAPABILITY_GRAPH_ARTIFACT,),
    "PRODUCTION": (STOPES_ARTIFACT,),
    "SCHEDULE": (TIMELINE_ARTIFACT,),
    "COMMUNICATION": (COMMUNICATION_ARTIFACT,),
    "SENSORS": (SENSORS_ARTIFACT,),
}


class ResetTargetNotGeneratedError(LookupError):
    """``DELETE …/design/stages/{stage}`` on a stage none of whose own
    artifacts exist: there is nothing to reset FROM (a downstream residue is
    reset from its own stage)."""

    code = "RESET_TARGET_NOT_GENERATED"
    http_status = 404

    def __init__(self, scenario_id: str, stage: str, artifacts: tuple[str, ...]) -> None:
        super().__init__(
            f"scenario '{scenario_id}' has nothing to reset at stage {stage}: "
            f"{', '.join(artifacts) or 'no artifact'} not generated"
        )
        self.scenario_id = scenario_id
        self.stage = stage
        self.artifacts = artifacts


class ResetStageNotDeletableError(RuntimeError):
    """``WORLD`` is a preview-only root: resetting it is the scenario PUT /
    world regeneration path (rules 40 / 46), never a derived-artifact delete."""

    code = "RESET_STAGE_NOT_DELETABLE"
    http_status = 409

    def __init__(self, stage: str) -> None:
        super().__init__(
            f"stage {stage} is not reset through the derived-artifact path; regenerate the "
            "world (POST …/world/generate) or replace the scenario (PUT …/scenarios/{id})"
        )
        self.stage = stage


def stage_artifacts(stage: str) -> tuple[str, ...]:
    try:
        return STAGE_ARTIFACTS[stage]  # type: ignore[index]
    except KeyError:
        raise KeyError(f"'{stage}' is not a workflow stage") from None


def reset_closure(stage: str, active_source: RampSource) -> tuple[ArtifactSpec, ...]:
    """The artifacts a reset from ``stage`` removes, in registry declaration
    order: the stage's own artifacts plus ``invalidated_by(own, source)``.
    ``WORLD`` → every registered derived artifact."""
    own = stage_artifacts(stage)
    if stage == "WORLD":
        return derived_artifacts()
    reached = {name: spec(name) for name in own}
    for a in invalidated_by(own, active_source):
        reached.setdefault(a.name, a)
    return tuple(a for a in derived_artifacts() if a.name in reached)


@dataclass(frozen=True)
class ResetPlan:
    """What a reset from ``stage`` would delete, as observed on disk NOW."""

    stage: str
    active_source: RampSource
    #: the stage's own artifacts (fingerprint-file names)
    stage_artifacts: tuple[str, ...]
    #: whether at least one of them exists (a reset has something to reset FROM)
    present: bool
    #: every file of the closure that exists, in deletion order
    will_delete: tuple[str, ...]
    #: the whole closure (present or not), for the record
    closure: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": self.stage,
            "activeSource": self.active_source,
            "stageArtifacts": list(self.stage_artifacts),
            "present": self.present,
            "willDelete": list(self.will_delete),
            "closure": list(self.closure),
        }


def reset_plan(stage: str, active_source: RampSource, derived_dir: Path) -> ResetPlan:
    """The preview AND the delete list: ``will_delete`` is exactly the set of
    closure files that exist under ``derived_dir`` at the time of the call."""
    own = stage_artifacts(stage)
    closure = reset_closure(stage, active_source)
    files = [f.name for a in closure for f in a.files]
    present_files = tuple(name for name in files if (derived_dir / name).is_file())
    own_present = any((derived_dir / name).is_file() for name in own)
    return ResetPlan(
        stage=stage,
        active_source=active_source,
        stage_artifacts=own,
        present=own_present,
        will_delete=present_files,
        closure=tuple(files),
    )
