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
  ramp-junction candidates inside a chainage / elevation window, a ONE-TURN
  CS connector (Phase 20B.2-A: one arc of R = R_min, left or right, then a
  straight — or a pure straight when the junction already faces the entry)
  from the junction pose to the anchor POINT with a free terminal heading,
  chord-exact constant vertical gradient, and hard validation of the
  DELIVERED polyline (gradient, plan circumradius, world, cover, restricted
  zones, orebody clearance under the evaluator's policy, excavation
  envelope, plan separation, direction-aware pillar). Junction spacing is a
  hard rule. Every failure is a typed reason; nothing is clamped. The old
  Dubins CSC (arc–straight–arc, G1 to the drift heading) is gone: a level
  access meets the footwall drift at a T/Y junction and the drift absorbs
  the direction change, so the second arc only ever added a loop.

  Among the candidates that pass EVERY hard check, selection minimizes
  ``(access_length_cost(L, P), L, junction chainage, connector sense)`` with
  ``P`` = the effective PREFERRED access length (rule 163) — not the shortest
  branch — and the connector sense ordered ``S < LS < RS``
  (``CONNECTOR_SENSE_ORDER``). Hard limits are never traded against that cost.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy.spatial import cKDTree

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
#: Phase 20B.2-A: a turnout arc never sweeps past a U-turn. A one-turn CS
#: solution whose arc would exceed this is refused for that sense
#: (CONNECTOR_UNAVAILABLE) — that is the structural ban on loops.
MAX_TURNOUT_SWEEP = math.pi
#: deterministic connector-sense order of the selection key (last element)
CONNECTOR_SENSE_ORDER: tuple[str, ...] = ("S", "LS", "RS")
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
    #: Phase 20C.2A curved-anchor fields (None on the exact TABULAR line
    #: anchor): the entry as a chainage on the level's offset development
    #: trace, with its local frame and nearest ore contact
    trace_chainage: float | None = None
    trace_length: float | None = None
    local_tangent: FloatArray | None = None  # (2,) unit, trace orientation
    local_normal: FloatArray | None = None  # (2,) unit, INWARD (toward ore)
    ore_contact: FloatArray | None = None  # (3,) nearest contact-trace vertex
    selected_component_id: int | None = None
    section_sampling_spacing: float | None = None  # configured base spacing
    section_effective_spacing: float | None = None  # refined grid spacing

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
            "traceChainage": self.trace_chainage,
            "traceLength": self.trace_length,
            "localTangent": (
                [float(v) for v in self.local_tangent] if self.local_tangent is not None else None
            ),
            "localNormal": (
                [float(v) for v in self.local_normal] if self.local_normal is not None else None
            ),
            "oreContact": (
                [float(v) for v in self.ore_contact] if self.ore_contact is not None else None
            ),
            "selectedComponentId": self.selected_component_id,
            "sectionSamplingSpacing": self.section_sampling_spacing,
            "sectionEffectiveSpacing": self.section_effective_spacing,
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


def _ramp_reference(ramp_points: FloatArray, z: float) -> FloatArray:
    """Main-ramp level reference: the z-crossing point, else the ramp vertex
    closest to the level elevation."""
    cr = find_crossing(ramp_points, z)
    if cr is not None:
        return np.asarray(cr.point, dtype=np.float64)
    i = int(np.argmin(np.abs(ramp_points[:, 2] - z)))
    return np.asarray(ramp_points[i], dtype=np.float64)


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
    ref = _ramp_reference(ramp_points, z)
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


#: minimum offset-trace arc length that can host a level development —
#: room for the entry end margins plus one positive drift span (a planning
#: floor, never statutory)
MIN_DEVELOPMENT_TRACE_LENGTH = 2.0 * BACKBONE_END_MARGIN


