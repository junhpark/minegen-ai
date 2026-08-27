"""Minimal deterministic binary-glTF (GLB) writer (rules 16/67).

Phase 06 needs only: header + JSON chunk + BIN chunk, a single mesh with one
vertex set (POSITION/NORMAL/TEXCOORD_0) and one indexed primitive per tunnel
segment plus the removable caps. A tiny ``struct + json + numpy`` writer is
simpler and more transparent than a new glTF dependency, and byte-for-byte
deterministic for identical input (sorted JSON keys, fixed padding).
"""

from __future__ import annotations

import json
import struct

import numpy as np

from minegen.design.tunnel_mesh import RenderMesh

_MAGIC = 0x46546C67
_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942
_ARRAY_BUFFER = 34962
_ELEMENT_ARRAY_BUFFER = 34963
_FLOAT = 5126
_UNSIGNED_INT = 5125


def write_glb(mesh: RenderMesh, *, generator: str = "minegen-phase06") -> bytes:
    def pad4(data: bytes, fill: bytes) -> bytes:
        return data + fill * (-len(data) % 4)

    pos = np.ascontiguousarray(mesh.positions, dtype=np.float32)
    nrm = np.ascontiguousarray(mesh.normals, dtype=np.float32)
    uv = np.ascontiguousarray(mesh.uvs, dtype=np.float32)
    n = int(pos.shape[0])

    blobs: list[bytes] = []
    views: list[dict[str, object]] = []
    offset = 0

    def add_view(data: bytes, target: int) -> int:
        nonlocal offset
        padded = pad4(data, b"\x00")
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(data), "target": target})
        blobs.append(padded)
        offset += len(padded)
        return len(views) - 1

    accessors: list[dict[str, object]] = [
        {
            "bufferView": add_view(pos.tobytes(), _ARRAY_BUFFER),
            "componentType": _FLOAT,
            "count": n,
            "type": "VEC3",
            "min": [float(v) for v in pos.min(axis=0)],
            "max": [float(v) for v in pos.max(axis=0)],
        },
        {
            "bufferView": add_view(nrm.tobytes(), _ARRAY_BUFFER),
            "componentType": _FLOAT,
            "count": n,
            "type": "VEC3",
        },
        {
            "bufferView": add_view(uv.tobytes(), _ARRAY_BUFFER),
            "componentType": _FLOAT,
            "count": n,
            "type": "VEC2",
        },
    ]
    primitives: list[dict[str, object]] = []
    for prim in mesh.primitives:
        idx = np.ascontiguousarray(prim.indices, dtype=np.uint32)
        acc = len(accessors)
        accessors.append(
            {
                "bufferView": add_view(idx.tobytes(), _ELEMENT_ARRAY_BUFFER),
                "componentType": _UNSIGNED_INT,
                "count": int(idx.shape[0]),
                "type": "SCALAR",
            }
        )
        primitives.append(
            {
                "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
                "indices": acc,
                "mode": 4,
                "extras": prim.extras,
            }
        )

    binary = b"".join(blobs)
    doc = {
        "asset": {"version": "2.0", "generator": generator},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": views,
        "accessors": accessors,
        "meshes": [{"name": "tunnel", "primitives": primitives}],
        "nodes": [{"mesh": 0, "name": "tunnel"}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    json_bytes = pad4(json.dumps(doc, separators=(",", ":"), sort_keys=True).encode("utf-8"), b" ")
    total = 12 + 8 + len(json_bytes) + 8 + len(binary) + (-len(binary) % 4)
    out = bytearray()
    out += struct.pack("<III", _MAGIC, 2, total)
    out += struct.pack("<II", len(json_bytes), _JSON_CHUNK)
    out += json_bytes
    bin_padded = pad4(binary, b"\x00")
    out += struct.pack("<II", len(bin_padded), _BIN_CHUNK)
    out += bin_padded
    return bytes(out)


def read_glb(data: bytes) -> tuple[dict[str, object], bytes]:
    """Parse a GLB back into (json document, binary chunk) — used by tests to
    verify the artifact without a glTF dependency."""
    magic, version, length = struct.unpack_from("<III", data, 0)
    if magic != _MAGIC or version != 2 or length != len(data):
        raise ValueError("not a valid GLB v2 container")
    json_len, json_type = struct.unpack_from("<II", data, 12)
    if json_type != _JSON_CHUNK:
        raise ValueError("first chunk is not JSON")
    doc: dict[str, object] = json.loads(data[20 : 20 + json_len].decode("utf-8"))
    off = 20 + json_len
    bin_len, bin_type = struct.unpack_from("<II", data, off)
    if bin_type != _BIN_CHUNK:
        raise ValueError("second chunk is not BIN")
    binary = data[off + 8 : off + 8 + bin_len]
    return doc, binary
