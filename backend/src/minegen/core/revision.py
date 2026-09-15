"""The ONE stat identity of a persisted artifact file (AC-01F).

``file_revision`` is the rule-60 revision of a single file: the short hash of
``(name, size, mtime_ns)`` — the same identity ``InputFingerprint`` captures
per path. It is the comparand of every persisted provenance field that names
an upstream file (``shafts.levelsRevision`` ↔ ``levels.json``,
``capabilityGraph.networkRevision`` ↔ ``network.json``,
``layout_v2_selected.layoutRevision`` ↔ ``layout_v2.json``).

Moved VERBATIM from ``services/effective_ramp.py`` (name, docstring and
formula unchanged, AC-01F A17) so the validated-read authority
(``services/artifact_reader.py``) can use it without importing a service:
``effective_ramp`` re-exports the name, so every existing import keeps
working. This module is a LEAF — standard library only.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

__all__ = ["file_revision", "revision_of_stat"]


def revision_of_stat(name: str, size: int, mtime_ns: int) -> str:
    """The rule-60 revision of a file with this NAME and these stat fields.

    The FORMULA is the one :func:`file_revision` has always used — this
    function only names it, so a publisher can compute the identity of the
    bytes it is INSTALLING from the temp file's own ``os.fstat`` instead of
    stat'ing the destination path afterwards (AC-01F.2 correction Q1.1: a
    post-hoc stat of a path names whatever file is there, which across
    processes can be another generation's). ``file_revision(p)`` and
    ``revision_of_stat(p.name, st.st_size, st.st_mtime_ns)`` are equal by
    construction and a test pins it."""
    return hashlib.sha256(f"{name}:{size}:{mtime_ns}".encode()).hexdigest()[:16]


def file_revision(path: Path) -> str | None:
    """Stable short revision of an artifact file: (size, mtime_ns) hash —
    the same identity the InputFingerprint protocol uses."""
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    return revision_of_stat(path.name, st.st_size, st.st_mtime_ns)
