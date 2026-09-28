"""Manifest-driven MineExchange bundle reader (adapter INPUT side).

READ ≠ TRUST at the adapter boundary: the ZIP is checked for safe paths
under the bundle root, ``manifest.json`` is validated against the
``ExchangeManifest`` DTO, every listed file must be present with its declared
SHA-256, no unlisted entry may exist, and the coordinate contract must be
the one the adapters know (``LOCAL_ENU_Z_UP`` metre). A defect is a typed
``MINEEXCHANGE_BUNDLE_INVALID`` (never a KeyError / ValueError escaping the
adapter). Documents are addressed by their bundle path and validated against
their MineExchange DTO on demand; the adapter never reconstructs a file stem.
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
    CoordinateMappingUnsupportedError,
    MineExchangeBundleInvalidError,
    MineExchangeVersionUnsupportedError,
)
from minegen.core.models import ApiModel
from minegen.exchange.bundle import BUNDLE_ROOT, MANIFEST_PATH, safe_relative_path, sha256_hex
from minegen.exchange.models import COORDINATE_FRAME, ExchangeManifest, ExchangeOmission

M = TypeVar("M", bound=ApiModel)

_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def parse_semver(version: str) -> tuple[int, int, int]:
    m = _SEMVER.match(version)
    if m is None:
        raise MineExchangeVersionUnsupportedError(
            f"manifest mineExchangeVersion {version!r} is not MAJOR.MINOR.PATCH"
        )
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def require_version(
    version: str, *, minimum: tuple[int, int, int], below_major: int, supported: str
) -> None:
    """``minimum <= version < below_major.0.0`` or a typed refusal."""
    v = parse_semver(version)
    if v < minimum or v[0] >= below_major:
        raise MineExchangeVersionUnsupportedError(
            f"MineExchange {version} is outside the supported range {supported}"
        )


@dataclass(frozen=True)
class MineExchangeBundle:
    """An integral bundle: validated manifest + payload bytes by path."""

    manifest: ExchangeManifest
    files: dict[str, bytes]

    def has(self, path: str) -> bool:
        return path in self.files

    def file(self, path: str) -> bytes:
        try:
            return self.files[path]
        except KeyError:
            raise MineExchangeBundleInvalidError(f"bundle file {path!r} is not present") from None

    def json(self, path: str) -> Any:
        try:
            return json.loads(self.file(path).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MineExchangeBundleInvalidError(
                f"bundle file {path!r} is not JSON: {exc}"
            ) from exc

    def document(self, path: str, model: type[M]) -> M:
        """The bundle document at ``path`` validated against its DTO."""
        try:
            return model.model_validate(self.json(path))
        except ValidationError as exc:
            first = exc.errors()[0]
            raise MineExchangeBundleInvalidError(
                f"bundle file {path!r} does not match {model.__name__}: "
                f"{first['msg']} at {list(first['loc'])}"
            ) from exc

    def text(self, path: str) -> str:
        try:
            return self.file(path).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MineExchangeBundleInvalidError(f"bundle file {path!r} is not UTF-8") from exc

    def omission(self, group: str) -> ExchangeOmission | None:
        for o in self.manifest.omissions:
            if o.group == group:
                return o
        return None


def read_mine_exchange_bundle(data: bytes) -> MineExchangeBundle:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise MineExchangeBundleInvalidError(f"not a ZIP archive: {exc}") from exc
    prefix = f"{BUNDLE_ROOT}/"
    entries: dict[str, bytes] = {}
    with zf:
        for name in zf.namelist():
            if not name.startswith(prefix) or name.endswith("/"):
                raise MineExchangeBundleInvalidError(
                    f"ZIP entry {name!r} is not a file under {prefix!r}"
                )
            rel = name[len(prefix) :]
            try:
                rel = safe_relative_path(rel)
            except ValueError as exc:
                raise MineExchangeBundleInvalidError(str(exc)) from exc
            if rel in entries:
                raise MineExchangeBundleInvalidError(f"duplicate ZIP entry {rel!r}")
            entries[rel] = zf.read(name)
    if MANIFEST_PATH not in entries:
        raise MineExchangeBundleInvalidError(f"{MANIFEST_PATH} is missing")
    try:
        manifest = ExchangeManifest.model_validate(json.loads(entries[MANIFEST_PATH]))
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as exc:
        raise MineExchangeBundleInvalidError(f"{MANIFEST_PATH} is malformed: {exc}") from exc
    payload = {p: b for p, b in entries.items() if p != MANIFEST_PATH}
    listed: set[str] = set()
    for f in manifest.files:
        if f.path in listed:
            raise MineExchangeBundleInvalidError(f"manifest lists {f.path!r} twice")
        listed.add(f.path)
        if f.path not in payload:
            raise MineExchangeBundleInvalidError(
                f"manifest lists {f.path!r} but it is not in the ZIP"
            )
        if sha256_hex(payload[f.path]) != f.sha256:
            raise MineExchangeBundleInvalidError(f"SHA-256 mismatch for {f.path!r}")
    unlisted = sorted(set(payload) - listed)
    if unlisted:
        raise MineExchangeBundleInvalidError(f"ZIP entries not listed in the manifest: {unlisted}")
    cs = manifest.coordinate_system
    if cs.name != COORDINATE_FRAME or cs.unit != "metre" or manifest.units.get("length") != "metre":
        raise CoordinateMappingUnsupportedError(
            f"bundle coordinate contract {cs.name} / {cs.unit} is not the "
            f"{COORDINATE_FRAME} metre contract the adapters translate from"
        )
    return MineExchangeBundle(manifest=manifest, files=payload)
