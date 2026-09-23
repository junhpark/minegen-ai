"""Deterministic JSON documents: sorted keys, fixed indentation, UTF-8, no
NaN / infinity (rule 34)."""

from __future__ import annotations

import json
from typing import Any


def dumps(document: Any) -> bytes:
    return (
        json.dumps(document, sort_keys=True, indent=1, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode("utf-8")
