"""Ramp junctions, level accesses and level-development anchors
(Phase 20B, rules 153–160).

A main-ramp crossing of a level elevation is only a RAMP LEVEL REFERENCE.
The physical route to a level is::

    main ramp → RAMP_JUNCTION (turnout) → LEVEL_ACCESS branch → LEVEL_ENTRY

and this module plans it deterministically:

* ``LevelDevelopmentAnchor`` — where the level-development backbone (the
  footwall / haulage drift for LONGHOLE, the generic backbone for any other
  method) is entered. Placed on the footwall backbone at the configured
  stand-off from the footwall edge; TABULAR uses the exact rule 43 line,
  implicit bodies use the authoritative numerical level section (local
  principal axis, footwall-side extent) — never a frontend reconstruction.
* ``plan_level_accesses`` — for every serviceable level: a finite lattice of
  ramp-junction candidates inside a chainage / elevation window, a G1
  Dubins CSC connector (arc–straight–arc, R = R_min) from the junction pose
  to the anchor pose, chord-exact constant vertical gradient, and hard
  validation of the DELIVERED polyline (gradient, plan circumradius, world,
  cover, restricted zones, orebody clearance under the evaluator's policy,
  excavation envelope). Junction spacing is a hard rule. Every failure is a
  typed reason; nothing is clamped.

  Among the candidates that pass EVERY hard check, selection minimizes
  ``(access_length_cost(L, P), L, junction chainage, terminal sense)`` with
  ``P`` = the effective PREFERRED access length (rule 163) — not the shortest
  branch. Hard limits are never traded against that cost.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.core.models import LevelAccessConfig, RampConstraints
from minegen.design.constraints import RejectionReason
from minegen.design.cost_field import DesignCostEvaluator
from minegen.design.profile import ProfileShape, boundary_points, gravity_frames
from minegen.design.targets import footwall_candidate_position
from minegen.design.validation import evaluate_and_validate
from minegen.layout.families import FootwallTrack
from minegen.layout.geometry import (
    STRAIGHT_HEADING_EPS,
    chainage,
    find_crossing,
    headings,
    plan_radii,
    unwrap_delta,
)
from minegen.layout.levels import LevelSections, RequiredLevel
from minegen.levels.builder import GENERIC_BACKBONE_END_CLEARANCE
from minegen.world.orebody import Orebody, TabularOrebody

FloatArray = npt.NDArray[np.float64]

RADIUS_TOLERANCE = 0.05  # m, floating-point noise on the delivered circumradius
GRADIENT_TOLERANCE = 1e-9
WELD_TOLERANCE = 1e-6  # m
#: keep the entry inside the backbone extent by this much (m) — the same
#: fixed clearance the generic backbone drift uses (rule 159)
BACKBONE_END_MARGIN = GENERIC_BACKBONE_END_CLEARANCE
#: minimum clear length below which a connector is degenerate
MIN_CONNECTOR_LENGTH = 1.0
#: default PREFERRED access length = this factor × tunnel width (planning
#: default, closeout v3 §2: usable turnout development, room for future sump /
#: services / ore-pass connections — never a statutory value)
PREFERRED_ACCESS_WIDTH_FACTOR = 6.0
#: extra cost per metre BEYOND the preferred length. A documented deterministic
#: planning coefficient (closeout v3 §2.D) — provisional, tuned against manual
#: acceptance, NOT a permanent engineering invariant and NOT a user weight.
LONG_ACCESS_COEF = 0.5
#: Phase 20B.1 O-1 observability: branch samples closer than this ALONG THE
#: BRANCH (3-D arc, m) to the junction are excluded from the excavation-
#: separation metric — the taper there is physically attached to the ramp by
#: construction, so including it would always report 0
SEPARATION_TAPER_EXCLUSION_ARC = 15.0
#: Phase 20B.1 O-2 observability: ramp-chainage half-window (m) around a
#: junction over which the delivered main ramp's cumulative heading change is
#: reported (diagnostic only in commit O; commit B gates on it)
TURNOUT_STRAIGHT_BUFFER = 25.0


def effective_preferred_access_length(
    cfg: LevelAccessConfig, ramp: RampConstraints
) -> tuple[float, str]:
    """Effective preferred branch length and its provenance:
    ``EXPLICIT`` (validated inside [min, max] by the schema) or
    ``DEFAULT_6X_TUNNEL_WIDTH`` = ``max(minimum_access_length,
    PREFERRED_ACCESS_WIDTH_FACTOR × tunnel_width)``."""
    if cfg.preferred_access_length is not None:
        return float(cfg.preferred_access_length), "EXPLICIT"
    return (
        max(float(cfg.minimum_access_length), PREFERRED_ACCESS_WIDTH_FACTOR * ramp.tunnel_width),
        "DEFAULT_6X_TUNNEL_WIDTH",
    )


def access_length_cost(
    length: float, preferred: float, long_coef: float = LONG_ACCESS_COEF
) -> float:
    """Selection cost of a VALID branch: ``|L − P| + long_coef · max(0, L − P)``.
    Hard limits (min / max length, gradient, radius, clearance, envelope) are
    checked BEFORE this cost exists — it only orders valid candidates."""
    return abs(length - preferred) + long_coef * max(0.0, length - preferred)


#: B-1 default plan-separation floor = this factor × tunnel width (30 m for
#: the default profile) — an engineering planning default, never statutory
PLAN_SEPARATION_WIDTH_FACTOR = 6.0
#: B-2 default excavation-separation (rock pillar) floor = this factor ×
#: tunnel width (10 m ≈ two spans between parallel openings — a planning
#: default, never statutory)
EXCAVATION_SEPARATION_WIDTH_FACTOR = 2.0
#: numerical tolerance on the separation gates (sampling / chord noise), m —
#: same role as RADIUS_TOLERANCE on the delivered circumradius
SEPARATION_TOLERANCE = 0.05


def effective_plan_separation(cfg: LevelAccessConfig, ramp: RampConstraints) -> float:
    """B-1 hard floor on junction → entry plan separation (m)."""
    if cfg.minimum_ramp_to_entry_plan_separation is not None:
        return float(cfg.minimum_ramp_to_entry_plan_separation)
    return PLAN_SEPARATION_WIDTH_FACTOR * float(ramp.tunnel_width)


def effective_excavation_separation(cfg: LevelAccessConfig, ramp: RampConstraints) -> float:
    """B-2 hard floor on the branch-to-ramp rock pillar (m)."""
    if cfg.minimum_excavation_separation is not None:
        return float(cfg.minimum_excavation_separation)
    return EXCAVATION_SEPARATION_WIDTH_FACTOR * float(ramp.tunnel_width)


def gate_taper_arc(r_min: float, lateral_needed: float) -> float:
    """Branch arc length excused from the B-2 pillar gate: the shortest arc
    over which the FASTEST lateral development a branch can perform — a
    minimum-radius turn toward perpendicular (lateral ``R·(1 − cos(s/R))``),
    then a perpendicular straight — reaches ``lateral_needed`` (the required
    centerline distance ``pillar + both half-spans``). Inside this arc the
    branch is geometrically incapable of holding the pillar, converging into
    its own turnout; beyond it (and always at the terminal) the gate is
    hard. Replaces commit O's fixed 15 m exclusion in the gated metric: on a
    curving winding the tangential divergence is only quadratic, so a fixed
    exclusion under-reports every helix branch."""
    if lateral_needed <= 0.0:
        return 0.0
    if lateral_needed <= r_min:
        return float(r_min * math.acos(max(-1.0, 1.0 - lateral_needed / r_min)))
    return float(r_min * math.pi / 2.0 + (lateral_needed - r_min))


class AccessFailure:
    NO_JUNCTION_IN_WINDOW = "NO_JUNCTION_IN_WINDOW"
    GRADE_LIMIT = "GRADE_LIMIT"
    TURN_RADIUS = "TURN_RADIUS"
    #: Phase 20B.1 B-1: junction → entry plan separation below the hard floor
    INSUFFICIENT_RAMP_TO_ENTRY_SEPARATION = "INSUFFICIENT_RAMP_TO_ENTRY_SEPARATION"
    #: Phase 20B.1 B-2: branch-to-ramp rock pillar below the hard floor
    INSUFFICIENT_RAMP_PILLAR = "INSUFFICIENT_RAMP_PILLAR"
    #: Phase 20B.1 B-3: the delivered ramp turns too much through the turnout window
    TURNOUT_NOT_STRAIGHT = "TURNOUT_NOT_STRAIGHT"
    ACCESS_TOO_LONG = "ACCESS_TOO_LONG"
    ACCESS_TOO_SHORT = "ACCESS_TOO_SHORT"
    WORLD_BOUNDS = "WORLD_BOUNDS"
    SURFACE_COVER = "SURFACE_COVER"
    ABOVE_TERRAIN = "ABOVE_TERRAIN"
    RESTRICTED_ZONE = "RESTRICTED_ZONE"
    OREBODY_CLEARANCE = "OREBODY_CLEARANCE"
    ENVELOPE_INVALID = "ENVELOPE_INVALID"
    JUNCTION_SPACING_CONFLICT = "JUNCTION_SPACING_CONFLICT"
    CONNECTOR_UNAVAILABLE = "CONNECTOR_UNAVAILABLE"
    TARGET_UNREACHABLE = "TARGET_UNREACHABLE"
    NO_ANCHOR = "NO_ANCHOR"


# --------------------------------------------------------------------------- #
# Level development anchors
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LevelDevelopmentAnchor:
    """Backend-authoritative development location a level access must reach."""

    level_id: str
    elevation: float
    position: FloatArray  # (3,)
    heading: float  # preferred terminal heading (clockwise from +Y, rad)
    backbone_direction: FloatArray  # (2,) unit along the backbone (+strike)
    backbone_extent: tuple[float, float]  # along-backbone coordinate range
    role: str
    orebody_side: str
    mining_method: str
    standoff: float
    ramp_reference: FloatArray | None  # main-ramp level reference (crossing) if any
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "levelId": self.level_id,
            "elevation": self.elevation,
            "position": [float(v) for v in self.position],
            "headingDeg": math.degrees(self.heading),
            "backboneDirection": [float(v) for v in self.backbone_direction],
            "backboneExtent": [float(self.backbone_extent[0]), float(self.backbone_extent[1])],
            "role": self.role,
            "orebodySide": self.orebody_side,
            "miningMethod": self.mining_method,
            "standoff": self.standoff,
            "rampLevelReference": (
                [float(v) for v in self.ramp_reference] if self.ramp_reference is not None else None
            ),
            "diagnostics": self.diagnostics,
        }


def _azimuth(v: FloatArray) -> float:
    return float(math.atan2(float(v[0]), float(v[1])))


def _principal_axis(xy: FloatArray, prefer: FloatArray) -> FloatArray:
    """Unit principal (longest) axis of an in-plane sample, oriented along
    ``prefer`` (dot ≥ 0). Deterministic: covariance eigenvector."""
    c = xy - xy.mean(axis=0)
    cov = c.T @ c / max(c.shape[0], 1)
    w, v = np.linalg.eigh(cov)
    axis = np.asarray(v[:, int(np.argmax(w))], dtype=np.float64)
    n = float(np.linalg.norm(axis))
    axis = prefer.copy() if n < 1e-12 else axis / n
    if float(axis @ prefer) < 0.0:
        axis = -axis
    return axis


def build_anchor(
    orebody: Orebody,
    level: RequiredLevel,
    sections: LevelSections,
    track: FootwallTrack,
    ramp_points: FloatArray,
    standoff: float,
    mining_method: str,
) -> LevelDevelopmentAnchor | None:
    """Level-development anchor on the footwall backbone at ``level``.

    Entry policy NEAREST_TO_RAMP: the backbone point closest to the main
    ramp's level reference (its z-crossing, else its closest vertex to the
    level elevation), clamped inside the backbone extent. The preferred
    terminal heading points along the backbone toward its centre so the
    drift continues along the ore."""
    sec = sections.section(level)
    if sec.empty:
        return None
    z = level.elevation
    cr = find_crossing(ramp_points, z)
    if cr is not None:
        ref = np.asarray(cr.point, dtype=np.float64)
    else:
        i = int(np.argmin(np.abs(ramp_points[:, 2] - z)))
        ref = np.asarray(ramp_points[i], dtype=np.float64)
    if isinstance(orebody, TabularOrebody):
        # exact rule 43 footwall line at this elevation
        u_h = np.asarray(orebody.u[:2], dtype=np.float64)
        u_h = u_h / float(np.linalg.norm(u_h))
        p0, _, _ = footwall_candidate_position(orebody, 0.0, z, standoff)
        origin = np.asarray(p0, dtype=np.float64)
        axis = u_h
        lo_u, hi_u = -float(orebody.half_length), float(orebody.half_length)
        diag: dict[str, Any] = {"backbone": "TABULAR_RULE_43", "halfLength": orebody.half_length}
    else:
        axis = _principal_axis(sec.inside_xy, track.u_h)
        normal = np.array([axis[1], -axis[0]])  # perpendicular, oriented to w_h
        if float(normal @ track.w_h) < 0.0:
            normal = -normal
        lo_n, hi_n = sec.extent_along(normal)
        lo_u, hi_u = sec.extent_along(axis)
        edge = sec.centroid + normal * hi_n
        origin = np.array([edge[0] + normal[0] * standoff, edge[1] + normal[1] * standoff, z])
        diag = {
            "backbone": "NUMERICAL_SECTION_PRINCIPAL_AXIS",
            "sectionSamples": int(sec.inside_xy.shape[0]),
            "sectionWidthAlongNormal": float(hi_n - lo_n),
            "localAxisAzimuthDeg": math.degrees(_azimuth(axis)),
        }
    span = hi_u - lo_u
    margin = min(BACKBONE_END_MARGIN, 0.25 * span)
    t_ref = float((ref[:2] - origin[:2]) @ axis)
    t = min(max(t_ref, lo_u + margin), hi_u - margin)
    pos = np.array([origin[0] + axis[0] * t, origin[1] + axis[1] * t, z])
    centre_t = 0.5 * (lo_u + hi_u)
    direction = axis if t <= centre_t else -axis
    diag.update(
        {
            "entryPolicy": "NEAREST_TO_RAMP",
            "backboneCoordinate": t,
            "referenceBackboneCoordinate": t_ref,
            "referenceOffset": float(np.linalg.norm(ref[:2] - pos[:2])),
        }
    )
    return LevelDevelopmentAnchor(
        level_id=level.level_id,
        elevation=z,
        position=pos,
        heading=_azimuth(direction),
        backbone_direction=np.asarray(axis, dtype=np.float64),
        backbone_extent=(lo_u, hi_u),
        role="FOOTWALL_DRIFT_ENTRY",
        orebody_side="FOOTWALL",
        mining_method=mining_method,
        standoff=standoff,
        ramp_reference=ref,
        diagnostics=diag,
    )


# --------------------------------------------------------------------------- #
# Dubins CSC connector (plan) with chord-exact vertical
# --------------------------------------------------------------------------- #


def _mod2pi(a: float) -> float:
    return a - 2.0 * math.pi * math.floor(a / (2.0 * math.pi))


def _dubins_csc(
    alpha: float, beta: float, d: float
) -> list[tuple[str, tuple[float, float, float], float]]:
    """Normalized Dubins CSC words (Shkel & Lumelsky): (word, (t, p, q), L)."""
    out: list[tuple[str, tuple[float, float, float], float]] = []
    sa, sb, ca, cb = math.sin(alpha), math.sin(beta), math.cos(alpha), math.cos(beta)
    c_ab = math.cos(alpha - beta)
    # LSL
    tmp = 2.0 + d * d - 2.0 * c_ab + 2.0 * d * (sa - sb)
    if tmp >= 0.0:
        p = math.sqrt(tmp)
        th = math.atan2(cb - ca, d + sa - sb)
        t = _mod2pi(-alpha + th)
        q = _mod2pi(beta - th)
        out.append(("LSL", (t, p, q), t + p + q))
    # RSR
    tmp = 2.0 + d * d - 2.0 * c_ab + 2.0 * d * (sb - sa)
    if tmp >= 0.0:
        p = math.sqrt(tmp)
        th = math.atan2(ca - cb, d - sa + sb)
        t = _mod2pi(alpha - th)
        q = _mod2pi(-beta + th)
        out.append(("RSR", (t, p, q), t + p + q))
    # LSR
    tmp = -2.0 + d * d + 2.0 * c_ab + 2.0 * d * (sa + sb)
    if tmp >= 0.0:
        p = math.sqrt(tmp)
        th = math.atan2(-ca - cb, d + sa + sb) - math.atan2(-2.0, p)
        t = _mod2pi(-alpha + th)
        q = _mod2pi(-_mod2pi(beta) + th)
        out.append(("LSR", (t, p, q), t + p + q))
    # RSL
    tmp = d * d - 2.0 + 2.0 * c_ab - 2.0 * d * (sa + sb)
    if tmp >= 0.0:
        p = math.sqrt(tmp)
        th = math.atan2(ca + cb, d - sa - sb) - math.atan2(2.0, p)
        t = _mod2pi(alpha - th)
        q = _mod2pi(beta - th)
        out.append(("RSL", (t, p, q), t + p + q))
    return out


def _sample_word(
    start_xy: FloatArray,
    theta0: float,
    word: str,
    tpq: tuple[float, float, float],
    radius: float,
    spacing: float,
) -> tuple[FloatArray, list[dict[str, Any]]]:
    """Sample a Dubins word from the start pose (math angle θ0). Arc points
    lie exactly on their circles; pieces share their boundary vertex."""
    pts: list[FloatArray] = [np.asarray(start_xy, dtype=np.float64)]
    pieces: list[dict[str, Any]] = []
    x, y, th = float(start_xy[0]), float(start_xy[1]), theta0
    for kind, val in zip(word, tpq, strict=True):
        if val <= 1e-12:
            continue
        if kind == "S":
            length = val * radius
            n = max(1, math.ceil(length / spacing))
            for i in range(1, n + 1):
                s = length * i / n
                pts.append(np.array([x + math.cos(th) * s, y + math.sin(th) * s]))
            x, y = float(pts[-1][0]), float(pts[-1][1])
            pieces.append({"kind": "STRAIGHT", "length": length})
        else:
            sign = 1.0 if kind == "L" else -1.0
            cx = x - sign * radius * math.sin(th)
            cy = y + sign * radius * math.cos(th)
            n = max(1, math.ceil(val * radius / spacing))
            for i in range(1, n + 1):
                a = th + sign * val * i / n
                pts.append(
                    np.array([cx + sign * radius * math.sin(a), cy - sign * radius * math.cos(a)])
                )
            th = th + sign * val
            x, y = float(pts[-1][0]), float(pts[-1][1])
            pieces.append(
                {
                    "kind": "ARC",
                    "sense": "CCW" if kind == "L" else "CW",
                    "radius": radius,
                    "angleDeg": math.degrees(val),
                }
            )
    return np.asarray(pts, dtype=np.float64), pieces


@dataclass
class Connector:
    word: str
    points: FloatArray  # (N, 3) delivered polyline
    pieces: list[dict[str, Any]]
    horizontal_length: float
    length3d: float
    gradient: float  # signed Δz / chord length (constant along the branch)


def build_connector(
    start: FloatArray,
    start_heading: float,
    end: FloatArray,
    end_heading: float,
    radius: float,
    spacing: float,
) -> Connector | None:
    """Shortest CSC Dubins connector (plan) from ``start`` heading
    ``start_heading`` to ``end`` heading ``end_heading`` with turning radius
    ``radius``; z is assigned linearly in delivered CHORD length so every
    edge carries the same gradient. Endpoints are exact. ``None`` when no
    CSC word exists (only for degenerate coincident poses)."""
    dxy = np.asarray(end[:2], dtype=np.float64) - np.asarray(start[:2], dtype=np.float64)
    dist = float(np.linalg.norm(dxy))
    if dist < MIN_CONNECTOR_LENGTH:
        return None
    # math angles (counter-clockwise from +X)
    th0 = math.pi / 2.0 - start_heading
    th1 = math.pi / 2.0 - end_heading
    phi = math.atan2(float(dxy[1]), float(dxy[0]))
    alpha = _mod2pi(th0 - phi)
    beta = _mod2pi(th1 - phi)
    words = _dubins_csc(alpha, beta, dist / radius)
    if not words:
        return None
    words.sort(key=lambda w: (w[2], w[0]))
    word, tpq, _ = words[0]
    xy, pieces = _sample_word(np.asarray(start[:2]), th0, word, tpq, radius, spacing)
    xy[-1] = end[:2]  # exact terminal (analytic error ≈ 1e-9)
    chord = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    total = float(np.sum(chord))
    if total < MIN_CONNECTOR_LENGTH:
        return None
    dz = float(end[2] - start[2])
    grad = dz / total
    z = float(start[2]) + grad * np.concatenate([[0.0], np.cumsum(chord)])
    z[-1] = float(end[2])
    pts = np.column_stack([xy, z])
    length3d = float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1)))
    return Connector(word, pts, pieces, total, length3d, grad)


# --------------------------------------------------------------------------- #
# Level access plan
# --------------------------------------------------------------------------- #


@dataclass
class LevelAccess:
    level_id: str
    elevation: float
    status: str  # OK | INFEASIBLE
    anchor: LevelDevelopmentAnchor | None
    junction_chainage: float | None = None
    junction_position: FloatArray | None = None
    junction_heading: float | None = None
    junction_edge_index: int | None = None
    terminal_heading: float | None = None
    connector_word: str | None = None
    pieces: list[dict[str, Any]] = field(default_factory=list)
    points: FloatArray | None = None
    length3d: float = 0.0
    horizontal_length: float = 0.0
    max_gradient: float = 0.0
    min_plan_radius: float | None = None
    field_cost: float | None = None
    validation: dict[str, Any] = field(default_factory=dict)
    candidates_tried: int = 0
    candidates_valid: int = 0
    rejection_counts: dict[str, int] = field(default_factory=dict)
    failure_reason: str | None = None
    failure_detail: str | None = None
    #: closeout v3 §2.G observability: why THIS branch was selected
    preferred_length: float | None = None
    length_deviation: float | None = None
    selection_cost: float | None = None
    #: Phase 20B.1 O-1/O-2 observability (reporting only, never selection):
    #: junction ↔ entry separations, the rock pillar to the main ramp and the
    #: turnout straightness — see ``fill_separation_metrics``
    junction_to_entry_plan_sep: float | None = None
    junction_to_entry_dist3d: float | None = None
    ramp_centerline_distance: float | None = None
    excavation_separation: float | None = None
    turnout_heading_change_deg: float | None = None
    #: Phase 20B.1 B-5: greedy-assignment diagnostic of a FAILED level —
    #: whether valid candidates exist once the already-used junction spacing
    #: is ignored (diagnostic re-run only; nothing is relaxed for the result)
    assignment_diagnostic: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.status == "OK"

    def to_dict(self, *, include_points: bool = True) -> dict[str, Any]:
        d: dict[str, Any] = {
            "levelId": self.level_id,
            "elevation": self.elevation,
            "status": self.status,
            "anchor": self.anchor.to_dict() if self.anchor else None,
            "rampJunction": (
                [float(v) for v in self.junction_position]
                if self.junction_position is not None
                else None
            ),
            "rampJunctionChainage": self.junction_chainage,
            "rampJunctionHeadingDeg": (
                math.degrees(self.junction_heading) if self.junction_heading is not None else None
            ),
            "rampJunctionEdgeIndex": self.junction_edge_index,
            "levelEntry": (
                [float(v) for v in self.points[-1]] if self.points is not None else None
            ),
            "terminalHeadingDeg": (
                math.degrees(self.terminal_heading) if self.terminal_heading is not None else None
            ),
            "connector": self.connector_word,
            "pieces": self.pieces,
            "length3d": self.length3d,
            "horizontalLength": self.horizontal_length,
            "maxGradient": self.max_gradient,
            "minPlanRadius": self.min_plan_radius,
            "fieldCost": self.field_cost,
            "validation": self.validation,
            "candidatesTried": self.candidates_tried,
            "candidatesValid": self.candidates_valid,
            "rejectionCounts": dict(self.rejection_counts),
            "failureReason": self.failure_reason,
            "failureDetail": self.failure_detail,
            "effectivePreferredAccessLength": self.preferred_length,
            "lengthDeviationFromPreferred": self.length_deviation,
            "selectionCost": self.selection_cost,
            "junctionToEntryPlanSep": self.junction_to_entry_plan_sep,
            "junctionToEntryDist3d": self.junction_to_entry_dist3d,
            "rampCenterlineDistance": self.ramp_centerline_distance,
            "excavationSeparation": self.excavation_separation,
            "turnoutHeadingChangeDeg": self.turnout_heading_change_deg,
            "assignmentDiagnostic": self.assignment_diagnostic,
        }
        if include_points and self.points is not None:
            d["centerline"] = {
                "points": [float(v) for v in self.points.ravel()],
                "pointCount": int(self.points.shape[0]),
            }
        else:
            d["centerline"] = None
        return d


@dataclass
class LevelAccessPlan:
    accesses: list[LevelAccess]
    max_gradient_limit: float
    min_turn_radius_limit: float
    required_clearance: float
    preferred_length: float | None = None
    preferred_source: str | None = None
    long_access_coef: float = LONG_ACCESS_COEF
    #: Phase 20B.1 B: the resolved hard-gate values this plan enforced
    plan_separation_required: float | None = None
    excavation_separation_required: float | None = None
    turnout_buffer: float | None = None
    turnout_max_heading_deg: float | None = None
    gate_taper_arc_m: float | None = None

    @property
    def feasible(self) -> bool:
        return all(a.ok for a in self.accesses)

    @property
    def total_length(self) -> float:
        return float(sum(a.length3d for a in self.accesses if a.ok))

    def summary(self) -> dict[str, Any]:
        ok = [a for a in self.accesses if a.ok]
        return {
            "feasible": self.feasible,
            "levelCount": len(self.accesses),
            "accessibleLevelCount": len(ok),
            "totalAccessLength": self.total_length,
            "worstAccessLength": max((a.length3d for a in ok), default=0.0),
            "maxAccessGradient": max((a.max_gradient for a in ok), default=0.0),
            "minAccessPlanRadius": min(
                (a.min_plan_radius for a in ok if a.min_plan_radius is not None), default=None
            ),
            "perLevelLength": {a.level_id: (a.length3d if a.ok else None) for a in self.accesses},
            "failures": {a.level_id: a.failure_reason for a in self.accesses if not a.ok},
            "maxGradientLimit": self.max_gradient_limit,
            "minTurnRadiusLimit": self.min_turn_radius_limit,
            "requiredClearance": self.required_clearance,
            "effectivePreferredAccessLength": self.preferred_length,
            "preferredAccessSource": self.preferred_source,
            "longAccessCoefficient": self.long_access_coef,
            "meanAbsDeviationFromPreferred": (
                float(np.mean([abs(a.length_deviation or 0.0) for a in ok])) if ok else None
            ),
            "maxAbsDeviationFromPreferred": (
                max(abs(a.length_deviation or 0.0) for a in ok) if ok else None
            ),
            # Phase 20B.1 O-1/O-2 observability aggregates (None until stage 4
            # selected the access, or when a branch is shorter than the taper
            # exclusion arc)
            "minJunctionToEntryPlanSep": _min_or_none(a.junction_to_entry_plan_sep for a in ok),
            "minExcavationSeparation": _min_or_none(a.excavation_separation for a in ok),
            "maxTurnoutHeadingChangeDeg": _max_or_none(a.turnout_heading_change_deg for a in ok),
            # Phase 20B.1 B: the resolved hard gates this plan enforced
            "minimumPlanSeparationRequired": self.plan_separation_required,
            "minimumExcavationSeparationRequired": self.excavation_separation_required,
            "turnoutStraightBuffer": self.turnout_buffer,
            "maximumTurnoutHeadingChangeDeg": self.turnout_max_heading_deg,
            "gateTaperArc": self.gate_taper_arc_m,
        }

    def to_dict(self, *, include_points: bool = True) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "accesses": [a.to_dict(include_points=include_points) for a in self.accesses],
        }


def _min_or_none(values: Any) -> float | None:
    xs = [v for v in values if v is not None]
    return float(min(xs)) if xs else None


def _max_or_none(values: Any) -> float | None:
    xs = [v for v in values if v is not None]
    return float(max(xs)) if xs else None


def nearest_on_polyline(
    points: FloatArray, polyline: FloatArray
) -> tuple[FloatArray, FloatArray, npt.NDArray[np.intp]]:
    """Closest-centerline pair for each of ``points`` (N, 3) against the
    segments of ``polyline`` (M, 3): (distance, closest point, segment index).
    Exact point-to-segment distances, fully vectorized (N × M pairs; an
    access branch has tens of samples)."""
    p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    a, b = polyline[:-1], polyline[1:]
    ab = b - a
    denom = np.einsum("md,md->m", ab, ab)
    denom = np.where(denom < 1e-12, 1.0, denom)
    ap = p[:, None, :] - a[None, :, :]
    t = np.clip(np.einsum("nmd,md->nm", ap, ab) / denom, 0.0, 1.0)
    closest = a[None, :, :] + t[:, :, None] * ab[None, :, :]
    dist = np.linalg.norm(p[:, None, :] - closest, axis=2)
    seg = np.argmin(dist, axis=1)
    rows = np.arange(p.shape[0])
    return dist[rows, seg], closest[rows, seg], seg


def min_distance_to_polyline(points: FloatArray, polyline: FloatArray) -> FloatArray:
    """Minimum 3-D distance from each of ``points`` to ``polyline``."""
    return nearest_on_polyline(points, polyline)[0]


def local_tangents(points: FloatArray) -> FloatArray:
    """Unit tangent at every vertex of a polyline (central differences,
    one-sided at the ends; a degenerate vertex inherits its predecessor)."""
    pts = np.asarray(points, dtype=np.float64)
    if pts.shape[0] < 2:
        return np.tile(np.array([1.0, 0.0, 0.0]), (pts.shape[0], 1))
    t = np.empty_like(pts)
    t[0] = pts[1] - pts[0]
    t[-1] = pts[-1] - pts[-2]
    if pts.shape[0] > 2:
        t[1:-1] = pts[2:] - pts[:-2]
    n = np.linalg.norm(t, axis=1)
    for i in range(pts.shape[0]):
        if n[i] < 1e-12:
            t[i] = t[i - 1] if i > 0 else np.array([1.0, 0.0, 0.0])
            n[i] = np.linalg.norm(t[i])
    return t / n[:, None]


def profile_support(
    shape: ProfileShape, tangents: FloatArray, directions: FloatArray
) -> FloatArray:
    """Support function of the gravity-aligned excavation cross-section:
    for each (tunnel tangent, unit direction) the largest extent of the
    profile — its vertices placed at ``x·right + y·up`` in the rule-26 frame
    of that tangent — measured along the direction. The floor-centerline
    D-profile is asymmetric: ``width/2`` sideways, ``height`` upward, 0
    downward (the floor is the centerline), so a vertically stacked pair
    reads ``height + 0`` where a horizontal pair reads ``width/2 + width/2``.
    Components of the direction along the tangent contribute nothing: this
    is the CROSS-SECTION support at one centerline sample, not the support
    of the swept tube."""
    t = np.asarray(tangents, dtype=np.float64).reshape(-1, 3)
    u = np.asarray(directions, dtype=np.float64).reshape(-1, 3)
    right, up = gravity_frames(t)
    dr = np.einsum("nd,nd->n", right, u)
    du = np.einsum("nd,nd->n", up, u)
    x, y = shape.points[:, 0], shape.points[:, 1]
    return np.asarray(np.max(x[None, :] * dr[:, None] + y[None, :] * du[:, None], axis=1))


def turnout_heading_change_deg(
    ramp_points: FloatArray,
    ramp_chainage: FloatArray,
    junction_chainage: float,
    half_window: float = TURNOUT_STRAIGHT_BUFFER,
) -> float:
    """Cumulative |Δheading| (degrees) of the DELIVERED main-ramp centerline
    over the chainage window ``junction ± half_window`` (O-2). 0.0 for a
    straight window; a junction inside a curve or next to a hairpin reports
    the turn it sits in. Diagnostic in commit O; commit B gates on it."""
    lo, hi = junction_chainage - half_window, junction_chainage + half_window
    # edges overlapping the window: edge i spans [ch[i], ch[i+1]]
    i0 = int(np.searchsorted(ramp_chainage, lo, side="right") - 1)
    i1 = int(np.searchsorted(ramp_chainage, hi, side="left"))
    i0 = max(i0, 0)
    i1 = min(i1, ramp_points.shape[0] - 1)
    if i1 - i0 < 2:
        return 0.0
    az = headings(ramp_points[i0 : i1 + 1])
    delta = unwrap_delta(az) if az.shape[0] > 1 else np.zeros(0)
    return float(math.degrees(np.sum(np.abs(delta))))


def gated_separation(
    branch_points: FloatArray,
    ramp_points: FloatArray,
    shape: ProfileShape,
    taper_arc: float,
) -> tuple[float, float]:
    """(minimum centerline distance, minimum excavation separation) of a
    branch against the full main-ramp polyline, over branch samples at
    least ``taper_arc`` ALONG THE BRANCH from the junction — the TERMINAL
    sample is always included, so a branch shorter than the taper is judged
    at its entry.

    The excavation separation is the DIRECTION-AWARE sampled envelope gap
    (Phase 20B.1-v2 1.2): at every post-taper sample the closest-centerline
    pair (branch sample, nearest ramp point) is found, ``u`` is the unit
    vector branch → ramp, and each tunnel's gravity-aligned cross-section
    (``shape``, the shared ``RampConstraints`` profile) contributes its
    support along ``u``::

        gap = d_centerline − support_branch(+u) − support_ramp(−u)

    Horizontal parallel drives therefore read ``d − width/2 − width/2``
    (the former fixed rule, unchanged), while a tunnel driven BELOW another
    reads ``d − height − 0``: the lower profile reaches ``height`` up to the
    upper floor centerline, which has no downward extent. This is a
    cross-section support at the sampled closest pair — not an exact
    swept-surface / mesh-to-mesh distance — but it follows the profile
    orientation, which the width-only rule could not, and it is what the
    B-2 rock-pillar gate means by sound rock."""
    pts = np.asarray(branch_points, dtype=np.float64)
    arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    mask = arc >= taper_arc
    mask[-1] = True  # the terminal is always judged
    judged = pts[mask]
    d, closest, seg = nearest_on_polyline(judged, ramp_points)
    ramp_dir = ramp_points[seg + 1] - ramp_points[seg]
    ramp_t = ramp_dir / np.maximum(np.linalg.norm(ramp_dir, axis=1, keepdims=True), 1e-12)
    branch_t = local_tangents(pts)[mask]
    reach = float(np.linalg.norm(shape.points, axis=1).max())
    safe = d > 1e-9
    u = np.zeros_like(judged)
    u[safe] = (closest[safe] - judged[safe]) / d[safe, None]
    r_branch = profile_support(shape, branch_t, u)
    r_ramp = profile_support(shape, ramp_t, -u)
    gap = np.where(safe, d - r_branch - r_ramp, -2.0 * reach)
    return float(np.min(d)), float(np.min(gap))


def fill_separation_metrics(
    access: LevelAccess,
    ramp_points: FloatArray,
    ramp_chainage: FloatArray,
    shape: ProfileShape,
    taper_arc: float = SEPARATION_TAPER_EXCLUSION_ARC,
) -> None:
    """Phase 20B.1 O-1/O-2 observability of a SELECTED access — reporting
    only, never part of candidate selection.

    * ``junction_to_entry_plan_sep`` / ``junction_to_entry_dist3d``: straight
      horizontal / 3-D distance junction → level entry.
    * ``ramp_centerline_distance`` / ``excavation_separation``: see
      ``gated_separation`` (direction-aware profile support since
      20B.1-v2 1.2). Commit B: the planner passes the geometry-derived
      ``gate_taper_arc`` as ``taper_arc`` so the reported metric and the B-2
      gate share ONE definition (commit O used a fixed 15 m exclusion and
      ``None`` for shorter branches; the terminal is now always judged).
    * ``turnout_heading_change_deg``: see ``turnout_heading_change_deg``.
    """
    if access.points is None or access.junction_position is None:
        return
    pts = access.points
    entry = pts[-1]
    j = np.asarray(access.junction_position, dtype=np.float64)
    access.junction_to_entry_plan_sep = float(np.hypot(*(entry[:2] - j[:2])))
    access.junction_to_entry_dist3d = float(np.linalg.norm(entry - j))
    d, sep = gated_separation(pts, ramp_points, shape, taper_arc)
    access.ramp_centerline_distance = d
    access.excavation_separation = sep
    if access.junction_chainage is not None:
        access.turnout_heading_change_deg = turnout_heading_change_deg(
            ramp_points, ramp_chainage, float(access.junction_chainage)
        )


_REASON_MAP = {
    RejectionReason.OUTSIDE_WORLD.value: AccessFailure.WORLD_BOUNDS,
    RejectionReason.ABOVE_TERRAIN.value: AccessFailure.ABOVE_TERRAIN,
    RejectionReason.INSUFFICIENT_COVER.value: AccessFailure.SURFACE_COVER,
    RejectionReason.INSIDE_OREBODY.value: AccessFailure.OREBODY_CLEARANCE,
    RejectionReason.OREBODY_BUFFER.value: AccessFailure.OREBODY_CLEARANCE,
    RejectionReason.RESTRICTED_ZONE.value: AccessFailure.RESTRICTED_ZONE,
}


@dataclass
class _Candidate:
    chainage: float
    position: FloatArray
    heading: float
    edge_index: int


def _rejecter(counts: dict[str, int]) -> Any:
    def reject(reason: str) -> None:
        counts[reason] = counts.get(reason, 0) + 1

    return reject


def _junction_candidates(
    ramp_points: FloatArray,
    z_level: float,
    cfg: LevelAccessConfig,
    anchor_xy: FloatArray,
) -> list[_Candidate]:
    ch = chainage(ramp_points)
    az = headings(ramp_points)
    total = float(ch[-1])
    n = math.floor(total / cfg.junction_search_spacing)
    out: list[_Candidate] = []
    for k in range(n + 1):
        s = k * cfg.junction_search_spacing
        i = int(np.searchsorted(ch, s, side="right") - 1)
        i = min(max(i, 0), ramp_points.shape[0] - 2)
        seg = float(ch[i + 1] - ch[i])
        t = (s - float(ch[i])) / seg if seg > 1e-12 else 0.0
        p = ramp_points[i] + t * (ramp_points[i + 1] - ramp_points[i])
        dz = float(p[2]) - z_level
        if dz > cfg.junction_window_above + 1e-9 or dz < -cfg.junction_window_below - 1e-9:
            continue
        if float(np.linalg.norm(p[:2] - anchor_xy)) > cfg.maximum_access_length:
            continue
        out.append(_Candidate(float(s), np.asarray(p, dtype=np.float64), float(az[i]), i))
    return out


@dataclass
class _PlanContext:
    """Everything constant across the levels of one plan (commit B refactor
    so the B-5 diagnostic can re-run one level's search verbatim)."""

    ramp_points: FloatArray
    ramp_ch: FloatArray
    cfg: LevelAccessConfig
    ramp: RampConstraints
    evaluator: DesignCostEvaluator
    shape: ProfileShape
    required_clearance: float
    g_max: float
    r_min: float
    preferred: float
    long_access_coef: float
    plan_sep_min: float
    exc_sep_min: float
    taper_arc: float


def _search_level(
    ctx: _PlanContext,
    lv: RequiredLevel,
    anchor: LevelDevelopmentAnchor,
    cands: list[_Candidate],
    used: list[float],
) -> tuple[tuple[tuple[float, float, float, int], LevelAccess] | None, int, int, dict[str, int]]:
    """One level's deterministic candidate search under EVERY hard gate.
    Returns (best, tried, valid, rejections). ``used`` carries the junction
    chainages already committed by shallower levels; the B-5 diagnostic
    calls this again with ``used = []`` to distinguish greedy assignment
    starvation from real geometric infeasibility — nothing is relaxed for
    the recorded result."""
    cfg, ramp_points = ctx.cfg, ctx.ramp_points
    rejections: dict[str, int] = {}
    reject = _rejecter(rejections)
    tried = 0
    valid = 0
    best: tuple[tuple[float, float, float, int], LevelAccess] | None = None
    for cand in cands:
        if any(abs(cand.chainage - u) < cfg.minimum_ramp_junction_spacing for u in used):
            reject(AccessFailure.JUNCTION_SPACING_CONFLICT)
            continue
        # B-3: the turnout must sit in ramp chainage that stays below the
        # curvature gate over ± the straight buffer (family-neutral)
        turnout_deg = turnout_heading_change_deg(
            ramp_points, ctx.ramp_ch, cand.chainage, cfg.minimum_turnout_straight_buffer
        )
        if turnout_deg > cfg.maximum_turnout_heading_change_deg + 1e-9:
            reject(AccessFailure.TURNOUT_NOT_STRAIGHT)
            continue
        # B-1: independent level-access SPACE is a plan-view quantity
        plan_sep = float(np.hypot(*(anchor.position[:2] - cand.position[:2])))
        if plan_sep < ctx.plan_sep_min - SEPARATION_TOLERANCE:
            reject(AccessFailure.INSUFFICIENT_RAMP_TO_ENTRY_SEPARATION)
            continue
        for sense_k, term in enumerate((anchor.heading, anchor.heading + math.pi)):
            tried += 1
            conn = build_connector(
                cand.position,
                cand.heading,
                anchor.position,
                term,
                ctx.r_min,
                cfg.access_sampling_spacing,
            )
            if conn is None:
                reject(AccessFailure.CONNECTOR_UNAVAILABLE)
                continue
            if abs(conn.gradient) > ctx.g_max + GRADIENT_TOLERANCE:
                reject(AccessFailure.GRADE_LIMIT)
                continue
            if conn.length3d > cfg.maximum_access_length:
                reject(AccessFailure.ACCESS_TOO_LONG)
                continue
            if conn.length3d < cfg.minimum_access_length:
                reject(AccessFailure.ACCESS_TOO_SHORT)
                continue
            pts = conn.points
            az = headings(pts)
            delta = unwrap_delta(az) if az.shape[0] > 1 else np.zeros(0)
            radii = plan_radii(pts, delta) if delta.shape[0] else np.zeros(0)
            turning = np.abs(delta) > STRAIGHT_HEADING_EPS if delta.shape[0] else np.zeros(0, bool)
            r_min_delivered = float(np.min(radii[turning])) if bool(np.any(turning)) else None
            if r_min_delivered is not None and r_min_delivered < ctx.r_min - RADIUS_TOLERANCE:
                reject(AccessFailure.TURN_RADIUS)
                continue
            # B-2: rock pillar on the DELIVERED branch beyond the geometric
            # turnout taper (terminal always judged) — a branch that runs
            # alongside any part of the ramp with a thin skin is rejected,
            # whatever its length
            _, exc_sep = gated_separation(pts, ramp_points, ctx.shape, ctx.taper_arc)
            if exc_sep < ctx.exc_sep_min - SEPARATION_TOLERANCE:
                reject(AccessFailure.INSUFFICIENT_RAMP_PILLAR)
                continue
            # hard validation of the delivered centerline (cover already
            # established: the branch starts underground on the ramp)
            ev, validation, finite = evaluate_and_validate(
                ctx.evaluator, pts, cover_established=True, stop_at_first=False
            )
            if validation.invalid_count > 0:
                worst = max(validation.rejection_reason_counts.items(), key=lambda kv: kv[1])[0]
                reject(_REASON_MAP.get(worst, AccessFailure.OREBODY_CLEARANCE))
                continue
            clearance = float(np.min(ev.orebody_distance))
            if clearance < ctx.required_clearance - 1e-9:
                reject(AccessFailure.OREBODY_CLEARANCE)
                continue
            # excavation envelope (rule 66 style): profile boundary points
            tangents = np.diff(pts, axis=0)
            tangents = np.vstack([tangents, tangents[-1:]])
            boundary = boundary_points(pts, tangents, ctx.shape).reshape(-1, 3)
            hard, above = ctx.evaluator.envelope_masks(boundary)
            if int(hard.sum()) > 0 or int(above.sum()) > 0:
                reject(AccessFailure.ENVELOPE_INVALID)
                continue
            valid += 1
            seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
            field_cost = float(np.sum(0.5 * (finite[:-1] + finite[1:]) * seg))
            cost = access_length_cost(conn.length3d, ctx.preferred, ctx.long_access_coef)
            key = (cost, conn.length3d, cand.chainage, sense_k)
            if best is None or key < best[0]:
                chosen = LevelAccess(
                    lv.level_id,
                    lv.elevation,
                    "OK",
                    anchor,
                    junction_chainage=cand.chainage,
                    junction_position=cand.position,
                    junction_heading=cand.heading,
                    junction_edge_index=cand.edge_index,
                    terminal_heading=term,
                    connector_word=conn.word,
                    pieces=conn.pieces,
                    points=pts,
                    length3d=conn.length3d,
                    horizontal_length=conn.horizontal_length,
                    max_gradient=abs(conn.gradient),
                    min_plan_radius=r_min_delivered,
                    field_cost=field_cost,
                    preferred_length=ctx.preferred,
                    length_deviation=conn.length3d - ctx.preferred,
                    selection_cost=cost,
                    validation={
                        "sampleCount": int(pts.shape[0]),
                        "invalidSampleCount": 0,
                        "envelopeHardViolations": 0,
                        "envelopeAboveTerrain": 0,
                        "minimumOrebodyDistance": clearance,
                        "requiredClearance": ctx.required_clearance,
                        "junctionWeldError": float(np.linalg.norm(pts[0] - cand.position)),
                        "entryWeldError": float(np.linalg.norm(pts[-1] - anchor.position)),
                    },
                )
                best = (key, chosen)
    return best, tried, valid, rejections


def plan_level_accesses(
    ramp_points: FloatArray,
    anchors: list[LevelDevelopmentAnchor | None],
    levels: list[RequiredLevel],
    cfg: LevelAccessConfig,
    ramp: RampConstraints,
    evaluator: DesignCostEvaluator,
    shape: ProfileShape,
    required_clearance: float,
    *,
    long_access_coef: float = LONG_ACCESS_COEF,
) -> LevelAccessPlan:
    """Deterministic level-access plan for one main ramp (top level first).
    Junction spacing is enforced against every already-selected junction.
    Phase 20B.1 B hard gates on every candidate: turnout curvature over the
    straight buffer (B-3), junction → entry plan separation (B-1) and the
    rock pillar on the delivered branch beyond the geometric turnout taper
    (B-2) — typed rejections, nothing clamped. Among the VALID candidates of
    a level the selection minimizes ``(access_length_cost(L, P), L, junction
    chainage, terminal sense)`` (closeout v3 §2, kept as the SECONDARY
    ordering under the gates). A level failing with junction-spacing
    conflicts records the B-5 assignment diagnostic (re-run ignoring only
    the used-junction spacing) so greedy starvation is distinguishable from
    real geometric infeasibility; no constraint is relaxed for the result."""
    g_max = cfg.max_gradient if cfg.max_gradient is not None else ramp.max_gradient
    r_min = cfg.min_turn_radius if cfg.min_turn_radius is not None else ramp.min_turn_radius
    preferred, preferred_source = effective_preferred_access_length(cfg, ramp)
    plan_sep_min = effective_plan_separation(cfg, ramp)
    exc_sep_min = effective_excavation_separation(cfg, ramp)
    taper = gate_taper_arc(r_min, exc_sep_min + ramp.tunnel_width)
    ctx = _PlanContext(
        ramp_points=ramp_points,
        ramp_ch=chainage(ramp_points),
        cfg=cfg,
        ramp=ramp,
        evaluator=evaluator,
        shape=shape,
        required_clearance=required_clearance,
        g_max=g_max,
        r_min=r_min,
        preferred=preferred,
        long_access_coef=long_access_coef,
        plan_sep_min=plan_sep_min,
        exc_sep_min=exc_sep_min,
        taper_arc=taper,
    )
    used: list[float] = []
    accesses: list[LevelAccess] = []
    for lv, anchor in zip(levels, anchors, strict=True):
        if anchor is None:
            accesses.append(
                LevelAccess(
                    lv.level_id,
                    lv.elevation,
                    "INFEASIBLE",
                    None,
                    failure_reason=AccessFailure.NO_ANCHOR,
                    failure_detail="no orebody section / development backbone at this level",
                )
            )
            continue
        access = LevelAccess(lv.level_id, lv.elevation, "INFEASIBLE", anchor)
        cands = _junction_candidates(ramp_points, lv.elevation, cfg, anchor.position[:2])
        if not cands:
            access.failure_reason = AccessFailure.NO_JUNCTION_IN_WINDOW
            access.failure_detail = (
                f"no ramp chainage within [{-cfg.junction_window_below:g}, "
                f"+{cfg.junction_window_above:g}] m of RL {lv.elevation:.1f} and "
                f"≤ {cfg.maximum_access_length:g} m from the anchor"
            )
            accesses.append(access)
            continue
        best, tried, valid, rejections = _search_level(ctx, lv, anchor, cands, used)
        if best is None:
            access.candidates_tried = tried
            access.candidates_valid = valid
            access.rejection_counts = rejections
            access.preferred_length = preferred
            top = (
                max(rejections.items(), key=lambda kv: (kv[1], kv[0]))[0]
                if rejections
                else (AccessFailure.TARGET_UNREACHABLE)
            )
            access.failure_reason = top
            access.failure_detail = (
                f"{tried} connector(s) from {len(cands)} junction candidate(s) rejected: "
                + ", ".join(f"{k} x{v}" for k, v in sorted(rejections.items()))
            )
            # B-5: distinguish greedy assignment starvation from geometry
            if rejections.get(AccessFailure.JUNCTION_SPACING_CONFLICT, 0) > 0:
                d_best, d_tried, d_valid, _ = _search_level(ctx, lv, anchor, cands, [])
                access.assignment_diagnostic = {
                    "starvationSuspected": d_best is not None,
                    "validCandidatesIgnoringSpacing": d_valid,
                    "connectorsTriedIgnoringSpacing": d_tried,
                    "note": (
                        "diagnostic re-run ignoring ONLY the junction spacing "
                        "already used by shallower levels; the recorded failure "
                        "relaxed nothing"
                    ),
                }
            accesses.append(access)
            continue
        chosen = best[1]
        chosen.candidates_tried = tried
        chosen.candidates_valid = valid
        chosen.rejection_counts = rejections
        # observability of the SELECTED branch — same taper as the B-2 gate
        fill_separation_metrics(chosen, ramp_points, ctx.ramp_ch, ctx.shape, taper)
        used.append(float(chosen.junction_chainage or 0.0))
        accesses.append(chosen)
    return LevelAccessPlan(
        accesses,
        g_max,
        r_min,
        required_clearance,
        preferred_length=preferred,
        preferred_source=preferred_source,
        long_access_coef=long_access_coef,
        plan_separation_required=plan_sep_min,
        excavation_separation_required=exc_sep_min,
        turnout_buffer=float(cfg.minimum_turnout_straight_buffer),
        turnout_max_heading_deg=float(cfg.maximum_turnout_heading_change_deg),
        gate_taper_arc_m=taper,
    )
