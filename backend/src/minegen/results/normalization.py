"""Canonical normalized form of a MineResult and its deterministic identity
(directive §19, §32, §84).

``NormalizedResult`` is an ordered mapping of NumPy arrays under FIXED keys:
input order is never an authority — samples are sorted by (time, edgeId) /
(time, agentId) / (time, edgeId), missing values are NaN (internal only:
the API never emits NaN, a missing value is reported by omission), string
columns are unicode arrays. ``content_sha256`` is a canonical byte digest
(key, dtype, shape, bytes in key order) and ``result_id`` binds that digest
to the source snapshot, the domain and the source application, so the same
package imported twice yields the same id (idempotent import).
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Mapping
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.exchange.models import SourceSnapshot
from minegen.results.errors import ResultPackageInvalidError

RESULT_ID_LENGTH = 16

NormalizedResult = dict[str, npt.NDArray[Any]]


def content_sha256(arrays: Mapping[str, npt.NDArray[Any]]) -> str:
    h = hashlib.sha256()
    for key in sorted(arrays):
        arr = np.ascontiguousarray(arrays[key])
        header = json.dumps(
            {"key": key, "dtype": arr.dtype.str, "shape": list(arr.shape)}, sort_keys=True
        )
        h.update(header.encode("utf-8"))
        h.update(b"\0")
        h.update(arr.tobytes())
        h.update(b"\0")
    return h.hexdigest()


def result_id_for(
    normalized_sha256: str,
    snapshot: SourceSnapshot,
    domain: str,
    source_application: str,
) -> str:
    payload = json.dumps(
        {
            "normalizedSha256": normalized_sha256,
            "sourceSnapshot": snapshot.model_dump(mode="json", by_alias=True),
            "domain": domain,
            "sourceApplication": source_application,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:RESULT_ID_LENGTH]


def npz_bytes(arrays: Mapping[str, npt.NDArray[Any]]) -> bytes:
    """The stored normalized container (compressed NPZ, keys in sorted order;
    the CANONICAL identity is ``content_sha256``, not these bytes)."""
    buf = io.BytesIO()
    ordered: dict[str, Any] = {k: np.ascontiguousarray(arrays[k]) for k in sorted(arrays)}
    np.savez_compressed(buf, **ordered)
    return buf.getvalue()


def load_npz(data: bytes, *, expected_sha256: str) -> NormalizedResult:
    """READ ≠ TRUST: the persisted normalized container must reproduce the
    manifest's canonical digest, else the result folder is refused."""
    try:
        with np.load(io.BytesIO(data), allow_pickle=False) as loaded:
            arrays: NormalizedResult = {k: np.asarray(loaded[k]) for k in loaded.files}
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, EOFError) as exc:
        raise ResultPackageInvalidError(
            f"normalized.npz is not readable: {exc}", subject="normalized.npz"
        ) from exc
    digest = content_sha256(arrays)
    if digest != expected_sha256:
        raise ResultPackageInvalidError(
            "normalized.npz does not reproduce the manifest's normalizedSha256",
            subject="normalized.npz",
        )
    return arrays


def str_array(values: list[str]) -> npt.NDArray[np.str_]:
    return np.asarray(values, dtype=str) if values else np.asarray([], dtype="<U1")


def finite_or_none(value: float) -> float | None:
    return None if not np.isfinite(value) else float(value)
