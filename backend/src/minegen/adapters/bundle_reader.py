"""Manifest-driven MineExchange bundle reader — the adapters' ONLY mine
input (directive §3–§5, rule 207).

READ ≠ TRUST at the adapter boundary: the ZIP is checked for safe paths
under the bundle root, ``manifest.json`` is validated against the
``ExchangeManifest`` DTO, every listed file must be present with its declared
SHA-256, no unlisted entry may exist, and the coordinate contract must be
the one the adapters know (``LOCAL_ENU_Z_UP`` metre). A defect is a typed
``ADAPTER_MINEEXCHANGE_BUNDLE_INVALID``. Files, entities, semantic types,
DXF handles and omissions are looked up through the MANIFEST — a file name
is never guessed and a handle is never re-derived by parsing.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import ValidationError

from minegen.adapters.errors import (
    MineExchangeBundleInvalidError,
    MineExchangeVersionUnsupportedError,
)
from minegen.core.models import ApiModel
from minegen.exchange.bundle import BUNDLE_ROOT, MANIFEST_PATH, safe_relative_path, sha256_hex
from minegen.exchange.models import (
    COORDINATE_FRAME,
    ExchangeEntity,
    ExchangeFile,
    ExchangeManifest,
    ExchangeOmission,
)

M = TypeVar("M", bound=ApiModel)
_READER = "BUNDLE_READER"
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def parse_semver(version: str, *, adapter: str = _READER) -> tuple[int, int, int]:
    m = _SEMVER.match(version)
    if m is None:
        raise MineExchangeVersionUnsupportedError(
            f"manifest mineExchangeVersion {version!r} is not MAJOR.MINOR.PATCH",
            adapter=adapter,
            subject="manifest.mineExchangeVersion",
        )
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def require_version(
    version: str,
    *,
    adapter: str,
    minimum: tuple[int, int, int],
    below_major: int,
    supported: str,
) -> None:
    """``minimum <= version < below_major.0.0`` or a typed refusal."""
    v = parse_semver(version, adapter=adapter)
    if v < minimum or v[0] >= below_major:
        raise MineExchangeVersionUnsupportedError(
            f"MineExchange {version} is outside the supported range {supported}",
            adapter=adapter,
            subject="manifest.mineExchangeVersion",
        )


@dataclass(frozen=True)
class MineExchangeBundle:
    """An integral bundle: validated manifest + payload bytes by path."""

    manifest: ExchangeManifest
    files: dict[str, bytes]

    # -- manifest authorities ------------------------------------------------- #

    @property
    def version(self) -> str:
        return self.manifest.mine_exchange_version

    @property
    def entries(self) -> dict[str, ExchangeFile]:
        return {f.path: f for f in self.manifest.files}

    @property
    def entities(self) -> dict[str, ExchangeEntity]:
        return {e.entity_id: e for e in self.manifest.entities}

    def files_of(self, semantic_type: str) -> list[ExchangeFile]:
        return [f for f in self.manifest.files if f.semantic_type == semantic_type]

    def file_entry(self, path: str) -> ExchangeFile:
        entry = self.entries.get(path)
        if entry is None:
            raise MineExchangeBundleInvalidError(
                "not listed in the manifest", adapter=_READER, subject=path
            )
        return entry

    def omission(self, group: str) -> ExchangeOmission | None:
        for o in self.manifest.omissions:
            if o.group == group:
                return o
        return None

    def dxf_handles(self, path: str) -> dict[str, dict[str, str]]:
        """``handle → {entityId, layer, entityType}`` of a DXF from the
        MANIFEST (``files[].dxfEntities``), never from parsing the file."""
        entry = self.file_entry(path)
        if not entry.dxf_entities:
            raise MineExchangeBundleInvalidError(
                "manifest carries no dxfEntities handle table", adapter=_READER, subject=path
            )
        out: dict[str, dict[str, str]] = {}
        for row in entry.dxf_entities:
            handle = row.get("handle")
            if not handle or handle in out:
                raise MineExchangeBundleInvalidError(
                    f"dxfEntities handle {handle!r} missing or duplicated",
                    adapter=_READER,
                    subject=path,
                )
            out[handle] = dict(row)
        return out

    # -- payload --------------------------------------------------------------- #

    def has(self, path: str) -> bool:
        return path in self.files

    def file(self, path: str) -> bytes:
        try:
            return self.files[path]
        except KeyError:
            raise MineExchangeBundleInvalidError(
                "file is not present in the bundle", adapter=_READER, subject=path
            ) from None

    def json(self, path: str) -> Any:
        try:
            return json.loads(self.file(path).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MineExchangeBundleInvalidError(
                f"not a JSON document: {exc}", adapter=_READER, subject=path
            ) from exc

    def document(self, path: str, model: type[M]) -> M:
        """The bundle document at ``path`` validated against its DTO."""
        try:
            return model.model_validate(self.json(path))
        except ValidationError as exc:
            first = exc.errors()[0]
            raise MineExchangeBundleInvalidError(
                f"does not match {model.__name__}: {first['msg']} at {list(first['loc'])}",
                adapter=_READER,
                subject=path,
            ) from exc

    def text(self, path: str) -> str:
        try:
            return self.file(path).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MineExchangeBundleInvalidError(
                "not UTF-8 text", adapter=_READER, subject=path
            ) from exc


def read_mine_exchange_bundle(data: bytes) -> MineExchangeBundle:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise MineExchangeBundleInvalidError(
            f"not a ZIP archive: {exc}", adapter=_READER, subject="bundle"
        ) from exc
    prefix = f"{BUNDLE_ROOT}/"
    entries: dict[str, bytes] = {}
    with zf:
        for name in zf.namelist():
            if not name.startswith(prefix) or name.endswith("/"):
                raise MineExchangeBundleInvalidError(
                    f"ZIP entry is not a file under {prefix!r}", adapter=_READER, subject=name
                )
            rel = name[len(prefix) :]
            try:
                rel = safe_relative_path(rel)
            except ValueError as exc:
                raise MineExchangeBundleInvalidError(
                    str(exc), adapter=_READER, subject=name
                ) from exc
            if rel in entries:
                raise MineExchangeBundleInvalidError(
                    "duplicate ZIP entry", adapter=_READER, subject=rel
                )
            entries[rel] = zf.read(name)
    if MANIFEST_PATH not in entries:
        raise MineExchangeBundleInvalidError(
            "manifest.json is missing", adapter=_READER, subject=MANIFEST_PATH
        )
    try:
        manifest = ExchangeManifest.model_validate(json.loads(entries[MANIFEST_PATH]))
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as exc:
        raise MineExchangeBundleInvalidError(
            f"malformed manifest: {exc}", adapter=_READER, subject=MANIFEST_PATH
        ) from exc
    payload = {p: b for p, b in entries.items() if p != MANIFEST_PATH}
    listed: set[str] = set()
    for f in manifest.files:
        if f.path in listed:
            raise MineExchangeBundleInvalidError(
                "listed twice in the manifest", adapter=_READER, subject=f.path
            )
        listed.add(f.path)
        if f.path not in payload:
            raise MineExchangeBundleInvalidError(
                "listed in the manifest but not in the ZIP", adapter=_READER, subject=f.path
            )
        if sha256_hex(payload[f.path]) != f.sha256:
            raise MineExchangeBundleInvalidError(
                "SHA-256 mismatch against the manifest", adapter=_READER, subject=f.path
            )
    unlisted = sorted(set(payload) - listed)
    if unlisted:
        raise MineExchangeBundleInvalidError(
            "ZIP entries not listed in the manifest", adapter=_READER, subject=", ".join(unlisted)
        )
    ids: set[str] = set()
    for e in manifest.entities:
        if e.entity_id in ids:
            raise MineExchangeBundleInvalidError(
                "duplicate entity id in the manifest", adapter=_READER, subject=e.entity_id
            )
        ids.add(e.entity_id)
        for path in e.files:
            if path not in listed:
                raise MineExchangeBundleInvalidError(
                    f"entity file {path!r} is not a listed bundle file",
                    adapter=_READER,
                    subject=e.entity_id,
                )
    cs = manifest.coordinate_system
    if cs.name != COORDINATE_FRAME or cs.unit != "metre" or manifest.units.get("length") != "metre":
        raise MineExchangeBundleInvalidError(
            f"coordinate contract {cs.name} / {cs.unit} is not the {COORDINATE_FRAME} metre "
            "contract the adapters translate from",
            adapter=_READER,
            subject="manifest.coordinateSystem",
        )
    return MineExchangeBundle(manifest=manifest, files=payload)
