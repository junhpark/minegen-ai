"""Deterministic adapter package writer (directive §9): the MineExchange
bundle rules — fixed ZIP timestamps, lexicographic paths, fixed DEFLATE,
SHA-256 per output file, safe relative paths, duplicate-path rejection, no
wall-clock value in the semantic manifest. Same input bundle + same
configuration → byte-identical output ZIP."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from typing import Any

from minegen.adapters.contracts import AdapterGeneratedFile, AdapterManifest
from minegen.adapters.errors import AdapterConversionFailedError
from minegen.exchange.bundle import safe_relative_path, sha256_hex
from minegen.exchange.formats.json_document import dumps

MANIFEST_PATH = "adapter_manifest.json"
README_PATH = "README.txt"
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_MEDIA_BY_SUFFIX: dict[str, str] = {
    "dxf": "application/dxf",
    "csv": "text/csv",
    "json": "application/json",
    "txt": "text/plain",
    "glb": "model/gltf-binary",
    "stl": "model/stl",
    "obj": "model/obj",
}


@dataclass(frozen=True)
class AdapterPackage:
    zip_bytes: bytes
    manifest: AdapterManifest


@dataclass
class PackageBuilder:
    """Collects the files of one adapter package and writes the ZIP with the
    manifest LAST (the manifest lists every other file with its hash)."""

    root: str
    adapter: str
    files: dict[str, bytes] = field(default_factory=dict)
    generated: list[AdapterGeneratedFile] = field(default_factory=list)

    def add(
        self,
        path: str,
        data: bytes,
        *,
        target_semantic: str,
        source_files: list[str],
        source_entity_ids: list[str] | None = None,
        media_type: str | None = None,
    ) -> None:
        try:
            path = safe_relative_path(path)
        except ValueError as exc:
            raise AdapterConversionFailedError(
                str(exc), adapter=self.adapter, subject=path
            ) from exc
        if path in self.files or path == MANIFEST_PATH:
            raise AdapterConversionFailedError(
                "duplicate package path", adapter=self.adapter, subject=path
            )
        suffix = path.rsplit(".", 1)[-1].lower()
        media = media_type or _MEDIA_BY_SUFFIX.get(suffix)
        if media is None:
            raise AdapterConversionFailedError(
                "no media type for the package file", adapter=self.adapter, subject=path
            )
        self.files[path] = data
        self.generated.append(
            AdapterGeneratedFile(
                path=path,
                media_type=media,
                target_semantic=target_semantic,
                source_entity_ids=list(source_entity_ids or []),
                source_files=list(source_files),
                sha256=sha256_hex(data),
            )
        )

    def finish(self, manifest_fields: dict[str, Any]) -> AdapterPackage:
        manifest = AdapterManifest(
            generated_files=sorted(self.generated, key=lambda f: f.path), **manifest_fields
        )
        payload = dict(self.files)
        payload[MANIFEST_PATH] = dumps(manifest.model_dump(mode="json", by_alias=True))
        return AdapterPackage(zip_bytes=write_package(self.root, payload), manifest=manifest)


def write_package(root: str, files: dict[str, bytes]) -> bytes:
    root = safe_relative_path(root)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path in sorted(files):
            info = zipfile.ZipInfo(f"{root}/{safe_relative_path(path)}", date_time=_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o644 & 0xFFFF) << 16
            info.create_system = 3
            zf.writestr(info, files[path], compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
    return buf.getvalue()
