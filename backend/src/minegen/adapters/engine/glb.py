"""Deterministic GLB root-transform patcher (directive §44–§46).

MineExchange carries two GLB kinds: exporter-created GLBs whose stored
vertices are ``LOCAL_ENU_Z_UP`` under a root node matrix that already maps
the scene into ``GLTF_Y_UP``, and copied production render GLBs whose
stored vertices are ``LOCAL_ENU_Z_UP`` with NO root transform. The engine
package normalizes the second kind by adding ONE deterministic root node
carrying the mine → glTF matrix ``(x, y, z) → (x, z, −y)`` that parents the
previous scene roots. The binary chunk (vertices, normals, indices) is
copied byte for byte — nothing is re-swept or recomputed — and a GLB whose
scene is already ``GLTF_Y_UP`` is never transformed twice.
"""

from __future__ import annotations

import json
import struct
from typing import Any

from minegen.exchange.formats.glb import MINE_TO_GLTF_MATRIX

_MAGIC = 0x46546C67
_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942
ROOT_NODE_NAME = "MineExchange_LOCAL_ENU_Z_UP_to_GLTF_Y_UP"


class GlbFormatError(ValueError):
    """Not a valid GLB v2 container (the adapter maps it to a typed refusal)."""


def split_glb(data: bytes) -> tuple[dict[str, Any], bytes]:
    """→ (JSON document, BIN chunk bytes) or ``GlbFormatError``."""
    if len(data) < 20:
        raise GlbFormatError("shorter than a GLB header")
    magic, version, length = struct.unpack_from("<III", data, 0)
    if magic != _MAGIC or version != 2 or length != len(data):
        raise GlbFormatError("not a valid GLB v2 container")
    json_len, json_type = struct.unpack_from("<II", data, 12)
    if json_type != _JSON_CHUNK or 20 + json_len > len(data):
        raise GlbFormatError("first chunk is not JSON")
    try:
        doc = json.loads(data[20 : 20 + json_len].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GlbFormatError(f"JSON chunk is not valid JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise GlbFormatError("JSON chunk is not an object")
    off = 20 + json_len
    binary = b""
    if off < len(data):
        if off + 8 > len(data):
            raise GlbFormatError("truncated BIN chunk header")
        bin_len, bin_type = struct.unpack_from("<II", data, off)
        if bin_type != _BIN_CHUNK or off + 8 + bin_len > len(data):
            raise GlbFormatError("second chunk is not BIN")
        binary = data[off + 8 : off + 8 + bin_len]
    return doc, binary


def _pad4(data: bytes, fill: bytes) -> bytes:
    return data + fill * (-len(data) % 4)


def join_glb(doc: dict[str, Any], binary: bytes) -> bytes:
    """Deterministic container: sorted-key compact JSON padded with spaces,
    BIN padded with zeros (the writer convention)."""
    json_bytes = _pad4(json.dumps(doc, separators=(",", ":"), sort_keys=True).encode("utf-8"), b" ")
    bin_padded = _pad4(binary, b"\x00")
    total = 12 + 8 + len(json_bytes) + (8 + len(bin_padded) if binary else 0)
    out = bytearray()
    out += struct.pack("<III", _MAGIC, 2, total)
    out += struct.pack("<II", len(json_bytes), _JSON_CHUNK)
    out += json_bytes
    if binary:
        out += struct.pack("<II", len(bin_padded), _BIN_CHUNK)
        out += bin_padded
    return bytes(out)


def scene_root_nodes(doc: dict[str, Any]) -> list[int]:
    """The root node indices of the default scene (or of every node that no
    other node parents when the GLB declares no scene)."""
    nodes = doc.get("nodes")
    if not isinstance(nodes, list):
        raise GlbFormatError("GLB declares no nodes")
    scenes = doc.get("scenes")
    if isinstance(scenes, list) and scenes:
        idx = doc.get("scene", 0)
        if not isinstance(idx, int) or idx < 0 or idx >= len(scenes):
            raise GlbFormatError("invalid default scene index")
        roots = scenes[idx].get("nodes", [])
    else:
        children = {c for n in nodes if isinstance(n, dict) for c in n.get("children", [])}
        roots = [i for i in range(len(nodes)) if i not in children]
    if not isinstance(roots, list) or not roots:
        raise GlbFormatError("the default scene has no root node")
    for r in roots:
        if not isinstance(r, int) or r < 0 or r >= len(nodes):
            raise GlbFormatError(f"scene root {r!r} is not a node index")
    return [int(r) for r in roots]


def add_root_transform(data: bytes) -> bytes:
    """Re-frame a GLB whose stored vertices are LOCAL_ENU_Z_UP with no root
    transform: ONE new root node with the mine → glTF matrix parents the
    previous scene roots. Nodes, meshes, accessors, extras and the binary
    chunk are preserved untouched. Never call it on a GLB whose scene is
    already GLTF_Y_UP (the caller decides from the MineExchange manifest)."""
    doc, binary = split_glb(data)
    roots = scene_root_nodes(doc)
    nodes = list(doc["nodes"])
    if any(isinstance(n, dict) and n.get("name") == ROOT_NODE_NAME for n in nodes):
        raise GlbFormatError("GLB already carries the MineExchange root transform")
    root_index = len(nodes)
    nodes.append(
        {
            "name": ROOT_NODE_NAME,
            "matrix": list(MINE_TO_GLTF_MATRIX),
            "children": roots,
            "extras": {
                "storedVertexFrame": "LOCAL_ENU_Z_UP",
                "sceneFrame": "GLTF_Y_UP",
                "addedBy": "minegen-engine-package",
            },
        }
    )
    new_doc = dict(doc)
    new_doc["nodes"] = nodes
    scenes = doc.get("scenes")
    if isinstance(scenes, list) and scenes:
        idx = int(doc.get("scene", 0))
        new_scenes = [dict(s) for s in scenes]
        new_scenes[idx] = {**new_scenes[idx], "nodes": [root_index]}
        new_doc["scenes"] = new_scenes
    else:
        new_doc["scenes"] = [{"nodes": [root_index]}]
        new_doc["scene"] = 0
    return join_glb(new_doc, binary)
