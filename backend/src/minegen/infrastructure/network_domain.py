"""Shared infrastructure network domain (rule 93).

MineNetwork integrity validation, owning-centerline resolution, backend
``NetworkLocation`` sampling and physical network-geodesic distance are
SHARED infrastructure-domain responsibilities: ``CommunicationBuilder``
(Phase 11) and ``SensorBuilder`` (Phase 12) both consume this component and
never independently reimplement these engineering calculations.

The domain deliberately knows NOTHING about communication coverage
thresholds, backhaul semantics, sensor monitoring thresholds, solver policy
or UI concepts — those belong to the per-phase strategies and builders.

All failures are typed: ``DomainValidationError`` carries the exact reason
message a builder should serialize, and ``UnsupportedEdgeTypeError`` lets
each builder emit its own phase token (``UNSUPPORTED_COMMUNICATION_EDGE_TYPE``
/ ``UNSUPPORTED_SENSOR_EDGE_TYPE``) for RAISE/SHAFT edges. Malformed input
never escapes as KeyError/IndexError/ValueError.
"""

from __future__ import annotations

import heapq
import math
from typing import Any

import numpy as np

from minegen.core.artifacts import RAMP_OWNING_ARTIFACTS
from minegen.infrastructure.models import CandidateSite, DemandPoint

LENGTH_SYNC_TOLERANCE = 1e-6  # m — recomputed centerline vs edge.length3d
ENDPOINT_TOLERANCE = 1e-6  # m — centerline ends vs from/to node positions

_SUPPORTED_EDGE_TYPES = ("RAMP", "DRIFT", "CROSSCUT")
_OWNING_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "RAMP": RAMP_OWNING_ARTIFACTS,
    "DRIFT": ("levels.json",),
    "CROSSCUT": ("levels.json",),
}

SampleRow = tuple[str, str | None, str | None, float | None, tuple[float, float, float]]


class DomainValidationError(Exception):
    """Typed domain failure; ``str(exc)`` is the serializable reason."""


class UnsupportedEdgeTypeError(Exception):
    """A physically unsupported edge type (RAISE/SHAFT) was encountered."""

    def __init__(self, edge_id: str, edge_type: str) -> None:
        super().__init__(edge_id, edge_type)
        self.edge_id = edge_id
        self.edge_type = edge_type


class EdgeGeometry:
    """Resolved owning-centerline geometry for one physical edge."""

    def __init__(self, points: np.ndarray) -> None:
        self.points = points
        seg = np.linalg.norm(np.diff(points, axis=0), axis=1)
        self.cum = np.concatenate([[0.0], np.cumsum(seg)])
        self.length = float(self.cum[-1])

    def position_at(self, chainage: float) -> tuple[float, float, float]:
        c = min(max(chainage, 0.0), self.length)
        i = int(np.searchsorted(self.cum, c, side="right") - 1)
        i = min(max(i, 0), len(self.cum) - 2)
        span = self.cum[i + 1] - self.cum[i]
        t = 0.0 if span <= 0 else (c - self.cum[i]) / span
        p = self.points[i] + (self.points[i + 1] - self.points[i]) * t
        return (float(p[0]), float(p[1]), float(p[2]))


