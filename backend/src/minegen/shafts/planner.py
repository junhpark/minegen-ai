"""Phase 20C.2B — deterministic vertical shaft planner (rules 182–184).

A shaft is an infrastructure primitive ADDED to the selected mine layout —
never a layout-v2 family, never a replacement for the ramp, never placed by
an optimizer. For every declared ``ShaftSpec`` the planner:

1. resolves the collar PLAN position — explicit, or the deterministic
   default (target-level entry plan centroid pushed ``collarStandoff`` m away
   from the orebody plan centre); the collar ELEVATION is always the terrain
   surface;
2. places one SHAFT_STATION per required level on the vertical axis at the
   elevation of that level's connection target — the EXISTING level
   development node (LEVEL_ENTRY or drift breakpoint) nearest to the axis in
   plan (rule 183; the level geometry is never rebuilt);
3. drives a straight station access from the station to that node,
   validated on the delivered polyline (world, terrain, cover, orebody
   buffer, restricted zones, gradient, length, excavation envelope);
4. validates the axis and its circular envelope with the SHARED design cost
   evaluator gates — the orebody is a hard exclusion for a permanent shaft
   (penetration forbidden), restricted zones and world bounds are hard,
   terrain break-through is permitted only within the collar zone;
5. fails typed. Every listed level is REQUIRED (directive §16): one
   infeasible station fails the shaft, and nothing is clamped or relaxed.

Geometry lives in ONE flat ``centerlines`` list so MineNetwork references it
through the unchanged ``GeometryRef{artifact, segmentIndex}`` contract.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.core.models import Scenario, ShaftSpec
from minegen.design.constraints import RejectionReason
from minegen.design.cost_field import DesignCostEvaluator
from minegen.design.profile import boundary_points, build_profile
from minegen.shafts.models import (
    Centerline,
    ConnectionTarget,
    Shaft,
    ShaftCenterline,
    ShaftFailureCode,
    ShaftMetrics,
    ShaftProfile,
    ShaftsMetrics,
    ShaftsPayload,
    ShaftStation,
    ShaftValidation,
    StationConnectionReport,
)
from minegen.world.synthetic_world import SyntheticWorld

FloatArray = npt.NDArray[np.float64]

#: axis / envelope sampling spacing ceiling (m); the actual spacing is
#: ``min(AXIS_SAMPLE_SPACING, smallest fault core half-width)`` (rule 50)
AXIS_SAMPLE_SPACING = 1.0
#: station-drive centerline sampling (m) — the Phase 08 development spacing
ACCESS_SAMPLE_SPACING = 2.0
#: boundary points per circular envelope ring
ENVELOPE_RING_POINTS = 8
#: a station must sit at least this many diameters below the collar
MIN_STATION_DEPTH_DIAMETERS = 1.0

_REASON_TO_CODE: dict[RejectionReason, ShaftFailureCode] = {
    RejectionReason.INSIDE_OREBODY: ShaftFailureCode.SHAFT_OREBODY_INTERSECTION,
    RejectionReason.OREBODY_BUFFER: ShaftFailureCode.SHAFT_CLEARANCE_VIOLATION,
    RejectionReason.RESTRICTED_ZONE: ShaftFailureCode.SHAFT_RESTRICTED_ZONE_INTERSECTION,
    RejectionReason.OUTSIDE_WORLD: ShaftFailureCode.SHAFT_BOTTOM_OUT_OF_BOUNDS,
    RejectionReason.ABOVE_TERRAIN: ShaftFailureCode.SHAFT_TERRAIN_INVALID,
    RejectionReason.INSUFFICIENT_COVER: ShaftFailureCode.SHAFT_GEOMETRY_INVALID,
}
#: precedence when several reasons hit: the most specific engineering cause
_CODE_PRIORITY: tuple[ShaftFailureCode, ...] = (
    ShaftFailureCode.SHAFT_OREBODY_INTERSECTION,
    ShaftFailureCode.SHAFT_CLEARANCE_VIOLATION,
    ShaftFailureCode.SHAFT_RESTRICTED_ZONE_INTERSECTION,
    ShaftFailureCode.SHAFT_BOTTOM_OUT_OF_BOUNDS,
    ShaftFailureCode.SHAFT_TERRAIN_INVALID,
    ShaftFailureCode.SHAFT_GEOMETRY_INVALID,
)


class ShaftPlanningError(ValueError):
    """Typed planner failure that is not attributable to one shaft (e.g. a
    levels artifact that is not consumable)."""


@dataclass(frozen=True)
class _Breakpoint:
    node_kind: str  # LEVEL_ENTRY | JUNCTION
    level_id: str
    u: float
    position: FloatArray


@dataclass
class _ShaftFailureError(Exception):
    code: ShaftFailureCode
    reason: str


def _sample_line(start: FloatArray, end: FloatArray, spacing: float) -> FloatArray:
    n = max(2, math.ceil(float(np.linalg.norm(end - start)) / spacing) + 1)
    t = np.linspace(0.0, 1.0, n)[:, None]
    return start[None, :] * (1 - t) + end[None, :] * t


def _reason_counts(reasons: list[list[RejectionReason]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for rs in reasons:
        for r in rs:
            counts[r.value] = counts.get(r.value, 0) + 1
    return dict(sorted(counts.items()))


def _dominant_code(counts: dict[str, int], default: ShaftFailureCode) -> ShaftFailureCode:
    present = {
        _REASON_TO_CODE[RejectionReason(name)]
        for name in counts
        if RejectionReason(name) in _REASON_TO_CODE
    }
    for code in _CODE_PRIORITY:
        if code in present:
            return code
    return default


def level_breakpoints(levels_payload: dict[str, Any]) -> dict[str, list[_Breakpoint]]:
    """Every EXISTING level-development node the network builder will
    create for a level (rule 73 breakpoints): the LEVEL_ENTRY plus every
    drift piece endpoint, keyed by its along-backbone coordinate ``u``.
    Deterministic order: LEVEL_ENTRY first, then ascending ``u``."""
    out: dict[str, list[_Breakpoint]] = {}
    entry_u: dict[str, float] = {}
    for lv in levels_payload.get("levels", []):
        lid = str(lv["levelId"])
        pos = np.asarray(lv["entry"], dtype=np.float64)
        entry_u[lid] = float(lv["entryU"])
        out[lid] = [_Breakpoint("LEVEL_ENTRY", lid, float(lv["entryU"]), pos)]
    for dev in levels_payload.get("developments", []):
        if dev.get("kind") != "DRIFT":
            continue
        lid = str(dev["levelId"])
        pts = np.asarray(dev["centerline"]["points"], dtype=np.float64).reshape(-1, 3)
        for u, pos in ((float(dev["fromU"]), pts[0]), (float(dev["toU"]), pts[-1])):
            bps = out.setdefault(lid, [])
            if any(abs(b.u - u) <= 1e-6 for b in bps):
                continue
            bps.append(_Breakpoint("JUNCTION", lid, u, pos.copy()))
    for lid, bps in out.items():
        head = [b for b in bps if b.node_kind == "LEVEL_ENTRY"]
        rest = sorted((b for b in bps if b.node_kind != "LEVEL_ENTRY"), key=lambda b: b.u)
        out[lid] = head + rest
    return out


class ShaftPlanner:
    """Plans every declared shaft against the validated ``levels.json``.

    ``axis_evaluator`` carries ``DesignContext.shaft`` (orebody buffer hard,
    no surface-cover rule — a shaft breaks the surface by definition);
    ``access_evaluator`` carries the decline context used by every level
    development drive, under the ACTIVE clearance policy (rule 172)."""

    def __init__(
        self,
        scenario: Scenario,
        world: SyntheticWorld,
        axis_evaluator: DesignCostEvaluator,
        access_evaluator: DesignCostEvaluator,
    ) -> None:
        self.scenario = scenario
        self.world = world
        self.axis_ev = axis_evaluator
        self.access_ev = access_evaluator
        self.shape = build_profile(scenario.ramp, scenario.tunnel_profile)
        cores = [f.config.core_half_width for f in world.faults]
        self.axis_spacing = min([AXIS_SAMPLE_SPACING, *cores]) if cores else AXIS_SAMPLE_SPACING

    # -- public --------------------------------------------------------------- #

    def build(
        self, levels_payload: dict[str, Any], source_revision: str, levels_revision: str
    ) -> ShaftsPayload:
        t0 = time.perf_counter()
        specs = self.scenario.shafts.specs
        if levels_payload.get("status") != "SUCCESS":
            return self._failed(
                source_revision,
                levels_revision,
                f"prerequisite levels artifact status {levels_payload.get('status')!r} is "
                "not consumable (rule 183)",
                t0,
            )
        breakpoints = level_breakpoints(levels_payload)
        centerlines: list[ShaftCenterline] = []
        shafts: list[Shaft] = []
        for spec in specs:
            shafts.append(self._plan_shaft(spec, breakpoints, centerlines))
        sep_failure = self._separation_check(shafts)
        if sep_failure is not None:
            sid, reason = sep_failure
            for i, sh in enumerate(shafts):
                if sh.shaft_id == sid and sh.status == "OK":
                    shafts[i] = sh.model_copy(
                        update={
                            "status": "FAILED",
                            "failure_code": ShaftFailureCode.SHAFT_GEOMETRY_INVALID,
                            "failure_reason": reason,
                        }
                    )
        failed = [s for s in shafts if s.status == "FAILED"]
        ok = [s for s in shafts if s.status == "OK"]
        metrics = ShaftsMetrics(
            shaft_count=len(shafts),
            station_count=sum(len(s.stations) for s in ok),
            total_shaft_length3d=float(
                math.fsum(s.metrics.total_shaft_length3d for s in ok if s.metrics)
            ),
            total_station_access_length3d=float(
                math.fsum(s.metrics.total_station_access_length3d for s in ok if s.metrics)
            ),
            planning_seconds=time.perf_counter() - t0,
        )
        failure = None
        if failed:
            failure = "; ".join(
                f"{s.shaft_id}: {s.failure_code} — {s.failure_reason}" for s in failed
            )
        return ShaftsPayload(
            status="SUCCESS" if failure is None else "FAILED",
            failure_reason=failure,
            source_revision=source_revision,
            levels_revision=levels_revision,
            shafts=shafts,
            centerlines=centerlines,
            metrics=metrics,
        )

    # -- per shaft -------------------------------------------------------------- #

    def _plan_shaft(
        self,
        spec: ShaftSpec,
        breakpoints: dict[str, list[_Breakpoint]],
        centerlines: list[ShaftCenterline],
    ) -> Shaft:
        radius = spec.diameter / 2.0
        profile = ShaftProfile(diameter=spec.diameter, analytic_area=math.pi * radius * radius)
        try:
            level_ids = self._target_levels(spec, breakpoints)
            collar_xy, collar_source = self._collar_plan(spec, level_ids, breakpoints)
            collar = self._collar(collar_xy)
            targets = [self._connection_target(collar_xy, breakpoints[lid]) for lid in level_ids]
            stations = self._station_points(spec, collar, targets)
            bottom = np.array(
                [collar_xy[0], collar_xy[1], stations[-1][2] - spec.bottom_sump_depth]
            )
            if not bool(self.axis_ev.world_valid(bottom[None, :])[0]):
                raise _ShaftFailureError(
                    ShaftFailureCode.SHAFT_BOTTOM_OUT_OF_BOUNDS,
                    f"shaft bottom z={bottom[2]:.2f} lies below the model floor",
                )
            validation = self._validate_axis(collar, bottom, radius)
        except _ShaftFailureError as exc:
            return Shaft(
                shaft_id=spec.shaft_id,
                role=spec.role,
                capabilities=list(spec.capabilities or []),
                profile=profile,
                collar=(0.0, 0.0, 0.0),
                collar_source="EXPLICIT" if spec.collar is not None else "DEFAULT_DERIVED",
                bottom=(0.0, 0.0, 0.0),
                stations=[],
                segment_indices=[],
                validation=None,
                metrics=None,
                status="FAILED",
                failure_code=exc.code,
                failure_reason=exc.reason,
            )

        # station drives — every listed level is REQUIRED (§16)
        station_models: list[ShaftStation] = []
        access_total = 0.0
        station_failed: ShaftStation | None = None
        for lid, target, point in zip(level_ids, targets, stations, strict=True):
            station = self._station(spec, lid, target, point, centerlines)
            station_models.append(station)
            if station.status == "FAILED" and station_failed is None:
                station_failed = station
            elif station.report is not None:
                access_total += station.report.length3d

        # axis segments collar → STN₁ → … → STNₙ → bottom
        segment_indices: list[int] = []
        chain = [collar, *stations, bottom]
        shaft_total = 0.0
        for k in range(len(chain) - 1):
            a, b = chain[k], chain[k + 1]
            length = float(abs(a[2] - b[2]))
            shaft_total += length
            segment_indices.append(len(centerlines))
            centerlines.append(
                ShaftCenterline(
                    id=f"SHAFT:{spec.shaft_id}:SEG{k:02d}",
                    shaft_id=spec.shaft_id,
                    kind="SHAFT_SEGMENT",
                    level_id=level_ids[k] if k < len(level_ids) else None,
                    centerline=Centerline(points=[*map(float, a), *map(float, b)]),
                    length3d=length,
                )
            )
        depth = float(collar[2] - bottom[2])
        metrics = ShaftMetrics(
            depth=depth,
            station_count=len(station_models),
            total_shaft_length3d=shaft_total,
            total_station_access_length3d=access_total,
            nominal_excavation_volume=profile.analytic_area * depth,
        )
        status = "OK"
        code = None
        reason = None
        if not validation.valid:
            status = "FAILED"
            code = _dominant_code(
                validation.rejection_counts, ShaftFailureCode.SHAFT_GEOMETRY_INVALID
            )
            reason = f"shaft axis/envelope validation failed: {validation.rejection_counts}"
        elif station_failed is not None:
            status = "FAILED"
            code = ShaftFailureCode.SHAFT_STATION_CONNECTION_INFEASIBLE
            reason = (
                f"required station {station_failed.station_id} failed: "
                f"{station_failed.failure_code} — {station_failed.failure_reason}"
            )
        return Shaft(
            shaft_id=spec.shaft_id,
            role=spec.role,
            capabilities=list(spec.capabilities or []),
            profile=profile,
            collar=(float(collar[0]), float(collar[1]), float(collar[2])),
            collar_source=collar_source,
            bottom=(float(bottom[0]), float(bottom[1]), float(bottom[2])),
            stations=station_models,
            segment_indices=segment_indices,
            validation=validation,
            metrics=metrics,
            status=status,
            failure_code=code,
            failure_reason=reason,
        )

    # -- steps --------------------------------------------------------------- #

    @staticmethod
    def _target_levels(spec: ShaftSpec, breakpoints: dict[str, list[_Breakpoint]]) -> list[str]:
        developed = sorted(breakpoints)
        if not developed:
            raise _ShaftFailureError(
                ShaftFailureCode.SHAFT_NO_SERVICEABLE_LEVELS,
                "the levels artifact contains no developed level",
            )
        if not spec.level_ids:
            return developed
        missing = [lid for lid in spec.level_ids if lid not in breakpoints]
        if missing:
            raise _ShaftFailureError(
                ShaftFailureCode.SHAFT_STATION_LEVEL_MISMATCH,
                f"required level(s) {missing} have no level development in levels.json",
            )
        return sorted(spec.level_ids)

    def _collar_plan(
        self,
        spec: ShaftSpec,
        level_ids: list[str],
        breakpoints: dict[str, list[_Breakpoint]],
    ) -> tuple[FloatArray, str]:
        if spec.collar is not None:
            return np.array([spec.collar.x, spec.collar.y], dtype=np.float64), "EXPLICIT"
        entries = np.array(
            [breakpoints[lid][0].position[:2] for lid in level_ids], dtype=np.float64
        )
        centroid = entries.mean(axis=0)
        lo, hi = self.world.orebody.bounding_box()
        ore_centre = 0.5 * (np.asarray(lo)[:2] + np.asarray(hi)[:2])
        away = centroid - ore_centre
        norm = float(np.linalg.norm(away))
        if norm <= 1e-9:
            raise _ShaftFailureError(
                ShaftFailureCode.SHAFT_GEOMETRY_INVALID,
                "default collar placement is undefined: the level-entry centroid coincides "
                "with the orebody plan centre; declare an explicit collar",
            )
        return centroid + spec.collar_standoff * (away / norm), "DEFAULT_DERIVED"

    def _collar(self, xy: FloatArray) -> FloatArray:
        terrain = self.world.terrain
        x_min, x_max = float(terrain.x[0]), float(terrain.x[-1])
        y_min, y_max = float(terrain.y[0]), float(terrain.y[-1])
        if not (x_min <= xy[0] <= x_max and y_min <= xy[1] <= y_max):
            raise _ShaftFailureError(
                ShaftFailureCode.SHAFT_TERRAIN_INVALID,
                f"collar plan position ({xy[0]:.1f}, {xy[1]:.1f}) lies outside the terrain grid",
            )
        z = float(terrain.sample(xy[None, :])[0])
        if not math.isfinite(z):
            raise _ShaftFailureError(
                ShaftFailureCode.SHAFT_TERRAIN_INVALID, "terrain elevation is not finite"
            )
        collar = np.array([xy[0], xy[1], z], dtype=np.float64)
        if not bool(self.axis_ev.world_valid(collar[None, :])[0]):
            raise _ShaftFailureError(
                ShaftFailureCode.SHAFT_COLLAR_OUT_OF_BOUNDS,
                f"collar ({xy[0]:.1f}, {xy[1]:.1f}, {z:.1f}) lies outside the world bounds",
            )
        return collar

    @staticmethod
    def _connection_target(collar_xy: FloatArray, bps: list[_Breakpoint]) -> ConnectionTarget:
        best: _Breakpoint | None = None
        best_key: tuple[float, float, int] | None = None
        for i, b in enumerate(bps):
            d = float(np.linalg.norm(b.position[:2] - collar_xy))
            key = (round(d, 9), b.u, i)
            if best_key is None or key < best_key:
                best, best_key = b, key
        assert best is not None and best_key is not None
        return ConnectionTarget(
            node_kind="LEVEL_ENTRY" if best.node_kind == "LEVEL_ENTRY" else "JUNCTION",
            level_id=best.level_id,
            station_u=best.u,
            position=(float(best.position[0]), float(best.position[1]), float(best.position[2])),
            plan_distance_to_axis=best_key[0],
        )

    @staticmethod
    def _station_points(
        spec: ShaftSpec, collar: FloatArray, targets: list[ConnectionTarget]
    ) -> list[FloatArray]:
        pts: list[FloatArray] = []
        min_depth = MIN_STATION_DEPTH_DIAMETERS * spec.diameter
        for t in targets:
            z = t.position[2]
            if collar[2] - z < min_depth:
                raise _ShaftFailureError(
                    ShaftFailureCode.SHAFT_STATION_LEVEL_MISMATCH,
                    f"level {t.level_id} station elevation {z:.2f} is less than {min_depth:.1f} m "
                    f"below the collar ({collar[2]:.2f})",
                )
            pts.append(np.array([collar[0], collar[1], z], dtype=np.float64))
        zs = [p[2] for p in pts]
        if len(set(round(z, 6) for z in zs)) != len(zs):
            raise _ShaftFailureError(
                ShaftFailureCode.SHAFT_STATION_LEVEL_MISMATCH,
                "two required levels share one station elevation",
            )
        order = sorted(range(len(pts)), key=lambda i: -zs[i])
        if order != list(range(len(pts))):
            raise _ShaftFailureError(
                ShaftFailureCode.SHAFT_STATION_LEVEL_MISMATCH,
                "required level ids are not in descending-elevation order "
                f"({[t.level_id for t in targets]})",
            )
        return pts

    def _validate_axis(
        self, collar: FloatArray, bottom: FloatArray, radius: float
    ) -> ShaftValidation:
        axis = _sample_line(collar, bottom, self.axis_spacing)
        axis_eval = self.axis_ev.evaluate_points(axis)
        counts = _reason_counts(axis_eval.rejection_reasons)
        axis_invalid = int((~axis_eval.valid).sum())
        # circular envelope rings (rule 183): terrain break-through is
        # permitted only inside the collar zone (one diameter below collar)
        angles = np.linspace(0.0, 2 * math.pi, ENVELOPE_RING_POINTS, endpoint=False)
        ring = np.stack([np.cos(angles), np.sin(angles), np.zeros_like(angles)], axis=1) * radius
        env = (axis[:, None, :] + ring[None, :, :]).reshape(-1, 3)
        env_eval = self.axis_ev.evaluate_points(env)
        depth_below_collar = np.repeat(collar[2] - axis[:, 2], ENVELOPE_RING_POINTS)
        collar_zone = depth_below_collar <= 2.0 * radius
        env_invalid = 0
        above_deep = 0
        env_counts: dict[str, int] = {}
        for i, reasons in enumerate(env_eval.rejection_reasons):
            hard: list[RejectionReason] = [
                r for r in reasons if r is not RejectionReason.ABOVE_TERRAIN
            ]
            above = RejectionReason.ABOVE_TERRAIN in reasons
            if above and not collar_zone[i]:
                above_deep += 1
                hard.append(RejectionReason.ABOVE_TERRAIN)
            if hard:
                env_invalid += 1
                for r in hard:
                    env_counts[r.value] = env_counts.get(r.value, 0) + 1
        merged = dict(counts)
        for k, v in env_counts.items():
            merged[k] = merged.get(k, 0) + v
        return ShaftValidation(
            axis_samples=int(axis.shape[0]),
            axis_invalid_samples=axis_invalid,
            envelope_samples=int(env.shape[0]),
            envelope_invalid_samples=env_invalid,
            envelope_above_terrain_below_collar_zone=above_deep,
            sample_spacing=self.axis_spacing,
            rejection_counts=dict(sorted(merged.items())),
            valid=axis_invalid == 0 and env_invalid == 0,
        )

    def _station(
        self,
        spec: ShaftSpec,
        level_id: str,
        target: ConnectionTarget,
        point: FloatArray,
        centerlines: list[ShaftCenterline],
    ) -> ShaftStation:
        station_id = f"SHAFT_STATION:{spec.shaft_id}:{level_id}"
        end = np.asarray(target.position, dtype=np.float64)
        d = end - point
        horizontal = float(np.linalg.norm(d[:2]))
        length = float(np.linalg.norm(d))
        ramp = self.scenario.ramp
        min_h = spec.diameter / 2.0 + ramp.tunnel_width / 2.0
        max_len = self.scenario.shafts.maximum_station_access_length

        def failed(code: ShaftFailureCode, reason: str) -> ShaftStation:
            return ShaftStation(
                station_id=station_id,
                level_id=level_id,
                elevation=float(point[2]),
                point=(float(point[0]), float(point[1]), float(point[2])),
                connection_target=target,
                access_centerline_index=None,
                report=None,
                status="FAILED",
                failure_code=code,
                failure_reason=reason,
            )

        if horizontal < min_h:
            return failed(
                ShaftFailureCode.SHAFT_STATION_CONNECTION_INFEASIBLE,
                f"connection target is {horizontal:.2f} m from the axis in plan — the station "
                f"drive must leave the shaft envelope (≥ {min_h:.2f} m)",
            )
        if length > max_len:
            return failed(
                ShaftFailureCode.SHAFT_STATION_CONNECTION_INFEASIBLE,
                f"station drive length {length:.1f} m exceeds maximumStationAccessLength "
                f"{max_len:.1f} m",
            )
        grade = abs(float(d[2])) / horizontal
        if grade > ramp.max_gradient + 1e-12:
            return failed(
                ShaftFailureCode.SHAFT_STATION_CONNECTION_INFEASIBLE,
                f"station drive gradient {grade:.4f} exceeds max_gradient {ramp.max_gradient}",
            )
        pts = _sample_line(point, end, ACCESS_SAMPLE_SPACING)
        res = self.access_ev.evaluate_points(pts)
        invalid = int((~res.valid).sum())
        counts = _reason_counts(res.rejection_reasons)
        tangent = d / max(length, 1e-12)
        tangents = np.broadcast_to(tangent, pts.shape).copy()
        boundary = boundary_points(pts, tangents, self.shape).reshape(-1, 3)
        hard, above = self.access_ev.envelope_masks(boundary)
        env_hard = int(hard.sum())
        env_above = int(above.sum())
        if invalid == 0:
            arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
            c = res.total_cost_per_m
            field_cost = float(np.dot(0.5 * (c[1:] + c[:-1]), np.diff(arc)))
        else:
            field_cost = 0.0
        report = StationConnectionReport(
            length3d=length,
            horizontal_length=horizontal,
            mean_gradient_signed=float(d[2]) / horizontal,
            max_abs_gradient=grade,
            centerline_invalid_samples=invalid,
            envelope_hard_violations=env_hard,
            envelope_above_terrain=env_above,
            field_cost=field_cost,
            rejection_counts=counts,
        )
        if invalid > 0 or env_hard > 0 or env_above > 0:
            code = _dominant_code(counts, ShaftFailureCode.SHAFT_STATION_CONNECTION_INFEASIBLE)
            if invalid == 0:
                code = (
                    ShaftFailureCode.SHAFT_TERRAIN_INVALID
                    if env_above > 0 and env_hard == 0
                    else ShaftFailureCode.SHAFT_STATION_CONNECTION_INFEASIBLE
                )
            st = failed(
                code,
                f"station drive validation failed: {invalid} invalid centerline samples "
                f"{counts}, {env_hard} envelope violations, {env_above} envelope samples "
                "above terrain",
            )
            return st.model_copy(update={"report": report})
        index = len(centerlines)
        centerlines.append(
            ShaftCenterline(
                id=f"SHAFT_STATION_ACCESS:{spec.shaft_id}:{level_id}",
                shaft_id=spec.shaft_id,
                kind="STATION_ACCESS",
                level_id=level_id,
                centerline=Centerline(points=[*map(float, point), *map(float, end)]),
                length3d=length,
            )
        )
        return ShaftStation(
            station_id=station_id,
            level_id=level_id,
            elevation=float(point[2]),
            point=(float(point[0]), float(point[1]), float(point[2])),
            connection_target=target,
            access_centerline_index=index,
            report=report,
            status="OK",
        )

    def _separation_check(self, shafts: list[Shaft]) -> tuple[str, str] | None:
        cfg = self.scenario.shafts
        pillar = (
            cfg.minimum_shaft_separation
            if cfg.minimum_shaft_separation is not None
            else 2.0 * self.scenario.ramp.tunnel_width
        )
        ok = [s for s in shafts if s.status == "OK"]
        for i, a in enumerate(ok):
            for b in ok[i + 1 :]:
                d = math.hypot(a.collar[0] - b.collar[0], a.collar[1] - b.collar[1])
                need = a.profile.diameter / 2.0 + b.profile.diameter / 2.0 + pillar
                if d < need:
                    return (
                        b.shaft_id,
                        f"shaft {b.shaft_id} axis is {d:.2f} m from {a.shaft_id} in plan; "
                        f"the envelopes need {need:.2f} m (radii + {pillar:.1f} m pillar)",
                    )
        return None

    @staticmethod
    def _failed(
        source_revision: str, levels_revision: str, reason: str, t0: float
    ) -> ShaftsPayload:
        return ShaftsPayload(
            status="FAILED",
            failure_reason=reason,
            source_revision=source_revision,
            levels_revision=levels_revision,
            shafts=[],
            centerlines=[],
            metrics=ShaftsMetrics(
                shaft_count=0,
                station_count=0,
                total_shaft_length3d=0.0,
                total_station_access_length3d=0.0,
                planning_seconds=time.perf_counter() - t0,
            ),
        )
