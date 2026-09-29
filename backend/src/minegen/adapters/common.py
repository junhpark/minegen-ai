"""Shared bundle-consumption helpers for every adapter (directive §5–§7).

Everything here reads the bundle through the manifest-driven reader and
validates against the MineExchange DTOs; nothing computes engineering
quantities. The five-state source mapping is decided ONCE here from the
bundle's own omission record plus the adapter's declared consumption.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.adapters.bundle_reader import MineExchangeBundle, require_version
from minegen.adapters.contracts import (
    AdapterAssumption,
    AdapterCoordinateMapping,
    AdapterSourceState,
    SourceState,
)
from minegen.adapters.errors import (
    MineExchangeBundleInvalidError,
    RequiredSourceAbsentError,
    RequiredSourceNotSuccessError,
)
from minegen.exchange.formats.csv_table import read_csv
from minegen.exchange.models import (
    COORDINATE_FRAME,
    ExchangeCapability,
    ExchangeNetwork,
    ExchangeNetworkEdge,
    ExchangeNetworkNode,
    ExchangeTimeline,
)

FloatArray = npt.NDArray[np.float64]

NETWORK_PATH = "topology/network.json"
CENTERLINES_CSV_PATH = "excavations/centerlines.csv"
CENTERLINES_DXF_PATH = "excavations/centerlines.dxf"
ENTITIES_PATH = "excavations/entities.json"
CAPABILITY_PATH = "semantics/capability.json"
MINING_METHOD_PATH = "semantics/mining_method.json"
TIMELINE_PATH = "operations/timeline.json"
CENTERLINES_HEADER = ("entityId", "kind", "levelId", "sequence", "x", "y", "z")
#: the bundle group whose omission the timeline reader consults
TIMELINE_GROUP = "TIMELINE"
#: the ONE active production group per bundle (rule 196: exactly one
#: production omission group / document per bundle — the active method's);
#: an inactive method's group is never listed in the bundle and therefore
#: never in an adapter's sourceStates
PRODUCTION_GROUPS = ("STOPES", "CUT_FILL", "ROOM_PILLAR")
PRODUCTION_DOCUMENTS: dict[str, str] = {
    "STOPES": "production/stopes.json",
    "CUT_FILL": "production/cut_fill.json",
    "ROOM_PILLAR": "production/room_pillar.json",
}

_COMMON = "ADAPTER_COMMON"
MINE_EXCHANGE_1_2 = (1, 2, 0)
MINE_EXCHANGE_1_3 = (1, 3, 0)


def identity_mapping(note: str) -> AdapterCoordinateMapping:
    """No re-framing: the target consumes MineExchange coordinates as they
    are (metres, X east, Y north, Z up, right-handed)."""
    return AdapterCoordinateMapping(
        source_frame=COORDINATE_FRAME,
        target_frame=COORDINATE_FRAME,
        unit="metre",
        unit_factor=1.0,
        handedness="RIGHT_HANDED",
        up_axis="Z",
        transform=None,
        note=note,
    )


def not_provided(kind: str, what: str, *, scope: str = "ALL") -> AdapterAssumption:
    return AdapterAssumption(
        kind=kind,
        state="NOT_PROVIDED",
        value=None,
        unit=None,
        scope=scope,
        source="no MineGen authority (docs/external-adapters.md §7 / §17)",
        user_override=None,
        note=f"{what}: entered by the user in the target application",
    )


# --------------------------------------------------------------------------- #
# five-state source mapping
# --------------------------------------------------------------------------- #

_BUNDLE_REASON_TO_STATE: dict[str, SourceState] = {
    "ARTIFACT_ABSENT": "ARTIFACT_ABSENT",
    "SOURCE_NOT_SUCCESS": "SOURCE_NOT_SUCCESS",
    "NOT_IN_V1": "NOT_EXPORTED_BY_VERSION",
}


def source_state(
    bundle: MineExchangeBundle, group: str, *, consumed: bool, detail_when_available: str
) -> AdapterSourceState:
    """The state of one bundle group for THIS adapter: the bundle's omission
    record decides ARTIFACT_ABSENT / SOURCE_NOT_SUCCESS /
    NOT_EXPORTED_BY_VERSION (its ``NOT_IN_V1``); otherwise the adapter's
    declared consumption decides AVAILABLE / UNSUPPORTED_BY_ADAPTER."""
    om = bundle.omission(group)
    if om is not None:
        state: SourceState = _BUNDLE_REASON_TO_STATE[om.reason_code]
        return AdapterSourceState(
            group=group, state=state, bundle_reason_code=om.reason_code, detail=om.detail
        )
    if consumed:
        return AdapterSourceState(
            group=group, state="AVAILABLE", bundle_reason_code=None, detail=detail_when_available
        )
    return AdapterSourceState(
        group=group,
        state="UNSUPPORTED_BY_ADAPTER",
        bundle_reason_code=None,
        detail="present in the bundle; not consumed by this adapter version",
    )


def present_production_group(bundle: MineExchangeBundle) -> str | None:
    """The production group whose document the bundle CARRIES (the active
    method's), or None (world-only / production not generated)."""
    present = [g for g, path in PRODUCTION_DOCUMENTS.items() if bundle.has(path)]
    if len(present) > 1:
        raise MineExchangeBundleInvalidError(
            f"bundle carries several production documents {present}; exactly one active "
            "production group is the MineExchange contract",
            adapter=_COMMON,
            source_group="PRODUCTION",
        )
    return present[0] if present else None


def production_group_states(
    bundle: MineExchangeBundle, *, consumed: bool, detail_when_available: str
) -> list[AdapterSourceState]:
    """Source states for the production groups: ONLY the group the bundle
    carries (AVAILABLE / UNSUPPORTED_BY_ADAPTER by ``consumed``) or the
    group the bundle records an omission for (its own reason). A group the
    bundle neither carries nor mentions — an INACTIVE method — is not a
    source of this bundle and is never listed (a listed state would claim a
    provenance the bundle does not have)."""
    out: list[AdapterSourceState] = []
    present = present_production_group(bundle)
    for group in PRODUCTION_GROUPS:
        if group == present:
            out.append(
                source_state(
                    bundle, group, consumed=consumed, detail_when_available=detail_when_available
                )
            )
        elif bundle.omission(group) is not None:
            out.append(source_state(bundle, group, consumed=consumed, detail_when_available=""))
    return out


def multi_member_group_state(
    bundle: MineExchangeBundle, group: str, *, present: bool, detail_when_available: str
) -> AdapterSourceState:
    """A group with SEVERAL bundle members (``RENDER_GLB``: the ramp tunnel
    GLB and the development GLB each carry their own omission record). The
    group is AVAILABLE when the adapter consumed at least one member; the
    members the bundle omitted are named in the detail (and are reported as
    typed adapter omissions by the caller). With no member present the
    bundle's own omission record decides, exactly as ``source_state``."""
    if not present:
        return source_state(bundle, group, consumed=True, detail_when_available="")
    omitted = [
        f"{o.source_artifact or o.group}: {o.reason_code}"
        for o in bundle.manifest.omissions
        if o.group == group
    ]
    detail = detail_when_available
    if omitted:
        detail = f"{detail}; omitted members: {', '.join(omitted)}"
    return AdapterSourceState(
        group=group, state="AVAILABLE", bundle_reason_code=None, detail=detail
    )


SHAFT_ENTITY_KINDS = ("SHAFT_SEGMENT", "SHAFT_STATION_ACCESS", "SHAFT")


def shafts_state(
    bundle: MineExchangeBundle, *, consumed: bool, detail_when_available: str
) -> AdapterSourceState:
    """SHAFTS is an OPTIONAL group the bundle records an omission for only
    when a shaft artifact exists and failed / is stale; a mine that declares
    no shaft carries neither a shaft entity nor an omission. Presence is
    therefore decided on the exported entities: no SHAFT entity → the group
    is ARTIFACT_ABSENT for this package (never AVAILABLE by default)."""
    om = bundle.omission("SHAFTS")
    if om is not None:
        return source_state(bundle, "SHAFTS", consumed=consumed, detail_when_available="")
    present = any(e.kind in SHAFT_ENTITY_KINDS for e in bundle.manifest.entities)
    if not present:
        return AdapterSourceState(
            group="SHAFTS",
            state="ARTIFACT_ABSENT",
            bundle_reason_code=None,
            detail="the bundle carries no shaft entity (no shaft declared or planned)",
        )
    return source_state(
        bundle, "SHAFTS", consumed=consumed, detail_when_available=detail_when_available
    )


def version_gap_state(group: str, detail: str) -> AdapterSourceState:
    """A group the consumed MineExchange version cannot carry at all."""
    return AdapterSourceState(
        group=group, state="NOT_EXPORTED_BY_VERSION", bundle_reason_code=None, detail=detail
    )


def require_group(bundle: MineExchangeBundle, group: str, *, adapter: str, why: str) -> None:
    """A required group must be present (typed refusal otherwise, with the
    bundle's own reason carried through)."""
    om = bundle.omission(group)
    if om is None:
        return
    reason = f"bundle group {group} is {om.reason_code} ({om.detail}); {why}"
    if om.reason_code == "SOURCE_NOT_SUCCESS":
        raise RequiredSourceNotSuccessError(reason, adapter=adapter, source_group=group)
    raise RequiredSourceAbsentError(reason, adapter=adapter, source_group=group)


def require_mine_exchange(
    bundle: MineExchangeBundle, *, adapter: str, minimum: tuple[int, int, int], supported: str
) -> None:
    require_version(
        bundle.version, adapter=adapter, minimum=minimum, below_major=2, supported=supported
    )


# --------------------------------------------------------------------------- #
# documents
# --------------------------------------------------------------------------- #


def network_document(bundle: MineExchangeBundle, *, adapter: str) -> ExchangeNetwork:
    doc = bundle.document(NETWORK_PATH, ExchangeNetwork)
    seen_nodes: set[str] = set()
    for n in doc.nodes:
        if n.id in seen_nodes:
            raise MineExchangeBundleInvalidError(
                "duplicate node id", adapter=adapter, source_group="NETWORK", subject=n.id
            )
        if len(n.position) != 3 or not np.all(np.isfinite(n.position)):
            raise MineExchangeBundleInvalidError(
                "node position is not a finite XYZ triple",
                adapter=adapter,
                source_group="NETWORK",
                subject=n.id,
            )
        seen_nodes.add(n.id)
    seen_edges: set[str] = set()
    for e in doc.edges:
        if e.id in seen_edges:
            raise MineExchangeBundleInvalidError(
                "duplicate edge id", adapter=adapter, source_group="NETWORK", subject=e.id
            )
        seen_edges.add(e.id)
        for node in (e.source_node_id, e.target_node_id):
            if node not in seen_nodes:
                raise MineExchangeBundleInvalidError(
                    f"edge references unknown node {node!r}",
                    adapter=adapter,
                    source_group="NETWORK",
                    subject=e.id,
                )
    return doc


@dataclass(frozen=True)
class CenterlinePoints:
    kind: str
    level_id: str | None
    points: FloatArray  # (N, 3) authoritative order


def centerline_points(bundle: MineExchangeBundle, *, adapter: str) -> dict[str, CenterlinePoints]:
    """Every authoritative centerline polyline by entity id (from the CSV
    authority, cross-checked against the manifest entity table)."""
    header, rows = read_csv(bundle.text(CENTERLINES_CSV_PATH))
    if tuple(header) != CENTERLINES_HEADER:
        raise MineExchangeBundleInvalidError(
            f"header {header} is not {list(CENTERLINES_HEADER)}",
            adapter=adapter,
            source_group="EXCAVATIONS",
            subject=CENTERLINES_CSV_PATH,
        )
    entities = bundle.entities
    grouped: dict[str, list[list[str]]] = {}
    for row in rows:
        if len(row) != len(CENTERLINES_HEADER):
            raise MineExchangeBundleInvalidError(
                f"malformed row {row}",
                adapter=adapter,
                source_group="EXCAVATIONS",
                subject=CENTERLINES_CSV_PATH,
            )
        grouped.setdefault(row[0], []).append(row)
    out: dict[str, CenterlinePoints] = {}
    for entity_id, entity_rows in grouped.items():
        entity = entities.get(entity_id)
        if entity is None or entity.kind != entity_rows[0][1]:
            raise MineExchangeBundleInvalidError(
                "centerline entity missing from the manifest or kind mismatch",
                adapter=adapter,
                source_group="EXCAVATIONS",
                subject=entity_id,
            )
        try:
            seq = [int(r[3]) for r in entity_rows]
            pts = np.asarray([[float(r[4]), float(r[5]), float(r[6])] for r in entity_rows])
        except ValueError as exc:
            raise MineExchangeBundleInvalidError(
                f"non-numeric centerline row: {exc}",
                adapter=adapter,
                source_group="EXCAVATIONS",
                subject=entity_id,
            ) from exc
        if seq != list(range(len(seq))) or len(seq) < 2 or not np.all(np.isfinite(pts)):
            raise MineExchangeBundleInvalidError(
                "sequence not contiguous from 0 with >= 2 finite points",
                adapter=adapter,
                source_group="EXCAVATIONS",
                subject=entity_id,
            )
        out[entity_id] = CenterlinePoints(
            kind=entity_rows[0][1], level_id=entity_rows[0][2] or None, points=pts
        )
    return out


def polyline_length(points: FloatArray) -> float:
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if pts.shape[0] < 2:
        return 0.0
    return float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())


