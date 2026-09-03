"""Phase 08 — level-development builder (rules 71–74).

Deterministic analytic geometry, no path search:

* A level DRIFT is anchored exactly at its Phase 05 LEVEL_ENTRY, aligned in
  plan with the orebody strike ``u`` (horizontal for a tabular body), and
  applies ``level_drift_gradient`` in the canonical +u direction:
  ``z(u) = z_entry − g·(u − u_entry)``. The entry never moves, and no claim
  is made that a graded drift stays on the exact 3D footwall-offset plane —
  the ACTUAL excavation envelope is validated instead (rule 71).
* Planned CROSSCUT stations are derived from the analytic orebody strike
  extent — never the Phase 03 access-candidate span. v0.1 pitch is
  ``stope_length + minimum_pillar``, symmetric about ``u = 0``, keeping the
  planned stope-length proxy plus end pillar inside the strike extent. This
  is an access-layout proxy for Phase 09, not final stope design (rule 72).
* Crosscuts run HORIZONTALLY toward the orebody (horizontal projection of
  the footwall→ore direction, not the full 3D −w vector) and terminate at
  the first footwall contact. Their context permits the ore contact while
  retaining world/terrain/restricted-zone hard constraints (rule 72).

The drift is emitted as PIECES split at every station/entry breakpoint, so
each Phase 08 MineNetwork DRIFT edge maps 1:1 onto a development in this
artifact (rule 73) and every graph edge owns exactly one centerline span.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.core.enums import MiningMethodType
from minegen.core.models import Scenario
from minegen.design.cost_field import DesignCostEvaluator
from minegen.design.profile import boundary_points, build_profile
from minegen.levels.models import (
    Centerline,
    Development,
    DevelopmentKind,
    DevelopmentReport,
    LevelsMetrics,
    LevelsPayload,
    LevelSummary,
    ProductionDevelopment,
)
from minegen.world.orebody import Orebody, TabularOrebody

FloatArray = npt.NDArray[np.float64]

WELD_TOLERANCE = 1e-6  # m
TERMINAL_SDF_TOLERANCE = 1e-6  # m — crosscut end sits ON the footwall contact
SAMPLE_SPACING = 2.0  # m — polyline sampling (endpoints always exact)
CONSUMABLE_SMOOTHED_STATUSES = ("SUCCESS", "SUCCESS_WITH_FALLBACK")


def _failed(source_revision: str, reason: str) -> LevelsPayload:
    return LevelsPayload(
        status="FAILED",
        failure_reason=reason,
        source_revision=source_revision,
        developments=[],
        levels=[],
        metrics=None,
    )


@dataclass(frozen=True)
class LevelEntrySpec:
    """Authoritative LEVEL_ENTRY handed to the builder (rule 157): for
    LAYOUT_V2 the terminal of the validated level access, for LEGACY the
    Phase 05 segment end."""

    level_id: str
    position: FloatArray
    candidate_id: str


def entries_from_level_accesses(accesses_payload: dict[str, Any]) -> list[LevelEntrySpec]:
    out: list[LevelEntrySpec] = []
    for acc in accesses_payload["accesses"]:
        if acc.get("status") != "OK" or acc.get("centerline") is None:
            continue
        pts = np.asarray(acc["centerline"]["points"], dtype=np.float64).reshape(-1, 3)
        out.append(
            LevelEntrySpec(
                str(acc["levelId"]), pts[-1].copy(), str(accesses_payload.get("candidateId") or "")
            )
        )
    return out


def entries_from_ramp_segments(smoothed_payload: dict[str, Any]) -> list[LevelEntrySpec]:
    """LEGACY semantics only: Phase 05 preserves every level-access target as
    the exact segment end, so the segment end IS the level entry."""
    out: list[LevelEntrySpec] = []
    for seg in smoothed_payload["segments"]:
        pts = np.asarray(seg["effectiveCenterline"]["points"], dtype=np.float64).reshape(-1, 3)
        out.append(LevelEntrySpec(str(seg["levelId"]), pts[-1].copy(), str(seg["candidateId"])))
    return out


def _sample_line(start: FloatArray, end: FloatArray) -> FloatArray:
    n = max(2, math.ceil(float(np.linalg.norm(end - start)) / SAMPLE_SPACING) + 1)
    t = np.linspace(0.0, 1.0, n)[:, None]
    return start[None, :] * (1 - t) + end[None, :] * t


def _polyline_stats(points: FloatArray) -> tuple[float, float, float]:
    d = np.diff(points, axis=0)
    length_3d = float(np.linalg.norm(d, axis=1).sum())
    dh = np.linalg.norm(d[:, :2], axis=1)
    dz = d[:, 2]
    total_h = float(dh.sum())
    mean_signed = float(dz.sum()) / total_h if total_h > 0 else 0.0
    mask = dh > 1e-9
    max_abs = float(np.max(np.abs(dz[mask] / dh[mask]))) if bool(mask.any()) else 0.0
    return length_3d, mean_signed, max_abs


@dataclass
class _EnvelopeCheck:
    hard: int
    above: int


class LevelDevelopmentBuilder:
    """Builds ``levels.json`` from the smoothed decline + orebody geometry.

    ``drift_evaluator`` carries the decline context (orebody buffer is a hard
    exclusion for footwall drifts); ``crosscut_evaluator`` carries
    ``DesignContext.crosscut`` (ore contact permitted, everything else
    retained)."""

    def __init__(
        self,
        scenario: Scenario,
        orebody: Orebody,
        drift_evaluator: DesignCostEvaluator,
        crosscut_evaluator: DesignCostEvaluator,
    ) -> None:
        self.scenario = scenario
        self.orebody = orebody
        self.drift_ev = drift_evaluator
        self.crosscut_ev = crosscut_evaluator
        self.shape = build_profile(scenario.ramp, scenario.tunnel_profile)

    # -- station lattice (rule 72) ------------------------------------------ #

    def station_pitch(self) -> float:
        return float(self.scenario.mining.stope_length + self.scenario.mining.minimum_pillar)

    def station_us(self, orebody: TabularOrebody) -> list[float]:
        """Symmetric about the orebody ``u = 0``; every planned stope-length
        proxy plus its end pillar must fit inside the strike extent."""
        pitch = self.station_pitch()
        margin = self.scenario.mining.stope_length / 2.0 + self.scenario.mining.minimum_pillar
        k_max = math.floor((orebody.half_length - margin) / pitch + 1e-9)
        return [k * pitch for k in range(-k_max, k_max + 1)]

    # -- envelope helper ---------------------------------------------------- #

    def _envelope(
        self, ev: DesignCostEvaluator, points: FloatArray, tangent: FloatArray
    ) -> _EnvelopeCheck:
        tangents = np.broadcast_to(tangent, points.shape).copy()
        boundary = boundary_points(points, tangents, self.shape).reshape(-1, 3)
        hard, above = ev.envelope_masks(boundary)
        return _EnvelopeCheck(hard=int(hard.sum()), above=int(above.sum()))

    def _centerline_and_cost(
        self, ev: DesignCostEvaluator, points: FloatArray
    ) -> tuple[int, float]:
        """(invalid centerline samples, field cost). Phase 08 has no
        Phase 04-style portal transition, so EVERY development centerline
        must independently satisfy its DesignContext hard constraints —
        including ``minimum_surface_cover``, which the envelope masks
        intentionally do not apply (blocker 1). The field cost is only
        defined for a fully valid centerline; invalid +inf costs are never
        silently converted to zero and carried on."""
        res = ev.evaluate_points(points)
        invalid = int((~res.valid).sum())
        if invalid > 0:
            return invalid, 0.0
        arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))])
        c = res.total_cost_per_m
        return 0, float(np.dot(0.5 * (c[1:] + c[:-1]), np.diff(arc)))

    # -- build --------------------------------------------------------------- #

    def build(
        self,
        smoothed_payload: dict[str, Any],
        source_revision: str,
        entries: list[LevelEntrySpec] | None = None,
    ) -> LevelsPayload:
        """``entries`` are the authoritative LEVEL_ENTRY positions. They MUST
        be supplied for a PARAMETRIC_V2 ramp (its segment ends are ramp
        junctions, not level entries — rule 157); for a LEGACY ramp they
        default to the Phase 05 segment ends."""
        smoothed_status = smoothed_payload.get("status")
        if smoothed_status not in CONSUMABLE_SMOOTHED_STATUSES:
            return _failed(
                source_revision,
                f"prerequisite smoothed artifact status {smoothed_status!r} is not "
                f"consumable (rule 74): only {', '.join(CONSUMABLE_SMOOTHED_STATUSES)} "
                "yield level developments",
            )
        segments = smoothed_payload["segments"]
        if not segments:
            return _failed(source_revision, "smoothed artifact has no effective segments")
        parametric = smoothed_payload.get("sourceKind") == "PARAMETRIC_V2" or any(
            s.get("rampJunction") is not None or s.get("levelId") is None for s in segments
        )
        if entries is None:
            if parametric:
                return _failed(
                    source_revision,
                    "LEVEL_ACCESSES_REQUIRED: a parametric main ramp ends its segments at "
                    "ramp junctions, never at level entries; level development needs the "
                    "validated level-access artifact (rule 157)",
                )
            entries = entries_from_ramp_segments(smoothed_payload)
            entry_source = "LEGACY_RAMP_SEGMENT"
        else:
            entry_source = "LEVEL_ACCESS"
        if not entries:
            return _failed(source_revision, "no level entries to develop")

        method = self.scenario.mining.method
        if method is MiningMethodType.LONGHOLE_OPEN_STOPING:
            production = ProductionDevelopment(method=method.value, status="IMPLEMENTED")
        else:
            production = ProductionDevelopment(
                method=method.value,
                status="UNSUPPORTED_METHOD",
                reason=(
                    f"{method.value} production development (ore drives, lift / fill "
                    "accesses, raises) is reserved and not implemented; only the generic "
                    "footwall backbone drift is developed — no longhole crosscut lattice "
                    "is substituted (rule 159)"
                ),
            )
        if not isinstance(self.orebody, TabularOrebody):
            return _failed(
                source_revision,
                "LEVEL_DEVELOPMENT_UNSUPPORTED_FOR_IMPLICIT_OREBODY: level drifts / "
                "crosscuts for a non-TABULAR orebody are not implemented (Phase 20B "
                "boundary); ramp junctions and level accesses are available",
            )
        ob = self.orebody
        u_hat = np.asarray(ob.u, dtype=np.float64)
        if abs(float(u_hat[2])) > 1e-9:
            return _failed(source_revision, "orebody strike vector is not horizontal")
        toward = -np.asarray(ob.w, dtype=np.float64)
        toward[2] = 0.0
        h = float(np.linalg.norm(toward))
        if h < 1e-6:
            return _failed(
                source_revision,
                "orebody is (near-)flat: horizontal crosscut direction is undefined",
            )
        toward /= h  # horizontal footwall → ore direction (rule 72)
        d_dot_w = float(np.dot(toward, ob.w))  # < 0: approaching the footwall face

        g = float(self.scenario.ramp.level_drift_gradient)
        drift_dir = np.array([u_hat[0], u_hat[1], -g])
        drift_dir /= float(np.linalg.norm(drift_dir))
        longhole = production.status == "IMPLEMENTED"
        stations = self.station_us(ob) if longhole else []
        pitch = self.station_pitch()
        if longhole and not stations:
            margin = self.scenario.mining.stope_length / 2.0 + self.scenario.mining.minimum_pillar
            return _failed(
                source_revision,
                "orebody strike extent cannot accommodate one planned "
                f"stope-access station (half-length {ob.half_length:g} m < "
                f"stope_length/2 + minimum_pillar = {margin:g} m, rule 72)",
            )

        developments: list[Development] = []
        summaries: list[LevelSummary] = []
        first_failure: str | None = None

        def fail(reason: str) -> None:
            nonlocal first_failure
            if first_failure is None:
                first_failure = reason

        for spec in entries:
            level_id = spec.level_id
            entry = np.asarray(spec.position, dtype=np.float64)
            u_entry = float(np.dot(entry - ob.center, u_hat))

            def drift_point(
                u: float, *, _entry: FloatArray = entry, _u0: float = u_entry
            ) -> FloatArray:
                # rule 71: exact LEVEL_ENTRY anchor; z(u) = z_entry − g·(u − u_entry)
                # (loop variables bound explicitly: the closure is per-level)
                p: FloatArray = _entry + (u - _u0) * u_hat + np.array([0.0, 0.0, -g * (u - _u0)])
                return p

            # breakpoints: stations ∪ entry (merged within weld tolerance). A
            # method without a production lattice develops the generic
            # backbone drift over the strike extent (rule 159).
            end_margin = (
                self.scenario.mining.stope_length / 2.0 + self.scenario.mining.minimum_pillar
            )
            breakpoints = (
                sorted(stations)
                if longhole
                else [-ob.half_length + end_margin, ob.half_length - end_margin]
            )
            if not any(abs(u_entry - s) <= WELD_TOLERANCE for s in breakpoints):
                breakpoints = sorted([*breakpoints, u_entry])
            level_valid = True

            # -- drift pieces (split at every breakpoint, rule 73) ---------- #
            piece_count = 0
            for i in range(len(breakpoints) - 1):
                u0, u1 = breakpoints[i], breakpoints[i + 1]
                pts = _sample_line(drift_point(u0), drift_point(u1))
                length_3d, mean_signed, max_abs = _polyline_stats(pts)
                cl_invalid, field_cost = self._centerline_and_cost(self.drift_ev, pts)
                env = self._envelope(self.drift_ev, pts, drift_dir)
                valid = cl_invalid == 0 and env.hard == 0 and env.above == 0
                if not valid:
                    level_valid = False
                    fail(
                        f"{level_id} drift piece [{u0:.1f}, {u1:.1f}] violates hard "
                        f"constraints ({cl_invalid} centerline, {env.hard} envelope, "
                        f"{env.above} above-terrain)"
                    )
                developments.append(
                    Development(
                        id=f"DRIFT:{level_id}:{piece_count:02d}",
                        kind=DevelopmentKind.DRIFT,
                        level_id=level_id,
                        from_u=u0,
                        to_u=u1,
                        centerline=Centerline(points=[float(v) for v in pts.ravel()]),
                        length3d=length_3d,
                        mean_gradient_signed=mean_signed,
                        max_abs_gradient=max_abs,
                        report=DevelopmentReport(
                            start_weld_error=0.0,
                            centerline_invalid_samples=cl_invalid,
                            envelope_hard_violations=env.hard,
                            envelope_above_terrain=env.above,
                            field_cost=field_cost,
                            valid=valid,
                            failure_reason=None
                            if valid
                            else ("CENTERLINE" if cl_invalid else "ENVELOPE"),
                        ),
                    )
                )
                piece_count += 1

            # -- crosscuts (one per planned station, rule 72) ---------------- #
            crosscut_count = 0
            for u_s in stations:
                k = round(u_s / pitch)
                start = drift_point(u_s)
                w_s = float(np.dot(start - ob.center, ob.w))
                t = (ob.half_thickness - w_s) / d_dot_w
                reason: str | None = None
                if t <= 0.0:
                    reason = "station is not on the footwall side of the orebody"
                end = start + t * toward
                pts = _sample_line(start, end)
                sdf_end = float(ob.signed_distance(end[None, :])[0])
                sdf_pre = ob.signed_distance(pts[:-1])
                interior = int(np.sum(sdf_pre < -1e-9))
                # start weld against the drift breakpoint (exact by construction)
                weld = float(np.linalg.norm(start - drift_point(u_s)))
                cl_invalid, field_cost = self._centerline_and_cost(self.crosscut_ev, pts)
                env = self._envelope(self.crosscut_ev, pts, toward)
                length_3d, mean_signed, max_abs = _polyline_stats(pts)
                if reason is None and abs(sdf_end) > TERMINAL_SDF_TOLERANCE:
                    reason = f"terminal |sdf| {abs(sdf_end):.3e} m exceeds tolerance"
                if reason is None and interior > 0:
                    reason = "pre-terminal centerline passes through the orebody"
                if reason is None and weld > WELD_TOLERANCE:
                    reason = f"start weld error {weld:.3e} m"
                if reason is None and cl_invalid > 0:
                    reason = f"{cl_invalid} centerline samples violate hard constraints"
                if reason is None and (env.hard > 0 or env.above > 0):
                    reason = (
                        f"hard excavation envelope ({env.hard} hard, {env.above} above-terrain)"
                    )
                if reason is not None:
                    level_valid = False
                    fail(f"{level_id} crosscut S{k:+03d}: {reason}")
                developments.append(
                    Development(
                        id=f"CROSSCUT:{level_id}:S{k:+03d}",
                        kind=DevelopmentKind.CROSSCUT,
                        level_id=level_id,
                        station_index=k,
                        station_u=u_s,
                        from_u=u_s,
                        to_u=u_s,
                        centerline=Centerline(points=[float(v) for v in pts.ravel()]),
                        length3d=length_3d,
                        mean_gradient_signed=mean_signed,
                        max_abs_gradient=max_abs,
                        report=DevelopmentReport(
                            start_weld_error=weld,
                            centerline_invalid_samples=cl_invalid,
                            envelope_hard_violations=env.hard,
                            envelope_above_terrain=env.above,
                            terminal_sdf=abs(sdf_end),
                            interior_breach_samples=interior,
                            field_cost=field_cost,
                            valid=reason is None,
                            failure_reason=reason,
                        ),
                    )
                )
                crosscut_count += 1

            summaries.append(
                LevelSummary(
                    level_id=level_id,
                    candidate_id=spec.candidate_id,
                    entry=(float(entry[0]), float(entry[1]), float(entry[2])),
                    entry_u=u_entry,
                    drift_piece_count=piece_count,
                    crosscut_count=crosscut_count,
                    valid=level_valid,
                )
            )

        drifts = [d for d in developments if d.kind is DevelopmentKind.DRIFT]
        crosscuts = [d for d in developments if d.kind is DevelopmentKind.CROSSCUT]
        metrics = LevelsMetrics(
            level_count=len(summaries),
            development_count=len(developments),
            drift_piece_count=len(drifts),
            crosscut_count=len(crosscuts),
            station_pitch=pitch,
            stations_per_level=len(stations),
            total_drift_length3d=float(math.fsum(d.length3d for d in drifts)),
            total_crosscut_length3d=float(math.fsum(d.length3d for d in crosscuts)),
        )
        return LevelsPayload(
            status="SUCCESS" if first_failure is None else "FAILED",
            failure_reason=first_failure,
            source_revision=source_revision,
            entry_source=entry_source,
            production_development=production,
            developments=developments,
            levels=summaries,
            metrics=metrics,
        )
