"""MineResult package reader — bounded, typed, READ ≠ TRUST (directive §21,
§43, §45, §95).

A result package is a ZIP of ``result_manifest.json`` plus the domain's CSV
files (the round-trip kit shape, or a canonical MineResult export). Members
may sit at the ZIP root or under ONE common top-level directory. Every
budget is an explicit constant; a package outside them is
``RESULT_LIMIT_EXCEEDED``; an unsafe, duplicate, unknown or non-UTF-8
member, a missing required file or a malformed manifest is
``RESULT_PACKAGE_INVALID``. Vendor project files are never parsed.
"""

from __future__ import annotations

import csv
import io
import json
import math
import posixpath
import zipfile
from dataclasses import dataclass

from pydantic import ValidationError

from minegen.exchange.bundle import BundlePathError, safe_relative_path
from minegen.results.errors import (
    ResultDataInvalidError,
    ResultLimitExceededError,
    ResultPackageInvalidError,
    ResultVersionUnsupportedError,
)
from minegen.results.models import MINE_RESULT_VERSION, ResultPackageManifest

MANIFEST_MEMBER = "result_manifest.json"
#: members every package may carry beside the domain files
OPTIONAL_MEMBERS = frozenset({"README.txt", "manifest.json"})

#: explicit input budgets (directive §45) — sized on the acceptance fixtures
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_ZIP_MEMBERS = 32
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_ROWS_PER_FILE = 1_000_000
MAX_AGENTS = 5_000
MAX_UNIQUE_TIMES = 100_000
MAX_CSV_LINE_BYTES = 64 * 1024


@dataclass(frozen=True)
class ResultPackage:
    manifest: ResultPackageManifest
    #: member name (relative, prefix stripped) → bytes
    files: dict[str, bytes]
    #: the top-level directory that was stripped, or ""
    prefix: str

    def has(self, name: str) -> bool:
        return name in self.files

    def text(self, name: str) -> str:
        try:
            return self.files[name].decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ResultPackageInvalidError("member is not valid UTF-8 text", subject=name) from exc


