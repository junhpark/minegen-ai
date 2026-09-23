"""GLB export through the EXISTING deterministic writer (``design/glb_writer``).

Stored vertices stay in the canonical ``LOCAL_ENU_Z_UP`` frame; the root
node carries the explicit MineGen → glTF transform ``(x, y, z) → (x, z, −y)``
(the frontend's ``toThreePositions``), recorded in the manifest as
``transformMatrix``. Core geometry is never re-framed.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.design.glb_writer import write_glb
from minegen.design.tunnel_mesh import RenderMesh, RenderPrimitive

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

#: glTF column-major 4×4: X' = x, Y' = z, Z' = −y
MINE_TO_GLTF_MATRIX: list[float] = [
    1.0,
    0.0,
    0.0,
    0.0,  # column 0: image of e_x
    0.0,
    0.0,
    -1.0,
    0.0,  # column 1: image of e_y → −Z'
    0.0,
    1.0,
    0.0,
    0.0,  # column 2: image of e_z → +Y'
    0.0,
    0.0,
    0.0,
    1.0,
]


def _as_matrix(column_major: list[float]) -> FloatArray:
    return np.asarray(column_major, dtype=np.float64).reshape(4, 4).T


def apply_transform(points: FloatArray, column_major: list[float]) -> FloatArray:
    """Apply a glTF column-major node matrix to (N, 3) points."""
    m = _as_matrix(column_major)
    p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    h = np.hstack([p, np.ones((p.shape[0], 1))])
    return np.asarray((h @ m.T)[:, :3], dtype=np.float64)


def inverse_transform(points: FloatArray, column_major: list[float]) -> FloatArray:
    m = np.linalg.inv(_as_matrix(column_major))
    p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    h = np.hstack([p, np.ones((p.shape[0], 1))])
    return np.asarray((h @ m.T)[:, :3], dtype=np.float64)


def vertex_normals(positions: FloatArray, triangles: IntArray) -> FloatArray:
    """Area-weighted per-vertex normals (display only)."""
    p = np.asarray(positions, dtype=np.float64)
    t = np.asarray(triangles, dtype=np.int64)
    n = np.zeros_like(p)
    face = np.cross(p[t[:, 1]] - p[t[:, 0]], p[t[:, 2]] - p[t[:, 0]])
    for k in range(3):
        np.add.at(n, t[:, k], face)
    length = np.linalg.norm(n, axis=1)
    safe = np.where(length > 0.0, length, 1.0)
    out = n / safe[:, None]
    out[length == 0.0] = [0.0, 0.0, 1.0]
    return np.asarray(out, dtype=np.float64)


def write_mesh_glb(
    positions: FloatArray,
    primitives: list[tuple[str, IntArray, dict[str, Any]]],
    *,
    name: str,
    node_extras: dict[str, Any],
    root_transform: bool = True,
) -> bytes:
    """One vertex set, one primitive per ``(name, triangles, extras)``;
    positions stored in the canonical frame, the root node transformed into
    glTF Y-up when ``root_transform``."""
    p = np.asarray(positions, dtype=np.float64).reshape(-1, 3)
    all_tris = (
        np.vstack([np.asarray(t, dtype=np.int64).reshape(-1, 3) for _, t, _ in primitives])
        if primitives
        else np.zeros((0, 3), dtype=np.int64)
    )
    normals = vertex_normals(p, all_tris) if all_tris.size else np.zeros_like(p)
    mesh = RenderMesh(
        positions=np.ascontiguousarray(p, dtype=np.float32),
        normals=np.ascontiguousarray(normals, dtype=np.float32),
        uvs=np.zeros((p.shape[0], 2), dtype=np.float32),
        primitives=[
            RenderPrimitive(
                name=prim_name,
                extras=dict(extras),
                indices=np.ascontiguousarray(
                    np.asarray(tris, dtype=np.int64).reshape(-1), dtype=np.uint32
                ),
            )
            for prim_name, tris, extras in primitives
        ],
        geometrically_closed=False,
        render_vertex_count=int(p.shape[0]),
    )
    return write_glb(
        mesh,
        generator="minegen-mineexchange-1.0.0",
        name=name,
        node_matrix=MINE_TO_GLTF_MATRIX if root_transform else None,
        node_extras=node_extras,
    )
