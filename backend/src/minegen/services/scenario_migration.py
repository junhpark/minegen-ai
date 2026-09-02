"""Persisted scenario-document migrations (Phase 18).

    v1 (Phase 02–17)   ``blockModel {dx, dy, dz}``  + BlockModel arrays.npz
    v2 (Phase 18)      ``fieldSampling {spacingX, spacingY, spacingZ}``
                       + SpatialFieldSet arrays.npz (``field_artifact_version``)

Migration is deterministic and explicit: the numbers are carried over
unchanged (10 m stays 10 m), only their meaning changes from mining-block
size to numerical field spacing. Every derived artifact of a migrated
scenario is discarded by the store — a Phase-17 BlockModel NPZ must never be
consumed under Phase-18 field semantics.
"""

from __future__ import annotations

from typing import Any

from minegen.core.models import SCENARIO_SCHEMA_VERSION, Scenario


class UnsupportedSchemaVersionError(ValueError):
    """The document was written by a NEWER schema than this backend knows."""


def migrate_scenario_document(raw: dict[str, Any]) -> tuple[Scenario, list[str]]:
    """Upgrade a raw persisted document to the current schema version.
    Returns the validated scenario and a list of human-readable migration
    notes (empty when the document was already current)."""
    doc = dict(raw)
    version = int(doc.get("schemaVersion", doc.get("schema_version", 1)))
    if version > SCENARIO_SCHEMA_VERSION:
        raise UnsupportedSchemaVersionError(
            f"scenario schemaVersion {version} is newer than the supported "
            f"{SCENARIO_SCHEMA_VERSION}"
        )
    notes: list[str] = []
    if version < 2:
        legacy = doc.pop("blockModel", None)
        if legacy is None:
            legacy = doc.pop("block_model", None)
        if isinstance(legacy, dict) and "fieldSampling" not in doc:
            doc["fieldSampling"] = {
                "spacingX": legacy.get("dx", 10.0),
                "spacingY": legacy.get("dy", 10.0),
                "spacingZ": legacy.get("dz", 10.0),
            }
            notes.append("v1→v2: blockModel {dx,dy,dz} → fieldSampling {spacingX,Y,Z}")
        doc["schemaVersion"] = 2
        notes.append("v1→v2: derived world/design artifacts discarded (regeneration required)")
    return Scenario.model_validate(doc), notes
