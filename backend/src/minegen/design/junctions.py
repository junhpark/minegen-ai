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
    - child quads whose four vertices are inside-or-on the parent's swept
      envelope (the child's intruding tube, including its coincident floor
      and roof — the parent keeps those surfaces), and
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


@dataclass
class JunctionCut:
    """Quads (ring interval × profile edge) omitted from ONE tube's render
    mesh for one junction, with the reason recorded for the report."""

    junction: Junction
    side: Literal["PARENT", "CHILD"]
    mask: BoolArray  # (R-1, K) True = omit
    window_rings: tuple[int, int]
    #: this tube's floor edge and two vertical wall edges (profile geometry)
    floor_edge: int = -1
    wall_edges: tuple[int, int] = (-1, -1)

    @property
    def removed_quads(self) -> int:
        return int(self.mask.sum())

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
    coincident floor / roof). Only quads whose rings lie inside the window
    are examined; everything else is untouched by construction."""
    radius = JUNCTION_WINDOW_WIDTHS * width
    tol = JUNCTION_SURFACE_TOLERANCE_FRACTION * width
    r, k, _ = own_rings.shape
    mask = np.zeros((r - 1, k), dtype=bool)
    floor_edge = floor_edge_index(own.shape)
    walls = wall_edge_indices(own.shape)
    lo, hi = own.ring_window(junction.point, radius)
    other_window = other.ring_window(junction.point, radius + width)
    if hi - lo < 2:
        return JunctionCut(junction, side, mask, (lo, hi), floor_edge, walls)
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
        omit = np.all(sd <= tol, axis=2)
    mask[intervals] = omit
    return JunctionCut(junction, side, mask, (lo, hi), floor_edge, walls)


def junction_report(junctions: list[Junction], cuts: list[JunctionCut]) -> dict[str, Any]:
    """The report block of one builder: every declared junction with the
    triangles this builder omitted on the sides it owns (a side swept by the
    other builder reports 0 here and its own count there)."""
    by_type: dict[str, int] = {}
    for j in junctions:
        by_type[j.type] = by_type.get(j.type, 0) + 1
    openings: list[dict[str, Any]] = []
    for j in junctions:
        parent_cuts = [c for c in cuts if c.junction is j and c.side == "PARENT"]
        parent = sum(2 * c.removed_quads for c in parent_cuts)
        child = sum(2 * c.removed_quads for c in cuts if c.junction is j and c.side == "CHILD")
        openings.append(
            {
                **j.to_dict(),
                "parentRemovedTriangles": int(parent),
                # Phase 20D.1.1 mouth contract: the parent's vertical wall must
                # open (> 0 where this builder owns the parent) and its floor
                # must stay (always 0)
                "parentWallTriangles": int(sum(2 * c.removed_wall_quads for c in parent_cuts)),
                "parentFloorTriangles": int(sum(2 * c.removed_floor_quads for c in parent_cuts)),
                "childRemovedTriangles": int(child),
                "removedTriangles": int(parent + child),
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
    "JUNCTION_RING_SPACING_FRACTION",
    "JUNCTION_SURFACE_TOLERANCE_FRACTION",
    "JUNCTION_TYPES",
    "JUNCTION_WINDOW_WIDTHS",
    "PARENT_QUAD_OVERLAP_MIN",
    "PARENT_QUAD_SAMPLE_FRACTIONS",
    "RAMP_TUBE_ID",
    "Junction",
    "JunctionCut",
    "TubeEnvelope",
    "cut_tube",
    "find_junctions",
    "junction_report",
]
