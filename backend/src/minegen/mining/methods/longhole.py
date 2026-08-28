"""Longhole open stoping stope generator (rules 75–77).

Consumes the validated Phase 08 ``levels.json`` artifact ONLY — the station
lattice is never recomputed from the scenario. For every adjacent completed
level pair and every station index, the paired CROSSCUT terminal points
anchor an orebody-aligned rectangular prism in the analytic local frame:

    u ∈ [stationU − stope_length/2, stationU + stope_length/2]
    v ∈ [local-v of the paired upper/lower crosscut terminals]
    w ∈ [−half_thickness, +half_thickness]

Missing, duplicated, mismatched or geometrically inconsistent station pairs
FAIL the whole artifact — a required stope is never silently skipped
(rule 76). The Phase 08 pitch (``stope_length + minimum_pillar``) leaves the
exact minimum strike pillar between neighbours; that contract is re-verified
here, not assumed (rule 77). Vertically adjacent stopes share their boundary
face — that is not an overlap.
"""

from __future__ import annotations

import math
from itertools import pairwise
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.core.enums import MiningMethodType
from minegen.core.models import Scenario
from minegen.design.cost_field import DesignCostEvaluator
from minegen.mining.models import (
    Stope,
    StopeGeometry,
    StopeLocalBounds,
    StopeReport,
    StopesMetrics,
    StopesPayload,
)
from minegen.world.orebody import TabularOrebody
from minegen.world.synthetic_world import SyntheticWorld

FloatArray = npt.NDArray[np.float64]

ANCHOR_TOLERANCE = 1e-6  # m — terminal on the footwall face, u == stationU
PILLAR_TOLERANCE = 1e-9  # m
SAMPLE_SPACING = 5.0  # m — deterministic hard-validation lattice inside the prism

# canonical box corners: bit i&1 → u, i>>1&1 → v, i>>2&1 → w. Triangles are
# wound OUTWARD for a right-handed (u, v, w) local frame; the generator
# reverses the winding once per build when the analytic frame determinant is
# negative, so the WORLD mesh is always outward (verified by signed volume).
_CORNER_BITS = [(i & 1, (i >> 1) & 1, (i >> 2) & 1) for i in range(8)]
_BOX_TRIANGLES = [
    (0, 2, 3),
    (0, 3, 1),  # w = wMin (outward −w)
    (4, 5, 7),
    (4, 7, 6),  # w = wMax (outward +w)
    (0, 1, 5),
    (0, 5, 4),  # v = vMin (outward −v)
    (2, 6, 7),
    (2, 7, 3),  # v = vMax (outward +v)
    (0, 4, 6),
    (0, 6, 2),  # u = uMin (outward −u)
    (1, 3, 7),
    (1, 7, 5),  # u = uMax (outward +u)
]


def _failed(method: str, source_revision: str, reason: str) -> StopesPayload:
    return StopesPayload(
        status="FAILED",
        failure_reason=reason,
        source_revision=source_revision,
        method=method,
        stopes=[],
        metrics=None,
    )


def _grade_proxy(world: SyntheticWorld, corners_world: FloatArray) -> float | None:
    """Deterministic planning proxy from the existing BlockModel grade — the
    mean grade of ore-flagged blocks whose centers a coarse interior lattice
    hits. NOT a reserve/resource estimate and never a feasibility criterion."""
    bm = world.block_model
    grid = bm.grid
    mins = corners_world.min(axis=0)
    maxs = corners_world.max(axis=0)
    axes = [
        np.linspace(mins[d], maxs[d], max(2, math.ceil((maxs[d] - mins[d]) / 10.0) + 1))
        for d in range(3)
    ]
    gx, gy, gz = np.meshgrid(*axes, indexing="ij")
    pts = np.column_stack([gx.ravel(), gy.ravel(), gz.ravel()])
    idx = np.floor((pts - np.asarray(grid.origin)) / np.asarray(grid.spacing)).astype(int)
    inb = np.all((idx >= 0) & (idx < np.asarray(grid.shape)), axis=1)
    if not bool(inb.any()):
        return None
    i, j, k = idx[inb].T
    flags = bm.ore_flag[i, j, k]
    if not bool(flags.any()):
        return None
    return float(np.mean(bm.grade[i, j, k][flags]))


