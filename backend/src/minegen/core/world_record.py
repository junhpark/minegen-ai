"""The WORLD COMMIT RECORD — the on-disk binding of a world to the scenario
document and the ``arrays.npz`` one generation published (AC-01F.2 correction,
finding B1).

``derived/world.json`` used to be a statistics snapshot no module read. It is
now the COMMIT RECORD of a world generation, and its publication — already the
LAST step of ``WorldService._save``, after ``arrays.npz`` — is the COMMIT POINT
of that generation::

    {"publication": {"scenarioId", "scenarioRevision", "arraysRevision"},
     "stats": { ...exactly the world.stats(scenario) payload... }}

Why it exists. Before it, a world was bound to its document only in memory
(``WorldService._BoundWorld``). A writer that died between ``store.replace()``
and ``invalidate()`` left a NEW ``scenario.json`` beside an OLD ``arrays.npz``
PERMANENTLY, and a fresh process had no evidence to tell that apart from a
coherent pair: it bound whatever the two current revisions were and answered
200. The record is that evidence.

What it is NOT. It is publication PROVENANCE, not dependency authority: it
compares ONE publication's own recorded inputs against the live files it names.
It is never ``payload.sourceRevision`` compared to a recomputed fingerprint (the
AC-01F A12 boundary), it introduces no generic freshness rule, and
``derived/world.json`` stays UNREGISTERED — in no fingerprint and in no cascade.

Both revisions are the existing rule-60 stat identity
(:func:`minegen.core.revision.file_revision`); no content hash is introduced.
They are the values the PUBLISHER installed (``publish_npz`` returns the arrays
revision from its own file descriptor, and the scenario revision is the one
``WorldService.generate`` verified under the store lock), never a stat of a path
taken afterwards — across processes such a stat can name another generation's
file (correction Q1.1).

This module is a LEAF: it builds and CHECKS a record object. It never touches
the filesystem — the bytes are observed by ``ArtifactReader.snapshot`` under the
store lock and parsed outside it, so the read authority stays the only module
that reads ``derived/``.
"""

from __future__ import annotations

from typing import Any, Final

__all__ = [
    "PUBLICATION_KEY",
    "STATS_KEY",
    "WORLD_RECORD_FILE",
    "build_world_record",
    "record_rejection",
]

#: the record's file name under ``derived/`` — UNREGISTERED (rule 40's
#: directory walk removes it; no fingerprint and no cascade name it)
WORLD_RECORD_FILE: Final[str] = "world.json"

#: the record block; ``stats`` carries the payload the file used to be
PUBLICATION_KEY: Final[str] = "publication"
STATS_KEY: Final[str] = "stats"

_SCENARIO_ID: Final[str] = "scenarioId"
_SCENARIO_REVISION: Final[str] = "scenarioRevision"
_ARRAYS_REVISION: Final[str] = "arraysRevision"


def build_world_record(
    *,
    scenario_id: str,
    scenario_revision: str,
    arrays_revision: str,
    stats: dict[str, Any],
) -> dict[str, Any]:
    """The record document a world generation publishes as its commit point."""
    return {
        PUBLICATION_KEY: {
            _SCENARIO_ID: scenario_id,
            _SCENARIO_REVISION: scenario_revision,
            _ARRAYS_REVISION: arrays_revision,
        },
        STATS_KEY: stats,
    }


def record_rejection(
    record: object,
    *,
    scenario_id: str,
    scenario_revision: str,
    arrays_revision: str,
) -> str | None:
    """``None`` when ``record`` commits exactly this scenario document and this
    ``arrays.npz``; otherwise the one-line reason it does not.

    A PURE comparison — it never repairs, never re-publishes and never guesses.
    ``record`` is whatever the captured bytes parsed to (``None`` for an absent
    or unparseable file), so every degenerate shape is a rejection rather than
    an exception. Reasons name FILES and revisions, never filesystem paths."""
    if not isinstance(record, dict):
        return "derived/world.json is missing or is not a JSON object"
    publication = record.get(PUBLICATION_KEY)
    if not isinstance(publication, dict):
        return "derived/world.json carries no publication record"
    recorded_id = publication.get(_SCENARIO_ID)
    if recorded_id != scenario_id:
        return f"the world was published for scenario '{recorded_id}', not '{scenario_id}'"
    recorded_scenario = publication.get(_SCENARIO_REVISION)
    if recorded_scenario != scenario_revision:
        return (
            f"the world was generated from scenario.json revision '{recorded_scenario}', "
            f"and the document on disk is '{scenario_revision}'"
        )
    recorded_arrays = publication.get(_ARRAYS_REVISION)
    if recorded_arrays != arrays_revision:
        return (
            f"the world publication names arrays.npz revision '{recorded_arrays}', "
            f"and the file on disk is '{arrays_revision}'"
        )
    return None
