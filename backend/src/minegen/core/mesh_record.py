"""The MESH COMMIT RECORD — the INTERNAL evidence that a mesh report and its
GLB belong to the same publication generation (AC-01F.2 correction, B3).

A sweep publishes two files (``<mesh>.glb`` and ``<mesh>.json``), so a
republication that dies between them leaves GLB G2 beside report G1. The mesh
build is DETERMINISTIC, so G2's bytes equal G1's and the report's
``artifactRevision`` — a content hash — still agrees: the content hash cannot
see that mixture on any route. What distinguishes the two generations is the
PUBLICATION identity.

That identity is recorded in a sidecar, ``<mesh>.commit.json``, and NOT in the
report: the report and the scene are public payloads whose success shape is
contractually unchanged (the AC-01F frozen oracle compares them leaf by leaf,
and ``tests/test_layout_policy_restore.py`` hashes them warm-vs-cold). The
first draft of this correction put a ``glbRevision`` field in the report
instead, which leaked publication provenance into the public projection and
forced BOTH of those comparison contracts to be widened — the review rejected
it, and this sidecar is the corrective.

The sidecar is published LAST, after the report (and, on the FAILED path,
after the stale GLB is unlinked), so its publication is the COMMIT POINT of a
mesh generation, exactly as ``derived/world.json`` is for a world. It is
UNREGISTERED — in no fingerprint and in no cascade — because it is publication
provenance, not dependency authority (AC-01F A12); a leftover sidecar beside a
cascade-deleted report is inert, since the artifact is then ABSENT and the
check never runs.

Both revisions are the existing rule-60 stat identity, and both are the values
the PUBLISHER installed (``publish_bytes`` / ``publish_text`` return them from
the temp file's own ``os.fstat``), never a stat of the path afterwards.

This module is a LEAF: it builds and CHECKS a record object and never touches
the filesystem.
"""

from __future__ import annotations

from typing import Any, Final

__all__ = [
    "GLB_REVISION_KEY",
    "MESH_COMMIT_SUFFIX",
    "REPORT_REVISION_KEY",
    "build_mesh_commit",
    "mesh_commit_name",
    "mesh_commit_rejection",
]

#: ``tunnel_mesh.json`` → ``tunnel_mesh.commit.json``
MESH_COMMIT_SUFFIX: Final[str] = ".commit.json"

REPORT_REVISION_KEY: Final[str] = "reportRevision"
GLB_REVISION_KEY: Final[str] = "glbRevision"


def mesh_commit_name(report_name: str) -> str:
    """The sidecar file name of a mesh report file name."""
    stem = report_name[: -len(".json")] if report_name.endswith(".json") else report_name
    return f"{stem}{MESH_COMMIT_SUFFIX}"


def build_mesh_commit(*, report_revision: str, glb_revision: str | None) -> dict[str, Any]:
    """The record a mesh publication commits itself with. ``glb_revision`` is
    ``None`` on the FAILED path, which publishes a report and NO GLB."""
    return {REPORT_REVISION_KEY: report_revision, GLB_REVISION_KEY: glb_revision}


def mesh_commit_rejection(
    record: object,
    *,
    report_name: str,
    report_revision: str,
    glb_name: str,
    glb_revision: str | None,
    expects_glb: bool,
) -> str | None:
    """``None`` when ``record`` commits exactly this report and this GLB;
    otherwise the one-line reason it does not.

    A PURE comparison — it never repairs and never guesses. ``record`` is
    whatever the captured bytes parsed to (``None`` for an absent or
    unparseable sidecar), so every degenerate shape is a rejection rather than
    an exception. ``glb_revision`` is the LIVE revision of the GLB beside the
    report, or ``None`` when no GLB is there."""
    if not isinstance(record, dict):
        return "its publication record is missing or is not a JSON object"
    recorded_report = record.get(REPORT_REVISION_KEY)
    if recorded_report != report_revision:
        return (
            f"its publication record names '{report_name}' revision "
            f"'{recorded_report}', and the file on disk is '{report_revision}'"
        )
    if not expects_glb:
        return None
    recorded_glb = record.get(GLB_REVISION_KEY)
    if recorded_glb != glb_revision:
        return (
            f"its publication record names '{glb_name}' revision '{recorded_glb}', "
            f"and the file on disk is '{glb_revision}'"
        )
    return None
