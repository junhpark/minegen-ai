"""Conservative construction *service reference* for the layout-v2 ramp
corridor (Phase 20C.4 Gates B/C — "align the reference, not the threshold").

Why this exists
---------------
The main-ramp corridor (rule 170) and the level-development anchor plane
(rules 158 / 178) describe ONE physical spacing system: the level drift sits
``footwall_access_offset`` off the footwall contact and the ramp corridor
``RAMP_CORRIDOR_MARGIN_WIDTHS × tunnel_width`` further out. Before Phase
20C.4 the two were measured from DIFFERENT references — the corridor from
the GLOBAL linear ``FootwallTrack`` edge (a weighted z-fit of the per-level
footprint edges), the anchor from the CERTIFIED clearance level set of the
level plane (the rule 178 offset trace). On irregular bodies the track edge
misses the local footprint by tens of metres, so the intended six-width
separation collapsed to a few metres and the level-access planner failed
typed (Gate A: 24 candidates / 122 levels, nearest approach p50 6.8 m,
binding gates plan separation / rock pillar / connector). The Gate A
counterfactuals showed the corridor is the moving side (anchors moved toward
the ore hit the certified clearance floor).

What it is
----------
A CONSERVATIVE CONSTRUCTION reference, built ONCE per search from the WORLD
clearance policy: for every serviceable level, the interior of the rule 178
offset development trace at the WORLD anchor stand-off (the very trace stage
4 builds for coarse anchors — same cache token ``"WORLD"``). It is not the
candidate's stage-4 field: stage 4 may refine the bound and move the entry
ore-ward, never outward (``RefinedConservativeClearance.signed_clearance =
max(coarse, refined)``), so every candidate anchor lies on or ore-ward of
this reference — the stage-4 dominance invariant, asserted by test.

How a family consumes it
------------------------
A family asks for a ``DeltaProfile`` for ITS corridor: lateral unit ``n``
(away from the ore), along unit ``along``, the along-centre of its footprint
per level and the footprint half-extent — the ramp's OWN along-extent
(SWITCHBACK ``leg/2 + R_min`` about the shared leg centre, SPIRAL the rim
``R`` about the axis; Gate C step 0), never a tolerance. Per level

    support   = max over reference points inside the footprint of p·n
    delta     = max(0, support + margin − (footwall_edge(z)·n + standoff))

and the corridor lateral becomes ``footwall_edge(z)·n + standoff + delta(z)``.
A corridor that serves every elevation continuously (the SPIRAL helix)
takes ``delta`` piecewise-linear in z between required levels and constant
beyond them (``DeltaProfile``); a corridor placed at DISCRETE elevations
(the SWITCHBACK stack, which applies ``delta`` exactly at every near-leg
start) takes the absolute requirement ``support + margin`` of every level
inside one window derived from its stacking mechanics
(``WindowRequirementProfile``, derivation in
``families.switchback_corridor_profile``). Both are never negative — the
corridor is only ever moved OUTWARD, so a placement that already holds the
intent is unchanged. An empty
footprint (no reference point alongside the ramp at that level) yields
delta 0, never a whole-trace fallback. The lateral projection over the
along-window can only over-shoot the perpendicular need on an oblique
backbone, never under-shoot it (C0: 305 L05 25.7 m against a 15.1 m
shortfall at 27.8° obliquity).

When it is inactive (``delta ≡ 0.0`` exactly, bit-identical geometry)
-------------------------------------------------------------------
* TABULAR orebodies: the rule 43 anchor line and the track edge are the
  same analytic plane (Gate B §5 sanity, track residual 0.02–0.39 m).
* an EXPLICIT ``layout.footwallStandoff``: the user's number IS the
  corridor (legacy placement preserved; the reference applies to the derived
  default only).
* a level whose WORLD trace is a typed section failure contributes 0 and is
  reported (``traceFailures``); stage 4 fails that level typed anyway.

LONGITUDINAL is deferred unchanged in Phase 20C.4 (its corridor spans the
whole strike; no LONGITUDINAL candidate appears in the audited failure
populations). Nothing here relaxes a hard constraint: every candidate is
still judged on its delivered polyline by the unchanged gates.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.layout.levels import LevelSections, RequiredLevel
from minegen.layout.sections import SectionGeometryError
from minegen.world.orebody import Orebody, TabularOrebody

FloatArray = npt.NDArray[np.float64]

#: reference inactivity reasons (reported, never silent)
INACTIVE_TABULAR = "TABULAR_ANALYTIC_PATH"
INACTIVE_EXPLICIT_STANDOFF = "EXPLICIT_FOOTWALL_STANDOFF"
INACTIVE_NO_LEVELS = "NO_SERVICEABLE_LEVELS"


class DeltaProfile:
    """``delta(z)``: the outward corridor correction of ONE candidate
    corridor — piecewise-linear between the required levels, constant
    beyond the shallowest / deepest level, never negative. The zero profile
    returns exactly ``0.0`` so an unaffected corridor is bit-identical to
    the pre-reference geometry."""

    __slots__ = ("_d_asc", "_deltas", "_levels", "_z", "_z_asc", "zero")

    def __init__(self, elevations: FloatArray, deltas: FloatArray, level_ids: tuple[str, ...]):
        z = np.asarray(elevations, dtype=np.float64)
        d = np.maximum(np.asarray(deltas, dtype=np.float64), 0.0)
        if z.shape != d.shape:
            raise ValueError("DeltaProfile: elevations and deltas differ in shape")
        order = np.argsort(z)  # np.interp needs ascending abscissae
        self._z_asc = z[order]
        self._d_asc = d[order]
        self._z = z
        self._deltas = d
        self._levels = level_ids
        self.zero = bool(d.size == 0 or not np.any(d > 0.0))

    def __call__(self, z: float) -> float:
        if self.zero:
            return 0.0
        return float(np.interp(float(z), self._z_asc, self._d_asc))

    @property
    def deltas(self) -> FloatArray:
        return self._deltas

    @property
    def max_delta(self) -> float:
        return float(np.max(self._deltas)) if self._deltas.size else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": not self.zero,
            "maxDelta": self.max_delta,
            "deltas": {lid: float(d) for lid, d in zip(self._levels, self._deltas, strict=True)},
        }


class WindowRequirementProfile(DeltaProfile):
    """``delta(z)`` for a corridor whose lateral is FIXED at discrete
    elevations but serves a vertical span — the SWITCHBACK stack (Phase
    20C.4 follow-up; the derivation lives in
    ``families.switchback_corridor_profile``). Per level ``i`` the ABSOLUTE
    corridor requirement is ``Q_i = support_i + margin`` (``None`` where the
    footprint holds no reference point). A placement at elevation ``z``
    must honour every level plane inside ONE window
    ``[z − below, z + above]``::

        W(z)      = max{ Q_i : z_i ∈ [z − below, z + above] }   (empty → none)
        delta(z)  = max(0, W(z) − base(z))

    with ``base(z) = footwall_edge(z)·n + standoff`` evaluated at the
    placement elevation itself — no second band and no edge band-min. The
    corridor lateral ``base + delta`` is therefore ``max(base(z), W(z))``:
    the requirement is locally constant over the window width, the base is
    the track's linear edge. The profile may jump where a level enters or
    leaves the window (the stack reads it at discrete elevations only); it
    is never negative and the exact zero profile is returned when no level
    carries a requirement."""

    __slots__ = ("_above", "_base_fn", "_below", "_req", "extras")

    def __init__(
        self,
        elevations: FloatArray,
        level_ids: tuple[str, ...],
        requirements: list[float | None],
        base_fn: Callable[[float], float],
        below: float,
        above: float,
    ):
        z = np.asarray(elevations, dtype=np.float64)
        if len(requirements) != z.shape[0]:
            raise ValueError("WindowRequirementProfile: one requirement per level is required")
        super().__init__(z, np.zeros(z.shape[0], dtype=np.float64), level_ids)
        self._req = np.asarray(
            [np.nan if q is None else float(q) for q in requirements], dtype=np.float64
        )
        self._base_fn = base_fn
        self._below = max(0.0, float(below))
        self._above = max(0.0, float(above))
        #: consumer-declared inspectable parameters (reported in ``to_dict``)
        self.extras: dict[str, Any] = {}
        has_req = bool(np.isfinite(self._req).any())
        # exact zero only when NO level carries a requirement: a window
        # profile can be positive between planes even when it is 0 on them
        self.zero = not has_req
        if has_req:
            self._deltas = np.asarray([self._window_delta(float(zi)) for zi in z], dtype=np.float64)
            self._d_asc = self._deltas[np.argsort(z)]

    def _window_delta(self, z: float) -> float:
        inside = (self._z >= z - self._below) & (self._z <= z + self._above)
        inside &= np.isfinite(self._req)
        if not bool(inside.any()):
            return 0.0
        return max(0.0, float(np.max(self._req[inside])) - float(self._base_fn(z)))

    def __call__(self, z: float) -> float:
        if self.zero:
            return 0.0
        return self._window_delta(float(z))

    @property
    def window(self) -> tuple[float, float]:
        return self._below, self._above

    def to_dict(self) -> dict[str, Any]:
        out = super().to_dict()
        out["windowBelowM"] = self._below
        out["windowAboveM"] = self._above
        out["requirements"] = {
            lid: (None if not np.isfinite(q) else float(q))
            for lid, q in zip(self._levels, self._req, strict=True)
        }
        out.update(self.extras)
        return out


ZERO_PROFILE = DeltaProfile(np.zeros(0), np.zeros(0), ())


@dataclass(frozen=True)
class ServiceReference:
    """Per-search construction reference (see module docstring)."""

    elevations: FloatArray  # (L,) serviceable levels, descending
    level_ids: tuple[str, ...]
    #: (K_i, 2) INTERIOR plan points of the WORLD-policy offset trace per
    #: level (end margins excluded exactly as the anchor admissible range
    #: excludes them); ``None`` when the level's trace is a typed failure
    backbones: tuple[FloatArray | None, ...]
    standoff: float  # effective corridor stand-off (rule 170)
    standoff_source: str  # EXPLICIT | DEFAULT_OFFSET_PLUS_CORRIDOR_MARGIN
    margin: float  # RAMP_CORRIDOR_MARGIN_WIDTHS × tunnel_width
    active: bool
    inactive_reason: str | None
    basis: str  # WORLD clearance-policy basis the traces were built under
    anchor_standoff: float  # WORLD anchor stand-off of the traces
    end_margin: float
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def level_deltas(
        self,
        n: FloatArray,
        along: FloatArray,
        centres: FloatArray,
        half: float,
        base_lateral: FloatArray,
    ) -> tuple[FloatArray, list[dict[str, Any]]]:
        """Per-level outward correction for a corridor with lateral unit
        ``n`` (away from the ore), along unit ``along``, footprint centre
        ``centres[i]`` (along-coordinate) and half-extent ``half``;
        ``base_lateral[i]`` is the corridor's current ore-facing lateral
        ``footwall_edge(z_i)·n + standoff``. Returns the deltas (≥ 0) and
        one inspectable record per level."""
        count = self.elevations.shape[0]
        centres = np.asarray(centres, dtype=np.float64)
        base_lateral = np.asarray(base_lateral, dtype=np.float64)
        if centres.shape != (count,) or base_lateral.shape != (count,):
            raise ValueError("level_deltas: centres / base_lateral must have one entry per level")
        deltas = np.zeros(count, dtype=np.float64)
        records: list[dict[str, Any]] = []
        n2 = np.asarray(n, dtype=np.float64)[:2]
        a2 = np.asarray(along, dtype=np.float64)[:2]
        for i in range(count):
            rec: dict[str, Any] = {
                "levelId": self.level_ids[i],
                "elevation": float(self.elevations[i]),
                "baseLateral": float(base_lateral[i]),
                "footprintCentre": float(centres[i]),
                "footprintHalf": float(half),
                "pointsInFootprint": 0,
                "support": None,
                "delta": 0.0,
            }
            bb = self.backbones[i]
            if self.active and bb is not None and bb.shape[0]:
                win = np.abs(bb @ a2 - centres[i]) <= half
                if bool(win.any()):
                    support = float(np.max(bb[win] @ n2))
                    deltas[i] = max(0.0, support + self.margin - float(base_lateral[i]))
                    rec["pointsInFootprint"] = int(win.sum())
                    rec["support"] = support
                    rec["delta"] = float(deltas[i])
            records.append(rec)
        return deltas, records

    def profile(
        self,
        n: FloatArray,
        along: FloatArray,
        centres: FloatArray,
        half: float,
        base_lateral: FloatArray,
    ) -> tuple[DeltaProfile, list[dict[str, Any]]]:
        if not self.active:
            return ZERO_PROFILE, []
        deltas, records = self.level_deltas(n, along, centres, half, base_lateral)
        return DeltaProfile(self.elevations, deltas, self.level_ids), records

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "inactiveReason": self.inactive_reason,
            "basis": self.basis,
            "corridorStandoff": self.standoff,
            "corridorStandoffSource": self.standoff_source,
            "corridorMargin": self.margin,
            "anchorStandoff": self.anchor_standoff,
            "endMargin": self.end_margin,
            "levels": [
                {
                    "levelId": lid,
                    "elevation": float(z),
                    "backbonePoints": int(bb.shape[0]) if bb is not None else 0,
                }
                for lid, z, bb in zip(self.level_ids, self.elevations, self.backbones, strict=True)
            ],
            **self.diagnostics,
        }


def build_service_reference(
    sections: LevelSections,
    levels: list[RequiredLevel],
    w_h: FloatArray,
    *,
    orebody: Orebody,
    clearance: Callable[[FloatArray], FloatArray],
    basis: str,
    standoff: float,
    standoff_source: str,
    margin: float,
    anchor_standoff: float,
    min_trace_length: float,
    end_margin: float,
    required_clearance: float,
) -> ServiceReference:
    """Build the construction reference from the WORLD-policy offset traces
    of the serviceable ``levels`` (token ``"WORLD"`` — the cached trace stage
    4 uses for coarse anchors, so no second clearance field exists)."""
    t0 = time.perf_counter()
    elevations = np.asarray([lv.elevation for lv in levels], dtype=np.float64)
    ids = tuple(lv.level_id for lv in levels)
    inactive: str | None = None
    if isinstance(orebody, TabularOrebody):
        inactive = INACTIVE_TABULAR
    elif standoff_source == "EXPLICIT":
        inactive = INACTIVE_EXPLICIT_STANDOFF
    elif not levels:
        inactive = INACTIVE_NO_LEVELS
    backbones: list[FloatArray | None] = [None] * len(levels)
    failures: dict[str, dict[str, Any]] = {}
    if inactive is None:
        for i, lv in enumerate(levels):
            try:
                off = sections.offset_trace(
                    lv,
                    w_h,
                    float(anchor_standoff),
                    float(min_trace_length),
                    clearance,
                    "WORLD",
                    float(required_clearance),
                )
            except SectionGeometryError as err:
                failures[lv.level_id] = {"code": err.code, "detail": err.detail}
                continue
            total = float(off.total_length)
            m = min(float(end_margin), 0.25 * total)
            ch = np.asarray(off.chainage, dtype=np.float64)
            interior = (ch >= m - 1e-9) & (ch <= total - m + 1e-9)
            pts = np.asarray(off.points, dtype=np.float64)[interior, :2]
            backbones[i] = np.ascontiguousarray(pts)
    diagnostics: dict[str, Any] = {
        "traceFailures": failures,
        "buildSeconds": time.perf_counter() - t0,
    }
    return ServiceReference(
        elevations=elevations,
        level_ids=ids,
        backbones=tuple(backbones),
        standoff=float(standoff),
        standoff_source=standoff_source,
        margin=float(margin),
        active=inactive is None,
        inactive_reason=inactive,
        basis=basis,
        anchor_standoff=float(anchor_standoff),
        end_margin=float(end_margin),
        diagnostics=diagnostics,
    )
