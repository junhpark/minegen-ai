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
    - child NON-FLOOR quads whose four vertices are inside-or-on the parent's
      swept envelope (the child's intruding tube, including its coincident
      roof — the parent keeps those surfaces),
    - child FLOOR quads: fully inside-or-on the parent → omitted; fully
      outside → emitted unchanged; STRADDLING the parent boundary → only the
      inside-or-on portion is removed and the outside remainder is emitted
      in its place (Phase 20D.1.2 typed local child-floor boundary
      clipping). The child profile floor is ONE edge spanning the whole
      tunnel width, so at a shallow turnout a floor quad reaches from inside
      the parent to outside it; the whole-quad rule kept every such quad and
      left a false floating floor slab across the parent (measured 0.7–1.6 m
      above the descending ramp floor at its far edge), while deleting the
      whole quad would open a hole in the legitimate child floor outside the
      parent. The boundary is the SAME tolerance surface the vertex rule
      uses, located by deterministic bisection on the quad's own edges; the
      remainder polygon (convex: a quad cut by one chord, or two corner
      triangles) is fan-triangulated into new render vertices, and
    - parent NON-FLOOR quads whose SURFACE the child excavation occupies
      over a meaningful area — at least ``PARENT_QUAD_OVERLAP_MIN`` of the
      ``PARENT_QUAD_SAMPLE_FRACTIONS``² deterministic surface samples lie
      strictly inside the child's envelope (Phase 20D.1.1). The original
      "all four VERTICES strictly inside" test could never remove a
      vertical wall quad: a wall quad's bottom edge lies on the parent
      floor, and the child floor is welded at (T-junction) or above
      (turnout) that height, so every declared mouth stayed an arch window
      over an intact full-height wall. The parent FLOOR edge is never a
      parent-side cut: it is the doorway's supporting floor;
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

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import numpy.typing as npt

