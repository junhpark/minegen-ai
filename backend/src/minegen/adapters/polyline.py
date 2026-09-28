"""Pure polyline helpers for adapters: length and Douglas–Peucker
simplification (3-D, endpoints preserved, iterative). A simplification is a
REPRESENTATION tolerance the adapter reports, never an engineering change:
every kept vertex is an authoritative point and every removed point lies
within the tolerance of the delivered polyline."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]


def polyline_length(points: FloatArray) -> float:
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if pts.shape[0] < 2:
        return 0.0
    return float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())


def _segment_distances(points: FloatArray, a: FloatArray, b: FloatArray) -> FloatArray:
    """Distance of every point to the segment ``a → b`` (3-D)."""
    ab = b - a
    denom = float(ab @ ab)
    if denom <= 0.0:
        return np.linalg.norm(points - a, axis=1)
    t = np.clip(((points - a) @ ab) / denom, 0.0, 1.0)
    proj = a[None, :] + t[:, None] * ab[None, :]
    return np.linalg.norm(points - proj, axis=1)


def simplify_polyline(points: FloatArray, tolerance: float) -> tuple[FloatArray, float]:
    """→ (kept points in original order, measured maximum deviation of any
    removed point from the delivered polyline). ``tolerance <= 0`` keeps
    every point (deviation 0). First and last points are always kept."""
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    n = int(pts.shape[0])
    if n <= 2 or tolerance <= 0.0:
        return pts.copy(), 0.0
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    max_removed = 0.0
    stack: list[tuple[int, int]] = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j - i < 2:
            continue
        inner = pts[i + 1 : j]
        d = _segment_distances(inner, pts[i], pts[j])
        k = int(np.argmax(d))
        if float(d[k]) > tolerance:
            split = i + 1 + k
            keep[split] = True
            stack.append((i, split))
            stack.append((split, j))
        else:
            max_removed = max(max_removed, float(d.max()) if d.size else 0.0)
    return pts[keep].copy(), max_removed
