"""Generic triangle-mesh QA for exported bodies (closed-solid contract).

Measured, never assumed: finite vertices, valid indices, degenerate
triangles, edge-manifoldness (every undirected edge in exactly two
triangles), watertightness (no boundary edge), consistent orientation
(every undirected edge seen once in each direction) and the signed volume
(divergence theorem; > 0 = outward winding). Independent of the mesh's
origin so orebody meshes, terrain surfaces and logical sweeps are judged
by the same code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

DEGENERATE_AREA = 1e-12


@dataclass
class MeshQa:
    vertex_count: int
    triangle_count: int
    finite: bool
    valid_indices: bool
    degenerate_triangles: int
    manifold: bool
    watertight: bool
    consistent_orientation: bool
    boundary_edges: int
    signed_volume: float
    problems: list[str] = field(default_factory=list)

    @property
    def closed_solid(self) -> bool:
        return (
            self.finite
            and self.valid_indices
            and self.degenerate_triangles == 0
            and self.manifold
            and self.watertight
            and self.consistent_orientation
            and self.signed_volume > 0.0
        )


def mesh_qa(positions: FloatArray, triangles: IntArray) -> MeshQa:
    p = np.asarray(positions, dtype=np.float64).reshape(-1, 3)
    t = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
    problems: list[str] = []
    finite = bool(np.isfinite(p).all())
    if not finite:
        problems.append("non-finite vertex coordinates")
    valid = bool(t.size == 0 or (t.min() >= 0 and t.max() < p.shape[0]))
    if not valid:
        problems.append("triangle index out of range")
    if not (finite and valid):
        return MeshQa(
            int(p.shape[0]),
            int(t.shape[0]),
            finite,
            valid,
            0,
            False,
            False,
            False,
            0,
            0.0,
            problems,
        )
    same = (t[:, 0] == t[:, 1]) | (t[:, 1] == t[:, 2]) | (t[:, 0] == t[:, 2])
    area2 = np.linalg.norm(np.cross(p[t[:, 1]] - p[t[:, 0]], p[t[:, 2]] - p[t[:, 0]]), axis=1)
    degenerate = int((same | (area2 < 2.0 * DEGENERATE_AREA)).sum())
    if degenerate:
        problems.append(f"{degenerate} degenerate triangles")
    # directed edges (a→b) of every triangle
    directed = np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]], axis=0)
    undirected = np.sort(directed, axis=1)
    keys = undirected[:, 0] * (p.shape[0] + 1) + undirected[:, 1]
    _, inverse, counts = np.unique(keys, return_inverse=True, return_counts=True)
    per_edge = counts[inverse]
    manifold = bool((counts <= 2).all())
    boundary = int((counts == 1).sum())
    watertight = bool(boundary == 0) and manifold
    if not manifold:
        problems.append(f"{int((counts > 2).sum())} non-manifold edges")
    if boundary:
        problems.append(f"{boundary} boundary edges")
    # orientation: on a manifold interior edge the two directed copies must
    # be opposite — i.e. no directed edge may appear twice
    dkeys = directed[:, 0] * (p.shape[0] + 1) + directed[:, 1]
    _, dcounts = np.unique(dkeys, return_counts=True)
    consistent = bool((dcounts == 1).all()) and manifold
    if not consistent:
        problems.append("inconsistent triangle orientation")
    del per_edge
    volume = float(np.einsum("ij,ij->i", p[t[:, 0]], np.cross(p[t[:, 1]], p[t[:, 2]])).sum() / 6.0)
    if watertight and consistent and volume <= 0.0:
        problems.append(f"signed volume {volume:.6g} is not positive (inward winding)")
    return MeshQa(
        int(p.shape[0]),
        int(t.shape[0]),
        finite,
        valid,
        degenerate,
        manifold,
        watertight,
        consistent,
        boundary,
        volume,
        problems,
    )
