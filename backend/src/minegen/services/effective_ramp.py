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

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from minegen.core.artifacts import (
    LAYOUT_V2_ARTIFACT,
    LAYOUT_V2_SELECTED_ARTIFACT,
    LEGACY_RAMP_ARTIFACT,
    RAMP_OWNING_ARTIFACTS,
    RAMP_SOURCE_FILE,
)

RampSource = Literal["LEGACY", "LAYOUT_V2"]
RAMP_SOURCES: tuple[RampSource, ...] = ("LEGACY", "LAYOUT_V2")

__all__ = [
    "LAYOUT_V2_ARTIFACT",
    "LAYOUT_V2_SELECTED_ARTIFACT",
    "LEGACY_RAMP_ARTIFACT",
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


def file_revision(path: Path) -> str | None:
    """Stable short revision of an artifact file: (size, mtime_ns) hash —
    the same identity the InputFingerprint protocol uses."""
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    return hashlib.sha256(f"{path.name}:{st.st_size}:{st.st_mtime_ns}".encode()).hexdigest()[:16]


def read_ramp_source(derived_dir: Path) -> RampSource:
    path = derived_dir / RAMP_SOURCE_FILE
    if not path.is_file():
        return "LEGACY"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "LEGACY"
    source = data.get("activeSource") if isinstance(data, dict) else None
    return source if source in RAMP_SOURCES else "LEGACY"


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


def _load(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def resolve_effective_ramp(derived_dir: Path) -> EffectiveRampResolution:
    """Deterministic resolution of the active Effective Ramp from the
    persisted derived state alone (no in-memory inputs)."""
    source = read_ramp_source(derived_dir)
    legacy_path = derived_dir / LEGACY_RAMP_ARTIFACT
    selected_path = derived_dir / LAYOUT_V2_SELECTED_ARTIFACT
    legacy_ok = legacy_path.is_file()
    layout_ok = (derived_dir / LAYOUT_V2_ARTIFACT).is_file()
    selected_ok = selected_path.is_file()
    payload: dict[str, Any] | None = None
    if source == "LEGACY":
        raw = _load(legacy_path)
        if raw is not None:
            payload = legacy_adapter(raw, file_revision(legacy_path))
        owning = LEGACY_RAMP_ARTIFACT
    else:
        sel = _load(selected_path)
        if sel is not None:
            payload = {
                **sel,
                "owningArtifact": LAYOUT_V2_SELECTED_ARTIFACT,
                "activeSource": "LAYOUT_V2",
            }
        owning = LAYOUT_V2_SELECTED_ARTIFACT
    return EffectiveRampResolution(
        active_source=source,
        owning_artifact=owning,
        payload=payload,
        legacy_available=legacy_ok,
        layout_v2_available=layout_ok,
        layout_v2_selected=selected_ok,
    )
