"""Deterministic binary STL writer (+ a reader for tests).

STL stores no unit — the manifest declares ``metre``. The 80-byte header
carries informational text only, never authority. Facet normals are computed
from the triangle geometry (right-hand rule on the stored winding).
"""

from __future__ import annotations

import struct

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

_RECORD = np.dtype(
    [
        ("normal", "<f4", (3,)),
        ("v0", "<f4", (3,)),
        ("v1", "<f4", (3,)),
        ("v2", "<f4", (3,)),
        ("attr", "<u2"),
    ]
)


def facet_normals(positions: FloatArray, triangles: IntArray) -> FloatArray:
    p = np.asarray(positions, dtype=np.float64)
    t = np.asarray(triangles, dtype=np.int64)
    n = np.cross(p[t[:, 1]] - p[t[:, 0]], p[t[:, 2]] - p[t[:, 0]])
    length = np.linalg.norm(n, axis=1)
    safe = np.where(length > 0.0, length, 1.0)
    out = n / safe[:, None]
    out[length == 0.0] = 0.0
    return np.asarray(out, dtype=np.float64)


def write_binary_stl(positions: FloatArray, triangles: IntArray, header: str = "") -> bytes:
    """``positions`` (N, 3) float, ``triangles`` (T, 3) int → binary STL."""
    p = np.asarray(positions, dtype=np.float64)
    t = np.asarray(triangles, dtype=np.int64)
    if t.ndim != 2 or t.shape[1] != 3:
        raise ValueError("triangles must be (T, 3)")
    head = header.encode("ascii", "replace")[:80].ljust(80, b"\x00")
    records = np.zeros(int(t.shape[0]), dtype=_RECORD)
    records["normal"] = facet_normals(p, t).astype(np.float32)
    records["v0"] = p[t[:, 0]].astype(np.float32)
    records["v1"] = p[t[:, 1]].astype(np.float32)
    records["v2"] = p[t[:, 2]].astype(np.float32)
    return head + struct.pack("<I", int(t.shape[0])) + records.tobytes()


def read_binary_stl(data: bytes) -> tuple[FloatArray, FloatArray]:
    """→ (triangle vertices (T, 3, 3), facet normals (T, 3)); tests only."""
    if len(data) < 84:
        raise ValueError("not a binary STL")
    (count,) = struct.unpack_from("<I", data, 80)
    expected = 84 + count * _RECORD.itemsize
    if len(data) != expected:
        raise ValueError(f"binary STL length {len(data)} != {expected} for {count} facets")
    records = np.frombuffer(data, dtype=_RECORD, count=count, offset=84)
    tris = np.stack([records["v0"], records["v1"], records["v2"]], axis=1).astype(np.float64)
    return tris, np.asarray(records["normal"], dtype=np.float64)


def concatenate_stl_triangles(
    parts: list[tuple[FloatArray, IntArray]],
) -> tuple[FloatArray, IntArray, list[tuple[int, int]]]:
    """Concatenate independent (positions, triangles) bodies into ONE
    triangle stream WITHOUT a Boolean union: returns the stacked positions,
    the re-indexed triangles and ``(firstTriangle, triangleCount)`` per
    part, in the given order."""
    positions: list[FloatArray] = []
    triangles: list[IntArray] = []
    ranges: list[tuple[int, int]] = []
    v_offset = 0
    t_offset = 0
    for p, t in parts:
        p = np.asarray(p, dtype=np.float64)
        t = np.asarray(t, dtype=np.int64)
        positions.append(p)
        triangles.append(t + v_offset)
        ranges.append((t_offset, int(t.shape[0])))
        v_offset += int(p.shape[0])
        t_offset += int(t.shape[0])
    if not parts:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64), []
    return np.vstack(positions), np.vstack(triangles), ranges
