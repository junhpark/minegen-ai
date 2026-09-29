"""Result persistence OUTSIDE ``derived/*`` (directive §15–§20, §82–§83,
rule 215).

    data/scenarios/{id}/results/<resultId>/
        manifest.json      MineResultManifest
        normalized.npz     canonical arrays (digest in the manifest)
        source.zip         the imported package, byte for byte (raw evidence)

A result folder is published ATOMICALLY: every file is written into a
temporary sibling directory through the shared ``core/publication.py``
write authority, fsynced, and the directory is renamed into place; a
concurrent identical import finds the folder already present and keeps it
(one atomic result per id). Reading is READ ≠ TRUST: a manifest
that does not validate, a digest that does not reproduce or a missing
member is a typed RESULT_PACKAGE_INVALID. Results are never a design
fingerprint input and no mine operation deletes them.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from minegen.core.publication import (  # the ONE write authority (AC-01F.2)
    _fsync_directory,
    publish_bytes,
)
from minegen.results.errors import (
    ResultNotFoundError,
    ResultPackageInvalidError,
    ResultPublicationFailedError,
)
from minegen.results.models import MineResultManifest
from minegen.results.normalization import NormalizedResult, load_npz
from minegen.services.scenario_service import ScenarioStore

RESULTS_DIR = "results"
MANIFEST_FILE = "manifest.json"
NORMALIZED_FILE = "normalized.npz"
SOURCE_FILE = "source.zip"
_RESULT_ID = re.compile(r"^[0-9a-f]{16}$")


@dataclass(frozen=True)
class StoredResult:
    result_id: str
    manifest: MineResultManifest
    path: Path


class ResultStore:
    def __init__(self, scenarios: ScenarioStore) -> None:
        self.scenarios = scenarios

    def results_dir(self, scenario_id: str) -> Path:
        return self.scenarios.scenario_dir(scenario_id) / RESULTS_DIR

    def result_dir(self, scenario_id: str, result_id: str) -> Path:
        if not _RESULT_ID.match(result_id):
            raise ResultNotFoundError(f"result {result_id!r} does not exist", subject=result_id)
        return self.results_dir(scenario_id) / result_id

    # -- read ----------------------------------------------------------------- #

    def list_ids(self, scenario_id: str) -> list[str]:
        root = self.results_dir(scenario_id)
        if not root.is_dir():
            return []
        return sorted(p.name for p in root.iterdir() if p.is_dir() and _RESULT_ID.match(p.name))

    def read_manifest(self, scenario_id: str, result_id: str) -> StoredResult:
        path = self.result_dir(scenario_id, result_id)
        if not path.is_dir():
            raise ResultNotFoundError(f"result {result_id!r} does not exist", subject=result_id)
        manifest_path = path / MANIFEST_FILE
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ResultPackageInvalidError(
                "stored result has no manifest.json", subject=result_id
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
            raise ResultPackageInvalidError(
                f"stored manifest.json is not readable: {exc}", subject=result_id
            ) from exc
        try:
            manifest = MineResultManifest.model_validate(raw)
        except ValidationError as exc:
            first = exc.errors()[0]
            raise ResultPackageInvalidError(
                f"stored manifest.json does not validate: {first['msg']} at {list(first['loc'])}",
                subject=result_id,
            ) from exc
        if manifest.result_id != result_id:
            raise ResultPackageInvalidError(
                f"stored manifest names resultId {manifest.result_id!r} in folder {result_id!r}",
                subject=result_id,
            )
        return StoredResult(result_id=result_id, manifest=manifest, path=path)

    def read_normalized(self, stored: StoredResult) -> NormalizedResult:
        try:
            data = (stored.path / NORMALIZED_FILE).read_bytes()
        except OSError as exc:
            raise ResultPackageInvalidError(
                f"stored normalized.npz is not readable: {exc}", subject=stored.result_id
            ) from exc
        return load_npz(data, expected_sha256=stored.manifest.normalized_sha256)

    def read_source(self, stored: StoredResult) -> bytes:
        try:
            return (stored.path / SOURCE_FILE).read_bytes()
        except OSError as exc:
            raise ResultPackageInvalidError(
                f"stored source.zip is not readable: {exc}", subject=stored.result_id
            ) from exc

    # -- write ---------------------------------------------------------------- #

    def publish(
        self,
        scenario_id: str,
        result_id: str,
        *,
        manifest_bytes: bytes,
        normalized_bytes: bytes,
        source_bytes: bytes,
    ) -> bool:
        """Atomically install the result folder. Returns True when THIS call
        installed it, False when an identical result (same id) was already
        present — the existing folder is kept untouched."""
        final = self.result_dir(scenario_id, result_id)
        root = self.results_dir(scenario_id)
        root.mkdir(parents=True, exist_ok=True)
        if final.is_dir():
            return False
        temp = root / f".tmp-{result_id}-{uuid.uuid4().hex}"
        try:
            temp.mkdir()
            # every member goes through the shared atomic publication primitive
            # (temp sibling + fsync + os.replace) inside the temp directory,
            # then the whole directory is renamed into place
            for name, data in (
                (MANIFEST_FILE, manifest_bytes),
                (NORMALIZED_FILE, normalized_bytes),
                (SOURCE_FILE, source_bytes),
            ):
                publish_bytes(temp / name, data)
            _fsync_directory(temp)
            try:
                os.rename(temp, final)
            except OSError:
                if final.is_dir():
                    # a concurrent identical import won the rename: keep ONE result
                    shutil.rmtree(temp, ignore_errors=True)
                    return False
                raise
            _fsync_directory(root)
            return True
        except OSError as exc:
            with contextlib.suppress(OSError):
                shutil.rmtree(temp, ignore_errors=True)
            raise ResultPublicationFailedError(
                f"could not publish the result folder: {exc}", subject=result_id
            ) from exc

    def delete(self, scenario_id: str, result_id: str) -> None:
        path = self.result_dir(scenario_id, result_id)
        if not path.is_dir():
            raise ResultNotFoundError(f"result {result_id!r} does not exist", subject=result_id)
        trash = path.parent / f".trash-{result_id}-{uuid.uuid4().hex}"
        try:
            os.rename(path, trash)  # the result disappears atomically
            shutil.rmtree(trash, ignore_errors=True)
            _fsync_directory(path.parent)
        except OSError as exc:
            raise ResultPublicationFailedError(
                f"could not delete the result folder: {exc}", subject=result_id
            ) from exc