def timeline_document(bundle: MineExchangeBundle, *, adapter: str) -> ExchangeTimeline | None:
    """The 1.3 operations document when the bundle carries it, else None."""
    if not bundle.has(TIMELINE_PATH):
        return None
    return bundle.document(TIMELINE_PATH, ExchangeTimeline)


def capability_document(bundle: MineExchangeBundle) -> ExchangeCapability | None:
    if not bundle.has(CAPABILITY_PATH):
        return None
    return bundle.document(CAPABILITY_PATH, ExchangeCapability)


def cross_section(edge: ExchangeNetworkEdge) -> tuple[float | None, float | None, str | None]:
    cs = edge.cross_section
    if not isinstance(cs, dict):
        return None, None, None
    width = cs.get("width")
    height = cs.get("height")
    shape = cs.get("shape")
    w = float(width) if isinstance(width, int | float) and np.isfinite(width) else None
    h = float(height) if isinstance(height, int | float) and np.isfinite(height) else None
    return w, h, (str(shape) if shape is not None else None)


def node_index(network: ExchangeNetwork) -> dict[str, ExchangeNetworkNode]:
    return {n.id: n for n in network.nodes}


def edge_index(network: ExchangeNetwork) -> dict[str, ExchangeNetworkEdge]:
    return {e.id: e for e in network.edges}


def mining_method(bundle: MineExchangeBundle) -> dict[str, Any] | None:
    if not bundle.has(MINING_METHOD_PATH):
        return None
    doc = bundle.json(MINING_METHOD_PATH)
    return doc if isinstance(doc, dict) else None
