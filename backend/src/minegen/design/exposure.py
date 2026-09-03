"""Geological exposure of development centerlines: fault crossings, fault
core / damage-zone length and poor-rock length on a ≤ 2 m resampling.

Shared by the golden harness (Phase 18) and the layout-v2 GEOLOGY score
group (Phase 20A). Pure NumPy over the analytic ``FaultPlane`` objects and
the batch rock-quality query; the poor-rock threshold is a SYNTHETIC
diagnostic on the 0–100 synthetic field — not an RMR class, not a support
threshold, not a regulatory limit.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise

import numpy as np
import numpy.typing as npt

from minegen.world.geology import FaultPlane

FloatArray = npt.NDArray[np.float64]

#: synthetic diagnostic threshold on the 0–100 synthetic rock-quality field
DIAGNOSTIC_POOR_ROCK_THRESHOLD = 40.0
#: resampling step for along-development integrals (m)
POLYLINE_SAMPLE_SPACING = 2.0


def resample_polyline(pts: FloatArray, spacing: float) -> tuple[FloatArray, FloatArray]:
    """Midpoints and lengths of ≤ ``spacing`` sub-pieces of every polyline
    edge (each edge split into ``ceil(len / spacing)`` equal pieces)."""
    if pts.shape[0] < 2:
        return np.zeros((0, 3)), np.zeros(0)
    mids: list[FloatArray] = []
    lens: list[FloatArray] = []
    for a, b in pairwise(pts):
        length = float(np.linalg.norm(b - a))
        if length <= 0.0:
            continue
        n = max(1, int(np.ceil(length / spacing)))
        t = (np.arange(n) + 0.5) / n
        mids.append(a[None, :] + t[:, None] * (b - a)[None, :])
        lens.append(np.full(n, length / n))
    if not mids:
        return np.zeros((0, 3)), np.zeros(0)
    return np.vstack(mids), np.concatenate(lens)


@dataclass
class DevelopmentExposure:
    fault_crossings: int = 0
    length_fault_core: float = 0.0
    length_fault_damage: float = 0.0
    length_poor_rock: float = 0.0
    total_length: float = 0.0


def measure_exposure(
    polylines: list[FloatArray],
    faults: list[FaultPlane],
    rock_quality: Callable[[FloatArray], FloatArray],
    poor_threshold: float = DIAGNOSTIC_POOR_ROCK_THRESHOLD,
) -> DevelopmentExposure:
    """Fault crossings (sign changes of each fault's signed distance at the
    development vertices) and length-weighted zone / poor-rock exposure on a
    ≤ 2 m resampling. ``length_fault_damage`` EXCLUDES the core."""
    out = DevelopmentExposure()
    for pts in polylines:
        if pts.shape[0] < 2:
            continue
        for f in faults:
            d = f.signed_distance(pts)
            out.fault_crossings += int(np.sum(d[:-1] * d[1:] < 0.0))
        mids, lens = resample_polyline(pts, POLYLINE_SAMPLE_SPACING)
        if mids.shape[0] == 0:
            continue
        out.total_length += float(lens.sum())
        core = np.zeros(mids.shape[0], dtype=bool)
        damage = np.zeros(mids.shape[0], dtype=bool)
        for f in faults:
            ad = np.abs(f.signed_distance(mids))
            core |= ad <= f.config.core_half_width
            damage |= ad <= f.config.influence_half_width
        damage &= ~core
        out.length_fault_core += float(lens[core].sum())
        out.length_fault_damage += float(lens[damage].sum())
        rq = np.asarray(rock_quality(mids), dtype=np.float64)
        out.length_poor_rock += float(lens[rq < poor_threshold].sum())
    return out
