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

* A mining method without an implemented production lattice (CUT_AND_FILL
  and every other reserved method) develops the GENERIC footwall backbone
  drift over the orebody strike extent minus a fixed end clearance
  (``GENERIC_BACKBONE_END_CLEARANCE``). ``stope_length`` / ``minimum_pillar``
  are LONGHOLE production parameters and never influence the generic
  backbone extent (rule 159).

The drift is emitted as PIECES split at every station/entry breakpoint, so
each Phase 08 MineNetwork DRIFT edge maps 1:1 onto a development in this
artifact (rule 73) and every graph edge owns exactly one centerline span.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import numpy.typing as npt

from minegen.core.enums import MiningMethodType
from minegen.core.models import Scenario
from minegen.design.cost_field import DesignCostEvaluator
from minegen.design.profile import boundary_points, build_profile, required_clearance
from minegen.layout.families import build_footwall_track
from minegen.layout.levels import LevelSections, required_levels
from minegen.layout.sections import (
    TRACE_RESAMPLE_SPACING,
    OffsetTrace,
    SectionGeometryError,
    resolve_section_resolution,
)
from minegen.levels.models import (
    Centerline,
    Development,
    DevelopmentKind,
    DevelopmentReport,
    ExcludedStation,
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
#: generic backbone end clearance from the orebody strike extent (m). Shared
#: with the level-access anchor placement; independent of every production
#: parameter (rule 159). Bounded by a quarter of the strike span so a tiny
#: body still gets a positive-length backbone.
GENERIC_BACKBONE_END_CLEARANCE = 5.0
#: bounded crosscut inward-normal probe (rule 180): each perpendicular of the
#: station's local trace tangent is probed to CROSSCUT_PROBE_FACTOR × the
#: trace's own contact distance at that chainage (floored by the stand-off).
#: The factor bounds the deterministic contains() march; it is a probe
#: budget, never an engineering distance.
CROSSCUT_PROBE_FACTOR = 2.0
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
    Phase 05 segment end. ``anchor`` is the access's persisted
    level-development anchor payload (Phase 20C.2A): a curved anchor
    (non-null ``traceChainage``) declares the SECTION_FOOTWALL_OFFSET_TRACE
    development-geometry contract; a TABULAR rule 43 anchor and the LEGACY
    path leave it to the exact strike-line contract."""

    level_id: str
    position: FloatArray
    candidate_id: str
    anchor: dict[str, Any] | None = None


def entries_from_level_accesses(accesses_payload: dict[str, Any]) -> list[LevelEntrySpec]:
    out: list[LevelEntrySpec] = []
    for acc in accesses_payload["accesses"]:
        if acc.get("status") != "OK" or acc.get("centerline") is None:
            continue
        pts = np.asarray(acc["centerline"]["points"], dtype=np.float64).reshape(-1, 3)
        out.append(
            LevelEntrySpec(
                str(acc["levelId"]),
                pts[-1].copy(),
                str(accesses_payload.get("candidateId") or ""),
                anchor=acc.get("anchor"),
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


def _ray_contact(
    orebody: Orebody, start: FloatArray, direction: FloatArray, max_len: float
) -> tuple[FloatArray, float] | None:
    """First orebody contact along a horizontal ray: coarse march (0.5 m)
    to the first ``contains`` hit, then bisection to a ≤ 1e-6 m bracket.
    The returned terminal is the OUTSIDE end of the bracket (never inside
    the ore); the bracket width is returned as the contact gap."""
    step = 0.5
    n = max(2, math.ceil(max_len / step) + 1)
    ts = np.linspace(0.0, max_len, n)
    pts = start[None, :] + ts[:, None] * direction[None, :]
    inside = orebody.contains(pts)
    if not bool(inside.any()):
        return None
    first = int(np.argmax(inside))
    if first == 0:  # the drift itself sits inside the ore — a real defect
        return start.copy(), 0.0
    t_out, t_in = float(ts[first - 1]), float(ts[first])
    for _ in range(40):
        t_mid = 0.5 * (t_out + t_in)
        q = start + t_mid * direction
        if bool(orebody.contains(q[None, :])[0]):
            t_in = t_mid
        else:
            t_out = t_mid
    return start + t_out * direction, t_in - t_out


#: outcome of the rule 180 inward probe: either ``(unit direction, (terminal,
#: gap))`` for a decided side, or ``(code, message)`` — codes
#: STATION_INSIDE_ORE / INWARD_AMBIGUOUS (per-station HARD failures) and
#: NO_PERPENDICULAR_ORE_SUPPORT (rule 141 precedent: the station is reported
#: and excluded from the REQUIRED lattice, never silently dropped).
_InwardResult = tuple["FloatArray", tuple["FloatArray", float]] | tuple[str, str]


def _inward_contact(
    orebody: Orebody, start: FloatArray, tangent: FloatArray, probe_len: float
) -> _InwardResult:
    """Rule 180 crosscut inward decision (PR #24 follow-up §1): probe BOTH
    horizontal perpendiculars of the local trace ``tangent`` with the same
    bounded ``contains()`` ray march that terminates the crosscut. Returns
    ``(unit direction, (terminal, gap))`` when exactly one side contacts
    ore; otherwise a typed ``(code, message)`` — a station inside the ore,
    ore on both perpendicular sides, or ore on neither. Never a
    nearest-cell fallback."""
    normal = np.array([-float(tangent[1]), float(tangent[0]), 0.0])
    if bool(orebody.contains(start[None, :])[0]):
        return ("STATION_INSIDE_ORE", "station lies inside the orebody footprint")
    hit_pos = _ray_contact(orebody, start, normal, probe_len)
    hit_neg = _ray_contact(orebody, start, -normal, probe_len)
    if hit_pos is not None and hit_neg is not None:
        return (
            "INWARD_AMBIGUOUS",
            f"inward normal ambiguous: ore contact on both perpendicular "
            f"sides of the local tangent within {probe_len:.1f} m",
        )
    if hit_pos is None and hit_neg is None:
        return (
            "NO_PERPENDICULAR_ORE_SUPPORT",
            f"no orebody contact within {probe_len:.1f} m along either "
            "perpendicular of the local tangent",
        )
    return (normal, hit_pos) if hit_pos is not None else (-normal, hit_neg)  # type: ignore[return-value]


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

    @staticmethod
    def generic_backbone_extent(orebody: TabularOrebody) -> tuple[float, float]:
        """Along-strike ``[u0, u1]`` of the generic backbone drift: the orebody
        strike extent minus a fixed end clearance. No production parameter
        (``stope_length``, ``minimum_pillar``) enters here (rule 159)."""
        half = float(orebody.half_length)
        clearance = min(GENERIC_BACKBONE_END_CLEARANCE, 0.25 * (2.0 * half))
        return (-half + clearance, half - clearance)

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
        entry_source: Literal["LEGACY_RAMP_SEGMENT", "LEVEL_ACCESS"]
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
        # Phase 20C.2A dispatch — by the AVAILABLE development-geometry
        # contract, not by orebody type: entries carrying curved anchors
        # (non-null traceChainage) are developed along the section-trace
        # backbone; TABULAR rule 43 entries keep the exact strike line.
        curved = [
            e for e in entries if e.anchor is not None and e.anchor.get("traceChainage") is not None
        ]
        if curved:
            if len(curved) != len(entries):
                return _failed(
                    source_revision,
                    "MIXED_DEVELOPMENT_GEOMETRY: level entries mix curved section-"
                    "trace anchors with straight rule 43 anchors — one selection "
                    "cannot carry two backbone contracts",
                )
            return self._build_curved(entries, source_revision, entry_source, production)
        if not isinstance(self.orebody, TabularOrebody):
            return _failed(
                source_revision,
                "SECTION_TRACE_ANCHORS_REQUIRED: a non-TABULAR orebody is developed "
                "along its curved section-trace anchors (Phase 20C.2A), which only "
                "the layout-v2 level-access artifact provides; the legacy ramp path "
                "cannot develop this orebody",
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
            # backbone drift over the strike extent minus a fixed end
            # clearance — never a stope / pillar margin (rule 159).
            breakpoints = sorted(stations) if longhole else list(self.generic_backbone_extent(ob))
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
            development_geometry="TABULAR_RULE_43",
            production_development=production,
            developments=developments,
            levels=summaries,
            metrics=metrics,
        )

    # -- curved section-trace development (Phase 20C.2A) --------------------- #

    def _curved_drift_points(
        self, off: OffsetTrace, c_a: float, c_b: float, c_entry: float, entry_z: float, g: float
    ) -> FloatArray:
        """Drift piece along the offset trace between chainages ``c_a`` and
        ``c_b`` (exact interpolated endpoints, trace vertices in between).
        ``z(c) = z_entry − g·(c − c_entry)`` along the canonical +chainage
        direction (rule 71 analogue); the trace XY is never moved. Interior
        vertices keep a quarter-spacing separation from the exact endpoints
        so a breakpoint next to a trace vertex cannot create a degenerate
        sub-millimetre segment (which would read as an arbitrary ring turn)."""
        gap = 0.25 * TRACE_RESAMPLE_SPACING
        inner = off.chainage[(off.chainage > c_a + gap) & (off.chainage < c_b - gap)]
        cs = np.concatenate([[c_a], inner, [c_b]])
        pts = np.empty((cs.shape[0], 3))
        for i, c in enumerate(cs):
            pts[i] = off.point_at(float(c))
        pts[:, 2] = entry_z - g * (cs - c_entry)
        return pts

    def _envelope_poly(self, ev: DesignCostEvaluator, points: FloatArray) -> _EnvelopeCheck:
        """Per-point-tangent excavation envelope for a CURVED centerline."""
        tangents = np.diff(points, axis=0)
        tangents = np.vstack([tangents, tangents[-1:]])
        boundary = boundary_points(points, tangents, self.shape).reshape(-1, 3)
        hard, above = ev.envelope_masks(boundary)
        return _EnvelopeCheck(hard=int(hard.sum()), above=int(above.sum()))

    def _ray_contact(
        self, start: FloatArray, direction: FloatArray, max_len: float
    ) -> tuple[FloatArray, float] | None:
        return _ray_contact(self.orebody, start, direction, max_len)

    def _build_curved(
        self,
        entries: list[LevelEntrySpec],
        source_revision: str,
        entry_source: Literal["LEGACY_RAMP_SEGMENT", "LEVEL_ACCESS"],
        production: ProductionDevelopment,
    ) -> LevelsPayload:
        """Level development along the curved SECTION_FOOTWALL_OFFSET_TRACE
        backbone (Phase 20C.2A A4). The offset trace is rebuilt
        deterministically from the same authoritative inputs stage 4 used
        (orebody + section resolution + the anchor's RECORDED stand-off) and
        the persisted entry must sit on it at its recorded chainage — a
        mismatch fails closed (rule 172 analogue), never a re-anchor.

        * DRIFT: follows the offset trace; ``level_drift_gradient`` applies
          along chainage from the entry in the canonical +chainage direction;
          the entry never moves.
        * LONGHOLE stations: the ``stope_length + minimum_pillar`` pitch on
          CURVED drift chainage, symmetric about the trace midpoint, keeping
          the stope + end-pillar margin inside the trace span (rule 72
          analogue — an access-layout proxy, not stope design).
        * CROSSCUT: horizontal from each station along the LOCAL inward
          normal — the ± perpendicular of the offset trace's local tangent,
          the ore side decided by bounded ``contains()`` probes — terminated
          at the first ``contains`` contact refined by bisection to ≤ 1e-6 m.
          A station inside the ore or with ore on BOTH perpendiculars is a
          typed per-station failure, never a fallback; a station where
          NEITHER perpendicular finds ore within the probe budget is
          reported and EXCLUDED from the required lattice
          (NO_PERPENDICULAR_ORE_SUPPORT, rule 141 precedent), and a level
          whose planned stations are ALL excluded fails typed.

        Every development passes the same hard validation as the TABULAR
        path (centerline context, excavation envelope); nothing is relaxed
        and an invalid required development fails the artifact explicitly."""
        sc = self.scenario
        base_standoff = (
            sc.layout.access.anchor_standoff
            if sc.layout.access.anchor_standoff is not None
            else sc.ramp.footwall_access_offset
        )
        try:
            resolution = resolve_section_resolution(
                float(sc.layout.section_sampling_spacing), float(base_standoff)
            )
            levels = required_levels(
                self.orebody,
                sc.mining.sublevel_interval,
                sc.design.top_mining_margin,
                sc.design.bottom_mining_margin,
            )
            sections = LevelSections(
                self.orebody, levels, float(sc.layout.section_sampling_spacing), resolution
            )
        except SectionGeometryError as err:
            return _failed(source_revision, f"{err.code}: {err.detail}")
        track = build_footwall_track(self.orebody, sections)
        if track is None:
            return _failed(source_revision, "no footwall reference track for this orebody")
        by_id = {lv.level_id: lv for lv in levels}
        g = float(sc.ramp.level_drift_gradient)
        longhole = production.status == "IMPLEMENTED"
        pitch = self.station_pitch()
        station_margin = sc.mining.stope_length / 2.0 + sc.mining.minimum_pillar

        developments: list[Development] = []
        summaries: list[LevelSummary] = []
        first_failure: str | None = None

        def fail(reason: str) -> None:
            nonlocal first_failure
            if first_failure is None:
                first_failure = reason

        for spec in entries:
            level_id = spec.level_id
            lv = by_id.get(level_id)
            anchor = spec.anchor or {}
            if lv is None:
                return _failed(source_revision, f"unknown level id {level_id!r} in level accesses")
            entry = np.asarray(spec.position, dtype=np.float64)
            standoff = float(anchor["standoff"])
            c_entry = float(anchor["traceChainage"])
            try:
                off = sections.offset_trace(
                    lv,
                    track.w_h,
                    standoff,
                    2.0 * GENERIC_BACKBONE_END_CLEARANCE,
                    # rule 172: the SAME clearance policy that certified the
                    # selection (the service wires the candidate policy into
                    # both evaluators) measures the backbone stand-off
                    self.drift_ev.clearance.signed_clearance,
                    "SELECTED",
                    required_clearance(sc.design, sc.ramp, sc.tunnel_profile),
                )
            except SectionGeometryError as err:
                return _failed(source_revision, f"{err.code}: {err.detail}")
            # rule 172 analogue: the rebuilt trace must reproduce the
            # persisted entry at its recorded chainage — fail closed
            weld = float(np.linalg.norm(off.point_at(c_entry) - entry))
            if weld > WELD_TOLERANCE:
                return _failed(
                    source_revision,
                    f"SECTION_TRACE_MISMATCH: level {level_id} entry deviates "
                    f"{weld:.3e} m from the rebuilt offset trace at chainage "
                    f"{c_entry:.2f} m (stand-off {standoff:g} m) — the level-access "
                    "artifact and the section geometry disagree",
                )
            span = off.total_length
            clearance = min(GENERIC_BACKBONE_END_CLEARANCE, 0.25 * span)
            mid = 0.5 * span
            planned: list[float] = []
            if longhole:
                k_max = math.floor((mid - station_margin) / pitch + 1e-9)
                planned = [mid + k * pitch for k in range(-k_max, k_max + 1)] if k_max >= 0 else []
                if not planned:
                    return _failed(
                        source_revision,
                        f"offset trace span {span:.1f} m at level {level_id} cannot "
                        "accommodate one planned stope-access station "
                        f"(span/2 < stope_length/2 + minimum_pillar = {station_margin:g} m)",
                    )
            # rule 180 station confirmation (rule 141 precedent, PR #24
            # follow-up): a planned station where NEITHER horizontal
            # perpendicular of the local trace tangent finds ore within the
            # bounded probe has no perpendicular crosscut — the offset level
            # set wraps around the body's tapered ends, so end stations can
            # sit past the local ore extent. Such a station is reported and
            # EXCLUDED from the REQUIRED lattice (NO_PERPENDICULAR_ORE_SUPPORT),
            # never silently dropped. Ambiguous / inside-ore stations remain
            # per-station HARD failures in the crosscut loop below.
            required: list[tuple[float, int, FloatArray, _InwardResult]] = []
            excluded: list[ExcludedStation] = []
            for c_s in planned:
                k = round((c_s - mid) / pitch)
                start = self._curved_drift_points(off, c_s, c_s, c_entry, float(entry[2]), g)[0]
                tangent = off.tangent_at(c_s)
                # bounded deterministic probe: the trace's own contact
                # distance at this chainage sets the scale (≈ the stand-off)
                d_ref = float(np.interp(c_s, off.chainage, off.ore_contact_distance))
                probe_len = max(CROSSCUT_PROBE_FACTOR * d_ref, standoff)
                decided = _inward_contact(self.orebody, start, tangent, probe_len)
                if isinstance(decided[0], str) and decided[0] == "NO_PERPENDICULAR_ORE_SUPPORT":
                    excluded.append(
                        ExcludedStation(
                            station_index=k,
                            station_u=c_s,
                            reason="NO_PERPENDICULAR_ORE_SUPPORT",
                            probe_length=probe_len,
                        )
                    )
                    continue
                required.append((c_s, k, start, decided))
            if longhole and planned and not required:
                return _failed(
                    source_revision,
                    f"level {level_id}: every planned crosscut station lacks "
                    f"perpendicular ore support ({len(excluded)} stations excluded)",
                )
            station_chainages = [c for c, _, _, _ in required]
            breakpoints = sorted(station_chainages) if longhole else [clearance, span - clearance]
            if not any(abs(c_entry - s) <= WELD_TOLERANCE for s in breakpoints):
                breakpoints = sorted([*breakpoints, c_entry])
            level_valid = True

            # -- drift pieces along the trace (rule 73 split) --------------- #
            piece_count = 0
            for i in range(len(breakpoints) - 1):
                c0, c1 = breakpoints[i], breakpoints[i + 1]
                pts = self._curved_drift_points(off, c0, c1, c_entry, float(entry[2]), g)
                length_3d, mean_signed, max_abs = _polyline_stats(pts)
                cl_invalid, field_cost = self._centerline_and_cost(self.drift_ev, pts)
                env = self._envelope_poly(self.drift_ev, pts)
                valid = cl_invalid == 0 and env.hard == 0 and env.above == 0
                if not valid:
                    level_valid = False
                    fail(
                        f"{level_id} drift piece [{c0:.1f}, {c1:.1f}] violates hard "
                        f"constraints ({cl_invalid} centerline, {env.hard} envelope, "
                        f"{env.above} above-terrain)"
                    )
                developments.append(
                    Development(
                        id=f"DRIFT:{level_id}:{piece_count:02d}",
                        kind=DevelopmentKind.DRIFT,
                        level_id=level_id,
                        from_u=c0,
                        to_u=c1,
                        centerline=Centerline(points=[float(v) for v in pts.ravel()]),
                        length3d=length_3d,
                        mean_gradient_signed=mean_signed,
                        max_abs_gradient=max_abs,
                        report=DevelopmentReport(
                            start_weld_error=weld if abs(c0 - c_entry) <= WELD_TOLERANCE else 0.0,
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

            # -- crosscuts: local inward normal to the ore contact ---------- #
            # Approved rule 180 contract (PR #24 follow-up §1): the crosscut
            # direction is the ± horizontal PERPENDICULAR of the offset
            # trace's LOCAL TANGENT at the station; the ore side is decided
            # by contains() probes (the same ray+bisection that terminates
            # the crosscut). A station inside the ore or with ore on BOTH
            # perpendicular sides is a typed per-station failure — never a
            # nearest-cell fallback.
            crosscut_count = 0
            for c_s, k, start, decided in required:
                reason: str | None = None
                direction = np.zeros(3)
                if isinstance(decided[0], str):
                    reason = str(decided[1])
                    end, gap = start + 1.0 * direction, math.inf
                else:
                    direction, (end, gap) = decided
                pts = _sample_line(start, end)
                inside_pre = self.orebody.contains(pts[:-1])
                interior = int(np.sum(inside_pre))
                cl_invalid, field_cost = self._centerline_and_cost(self.crosscut_ev, pts)
                env = self._envelope(self.crosscut_ev, pts, direction)
                length_3d, mean_signed, max_abs = _polyline_stats(pts)
                if reason is None and length_3d < 1e-6:
                    reason = "station lies on the ore contact — zero-length crosscut"
                if reason is None and gap > 1e-6:
                    reason = f"terminal contact bracket {gap:.3e} m exceeds tolerance"
                if reason is None and interior > 0:
                    reason = "pre-terminal centerline passes through the orebody"
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
                        station_u=c_s,
                        from_u=c_s,
                        to_u=c_s,
                        centerline=Centerline(points=[float(v) for v in pts.ravel()]),
                        length3d=length_3d,
                        mean_gradient_signed=mean_signed,
                        max_abs_gradient=max_abs,
                        report=DevelopmentReport(
                            start_weld_error=0.0,
                            centerline_invalid_samples=cl_invalid,
                            envelope_hard_violations=env.hard,
                            envelope_above_terrain=env.above,
                            terminal_contact_gap=None if math.isinf(gap) else gap,
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
                    entry_u=c_entry,
                    drift_piece_count=piece_count,
                    crosscut_count=crosscut_count,
                    valid=level_valid,
                    excluded_stations=excluded,
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
            stations_per_level=(
                max((s.crosscut_count for s in summaries), default=0) if longhole else 0
            ),
            total_drift_length3d=float(math.fsum(d.length3d for d in drifts)),
            total_crosscut_length3d=float(math.fsum(d.length3d for d in crosscuts)),
        )
        return LevelsPayload(
            status="SUCCESS" if first_failure is None else "FAILED",
            failure_reason=first_failure,
            source_revision=source_revision,
            entry_source=entry_source,
            development_geometry="SECTION_FOOTWALL_OFFSET_TRACE",
            production_development=production,
            developments=developments,
            levels=summaries,
            metrics=metrics,
        )