from minegen.design.profile import (
    ProfileShape,
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
#: width: a child vertex within this band of the parent's envelope counts
#: as ON it (coincident floors / roofs are removed from the child, kept on
#: the parent); a parent surface sample must be inside the child's envelope
#: by MORE than this band to count as blocked. 0.02 × 5 m = 0.1 m absorbs
#: the secondary profile's coarser tessellation (≤ 1 % inscribed bias) and
#: the gradient / frame differences of two tangent tubes.
JUNCTION_SURFACE_TOLERANCE_FRACTION = 0.02
#: Phase 20D.1.1 parent-side surface test. A parent quad is judged on a
#: deterministic bilinear grid of INTERIOR surface samples (these fractions
#: along the ring interval × along the profile edge — never the corners,
#: which sit on the parent floor / shared boundaries), and is removed when
#: at least ``PARENT_QUAD_OVERLAP_MIN`` of them lie strictly inside the
#: child: two of the three sample rows / columns, i.e. the child occupies
#: at least two thirds of the quad's surface. For a 2.5 m wall this opens
#: the wall while the child floor sits up to ≈ 1.15 m above the parent
#: floor (sill), and keeps it once the child floor is higher than that —
#: an area rule of the intersection, not a doorway size, a player height
#: or a hard-coded edge. Not stochastic, not a mesh distance, window-local.
PARENT_QUAD_SAMPLE_FRACTIONS: tuple[float, ...] = (1.0 / 6.0, 0.5, 5.0 / 6.0)
PARENT_QUAD_OVERLAP_MIN = 6
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
        as outside (+inf): the tube does not extend past its rings."""
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
        # beyond the span (only possible at the two window ends): outside
        beyond = ((m == 0) & (tt < 0.0)) | ((m == a.shape[0] - 1) & (tt > 1.0))
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

    @property
    def replacement_triangles(self) -> int:
        return int(sum(max(int(p.shape[0]) - 2, 0) for p in self.polygons))


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

    @property
    def removed_quads(self) -> int:
        return int(self.mask.sum())

    @property
    def clipped_floor_quads(self) -> int:
        return len(self.floor_clips)

    @property
    def replacement_triangles(self) -> int:
        return int(sum(c.replacement_triangles for c in self.floor_clips))

    @property
    def removed_wall_quads(self) -> int:
        return int(self.mask[:, list(self.wall_edges)].sum()) if self.floor_edge >= 0 else 0

    @property
    def removed_floor_quads(self) -> int:
        return int(self.mask[:, self.floor_edge].sum()) if self.floor_edge >= 0 else 0


def _quad_surface_samples(corners: FloatArray) -> FloatArray:
    """Deterministic interior surface samples of quads given as (…, 4, 3)
    corners [ring i vtx j, ring i vtx j+1, ring i+1 vtx j, ring i+1 vtx j+1]:
    the bilinear grid ``PARENT_QUAD_SAMPLE_FRACTIONS`` (along the interval)
    × ``PARENT_QUAD_SAMPLE_FRACTIONS`` (along the edge) → (…, S, 3)."""
    fr = np.asarray(PARENT_QUAD_SAMPLE_FRACTIONS, dtype=np.float64)
    grid_a, grid_b = np.meshgrid(fr, fr, indexing="ij")
    a: FloatArray = grid_a.ravel()
    b: FloatArray = grid_b.ravel()
    w = np.stack([(1 - a) * (1 - b), (1 - a) * b, a * (1 - b), a * b], axis=0)  # (4, S)
    out: FloatArray = np.einsum("...cx,cs->...sx", corners, w)
    return out


def _boundary_crossings(
    other: TubeEnvelope,
    window: tuple[int, int],
    p_in: FloatArray,
    p_out: FloatArray,
    tol: float,
) -> tuple[FloatArray, FloatArray]:
    """Points where the segments ``p_in → p_out`` ((m, 3) each; ``p_in``
    inside-or-on the ``other`` envelope, ``p_out`` outside) cross the SAME
    tolerance surface the vertex rule uses (``sd == tol``), by deterministic
    bisection. Returns the crossing points and their parameters t ∈ (0, 1)."""
    m = int(p_in.shape[0])
    lo = np.zeros(m)
    hi = np.ones(m)
    for _ in range(CLIP_BISECTION_ITERATIONS):
        mid = 0.5 * (lo + hi)
        pts = p_in + mid[:, None] * (p_out - p_in)
        inside = other.signed_distance(pts, window) <= tol
        lo = np.where(inside, mid, lo)
        hi = np.where(inside, hi, mid)
    # the OUTSIDE bracket end: on a continuous boundary it is within 2^-40 of
    # the midpoint; where the parent envelope ends discontinuously (its
    # terminal ring: sd jumps from a finite inside value to +inf) the crossing
    # then sits on the outside side of the terminal plane, so a chord between
    # two such crossings never samples the inside value of the plane itself
    t = hi
    return p_in + t[:, None] * (p_out - p_in), t


def _dedupe_loop(poly: list[FloatArray], par: list[FloatArray]) -> tuple[FloatArray, FloatArray]:
    """Drop consecutive (cyclic) vertices closer than ``CLIP_VERTEX_MERGE_DISTANCE``."""
    keep_p: list[FloatArray] = []
    keep_q: list[FloatArray] = []
    for p, q in zip(poly, par, strict=True):
        if keep_p and float(np.linalg.norm(p - keep_p[-1])) < CLIP_VERTEX_MERGE_DISTANCE:
            continue
        keep_p.append(p)
        keep_q.append(q)
    while (
        len(keep_p) > 1
        and float(np.linalg.norm(keep_p[0] - keep_p[-1])) < CLIP_VERTEX_MERGE_DISTANCE
    ):
        keep_p.pop()
        keep_q.pop()
    q = np.asarray(keep_q, dtype=np.float64)
    return (
        np.asarray(keep_p, dtype=np.float64).reshape(-1, 3),
        q.reshape(len(keep_q), -1) if keep_q else q.reshape(0, 2),
    )


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
) -> list[tuple[list[FloatArray], list[FloatArray]]] | None:
    """Outside-parent loops of one (sub-)quad whose corners ``pts`` (4, 3) /
    ``par`` (4, 2) are in perimeter orientation order with ``out`` flags:
    marching-squares on the corners, crossings by bisection on the quad's
    own edges, the diagonal case decided by the centre sample. Returns None
    when a loop edge is NOT a faithful chord of the boundary (an interior
    sample lies inside the parent: the boundary bends inside the quad, e.g.
    the wall / terminal-plane corner where the parent ends) — the caller
    subdivides."""
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
        xs, ts = _boundary_crossings(other, window, p_in, p_out, tol)
        for n, m in enumerate(mixed):
            cross_pt[m] = xs[n]
            cross_par[m] = q_in[n] + ts[n] * (q_out[n] - q_in[n])
    loops: list[tuple[list[FloatArray], list[FloatArray]]] = []
    diagonal = int(out.sum()) == 2 and bool(out[0] == out[2])
    if diagonal:
        center = pts.mean(axis=0)
        center_out = bool(other.signed_distance(center[None, :], window)[0] > tol)
        if not center_out:
            for m in range(4):
                if out[m]:
                    prev_e = (m - 1) % 4
                    loops.append(
                        (
                            [cross_pt[prev_e], pts[m], cross_pt[m]],
                            [cross_par[prev_e], par[m], cross_par[m]],
                        )
                    )
    if not loops:
        poly: list[FloatArray] = []
        pp: list[FloatArray] = []
        for m in range(4):
            if out[m]:
                poly.append(pts[m])
                pp.append(par[m])
            if m in cross_pt:
                poly.append(cross_pt[m])
                pp.append(cross_par[m])
        loops.append((poly, pp))
    # chord fidelity: every loop edge must stay outside-or-on the parent
    for poly, _ in loops:
        if not _edges_stay(np.stack(poly), other, window, tol, outside=True):
            return None
    return loops


def _edges_stay(
    loop: FloatArray, other: TubeEnvelope, window: tuple[int, int], tol: float, *, outside: bool
) -> bool:
    """Interior samples of every edge of ``loop`` (n, 3) — and of both
    diagonals for a quad — are all outside-or-on (``outside=True``: sd ≥ −tol)
    or all inside-or-on (sd ≤ tol) the parent. A quad whose four corners
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
    sd = other.signed_distance(samples, window)
    return bool(np.all(sd >= -tol)) if outside else bool(np.all(sd <= tol))


def _floor_quad_kind(
    corners: FloatArray, other: TubeEnvelope, window: tuple[int, int], tol: float
) -> str:
    """'INSIDE' (omit whole), 'OUTSIDE' (keep unchanged) or 'MIXED' (clip) for
    one child floor quad given as [P00, P01, P10, P11]: the four corners AND
    interior samples of the quad's edges / diagonals must agree — a quad
    whose corners all lie outside can still be crossed by the parent's
    wall / terminal-plane corner, and one whose corners all lie inside-or-on
    can hide an outside pocket."""
    sd = other.signed_distance(corners, window)
    inside = sd <= tol
    loop = corners[[0, 2, 3, 1]]  # perimeter orientation order
    if bool(inside.all()):
        return "INSIDE" if _edges_stay(loop, other, window, tol, outside=False) else "MIXED"
    if not bool(inside.any()):
        return "OUTSIDE" if _edges_stay(loop, other, window, tol, outside=True) else "MIXED"
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
) -> FloorClip | None:
    """The outside-parent remainder of ONE straddling floor quad.
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
    order = (0, 2, 3, 1)  # builder corner order → perimeter orientation order
    top = ~inside[list(order)]
    polygons: list[FloatArray] = []
    pars: list[FloatArray] = []
    stack: list[tuple[float, float, float, float, int]] = [(0.0, 1.0, 0.0, 1.0, 0)]
    while stack:
        s0, s1, u0, u1, depth = stack.pop()
        par = np.array([[s0, u0], [s1, u0], [s1, u1], [s0, u1]], dtype=np.float64)
        pts = np.stack([_sub_quad_point(corners, float(sv), float(uv)) for sv, uv in par])
        out = other.signed_distance(pts, window) > tol
        faithful = True
        loops: list[tuple[list[FloatArray], list[FloatArray]]] = []
        if not out.any():
            # all corners inside-or-on: nothing to keep — unless the boundary
            # crosses the quad interior (an outside pocket)
            if _edges_stay(pts, other, window, tol, outside=False):
                continue
            faithful = False
        elif out.all():
            if _edges_stay(pts, other, window, tol, outside=True):
                loops = [([*pts], [*par])]
            else:
                faithful = False
        else:
            chords = _chord_loops(pts, par, out, other, window, tol)
            if chords is None:
                faithful = False
            else:
                loops = chords
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
        for poly, pp in loops:
            p_arr, q_arr = _dedupe_loop(poly, pp)
            if p_arr.shape[0] >= 3:
                polygons.append(p_arr)
                pars.append(q_arr)
    if not polygons:
        return None
    return FloorClip(
        interval=interval,
        edge=edge,
        polygons=tuple(polygons),
        params=tuple(pars),
        corners_outside=(bool(top[0]), bool(top[1]), bool(top[2]), bool(top[3])),
        junction_node_id=node_id,
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
) -> list[tuple[FloatArray, FloatArray]]:
    """Outside-``other`` remainder polygons of ONE triangle ``pts`` (3, 3)
    with per-corner weights ``bary`` (3, 3): corners inside-or-on / outside
    decided by the SAME tolerance surface the quad rules use, crossings by
    deterministic bisection on the triangle's own edges, chord fidelity
    checked on the remainder's edges; where a chord is not a faithful piece
    of the boundary the triangle is bisected along its longest edge
    (deterministically, at most ``CLIP_MAX_SUBDIVISION_DEPTH`` times).
    A triangle wholly inside-or-on yields no polygon (omitted)."""
    sd = other.signed_distance(pts, window)
    out = sd > tol
    if not out.any():
        if _edges_stay(pts, other, window, tol, outside=False):
            return []
    elif out.all():
        if _edges_stay(pts, other, window, tol, outside=True):
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
        xs, ts = _boundary_crossings(other, window, p_in, p_out, tol)
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
        p_arr, b_arr = _dedupe_loop(poly, pb)
        if p_arr.shape[0] < 3:
            return []
        if _edges_stay(p_arr, other, window, tol, outside=True):
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
    return _clip_triangle(*first, other, window, tol, node_id, label, depth + 1) + _clip_triangle(
        *second, other, window, tol, node_id, label, depth + 1
    )


def cut_cap(
    corners: FloatArray,
    other: TubeEnvelope,
    junction: Junction,
    end: Literal["start", "end"],
    width: float,
) -> CapCut:
    """Omit / clip the fan triangles of ONE end cap (``corners`` (K, 3, 3) in
    the emitted winding: apex first) against the CHILD envelope ``other`` of
    a declared junction. Same window, tolerance and classification as the
    child floor quads: inside-or-on → omit, outside → keep, straddling →
    clipped remainder. A cap the child does not reach comes back empty."""
    radius = JUNCTION_WINDOW_WIDTHS * width
    tol = JUNCTION_SURFACE_TOLERANCE_FRACTION * width
    k = int(corners.shape[0])
    omit = np.zeros(k, dtype=bool)
    clips: dict[int, CapClip] = {}
    window = other.ring_window(junction.point, radius + width)
    if window[1] - window[0] < 2:
        return CapCut(junction, end, omit, clips)
    sd = other.signed_distance(corners.reshape(-1, 3), window).reshape(k, 3)
    inside = sd <= tol
    ident = np.eye(3, dtype=np.float64)
    for t in range(k):
        pts = corners[t]
        if bool(inside[t].all()) and _edges_stay(pts, other, window, tol, outside=False):
            omit[t] = True
            continue
        if not bool(inside[t].any()) and _edges_stay(pts, other, window, tol, outside=True):
            continue
        loops = _clip_triangle(pts, ident, other, window, tol, junction.node_id, t)
        if not loops:
            omit[t] = True
            continue
        clips[t] = CapClip(
            triangle=t,
            polygons=tuple(p for p, _ in loops),
            bary=tuple(b for _, b in loops),
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
    cut = cut_cap(corners, parent, junction, end, width)
    if cut.omitted_triangles == int(corners.shape[0]):
        return None
    # the remainder is emitted as float32 render geometry: a crossing that
    # lands within float32 resolution of a fan corner would leave a zero-area
    # sliver (a degenerate triangle covers no surface, so dropping it can
    # open nothing); vertices closer than MOUTH_CAP_VERTEX_MERGE_M are merged
    # and pieces below MOUTH_CAP_MIN_AREA_M2 are dropped
    for t, clip in list(cut.clips.items()):
        polys: list[FloatArray] = []
        bars: list[FloatArray] = []
        for poly, bary in zip(clip.polygons, clip.bary, strict=True):
            cleaned = _clean_render_polygon(poly, bary)
            if cleaned is not None:
                polys.append(cleaned[0])
                bars.append(cleaned[1])
        if polys:
            cut.clips[t] = CapClip(clip.triangle, tuple(polys), tuple(bars), clip.junction_node_id)
        else:
            del cut.clips[t]
            cut.omit[t] = True
    if cut.omitted_triangles == int(corners.shape[0]):
        return None
    return cut


#: Phase 20D.2.1: render-scale cleaning of a mouth-cap remainder polygon —
#: float32 positions at a few hundred metres resolve ≈ 1.5e-5 m, so a
#: crossing within 1 mm of a corner is a degenerate sliver, never a surface
MOUTH_CAP_VERTEX_MERGE_M = 1e-3
MOUTH_CAP_MIN_AREA_M2 = 1e-6


def _clean_render_polygon(
    poly: FloatArray, bary: FloatArray
) -> tuple[FloatArray, FloatArray] | None:
    """Merge consecutive vertices closer than ``MOUTH_CAP_VERTEX_MERGE_M``,
    drop interior vertices whose fan triangle (from vertex 0) is degenerate,
    and drop the polygon when fewer than three vertices or less than
    ``MOUTH_CAP_MIN_AREA_M2`` remain. The surface change is below float32
    resolution of the emitted geometry."""
    keep_p: list[FloatArray] = []
    keep_b: list[FloatArray] = []
    for q in range(int(poly.shape[0])):
        if keep_p and float(np.linalg.norm(poly[q] - keep_p[-1])) < MOUTH_CAP_VERTEX_MERGE_M:
            continue
        keep_p.append(poly[q])
        keep_b.append(bary[q])
    while (
        len(keep_p) > 1 and float(np.linalg.norm(keep_p[-1] - keep_p[0])) < MOUTH_CAP_VERTEX_MERGE_M
    ):
        keep_p.pop()
        keep_b.pop()
    # fan-degenerate interior vertices (collinear with vertex 0 and a neighbour)
    changed = True
    while changed and len(keep_p) >= 3:
        changed = False
        for i in range(1, len(keep_p) - 1):
            area = 0.5 * float(
                np.linalg.norm(np.cross(keep_p[i] - keep_p[0], keep_p[i + 1] - keep_p[0]))
            )
            if area < MOUTH_CAP_MIN_AREA_M2:
                del keep_p[i]
                del keep_b[i]
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
    if total < MOUTH_CAP_MIN_AREA_M2:
        return None
    return p_arr, np.stack(keep_b)


def cut_tube(
    own: TubeEnvelope,
    own_rings: FloatArray,
    other: TubeEnvelope,
    junction: Junction,
    side: Literal["PARENT", "CHILD"],
    width: float,
) -> JunctionCut:
    """Mask of this tube's quads to omit at ``junction`` against the OTHER
    tube's envelope. PARENT side (Phase 20D.1.1): non-floor quads whose
    surface the child occupies over a meaningful area (the blocking wall
    and the roof above the mouth); the floor edge is never cut. CHILD side:
    quads whose four vertices are inside-or-on the parent (intruding shell,
    coincident roof) are omitted; a FLOOR quad with some corners inside-or-on
    and some outside is CLIPPED at the parent boundary (Phase 20D.1.2,
    ``floor_clips``) instead of being kept or dropped whole. Only quads whose
    rings lie inside the window are examined; everything else is untouched
    by construction."""
    radius = JUNCTION_WINDOW_WIDTHS * width
    tol = JUNCTION_SURFACE_TOLERANCE_FRACTION * width
    r, k, _ = own_rings.shape
    mask = np.zeros((r - 1, k), dtype=bool)
    floor_edge = floor_edge_index(own.shape)
    walls = wall_edge_indices(own.shape)
    lo, hi = own.ring_window(junction.point, radius)
    other_window = other.ring_window(junction.point, radius + width)
    clips: list[FloorClip] = []
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
    if side == "PARENT":
        samples = _quad_surface_samples(v)  # (I, K, S, 3)
        n_samples = samples.shape[2]
        sd = other.signed_distance(samples.reshape(-1, 3), other_window)
        inside = (sd.reshape(len(intervals), k, n_samples) < -tol).sum(axis=2)
        omit = inside >= PARENT_QUAD_OVERLAP_MIN
        omit[:, floor_edge] = False  # the parent floor supports the doorway
    else:
        sd = other.signed_distance(v.reshape(-1, 3), other_window).reshape(len(intervals), k, 4)
        inside_v = sd <= tol
        omit = np.all(inside_v, axis=2)
        # Phase 20D.1.2: the FLOOR edge is never decided by its corners alone —
        # INSIDE quads are omitted, OUTSIDE quads kept, MIXED quads clipped
        for idx in range(len(intervals)):
            corners = v[idx, floor_edge]
            kind = _floor_quad_kind(corners, other, other_window, tol)
            omit[idx, floor_edge] = kind == "INSIDE"
            if kind != "MIXED":
                continue
            clip = _clip_floor_quad(
                corners,
                inside_v[idx, floor_edge],
                other,
                other_window,
                tol,
                int(intervals[idx]),
                floor_edge,
                junction.node_id,
            )
            if clip is None:
                omit[idx, floor_edge] = True  # measure-zero remainder: nothing to keep
            else:
                clips.append(clip)
    mask[intervals] = omit
    if side == "CHILD":
        _extend_child_floor_pass(
            own, own_rings, other, junction, width, tol, floor_edge, (lo, hi), mask, clips
        )
    return JunctionCut(junction, side, mask, (lo, hi), floor_edge, walls, clips)


def _extend_child_floor_pass(
    own: TubeEnvelope,
    own_rings: FloatArray,
    other: TubeEnvelope,
    junction: Junction,
    width: float,
    tol: float,
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
    window grows with the examined ring's distance from the junction."""
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
        kind = _floor_quad_kind(corners, other, other_window, tol)
        if kind == "OUTSIDE":
            break
        if mask[i, floor_edge]:
            continue
        if kind == "INSIDE":
            mask[i, floor_edge] = True
            continue
        inside = other.signed_distance(corners, other_window) <= tol
        clip = _clip_floor_quad(
            corners, inside, other, other_window, tol, i, floor_edge, junction.node_id
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
        parent = sum(2 * c.removed_quads for c in parent_cuts)
        # a clipped floor quad's two original triangles are not emitted as-is
        # either (their outside remainder is re-emitted as replacement
        # triangles), so they count as removed — same meaning as before for
        # every whole-quad omission
        clipped_quads = sum(c.clipped_floor_quads for c in child_cuts)
        replacement = sum(c.replacement_triangles for c in child_cuts)
        child = sum(2 * c.removed_quads for c in child_cuts) + 2 * clipped_quads
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
        openings.append(
            {
                **j.to_dict(),
                "parentRemovedTriangles": int(parent),
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
    "PARENT_QUAD_OVERLAP_MIN",
    "PARENT_QUAD_SAMPLE_FRACTIONS",
    "RAMP_TUBE_ID",
    "CapClip",
    "CapCut",
    "FloorClip",
    "Junction",
    "JunctionClipTopologyError",
    "JunctionCut",
    "TubeEnvelope",
    "cut_cap",
    "cut_mouth_cap",
    "cut_tube",
    "find_junctions",
    "junction_report",
]
