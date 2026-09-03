"""Decline access elevations and level-aware footwall access candidates
(CLAUDE.md rules 43–45). No path search happens here.

Levels
------
From the analytic orebody's vertical extent ``[z_min, z_max]`` (slab
corners), level elevations start at ``z_max − top_margin`` and step down by
``sublevel_interval`` while ``≥ z_min + bottom_margin``.

Candidates
----------
For each level, ``candidate_count`` candidates spread ``±span/2`` along
strike around the orebody center. Each satisfies exactly:

    P = C + u·u_coord + v·v_coord + w·q,     q = thickness/2 + footwall_access_offset
    P.z = z_level   ⇒   v_coord = (z_level − C.z − q·w.z) / v.z

so every candidate on a level shares the elevation and the perpendicular
footwall offset; only ``u_coord`` varies. Candidates outside the orebody's
strike/dip extent or rejected by the cost evaluator are kept with reasons.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.core.coordinates import decline_heuristic_distance
from minegen.core.models import DesignConfig, Point3D, RampConstraints, Scenario
from minegen.design.constraints import RejectionReason
from minegen.design.cost_field import DesignCostEvaluator
from minegen.world.orebody import Orebody, TabularOrebody
from minegen.world.synthetic_world import SyntheticWorld
from minegen.world.terrain import Terrain

FloatArray = npt.NDArray[np.float64]


@dataclass
class AccessCandidate:
    id: str
    level_id: str
    position: FloatArray
    u_coord: float
    v_coord: float
    footwall_offset: float  # perpendicular distance beyond the footwall contact
    valid: bool
    rejection_reasons: list[RejectionReason] = field(default_factory=list)
    rock_quality: float = math.nan
    fault_penalty: float = math.nan
    point_cost_per_m: float = math.nan  # inf if invalid
    next_level_accessibility: float | None = None  # heuristic distance, rule 45

    def to_dict(self) -> dict[str, Any]:
        def f(v: float) -> float | None:
            return float(v) if math.isfinite(v) else None

        return {
            "id": self.id,
            "levelId": self.level_id,
            "position": [float(c) for c in self.position],
            "uCoord": self.u_coord,
            "vCoord": self.v_coord,
            "footwallOffset": self.footwall_offset,
            "valid": self.valid,
            "rejectionReasons": [r.value for r in self.rejection_reasons],
            "rockQuality": f(self.rock_quality),
            "faultPenalty": f(self.fault_penalty),
            "pointCostPerM": f(self.point_cost_per_m),
            "nextLevelAccessibility": f(self.next_level_accessibility)
            if self.next_level_accessibility is not None
            else None,
        }


@dataclass
class LevelAccessTargets:
    level_id: str
    index: int  # 0 = top
    elevation: float
    candidates: list[AccessCandidate]

    @property
    def valid_candidates(self) -> list[AccessCandidate]:
        return [c for c in self.candidates if c.valid]

    def to_dict(self) -> dict[str, Any]:
        return {
            "levelId": self.level_id,
            "index": self.index,
            "elevation": self.elevation,
            "nValid": len(self.valid_candidates),
            "nRejected": len(self.candidates) - len(self.valid_candidates),
            "candidates": [c.to_dict() for c in self.candidates],
        }


@dataclass
class AccessTargetSet:
    portal: FloatArray
    portal_generated: bool
    levels: list[LevelAccessTargets]

    def to_dict(self) -> dict[str, Any]:
        n_valid = sum(len(lv.valid_candidates) for lv in self.levels)
        n_all = sum(len(lv.candidates) for lv in self.levels)
        return {
            "portal": [float(c) for c in self.portal],
            "portalGenerated": self.portal_generated,
            "nLevels": len(self.levels),
            "nCandidates": n_all,
            "nValid": n_valid,
            "nRejected": n_all - n_valid,
            "levels": [lv.to_dict() for lv in self.levels],
        }


# --------------------------------------------------------------------------- #
# Levels
# --------------------------------------------------------------------------- #


def generate_level_elevations(
    orebody: Orebody, sublevel_interval: float, top_margin: float, bottom_margin: float
) -> list[float]:
    lo, hi = orebody.bounding_box()
    z_min, z_max = float(lo[2]), float(hi[2])
    first = z_max - top_margin
    floor = z_min + bottom_margin
    if first < floor:
        return []
    n = math.floor((first - floor) / sublevel_interval) + 1
    return [first - i * sublevel_interval for i in range(n)]


def level_id(index: int, elevation: float) -> str:
    return f"L{index + 1:02d}"


# --------------------------------------------------------------------------- #
# Candidates
# --------------------------------------------------------------------------- #


def footwall_candidate_position(
    orebody: TabularOrebody, u_coord: float, z_level: float, footwall_offset: float
) -> tuple[FloatArray, float, float]:
    """Returns ``(P, v_coord, q)`` per rule 43. ``v.z`` is never zero because
    the schema requires ``dip > 0``."""
    q = orebody.half_thickness + footwall_offset
    c = orebody.center
    v_z = float(orebody.v[2])
    v_coord = (z_level - float(c[2]) - q * float(orebody.w[2])) / v_z
    p = c + u_coord * orebody.u + v_coord * orebody.v + q * orebody.w
    return p, v_coord, q


def footwall_contact_v_coord(orebody: TabularOrebody, z_level: float) -> float:
    """Down-dip coordinate of the footwall *contact* (offset 0) at ``z_level``.
    Ore exists next to a level iff this lies within the slab's dip extent;
    the candidate's own ``v_coord`` projects further up-dip because the
    perpendicular offset has a vertical component, so it is not the right test."""
    q = orebody.half_thickness
    c = orebody.center
    return (z_level - float(c[2]) - q * float(orebody.w[2])) / float(orebody.v[2])


def generate_access_targets(
    world: SyntheticWorld,
    cfg: DesignConfig,
    ramp: RampConstraints,
    sublevel_interval: float,
    evaluator: DesignCostEvaluator,
    portal: FloatArray,
    portal_generated: bool,
) -> AccessTargetSet:
    ob = world.orebody
    if not isinstance(ob, TabularOrebody):
        raise NotImplementedError("access targets are implemented for TABULAR orebodies only")

    elevations = generate_level_elevations(
        ob, sublevel_interval, cfg.top_mining_margin, cfg.bottom_mining_margin
    )
    n = cfg.candidate_count
    u_coords = (
        np.linspace(-cfg.candidate_along_strike_span / 2, cfg.candidate_along_strike_span / 2, n)
        if n > 1
        else np.array([0.0])
    )

    levels: list[LevelAccessTargets] = []
    for li, z in enumerate(elevations):
        lid = level_id(li, z)
        contact_ok = abs(footwall_contact_v_coord(ob, z)) <= ob.half_height
        cands: list[AccessCandidate] = []
        for ci, u in enumerate(u_coords):
            p, v_coord, _ = footwall_candidate_position(
                ob, float(u), z, ramp.footwall_access_offset
            )
            reasons: list[RejectionReason] = []
            if abs(u) > ob.half_length:
                reasons.append(RejectionReason.OUTSIDE_OREBODY_STRIKE_EXTENT)
            if not contact_ok:
                reasons.append(RejectionReason.OUTSIDE_OREBODY_DIP_EXTENT)
            cands.append(
                AccessCandidate(
                    id=f"{lid}-C{ci + 1:02d}",
                    level_id=lid,
                    position=p,
                    u_coord=float(u),
                    v_coord=float(v_coord),
                    footwall_offset=ramp.footwall_access_offset,
                    valid=not reasons,
                    rejection_reasons=reasons,
                )
            )
        levels.append(LevelAccessTargets(level_id=lid, index=li, elevation=z, candidates=cands))

    # one batched cost evaluation for every candidate
    all_c = [c for lv in levels for c in lv.candidates]
    if all_c:
        ev = evaluator.evaluate_points(np.array([c.position for c in all_c]))
        for i, c in enumerate(all_c):
            c.rock_quality = float(ev.rock_quality[i])
            c.fault_penalty = float(ev.fault_penalty[i])
            c.point_cost_per_m = float(ev.total_cost_per_m[i])
            c.rejection_reasons.extend(ev.rejection_reasons[i])
            c.valid = c.valid and bool(ev.valid[i])
            if not c.valid:
                c.point_cost_per_m = math.inf

    # next-level accessibility: admissible heuristic distance only (rule 45)
    for lv, nxt in pairwise(levels):
        targets = nxt.valid_candidates or nxt.candidates
        for c in lv.candidates:
            c.next_level_accessibility = min(
                decline_heuristic_distance(c.position, t.position, ramp.max_gradient)
                for t in targets
            )

    return AccessTargetSet(portal=portal, portal_generated=portal_generated, levels=levels)


# --------------------------------------------------------------------------- #
# Portal
# --------------------------------------------------------------------------- #


def entry_burial_margin(
    terrain: Terrain,
    portal_xy: FloatArray,
    direction_xy: FloatArray,
    max_gradient: float,
    *,
    length: float = 120.0,
    step: float = 5.0,
    lead_in: float = 20.0,
) -> float:
    """Minimum (terrain − decline) clearance along a straight max-gradient
    entry line from the portal in ``direction_xy``, evaluated from
    ``lead_in`` to ``length`` (the clearance is 0 at the portal itself by
    construction). Negative means a decline at maximum grade would daylight —
    the portal faces a slope that falls away faster than the decline descends."""
    s = np.arange(lead_in, length + 1e-9, step)
    xy = portal_xy[None, :] + s[:, None] * direction_xy[None, :]
    surface = terrain.sample(xy)
    z_portal = float(terrain.sample(portal_xy[None, :])[0])
    decline = z_portal - max_gradient * s
    return float(np.min(surface - decline))


def default_portal(scenario: Scenario, orebody: Orebody, terrain: Terrain) -> FloatArray:
    """Surface point on the footwall side of the orebody chosen so that a
    max-gradient entry toward the orebody stays buried.

    Candidates are sampled on the footwall side (against the dip direction)
    at distances around ``portal_footwall_distance`` and along-strike offsets;
    the one with the largest ``entry_burial_margin`` wins (ties → closest to
    the nominal distance). A placeholder until the user picks a portal.
    Uses only the generic strike/dip frame (``u``, ``w``, ``center``), so
    layout-v2 (Phase 20A) shares it for every orebody type."""
    fw = np.array([orebody.w[0], orebody.w[1]])
    norm = float(np.linalg.norm(fw))
    fw = np.array([1.0, 0.0]) if norm < 1e-9 else fw / norm
    along = np.array([orebody.u[0], orebody.u[1]])
    nominal = scenario.design.portal_footwall_distance
    half_x = scenario.world.size_x / 2 - 25.0
    half_y = scenario.world.size_y / 2 - 25.0
    c_xy = orebody.center[:2]

    best: tuple[tuple[float, float], FloatArray] | None = None
    for dist in np.arange(0.5 * nominal, 1.5 * nominal + 1e-9, 25.0):
        for off in np.arange(-0.5 * nominal, 0.5 * nominal + 1e-9, 25.0):
            xy = c_xy + dist * fw + off * along
            if abs(xy[0]) > half_x or abs(xy[1]) > half_y:
                continue
            toward = c_xy - xy
            toward = toward / float(np.linalg.norm(toward))
            margin = entry_burial_margin(terrain, xy, toward, scenario.ramp.max_gradient)
            key = (margin, -abs(dist - nominal) - 0.1 * abs(off))
            if best is None or key > best[0]:
                best = (key, xy)
    if best is None:  # degenerate world: nominal point clamped into the world
        xy = np.clip(c_xy + nominal * fw, [-half_x, -half_y], [half_x, half_y])
    else:
        xy = best[1]
    z = float(terrain.sample(xy[None, :])[0])
    return np.array([float(xy[0]), float(xy[1]), z])


def resolve_portal(scenario: Scenario, world: SyntheticWorld) -> tuple[FloatArray, bool]:
    if scenario.portal is not None:
        return np.array(scenario.portal.as_tuple(), dtype=np.float64), False
    ob = world.orebody
    assert isinstance(ob, TabularOrebody)
    return default_portal(scenario, ob, world.terrain), True


def point3d(p: FloatArray) -> Point3D:
    return Point3D(x=float(p[0]), y=float(p[1]), z=float(p[2]))
