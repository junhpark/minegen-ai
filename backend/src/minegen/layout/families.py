"""Parametric ramp families for layout-v2 (Phase 20A, rules 142–143).

Three genuinely different geometric constructions, each producing ONE
continuous (position AND heading) discretized centerline from the portal to
the deepest required level:

SPIRAL
    a drifting helix: constant plan radius ``R = ΔZ / (2π·g·n)`` derived from
    the required level interval ΔZ, the target gradient ``g`` and the turns
    per level ``n`` (never sampled); its vertical axis tracks the footwall
    reference of the orebody with depth so the crossing stays near the ore.

LONGITUDINAL
    one-direction along-strike descent whose plan direction is tilted by the
    measured footwall drift per metre of descent, so vertical descent and plan
    geometry are coupled; no reversal ever.

SWITCHBACK
    antiparallel straight legs stacked in one corridor, joined by 180°
    hairpin arcs of the minimum turning radius; the straight length of every
    cycle is DERIVED after subtracting the hairpin's horizontal arc length
    from the horizontal travel the gradient needs for the cycle's drop.

Every family starts with the same approach connector from the authoritative
portal (straight → arc, tangent-continuous into the family's first piece).
All geometry is built from two primitives integrated in closed form — a
straight and a circular arc, each descending at a constant gradient — so
continuity is exact by construction and then re-measured on the delivered
polyline by ``layout.geometry`` (rule 144).

Nothing here decides feasibility: constructors return either a
``FamilyGeometry`` or a typed ``FamilyInfeasible`` reason; the delivered
centerline is judged by the search stage.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.core.enums import FAMILY_ORDER as FAMILY_ORDER
from minegen.core.enums import RampFamily as RampFamily
from minegen.core.models import LayoutV2Config, RampConstraints
from minegen.layout.levels import LevelSections, RequiredLevel, level_intervals
from minegen.world.orebody import Orebody

FloatArray = npt.NDArray[np.float64]

#: Phase 20B.1 C-1 (roadmap S1): the PERMANENT main-ramp corridor's default
#: stand-off exceeds the level-development anchor plane
#: (``ramp.footwall_access_offset``) by this many tunnel widths. Three
#: SPATIAL terms (spatial + spatial, never a path-length term — rule 168):
#: one width for the two lateral half-spans of ramp and level development,
#: a two-width rock pillar between their envelopes, and a three-width
#: turnout-taper allowance — the lateral offset a minimum-radius turnout
#: develops while still inside its own geometric taper,
#: ``R·(1 − cos(s*/R)) ≈ 15 m ≈ 3 widths`` for the default R = 18 m — so an
#: access can hold the full pillar over its ENTIRE post-taper run, not only
#: at its terminal. A planning default, not a statutory value. Before the
#: audit both stand-offs defaulted to the SAME 20 m, which made the main
#: ramp and every level drift collinear (measured envelope separation
#: −4.9 m, commit O baseline).
RAMP_CORRIDOR_MARGIN_WIDTHS = 6.0


def effective_footwall_standoff(cfg: LayoutV2Config, ramp: RampConstraints) -> tuple[float, str]:
    """Main-ramp corridor stand-off and its provenance: ``EXPLICIT`` or
    ``DEFAULT_OFFSET_PLUS_CORRIDOR_MARGIN`` = ``footwall_access_offset +
    RAMP_CORRIDOR_MARGIN_WIDTHS × tunnel_width``."""
    if cfg.footwall_standoff is not None:
        return float(cfg.footwall_standoff), "EXPLICIT"
    return (
        float(ramp.footwall_access_offset) + RAMP_CORRIDOR_MARGIN_WIDTHS * float(ramp.tunnel_width),
        "DEFAULT_OFFSET_PLUS_CORRIDOR_MARGIN",
    )


class InfeasibleReason(StrEnum):
    GRADE_LIMIT = "GRADE_LIMIT"
    TURN_RADIUS = "TURN_RADIUS"
    WORLD_BOUNDS = "WORLD_BOUNDS"
    SURFACE_COVER = "SURFACE_COVER"
    ABOVE_TERRAIN = "ABOVE_TERRAIN"
    RESTRICTED_ZONE = "RESTRICTED_ZONE"
    OREBODY_CLEARANCE = "OREBODY_CLEARANCE"
    NO_RL_CROSSING = "NO_RL_CROSSING"
    NO_OREBODY_SECTION_AT_LEVEL = "NO_OREBODY_SECTION_AT_LEVEL"
    ACCESS_REACH_EXCEEDED = "ACCESS_REACH_EXCEEDED"
    CONNECTION_POINT_INVALID = "CONNECTION_POINT_INVALID"
    LEVEL_SERVICE_INFEASIBLE = "LEVEL_SERVICE_INFEASIBLE"
    #: Phase 20B: a required level has no valid ramp junction + access branch
    LEVEL_ACCESS_INFEASIBLE = "LEVEL_ACCESS_INFEASIBLE"
    LEVEL_INTERVAL_NONUNIFORM = "LEVEL_INTERVAL_NONUNIFORM"
    NO_REQUIRED_LEVELS = "NO_REQUIRED_LEVELS"
    LEG_TOO_SHORT = "LEG_TOO_SHORT"
    APPROACH_INFEASIBLE = "APPROACH_INFEASIBLE"
    LOCAL_DETOUR_INFEASIBLE = "LOCAL_DETOUR_INFEASIBLE"
    GEOMETRY_ASSEMBLY = "GEOMETRY_ASSEMBLY"


# --------------------------------------------------------------------------- #
# Primitive integration (closed form, tangent-continuous)
# --------------------------------------------------------------------------- #


@dataclass
class Pose:
    x: float
    y: float
    z: float
    heading: float  # clockwise azimuth from +Y (rad)

    @property
    def xy(self) -> FloatArray:
        return np.array([self.x, self.y])

    @property
    def direction(self) -> FloatArray:
        return np.array([math.sin(self.heading), math.cos(self.heading)])


class Path:
    """Accumulates sampled points; every primitive appends its samples and
    advances the pose. Gradients are magnitudes; the ramp always descends."""

    def __init__(self, start: Pose, spacing: float) -> None:
        self.pose = start
        self.spacing = spacing
        self.points: list[FloatArray] = [np.array([start.x, start.y, start.z])]
        self.pieces: list[dict[str, Any]] = []

    def straight(self, length: float, gradient: float, label: str) -> None:
        if length <= 0.0:
            return
        n = max(1, math.ceil(length / self.spacing))
        d = self.pose.direction
        step = length / n
        for i in range(1, n + 1):
            s = step * i
            self.points.append(
                np.array(
                    [self.pose.x + d[0] * s, self.pose.y + d[1] * s, self.pose.z - gradient * s]
                )
            )
        self.pose = Pose(
            self.pose.x + d[0] * length,
            self.pose.y + d[1] * length,
            self.pose.z - gradient * length,
            self.pose.heading,
        )
        self.pieces.append({"kind": "STRAIGHT", "label": label, "horizontalLength": length})

    def arc(self, radius: float, angle: float, gradient: float, label: str) -> None:
        """Circular arc of signed heading change ``angle`` (positive = CW =
        clockwise azimuth increase = right turn) at constant plan radius.
        Descent is applied per CHORD of the delivered polyline (``dz =
        gradient × chord``), so the delivered centerline — the acceptance
        authority — carries exactly the target gradient on every edge; the
        arc's total drop is therefore ``gradient × Σ chords`` (≈ 0.02 %
        below ``gradient × R·|angle|`` at 2 m sampling)."""
        if abs(angle) <= 0.0:
            return
        arc_len = radius * abs(angle)
        n = max(1, math.ceil(arc_len / self.spacing))
        sense = 1.0 if angle > 0 else -1.0
        h0 = self.pose.heading
        # center is to the right (CW) or left (CCW) of the current direction
        d = self.pose.direction
        right = np.array([d[1], -d[0]])  # right-hand normal in (E, N)
        c = self.pose.xy + sense * radius * right
        z = self.pose.z
        prev = self.pose.xy
        for i in range(1, n + 1):
            h = h0 + angle * i / n
            dh = np.array([math.sin(h), math.cos(h)])
            r = np.array([dh[1], -dh[0]])
            p = c - sense * radius * r
            z -= gradient * float(np.linalg.norm(p - prev))
            prev = p
            self.points.append(np.array([p[0], p[1], z]))
        self.pose = Pose(float(prev[0]), float(prev[1]), z, h0 + angle)
        self.pieces.append(
            {
                "kind": "ARC",
                "label": label,
                "radius": radius,
                "angleDeg": math.degrees(angle),
                "horizontalLength": arc_len,
            }
        )

    def drifting_helix(
        self,
        axis_at: Any,
        radius: float,
        sense: float,
        gradient: float,
        z_stop: float,
        label: str,
    ) -> None:
        """Helix whose axis ``axis_at(z) -> (x, y)`` may drift with depth.
        ``sense`` +1 = CW (clockwise in plan = decreasing math angle about
        the axis), −1 = CCW. Angular step ``spacing / R``; descent is
        chord-exact (see ``arc``) and the last step lands EXACTLY on
        ``z_stop``. The pose must lie on the circle with a tangent heading
        (the approach connector guarantees it)."""
        if self.pose.z <= z_stop:
            return
        dtheta = self.spacing / radius
        a0 = np.asarray(axis_at(self.pose.z), dtype=np.float64)
        rel = self.pose.xy - a0
        theta = math.atan2(rel[1], rel[0])
        z = self.pose.z
        prev = self.pose.xy
        total_angle = 0.0
        while True:
            theta_next = theta - sense * dtheta
            a = np.asarray(axis_at(z), dtype=np.float64)
            p = a + radius * np.array([math.cos(theta_next), math.sin(theta_next)])
            chord = float(np.linalg.norm(p - prev))
            if z - gradient * chord <= z_stop + 1e-12:
                # final partial step: shrink the angle so the chord drop lands
                # exactly on z_stop (chord ∝ angle to first order; two Newton
                # refinements keep the landing exact to 1e-9 m)
                frac = (z - z_stop) / (gradient * chord) if chord > 0 else 0.0
                for _ in range(3):
                    th = theta - sense * dtheta * frac
                    p = a + radius * np.array([math.cos(th), math.sin(th)])
                    chord = float(np.linalg.norm(p - prev))
                    if chord <= 0.0:
                        break
                    frac *= (z - z_stop) / (gradient * chord)
                theta = theta - sense * dtheta * frac
                total_angle += dtheta * frac
                self.points.append(np.array([p[0], p[1], z_stop]))
                z = z_stop
                prev = p
                break
            z -= gradient * chord
            theta = theta_next
            total_angle += dtheta
            self.points.append(np.array([p[0], p[1], z]))
            prev = p
        last = self.points[-1]
        before = self.points[-2]
        d = last[:2] - before[:2]
        self.pose = Pose(float(last[0]), float(last[1]), float(last[2]), math.atan2(d[0], d[1]))
        self.pieces.append(
            {
                "kind": "HELIX",
                "label": label,
                "radius": radius,
                "turns": total_angle / (2.0 * math.pi),
                "horizontalLength": radius * total_angle,
            }
        )

    def array(self) -> FloatArray:
        return np.asarray(self.points, dtype=np.float64)


# --------------------------------------------------------------------------- #
# Footwall reference track
# --------------------------------------------------------------------------- #


@dataclass
class FootwallTrack:
    """Footwall reference track derived from the numerical level sections
    (never from a global thickness): per level, the footprint centroid
    pushed to the footwall-side edge along the horizontal footwall normal
    ``w_h``. The track used for geometry is the sample-count-weighted LINEAR
    least-squares fit of those per-level references in z — exact for a
    planar (TABULAR / ELLIPSOID) body, and for an irregular body the smooth
    trend that families follow while the numerical level service judges the
    local wobble candidate by candidate. Per-level residuals are kept for
    diagnostics."""

    elevations: FloatArray  # descending, serviceable levels only
    edge_points: FloatArray  # (n, 2) per-level footwall-edge reference
    hanging_points: FloatArray  # (n, 2) per-level hanging-wall-edge reference
    centroids: FloatArray  # (n, 2)
    weights: FloatArray  # (n,) inside-sample counts
    u_h: FloatArray  # horizontal strike direction
    w_h: FloatArray  # horizontal footwall normal (away from the ore)
    strike_half_extent: float  # max |along-strike| footprint extent over levels

    def _fit(self, table: FloatArray) -> tuple[FloatArray, FloatArray]:
        """Weighted linear fit ``table(z) ≈ a + b·z`` → (a, b) per column."""
        z = self.elevations
        if z.shape[0] == 1:
            return np.asarray(table[0], dtype=np.float64), np.zeros(2)
        w = self.weights / float(np.sum(self.weights))
        zm = float(np.sum(w * z))
        dz = z - zm
        var = float(np.sum(w * dz * dz))
        if var <= 1e-12:
            return np.asarray(np.sum(w[:, None] * table, axis=0)), np.zeros(2)
        b = np.sum(w[:, None] * dz[:, None] * table, axis=0) / var
        a = np.sum(w[:, None] * table, axis=0) - b * zm
        return np.asarray(a), np.asarray(b)

    def __post_init__(self) -> None:
        self._edge_ab = self._fit(self.edge_points)
        self._hang_ab = self._fit(self.hanging_points)
        self._cent_ab = self._fit(self.centroids)

    def footwall_edge(self, z: float) -> FloatArray:
        a, b = self._edge_ab
        return np.asarray(a + b * z)

    def hanging_edge(self, z: float) -> FloatArray:
        a, b = self._hang_ab
        return np.asarray(a + b * z)

    def centroid(self, z: float) -> FloatArray:
        a, b = self._cent_ab
        return np.asarray(a + b * z)

    @property
    def lateral_drift_per_metre(self) -> float:
        """Footwall-edge drift along ``w_h`` per metre of DESCENT (positive
        when the edge moves toward the footwall side with depth)."""
        _, b = self._edge_ab
        return -float(b @ self.w_h)

    def residuals(self) -> FloatArray:
        """Per-level distance between the raw edge reference and the fitted
        track (m) — the irregularity the families do not follow."""
        fitted = np.asarray([self.footwall_edge(float(z)) for z in self.elevations])
        return np.asarray(np.linalg.norm(self.edge_points - fitted, axis=1))

    def to_dict(self) -> dict[str, Any]:
        res = self.residuals()
        return {
            "levels": int(self.elevations.shape[0]),
            "lateralDriftPerMetreDescent": self.lateral_drift_per_metre,
            "maxEdgeResidual": float(np.max(res)) if res.size else 0.0,
            "meanEdgeResidual": float(np.mean(res)) if res.size else 0.0,
            "strikeHalfExtent": self.strike_half_extent,
            "uH": self.u_h.tolist(),
            "wH": self.w_h.tolist(),
        }


def build_footwall_track(orebody: Orebody, sections: LevelSections) -> FootwallTrack | None:
    w = np.asarray(orebody.w, dtype=np.float64)
    w_h = w[:2].copy()
    n = float(np.linalg.norm(w_h))
    if n < 1e-9:
        # vertical footwall normal (flat body): fall back to the down-dip direction
        v = np.asarray(orebody.v, dtype=np.float64)[:2]
        n = float(np.linalg.norm(v))
        if n < 1e-9:
            return None
        w_h = -v
    w_h = w_h / float(np.linalg.norm(w_h))
    u_h = np.asarray(orebody.u, dtype=np.float64)[:2]
    u_h = u_h / float(np.linalg.norm(u_h))
    elevations: list[float] = []
    edges: list[FloatArray] = []
    hangings: list[FloatArray] = []
    centroids: list[FloatArray] = []
    weights: list[float] = []
    half_u = 0.0
    for lv in sections.serviceable():
        sec = sections.section(lv)
        c = sec.centroid
        lo_w, hi_w = sec.extent_along(w_h)
        lo_u, hi_u = sec.extent_along(u_h)
        half_u = max(half_u, abs(lo_u), abs(hi_u))
        elevations.append(lv.elevation)
        centroids.append(c)
        edges.append(c + w_h * hi_w)
        hangings.append(c + w_h * lo_w)
        weights.append(float(sec.inside_xy.shape[0]))
    if not elevations:
        return None
    return FootwallTrack(
        elevations=np.asarray(elevations),
        edge_points=np.asarray(edges),
        hanging_points=np.asarray(hangings),
        centroids=np.asarray(centroids),
        weights=np.asarray(weights),
        u_h=u_h,
        w_h=w_h,
        strike_half_extent=half_u,
    )


def rotate(v: FloatArray, deg: float) -> FloatArray:
    """Rotate a horizontal vector CLOCKWISE (azimuth sense) by ``deg``."""
    a = math.radians(deg)
    # clockwise rotation in the (E, N) plane
    return np.array(
        [v[0] * math.cos(a) + v[1] * math.sin(a), -v[0] * math.sin(a) + v[1] * math.cos(a)]
    )


def azimuth_of(v: FloatArray) -> float:
    return math.atan2(float(v[0]), float(v[1]))


# --------------------------------------------------------------------------- #
# Candidate parameters and enumeration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CandidateParams:
    family: RampFamily
    target_gradient: float
    # SPIRAL
    turns_per_level: float | None = None
    turn_sense: str | None = None
    entry_orientation_deg: float | None = None
    # LONGITUDINAL
    orientation: str | None = None
    side: str | None = None
    # SWITCHBACK
    legs_per_level: int | None = None
    principal_orientation_deg: float | None = None
    initial_turn_sense: str | None = None

    @property
    def candidate_id(self) -> str:
        g = f"g{self.target_gradient:.3f}"
        if self.family is RampFamily.SPIRAL:
            return (
                f"SPIRAL-n{self.turns_per_level:g}-{self.turn_sense}-"
                f"e{self.entry_orientation_deg:+g}-{g}"
            )
        if self.family is RampFamily.LONGITUDINAL:
            return f"LONGITUDINAL-{self.orientation}-{self.side}-{g}"
        return (
            f"SWITCHBACK-k{self.legs_per_level}-p{self.principal_orientation_deg:+g}-"
            f"{self.initial_turn_sense}-{g}"
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"family": self.family.value, "targetGradient": self.target_gradient}
        if self.family is RampFamily.SPIRAL:
            d.update(
                turnsPerLevel=self.turns_per_level,
                turnSense=self.turn_sense,
                entryOrientationDeg=self.entry_orientation_deg,
            )
        elif self.family is RampFamily.LONGITUDINAL:
            d.update(orientation=self.orientation, side=self.side)
        else:
            d.update(
                legsPerLevel=self.legs_per_level,
                principalOrientationDeg=self.principal_orientation_deg,
                initialTurnSense=self.initial_turn_sense,
            )
        return d


def enumerate_candidates(cfg: LayoutV2Config) -> list[CandidateParams]:
    """Frozen, finite, deterministic enumeration (rule 142): family order,
    then the declared field order of each grid, target gradient innermost."""
    out: list[CandidateParams] = []
    for n in cfg.spiral.turns_per_level:
        for sense in cfg.spiral.turn_senses:
            for e in cfg.spiral.entry_orientations_deg:
                for g in cfg.target_gradients:
                    out.append(
                        CandidateParams(
                            RampFamily.SPIRAL,
                            g,
                            turns_per_level=n,
                            turn_sense=sense,
                            entry_orientation_deg=e,
                        )
                    )
    for o in cfg.longitudinal.orientations:
        for side in cfg.longitudinal.sides:
            for g in cfg.target_gradients:
                out.append(CandidateParams(RampFamily.LONGITUDINAL, g, orientation=o, side=side))
    for k in cfg.switchback.legs_per_level:
        for p in cfg.switchback.principal_orientations_deg:
            for sense in cfg.switchback.initial_turn_senses:
                for g in cfg.target_gradients:
                    out.append(
                        CandidateParams(
                            RampFamily.SWITCHBACK,
                            g,
                            legs_per_level=k,
                            principal_orientation_deg=p,
                            initial_turn_sense=sense,
                        )
                    )
    ids = [c.candidate_id for c in out]
    if len(set(ids)) != len(ids):
        raise ValueError("layout grid produces duplicate candidate ids")
    return out


# --------------------------------------------------------------------------- #
# Construction context and results
# --------------------------------------------------------------------------- #


@dataclass
class LayoutContext:
    portal: FloatArray  # (3,)
    levels: list[RequiredLevel]  # SERVICEABLE required levels (descending)
    sections: LevelSections
    track: FootwallTrack
    ramp: RampConstraints
    cfg: LayoutV2Config
    world_half_x: float
    world_half_y: float

    @property
    def standoff(self) -> float:
        return effective_footwall_standoff(self.cfg, self.ramp)[0]

    @property
    def z_last(self) -> float:
        return self.levels[-1].elevation

    def inside_world(self, xy: FloatArray) -> bool:
        m = self.cfg.world_margin
        return bool(abs(xy[0]) <= self.world_half_x - m and abs(xy[1]) <= self.world_half_y - m)


@dataclass
class FamilyInfeasible:
    reason: InfeasibleReason
    detail: str


@dataclass
class FamilyGeometry:
    points: FloatArray
    pieces: list[dict[str, Any]]
    derived: dict[str, Any] = field(default_factory=dict)


def _approach(
    path: Path,
    target_xy: FloatArray,
    target_heading: float,
    radius: float,
    gradient: float,
    ctx: LayoutContext,
) -> str | None:
    """Straight → arc connector from the current pose (the portal, free
    heading) onto ``(target_xy, target_heading)``: the circle of radius
    ``radius`` tangent to the target heading at the target lies on the
    left or right; from the portal draw the tangent line to that circle
    whose rotation sense matches, then run the arc to the target. Chooses
    the shorter feasible option deterministically (left tie → right).
    Returns an error string when the portal lies inside both circles."""
    p = path.pose.xy
    d_t = np.array([math.sin(target_heading), math.cos(target_heading)])
    right = np.array([d_t[1], -d_t[0]])
    best: tuple[float, float, float, float] | None = None  # (total, straight, angle, heading)
    for sense in (1.0, -1.0):  # +1 = CW (center to the right of target heading)
        c = target_xy + sense * radius * right
        v = c - p
        dist = float(np.linalg.norm(v))
        if dist <= radius + 1e-9:
            continue
        # tangent from p to the circle consistent with the sense: the tangent
        # point T satisfies |T-c| = R, (T-p)·(T-c) = 0; two solutions, keep the
        # one whose arc sense from T to target matches `sense`
        alpha = math.asin(radius / dist)
        base = math.atan2(v[1], v[0])
        for sign in (1.0, -1.0):
            ang = base + sign * alpha
            dir_t = np.array([math.cos(ang), math.sin(ang)])
            straight = math.sqrt(max(dist * dist - radius * radius, 0.0))
            t_pt = p + dir_t * straight
            heading_in = azimuth_of(dir_t)
            # sense check: for CW (sense=+1) the center must be to the right
            # of the incoming direction
            r_in = np.array([dir_t[1], -dir_t[0]])
            on_right = float((c - t_pt) @ r_in) > 0
            if (sense > 0) != on_right:
                continue
            # signed arc angle from heading_in to target_heading in the sense
            delta = (target_heading - heading_in + math.pi) % (2.0 * math.pi) - math.pi
            if sense > 0 and delta < 0:
                delta += 2.0 * math.pi
            if sense < 0 and delta > 0:
                delta -= 2.0 * math.pi
            total = straight + radius * abs(delta)
            if best is None or total < best[0] - 1e-9:
                best = (total, straight, delta, heading_in)
    if best is None:
        return "portal lies inside the approach turning circle"
    total, straight, delta, heading_in = best
    if straight < ctx.cfg.min_straight_length:
        return f"approach straight {straight:.1f} m shorter than {ctx.cfg.min_straight_length} m"
    path.pose = Pose(path.pose.x, path.pose.y, path.pose.z, heading_in)
    path.straight(straight, gradient, "APPROACH_STRAIGHT")
    path.arc(radius, delta, gradient, "APPROACH_ARC")
    return None


# --------------------------------------------------------------------------- #
# SPIRAL
# --------------------------------------------------------------------------- #


def build_spiral(params: CandidateParams, ctx: LayoutContext) -> FamilyGeometry | FamilyInfeasible:
    assert (
        params.turns_per_level is not None
        and params.turn_sense
        and (params.entry_orientation_deg is not None)
    )
    g = params.target_gradient
    n = params.turns_per_level
    intervals = level_intervals(ctx.levels)
    if len(ctx.levels) < 2:
        return FamilyInfeasible(InfeasibleReason.NO_REQUIRED_LEVELS, "spiral needs ≥ 2 levels")
    dz = intervals[0]
    if max(intervals) - min(intervals) > ctx.cfg.level_interval_tolerance * dz:
        return FamilyInfeasible(
            InfeasibleReason.LEVEL_INTERVAL_NONUNIFORM,
            f"level intervals {min(intervals):.3f}..{max(intervals):.3f} m differ; a constant-"
            "radius helix cannot reconcile them",
        )
    radius = dz / (2.0 * math.pi * g * n)  # rule 143 coupling
    if radius < ctx.ramp.min_turn_radius - 1e-9:
        return FamilyInfeasible(
            InfeasibleReason.TURN_RADIUS,
            f"derived radius {radius:.2f} m < minimum {ctx.ramp.min_turn_radius:g} m "
            f"(ΔZ {dz:g} m, g {g:g}, {n:g} turns/level)",
        )
    sense = 1.0 if params.turn_sense == "CW" else -1.0
    d_hat = rotate(ctx.track.w_h, params.entry_orientation_deg)
    offset = ctx.standoff + radius

    def axis_at(z: float) -> FloatArray:
        return np.asarray(ctx.track.footwall_edge(z) + d_hat * offset)

    portal = ctx.portal
    # approach: straight from the portal to the tangent point of the circle at
    # the join elevation; fixed-point iterate the join elevation (5 rounds)
    z_join = portal[2] - g * float(np.linalg.norm(axis_at(ctx.levels[0].elevation) - portal[:2]))
    g_app = g
    tangent_pt = None
    heading_in = 0.0
    for _ in range(5):
        c = axis_at(z_join)
        v = c - portal[:2]
        dist = float(np.linalg.norm(v))
        if dist <= radius + 1e-9:
            return FamilyInfeasible(
                InfeasibleReason.APPROACH_INFEASIBLE, "portal inside the spiral circle"
            )
        alpha = math.asin(radius / dist)
        base = math.atan2(v[1], v[0])
        chosen = None
        for sign in (1.0, -1.0):
            ang = base + sign * alpha
            dir_t = np.array([math.cos(ang), math.sin(ang)])
            straight = math.sqrt(max(dist * dist - radius * radius, 0.0))
            t_pt = portal[:2] + dir_t * straight
            r_in = np.array([dir_t[1], -dir_t[0]])
            on_right = float((c - t_pt) @ r_in) > 0
            if (sense > 0) == on_right:
                chosen = (straight, t_pt, azimuth_of(dir_t))
        if chosen is None:
            return FamilyInfeasible(InfeasibleReason.APPROACH_INFEASIBLE, "no tangent")
        straight, tangent_pt, heading_in = chosen
        # phase tuning (derived, not sampled): choose the approach gradient in
        # [f·g, g] so the level crossings land on the ore-facing angle
        rel = tangent_pt - c
        theta_join = math.atan2(rel[1], rel[0])
        ore_dir = -d_hat
        theta_star = math.atan2(ore_dir[1], ore_dir[0])
        # angular position at level 1: theta_join + sense·2π·n·(z_join − z1)/dz
        phi = ((theta_star - theta_join) * (-sense) / (2.0 * math.pi)) % 1.0
        period = dz / n
        z1 = ctx.levels[0].elevation
        z_lo = portal[2] - g * straight
        z_hi = portal[2] - ctx.cfg.approach_min_gradient_fraction * g * straight
        k = math.floor((z_lo - z1) / period - phi)
        candidates = [z1 + (k + j + phi) * period for j in range(0, 4)]
        feasible = [z for z in candidates if z_lo - 1e-9 <= z <= z_hi + 1e-9]
        if feasible:
            z_new = min(feasible)  # steepest admissible approach
            g_app = (portal[2] - z_new) / straight if straight > 0 else g
        else:
            z_new = z_lo
            g_app = g
        if abs(z_new - z_join) < 1e-6:
            z_join = z_new
            break
        z_join = z_new
    assert tangent_pt is not None
    # final tangent geometry for the converged join elevation: the straight
    # must end ON the circle of the axis at z_join with a tangent heading
    c = axis_at(z_join)
    v = c - portal[:2]
    dist = float(np.linalg.norm(v))
    alpha = math.asin(min(1.0, radius / dist))
    base = math.atan2(v[1], v[0])
    for sign in (1.0, -1.0):
        ang = base + sign * alpha
        dir_t = np.array([math.cos(ang), math.sin(ang)])
        straight = math.sqrt(max(dist * dist - radius * radius, 0.0))
        t_pt = portal[:2] + dir_t * straight
        r_in = np.array([dir_t[1], -dir_t[0]])
        if (sense > 0) == (float((c - t_pt) @ r_in) > 0):
            tangent_pt, heading_in = t_pt, azimuth_of(dir_t)
    g_app = (portal[2] - z_join) / straight if straight > 0 else g
    if g_app > g + 1e-12 or g_app < ctx.cfg.approach_min_gradient_fraction * g - 1e-12:
        g_app = min(g, max(g_app, ctx.cfg.approach_min_gradient_fraction * g))
    if straight < ctx.cfg.min_straight_length:
        return FamilyInfeasible(
            InfeasibleReason.APPROACH_INFEASIBLE, f"approach straight {straight:.1f} m too short"
        )
    path = Path(
        Pose(float(portal[0]), float(portal[1]), float(portal[2]), heading_in),
        ctx.cfg.sample_spacing,
    )
    path.straight(straight, g_app, "APPROACH_STRAIGHT")
    if path.pose.z <= ctx.z_last:
        return FamilyInfeasible(
            InfeasibleReason.GEOMETRY_ASSEMBLY, "approach alone descends below the deepest level"
        )
    path.drifting_helix(axis_at, radius, sense, g, ctx.z_last, "HELIX")
    return FamilyGeometry(
        path.array(),
        path.pieces,
        {
            "radius": radius,
            "levelInterval": dz,
            "turnsPerLevel": n,
            "approachGradient": g_app,
            "joinElevation": z_join,
            "dropPerTurn": 2.0 * math.pi * radius * g,
        },
    )


# --------------------------------------------------------------------------- #
# LONGITUDINAL
# --------------------------------------------------------------------------- #


def build_longitudinal(
    params: CandidateParams, ctx: LayoutContext
) -> FamilyGeometry | FamilyInfeasible:
    assert params.orientation and params.side
    g = params.target_gradient
    if not ctx.levels:
        return FamilyInfeasible(InfeasibleReason.NO_REQUIRED_LEVELS, "no required levels")
    tr = ctx.track
    along = tr.u_h if params.orientation == "STRIKE_POSITIVE" else -tr.u_h
    side_sign = 1.0 if params.side == "FOOTWALL" else -1.0
    # lateral drift of the corridor per metre of descent, measured on the
    # footwall track (rule 143 coupling: plan direction ↔ vertical descent)
    drift = tr.lateral_drift_per_metre  # along w_h per metre of descent
    lateral = tr.w_h * (drift * g)  # per horizontal metre travelled
    direction = along + lateral
    direction = direction / float(np.linalg.norm(direction))
    z1 = ctx.levels[0].elevation
    ref = tr.footwall_edge(z1) if side_sign > 0 else tr.hanging_edge(z1)
    corridor0 = ref + side_sign * tr.w_h * ctx.standoff
    half = tr.strike_half_extent + ctx.cfg.longitudinal_extension
    start_xy = corridor0 - along * half
    # clip the start to the world margin along the corridor
    for _ in range(200):
        if ctx.inside_world(start_xy):
            break
        start_xy = start_xy + along * 10.0
    else:
        return FamilyInfeasible(InfeasibleReason.WORLD_BOUNDS, "corridor start outside the world")
    heading = azimuth_of(direction)
    path = Path(
        Pose(float(ctx.portal[0]), float(ctx.portal[1]), float(ctx.portal[2]), 0.0),
        ctx.cfg.sample_spacing,
    )
    err = _approach(path, start_xy, heading, ctx.ramp.min_turn_radius, g, ctx)
    if err:
        return FamilyInfeasible(InfeasibleReason.APPROACH_INFEASIBLE, err)
    # run along the corridor until the deepest level is reached or the world
    # margin is hit (then the remaining levels are simply not crossed)
    z_needed = path.pose.z - ctx.z_last
    length_needed = z_needed / g
    # world clip: march in spacing steps to find the admissible length
    length = 0.0
    step = ctx.cfg.sample_spacing
    while length + step <= length_needed + 1e-9:
        nxt = path.pose.xy + direction * (length + step)
        if not ctx.inside_world(nxt):
            break
        length += step
    else:
        length = length_needed
    if length < ctx.cfg.min_straight_length:
        return FamilyInfeasible(
            InfeasibleReason.WORLD_BOUNDS, "corridor has no room inside the world"
        )
    path.straight(length, g, "CORRIDOR")
    return FamilyGeometry(
        path.array(),
        path.pieces,
        {
            "corridorAzimuthDeg": math.degrees(heading) % 360.0,
            "lateralDriftPerMetreDescent": drift,
            "corridorLength": length,
            "reachedDeepestLevel": bool(abs(length - length_needed) < 1e-6),
        },
    )


# --------------------------------------------------------------------------- #
# SWITCHBACK
# --------------------------------------------------------------------------- #


def build_switchback(
    params: CandidateParams, ctx: LayoutContext
) -> FamilyGeometry | FamilyInfeasible:
    assert (
        params.legs_per_level is not None
        and params.initial_turn_sense
        and (params.principal_orientation_deg is not None)
    )
    g = params.target_gradient
    k = params.legs_per_level
    intervals = level_intervals(ctx.levels)
    if len(ctx.levels) < 2:
        return FamilyInfeasible(InfeasibleReason.NO_REQUIRED_LEVELS, "switchback needs ≥ 2 levels")
    dz = intervals[0]
    if max(intervals) - min(intervals) > ctx.cfg.level_interval_tolerance * dz:
        return FamilyInfeasible(
            InfeasibleReason.LEVEL_INTERVAL_NONUNIFORM,
            "level intervals differ; the leg/turn cycle assumes one constant interval",
        )
    tr = ctx.track
    r_min = ctx.ramp.min_turn_radius
    leg_dir = rotate(tr.u_h, params.principal_orientation_deg)
    # lateral unit pointing AWAY from the ore (positive w_h component)
    n_hat = np.array([leg_dir[1], -leg_dir[0]])  # right of leg_dir
    if float(n_hat @ tr.w_h) < 0:
        n_hat = -n_hat
    right_is_away = float(np.array([leg_dir[1], -leg_dir[0]]) @ n_hat) > 0
    first_sense = 1.0 if params.initial_turn_sense == "CW" else -1.0
    # the first hairpin moves the corridor to the right (CW) or left (CCW);
    # the first leg is the NEAR leg when that move goes away from the ore
    first_moves_away = (first_sense > 0) == right_is_away
    drop_per_cycle = dz / k
    # cycle: straight leg + 180° hairpin; the hairpin's horizontal arc length
    # is subtracted from the horizontal travel the gradient needs (rule 143)
    z1 = ctx.levels[0].elevation
    near_lateral = ctx.standoff  # ore-facing leg
    leg_lateral0 = near_lateral if first_moves_away else near_lateral + 2.0 * r_min
    leg_len_nominal = drop_per_cycle / g - math.pi * r_min
    if leg_len_nominal < ctx.cfg.min_straight_length:
        return FamilyInfeasible(
            InfeasibleReason.LEG_TOO_SHORT,
            f"derived straight leg {leg_len_nominal:.1f} m < {ctx.cfg.min_straight_length} m "
            f"(ΔZ/k {drop_per_cycle:g} m at g {g:g} minus hairpin π·R {math.pi * r_min:.1f} m)",
        )
    heading = azimuth_of(leg_dir)
    # the corridor is anchored to the footwall edge at the JOIN elevation (the
    # elevation where the first leg actually starts); the join elevation
    # depends on the approach length, so iterate the fixed point (5 rounds)
    z_join = z1
    start_xy = ctx.portal[:2]
    for _ in range(5):
        corridor_center = tr.footwall_edge(z_join) + n_hat * leg_lateral0
        centroid_along = float((tr.centroid(z_join) - corridor_center) @ leg_dir)
        start_xy = corridor_center + leg_dir * (centroid_along - 0.5 * leg_len_nominal)
        probe = Path(
            Pose(float(ctx.portal[0]), float(ctx.portal[1]), float(ctx.portal[2]), 0.0),
            ctx.cfg.sample_spacing,
        )
        if _approach(probe, start_xy, heading, r_min, g, ctx) is not None:
            break
        z_new = probe.pose.z
        if abs(z_new - z_join) < 1e-6:
            z_join = z_new
            break
        z_join = z_new
    path = Path(
        Pose(float(ctx.portal[0]), float(ctx.portal[1]), float(ctx.portal[2]), 0.0),
        ctx.cfg.sample_spacing,
    )
    err = _approach(path, start_xy, heading, r_min, g, ctx)
    if err:
        return FamilyInfeasible(InfeasibleReason.APPROACH_INFEASIBLE, err)
    # every hairpin keeps the SAME sense: with the heading reversed after
    # each one, a constant sense alternates the absolute lateral move
    # (toward / away from the ore), which is exactly what stacks the legs in
    # one corridor (a serpentine would alternate the sense instead)
    sense = first_sense
    cycle = 0
    max_cycles = 4 * k * (len(ctx.levels) + 8)
    while path.pose.z > ctx.z_last + 1e-9 and cycle < max_cycles:
        # corridor drift toward the dip direction: the footwall edge moves with
        # depth, so over every PAIR of cycles the legs must shift by the edge
        # shift; the whole pair drift goes into the hairpin that bulges toward
        # the edge's motion (radius enlarged), the other keeps the minimum
        # radius — hairpins are never shrunk below R_min
        z_a = path.pose.z
        z_pair = max(z_a - 2.0 * drop_per_cycle, ctx.z_last)
        pair_drift = float((tr.footwall_edge(z_pair) - tr.footwall_edge(z_a)) @ n_hat)
        d_cur = path.pose.direction
        right_cur = np.array([d_cur[1], -d_cur[0]])
        move_sign = float(np.sign((sense * right_cur) @ n_hat))
        radius = r_min
        if move_sign * pair_drift > 0.0:
            radius = r_min + abs(pair_drift) / 2.0
        # both legs of a pair share ONE length so the stack stays aligned
        # along strike: the pair drops 2·ΔZ/k over 2·L + π·(2·R_min +
        # |drift|/2), i.e. L = ΔZ/(k·g) − π·(R_min + |drift|/4)
        leg = drop_per_cycle / g - math.pi * (r_min + abs(pair_drift) / 4.0)
        if leg < ctx.cfg.min_straight_length:
            return FamilyInfeasible(
                InfeasibleReason.LEG_TOO_SHORT,
                f"cycle {cycle}: straight leg {leg:.1f} m too short after the "
                f"{radius:.1f} m hairpin",
            )
        remaining = path.pose.z - ctx.z_last
        if remaining <= g * leg + 1e-9:
            path.straight(remaining / g, g, f"LEG_{cycle}")
            break
        path.straight(leg, g, f"LEG_{cycle}")
        remaining = path.pose.z - ctx.z_last
        if remaining <= g * math.pi * radius + 1e-9:
            path.arc(radius, sense * (remaining / (g * radius)), g, f"HAIRPIN_{cycle}")
            break
        path.arc(radius, sense * math.pi, g, f"HAIRPIN_{cycle}")
        cycle += 1
    # a closing partial hairpin descends chord-exactly, so it can stop a few
    # millimetres above the deepest level: finish with a straight that lands
    # exactly on it (never more than half a sample spacing)
    rem = path.pose.z - ctx.z_last
    if 0.0 < rem <= g * ctx.cfg.sample_spacing:
        path.straight(rem / g, g, "LANDING")
    if path.pose.z > ctx.z_last + 1e-6:
        return FamilyInfeasible(
            InfeasibleReason.GEOMETRY_ASSEMBLY,
            f"cycle budget exhausted {path.pose.z - ctx.z_last:.3f} m above the deepest level",
        )
    pts = path.array()
    if not all(ctx.inside_world(p[:2]) for p in pts[:: max(1, len(pts) // 200)]):
        pass  # world bounds are judged on the delivered centerline by the search
    return FamilyGeometry(
        pts,
        path.pieces,
        {
            "hairpinRadius": r_min,
            "legLengthNominal": leg_len_nominal,
            "dropPerCycle": drop_per_cycle,
            "cycles": cycle + 1,
        },
    )


def build_family(params: CandidateParams, ctx: LayoutContext) -> FamilyGeometry | FamilyInfeasible:
    if params.family is RampFamily.SPIRAL:
        return build_spiral(params, ctx)
    if params.family is RampFamily.LONGITUDINAL:
        return build_longitudinal(params, ctx)
    return build_switchback(params, ctx)