def read_result_package(data: bytes, *, allowed_members: frozenset[str]) -> ResultPackage:
    """Open, budget-check and validate a result ZIP. ``allowed_members`` are
    the domain's file names (required + optional); anything else beside the
    manifest, README and a canonical ``manifest.json`` is refused."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ResultLimitExceededError(
            f"upload is {len(data)} bytes; the limit is {MAX_UPLOAD_BYTES}", subject="upload"
        )
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ResultPackageInvalidError(f"not a ZIP archive: {exc}", subject="package") from exc
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if not infos:
            raise ResultPackageInvalidError("the archive carries no file", subject="package")
        if len(infos) > MAX_ZIP_MEMBERS:
            raise ResultLimitExceededError(
                f"{len(infos)} members; the limit is {MAX_ZIP_MEMBERS}", subject="package"
            )
        total = 0
        for info in infos:
            if info.file_size > MAX_MEMBER_BYTES:
                raise ResultLimitExceededError(
                    f"member declares {info.file_size} bytes; the limit is {MAX_MEMBER_BYTES}",
                    subject=info.filename,
                )
            total += info.file_size
        if total > MAX_UNCOMPRESSED_BYTES:
            raise ResultLimitExceededError(
                f"members declare {total} uncompressed bytes; the limit is "
                f"{MAX_UNCOMPRESSED_BYTES}",
                subject="package",
            )
        names: list[str] = []
        for info in infos:
            try:
                rel = safe_relative_path(info.filename)
            except BundlePathError as exc:
                raise ResultPackageInvalidError(str(exc), subject=info.filename) from exc
            names.append(rel)
        prefix = _common_prefix(names)
        files: dict[str, bytes] = {}
        for info, rel in zip(infos, names, strict=True):
            member = rel[len(prefix) :] if prefix else rel
            if not member or "/" in member:
                raise ResultPackageInvalidError(
                    "members must be flat files at the package root (or under one top-level "
                    "directory)",
                    subject=info.filename,
                )
            if member in files:
                raise ResultPackageInvalidError("duplicate member", subject=member)
            try:
                payload = zf.read(info)
            except (zipfile.BadZipFile, RuntimeError, EOFError, OSError) as exc:
                raise ResultPackageInvalidError(
                    f"member cannot be read: {exc}", subject=member
                ) from exc
            if len(payload) != info.file_size or len(payload) > MAX_MEMBER_BYTES:
                raise ResultLimitExceededError(
                    "member size disagrees with its declaration", subject=member
                )
            files[member] = payload
    if MANIFEST_MEMBER not in files:
        raise ResultPackageInvalidError("missing required file", subject=MANIFEST_MEMBER)
    unknown = sorted(set(files) - allowed_members - OPTIONAL_MEMBERS - {MANIFEST_MEMBER})
    if unknown:
        raise ResultPackageInvalidError(
            f"unknown members {unknown}; a MineResult package carries only its declared files",
            subject="package",
        )
    try:
        raw = json.loads(files[MANIFEST_MEMBER].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResultPackageInvalidError(
            f"not a JSON document: {exc}", subject=MANIFEST_MEMBER
        ) from exc
    if not isinstance(raw, dict):
        raise ResultPackageInvalidError("manifest is not an object", subject=MANIFEST_MEMBER)
    version = raw.get("mineResultVersion")
    if version != MINE_RESULT_VERSION:
        raise ResultVersionUnsupportedError(
            f"mineResultVersion {version!r} is not supported (this MineGen reads "
            f"{MINE_RESULT_VERSION})",
            subject=MANIFEST_MEMBER,
        )
    try:
        manifest = ResultPackageManifest.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise ResultPackageInvalidError(
            f"manifest does not validate: {first['msg']} at {list(first['loc'])}",
            subject=MANIFEST_MEMBER,
        ) from exc
    return ResultPackage(manifest=manifest, files=files, prefix=prefix)


def _common_prefix(names: list[str]) -> str:
    """``dir/`` when EVERY member sits under the same single directory, else ``""``."""
    heads = {n.split("/", 1)[0] if "/" in n else None for n in names}
    if len(heads) == 1 and None not in heads:
        head = next(iter(heads))
        assert head is not None
        return posixpath.join(head, "")
    return ""


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CsvTable:
    name: str
    header: list[str]
    rows: list[list[str]]


def read_csv_member(
    package: ResultPackage, name: str, *, required_columns: tuple[str, ...]
) -> CsvTable:
    """Parse one CSV member: header + rows, bounded, every required column
    present, no duplicate column, every row the header's width."""
    text = package.text(name)
    if any(len(line) > MAX_CSV_LINE_BYTES for line in text.splitlines()):
        raise ResultLimitExceededError(f"a line exceeds {MAX_CSV_LINE_BYTES} bytes", subject=name)
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise ResultPackageInvalidError("empty CSV (no header)", subject=name)
    header = [h.strip() for h in rows[0]]
    if len(set(header)) != len(header):
        raise ResultPackageInvalidError("duplicate column name", subject=name)
    missing = [c for c in required_columns if c not in header]
    if missing:
        raise ResultPackageInvalidError(f"missing required columns {missing}", subject=name)
    body = [r for r in rows[1:] if any(cell.strip() for cell in r)]
    if len(body) > MAX_ROWS_PER_FILE:
        raise ResultLimitExceededError(
            f"{len(body)} rows; the limit is {MAX_ROWS_PER_FILE}", subject=name
        )
    for i, r in enumerate(body):
        if len(r) != len(header):
            raise ResultPackageInvalidError(
                f"row {i + 2} has {len(r)} cells, the header {len(header)}", subject=name
            )
    return CsvTable(name=name, header=header, rows=body)


def parse_float(cell: str, *, name: str, row: int, column: str) -> float | None:
    """A finite float or None for an empty cell; NaN / Inf / text are refused."""
    text = cell.strip()
    if text == "":
        return None
    try:
        value = float(text)
    except ValueError as exc:
        raise ResultDataInvalidError(
            f"row {row}: column {column!r} is not a number ({text!r})", subject=name
        ) from exc
    if not math.isfinite(value):
        raise ResultDataInvalidError(
            f"row {row}: column {column!r} is not finite ({text!r})", subject=name
        )
    return value


def parse_int(cell: str, *, name: str, row: int, column: str) -> int | None:
    text = cell.strip()
    if text == "":
        return None
    value = parse_float(text, name=name, row=row, column=column)
    assert value is not None
    if value != int(value):
        raise ResultDataInvalidError(
            f"row {row}: column {column!r} must be an integer ({text!r})", subject=name
        )
    return int(value)
