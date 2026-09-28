"""Deterministic adapter package ZIP (same rules as the MineExchange bundle:
lexicographic entry order, fixed entry timestamp, fixed DEFLATE settings,
normalized relative paths under one root, no wall-clock value)."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Mapping

from minegen.exchange.bundle import safe_relative_path

_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def write_package(root: str, files: Mapping[str, bytes]) -> bytes:
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
