"""Typed junctions — the minimum union of connected excavations (Phase 20D.1).

MineGen's development topology declares exactly three kinds of junction,
each welded at ≤ 1e-6 m by the artifacts the mesh builders already consume
(and re-validated by the network builder, which mints the node ids below):

    RAMP_ACCESS     RAMP → LEVEL_ACCESS   at the RAMP_JUNCTION (a shared
                    boundary ring of the ramp chain; the access's first point)
    ACCESS_DRIFT    LEVEL_ACCESS → DRIFT  at the LEVEL_ENTRY (a DRIFT piece
                    breakpoint; the access's last point)
    DRIFT_CROSSCUT  DRIFT → CROSSCUT      at the station (a DRIFT piece
                    breakpoint; the crosscut's first point)

Before this phase every tube was swept independently, so the PARENT's wall
quads ran straight through the CHILD's mouth and the child's open end sat
inside the parent as a visible inner shell. The union here is deliberately
typed and local — no general boolean, no BSP, no voxel remesh:

* a junction is identified from the declared topology (never from mesh
  proximity);
* inside a window of ``JUNCTION_WINDOW_WIDTHS × tunnel width`` along each
  centerline from the junction point, whole quads (ring interval × profile
  edge) are OMITTED from the RENDER mesh:
    - child quads — floor, walls and roof alike (hardening PR-5, rule 227 b)
      — judged at the parent's EXACT surface (``CHILD_JUDGE_LEVEL``, a
      numerical tie-break toward inside so a coincident child surface such
      as a tangent turnout's first ring or a T-junction's crown is omitted
      deterministically) against the parent with its floor lowered by
      ``CHILD_JUDGE_FLOOR_DROP_WIDTHS`` widths (a child surface under the
      parent floor between its walls is hidden under a floor that is never
      cut): INSIDE omitted, OUTSIDE emitted unchanged, STRADDLING clipped —
      only the inside portion is removed and the outside remainder is
      emitted in its place (Phase 20D.1.2 typed local boundary clipping,
      hardening PR-2 for walls / roof). The child profile floor is ONE edge
      spanning the whole tunnel width, so at a shallow turnout a floor quad
      reaches from inside the parent to outside it; the whole-quad rule kept
      every such quad and left a false floating floor slab across the parent
      (measured 0.7–1.6 m above the descending ramp floor at its far edge),
      while deleting the whole quad would open a hole in the legitimate
      child floor outside the parent. The boundary is located by
      deterministic bisection on the quad's own edges; the remainder polygon
      (convex: a quad cut by one chord, or two corner triangles) is cleaned
      at render scale and fan-triangulated into new render vertices. Before
      PR-5 the child was cut at ``+tol``: its remainder began tol OUTSIDE
      the parent wall while the parent's rim ended tol INSIDE the child
      wall, a tol-wide slit along every seam, and
    - parent NON-FLOOR quads are judged EXACTLY against the child
      (hardening PR-5, replacing the Phase 20D.1.1 whole-quad area rule):
      a quad inside-or-on the child's judging surface is omitted, a quad
      outside it is kept, a STRADDLING quad is clipped at that surface by
      the same bilinear chord clip the child floor receives and only its
      outside remainder is emitted. The judging surface is the child
      envelope's ``−tol`` level (a parent point counts as blocked only when
      it is inside the child by MORE than the tolerance, so a parent roof
      or wall coincident with the child's — the tangential start of a
      turnout, the roof of a T-junction — stays with the parent while the
      child's coincident quads are removed as "on"), with the child's FLOOR
      edge lowered by ``PARENT_JUDGE_FLOOR_DROP_TOLERANCES × tol`` so the
      band never leaves a curb of parent wall across a flush doorway. The
      whole-quad rule (≥ 6 of 9 surface samples) kept every quad the child
      covered less than two thirds and removed every quad it covered more:
      measured on the TABULAR fixture (``tests/test_junction_seam.py``) 80
      parent triangles stood inside the mouth by up to 0.37 m (wedges) and
      175 of 75,008 eye rays left the union through the rim (holes). The
      parent FLOOR edge is never a parent-side cut: it is the doorway's
      supporting floor. The same judgement cuts a drift's end caps and the
      ramp's PORTAL / TERMINAL caps (``cut_cap``, every cap within
      ``PARENT_EXTENSION_MAX_WIDTHS`` of a junction);
    - the floor seam is closed by SILLS that are RISERS (``_with_sills``):
      the strip between a floor clip chord — which lies ON the parent's wall
      or terminal plane — and the parent wall's riser top, measured every
      half tolerance along the chord from the parent floor boundary (side
      edges and the floor's end edges) and emitted per contiguous run of
      stations with a riser of at least render resolution, oriented into the
      rock by the step direction; every clip remainder, cap clip and sill is
      cleaned at render scale (``_clean_render_loop``: 1 mm merge,
      degenerate fans, 1e-6 m² floor) because a float32-degenerate sliver
      covers no surface;
* rings are refined to ``JUNCTION_RING_SPACING_FRACTION × width`` inside the
  window so the aperture rim is resolved at a fraction of the tunnel width
  (every refinement ring still lies ON the validated polyline, rule 65).

Containment is a per-point query against a swept tube: nearest ring
interval within the window, gravity-aligned local coordinates
(``design.profile.gravity_frames``, the same frame the sweep uses) and the
signed distance to the convex profile polygon. It is a cross-section
support at the nearest ring, never claimed as an exact swept-surface
distance; the rim it produces is jagged at the refined ring spacing and the
straddling quads it keeps overlap the neighbour by at most one quad. The
logical (engineering) mesh, its volume / watertightness QA and the
centerlines are untouched: the union is a visualization / traversal cut of
the derived mesh, reported per junction and never persisted as geometry.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal

import numpy as np
import numpy.typing as npt

from minegen.design.profile import (
    ProfileShape,
    boundary_points,
    floor_edge_index,
    gravity_frames,
    wall_edge_indices,
)
from minegen.network.node_ids import (
    drift_station_junction_id,
    level_entry_id,
    ramp_junction_id,
)

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]

JunctionType = Literal["RAMP_ACCESS", "ACCESS_DRIFT", "DRIFT_CROSSCUT"]
JUNCTION_TYPES: tuple[JunctionType, ...] = ("RAMP_ACCESS", "ACCESS_DRIFT", "DRIFT_CROSSCUT")

#: Locality of the union, in tunnel WIDTHS along each centerline from the
#: junction point: no quad outside this window is ever touched, whatever the
#: geometry. Two widths cover a level access leaving a ramp tangentially
#: (its inner wall clears the ramp wall within ~R·acos(1 − w/R) ≈ 1.6 w for
#: R = 18 m, w = 5 m) with margin; a perpendicular T-junction needs ~0.6 w.
JUNCTION_WINDOW_WIDTHS = 2.0
#: Ring spacing inside the window as a fraction of the tunnel width: the
#: aperture rim is resolved at this scale (0.1 × 5 m = 0.5 m for the default
#: tunnel). Refinement rings are linear subdivisions of the validated
#: polyline (rule 65), so geometry is never moved.
JUNCTION_RING_SPACING_FRACTION = 0.1
#: The ONE surface tolerance of the union, as a fraction of the tunnel
#: width. Since hardening PR-5 it is the PARENT's lip: a parent surface is
#: cut only where it is inside the child's judging envelope by MORE than
#: this band (``−tol`` level), so a parent surface coincident with the
#: child's stays with the parent and every jamb keeps a one-tolerance lip
#: into the child void; the child is cut at the parent's exact surface
#: (``CHILD_JUDGE_LEVEL``). It also sizes the clip band (``_edges_stay``)
#: and the sill sampling. 0.02 × 5 m = 0.1 m absorbs the secondary
#: profile's coarser tessellation (≤ 1 % inscribed bias) and the gradient /
#: frame differences of two tangent tubes.
JUNCTION_SURFACE_TOLERANCE_FRACTION = 0.02
#: Hardening PR-2 (H0 §3.4 seam), PR-5: the sill strip that bridges a clipped
#: child floor's boundary chord (which lies ON the parent's wall or terminal
#: plane at the child floor elevation) to the parent's riser top is built
#: only where the chord is a floor seam: it lies within this many tunnel
#: widths of a parent floor BOUNDARY in plan (a side edge at the wall base,
#: or the floor's end edge on a terminal plane). The riser top is the top of
#: the parent wall that still stands under the chord after the exact parent
#: clip, found on the same judging surface the parent clip uses; where the
#: wall is cut to the floor it is the parent floor edge, where the wall
#: stands to the chord height (the jamb lip) there is nothing to bridge. A
#: chord farther from every floor boundary is not a floor seam of this kind
#: and is counted, never bridged by invented geometry.
SILL_MAX_PLAN_DISTANCE_WIDTHS = 0.1
#: Hardening PR-5 parent-side judging surface. The parent is clipped at the
#: child envelope's ``−tol`` level, so coincident surfaces (|sd| ≤ tol) stay
#: with the parent; a wall band within ``tol`` ABOVE the child floor is
#: coincident with nothing, yet it would survive that level as a curb across
#: every flush doorway (the band is measured to the child's floor plane).
#: The child's FLOOR edge is therefore lowered by this many tolerances for
#: the parent judgement only — a judging envelope, never emitted geometry —
#: so the parent wall is opened down to its own floor edge (which is never
#: cut) and the floor seam is closed by the sill. 2 × tol = 0.2 m for the
#: default 5 m tunnel: the band plus one tolerance of margin.
PARENT_JUDGE_FLOOR_DROP_TOLERANCES = 2.0
#: Hardening PR-5 child-side judging level: the CHILD is cut at the
#: parent's EXACT surface (signed distance 0) with this numerical
#: tie-break (m) toward INSIDE, so a child surface coincident with the
#: parent's (the first ring of a tangent turnout on a straight parent, a
#: crosscut crown under the drift crown) is omitted deterministically
#: while every transversal crossing is cut where the child really leaves
#: the parent; the parent keeps its coincident surface (it is judged at
#: ``−tol``). Before PR-5 the child was cut at ``+tol``: its remainder
#: began tol OUTSIDE the parent wall while the parent's rim ended tol
#: INSIDE the child wall, so a tol-wide slit ran along every seam (a
#: ray hugging the child wall slipped behind the step into rock). One
#: tenth of ``CLIP_VERTEX_MERGE_DISTANCE``: a crossing next to a vertex that
#: sits ON the parent surface lands within this distance of it and is
#: merged into it, never emitted as a float32-degenerate sliver.
CHILD_JUDGE_LEVEL = 1e-7
#: The child is judged against the parent with its FLOOR lowered by this
#: many tunnel widths (a judging envelope, never emitted geometry): a
#: child surface under the parent floor between the parent's walls is
#: hidden under a floor that is never cut, so it is omitted; the child
#: floor's clip chord then lies on the parent's wall plane whatever the
#: rule-188 floor mismatch, and the sill is the riser between the two
#: floors (up into the child, or down from the parent floor edge). One
#: width is far beyond the measured mismatch (≤ 0.3 m) and never reaches
#: outside the junction window: the pass stops at the first floor quad
#: beyond the parent's walls.
CHILD_JUDGE_FLOOR_DROP_WIDTHS = 1.0
#: Phase 20D.1.2 child-floor clipping: bisection steps that locate the
#: parent tolerance boundary on a straddling floor quad's edge (2^-40 of the
#: edge length — sub-nanometre for a 5 m floor edge, deterministic).
CLIP_BISECTION_ITERATIONS = 40
#: Two polygon vertices closer than this (m) are one vertex: a boundary
#: crossing that lands on a corner never produces a zero-area triangle.
CLIP_VERTEX_MERGE_DISTANCE = 1e-6
#: A straddling floor quad is bisected along its longer side (deterministic,
#: at most this many times) whenever a straight chord between two boundary
#: crossings would intrude into the parent beyond the tolerance — the
#: boundary bends inside the quad where the parent's wall meets its terminal
#: plane (a ramp ending shortly after its last turnout). Ten bisections take
#: a 5 m × 0.5 m floor quad below 0.1 m on both sides.
CLIP_MAX_SUBDIVISION_DEPTH = 10
#: interior samples per loop edge for the chord-fidelity check
CLIP_CHORD_SAMPLES = 3


@dataclass(frozen=True)
class Junction:
    """One declared junction: the parent tube the child joins, the shared
    point, and which END of the child sits on the parent."""

    type: JunctionType
    node_id: str
    parent_id: str
    child_id: str
    point: FloatArray  # (3,) the welded junction point
    child_end: Literal["start", "end"]
    level_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "nodeId": self.node_id,
            "parentId": self.parent_id,
            "childId": self.child_id,
            "levelId": self.level_id,
            "point": [float(v) for v in self.point],
            "childEnd": self.child_end,
        }


RAMP_TUBE_ID = "RAMP"


def _pts(flat: list[float]) -> FloatArray:
    return np.asarray(flat, dtype=np.float64).reshape(-1, 3)


def find_junctions(
    ramp_payload: dict[str, Any] | None,
    accesses_payload: dict[str, Any] | None,
    levels_payload: dict[str, Any] | None,
) -> list[Junction]:
    """The declared junctions of the given artifacts, in a deterministic
    order (RAMP_ACCESS by access order, ACCESS_DRIFT by access order,
    DRIFT_CROSSCUT by development order). Only SUCCESS artifacts and OK
    accesses declare junctions; a child whose parent is absent (an access
    without the ramp payload, a crosscut without a drift) declares none —
    the union never guesses a parent."""
    out: list[Junction] = []
    ramp_ok = ramp_payload is not None and ramp_payload.get("status") == "SUCCESS"
    accesses_ok = accesses_payload is not None and accesses_payload.get("status") == "SUCCESS"
    levels_ok = levels_payload is not None and levels_payload.get("status") == "SUCCESS"
    drift_levels: set[str] = set()
    if levels_ok:
        assert levels_payload is not None
        drift_levels = {
            str(d["levelId"])
            for d in levels_payload.get("developments", [])
            if d.get("kind") == "DRIFT"
        }
    if accesses_ok:
        assert accesses_payload is not None
        for a in accesses_payload.get("accesses", []):
            if a.get("status") != "OK" or not a.get("centerline"):
                continue
            level_id = str(a["levelId"])
            child_id = f"LEVEL_ACCESS:{level_id}"
            pts = _pts(a["centerline"]["points"])
            if ramp_ok and a.get("rampJunction") is not None:
                out.append(
                    Junction(
                        type="RAMP_ACCESS",
                        node_id=ramp_junction_id(level_id),
                        parent_id=RAMP_TUBE_ID,
                        child_id=child_id,
                        point=pts[0].copy(),
                        child_end="start",
                        level_id=level_id,
                    )
                )
            if level_id in drift_levels:
                out.append(
                    Junction(
                        type="ACCESS_DRIFT",
                        node_id=level_entry_id(level_id),
                        parent_id=f"DRIFT:{level_id}",
                        child_id=child_id,
                        point=pts[-1].copy(),
                        child_end="end",
                        level_id=level_id,
                    )
                )
    if levels_ok:
        assert levels_payload is not None
        for d in levels_payload.get("developments", []):
            if d.get("kind") != "CROSSCUT":
                continue
            level_id = str(d["levelId"])
            if level_id not in drift_levels or d.get("stationIndex") is None:
                continue
            pts = _pts(d["centerline"]["points"])
            out.append(
                Junction(
                    type="DRIFT_CROSSCUT",
                    node_id=drift_station_junction_id(level_id, int(d["stationIndex"])),
                    parent_id=f"DRIFT:{level_id}",
                    child_id=str(d["id"]),
                    point=pts[0].copy(),
                    child_end="start",
                    level_id=level_id,
                )
            )
    return out


# --------------------------------------------------------------------------- #
# swept-tube containment
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TubeEnvelope:
    """A swept tube for containment queries: ring centers + unit tangents on
    the centerline and the profile polygon in the gravity-aligned frame."""

    centers: FloatArray  # (R, 3)
    tangents: FloatArray  # (R, 3) unit
    chainage: FloatArray  # (R,)
    shape: ProfileShape
    #: outward unit normals + offsets of the convex CCW profile edges
    edge_normals: FloatArray = field(repr=False)  # (K, 2)
    edge_offsets: FloatArray = field(repr=False)  # (K,)
    #: hardening PR-5 round 2 — which REAL ends (ring 0, the last ring) are
    #: judged as CAPPED planes (a continuous field, see ``signed_distance``
    #: and ``with_end_planes``); the default declares neither, the
    #: +inf-beyond-the-span semantics every measurement instrument uses
    end_planes: tuple[bool, bool] = (False, False)

    @classmethod
    def build(cls, centers: FloatArray, tangents: FloatArray, shape: ProfileShape) -> TubeEnvelope:
        c = np.asarray(centers, dtype=np.float64)
        t = np.asarray(tangents, dtype=np.float64)
        t = t / np.linalg.norm(t, axis=1, keepdims=True)
        steps = np.linalg.norm(np.diff(c, axis=0), axis=1)
        chainage = np.concatenate([[0.0], np.cumsum(steps)])
        pts = shape.points
        nxt = np.roll(pts, -1, axis=0)
        edges = nxt - pts
        # CCW polygon: the outward normal of edge (p → q) is (dy, −dx)
        normals = np.stack([edges[:, 1], -edges[:, 0]], axis=1)
        normals = normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
        offsets = np.einsum("ij,ij->i", normals, pts)
        return cls(c, t, chainage, shape, normals, offsets)

    def floor_lowered(self, drop: float) -> TubeEnvelope:
        """The same tube with its FLOOR half-plane moved ``drop`` m down (the
        walls extend down to meet it): the PARENT-side judging envelope of
        hardening PR-5 (``PARENT_JUDGE_FLOOR_DROP_TOLERANCES``). Only the
        floor edge's offset changes — the profile, rings and every other
        half-plane are untouched, and nothing is ever emitted from it."""
        fe = floor_edge_index(self.shape)
        offsets = self.edge_offsets.copy()
        # the floor edge's outward normal is (0, −1): inside ⇔ y ≥ −offset
        offsets[fe] += float(drop)
        return replace(self, edge_offsets=offsets)

    def with_end_planes(self, start: bool, end: bool) -> TubeEnvelope:
        """The same tube judged with its REAL start / end (ring 0 / the last
        ring) treated as a CAPPED PLANE (hardening PR-5 round 2): the end
        plane's half-space joins the profile's half-planes in
        ``signed_distance``, so the field is continuous across it — 0 ON the
        plane — instead of jumping from a finite inside value to +inf. A
        judging envelope declares the ends that are surfaces of the solid it
        stands for: the PARENT's two ends on the child side (a drift's end
        cap, the ramp's portal / terminal cap, an access's open end — where
        the parent void stops and the child beyond it is kept) and the
        CHILD's far end on the parent side — never the child's OPEN junction
        end, where the parent's own void continues and the −tol lip rule
        would leave a fin of parent cap standing in the mouth. Measured on
        the default scenario (13 levels, 221 crosscut stations): a crosscut
        whose floor centre line lies IN the drift's end plane (an L-junction —
        the drift ends AT the station) read that plane at floating-point whim
        and its floor quad never converged (JUNCTION_CLIP_TOPOLOGY after 10
        subdivisions); the TABULAR verification fixture's 8 extremity stations
        happened to read one side."""
        return replace(self, end_planes=(bool(start), bool(end)))

    def ring_window(self, point: FloatArray, radius: float) -> tuple[int, int]:
        """Ring index range ``[lo, hi)`` whose centers lie within ``radius``
        of ``point`` along the chainage of the nearest ring (a contiguous
        window on the centerline, never a proximity search of the mesh)."""
        d = np.linalg.norm(self.centers - point[None, :], axis=1)
        nearest = int(np.argmin(d))
        s0 = self.chainage[nearest]
        lo = int(np.searchsorted(self.chainage, s0 - radius, side="left"))
        hi = int(np.searchsorted(self.chainage, s0 + radius, side="right"))
        return max(lo, 0), min(hi, int(self.centers.shape[0]))

    def signed_distance(self, points: FloatArray, window: tuple[int, int]) -> FloatArray:
        """Signed distance of ``points`` (N, 3) to the tube envelope, using
        the nearest ring INTERVAL among rings ``window`` (negative inside).
        Points that project beyond the windowed centerline span are reported
        as outside (+inf): the tube does not extend past its rings — except
        past a REAL end declared CAPPED (``end_planes``), where the end plane
        is a surface of the solid and the distance stays continuous."""
        lo, hi = window
        n = int(points.shape[0])
        if hi - lo < 2 or n == 0:
            return np.full(n, np.inf)
        a = self.centers[lo : hi - 1]  # (M, 3) interval starts
        b = self.centers[lo + 1 : hi]  # (M, 3) interval ends
        ab = b - a
        ab_len2 = np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-18)
        # projection parameter of every point on every interval chord
        ap = points[:, None, :] - a[None, :, :]  # (N, M, 3)
        t = np.einsum("nmj,mj->nm", ap, ab) / ab_len2[None, :]
        t_clamped = np.clip(t, 0.0, 1.0)
        foot = a[None, :, :] + t_clamped[:, :, None] * ab[None, :, :]
        dist2 = np.einsum("nmj,nmj->nm", points[:, None, :] - foot, points[:, None, :] - foot)
        m = np.argmin(dist2, axis=1)  # nearest interval per point
        rows = np.arange(n)
        tt = t[rows, m]
        last = a.shape[0] - 1
        # hardening PR-5 round 2: a REAL end declared CAPPED is judged as a
        # plane of the solid (below); beyond an UNCAPPED span end — a window
        # edge the tube continues past, or an OPEN end — the point is
        # unjudged and reported outside
        cap_start = bool(self.end_planes[0]) and lo == 0
        cap_end = bool(self.end_planes[1]) and hi == int(self.centers.shape[0])
        beyond = ((m == 0) & (tt < 0.0) & (not cap_start)) | (
            (m == last) & (tt > 1.0) & (not cap_end)
        )
        tt = np.clip(tt, 0.0, 1.0)
        center = a[m] + tt[:, None] * ab[m]
        tan = self.tangents[lo + m] * (1.0 - tt)[:, None] + self.tangents[lo + m + 1] * tt[:, None]
        tan = tan / np.maximum(np.linalg.norm(tan, axis=1, keepdims=True), 1e-12)
        right, up = gravity_frames(tan)
        rel = points - center
        x = np.einsum("ij,ij->i", rel, right)
        y = np.einsum("ij,ij->i", rel, up)
        local = np.stack([x, y], axis=1)  # (N, 2)
        # convex polygon: signed distance = max over edges of the half-plane
        # distance (exact outside near an edge, exact inside everywhere)
        d = local @ self.edge_normals.T - self.edge_offsets[None, :]  # (N, K)
        sd = d.max(axis=1)
        # a capped end plane is one more half-plane of the convex solid: the
        # signed distance to the plane (outward normal = −tangent at the
        # start, +tangent at the end) joins the max — continuous, 0 on it
        if cap_start:
            sd = np.maximum(sd, -np.einsum("ij,j->i", points - self.centers[0], self.tangents[0]))
        if cap_end:
            sd = np.maximum(sd, np.einsum("ij,j->i", points - self.centers[-1], self.tangents[-1]))
        sd[beyond] = np.inf
        return sd


# --------------------------------------------------------------------------- #
# quad masks
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FloorClip:
    """Phase 20D.1.2: ONE child floor quad (ring interval × floor edge) that
    straddles the parent envelope boundary, with the OUTSIDE-parent remainder
    the render builder emits in place of the quad's two original triangles.
    ``polygons`` are world-space vertex loops in the quad's own orientation
    order (each convex, fan-triangulated from its first vertex); ``params``
    are their bilinear quad coordinates (s along the ring interval, u along
    the floor edge from profile vertex j to j+1) so UV / chainage attribution
    stays exact. Normally one polygon; the diagonal corner case yields two
    corner triangles. Render-only: the logical mesh is untouched."""

    interval: int
    edge: int
    polygons: tuple[FloatArray, ...]
    params: tuple[FloatArray, ...]
    #: outside-parent flags of the four corners in perimeter order
    corners_outside: tuple[bool, bool, bool, bool]
    junction_node_id: str
    #: the remainder's boundary CHORDS (pairs of crossing points on the
    #: parent's tolerance surface), in loop order — the seam the sills close
    chords: tuple[FloatArray, ...] = ()
    chord_params: tuple[FloatArray, ...] = ()
    #: hardening PR-2 (H0 §3.4): sill strips bridging each chord to the parent
    #: FLOOR edge (world loops + bilinear params copied from the chord ends);
    #: empty for a non-floor clip or a chord away from the parent floor
    sills: tuple[FloatArray, ...] = ()
    sill_params: tuple[FloatArray, ...] = ()
    #: index into ``chords`` of the chord each sill bridges (same order as
    #: ``sills``), so a seam audit can pair every sill with its chord
    sill_chords: tuple[int, ...] = ()
    #: chords of a floor clip that got NO sill because they are not a floor
    #: seam of the documented kind (not adjacent to the parent floor edge, or
    #: the parent wall below them still stands) — counted, never invented
    chords_without_sill: int = 0
    #: True when this clip is a FLOOR quad (the Phase 20D.1.2 case); False
    #: for a straddling WALL / ROOF quad clipped the same way (PR-2)
    floor: bool = True

    @property
    def replacement_triangles(self) -> int:
        return int(
            sum(max(int(p.shape[0]) - 2, 0) for p in self.polygons)
            + sum(max(int(p.shape[0]) - 2, 0) for p in self.sills)
        )

    @property
    def sill_triangles(self) -> int:
        return int(sum(max(int(p.shape[0]) - 2, 0) for p in self.sills))


@dataclass
class JunctionCut:
    """Quads (ring interval × profile edge) omitted from ONE tube's render
    mesh for one junction, with the reason recorded for the report, plus
    (CHILD side, Phase 20D.1.2) the straddling floor quads that are clipped
    rather than omitted."""

    junction: Junction
    side: Literal["PARENT", "CHILD"]
    mask: BoolArray  # (R-1, K) True = omit
    window_rings: tuple[int, int]
    #: this tube's floor edge and two vertical wall edges (profile geometry)
    floor_edge: int = -1
    wall_edges: tuple[int, int] = (-1, -1)
    #: CHILD floor quads clipped at the parent boundary (never masked)
    floor_clips: list[FloorClip] = field(default_factory=list)
    #: hardening PR-2 (H0 §3.4): CHILD wall / roof quads straddling the parent
    #: boundary, clipped the same way (their inside-parent part used to stand
    #: inside the parent as a fragment up to one quad long)
    wall_clips: list[FloorClip] = field(default_factory=list)
    #: straddling wall / roof quads whose boundary could not be represented
    #: by chords within the subdivision budget: kept WHOLE (the pre-PR-2
    #: behaviour) and counted — never a silent approximation, never a failure
    #: of the whole mesh for a render-only fragment
    unclipped_wall_quads: int = 0
    #: hardening PR-4 (W1b): the ring-interval range the PARENT side actually
    #: examined — the ``window_rings`` plus the contiguous extension past the
    #: window on each side while an interval still lost a quad
    #: (``_extend_parent_pass``); equals ``window_rings`` when nothing was
    #: cut at the window edge. CHILD cuts keep ``None``.
    extended_rings: tuple[int, int] | None = None
    #: chainage span [min, max] along THIS tube's centerline of every interval
    #: that lost or clipped a quad (``None`` when nothing was cut): the
    #: doorway's footprint on the parent, consumed by the temporal aperture
    #: barrier
    cut_chainage: tuple[float, float] | None = None
    #: hardening PR-5 (PARENT side): the judging envelope, surface level and
    #: tolerance this cut clipped against, so a second junction touching the
    #: same parent quad can re-clip the remainder (``merge_parent_cut``)
    judge_envelope: TubeEnvelope | None = None
    judge_level: float | None = None
    judge_tolerance: float | None = None

    @property
    def extension_intervals(self) -> int:
        """Ring intervals cut OUTSIDE the nominal window (parent side)."""
        if self.extended_rings is None:
            return 0
        lo, hi = self.window_rings
        elo, ehi = self.extended_rings
        return int(max(lo - elo, 0) + max(ehi - hi, 0))

    @property
    def clips(self) -> list[FloorClip]:
        """Every clipped quad of this cut (floor + wall), for the render."""
        return [*self.floor_clips, *self.wall_clips]

    @property
    def removed_quads(self) -> int:
        return int(self.mask.sum())

    @property
    def clipped_floor_quads(self) -> int:
        return len(self.floor_clips)

    @property
    def clipped_wall_quads(self) -> int:
        return len(self.wall_clips)

    @property
    def replacement_triangles(self) -> int:
        return int(sum(c.replacement_triangles for c in self.clips))

    @property
    def sill_triangles(self) -> int:
        return int(sum(c.sill_triangles for c in self.floor_clips))

    @property
    def removed_wall_quads(self) -> int:
        return int(self.mask[:, list(self.wall_edges)].sum()) if self.floor_edge >= 0 else 0

    @property
    def removed_floor_quads(self) -> int:
        return int(self.mask[:, self.floor_edge].sum()) if self.floor_edge >= 0 else 0


def _boundary_crossings(
    other: TubeEnvelope,
    window: tuple[int, int],
    p_in: FloatArray,
    p_out: FloatArray,
    tol: float,
    level: float | None = None,
) -> tuple[FloatArray, FloatArray]:
    """Points where the segments ``p_in → p_out`` ((m, 3) each; ``p_in``
    inside-or-on the ``other`` envelope, ``p_out`` outside) cross the SAME
    surface the vertex rule uses (``sd == level``; the child side clips at
    ``+tol``, the parent side at ``−tol`` — hardening PR-5), by deterministic
    bisection. Returns the crossing points and their parameters t ∈ (0, 1)."""
    lvl = tol if level is None else level
    m = int(p_in.shape[0])
    lo = np.zeros(m)
    hi = np.ones(m)
    for _ in range(CLIP_BISECTION_ITERATIONS):
        mid = 0.5 * (lo + hi)
        pts = p_in + mid[:, None] * (p_out - p_in)
        inside = other.signed_distance(pts, window) <= lvl
        lo = np.where(inside, mid, lo)
        hi = np.where(inside, hi, mid)
    # the OUTSIDE bracket end: on a continuous boundary it is within 2^-40 of
    # the midpoint; where the parent envelope ends discontinuously (its
    # terminal ring: sd jumps from a finite inside value to +inf) the crossing
    # then sits on the outside side of the terminal plane, so a chord between
    # two such crossings never samples the inside value of the plane itself
    t = hi
    return p_in + t[:, None] * (p_out - p_in), t


def _dedupe_loop(
    poly: list[FloatArray], par: list[FloatArray], crossing: list[bool] | None = None
) -> tuple[FloatArray, FloatArray, list[bool]]:
    """Drop consecutive (cyclic) vertices closer than ``CLIP_VERTEX_MERGE_DISTANCE``
    (a merged crossing keeps the crossing flag of the survivor)."""
    flags = crossing if crossing is not None else [False] * len(poly)
    keep_p: list[FloatArray] = []
    keep_q: list[FloatArray] = []
    keep_c: list[bool] = []
    for p, q, c in zip(poly, par, flags, strict=True):
        if keep_p and float(np.linalg.norm(p - keep_p[-1])) < CLIP_VERTEX_MERGE_DISTANCE:
            keep_c[-1] = keep_c[-1] or c
            continue
        keep_p.append(p)
        keep_q.append(q)
        keep_c.append(c)
    while (
        len(keep_p) > 1
        and float(np.linalg.norm(keep_p[0] - keep_p[-1])) < CLIP_VERTEX_MERGE_DISTANCE
    ):
        keep_p.pop()
        keep_q.pop()
        dropped = keep_c.pop()
        keep_c[0] = keep_c[0] or dropped
    q = np.asarray(keep_q, dtype=np.float64)
    return (
        np.asarray(keep_p, dtype=np.float64).reshape(-1, 3),
        q.reshape(len(keep_q), -1) if keep_q else q.reshape(0, 2),
        keep_c,
    )


class JunctionClipConflictError(ValueError):
    """Two typed junctions ask to clip the SAME child floor quad or the same
    cap fan triangle (their windows overlap on one tube). The union cannot
    represent the intersection of two remainders without a general
    Boolean, so the build fails explicitly instead of approximating
    (Phase 20D.1.2 / 20D.2; hardening PR-5 moved it here from the
    development sweep so the ramp sweep shares it)."""


class JunctionClipTopologyError(ValueError):
    """The parent boundary inside ONE straddling child floor quad cannot be
    represented by straight chords even after ``CLIP_MAX_SUBDIVISION_DEPTH``
    deterministic 2 × 2 subdivisions (Phase 20D.1.2). The build fails
    explicitly; the quad is never approximated by deleting or keeping it."""


def _sub_quad_point(corners: FloatArray, s: float, u: float) -> FloatArray:
    """Bilinear point of the quad given as [P00, P01, P10, P11] (ring i vtx j,
    ring i vtx j+1, ring i+1 vtx j, ring i+1 vtx j+1) at (s along the
    interval, u along the floor edge)."""
    out: FloatArray = (
        (1 - s) * (1 - u) * corners[0]
        + (1 - s) * u * corners[1]
        + s * (1 - u) * corners[2]
        + s * u * corners[3]
    )
    return out


def _chord_loops(
    pts: FloatArray,
    par: FloatArray,
    out: BoolArray,
    other: TubeEnvelope,
    window: tuple[int, int],
    tol: float,
    level: float | None = None,
) -> list[tuple[list[FloatArray], list[FloatArray], list[bool]]] | None:
    """Outside-parent loops of one (sub-)quad whose corners ``pts`` (4, 3) /
    ``par`` (4, 2) are in perimeter orientation order with ``out`` flags:
    marching-squares on the corners, crossings by bisection on the quad's
    own edges, the diagonal case decided by the centre sample. Each loop
    carries a per-vertex flag telling which vertices are boundary CROSSINGS
    (an edge between two consecutive crossings is a boundary chord). Returns
    None when a loop edge is NOT a faithful chord of the boundary (an interior
    sample lies inside the parent: the boundary bends inside the quad, e.g.
    the wall / terminal-plane corner where the parent ends) — the caller
    subdivides."""
    lvl = tol if level is None else level
    edges = [(m, (m + 1) % 4) for m in range(4)]
    mixed = [m for m, (a, b) in enumerate(edges) if out[a] != out[b]]
    cross_pt: dict[int, FloatArray] = {}
    cross_par: dict[int, FloatArray] = {}
    if mixed:
        p_in = np.stack([pts[edges[m][1]] if out[edges[m][0]] else pts[edges[m][0]] for m in mixed])
        p_out = np.stack(
            [pts[edges[m][0]] if out[edges[m][0]] else pts[edges[m][1]] for m in mixed]
        )
        q_in = np.stack([par[edges[m][1]] if out[edges[m][0]] else par[edges[m][0]] for m in mixed])
        q_out = np.stack(
            [par[edges[m][0]] if out[edges[m][0]] else par[edges[m][1]] for m in mixed]
        )
        xs, ts = _boundary_crossings(other, window, p_in, p_out, tol, lvl)
        for n, m in enumerate(mixed):
            cross_pt[m] = xs[n]
            cross_par[m] = q_in[n] + ts[n] * (q_out[n] - q_in[n])
    loops: list[tuple[list[FloatArray], list[FloatArray], list[bool]]] = []
    diagonal = int(out.sum()) == 2 and bool(out[0] == out[2])
    if diagonal:
        center = pts.mean(axis=0)
        center_out = bool(other.signed_distance(center[None, :], window)[0] > lvl)
        if not center_out:
            for m in range(4):
                if out[m]:
                    prev_e = (m - 1) % 4
                    loops.append(
                        (
                            [cross_pt[prev_e], pts[m], cross_pt[m]],
                            [cross_par[prev_e], par[m], cross_par[m]],
                            [True, False, True],
                        )
                    )
    if not loops:
        poly: list[FloatArray] = []
        pp: list[FloatArray] = []
        crossing: list[bool] = []
        for m in range(4):
            if out[m]:
                poly.append(pts[m])
                pp.append(par[m])
                crossing.append(False)
            if m in cross_pt:
                poly.append(cross_pt[m])
                pp.append(cross_par[m])
                crossing.append(True)
        loops.append((poly, pp, crossing))
    # chord fidelity: every loop edge must stay outside-or-on the parent
    for poly, _, _ in loops:
        if not _edges_stay(np.stack(poly), other, window, tol, outside=True, level=lvl):
            return None
    return loops


def _edges_stay(
    loop: FloatArray,
    other: TubeEnvelope,
    window: tuple[int, int],
    tol: float,
    *,
    outside: bool,
    level: float | None = None,
) -> bool:
    """Interior samples of every edge of ``loop`` (n, 3) — and of both
    diagonals for a quad — are all outside-or-on (``outside=True``:
    sd ≥ level − 2·tol, the clip band below the surface) or all
    inside-or-on (sd ≤ level) the ``other`` tube's judging surface
    (``level`` defaults to ``+tol``, the child side). A quad whose four corners
    agree can still be crossed by the parent boundary (the wall / terminal
    plane corner of a ramp ending after its last turnout runs through the
    quad interior); this check exposes it so the quad is bisected."""
    fr = (np.arange(1, CLIP_CHORD_SAMPLES + 1) / (CLIP_CHORD_SAMPLES + 1))[:, None]
    a = loop
    b = np.roll(loop, -1, axis=0)
    if loop.shape[0] == 4:
        a = np.vstack([a, loop[[0, 1]]])
        b = np.vstack([b, loop[[2, 3]]])
    samples = (a[:, None, :] + fr[None, :, :] * (b - a)[:, None, :]).reshape(-1, 3)
    lvl = tol if level is None else level
    sd = other.signed_distance(samples, window)
    ok = (sd >= lvl - 2.0 * tol) if outside else (sd <= lvl)
    if not bool(ok.all()):
        # hardening PR-5 round 2: a sample ON a jump of the judging field (the
        # plane where the tube's window or an OPEN end stops — the profile
        # value inside, +inf beyond) reads either side at floating-point whim,
        # and a loop edge lying IN that plane (a cap fan edge on the child's
        # start plane, a quad edge on a drift's end plane) never converged
        # under subdivision. The failing samples are re-judged one
        # vertex-merge distance toward the loop's own interior, where the
        # field is single-valued; a genuine intrusion or pocket keeps failing
        # and the surface change is below the merge distance.
        bad = np.flatnonzero(~ok)
        toward = loop.mean(axis=0)[None, :] - samples[bad]
        norm = np.linalg.norm(toward, axis=1, keepdims=True)
        nudged = samples[bad] + toward / np.maximum(norm, 1e-18) * CLIP_VERTEX_MERGE_DISTANCE
        sd2 = other.signed_distance(nudged, window)
        ok[bad] = (sd2 >= lvl - 2.0 * tol) if outside else (sd2 <= lvl)
    return bool(ok.all())


def _floor_quad_kind(
    corners: FloatArray,
    other: TubeEnvelope,
    window: tuple[int, int],
    tol: float,
    level: float | None = None,
) -> str:
    """'INSIDE' (omit whole), 'OUTSIDE' (keep unchanged) or 'MIXED' (clip) for
    one child floor quad given as [P00, P01, P10, P11]: the four corners AND
    interior samples of the quad's edges / diagonals must agree — a quad
    whose corners all lie outside can still be crossed by the parent's
    wall / terminal-plane corner, and one whose corners all lie inside-or-on
    can hide an outside pocket."""
    lvl = tol if level is None else level
    sd = other.signed_distance(corners, window)
    inside = sd <= lvl
    loop = corners[[0, 2, 3, 1]]  # perimeter orientation order
    if bool(inside.all()):
        return (
            "INSIDE" if _edges_stay(loop, other, window, tol, outside=False, level=lvl) else "MIXED"
        )
    if not bool(inside.any()):
        return (
            "OUTSIDE" if _edges_stay(loop, other, window, tol, outside=True, level=lvl) else "MIXED"
        )
    return "MIXED"


def _clip_floor_quad(
    corners: FloatArray,
    inside: BoolArray,
    other: TubeEnvelope,
    window: tuple[int, int],
    tol: float,
    interval: int,
    edge: int,
    node_id: str,
    *,
    floor: bool = True,
    level: float | None = None,
) -> FloorClip | None:
    """The outside-``other`` remainder of ONE straddling floor quad (or, with
    ``floor=False`` — hardening PR-2 — of a straddling WALL / ROOF quad,
    the same bilinear clip; with ``level`` — hardening PR-5 — against the
    ``other`` tube's surface at that signed-distance level instead of
    ``+tol``, the PARENT side's ``−tol``).
    ``corners`` / ``inside`` are ordered [ring i vtx j, ring i vtx j+1,
    ring i+1 vtx j, ring i+1 vtx j+1] (the render builder's quad corners);
    the perimeter in the quad's triangle orientation is
    (i, j) → (i+1, j) → (i+1, j+1) → (i, j+1). The quad is clipped by
    straight chords between boundary crossings; where a chord is not a
    faithful piece of the boundary the quad is bisected along its longer side
    (deterministically, at most ``CLIP_MAX_SUBDIVISION_DEPTH`` times) so the
    remainder never intrudes into the parent beyond the tolerance. Returns
    None when the remainder is degenerate (measure zero) — the caller then
    omits the quad."""
    lvl = tol if level is None else level
    order = (0, 2, 3, 1)  # builder corner order → perimeter orientation order
    top = ~inside[list(order)]
    polygons: list[FloatArray] = []
    pars: list[FloatArray] = []
    chords: list[FloatArray] = []
    chord_params: list[FloatArray] = []
    stack: list[tuple[float, float, float, float, int]] = [(0.0, 1.0, 0.0, 1.0, 0)]
    while stack:
        s0, s1, u0, u1, depth = stack.pop()
        par = np.array([[s0, u0], [s1, u0], [s1, u1], [s0, u1]], dtype=np.float64)
        pts = np.stack([_sub_quad_point(corners, float(sv), float(uv)) for sv, uv in par])
        out = other.signed_distance(pts, window) > lvl
        faithful = True
        loops: list[tuple[list[FloatArray], list[FloatArray], list[bool]]] = []
        if not out.any():
            # all corners inside-or-on: nothing to keep — unless the boundary
            # crosses the quad interior (an outside pocket)
            if _edges_stay(pts, other, window, tol, outside=False, level=lvl):
                continue
            faithful = False
        elif out.all():
            if _edges_stay(pts, other, window, tol, outside=True, level=lvl):
                loops = [([*pts], [*par], [False] * 4)]
            else:
                faithful = False
        else:
            chord_loops = _chord_loops(pts, par, out, other, window, tol, lvl)
            if chord_loops is None:
                faithful = False
            else:
                loops = chord_loops
        if not faithful:
            if depth >= CLIP_MAX_SUBDIVISION_DEPTH:
                sd_c = other.signed_distance(pts, window)
                raise JunctionClipTopologyError(
                    f"{node_id}: floor quad ({interval}, {edge}) boundary not representable "
                    f"after {CLIP_MAX_SUBDIVISION_DEPTH} subdivisions (sub-quad s∈[{s0:.4f},"
                    f"{s1:.4f}] u∈[{u0:.4f},{u1:.4f}], corner sd {np.round(sd_c, 3).tolist()}, "
                    f"corners {np.round(pts, 3).tolist()})"
                )
            # bisect the LONGER side (world length): a floor quad is w wide
            # and ~0.1 w long, so the width needs most of the splits
            len_s = float(np.linalg.norm(pts[1] - pts[0]))
            len_u = float(np.linalg.norm(pts[3] - pts[0]))
            if len_u >= len_s:
                um = 0.5 * (u0 + u1)
                stack.extend([(s0, s1, u0, um, depth + 1), (s0, s1, um, u1, depth + 1)])
            else:
                sm = 0.5 * (s0 + s1)
                stack.extend([(s0, sm, u0, u1, depth + 1), (sm, s1, u0, u1, depth + 1)])
            continue
        for poly, pp, cr in loops:
            p_arr, q_arr, c_arr = _dedupe_loop(poly, pp, cr)
            if p_arr.shape[0] < 3:
                continue
            # hardening PR-5: render-scale cleaning (1 mm merge, degenerate
            # fans, 1e-6 m² floor) BEFORE the chords are read, so a sill is
            # built on the vertices that are actually emitted
            cleaned = _clean_render_loop(p_arr, q_arr, c_arr)
            if cleaned is None:
                continue  # a sliver below render resolution: nothing to emit
            p_arr, q_arr, c_arr = cleaned
            polygons.append(p_arr)
            pars.append(q_arr)
            n_v = int(p_arr.shape[0])
            for a in range(n_v):
                b = (a + 1) % n_v
                if c_arr[a] and c_arr[b]:
                    chords.append(np.stack([p_arr[a], p_arr[b]]))
                    chord_params.append(np.stack([q_arr[a], q_arr[b]]))
    if not polygons:
        return None
    return FloorClip(
        interval=interval,
        edge=edge,
        polygons=tuple(polygons),
        params=tuple(pars),
        corners_outside=(bool(top[0]), bool(top[1]), bool(top[2]), bool(top[3])),
        junction_node_id=node_id,
        chords=tuple(chords),
        chord_params=tuple(chord_params),
        floor=floor,
    )


# --------------------------------------------------------------------------- #
# Phase 20D.2: an end cap at a declared junction
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CapClip:
    """Render-only clip of ONE cap fan triangle (Phase 20D.2): the polygons
    of its outside-child remainder, each with barycentric weights over the
    fan triangle's three corners (emitted winding order) for UV
    interpolation. The logical mesh is untouched."""

    triangle: int
    polygons: tuple[FloatArray, ...]
    bary: tuple[FloatArray, ...]
    junction_node_id: str

    @property
    def replacement_triangles(self) -> int:
        return int(sum(max(int(p.shape[0]) - 2, 0) for p in self.polygons))


@dataclass
class CapCut:
    """Fan triangles of ONE end cap omitted or clipped where a declared
    junction's CHILD excavation occupies the cap surface (Phase 20D.2).

    A crosscut station on a drift EXTREMITY puts the crosscut's axis in the
    DRIFT_CAP plane: the cap's crosscut-side half then stands inside the
    crosscut mouth (a cap is a separate primitive, so the quad rules never
    saw it). Cap triangles inside-or-on the child are omitted, triangles
    outside it are kept, straddling triangles are clipped at the child's
    envelope — the SAME typed local cut the child floor receives, on a cap
    fan instead of a quad grid. The remainder is the real end wall on the
    rock side; nothing is invented and no blanket cap omission exists."""

    junction: Junction
    end: Literal["start", "end"]
    omit: BoolArray  # (K,) True = omit the whole fan triangle
    clips: dict[int, CapClip] = field(default_factory=dict)

    @property
    def omitted_triangles(self) -> int:
        return int(self.omit.sum())

    @property
    def clipped_triangles(self) -> int:
        return len(self.clips)

    @property
    def replacement_triangles(self) -> int:
        return int(sum(c.replacement_triangles for c in self.clips.values()))

    @property
    def empty(self) -> bool:
        return self.omitted_triangles == 0 and not self.clips


def _clip_triangle(
    pts: FloatArray,
    bary: FloatArray,
    other: TubeEnvelope,
    window: tuple[int, int],
    tol: float,
    node_id: str,
    label: int,
    depth: int = 0,
    level: float | None = None,
) -> list[tuple[FloatArray, FloatArray]]:
    """Outside-``other`` remainder polygons of ONE triangle ``pts`` (3, 3)
    with per-corner weights ``bary`` (3, 3): corners inside-or-on / outside
    decided by the SAME tolerance surface the quad rules use, crossings by
    deterministic bisection on the triangle's own edges, chord fidelity
    checked on the remainder's edges; where a chord is not a faithful piece
    of the boundary the triangle is bisected along its longest edge
    (deterministically, at most ``CLIP_MAX_SUBDIVISION_DEPTH`` times).
    A triangle wholly inside-or-on yields no polygon (omitted)."""
    lvl = tol if level is None else level
    sd = other.signed_distance(pts, window)
    out = sd > lvl
    if not out.any():
        if _edges_stay(pts, other, window, tol, outside=False, level=lvl):
            return []
    elif out.all():
        if _edges_stay(pts, other, window, tol, outside=True, level=lvl):
            return [(pts, bary)]
    else:
        edges = ((0, 1), (1, 2), (2, 0))
        mixed = [m for m, (a, b) in enumerate(edges) if out[a] != out[b]]
        p_in = np.stack([pts[edges[m][1]] if out[edges[m][0]] else pts[edges[m][0]] for m in mixed])
        p_out = np.stack(
            [pts[edges[m][0]] if out[edges[m][0]] else pts[edges[m][1]] for m in mixed]
        )
        b_in = np.stack(
            [bary[edges[m][1]] if out[edges[m][0]] else bary[edges[m][0]] for m in mixed]
        )
        b_out = np.stack(
            [bary[edges[m][0]] if out[edges[m][0]] else bary[edges[m][1]] for m in mixed]
        )
        xs, ts = _boundary_crossings(other, window, p_in, p_out, tol, lvl)
        cross_p = {m: xs[n] for n, m in enumerate(mixed)}
        cross_b = {m: b_in[n] + ts[n] * (b_out[n] - b_in[n]) for n, m in enumerate(mixed)}
        poly: list[FloatArray] = []
        pb: list[FloatArray] = []
        for m in range(3):
            if out[m]:
                poly.append(pts[m])
                pb.append(bary[m])
            if m in cross_p:
                poly.append(cross_p[m])
                pb.append(cross_b[m])
        p_arr, b_arr, _ = _dedupe_loop(poly, pb)
        if p_arr.shape[0] < 3:
            return []
        if _edges_stay(p_arr, other, window, tol, outside=True, level=lvl):
            return [(p_arr, b_arr)]
    if depth >= CLIP_MAX_SUBDIVISION_DEPTH:
        raise JunctionClipTopologyError(
            f"{node_id}: cap triangle {label} boundary not representable after "
            f"{CLIP_MAX_SUBDIVISION_DEPTH} subdivisions (corner sd {np.round(sd, 3).tolist()}, "
            f"corners {np.round(pts, 3).tolist()})"
        )
    lengths = [
        float(np.linalg.norm(pts[1] - pts[0])),
        float(np.linalg.norm(pts[2] - pts[1])),
        float(np.linalg.norm(pts[0] - pts[2])),
    ]
    e = int(np.argmax(lengths))
    a, b, c = e, (e + 1) % 3, (e + 2) % 3
    mid = 0.5 * (pts[a] + pts[b])
    bm = 0.5 * (bary[a] + bary[b])
    first = (np.stack([pts[a], mid, pts[c]]), np.stack([bary[a], bm, bary[c]]))
    second = (np.stack([mid, pts[b], pts[c]]), np.stack([bm, bary[b], bary[c]]))
    return _clip_triangle(
        *first, other, window, tol, node_id, label, depth + 1, level=lvl
    ) + _clip_triangle(*second, other, window, tol, node_id, label, depth + 1, level=lvl)


def cut_cap(
    corners: FloatArray,
    other: TubeEnvelope,
    junction: Junction,
    end: Literal["start", "end"],
    width: float,
    *,
    side: Literal["PARENT", "CHILD"] = "PARENT",
) -> CapCut:
    """Omit / clip the fan triangles of ONE end cap (``corners`` (K, 3, 3) in
    the emitted winding: apex first) against the OTHER tube's envelope at a
    declared junction, with the SAME judging surface the tube quads of that
    side use (hardening PR-5): a PARENT cap (a drift end, the ramp's portal /
    terminal cap) against the child with its floor lowered by
    ``PARENT_JUDGE_FLOOR_DROP_TOLERANCES × tol`` at the ``−tol`` level, a CHILD
    cap (the mouth cap of ``cut_mouth_cap``) against the parent with its
    floor lowered by ``CHILD_JUDGE_FLOOR_DROP_WIDTHS`` widths at
    ``CHILD_JUDGE_LEVEL``. Inside-or-on → omit, outside → keep, straddling →
    clipped remainder; the query window grows with the cap's distance from
    the junction, so a cap up to ``PARENT_EXTENSION_MAX_WIDTHS`` away is
    judged exactly. A cap the other tube does not reach comes back empty.
    Before PR-5 a parent cap was judged at ``+tol`` like a child, which left a
    tol-wide ring notch around a crosscut piercing a drift end cap (the cap
    hole tol larger than the crosscut, the crosscut's shell beginning tol
    beyond the cap plane)."""
    radius = JUNCTION_WINDOW_WIDTHS * width
    tol = JUNCTION_SURFACE_TOLERANCE_FRACTION * width
    if side == "PARENT":
        # hardening PR-5 round 2: the same end-plane declaration as
        # ``cut_tube`` — the child's far end capped, its junction end open
        judge = other.floor_lowered(PARENT_JUDGE_FLOOR_DROP_TOLERANCES * tol).with_end_planes(
            junction.child_end != "start", junction.child_end != "end"
        )
        level = -tol
    else:
        judge = other.floor_lowered(CHILD_JUDGE_FLOOR_DROP_WIDTHS * width).with_end_planes(
            True, True
        )
        level = CHILD_JUDGE_LEVEL
    k = int(corners.shape[0])
    omit = np.zeros(k, dtype=bool)
    clips: dict[int, CapClip] = {}
    flat = corners.reshape(-1, 3)
    reach = float(np.linalg.norm(flat - junction.point[None, :], axis=1).max())
    window = judge.ring_window(junction.point, max(radius, reach) + width)
    if window[1] - window[0] < 2:
        return CapCut(junction, end, omit, clips)
    sd = judge.signed_distance(flat, window).reshape(k, 3)
    inside = sd <= level
    ident = np.eye(3, dtype=np.float64)
    for t in range(k):
        pts = corners[t]
        if bool(inside[t].all()) and _edges_stay(
            pts, judge, window, tol, outside=False, level=level
        ):
            omit[t] = True
            continue
        if not bool(inside[t].any()) and _edges_stay(
            pts, judge, window, tol, outside=True, level=level
        ):
            continue
        loops = _clip_triangle(pts, ident, judge, window, tol, junction.node_id, t, level=level)
        # the remainder is emitted as float32 render geometry: a crossing that
        # lands within render resolution of a fan corner, or a fan whose three
        # vertices fall on one line, covers no surface — cleaned, so dropping
        # it can open nothing (hardening PR-5: the same rule for every side)
        polys: list[FloatArray] = []
        bars: list[FloatArray] = []
        for poly, bary in loops:
            cleaned = _clean_render_polygon(poly, bary)
            if cleaned is not None:
                polys.append(cleaned[0])
                bars.append(cleaned[1])
        if not polys:
            omit[t] = True
            continue
        clips[t] = CapClip(
            triangle=t,
            polygons=tuple(polys),
            bary=tuple(bars),
            junction_node_id=junction.node_id,
        )
    return CapCut(junction, end, omit, clips)


def cut_mouth_cap(
    corners: FloatArray,
    parent: TubeEnvelope,
    junction: Junction,
    end: Literal["start", "end"],
    width: float,
) -> CapCut | None:
    """Phase 20D.2.1 — the CHILD's OPEN end ring judged against the PARENT
    envelope: the mirror of ``cut_cap``. ``corners`` (K, 3, 3) is the cap fan
    of the child's OPEN end ring (emitted winding, apex first). Fan
    triangles inside-or-on the parent excavation are omitted (the mouth
    stays OPEN into the parent), triangles outside it are kept and
    straddling ones are clipped at the parent's boundary — the remainder is
    the rock-facing part of the mouth that has no surface without it (a
    crosscut station on a drift EXTREMITY: the drift ends AT the station,
    so half of the crosscut mouth lies beyond the drift end). Same window,
    tolerance and classification as every other typed junction cut; a ring
    wholly inside its parent (an interior T-junction) yields ``None`` and
    the render stays bit-identical. Not a general Boolean: ONE child end,
    ONE parent envelope, the declared junction only."""
    radius = JUNCTION_WINDOW_WIDTHS * width
    window = parent.ring_window(junction.point, radius + width)
    if window[1] - window[0] < 2:
        raise JunctionClipTopologyError(
            f"{junction.node_id}: parent {junction.parent_id} has no ring window at the "
            f"child mouth (junction point {np.round(junction.point, 3).tolist()})"
        )
    cut = cut_cap(corners, parent, junction, end, width, side="CHILD")
    if cut.omitted_triangles == int(corners.shape[0]):
        return None
    return cut


#: Render-scale cleaning of EVERY clip remainder (Phase 20D.2.1 for the
#: mouth cap; hardening PR-5 for cap clips, floor / wall clips and sills) —
#: float32 positions at a few hundred metres resolve ≈ 1.5e-5 m, so a
#: crossing within 1 mm of a corner, or a riser below a millimetre, is a
#: degenerate sliver, never a surface. Measured on the TABULAR fixture
#: before PR-5 cleaned them: the drift END cap's crown fan at an extremity
#: station kept a zero-area triangle (apex, crown, crown − tol: three points
#: on the cap's centre line) once the crown vertex counted as outside at −tol.
RENDER_VERTEX_MERGE_M = 1e-3
RENDER_MIN_AREA_M2 = 1e-6
MOUTH_CAP_VERTEX_MERGE_M = RENDER_VERTEX_MERGE_M
MOUTH_CAP_MIN_AREA_M2 = RENDER_MIN_AREA_M2


def _clean_render_loop(
    poly: FloatArray, bary: FloatArray, flags: list[bool] | None = None
) -> tuple[FloatArray, FloatArray, list[bool]] | None:
    """Merge consecutive (cyclic) vertices closer than ``RENDER_VERTEX_MERGE_M``
    (a merged vertex keeps a crossing flag if either had one), drop interior
    vertices whose fan triangle (from vertex 0) is degenerate, and drop the
    loop when fewer than three vertices or less than ``RENDER_MIN_AREA_M2``
    remain. The surface change is below float32 resolution of the emitted
    geometry. ``flags`` (boundary-crossing markers, see ``_chord_loops``)
    travel with their vertices so chords are read from the CLEANED loop."""
    fl = flags if flags is not None else [False] * int(poly.shape[0])
    keep_p: list[FloatArray] = []
    keep_b: list[FloatArray] = []
    keep_f: list[bool] = []
    for q in range(int(poly.shape[0])):
        if keep_p and float(np.linalg.norm(poly[q] - keep_p[-1])) < RENDER_VERTEX_MERGE_M:
            keep_f[-1] = keep_f[-1] or fl[q]
            continue
        keep_p.append(poly[q])
        keep_b.append(bary[q])
        keep_f.append(fl[q])
    while len(keep_p) > 1 and float(np.linalg.norm(keep_p[-1] - keep_p[0])) < RENDER_VERTEX_MERGE_M:
        keep_f[0] = keep_f[0] or keep_f[-1]
        keep_p.pop()
        keep_b.pop()
        keep_f.pop()
    # fan-degenerate interior vertices (collinear with vertex 0 and a neighbour)
    changed = True
    while changed and len(keep_p) >= 3:
        changed = False
        for i in range(1, len(keep_p) - 1):
            area = 0.5 * float(
                np.linalg.norm(np.cross(keep_p[i] - keep_p[0], keep_p[i + 1] - keep_p[0]))
            )
            if area < RENDER_MIN_AREA_M2:
                del keep_p[i]
                del keep_b[i]
                del keep_f[i]
                changed = True
                break
    if len(keep_p) < 3:
        return None
    p_arr = np.stack(keep_p)
    total = 0.5 * float(
        np.linalg.norm(
            sum(
                np.cross(p_arr[i] - p_arr[0], p_arr[i + 1] - p_arr[0])
                for i in range(1, len(keep_p) - 1)
            )
        )
    )
    if total < RENDER_MIN_AREA_M2:
        return None
    return p_arr, np.stack(keep_b), keep_f


def _clean_render_polygon(
    poly: FloatArray, bary: FloatArray
) -> tuple[FloatArray, FloatArray] | None:
    """``_clean_render_loop`` without crossing flags."""
    cleaned = _clean_render_loop(poly, bary)
    if cleaned is None:
        return None
    return cleaned[0], cleaned[1]


def _nearest_on_polyline(poly: FloatArray, p: FloatArray) -> tuple[FloatArray, float]:
    """Foot point of ``p`` on the polyline ``poly`` (M, 3) and its PLAN distance."""
    a = poly[:-1]
    b = poly[1:]
    ab = b - a
    ab2 = np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-18)
    t = np.clip(np.einsum("ij,ij->i", p[None, :] - a, ab) / ab2, 0.0, 1.0)
    feet = a + t[:, None] * ab
    d_plan = np.linalg.norm(feet[:, :2] - p[None, :2], axis=1)
    i = int(np.argmin(d_plan))
    return feet[i], float(d_plan[i])


def _riser_top(
    foot: FloatArray,
    chord_end: FloatArray,
    up: FloatArray,
    judge: TubeEnvelope,
    judge_window: tuple[int, int],
    level: float,
) -> FloatArray:
    """Hardening PR-5: the highest point of the parent wall above ``foot``
    (on the parent floor edge) that the exact parent clip KEEPS, no higher
    than the chord end — the top of the riser under a clipped child floor.
    Found on the SAME judging surface the parent clip uses (``judge`` at
    ``level``), by deterministic bisection along the parent's local up:
    the wall is cut down to the floor edge when the foot itself is inside
    (the sill then lands on the floor edge, as before PR-5), and stands
    through the chord's height when no point below it is inside (the sill
    is then a flat strip from the chord to the wall)."""
    t_max = max(float(np.dot(chord_end - foot, up)), 0.0)
    if t_max <= 1e-9:
        return foot
    if float(judge.signed_distance(foot[None, :], judge_window)[0]) <= level:
        return foot
    top = foot + up * t_max
    if float(judge.signed_distance(top[None, :], judge_window)[0]) > level:
        return top
    lo, hi = 0.0, t_max  # lo kept, hi removed
    for _ in range(CLIP_BISECTION_ITERATIONS):
        mid = 0.5 * (lo + hi)
        if float(judge.signed_distance((foot + up * mid)[None, :], judge_window)[0]) <= level:
            hi = mid
        else:
            lo = mid
    out: FloatArray = foot + up * lo
    return out


#: Hardening PR-5 sill sampling: riser tops are measured every half
#: tolerance along a chord, and a riser shorter than ``RENDER_VERTEX_MERGE_M``
#: is a flush seam (no sill).
SILL_STATION_FRACTION_OF_TOL = 0.5


def _straight_riser_runs(tops: FloatArray, a: int, b: int) -> list[tuple[int, int]]:
    """Split the station run ``[a, b]`` where the riser-top polyline bends:
    every returned sub-run's interior tops lie within ``RENDER_VERTEX_MERGE_M``
    of the segment between its end tops (deterministic Douglas–Peucker), so
    one quad per sub-run represents the riser exactly at render scale and
    neighbouring quads share their vertical edge."""
    out: list[tuple[int, int]] = []
    stack = [(a, b)]
    while stack:
        i, j = stack.pop()
        if j - i <= 1:
            out.append((i, j))
            continue
        seg = tops[j] - tops[i]
        seg2 = max(float(np.dot(seg, seg)), 1e-18)
        rel = tops[i + 1 : j] - tops[i][None, :]
        proj = (rel @ seg) / seg2
        dev = np.linalg.norm(rel - proj[:, None] * seg[None, :], axis=1)
        k = int(np.argmax(dev))
        if float(dev[k]) <= RENDER_VERTEX_MERGE_M:
            out.append((i, j))
        else:
            stack.append((i + 1 + k, j))
            stack.append((i, i + 1 + k))
    return sorted(out)


def _with_sills(
    clip: FloorClip,
    other: TubeEnvelope,
    window: tuple[int, int],
    width: float,
    riser: tuple[TubeEnvelope, tuple[int, int], float] | None = None,
) -> FloorClip:
    """Hardening PR-2 (H0 §3.4 seam), PR-5: close the floor seam of a clipped
    CHILD floor quad. Since PR-5 the remainder's boundary chord lies ON the
    parent's wall plane (or its terminal plane) at the child floor elevation,
    while the parent's wall — cut by the exact parent clip on the child's
    judging envelope — stands under it only up to the RISER TOP: ``tol``
    below the chord where the child floor is above the parent floor (the
    lowered judging floor leaves exactly one tolerance of wall), the parent
    floor edge itself where the chord is at or below it, and the chord's own
    height within ``tol`` of the chord ends (the doorway jamb, which the
    parent keeps as its −tol lip). The strip between chord and riser top is
    the SILL: a real step surface between two real surfaces, oriented into
    the rock, never a floating slab.

    The riser top is measured at stations every ``SILL_STATION_FRACTION_OF_TOL
    × tol`` along the chord (``_riser_top`` on the child's judging envelope
    ``riser`` = (envelope, window, level), from the parent floor BOUNDARY
    point under each station — a side edge, or the floor's END edge where the
    chord lies on the parent's terminal plane: a ramp ending inside a
    turnout, hardening PR-5), and one sill quad is emitted per contiguous run
    of stations whose riser is at least ``RENDER_VERTEX_MERGE_M`` high, the
    run widened by one station so the strip reaches the standing jamb (PR-2's
    single quad between the two chord ENDS collapsed whenever the jambs stood
    to the chord height, leaving the whole tol-high strip open — measured as
    the floor-seam escapes of ``tests/test_junction_seam.py``). A chord that
    is not a floor meeting (farther than ``SILL_MAX_PLAN_DISTANCE_WIDTHS ×
    width`` in plan from every floor boundary) gets no sill and is counted.
    Non-floor clips are returned unchanged."""
    if not clip.floor or not clip.chords:
        return clip
    lo, hi = window
    if hi - lo < 2:
        return clip
    rings = boundary_points(other.centers[lo:hi], other.tangents[lo:hi], other.shape)
    fe = floor_edge_index(other.shape)
    fn = (fe + 1) % other.shape.k
    boundaries: list[FloatArray] = [rings[:, fe, :], rings[:, fn, :]]
    if lo == 0:
        boundaries.append(rings[0, [fe, fn], :])  # the floor's start edge (a cap end)
    if hi == int(other.centers.shape[0]):
        boundaries.append(rings[-1, [fe, fn], :])  # the floor's end edge
    centers = other.centers[lo:hi]
    _, ups = gravity_frames(other.tangents[lo:hi])
    tol = JUNCTION_SURFACE_TOLERANCE_FRACTION * width
    station = SILL_STATION_FRACTION_OF_TOL * tol
    sills: list[FloatArray] = []
    sill_params: list[FloatArray] = []
    sill_chords: list[int] = []
    skipped = 0
    for index, (chord, par) in enumerate(zip(clip.chords, clip.chord_params, strict=True)):
        best: tuple[float, FloatArray] | None = None
        for side in boundaries:
            d = max(
                _nearest_on_polyline(side, chord[0])[1], _nearest_on_polyline(side, chord[1])[1]
            )
            if best is None or d < best[0]:
                best = (d, side)
        assert best is not None
        d_plan, side = best
        if d_plan > SILL_MAX_PLAN_DISTANCE_WIDTHS * width:
            skipped += 1
            continue
        length = float(np.linalg.norm(chord[1] - chord[0]))
        n_st = max(3, int(np.ceil(length / station)) + 1)
        s = np.linspace(0.0, 1.0, n_st)
        pts = chord[0][None, :] + s[:, None] * (chord[1] - chord[0])[None, :]
        prs = par[0][None, :] + s[:, None] * (par[1] - par[0])[None, :]
        tops = np.empty_like(pts)
        for q in range(n_st):
            foot, _ = _nearest_on_polyline(side, pts[q])
            if riser is not None:
                judge, judge_window, level = riser
                up = ups[int(np.argmin(np.linalg.norm(centers - pts[q][None, :], axis=1)))]
                foot = _riser_top(foot, pts[q], up, judge, judge_window, level)
            tops[q] = foot
        gap = np.linalg.norm(pts - tops, axis=1)
        open_ = gap >= RENDER_VERTEX_MERGE_M
        if not bool(open_.any()):
            continue  # a flush seam: the chord lies on the riser top
        runs: list[tuple[int, int]] = []
        q = 0
        while q < n_st:
            if not open_[q]:
                q += 1
                continue
            a = q
            while q + 1 < n_st and open_[q + 1]:
                q += 1
            runs.extend(_straight_riser_runs(tops, a, q))
            q += 1
        for a, b in runs:
            # the chord edge of the strip reaches one station past the run
            # (to the standing jamb, where the riser top is the chord itself);
            # the riser-top edge spans the OPEN stations only — a corner that
            # coincided with the chord end would collapse the quad
            a_c = a - 1 if a > 0 and not open_[a - 1] else a
            b_c = b + 1 if b + 1 < n_st and not open_[b + 1] else b
            cleaned = _clean_render_polygon(
                np.stack([pts[a_c], pts[b_c], tops[b], tops[a]]),
                np.stack([prs[a_c], prs[b_c], prs[b], prs[a]]),
            )
            if cleaned is None:
                continue
            loop, pars = cleaned
            area_vec = np.zeros(3)
            for m in range(1, int(loop.shape[0]) - 1):
                area_vec += np.cross(loop[m] - loop[0], loop[m + 1] - loop[0])
            if float(np.linalg.norm(area_vec)) < 1e-6:
                continue
            # orientation = INTO THE ROCK (the mesh convention of every tube
            # quad and cap, rule 66). A near-horizontal strip is a floor
            # patch: rock below, normal down. A riser's rock side is under
            # the LOWER floor: a step UP into the child (chord above the riser
            # top) has rock on the child side → normal away from the parent
            # centerline; a step DOWN (chord below the parent floor edge) has
            # rock under the parent floor → normal toward it. PR-2 oriented
            # every sill away from the parent, right only for a step up.
            mid = pts[a_c : b_c + 1].mean(axis=0)
            # "toward the parent" = toward a centerline point strictly INSIDE
            # the parent: for a sill on the parent's terminal plane (a ramp
            # ending inside a turnout) the nearest ring center lies ON that
            # plane beside the chord, so the inward neighbour ring decides
            # the sign (measured: the L04 terminal-plane risers came out
            # facing the access, and the probe's rays passed their back face
            # into the rock under the ramp floor)
            g = lo + int(np.argmin(np.linalg.norm(centers - mid[None, :], axis=1)))
            r_total = int(other.centers.shape[0])
            g = (
                1
                if g == 0 and r_total > 1
                else (r_total - 2 if g == r_total - 1 and r_total > 1 else g)
            )
            toward = other.centers[g] - mid
            toward[2] = 0.0
            if abs(float(area_vec[2])) >= float(np.hypot(area_vec[0], area_vec[1])):
                flip = float(area_vec[2]) > 0.0
            else:
                step_up = float(pts[a : b + 1, 2].mean() - tops[a : b + 1, 2].mean()) > 0.0
                along = float(np.dot(area_vec, toward))
                flip = along > 0.0 if step_up else along < 0.0
            if flip:
                loop = loop[::-1].copy()
                pars = pars[::-1].copy()
            sills.append(loop)
            sill_params.append(pars)
            sill_chords.append(index)
    if not sills and not skipped:
        return clip
    return replace(
        clip,
        sills=tuple(sills),
        sill_params=tuple(sill_params),
        sill_chords=tuple(sill_chords),
        chords_without_sill=skipped,
    )


def cut_tube(
    own: TubeEnvelope,
    own_rings: FloatArray,
    other: TubeEnvelope,
    junction: Junction,
    side: Literal["PARENT", "CHILD"],
    width: float,
) -> JunctionCut:
    """Mask of this tube's quads to omit at ``junction`` against the OTHER
    tube's envelope, plus the quads clipped instead of omitted. PARENT side
    (hardening PR-5, replacing the Phase 20D.1.1 area rule): every non-floor
    quad is judged EXACTLY against the child's judging envelope (the child
    with its floor lowered by ``PARENT_JUDGE_FLOOR_DROP_TOLERANCES × tol``) at
    the ``−tol`` level — inside omitted, outside kept, straddling clipped
    (``wall_clips``); the floor edge is never cut. CHILD side (hardening
    PR-5): every quad is judged at the parent's EXACT surface
    (``CHILD_JUDGE_LEVEL``) against the parent with its floor lowered by
    ``CHILD_JUDGE_FLOOR_DROP_WIDTHS`` widths — INSIDE omitted (intruding
    shell, coincident roof), OUTSIDE kept, STRADDLING clipped: a FLOOR quad
    into ``floor_clips`` (Phase 20D.1.2) whose boundary chords are bridged
    to the parent's riser top by sill strips (hardening PR-2 / PR-5,
    ``FloorClip.sills``), a WALL / ROOF quad into ``wall_clips`` instead of
    being kept whole. Only quads whose rings lie inside the window are
    examined; everything else is untouched by construction."""
    radius = JUNCTION_WINDOW_WIDTHS * width
    tol = JUNCTION_SURFACE_TOLERANCE_FRACTION * width
    r, k, _ = own_rings.shape
    mask = np.zeros((r - 1, k), dtype=bool)
    floor_edge = floor_edge_index(own.shape)
    walls = wall_edge_indices(own.shape)
    lo, hi = own.ring_window(junction.point, radius)
    other_window = other.ring_window(junction.point, radius + width)
    clips: list[FloorClip] = []
    wall_clips: list[FloorClip] = []
    unclipped_walls = 0
    if hi - lo < 2:
        return JunctionCut(junction, side, mask, (lo, hi), floor_edge, walls, clips)
    # all quad vertices of the windowed intervals in one query
    intervals = np.arange(lo, hi - 1)
    v = np.stack(
        [
            own_rings[intervals][:, :, :],  # ring i, vertex j
            np.roll(own_rings[intervals], -1, axis=1),  # ring i, vertex j+1
            own_rings[intervals + 1][:, :, :],  # ring i+1, vertex j
            np.roll(own_rings[intervals + 1], -1, axis=1),  # ring i+1, vertex j+1
        ],
        axis=2,
    )  # (I, K, 4, 3)
    extended: tuple[int, int] | None = None
    judge: TubeEnvelope | None = None
    level = tol
    if side == "PARENT":
        # hardening PR-5 round 2: the child's FAR end is a surface of the child
        # (a crosscut face, a drift end); its OPEN junction end is not — the
        # parent's own void continues through it (``with_end_planes``)
        judge = other.floor_lowered(PARENT_JUDGE_FLOOR_DROP_TOLERANCES * tol).with_end_planes(
            junction.child_end != "start", junction.child_end != "end"
        )
        level = -tol
        omit = np.zeros((len(intervals), k), dtype=bool)
        for idx in range(len(intervals)):
            row, row_clips, n_unclipped = _judge_parent_interval(
                v[idx], judge, other_window, tol, level, floor_edge, int(intervals[idx]), junction
            )
            omit[idx] = row
            wall_clips.extend(row_clips)
            unclipped_walls += n_unclipped
        mask[intervals] = omit
        extended, n_unclipped = _extend_parent_pass(
            own,
            own_rings,
            judge,
            junction,
            width,
            tol,
            level,
            floor_edge,
            (lo, hi),
            mask,
            wall_clips,
        )
        unclipped_walls += n_unclipped
    else:
        # hardening PR-5: the child is judged at the parent's EXACT surface
        # (``CHILD_JUDGE_LEVEL``) against the parent with its floor lowered
        # (``CHILD_JUDGE_FLOOR_DROP_WIDTHS``) — every quad, floor and
        # non-floor, by the one kind / clip rule the parent side uses: INSIDE
        # omitted, OUTSIDE kept, MIXED clipped (Phase 20D.1.2 for the floor,
        # hardening PR-2 for walls / roof; before PR-5 a wall quad with every
        # corner outside was kept whole even when the boundary crossed its
        # interior). A floor boundary the chord clip cannot represent stays
        # fatal; a wall / roof one keeps the quad whole and is counted.
        # hardening PR-5 round 2: both ends of the PARENT are surfaces where its
        # void stops (an end cap, the ramp's portal / terminal cap, an access's
        # open end into the ramp or the drift) — judged as capped planes, so a
        # child surface lying IN such a plane (the L-junction crosscut) is
        # classified continuously (``with_end_planes``)
        child_judge = other.floor_lowered(CHILD_JUDGE_FLOOR_DROP_WIDTHS * width).with_end_planes(
            True, True
        )
        level = CHILD_JUDGE_LEVEL
        sd = child_judge.signed_distance(v.reshape(-1, 3), other_window)
        inside_v = sd.reshape(len(intervals), k, 4) <= level
        omit = np.zeros((len(intervals), k), dtype=bool)
        for idx in range(len(intervals)):
            for e in range(k):
                corners = v[idx, e]
                kind = _floor_quad_kind(corners, child_judge, other_window, tol, level=level)
                if kind == "INSIDE":
                    omit[idx, e] = True
                    continue
                if kind == "OUTSIDE":
                    continue
                try:
                    clip = _clip_floor_quad(
                        corners,
                        inside_v[idx, e],
                        child_judge,
                        other_window,
                        tol,
                        int(intervals[idx]),
                        e,
                        junction.node_id,
                        floor=e == floor_edge,
                        level=level,
                    )
                except JunctionClipTopologyError:
                    if e == floor_edge:
                        raise
                    unclipped_walls += 1
                    continue
                if clip is None:
                    omit[idx, e] = True  # measure-zero remainder: nothing to keep
                elif e == floor_edge:
                    clips.append(clip)
                else:
                    wall_clips.append(clip)
        mask[intervals] = omit
        _extend_child_floor_pass(
            own,
            own_rings,
            child_judge,
            junction,
            width,
            tol,
            level,
            floor_edge,
            (lo, hi),
            mask,
            clips,
        )
        sill_window = other.ring_window(junction.point, radius + 3.0 * width)
        # hardening PR-5: the sill foot is the parent's riser top under the
        # chord, judged on THIS child's judging envelope exactly as the parent
        # clip judges it (the parent builder sweeps the same centerline)
        own_judge = own.floor_lowered(PARENT_JUDGE_FLOOR_DROP_TOLERANCES * tol).with_end_planes(
            junction.child_end != "start", junction.child_end != "end"
        )
        own_window = own.ring_window(junction.point, radius + width)
        clips = [
            _with_sills(c, other, sill_window, width, riser=(own_judge, own_window, -tol))
            for c in clips
        ]
    touched_rows = mask.any(axis=1)
    for c in (*clips, *wall_clips):
        touched_rows[c.interval] = True
    cut_rows = np.flatnonzero(touched_rows)
    span = (
        (float(own.chainage[int(cut_rows.min())]), float(own.chainage[int(cut_rows.max()) + 1]))
        if cut_rows.size
        else None
    )
    return JunctionCut(
        junction,
        side,
        mask,
        (lo, hi),
        floor_edge,
        walls,
        clips,
        wall_clips,
        unclipped_walls,
        extended,
        span,
        judge,
        level if side == "PARENT" else None,
        tol if side == "PARENT" else None,
    )


#: Safety bound of the parent-side extension pass, in tunnel widths from the
#: junction point: a child body that still overlaps the parent this far out
#: is not a doorway any more (a drive running inside the parent), so the pass
#: stops and the truncation is reported instead of cutting the parent open
#: indefinitely. A tangential access clears a R = 37 m ramp's wall line with
#: its full width at ≈ sqrt(2·R·w) ≈ 3.9 widths.
PARENT_EXTENSION_MAX_WIDTHS = 6.0


def _judge_parent_interval(
    corners: FloatArray,
    judge: TubeEnvelope,
    window: tuple[int, int],
    tol: float,
    level: float,
    floor_edge: int,
    interval: int,
    junction: Junction,
) -> tuple[BoolArray, list[FloorClip], int]:
    """Hardening PR-5: the exact PARENT judgement of ONE ring interval's quads
    ``corners`` (K, 4, 3) against the child's judging envelope at ``level``
    → (omit row (K,), clipped quads, quads kept whole because their boundary
    could not be represented within the subdivision budget). The floor edge
    is never judged. Quads whose four corners are all farther outside the
    surface than their own size cannot be crossed by it (the signed distance
    is 1-Lipschitz) and are kept without edge sampling."""
    k = int(corners.shape[0])
    omit = np.zeros(k, dtype=bool)
    clips: list[FloorClip] = []
    unclipped = 0
    sd = judge.signed_distance(corners.reshape(-1, 3), window).reshape(k, 4)
    size = np.maximum(
        np.linalg.norm(corners[:, 3] - corners[:, 0], axis=1),
        np.linalg.norm(corners[:, 2] - corners[:, 1], axis=1),
    )
    for e in range(k):
        if e == floor_edge:
            continue
        if bool(np.all(sd[e] > level + size[e])):
            continue
        kind = _floor_quad_kind(corners[e], judge, window, tol, level=level)
        if kind == "INSIDE":
            omit[e] = True
            continue
        if kind == "OUTSIDE":
            continue
        try:
            clip = _clip_floor_quad(
                corners[e],
                sd[e] <= level,
                judge,
                window,
                tol,
                interval,
                e,
                junction.node_id,
                floor=False,
                level=level,
            )
        except JunctionClipTopologyError:
            unclipped += 1  # kept whole and counted, never approximated
            continue
        if clip is None:
            omit[e] = True  # measure-zero remainder
        else:
            clips.append(clip)
    return omit, clips, unclipped


def _extend_parent_pass(
    own: TubeEnvelope,
    own_rings: FloatArray,
    judge: TubeEnvelope,
    junction: Junction,
    width: float,
    tol: float,
    level: float,
    floor_edge: int,
    window: tuple[int, int],
    mask: BoolArray,
    wall_clips: list[FloorClip],
) -> tuple[tuple[int, int], int]:
    """Hardening PR-4 (W1b, doorway probe finding), PR-5: the PARENT quads are
    judged past the window edge, ring interval by ring interval in BOTH
    directions along the parent, until the first interval that loses no
    quad. The window (``JUNCTION_WINDOW_WIDTHS`` = 2 widths) was sized for the
    CHILD's inner wall to clear the parent (≈ R·acos(1 − w/R) ≈ 1.6 w for
    R = 18 m, w = 5 m); the child's full body leaves the parent wall line
    only at lateral = w (≈ R·acos(1 − 2w/R) ≈ 2.8 w, 13.7 m), so at every
    shallow-angle ramp turnout of the TABULAR fixture a ramp wall slab
    survived from 10 m to ≈ 13.7 m along the access, standing across the
    access's outer half (``tests/test_junction_passability.py``: the shoulder
    probe 0.6 m off the centerline at 1.0 m hit it at chainage 10.0 m, the
    triangle 0.74 m above the floor). The SAME exact judgement decides every
    extended quad (``_judge_parent_interval``); the floor edge is never cut;
    the pass is contiguous from the window (a clean interval ends it) and
    bounded by ``PARENT_EXTENSION_MAX_WIDTHS``, so a parent the child merely
    passes near elsewhere is never touched. Returns the examined ring range
    and the quads kept whole for want of a representable boundary."""
    lo, hi = window
    r = int(own_rings.shape[0])
    limit = PARENT_EXTENSION_MAX_WIDTHS * width
    unclipped = 0

    def judge_interval(i: int) -> bool:
        nonlocal unclipped
        reach = float(np.linalg.norm(own.centers[[i, i + 1]] - junction.point, axis=1).max())
        if reach > limit:
            return False
        corners = np.stack(
            [
                own_rings[i],
                np.roll(own_rings[i], -1, axis=0),
                own_rings[i + 1],
                np.roll(own_rings[i + 1], -1, axis=0),
            ],
            axis=1,
        )  # (K, 4, 3)
        other_window = judge.ring_window(junction.point, reach + width)
        omit, clips, n_unclipped = _judge_parent_interval(
            corners, judge, other_window, tol, level, floor_edge, i, junction
        )
        if not bool(omit.any()) and not clips:
            return False
        mask[i] |= omit
        wall_clips.extend(clips)
        unclipped += n_unclipped
        return True

    ehi = hi
    for i in range(hi - 1, r - 1):
        if not judge_interval(i):
            break
        ehi = i + 2
    elo = lo
    for i in range(lo - 1, -1, -1):
        if not judge_interval(i):
            break
        elo = i
    return (min(elo, lo), max(ehi, hi)), unclipped


def _reclip(existing: FloorClip, cut: JunctionCut, width: float) -> FloorClip | None:
    """Hardening PR-5: the remainder polygons of a parent quad already clipped
    by one junction, clipped again against ``cut``'s judging envelope (the
    second junction's child) — each polygon fan-triangulated and run through
    the same chord clip, bilinear params carried as the triangle weights.
    Returns None when nothing remains (the quad is then omitted)."""
    assert cut.judge_envelope is not None
    assert cut.judge_level is not None and cut.judge_tolerance is not None
    judge, level, tol = cut.judge_envelope, cut.judge_level, cut.judge_tolerance
    polys: list[FloatArray] = []
    pars: list[FloatArray] = []
    for poly, par in zip(existing.polygons, existing.params, strict=True):
        reach = float(np.linalg.norm(poly - cut.junction.point[None, :], axis=1).max())
        window = judge.ring_window(cut.junction.point, reach + width)
        for a in range(1, int(poly.shape[0]) - 1):
            tri = np.stack([poly[0], poly[a], poly[a + 1]])
            tpar = np.stack([par[0], par[a], par[a + 1]])
            for p_arr, q_arr in _clip_triangle(
                tri, tpar, judge, window, tol, cut.junction.node_id, a, level=level
            ):
                polys.append(p_arr)
                pars.append(q_arr)
    if not polys:
        return None
    return replace(
        existing,
        polygons=tuple(polys),
        params=tuple(pars),
        junction_node_id=f"{existing.junction_node_id}+{cut.junction.node_id}",
    )


def merge_parent_cut(
    cut: JunctionCut,
    quad_mask: BoolArray,
    clips: dict[tuple[int, int], FloorClip],
    width: float,
) -> int:
    """Hardening PR-5: apply one PARENT cut to a tube's accumulated render
    mask and clip map. A whole omission (by any junction) wins over a clip;
    a quad already clipped by another junction is RE-CLIPPED against this
    one (``_reclip``) — two turnouts, or a level entry and a station, may
    share parent quads — and a quad whose re-clip cannot represent the
    boundary keeps its earlier clip (counted, never approximated). Returns
    the number of re-clipped quads."""
    quad_mask |= cut.mask
    reclipped = 0
    for clip in cut.clips:
        key = (clip.interval, clip.edge)
        if quad_mask[key]:
            continue
        existing = clips.get(key)
        if existing is None:
            clips[key] = clip
            continue
        try:
            merged = _reclip(existing, cut, width)
        except JunctionClipTopologyError:
            continue
        reclipped += 1
        if merged is None:
            quad_mask[key] = True
            del clips[key]
        else:
            clips[key] = merged
    for key in [key for key in clips if quad_mask[key]]:
        del clips[key]
    return reclipped


def merge_cap_cut(existing: CapCut | None, cap_cut: CapCut, owner_id: str) -> CapCut:
    """Phase 20D.2 (shared by the development and ramp sweeps since hardening
    PR-5): merge one junction's cut of an end cap into that cap's accumulated
    cut. A whole omission (by any junction) is a superset of a clip; two
    junctions clipping one fan triangle are an explicit
    ``JunctionClipConflictError``, never an approximation (the contract of
    the child floor clips). Returns the accumulated cut (a copy on first
    use, so the per-junction cut is never mutated)."""
    if existing is None:
        return CapCut(cap_cut.junction, cap_cut.end, cap_cut.omit.copy(), dict(cap_cut.clips))
    existing.omit |= cap_cut.omit
    for t, clip in cap_cut.clips.items():
        if existing.omit[t]:
            continue
        if t in existing.clips and existing.clips[t].junction_node_id != clip.junction_node_id:
            raise JunctionClipConflictError(
                f"{owner_id}: cap triangle {t} ({cap_cut.end}) clipped by "
                f"both {existing.clips[t].junction_node_id} and {clip.junction_node_id}"
            )
        existing.clips[t] = clip
    for t in [t for t in existing.clips if existing.omit[t]]:
        del existing.clips[t]
    return existing


def _extend_child_floor_pass(
    own: TubeEnvelope,
    own_rings: FloatArray,
    other: TubeEnvelope,
    junction: Junction,
    width: float,
    tol: float,
    level: float,
    floor_edge: int,
    window: tuple[int, int],
    mask: BoolArray,
    clips: list[FloorClip],
) -> None:
    """Phase 20D.1.2: the CHILD FLOOR is judged past the window edge, ring
    interval by ring interval away from the junction end, until the first
    floor quad that lies fully outside the parent. The wall window
    (``JUNCTION_WINDOW_WIDTHS``) was sized for the child's INNER wall to clear
    the parent (≈ R·acos(1 − w/R) ≈ 1.6 w); the far corner of the full-width
    floor clears only at lateral = w (≈ R·acos(1 − 2w/R) ≈ 2.8 w for R = 18 m,
    w = 5 m), so the slab reached 12 m past a 10 m window. The pass is
    contiguous from the window (a floor fully outside ends it), so a child
    passing near the parent elsewhere is never touched; the parent query
    window grows with the examined ring's distance from the junction.
    ``other`` is the child's judging envelope and ``level`` its judging level
    (hardening PR-5: the floor-lowered parent at ``CHILD_JUDGE_LEVEL``)."""
    lo, hi = window
    r = own_rings.shape[0]
    away = junction.child_end == "start"  # the child continues past hi (start) or before lo (end)
    intervals = range(hi - 1, r - 1) if away else range(lo - 1, -1, -1)
    jn = (floor_edge + 1) % own_rings.shape[1]
    for i in intervals:
        corners = np.stack(
            [
                own_rings[i, floor_edge],
                own_rings[i, jn],
                own_rings[i + 1, floor_edge],
                own_rings[i + 1, jn],
            ]
        )
        reach = float(
            max(np.linalg.norm(own.centers[[i, i + 1]] - junction.point, axis=1).max(), 0.0)
        )
        other_window = other.ring_window(junction.point, reach + width)
        kind = _floor_quad_kind(corners, other, other_window, tol, level=level)
        if kind == "OUTSIDE":
            break
        if mask[i, floor_edge]:
            continue
        if kind == "INSIDE":
            mask[i, floor_edge] = True
            continue
        inside = other.signed_distance(corners, other_window) <= level
        clip = _clip_floor_quad(
            corners, inside, other, other_window, tol, i, floor_edge, junction.node_id, level=level
        )
        if clip is None:
            mask[i, floor_edge] = True
        else:
            clips.append(clip)


def junction_report(
    junctions: list[Junction],
    cuts: list[JunctionCut],
    cap_cuts: list[CapCut] | None = None,
    mouth_caps: list[CapCut] | None = None,
) -> dict[str, Any]:
    """The report block of one builder: every declared junction with the
    triangles this builder omitted on the sides it owns (a side swept by the
    other builder reports 0 here and its own count there)."""
    by_type: dict[str, int] = {}
    for j in junctions:
        by_type[j.type] = by_type.get(j.type, 0) + 1
    openings: list[dict[str, Any]] = []
    for j in junctions:
        parent_cuts = [c for c in cuts if c.junction is j and c.side == "PARENT"]
        child_cuts = [c for c in cuts if c.junction is j and c.side == "CHILD"]
        # hardening PR-5: a clipped parent quad's two original triangles are
        # not emitted as-is either (their outside-child remainder is), so
        # they count as removed, exactly like the child's clipped quads
        parent_clipped = sum(c.clipped_wall_quads for c in parent_cuts)
        parent_unclipped = sum(c.unclipped_wall_quads for c in parent_cuts)
        parent_replacement = sum(c.replacement_triangles for c in parent_cuts)
        parent = sum(2 * c.removed_quads for c in parent_cuts) + 2 * parent_clipped
        # a clipped floor quad's two original triangles are not emitted as-is
        # either (their outside remainder is re-emitted as replacement
        # triangles), so they count as removed — same meaning as before for
        # every whole-quad omission
        clipped_quads = sum(c.clipped_floor_quads for c in child_cuts)
        clipped_walls = sum(c.clipped_wall_quads for c in child_cuts)
        unclipped_walls = sum(c.unclipped_wall_quads for c in child_cuts)
        sills = sum(c.sill_triangles for c in child_cuts)
        no_sill = sum(cl.chords_without_sill for c in child_cuts for cl in c.floor_clips)
        replacement = sum(c.replacement_triangles for c in child_cuts)
        child = sum(2 * c.removed_quads for c in child_cuts) + 2 * (clipped_quads + clipped_walls)
        # Phase 20D.2: the parent's END CAP where the child occupies it (a
        # crosscut station on a drift extremity); omitted + clipped fan
        # triangles are not emitted as-is, so they count as removed
        caps = [c for c in (cap_cuts or []) if c.junction is j]
        cap_omitted = sum(c.omitted_triangles for c in caps)
        cap_clipped = sum(c.clipped_triangles for c in caps)
        cap_replacement = sum(c.replacement_triangles for c in caps)
        # Phase 20D.2.1: the child's OPEN end ring outside the parent (a
        # drift-extremity L-junction) carries a mouth cap: kept whole fans
        # plus the clipped remainders; these triangles are ADDED (they never
        # existed in the render), so they are not "removed"
        mouths = [c for c in (mouth_caps or []) if c.junction is j]
        mouth_emitted = sum(
            int(c.omit.shape[0])
            - c.omitted_triangles
            - c.clipped_triangles
            + c.replacement_triangles
            for c in mouths
        )
        mouth_clipped = sum(c.clipped_triangles for c in mouths)
        spans = [c.cut_chainage for c in parent_cuts if c.cut_chainage is not None]
        openings.append(
            {
                **j.to_dict(),
                "parentRemovedTriangles": int(parent),
                # hardening PR-4 (W1b, additive): the doorway's footprint along
                # the PARENT centerline (chainage of the first / last interval
                # that lost a quad) and how many intervals the contiguous
                # extension cut beyond the nominal window
                "parentCutChainage": (
                    [min(sp[0] for sp in spans), max(sp[1] for sp in spans)] if spans else None
                ),
                "parentExtensionIntervals": int(sum(c.extension_intervals for c in parent_cuts)),
                # hardening PR-5 (additive): parent quads clipped at the child's
                # judging surface, the ones kept whole for want of a
                # representable boundary, and the remainder triangles emitted
                "parentClippedWallQuads": int(parent_clipped),
                "parentUnclippedWallQuads": int(parent_unclipped),
                "parentReplacementTriangles": int(parent_replacement),
                "parentCapOmittedTriangles": int(cap_omitted),
                "parentCapClippedTriangles": int(cap_clipped),
                "parentCapReplacementTriangles": int(cap_replacement),
                # Phase 20D.1.1 mouth contract: the parent's vertical wall must
                # open (> 0 where this builder owns the parent) and its floor
                # must stay (always 0)
                "parentWallTriangles": int(sum(2 * c.removed_wall_quads for c in parent_cuts)),
                "parentFloorTriangles": int(sum(2 * c.removed_floor_quads for c in parent_cuts)),
                "childRemovedTriangles": int(child),
                # Phase 20D.1.2 child-floor boundary clipping (additive)
                "childClippedFloorQuads": int(clipped_quads),
                "childClippedFloorTriangles": int(2 * clipped_quads),
                "childReplacementTriangles": int(replacement),
                # hardening PR-2 (H0 §3.4, additive): straddling wall / roof
                # quads clipped at the parent boundary, the ones the chord clip
                # could not represent (kept whole), and the sill triangles that
                # close the floor seam between the clipped child floor and the
                # parent floor edge
                "childClippedWallQuads": int(clipped_walls),
                "childUnclippedWallQuads": int(unclipped_walls),
                "childSillTriangles": int(sills),
                "childChordsWithoutSill": int(no_sill),
                # Phase 20D.2.1 (additive): the child mouth cap emitted on the
                # rock-facing part of its OPEN end ring (0 at a T-junction)
                "childMouthCapTriangles": int(mouth_emitted),
                "childMouthCapClippedTriangles": int(mouth_clipped),
                "removedTriangles": int(parent + child + cap_omitted + cap_clipped),
            }
        )
    return {
        "count": len(junctions),
        "byType": {t: by_type[t] for t in JUNCTION_TYPES if t in by_type},
        "openedEndpointCount": sum(1 for o in openings if o["removedTriangles"] > 0),
        "removedTriangles": int(sum(o["removedTriangles"] for o in openings)),
        "openings": openings,
    }


__all__ = [
    "CHILD_JUDGE_FLOOR_DROP_WIDTHS",
    "CHILD_JUDGE_LEVEL",
    "CLIP_BISECTION_ITERATIONS",
    "CLIP_CHORD_SAMPLES",
    "CLIP_MAX_SUBDIVISION_DEPTH",
    "CLIP_VERTEX_MERGE_DISTANCE",
    "JUNCTION_RING_SPACING_FRACTION",
    "JUNCTION_SURFACE_TOLERANCE_FRACTION",
    "JUNCTION_TYPES",
    "JUNCTION_WINDOW_WIDTHS",
    "MOUTH_CAP_MIN_AREA_M2",
    "MOUTH_CAP_VERTEX_MERGE_M",
    "PARENT_EXTENSION_MAX_WIDTHS",
    "PARENT_JUDGE_FLOOR_DROP_TOLERANCES",
    "RAMP_TUBE_ID",
    "RENDER_MIN_AREA_M2",
    "RENDER_VERTEX_MERGE_M",
    "SILL_MAX_PLAN_DISTANCE_WIDTHS",
    "SILL_STATION_FRACTION_OF_TOL",
    "CapClip",
    "CapCut",
    "FloorClip",
    "Junction",
    "JunctionClipConflictError",
    "JunctionClipTopologyError",
    "JunctionCut",
    "TubeEnvelope",
    "cut_cap",
    "cut_mouth_cap",
    "cut_tube",
    "find_junctions",
    "junction_report",
    "merge_cap_cut",
    "merge_parent_cut",
]