class InfrastructureNetworkDomain:
    """Validated physical MineNetwork with geodesic-distance machinery."""

    def __init__(
        self,
        nodes: dict[str, dict[str, Any]],
        edges_by_id: dict[str, dict[str, Any]],
        node_order: list[str],
        edge_order: list[str],
        portal_id: str,
        geometries: dict[str, EdgeGeometry],
        node_index: dict[str, int],
        node_dist: np.ndarray,
    ) -> None:
        self.nodes = nodes
        self.edges_by_id = edges_by_id
        self.node_order = node_order
        self.edge_order = edge_order
        self.portal_id = portal_id
        self.geometries = geometries
        self.node_index = node_index
        self.node_dist = node_dist

    # ------------------------------------------------------------------ #
    @classmethod
    def build(
        cls,
        network_payload: dict[str, Any],
        smoothed_payload: dict[str, Any],
        levels_payload: dict[str, Any],
    ) -> InfrastructureNetworkDomain:
        """§11 shared gates. Raises typed errors; never Key/Index/ValueError."""
        if network_payload.get("status") != "SUCCESS":
            raise DomainValidationError(
                f"prerequisite network artifact status {network_payload.get('status')!r} "
                "is not consumable"
            )
        validation = network_payload.get("validation") or {}
        if not (validation.get("connected") and validation.get("synchronized")):
            raise DomainValidationError(
                "network validation is not connected+synchronized — infrastructure "
                "planning requires a physically connected, synchronized MineNetwork"
            )

        node_list, edge_list = cls._validate_structure(network_payload)
        node_ids = [n["id"] for n in node_list]
        if len(set(node_ids)) != len(node_ids):
            dup = sorted({i for i in node_ids if node_ids.count(i) > 1})[:3]
            raise DomainValidationError(f"duplicate network node ids: {dup}")
        edge_ids = [e["id"] for e in edge_list]
        if len(set(edge_ids)) != len(edge_ids):
            dup = sorted({i for i in edge_ids if edge_ids.count(i) > 1})[:3]
            raise DomainValidationError(f"duplicate network edge ids: {dup}")
        portal_ids = [n["id"] for n in node_list if n.get("type") == "PORTAL"]
        if len(portal_ids) != 1:
            raise DomainValidationError(f"expected exactly one PORTAL node, got {len(portal_ids)}")
        nodes = {n["id"]: n for n in node_list}
        for e in edge_list:
            if e.get("type") not in _SUPPORTED_EDGE_TYPES:
                raise UnsupportedEdgeTypeError(str(e.get("id")), str(e.get("type")))
            for endpoint in (e.get("fromNode"), e.get("toNode")):
                if endpoint not in nodes:
                    raise DomainValidationError(
                        f"edge {e['id']} references missing node {endpoint}"
                    )

        geometries: dict[str, EdgeGeometry] = {}
        for e in edge_list:
            geometries[e["id"]] = cls._resolve_geometry(e, nodes, smoothed_payload, levels_payload)

        node_order = sorted(nodes)
        edge_order = sorted(edge_ids)
        node_index = {nid: i for i, nid in enumerate(node_order)}
        node_dist = cls._all_pairs_node_distance(node_order, node_index, edge_list)
        if not np.all(np.isfinite(node_dist)):
            raise DomainValidationError("network is not physically connected (infinite geodesic)")
        return cls(
            nodes=nodes,
            edges_by_id={e["id"]: e for e in edge_list},
            node_order=node_order,
            edge_order=edge_order,
            portal_id=portal_ids[0],
            geometries=geometries,
            node_index=node_index,
            node_dist=node_dist,
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    def _validate_structure(
        network_payload: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Structural gate BEFORE any keyed access (typed-FAILED contract):
        malformed shapes become DomainValidationError, never
        KeyError/TypeError/ValueError."""

        def _non_empty_str(v: Any) -> bool:
            return isinstance(v, str) and len(v) > 0

        node_list = network_payload.get("nodes")
        if not isinstance(node_list, list):
            raise DomainValidationError("network nodes is not a list")
        for i, n in enumerate(node_list):
            if not isinstance(n, dict):
                raise DomainValidationError(f"network node #{i} is not an object")
            if not _non_empty_str(n.get("id")):
                raise DomainValidationError(f"network node #{i} is missing a valid id")
            pos = n.get("position")
            if not isinstance(pos, (list, tuple)) or len(pos) != 3:
                raise DomainValidationError(f"node {n['id']} position is not a 3-coordinate list")
            for v in pos:
                if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
                    raise DomainValidationError(
                        f"node {n['id']} position has a non-finite or non-numeric coordinate"
                    )
        edge_list = network_payload.get("edges")
        if not isinstance(edge_list, list):
            raise DomainValidationError("network edges is not a list")
        for i, e in enumerate(edge_list):
            if not isinstance(e, dict):
                raise DomainValidationError(f"network edge #{i} is not an object")
            if not _non_empty_str(e.get("id")):
                raise DomainValidationError(f"network edge #{i} is missing a valid id")
            for field in ("fromNode", "toNode", "type"):
                if not _non_empty_str(e.get(field)):
                    raise DomainValidationError(
                        f"edge {e['id']} field {field} is not a non-empty string"
                    )
            length = e.get("length3d")
            if (
                not isinstance(length, (int, float))
                or isinstance(length, bool)
                or not math.isfinite(length)
                or length <= 0
            ):
                raise DomainValidationError(f"edge {e['id']} has non-positive length3d {length!r}")
            ref = e.get("geometryRef")
            if not isinstance(ref, dict):
                raise DomainValidationError(f"edge {e['id']} geometryRef is not an object")
        return node_list, edge_list

    # ------------------------------------------------------------------ #
    @staticmethod
    def _resolve_geometry(
        e: dict[str, Any],
        nodes: dict[str, dict[str, Any]],
        smoothed_payload: dict[str, Any],
        levels_payload: dict[str, Any],
    ) -> EdgeGeometry:
        expected_artifacts = _OWNING_ARTIFACTS[e["type"]]
        ref = e.get("geometryRef")
        if not isinstance(ref, dict):
            raise DomainValidationError(f"edge {e['id']} geometryRef is not an object")
        artifact = ref.get("artifact")
        if artifact not in expected_artifacts:
            raise DomainValidationError(
                f"edge {e['id']} of type {e['type']} must be owned by "
                f"{' or '.join(expected_artifacts)}, geometryRef points to {artifact!r}"
            )
        raw_index = ref.get("segmentIndex")
        if not isinstance(raw_index, int) or isinstance(raw_index, bool) or raw_index < 0:
            raise DomainValidationError(
                f"edge {e['id']} segmentIndex {raw_index!r} is not a non-negative integer"
            )
        is_ramp = artifact in RAMP_OWNING_ARTIFACTS
        owners = smoothed_payload.get("segments") if is_ramp else levels_payload.get("developments")
        container = "effectiveCenterline" if is_ramp else "centerline"
        if not isinstance(owners, list) or raw_index >= len(owners):
            count = len(owners) if isinstance(owners, list) else 0
            raise DomainValidationError(
                f"edge {e['id']} segmentIndex {raw_index} is out of range for "
                f"{artifact} ({count} entries)"
            )
        owner = owners[raw_index]
        centerline = owner.get(container) if isinstance(owner, dict) else None
        raw_points = centerline.get("points") if isinstance(centerline, dict) else None
        # malformed owning geometry is a typed failure, never an unhandled
        # reshape/conversion exception
        if not isinstance(raw_points, list) or len(raw_points) < 6 or len(raw_points) % 3 != 0:
            raise DomainValidationError(
                f"edge {e['id']} owning centerline is missing, has < 2 points or "
                "is not a flat multiple-of-3 coordinate list"
            )
        try:
            pts = np.asarray(raw_points, dtype=np.float64).reshape(-1, 3)
        except (TypeError, ValueError):
            raise DomainValidationError(
                f"edge {e['id']} owning centerline contains non-numeric values"
            ) from None
        if pts.shape[0] < 2:
            raise DomainValidationError(f"edge {e['id']} owning centerline has < 2 points")
        if not np.all(np.isfinite(pts)):
            raise DomainValidationError(f"edge {e['id']} owning centerline has non-finite points")
        geom = EdgeGeometry(pts)
        if abs(geom.length - float(e["length3d"])) > LENGTH_SYNC_TOLERANCE:
            raise DomainValidationError(
                f"edge {e['id']} owning centerline measures {geom.length:.6f} m but "
                f"the edge declares {float(e['length3d']):.6f} m (> 1e-6 tolerance)"
            )
        # canonical fromNode -> toNode chainage orientation (Phase 07/08
        # contract; verified worst end deviation 1.4e-14 m on the default)
        from_pos = np.asarray(nodes[e["fromNode"]]["position"], dtype=np.float64)
        to_pos = np.asarray(nodes[e["toNode"]]["position"], dtype=np.float64)
        if (
            float(np.linalg.norm(pts[0] - from_pos)) > ENDPOINT_TOLERANCE
            or float(np.linalg.norm(pts[-1] - to_pos)) > ENDPOINT_TOLERANCE
        ):
            raise DomainValidationError(
                f"edge {e['id']} centerline orientation does not match the canonical "
                "fromNode->toNode contract within 1e-6 m"
            )
        return geom

    @staticmethod
    def _all_pairs_node_distance(
        node_order: list[str], node_index: dict[str, int], edge_list: list[dict[str, Any]]
    ) -> np.ndarray:
        n_nodes = len(node_order)
        node_dist = np.full((n_nodes, n_nodes), np.inf, dtype=np.float64)
        adjacency: dict[int, list[tuple[int, float]]] = {i: [] for i in range(n_nodes)}
        for e in edge_list:
            a = node_index[e["fromNode"]]
            b = node_index[e["toNode"]]
            w = float(e["length3d"])
            adjacency[a].append((b, w))
            adjacency[b].append((a, w))
        for src in range(n_nodes):
            dist = node_dist[src]
            dist[src] = 0.0
            heap = [(0.0, src)]
            done = np.zeros(n_nodes, dtype=bool)
            while heap:
                d, u = heapq.heappop(heap)
                if done[u]:
                    continue
                done[u] = True
                for v, w in adjacency[u]:
                    nd = d + w
                    if nd < dist[v]:
                        dist[v] = nd
                        heapq.heappush(heap, (nd, v))
        return node_dist

    # ------------------------------------------------------------------ #
    @property
    def total_network_length3d(self) -> float:
        return float(math.fsum(float(e["length3d"]) for e in self.edges_by_id.values()))

    def sample(self, spacing: float, prefix: str) -> list[SampleRow]:
        """§13/§14 deterministic sampling: every node, plus interior edge
        points at k*spacing strictly inside the edge (endpoints are NODE
        samples, never duplicated). Ordinal starts at 1 in canonical
        fromNode direction."""
        out: list[SampleRow] = []
        for nid in self.node_order:
            p = self.nodes[nid]["position"]
            out.append(
                (
                    f"{prefix}:NODE:{nid}",
                    nid,
                    None,
                    None,
                    (float(p[0]), float(p[1]), float(p[2])),
                )
            )
        for eid in self.edge_order:
            geom = self.geometries[eid]
            k = 1
            while k * spacing < geom.length - 1e-12:
                c = k * spacing
                out.append((f"{prefix}:EDGE:{eid}:P{k}", None, eid, c, geom.position_at(c)))
                k += 1
        return out

    @staticmethod
    def candidates_from_rows(rows: list[SampleRow]) -> list[CandidateSite]:
        return [
            CandidateSite(
                id=rid,
                location_kind="NODE" if nid is not None else "EDGE",
                node_id=nid,
                edge_id=eid,
                chainage_m=ch,
                position=pos,
                eligible=True,
            )
            for rid, nid, eid, ch, pos in rows
        ]

    @staticmethod
    def demands_from_rows(rows: list[SampleRow]) -> list[DemandPoint]:
        return [
            DemandPoint(
                id=rid,
                location_kind="NODE" if nid is not None else "EDGE",
                node_id=nid,
                edge_id=eid,
                chainage_m=ch,
                position=pos,
                weight=1.0,
            )
            for rid, nid, eid, ch, pos in rows
        ]

    # ------------------------------------------------------------------ #
    def _anchors(
        self, nid: str | None, eid: str | None, ch: float | None
    ) -> list[tuple[int, float]]:
        if nid is not None:
            return [(self.node_index[nid], 0.0)]
        assert eid is not None and ch is not None
        e = self.edges_by_id[eid]
        return [
            (self.node_index[e["fromNode"]], float(ch)),
            (self.node_index[e["toNode"]], float(e["length3d"]) - float(ch)),
        ]

    def location_distance(
        self,
        a: tuple[str | None, str | None, float | None],
        b: tuple[str | None, str | None, float | None],
    ) -> float:
        """Exact network-geodesic distance between two locations given as
        (node_id, edge_id, chainage_m) triples. Never Euclidean."""
        best = math.inf
        if a[1] is not None and a[1] == b[1]:  # same edge: direct chainage
            assert a[2] is not None and b[2] is not None
            best = abs(a[2] - b[2])
        for na, oa in self._anchors(*a):
            for nb, ob in self._anchors(*b):
                best = min(best, oa + float(self.node_dist[na, nb]) + ob)
        return best

    def pairwise(self, rows_a: list[SampleRow], rows_b: list[SampleRow]) -> np.ndarray:
        """Network-geodesic distance matrix between two sample-row lists."""

        def pack(rows: list[SampleRow]) -> tuple[np.ndarray, np.ndarray]:
            idx = np.empty((2, len(rows)), dtype=np.int64)
            off = np.empty((2, len(rows)), dtype=np.float64)
            for j, (_rid, nid, eid, ch, _pos) in enumerate(rows):
                anc = self._anchors(nid, eid, ch)
                if len(anc) == 1:
                    anc = [anc[0], anc[0]]
                for k in (0, 1):
                    idx[k, j], off[k, j] = anc[k][0], anc[k][1]
            return idx, off

        ia, oa = pack(rows_a)
        ib, ob = pack(rows_b)
        out = np.full((len(rows_a), len(rows_b)), np.inf, dtype=np.float64)
        for k in (0, 1):
            for m in (0, 1):
                combo = self.node_dist[ia[k]][:, ib[m]] + oa[k][:, None] + ob[m][None, :]
                np.minimum(out, combo, out=out)
        # same-edge direct chainage correction
        by_edge_a: dict[str, list[int]] = {}
        for j, (_rid, _nid, eid, _ch, _pos) in enumerate(rows_a):
            if eid is not None:
                by_edge_a.setdefault(eid, []).append(j)
        for j2, (_rid, _nid, eid, ch, _pos) in enumerate(rows_b):
            if eid is None:
                continue
            for j1 in by_edge_a.get(eid, []):
                direct = abs(float(rows_a[j1][3]) - float(ch))  # type: ignore[arg-type]
                if direct < out[j1, j2]:
                    out[j1, j2] = direct
        return out
