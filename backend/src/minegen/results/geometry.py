"""Result geometry: the MineExchange edge centerlines a result is bound to,
and the deterministic chainage → XYZ projection (directive §36–§37).

The polylines are the SOURCE snapshot's exported centerlines (chainage 0 at
the edge's ``sourceNodeId`` end = first point, 1 at ``targetNodeId`` = last
point). A projected XYZ is a visualization derivative, never an authority.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class EdgeGeometry:
    edge_id: str
    edge_type: str
    source_node_id: str
    target_node_id: str
    geometry_entity_id: str
    points: FloatArray  # (N >= 2, 3) LOCAL_ENU_Z_UP


def chainage_to_xyz(points: FloatArray, fraction: float) -> FloatArray:
    """Position at ``fraction`` of the polyline ARC LENGTH (0 = first point,
    1 = last point); the fraction must already be validated in [0, 1]."""
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if pts.shape[0] == 1:
        return np.array(pts[0], dtype=np.float64)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1])
    if total <= 0.0:
        return np.array(pts[0], dtype=np.float64)
    target = float(np.clip(fraction, 0.0, 1.0)) * total
    k = int(np.searchsorted(cum, target, side="right") - 1)
    k = min(max(k, 0), pts.shape[0] - 2)
    span = float(cum[k + 1] - cum[k])
    t = 0.0 if span <= 0.0 else (target - float(cum[k])) / span
    return np.asarray(pts[k] + t * (pts[k + 1] - pts[k]), dtype=np.float64)


def pack_polylines(edges: list[EdgeGeometry]) -> tuple[FloatArray, npt.NDArray[np.int64]]:
    """Concatenate polylines: (points (P, 3), offsets (E + 1,)) in edge order."""
    offsets = np.zeros(len(edges) + 1, dtype=np.int64)
    chunks: list[FloatArray] = []
    for i, e in enumerate(edges):
        pts = np.asarray(e.points, dtype=np.float64).reshape(-1, 3)
        chunks.append(pts)
        offsets[i + 1] = offsets[i] + pts.shape[0]
    points = np.vstack(chunks) if chunks else np.zeros((0, 3), dtype=np.float64)
    return points, offsets