def build_curved_anchor(
    orebody: Orebody,
    level: RequiredLevel,
    sections: LevelSections,
    w_h: FloatArray,
    u_h: FloatArray,
    ramp_points: FloatArray,
    standoff: float,
    mining_method: str,
) -> LevelDevelopmentAnchor | None:
    """Phase 20C.2A curved level-development anchor for implicit orebodies.

    The backbone is the level's OFFSET DEVELOPMENT TRACE (the EDT level set
    at ``standoff`` from the dominant section component, adjacent to the
    dominant footwall trace — ``layout.sections``), never a global principal
    axis. ``w_h`` is the footwall-side orientation seed only; ``u_h`` is
    used solely for the PCA-comparison diagnostic. Entry policy
    NEAREST_TO_RAMP: the admissible trace chainage (inside the end margins)
    whose point is plan-closest to the main ramp's level reference —
    deterministic (ties resolve to the lowest chainage). The preferred
    terminal heading is the LOCAL trace tangent, oriented toward the longer
    usable trace side (tie: along the deterministic trace orientation).

    Returns ``None`` for an empty section (NO_ANCHOR, as before); section
    trace failures raise typed ``SectionGeometryError``
    (SECTION_FOOTWALL_AMBIGUOUS / SECTION_TRACE_OFFSET_INVALID /
    SECTION_RESOLUTION_BUDGET_EXCEEDED) for the caller to record."""
    if sections.geometry(level).empty:
        return None
    z = level.elevation
    ref = _ramp_reference(ramp_points, z)
    trace = sections.footwall_trace(level, w_h)
    off = sections.offset_trace(level, w_h, standoff, MIN_DEVELOPMENT_TRACE_LENGTH)
    total = off.total_length
    margin = min(BACKBONE_END_MARGIN, 0.25 * total)
    admissible = (off.chainage >= margin - 1e-9) & (off.chainage <= total - margin + 1e-9)
    if not bool(admissible.any()):  # pragma: no cover — total ≥ 2·margin by the trace gate
        admissible = np.ones(off.chainage.shape[0], dtype=bool)
    d = np.hypot(off.points[:, 0] - ref[0], off.points[:, 1] - ref[1])
    d = np.where(admissible, d, np.inf)
    i = int(np.argmin(d))  # ties → lowest chainage (first index)
    t = float(off.chainage[i])
    pos = off.points[i].copy()
    tangent = off.tangents[i].copy()
    forward_len = total - t
    backward_len = t
    direction = tangent if forward_len >= backward_len else -tangent
    inward = off.ore_contact[i, :2] - pos[:2]
    n_in = float(np.linalg.norm(inward))
    inward = inward / n_in if n_in > 1e-12 else -off.tangents[i]
    # heading-frame extent: 0 at the entry, positive along the heading
    ahead, behind = (
        (forward_len, backward_len) if forward_len >= backward_len else (backward_len, forward_len)
    )
    sec = sections.section(level)
    pca_axis = _principal_axis(sec.inside_xy, u_h)
    cosang = abs(float(np.clip(pca_axis @ tangent, -1.0, 1.0)))
    res = sections.resolution
    assert res is not None  # offset_trace above already required it
    diag: dict[str, Any] = {
        "backbone": "SECTION_FOOTWALL_OFFSET_TRACE",
        "entryPolicy": "NEAREST_TO_RAMP",
        "traceDiagnostics": off.diagnostics,
        "footwallTrace": {
            "totalLength": trace.total_length,
            "vertexCount": int(trace.contact_points.shape[0]),
            **{k: trace.diagnostics[k] for k in ("orientationFlipped", "footwallRunCount")},
        },
        "endMargin": margin,
        "referenceOffset": float(np.hypot(*(ref[:2] - pos[:2]))),
        "localTangentAzimuthDeg": math.degrees(_azimuth(direction)),
        "localTangentVsGlobalPcaDeg": math.degrees(math.acos(cosang)),
    }
    return LevelDevelopmentAnchor(
        level_id=level.level_id,
        elevation=z,
        position=pos,
        heading=_azimuth(direction),
        backbone_direction=np.asarray(direction, dtype=np.float64),
        backbone_extent=(-behind, ahead),
        role="FOOTWALL_DRIFT_ENTRY",
        orebody_side="FOOTWALL",
        mining_method=mining_method,
        standoff=standoff,
        ramp_reference=ref,
        diagnostics=diag,
        trace_chainage=t,
        trace_length=total,
        local_tangent=np.asarray(tangent, dtype=np.float64),
        local_normal=np.asarray(inward, dtype=np.float64),
        ore_contact=off.ore_contact[i].copy(),
        selected_component_id=sections.geometry(level).selected_component_id,
        section_sampling_spacing=res.base_spacing,
        section_effective_spacing=res.effective_spacing,
    )