class LongholeOpenStopingStrategy:
    method = MiningMethodType.LONGHOLE_OPEN_STOPING

    def generate(
        self,
        scenario: Scenario,
        world: SyntheticWorld,
        levels_payload: dict[str, Any],
        hard_evaluator: DesignCostEvaluator,
        source_revision: str,
    ) -> StopesPayload:
        method = self.method.value
        if levels_payload.get("status") != "SUCCESS":
            return _failed(
                method,
                source_revision,
                f"prerequisite levels artifact status {levels_payload.get('status')!r} "
                "is not consumable (rule 79)",
            )
        ob = world.orebody
        if not isinstance(ob, TabularOrebody):
            return _failed(
                method, source_revision, "Phase 09 v0.1 requires a TABULAR orebody (rule 75)"
            )

        level_order = [lv["levelId"] for lv in levels_payload["levels"]]
        if len(level_order) < 2:
            return _failed(
                method,
                source_revision,
                "at least two completed levels are required to span a longhole stope",
            )

        # -- collect crosscut terminals per (level, station), gate duplicates - #
        terminals: dict[tuple[str, int], dict[str, Any]] = {}
        for dev in levels_payload["developments"]:
            if dev["kind"] != "CROSSCUT":
                continue
            key = (dev["levelId"], int(dev["stationIndex"]))
            if key in terminals:
                return _failed(
                    method,
                    source_revision,
                    f"duplicate crosscut station {key[1]:+d} on level {key[0]} (rule 76)",
                )
            terminals[key] = dev

        stations_by_level: dict[str, set[int]] = {}
        for lvl, k in terminals:
            stations_by_level.setdefault(lvl, set()).add(k)

        stope_len = float(scenario.mining.stope_length)
        min_pillar = float(scenario.mining.minimum_pillar)
        # world winding: flip once if the analytic local frame is left-handed
        handed = float(np.linalg.det(np.column_stack([ob.u, ob.v, ob.w])))
        triangles = _BOX_TRIANGLES if handed > 0 else [(a, c, b) for a, b, c in _BOX_TRIANGLES]
        stopes: list[Stope] = []
        first_failure: str | None = None

        def fail(reason: str) -> None:
            nonlocal first_failure
            if first_failure is None:
                first_failure = reason

        def terminal_local(dev: dict[str, Any]) -> FloatArray:
            pts = np.asarray(dev["centerline"]["points"], dtype=np.float64).reshape(-1, 3)
            local: FloatArray = ob.to_local(pts[-1][None, :])[0]
            return local

        intervals = list(pairwise(level_order))
        stations_per_interval: int | None = None
        per_interval: list[list[Stope]] = []
        for upper_id, lower_id in intervals:
            up_set = stations_by_level.get(upper_id, set())
            lo_set = stations_by_level.get(lower_id, set())
            if up_set != lo_set:
                missing = sorted(up_set.symmetric_difference(lo_set))
                return _failed(
                    method,
                    source_revision,
                    f"station set mismatch between {upper_id} and {lower_id} "
                    f"(unpaired stations {missing}) — a required stope is never "
                    "silently skipped (rule 76)",
                )
            ks = sorted(up_set)
            if stations_per_interval is None:
                stations_per_interval = len(ks)
            interval_stopes: list[Stope] = []
            for k in ks:
                up_dev = terminals[(upper_id, k)]
                lo_dev = terminals[(lower_id, k)]
                station_u = float(up_dev["stationU"])
                reason: str | None = None
                if abs(float(lo_dev["stationU"]) - station_u) > ANCHOR_TOLERANCE:
                    reason = "paired stations disagree on stationU"
                up_local = terminal_local(up_dev)
                lo_local = terminal_local(lo_dev)
                up_err = max(
                    abs(float(up_local[2]) - ob.half_thickness),
                    abs(float(up_local[0]) - station_u),
                )
                lo_err = max(
                    abs(float(lo_local[2]) - ob.half_thickness),
                    abs(float(lo_local[0]) - station_u),
                )
                if reason is None and (up_err > ANCHOR_TOLERANCE or lo_err > ANCHOR_TOLERANCE):
                    reason = (
                        f"access terminal off the footwall face / station plane "
                        f"(upper {up_err:.3e} m, lower {lo_err:.3e} m)"
                    )
                v_lo, v_hi = sorted((float(up_local[1]), float(lo_local[1])))
                bounds = StopeLocalBounds(
                    u_min=station_u - stope_len / 2.0,
                    u_max=station_u + stope_len / 2.0,
                    v_min=v_lo,
                    v_max=v_hi,
                    w_min=-ob.half_thickness,
                    w_max=+ob.half_thickness,
                )
                du = bounds.u_max - bounds.u_min
                dv = bounds.v_max - bounds.v_min
                dw = bounds.w_max - bounds.w_min
                if reason is None and (du <= 0 or dv <= 0 or dw <= 0):
                    reason = f"non-positive stope dimensions ({du:g} x {dv:g} x {dw:g})"
                if reason is None and (
                    bounds.u_min < -ob.half_length - ANCHOR_TOLERANCE
                    or bounds.u_max > ob.half_length + ANCHOR_TOLERANCE
                    or bounds.v_min < -ob.half_height - ANCHOR_TOLERANCE
                    or bounds.v_max > ob.half_height + ANCHOR_TOLERANCE
                ):
                    reason = "stope bounds leave the analytic orebody extent"

                # world prism + deterministic hard-validation lattice (rule 77)
                lows = np.array([bounds.u_min, bounds.v_min, bounds.w_min])
                highs = np.array([bounds.u_max, bounds.v_max, bounds.w_max])
                corners_local = np.array(
                    [
                        [lows[d] if bit == 0 else highs[d] for d, bit in enumerate(bits)]
                        for bits in _CORNER_BITS
                    ]
                )
                corners_world = ob.to_world(corners_local)
                axes = [
                    np.linspace(
                        lows[d],
                        highs[d],
                        max(2, math.ceil((highs[d] - lows[d]) / SAMPLE_SPACING) + 1),
                    )
                    for d in range(3)
                ]
                gu, gv, gw = np.meshgrid(*axes, indexing="ij")
                lattice_local = np.column_stack([gu.ravel(), gv.ravel(), gw.ravel()])
                lattice_world = ob.to_world(lattice_local)
                hard = hard_evaluator.evaluate_points(lattice_world)
                hard_invalid = int((~hard.valid).sum())
                if reason is None and hard_invalid > 0:
                    reason = (
                        f"{hard_invalid} prism samples violate hard world/terrain/"
                        "cover/zone constraints"
                    )

                volume = float(du * dv * dw)
                tonnes = volume * float(scenario.orebody.density)
                vertical = float(dv * abs(ob.v[2]))
                proxy = _grade_proxy(world, corners_world)
                values = [volume, tonnes, du, dv, dw, vertical, up_err, lo_err] + (
                    [proxy] if proxy is not None else []
                )
                finite = bool(np.isfinite(np.asarray(values)).all())
                if reason is None and not finite:
                    reason = "non-finite stope metrics"
                if reason is not None:
                    fail(f"{upper_id}-{lower_id} S{k:+03d}: {reason}")
                interval_stopes.append(
                    Stope(
                        id=f"STOPE:{upper_id}-{lower_id}:S{k:+03d}",
                        method="LONGHOLE_OPEN_STOPING",
                        station_index=k,
                        station_u=station_u,
                        upper_level_id=upper_id,
                        lower_level_id=lower_id,
                        upper_access_node_id=f"STOPE_ACCESS:{upper_id}:S{k:+03d}",
                        lower_access_node_id=f"STOPE_ACCESS:{lower_id}:S{k:+03d}",
                        local_bounds=bounds,
                        geometry=StopeGeometry(
                            vertices=[float(x) for x in corners_world.ravel()],
                            triangle_indices=[i for tri in triangles for i in tri],
                        ),
                        strike_length=float(du),
                        down_dip_span=float(dv),
                        vertical_height=vertical,
                        thickness=float(dw),
                        geometric_volume_m3=volume,
                        tonnes=tonnes,
                        mean_grade_proxy=proxy,
                        report=StopeReport(
                            upper_anchor_error=up_err,
                            lower_anchor_error=lo_err,
                            hard_invalid_samples=hard_invalid,
                            finite=finite,
                            valid=reason is None,
                            failure_reason=reason,
                        ),
                    )
                )
            per_interval.append(interval_stopes)
            stopes.extend(interval_stopes)

        # -- strike pillar / overlap contract (rule 77) ---------------------- #
        for interval_stopes in per_interval:
            ordered = sorted(interval_stopes, key=lambda s: s.local_bounds.u_min)
            for a, b in pairwise(ordered):
                gap = b.local_bounds.u_min - a.local_bounds.u_max
                a.report.strike_pillar_clearance = (
                    gap
                    if a.report.strike_pillar_clearance is None
                    else min(a.report.strike_pillar_clearance, gap)
                )
                b.report.strike_pillar_clearance = (
                    gap
                    if b.report.strike_pillar_clearance is None
                    else min(b.report.strike_pillar_clearance, gap)
                )
                if gap < -PILLAR_TOLERANCE:
                    fail(f"strike overlap between {a.id} and {b.id} ({gap:.3f} m)")
                elif gap < min_pillar - PILLAR_TOLERANCE:
                    fail(
                        f"strike pillar between {a.id} and {b.id} is {gap:.3f} m "
                        f"< minimum_pillar {min_pillar:g} m"
                    )
            if ordered:
                end_lo = ordered[0].local_bounds.u_min + ob.half_length
                end_hi = ob.half_length - ordered[-1].local_bounds.u_max
                if min(end_lo, end_hi) < min_pillar - PILLAR_TOLERANCE:
                    fail(
                        f"end pillar {min(end_lo, end_hi):.3f} m violates the Phase 08 "
                        f"end-pillar contract (≥ {min_pillar:g} m)"
                    )
        # vertical neighbours share their boundary face — never overlap
        for upper_iv, lower_iv in pairwise(per_interval):
            lower_by_k = {s.station_index: s for s in lower_iv}
            for s in upper_iv:
                t = lower_by_k.get(s.station_index)
                if t is not None and s.local_bounds.v_max > t.local_bounds.v_min + 1e-9:
                    fail(f"vertical overlap between {s.id} and {t.id}")

        total_v = float(math.fsum(s.geometric_volume_m3 for s in stopes))
        total_t = float(math.fsum(s.tonnes for s in stopes))
        orebody_v = 2.0 * ob.half_length * 2.0 * ob.half_height * 2.0 * ob.half_thickness
        graded = [(s.mean_grade_proxy, s.tonnes) for s in stopes if s.mean_grade_proxy is not None]
        weighted = (
            float(math.fsum(g * t for g, t in graded) / math.fsum(t for _, t in graded))
            if graded
            else None
        )
        metrics = StopesMetrics(
            stope_count=len(stopes),
            level_interval_count=len(intervals),
            stations_per_interval=stations_per_interval or 0,
            total_geometric_volume_m3=total_v,
            total_tonnes=total_t,
            geometric_extraction_fraction_of_orebody=total_v / orebody_v,
            weighted_mean_grade_proxy=weighted,
        )
        return StopesPayload(
            status="SUCCESS" if first_failure is None else "FAILED",
            failure_reason=first_failure,
            source_revision=source_revision,
            method=method,
            stopes=stopes,
            metrics=metrics,
        )
