"""Source-neutral Effective Ramp resolution (Phase 20A, rules 149–150).

Downstream phases (tunnel mesh, levels, MineNetwork, timeline, communication,
sensors, walkthrough) consume ONE ramp contract — the Effective Ramp — and
never care whether it came from the legacy Phase 04/05 pipeline or from the
layout-v2 parametric search. The active source is an explicit, persisted,
backend-owned choice:

    derived/ramp_source.json        {"activeSource": "LEGACY" | "LAYOUT_V2"}
                                    (absent → LEGACY)
    derived/decline_smoothed.json   legacy Phase 05 artifact (unchanged)
    derived/layout_v2_selected.json materialized layout-v2 effective ramp

The legacy artifact is exposed through a thin ADAPTER view (provenance
fields added, geometry untouched); the layout-v2 artifact is already
written in the contract. Every effective ramp carries::

    sourceKind      LEGACY_SMOOTHED | LEGACY_RAW_FALLBACK | PARAMETRIC_V2
    owningArtifact  the derived file that owns the segment geometry
    sourceRevision  revision of the owning artifact
    activeSource    LEGACY | LAYOUT_V2
    segments[]      levelId / effectiveCenterline / boundaryTangents /
                    effectiveSource / report   (Phase 05 shape)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from minegen.core.artifacts import (
    LAYOUT_V2_ARTIFACT,
    LAYOUT_V2_SELECTED_ARTIFACT,
    LEGACY_RAMP_ARTIFACT,
    RAMP_OWNING_ARTIFACTS,
    RAMP_SOURCE_FILE,
    RampSource,
)
from minegen.core.revision import file_revision
from minegen.services.artifact_reader import ArtifactReader, ArtifactSnapshot

RAMP_SOURCES: tuple[RampSource, ...] = ("LEGACY", "LAYOUT_V2")

#: the artifacts one ramp resolution observes: the source switch, both owners
#: and the catalogue whose presence the summary reports
RAMP_FILES: tuple[str, ...] = (
    RAMP_SOURCE_FILE,
    LEGACY_RAMP_ARTIFACT,
    LAYOUT_V2_ARTIFACT,
    LAYOUT_V2_SELECTED_ARTIFACT,
)

__all__ = [
    "LAYOUT_V2_ARTIFACT",
    "LAYOUT_V2_SELECTED_ARTIFACT",
    "LEGACY_RAMP_ARTIFACT",
    "RAMP_FILES",
    "RAMP_OWNING_ARTIFACTS",
    "RAMP_SOURCE_FILE",
    "EffectiveRampResolution",
    "RampSource",
    "file_revision",
    "legacy_adapter",
    "read_ramp_source",
    "resolve_effective_ramp",
    "write_ramp_source",
]

SOURCE_KIND_LEGACY_SMOOTHED = "LEGACY_SMOOTHED"
SOURCE_KIND_LEGACY_RAW_FALLBACK = "LEGACY_RAW_FALLBACK"
SOURCE_KIND_PARAMETRIC_V2 = "PARAMETRIC_V2"


def read_ramp_source(reader: ArtifactReader, scenario_id: str) -> RampSource:
    """The ACTIVE ramp source, through the ONE read authority (AC-01F).

    ABSENT → ``LEGACY`` (rule 150: LEGACY IS the absence of the file);
    present but not a usable document → ``ArtifactMalformedError`` (A7: never
    a silent LEGACY, which used to re-point the whole mine, Stage A I-12).

    The parameters are the reader and the scenario id rather than the derived
    directory: the file must be observed under the per-scenario store lock the
    writers hold, and the bytes must be read by ``artifact_reader`` alone —
    a ``Path``-only signature would need a second raw reader of a derived
    artifact, which is exactly what this step removes."""
    return reader.resolve_ramp_source(reader.snapshot(scenario_id, [RAMP_SOURCE_FILE]))


def write_ramp_source(derived_dir: Path, source: RampSource) -> None:
    derived_dir.mkdir(parents=True, exist_ok=True)
    (derived_dir / RAMP_SOURCE_FILE).write_text(
        json.dumps({"activeSource": source}), encoding="utf-8"
    )


def legacy_adapter(smoothed_payload: dict[str, Any], revision: str | None) -> dict[str, Any]:
    """Adapter view of the Phase 05 artifact in the Effective Ramp contract.
    Geometry, segments and totals are the artifact's own objects — nothing
    is copied, moved or re-smoothed; only provenance fields are added."""
    fallback = any(s.get("effectiveSource") == "RAW_FALLBACK" for s in smoothed_payload["segments"])
    kind = SOURCE_KIND_LEGACY_RAW_FALLBACK if fallback else SOURCE_KIND_LEGACY_SMOOTHED
    return {
        **smoothed_payload,
        "sourceKind": kind,
        "owningArtifact": LEGACY_RAMP_ARTIFACT,
        "sourceRevision": revision,
        "activeSource": "LEGACY",
        "candidateId": None,
        "family": None,
    }


@dataclass(frozen=True)
class EffectiveRampResolution:
    active_source: RampSource
    owning_artifact: str
    payload: dict[str, Any] | None  # None when the active source has no artifact yet
    legacy_available: bool
    layout_v2_available: bool
    layout_v2_selected: bool

    @property
    def available(self) -> bool:
        return self.payload is not None

    def summary(self) -> dict[str, Any]:
        p = self.payload
        return {
            "activeSource": self.active_source,
            "owningArtifact": self.owning_artifact,
            "available": self.available,
            "legacyAvailable": self.legacy_available,
            "layoutV2Available": self.layout_v2_available,
            "layoutV2Selected": self.layout_v2_selected,
            "sourceKind": p.get("sourceKind") if p else None,
            "sourceRevision": p.get("sourceRevision") if p else None,
            "candidateId": p.get("candidateId") if p else None,
            "family": p.get("family") if p else None,
            "status": p.get("status") if p else None,
            "segmentCount": len(p.get("segments", [])) if p else 0,
        }


def resolve_effective_ramp(
    snapshot: ArtifactSnapshot, reader: ArtifactReader
) -> EffectiveRampResolution:
    """Deterministic resolution of the active Effective Ramp from ONE read
    snapshot of the persisted derived state (AC-01F).

    The ACTIVE owner must be VALID: its typed read-state error propagates
    (``LAYOUT_V2_SELECTION_STALE`` / ``LAYOUT_V2_CLEARANCE_MISMATCH`` /
    ``ARTIFACT_MALFORMED``) instead of an arbitrary document being served AS
    the ramp (Stage A I-11). ABSENT stays ``payload=None`` — the caller turns
    that into ``SMOOTHED_NOT_GENERATED`` / ``LAYOUT_V2_NOT_SELECTED`` or, for
    the status endpoint, ``available: false`` (A8).

    The INACTIVE owner and the catalogue are PRESENCE flags only, taken from
    the SAME observations (never a third ``is_file`` probe), so the R4
    interleaving — one response whose ramp and whose ``layoutV2Selected`` flag
    disagree — is structurally impossible."""
    source = reader.resolve_ramp_source(snapshot)
    legacy_read = reader.read(snapshot, LEGACY_RAMP_ARTIFACT)
    selected_read = reader.read(snapshot, LAYOUT_V2_SELECTED_ARTIFACT)
    payload: dict[str, Any] | None = None
    if source == "LEGACY":
        owning = LEGACY_RAMP_ARTIFACT
        if legacy_read.error is not None:
            raise legacy_read.error
        if legacy_read.raw is not None:
            payload = legacy_adapter(legacy_read.raw, legacy_read.revision)
    else:
        owning = LAYOUT_V2_SELECTED_ARTIFACT
        if selected_read.error is not None:
            raise selected_read.error
        if selected_read.raw is not None:
            payload = {
                **selected_read.raw,
                "owningArtifact": LAYOUT_V2_SELECTED_ARTIFACT,
                "activeSource": "LAYOUT_V2",
            }
    return EffectiveRampResolution(
        active_source=source,
        owning_artifact=owning,
        payload=payload,
        legacy_available=_present(snapshot, LEGACY_RAMP_ARTIFACT),
        layout_v2_available=_present(snapshot, LAYOUT_V2_ARTIFACT),
        layout_v2_selected=_present(snapshot, LAYOUT_V2_SELECTED_ARTIFACT),
    )


def _present(snapshot: ArtifactSnapshot, name: str) -> bool:
    """Presence of one artifact in the SAME observation set — the flag the
    summary has always reported (``Path.is_file``), now read once."""
    obs = snapshot.observation(name)
    return obs is not None and obs.present