# --------------------------------------------------------------------------- #
# One-turn CS connector (plan) with chord-exact vertical (Phase 20B.2-A)
# --------------------------------------------------------------------------- #


def _mod2pi(a: float) -> float:
    return a - 2.0 * math.pi * math.floor(a / (2.0 * math.pi))


def _sample_word(
    start_xy: FloatArray,
    theta0: float,
    word: str,
    tpq: tuple[float, ...],
    radius: float,
    spacing: float,
) -> tuple[FloatArray, list[dict[str, Any]]]:
    """Sample a connector word from the start pose (math angle θ0). Arc points
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


def _cs_solution(
    start_xy: FloatArray, theta0: float, end_xy: FloatArray, radius: float, kind: str
) -> tuple[str, tuple[float, ...], float] | None:
    """Analytic one-turn tangent geometry for ONE sense (``kind`` = L or R):
    the turning circle of the start pose, the tangent from it through the
    target point, the arc sweep ``t`` to the tangent point and the straight
    ``ℓ = sqrt(|C→P|² − R²)``. Returns ``(word, normalized pieces, terminal
    math angle)`` or ``None`` when the target lies inside the turning circle
    or the sweep would exceed ``MAX_TURNOUT_SWEEP``. A vanishing sweep
    collapses to the pure straight ``S``."""
    sgn = 1.0 if kind == "L" else -1.0
    cx = float(start_xy[0]) - sgn * radius * math.sin(theta0)
    cy = float(start_xy[1]) + sgn * radius * math.cos(theta0)
    dx, dy = float(end_xy[0]) - cx, float(end_xy[1]) - cy
    d_c = math.hypot(dx, dy)
    if d_c < radius - 1e-12:
        return None
    ell = math.sqrt(max(d_c * d_c - radius * radius, 0.0))
    psi = math.atan2(dy, dx)
    gamma = psi - sgn * math.atan2(ell, radius)  # tangent point angle on the circle
    gamma0 = theta0 - sgn * math.pi / 2.0  # start point angle on the circle
    t = _mod2pi(sgn * (gamma - gamma0))
    if t > MAX_TURNOUT_SWEEP + 1e-9:
        return None
    if t < 1e-9:
        return "S", (ell / radius,), theta0
    return kind + "S", (t, ell / radius), theta0 + sgn * t


@dataclass
class Connector:
    word: str  # S | LS | RS
    points: FloatArray  # (N, 3) delivered polyline
    pieces: list[dict[str, Any]]
    horizontal_length: float
    length3d: float
    gradient: float  # signed Δz / chord length (constant along the branch)
    #: compass heading (rad, clockwise from +Y) of the final straight — the
    #: access's ACTUAL terminal heading, free of the drift direction
    terminal_heading: float
    #: CCW | CW | None (pure straight)
    sense: str | None
    #: position of ``word`` in CONNECTOR_SENSE_ORDER — the selection tie-break
    sense_rank: int
    arc_length: float
    straight_length: float


def build_connector(
    start: FloatArray,
    start_heading: float,
    end: FloatArray,
    radius: float,
    spacing: float,
    kind: str = "L",
) -> Connector | None:
    """One-turn CS connector of sense ``kind`` (L = CCW, R = CW) from
    ``start`` heading ``start_heading`` (compass) to the POINT ``end``; the
    terminal heading is free. z is assigned linearly in delivered CHORD
    length so every edge carries the same gradient. Endpoints are exact.
    ``None`` when no tangent exists for that sense (target inside the turning
    circle, sweep past a U-turn, or a degenerate coincident pose)."""
    dxy = np.asarray(end[:2], dtype=np.float64) - np.asarray(start[:2], dtype=np.float64)
    if float(np.linalg.norm(dxy)) < MIN_CONNECTOR_LENGTH:
        return None
    th0 = math.pi / 2.0 - start_heading  # math angle, counter-clockwise from +X
    sol = _cs_solution(np.asarray(start[:2], dtype=np.float64), th0, end[:2], radius, kind)
    if sol is None:
        return None
    word, tp, th_end = sol
    xy, pieces = _sample_word(np.asarray(start[:2]), th0, word, tp, radius, spacing)
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
    arc_len = sum(p["angleDeg"] / 180.0 * math.pi * radius for p in pieces if p["kind"] == "ARC")
    straight = sum(float(p["length"]) for p in pieces if p["kind"] == "STRAIGHT")
    sense = None if word == "S" else ("CCW" if word[0] == "L" else "CW")
    return Connector(
        word,
        pts,
        pieces,
        total,
        length3d,
        grad,
        terminal_heading=_mod2pi(math.pi / 2.0 - th_end),
        sense=sense,
        sense_rank=CONNECTOR_SENSE_ORDER.index(word),
        arc_length=float(arc_len),
        straight_length=float(straight),
    )


def build_cs_connectors(
    start: FloatArray, start_heading: float, end: FloatArray, radius: float, spacing: float
) -> list[Connector]:
    """Every distinct one-turn CS connector from the junction pose to the
    entry point, in deterministic sense order (L then R; a pure straight is
    reported once). Both senses are always evaluated — the planner judges
    each on its delivered polyline and picks by the selection key."""
    out: list[Connector] = []
    for kind in ("L", "R"):
        conn = build_connector(start, start_heading, end, radius, spacing, kind)
        if conn is None:
            continue
        if conn.word == "S" and any(c.word == "S" for c in out):
            continue
        out.append(conn)
    return out


def heading_axis_mismatch_deg(heading: float, axis_heading: float) -> float:
    """Angle (deg, 0–90) between a heading and an UNDIRECTED axis — the
    access terminal heading against the drift axis it meets at the level
    entry (either drift direction is a valid T/Y junction)."""
    d = abs(_mod2pi(heading - axis_heading + math.pi) - math.pi)
    return math.degrees(min(d, math.pi - d))


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
    #: Phase 20B.2-A: the access's ACTUAL final straight heading (free of the
    #: drift direction) and its angle to the drift axis it meets
    terminal_heading: float | None = None
    terminal_heading_mismatch_deg: float | None = None
    connector_word: str | None = None
    turnout_arc_length: float | None = None
    straight_length: float | None = None
    path_to_chord_ratio: float | None = None
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
            "terminalHeadingMismatchDeg": self.terminal_heading_mismatch_deg,
            "connector": self.connector_word,
            "turnoutArcLength": self.turnout_arc_length,
            "straightLength": self.straight_length,
            "pathToChordRatio": self.path_to_chord_ratio,
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
            # Phase 20B.2-A one-turn CS observability
            "maxTerminalHeadingMismatchDeg": _max_or_none(
                a.terminal_heading_mismatch_deg for a in ok
            ),
            "maxTurnoutArcLength": _max_or_none(a.turnout_arc_length for a in ok),
            "maxPathToChordRatio": _max_or_none(a.path_to_chord_ratio for a in ok),
            "connectorWords": {
                w: sum(1 for a in ok if a.connector_word == w) for w in CONNECTOR_SENSE_ORDER
            },
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
    points: FloatArray, polyline: FloatArray, tree: cKDTree | None = None
) -> tuple[FloatArray, FloatArray, npt.NDArray[np.intp]]:
    """Closest-centerline pair for each of ``points`` (N, 3) against the
    segments of ``polyline`` (M, 3): (distance, closest point, segment index).
    Exact point-to-segment distances, fully vectorized (N × M pairs; an
    access branch has tens of samples).

    ``tree`` (Phase 20C.1-Q, optional): a ``cKDTree`` of the polyline
    VERTICES. With it the exact projection runs only on the segments that can
    hold a nearest point — every point's nearest vertex lies within
    ``d_v`` and any point of a segment is within one segment length of an
    endpoint, so a segment closer than ``d_v`` has an endpoint inside
    ``max(d_v) + max segment length``; the candidate set is that ball's
    union. Distances and the ascending-index tie-break are IDENTICAL to the
    full evaluation — a pure cost reduction, never an approximation."""
    p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    segs: npt.NDArray[np.intp] | None = None
    if tree is not None and polyline.shape[0] > 2:
        d_v, _ = tree.query(p)
        seg_len_max = float(np.max(np.linalg.norm(np.diff(polyline, axis=0), axis=1)))
        radius = float(np.max(d_v)) + seg_len_max + 1e-9
        balls = tree.query_ball_point(p, radius)
        verts = np.unique(np.concatenate([np.asarray(i, dtype=np.intp) for i in balls]))
        segs = np.unique(np.concatenate([verts - 1, verts]))
        segs = segs[(segs >= 0) & (segs < polyline.shape[0] - 1)]
        a, b = polyline[segs], polyline[segs + 1]
    else:
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
    out_seg = segs[seg] if segs is not None else seg
    return dist[rows, seg], closest[rows, seg], out_seg


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
    tree: cKDTree | None = None,
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
    d, closest, seg = nearest_on_polyline(judged, ramp_points, tree)
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
    ch: FloatArray | None = None,
    az: FloatArray | None = None,
) -> list[_Candidate]:
    """Junction lattice of one level; ``ch`` / ``az`` are the ramp chainage
    and edge headings when the caller already holds them (same values)."""
    if ch is None:
        ch = chainage(ramp_points)
    if az is None:
        az = headings(ramp_points)
    total = float(ch[-1])
    n = math.floor(total / cfg.junction_search_spacing)
    # vectorized lattice (Phase 20C.1-Q cost reduction; the per-point
    # arithmetic is unchanged, so every candidate is bit-identical)
    s_all = np.arange(n + 1, dtype=np.float64) * cfg.junction_search_spacing
    idx = np.searchsorted(ch, s_all, side="right") - 1
    idx = np.clip(idx, 0, ramp_points.shape[0] - 2)
    seg = ch[idx + 1] - ch[idx]
    t = np.where(seg > 1e-12, (s_all - ch[idx]) / np.where(seg > 1e-12, seg, 1.0), 0.0)
    p_all = ramp_points[idx] + t[:, None] * (ramp_points[idx + 1] - ramp_points[idx])
    dz = p_all[:, 2] - z_level
    keep = (dz <= cfg.junction_window_above + 1e-9) & (dz >= -cfg.junction_window_below - 1e-9)
    keep &= np.linalg.norm(p_all[:, :2] - anchor_xy, axis=1) <= cfg.maximum_access_length
    return [
        _Candidate(
            float(s_all[k]), np.asarray(p_all[k], dtype=np.float64), float(az[idx[k]]), int(idx[k])
        )
        for k in np.flatnonzero(keep)
    ]


@dataclass
class _PlanContext:
    """Everything constant across the levels of one plan (commit B refactor
    so the B-5 diagnostic can re-run one level's search verbatim)."""

    ramp_points: FloatArray
    ramp_ch: FloatArray
    #: vertex KD-tree of the main ramp (exact nearest-segment pre-filter)
    ramp_tree: cKDTree
    ramp_az: FloatArray
    cfg: LevelAccessConfig
    ramp: RampConstraints
    #: None only for the evaluator-free GEOMETRIC screen (Phase 20C.1-Q)
    evaluator: DesignCostEvaluator | None
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
    *,
    geometric_only: bool = False,
) -> tuple[tuple[tuple[float, float, float, int], LevelAccess] | None, int, int, dict[str, int]]:
    """One level's deterministic candidate search under EVERY hard gate.
    Returns (best, tried, valid, rejections). ``used`` carries the junction
    chainages already committed by shallower levels; the B-5 diagnostic
    calls this again with ``used = []`` to distinguish greedy assignment
    starvation from real geometric infeasibility — nothing is relaxed for
    the recorded result.

    ``geometric_only`` (Phase 20C.1-Q geometric access screen): the SAME
    gate sequence up to and including the B-2 rock pillar — everything that
    needs no evaluator — and the search stops at the first candidate that
    passes them (``valid = 1``, ``best = None``); the evaluator gates
    (centerline validation, clearance, envelope) are never reached. A level
    with ``valid == 0`` here has no candidate that could pass stage 4."""
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
        conns = build_cs_connectors(
            cand.position, cand.heading, anchor.position, ctx.r_min, cfg.access_sampling_spacing
        )
        if not conns:
            tried += 1
            reject(AccessFailure.CONNECTOR_UNAVAILABLE)
            continue
        for conn in conns:
            tried += 1
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
            _, exc_sep = gated_separation(pts, ramp_points, ctx.shape, ctx.taper_arc, ctx.ramp_tree)
            if exc_sep < ctx.exc_sep_min - SEPARATION_TOLERANCE:
                reject(AccessFailure.INSUFFICIENT_RAMP_PILLAR)
                continue
            if geometric_only:
                return None, tried, valid + 1, rejections
            assert ctx.evaluator is not None
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
            key = (cost, conn.length3d, cand.chainage, conn.sense_rank)
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
                    terminal_heading=conn.terminal_heading,
                    terminal_heading_mismatch_deg=heading_axis_mismatch_deg(
                        conn.terminal_heading, anchor.heading
                    ),
                    connector_word=conn.word,
                    turnout_arc_length=conn.arc_length,
                    straight_length=conn.straight_length,
                    path_to_chord_ratio=(
                        conn.horizontal_length / plan_sep if plan_sep > 1e-9 else None
                    ),
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


