"""Shared helpers for the Phase 23B adapter tests: unzip an adapter package,
read its manifest / CSV tables, and re-hash a mutated MineExchange bundle so
the adapter's OWN checks (not the integrity gate) are exercised."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from typing import Any

from minegen.adapters.package import MANIFEST_PATH
from minegen.exchange.bundle import BUNDLE_ROOT
from minegen.exchange.formats.csv_table import read_csv


def unzip(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        root = names[0].split("/", 1)[0]
        assert all(n.startswith(root + "/") for n in names)
        return {n.split("/", 1)[1]: zf.read(n) for n in names}


def package_root(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return zf.namelist()[0].split("/", 1)[0]


def manifest(files: dict[str, bytes]) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(files[MANIFEST_PATH])
    return doc


def table(files: dict[str, bytes], path: str) -> tuple[list[str], list[dict[str, str]]]:
    header, rows = read_csv(files[path].decode("utf-8"))
    return header, [dict(zip(header, r, strict=True)) for r in rows]


def bundle_files(bundle: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(bundle)) as zf:
        return {n[len(BUNDLE_ROOT) + 1 :]: zf.read(n) for n in zf.namelist()}


def bundle_manifest(bundle: bytes) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(bundle_files(bundle)["manifest.json"])
    return doc


def rehashed(bundle: bytes, changes: dict[str, bytes], *, manifest_edit: Any = None) -> bytes:
    """Replace bundle files and re-hash their manifest entries (so the
    integrity gate passes and the adapter's own validation is reached).
    ``manifest_edit(doc)`` may further edit the manifest document."""
    entries = bundle_files(bundle)
    doc = json.loads(entries["manifest.json"])
    for path, data in changes.items():
        entries[path] = data
        for f in doc["files"]:
            if f["path"] == path:
                f["sha256"] = hashlib.sha256(data).hexdigest()
    if manifest_edit is not None:
        manifest_edit(doc)
    entries["manifest.json"] = json.dumps(doc).encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n in sorted(entries):
            zf.writestr(f"{BUNDLE_ROOT}/{n}", entries[n])
    return buf.getvalue()


def edited_network(bundle: bytes, edit: Any) -> bytes:
    net = json.loads(bundle_files(bundle)["topology/network.json"])
    edit(net)
    return rehashed(bundle, {"topology/network.json": json.dumps(net).encode("utf-8")})
