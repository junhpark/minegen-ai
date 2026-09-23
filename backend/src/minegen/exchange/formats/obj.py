"""Deterministic Wavefront OBJ writer (geometry only: ``o``, ``v``, ``f``;
no materials / textures in v1) plus a reader for tests. Coordinates are
written with Python's shortest round-trip float representation."""

from __future__ import annotations

import re

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]


def sanitize_name(name: str) -> str:
    """OBJ object names: no whitespace; everything else kept (``:`` is
    common in the stable entity ids and is legal in ``o`` names)."""
    return re.sub(r"\s+", "_", name.strip()) or "object"


def write_obj(positions: FloatArray, triangles: IntArray, object_name: str) -> str:
    p = np.asarray(positions, dtype=np.float64)
    t = np.asarray(triangles, dtype=np.int64)
    lines = [
        "# MineExchange OBJ — LOCAL_ENU_Z_UP metres (see manifest.json)",
        f"o {sanitize_name(object_name)}",
    ]
    lines.extend(f"v {x!r} {y!r} {z!r}" for x, y, z in p.tolist())
    lines.extend(f"f {a + 1} {b + 1} {c + 1}" for a, b, c in t.tolist())
    return "\n".join(lines) + "\n"


def read_obj(text: str) -> tuple[FloatArray, IntArray, str | None]:
    verts: list[list[float]] = []
    faces: list[list[int]] = []
    name: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0] == "o":
            name = parts[1] if len(parts) > 1 else ""
        elif parts[0] == "v":
            verts.append([float(v) for v in parts[1:4]])
        elif parts[0] == "f":
            faces.append([int(v.split("/")[0]) - 1 for v in parts[1:4]])
    return (
        np.asarray(verts, dtype=np.float64).reshape(-1, 3),
        np.asarray(faces, dtype=np.int64).reshape(-1, 3),
        name,
    )