def _plan_context(
    ramp_points: FloatArray,
    cfg: LevelAccessConfig,
    ramp: RampConstraints,
    evaluator: DesignCostEvaluator | None,
    shape: ProfileShape,
    required_clearance: float,
    long_access_coef: float,
) -> _PlanContext:
    g_max = cfg.max_gradient if cfg.max_gradient is not None else ramp.max_gradient
    r_min = cfg.min_turn_radius if cfg.min_turn_radius is not None else ramp.min_turn_radius
    preferred, _ = effective_preferred_access_length(cfg, ramp)
    plan_sep_min = effective_plan_separation(cfg, ramp)
    exc_sep_min = effective_excavation_separation(cfg, ramp)
    return _PlanContext(
        ramp_points=ramp_points,
        ramp_ch=chainage(ramp_points),
        ramp_tree=cKDTree(np.asarray(ramp_points, dtype=np.float64)),
        ramp_az=headings(ramp_points),
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
        taper_arc=gate_taper_arc(r_min, exc_sep_min + ramp.tunnel_width),
    )


#: What a BLOCKED level of the geometric access screen proves (Phase 20C.1
#: closeout B). The screen runs the evaluator-free stage-4 gates on
#: coarse-stand-off anchors, so its authority is decided by whether stage 4
#: can still change the anchor — i.e. by the CLEARANCE POLICY's distance
#: contract, never by the orebody type.
SCREEN_NECESSARY_CONDITION = "NECESSARY_CONDITION"
SCREEN_HEURISTIC = "HEURISTIC"


