"""Atomic publication of ONE persisted file (AC-01F.2, F06-B).

Every artifact of the store — ``scenario.json``, ``arrays.npz`` and every
file under ``derived/`` — is PUBLISHED through this module. A publication is

1. ``path.parent`` must already exist. Callers keep their own ``mkdir``
   calls; the helper never creates a directory.
2. the bytes are written to a TEMP SIBLING in the same directory, named
   ``.<final name>.<8 random hex>.tmp`` (the NPZ temp additionally ends in
   ``.npz``, so numpy never appends a suffix of its own and the name stays
   honest about what the file holds), created ``O_CREAT | O_EXCL`` so a name
   collision is an error rather than a silently shared file;
3. ``flush()`` + :func:`os.fsync` on that temp file;
4. :func:`os.replace` of the temp onto the target — atomic on POSIX: a
   concurrent reader observes either the whole previous file or the whole
   new one, never a prefix of either;
5. a BEST-EFFORT fsync of the containing directory (``os.open(dir,
   O_RDONLY)`` + ``os.fsync``), so the rename itself is durable on
   filesystems that honour it; every ``OSError`` there is ignored, because
   some platforms and filesystems refuse a directory fsync outright and a
   published file must not fail on that;
6. on ANY exception before the replace, the temp file is removed
   (best effort) and the exception propagates unchanged — the previous
   target, or its absence, is untouched.

The helper never reads the target, never retries, never logs, and imports
the standard library and numpy only. It is a LEAF: it knows nothing about
scenarios, artifacts, locks, fingerprints or the registry.

What it does NOT do, stated so nobody assumes it:

* two publications are two atomic file replacements, never one atomic pair.
  A report and its GLB, or a selection and its level accesses, are ORDERED
  (AC-01F.2 D3) so a crash between them leaves the state the validated
  reader classifies most conservatively; the read-side checks stay the
  durable answer.
* a crash before step 4 can leave a ``.<name>.<hex>.tmp`` sibling behind.
  No reader ever observes it (every reader looks up artifact file NAMES)
  and the registry cascade ignores it. ``ScenarioStore.clear_derived``
  removes such a temp only UNDER ``derived/`` — it walks that directory and
  unlinks ``arrays.npz`` by its exact path — so a temp beside
  ``scenario.json`` / ``arrays.npz`` in the scenario root survives every
  invalidation and is removed only by ``ScenarioStore.delete``. No startup
  sweep exists.
* two narrow windows survive by design and are documented rather than
  coded around: a non-``OSError`` raised inside the directory fsync of
  step 5 escapes AFTER the replace — the artifact IS published and the
  caller nonetheless aborts — and an interrupt landing inside the temp
  ``unlink`` of step 6 leaves the residue the previous bullet describes.
* the publication installs a NEW INODE. Mode, ownership and symlink
  identity of an existing target are therefore not preserved: the temp is
  created ``0o666`` masked by the process umask and owned by the
  publishing uid, and a target that was a symlink is replaced by a regular
  file. Nothing in MineGen sets a special mode, owner or link on a
  persisted file.
* the rule-60 stat identity is unchanged in semantics: ``os.replace``
  installs the temp file's inode, whose size and mtime are those of this
  write, so every publication is a NEW ``(size, mtime_ns)`` revision — a
  byte-identical regeneration still counts as a new revision, exactly as
  an in-place rewrite did.

The bytes are the caller's bytes: no ``json.dumps`` argument, encoding or
serializer changes here — ``np.savez_compressed`` is still the NPZ
serializer, only its destination moved.
"""

from __future__ import annotations

import contextlib
import os
import secrets
from pathlib import Path
from typing import Any

import numpy as np

__all__ = ["publish_bytes", "publish_npz", "publish_text"]

#: temp siblings are hidden (leading dot) and carry a random token, so two
#: concurrent publications of the same target do not normally collide; the
#: 2**-32 collision that remains is not tolerated silently but raised
#: (``O_EXCL``) and cleaned up by the ordinary exception path
TEMP_SUFFIX = ".tmp"
TEMP_TOKEN_BYTES = 4  # 8 hex characters
#: create-exclusively, write-only; the mode is the ordinary 0o666 that
#: ``open(..., "wb")`` requests, masked by the process umask
TEMP_OPEN_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL
TEMP_OPEN_MODE = 0o666


def _temp_sibling(path: Path, *, suffix: str = "") -> Path:
    """``.<final name>.<8 random hex>.tmp[<suffix>]`` in the target's own
    directory — the same filesystem, which ``os.replace`` requires."""
    token = secrets.token_hex(TEMP_TOKEN_BYTES)
    return path.with_name(f".{path.name}.{token}{TEMP_SUFFIX}{suffix}")


def _open_temp(temp: Path) -> Any:
    """Create the temp sibling EXCLUSIVELY. A pre-existing file at that name
    — a token collision, or residue of a crashed publication — raises
    ``FileExistsError`` instead of being opened and overwritten; the caller's
    exception path removes it and the target is never touched. Second-order
    consequence of that cleanup on a (2**-32) concurrent token collision
    across processes: the loser removes the winner's in-flight temp, so the
    winner's ``os.replace`` fails ENOENT and its publication aborts with the
    previous target intact — safe, and inside one process same-target
    publishes are serialized by the store lock anyway."""
    return os.fdopen(os.open(temp, TEMP_OPEN_FLAGS, TEMP_OPEN_MODE), "wb")


def _fsync_directory(directory: Path) -> None:
    """Best-effort durability of the RENAME. Ignored on platforms and
    filesystems that refuse a directory fsync: the file is already
    published at this point, and refusing the publication over it would be
    strictly worse. A non-``OSError`` failure here still escapes, after the
    artifact has been published (module docstring)."""
    fd = None
    try:
        fd = os.open(directory, os.O_RDONLY)
        os.fsync(fd)
    except OSError:
        pass
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)


def publish_bytes(path: Path, data: bytes) -> None:
    """Publish ``data`` as ``path``, atomically (module docstring)."""
    temp = _temp_sibling(path)
    try:
        with _open_temp(temp) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            temp.unlink()
        raise
    _fsync_directory(path.parent)


def publish_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Publish ``text`` as ``path``, atomically. Exactly
    ``publish_bytes(path, text.encode(encoding))`` — the encoding default is
    the one every migrated call site passed explicitly."""
    publish_bytes(path, text.encode(encoding))


def publish_npz(path: Path, **arrays: Any) -> None:
    """Publish ``arrays`` as a compressed NPZ at ``path``, atomically.

    ``np.savez_compressed`` remains the serializer and is handed the OPEN
    temp file, so the durability path is the one of :func:`publish_bytes`
    (flush + fsync of the handle that was written) and numpy has no name to
    append a suffix to. numpy's own ``_savez`` opens the DESTINATION zip in
    mode ``"w"`` and writes the arrays into the live file, which is why an
    in-place ``np.savez_compressed`` is not publishable state."""
    temp = _temp_sibling(path, suffix=".npz")
    try:
        with _open_temp(temp) as handle:
            np.savez_compressed(handle, **arrays)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            temp.unlink()
        raise
    _fsync_directory(path.parent)