def geometric_access_screen(
    ramp_points: FloatArray,
    anchors: list[LevelDevelopmentAnchor | None],
    levels: list[RequiredLevel],
    cfg: LevelAccessConfig,
    ramp: RampConstraints,
    shape: ProfileShape,
    authority: str = SCREEN_HEURISTIC,
) -> dict[str, Any]:
    """Phase 20C.1-Q evaluator-free GEOMETRIC access screen: for every
    required level, whether at least one junction candidate of the stage-4
    lattice passes the evaluator-free hard gates — turnout curvature (B-3),
    plan separation (B-1), connector availability, gradient, length, plan
    radius and the rock pillar (B-2) — with the junction-spacing assignment
    ignored. It is the SAME code path ``plan_level_accesses`` runs
    (``_search_level(geometric_only=True)``). It never rejects a candidate;
    the search uses the blocked count only for stage-3 ordering (rule 176)
    and stage 4 stays the final authority.

    ``authority`` (closeout B) records what a BLOCKED level PROVES, and it
    is decided by the caller's CLEARANCE POLICY, never by the orebody type:

    ``NECESSARY_CONDITION`` — the policy's distance contract is exact, so
        the anchor the screen used IS the anchor stage 4 will use and the
        gates judged here are the same gates: a blocked level cannot become
        served (``blocked ⊆ stage-4 failed``).
    ``HEURISTIC`` — under a conservative (derived-approximate) contract the
        anchors given here sit at the COARSE stand-off; stage 4 may refine
        the bound, shrink the stand-off and move the entry, so a blocked
        level can still be served. Nothing here is provable and the count
        must not be treated as a necessary condition."""
    ctx = _plan_context(ramp_points, cfg, ramp, None, shape, 0.0, LONG_ACCESS_COEF)
    per_level: dict[str, dict[str, Any]] = {}
    blocked: list[str] = []
    for lv, anchor in zip(levels, anchors, strict=True):
        entry: dict[str, Any] = {"blocked": False, "reason": None, "rejectionCounts": {}}
        if anchor is None:
            entry.update({"blocked": True, "reason": AccessFailure.NO_ANCHOR})
        else:
            cands = _junction_candidates(
                ramp_points, lv.elevation, cfg, anchor.position[:2], ctx.ramp_ch, ctx.ramp_az
            )
            if not cands:
                entry.update({"blocked": True, "reason": AccessFailure.NO_JUNCTION_IN_WINDOW})
            else:
                _, _, valid, rejections = _search_level(
                    ctx, lv, anchor, cands, [], geometric_only=True
                )
                entry["rejectionCounts"] = rejections
                if valid == 0:
                    top = max(rejections.items(), key=lambda kv: (kv[1], kv[0]))[0]
                    entry.update({"blocked": True, "reason": top})
        if entry["blocked"]:
            blocked.append(lv.level_id)
        per_level[lv.level_id] = entry
    return {
        "blockedLevelIds": blocked,
        "blockedCount": len(blocked),
        "authority": authority,
        "levels": per_level,
    }


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
    chainage, connector sense S < LS < RS)`` (closeout v3 §2, kept as the SECONDARY
    ordering under the gates). A level failing with junction-spacing
    conflicts records the B-5 assignment diagnostic (re-run ignoring only
    the used-junction spacing) so greedy starvation is distinguishable from
    real geometric infeasibility; no constraint is relaxed for the result."""
    preferred, preferred_source = effective_preferred_access_length(cfg, ramp)
    ctx = _plan_context(
        ramp_points, cfg, ramp, evaluator, shape, required_clearance, long_access_coef
    )
    g_max, r_min = ctx.g_max, ctx.r_min
    plan_sep_min, exc_sep_min, taper = ctx.plan_sep_min, ctx.exc_sep_min, ctx.taper_arc
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
        cands = _junction_candidates(
            ramp_points, lv.elevation, cfg, anchor.position[:2], ctx.ramp_ch, ctx.ramp_az
        )
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
