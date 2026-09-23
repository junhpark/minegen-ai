"""Phase 23A PR #44 independent-review corrections (B1–B5, S1, S2).

FAST, builder-level: a small synthetic world plus hand-written owning
artifacts (straight ramp, one level access, a two-piece drift, one crosscut,
one shaft) drive ``build_exchange`` / ``write_bundle`` and the pure helpers
directly, so every correction is proven without the layout-v2 chain:

- B1 canonical ``resolve_owning_centerline`` for every network geometryRef,
  typed refusals, RAISE explicit (never a silent null)
- B2 present-but-FAILED capability graph → SOURCE_NOT_SUCCESS omission
- B3 shaft aggregate parents (``shaft:<id>``) that own no geometry
- B4 injective file stems + bundle preflight (duplicate ids / paths, dangling
  parents / geometry refs, malformed development ids) → typed 409
- B5 copied-GLB ``junctionApertures`` from the authoritative report
- S1 aggregates carry ``sourceId = null`` + ``sourceMemberIds``
- S2 present-but-FAILED optional development sources are explicit omissions
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from minegen.core.artifacts import (
    CAPABILITY_GRAPH_ARTIFACT,
    LAYOUT_V2_SELECTED_ARTIFACT,
    LEGACY_RAMP_ARTIFACT,
    LEVEL_ACCESSES_ARTIFACT,
    LEVELS_ARTIFACT,
    SHAFTS_ARTIFACT,
    TUNNEL_MESH_ARTIFACT,
)
from minegen.core.models import Scenario
from minegen.exchange.builder import (
    ArtifactInput,
    BundleFile,
    BundleSpec,
    ExchangeExportError,
    ExchangeInputs,
    build_exchange,
    entity_file_stem,
    junction_apertures_of,
    preflight_bundle,
    project_network,
)
from minegen.exchange.bundle import BUNDLE_ROOT, BundlePathError, write_bundle
from minegen.exchange.geometry.centerlines import (
    CenterlineEntity,
    access_centerlines,
    development_entity_id,
    level_centerlines,
    ramp_centerlines,
    shaft_aggregates,
    shaft_centerlines,
)
from minegen.exchange.models import ExchangeEntity, SourceSnapshot
from minegen.world.synthetic_world import SyntheticWorld, generate_world
from tests.conftest import small_scenario
from tests.test_world_api import _create

EXPORT = "/export/mine-exchange"


# --------------------------------------------------------------------------- #
# synthetic owning artifacts (straight developments, every kind once)
# --------------------------------------------------------------------------- #


def _line(a: tuple[float, float, float], b: tuple[float, float, float], n: int = 9) -> list[float]:
    t = np.linspace(0.0, 1.0, n)[:, None]
    pts = np.asarray(a)[None, :] * (1 - t) + np.asarray(b)[None, :] * t
    return [float(v) for v in pts.ravel()]


_TANGENT = [0.0, 0.995037, -0.099504]  # unit tangent of the straight −10 % ramp legs


def ramp_doc() -> dict[str, Any]:
    return {
        "status": "SUCCESS",
        "failureReason": None,
        "segments": [
            {
                "segmentId": "S01",
                "levelId": "L01",
                "effectiveSource": "SMOOTHED",
                "boundaryTangents": {"start": _TANGENT, "end": _TANGENT},
                "effectiveCenterline": {"points": _line((0, 0, 100), (0, 120, 88), 13)},
            },
            {
                "segmentId": "S02",
                "levelId": "L02",
                "effectiveSource": "SMOOTHED",
                "boundaryTangents": {"start": _TANGENT, "end": _TANGENT},
                "effectiveCenterline": {"points": _line((0, 120, 88), (0, 240, 76), 13)},
            },
        ],
        "totals": {},
    }


def accesses_doc() -> dict[str, Any]:
    return {
        "status": "SUCCESS",
        "failureReason": None,
        "accesses": [
            {
                "levelId": "L01",
                "status": "OK",
                "centerline": {"points": _line((40, 120, 88), (80, 120, 88), 9)},
            }
        ],
    }


def levels_doc() -> dict[str, Any]:
    return {
        "status": "SUCCESS",
        "failureReason": None,
        "developments": [
            {
                "id": "DRIFT:L01:00",
                "kind": "DRIFT",
                "levelId": "L01",
                "fromU": 0.0,
                "centerline": {"points": _line((80, 60, 88), (80, 120, 88), 7)},
            },
            {
                "id": "DRIFT:L01:01",
                "kind": "DRIFT",
                "levelId": "L01",
                "fromU": 60.0,
                "centerline": {"points": _line((80, 120, 88), (80, 180, 88), 7)},
            },
            {
                "id": "CROSSCUT:L01:S+00",
                "kind": "CROSSCUT",
                "levelId": "L01",
                "fromU": 30.0,
                "centerline": {"points": _line((80, 90, 88), (110, 90, 88), 5)},
            },
        ],
    }


def shafts_doc() -> dict[str, Any]:
    return {
        "status": "SUCCESS",
        "failureReason": None,
        "shafts": [
            {
                "shaftId": "SHAFT-01",
                "status": "OK",
                "segmentIndices": [0, 1],
                "stations": [{"stationId": "STN:SHAFT-01:L01", "levelId": "L01"}],
            }
        ],
        "centerlines": [
            {
                "id": "SHAFT:SHAFT-01:SEG00",
                "shaftId": "SHAFT-01",
                "kind": "SHAFT_SEGMENT",
                "levelId": None,
                "centerline": {"points": _line((150, 90, 130), (150, 90, 88), 5)},
            },
            {
                "id": "SHAFT:SHAFT-01:SEG01",
                "shaftId": "SHAFT-01",
                "kind": "SHAFT_SEGMENT",
                "levelId": None,
                "centerline": {"points": _line((150, 90, 88), (150, 90, 70), 5)},
            },
            {
                "id": "SHAFT_STATION_ACCESS:SHAFT-01:L01",
                "shaftId": "SHAFT-01",
                "kind": "STATION_ACCESS",
                "levelId": "L01",
                "centerline": {"points": _line((150, 90, 88), (110, 90, 88), 5)},
            },
        ],
    }


def _edge(
    edge_id: str, edge_type: str, artifact: str | None, index: Any, a: str = "N1", b: str = "N2"
) -> dict[str, Any]:
    return {
        "id": edge_id,
        "type": edge_type,
        "fromNode": a,
        "toNode": b,
        "geometryRef": None if artifact is None else {"artifact": artifact, "segmentIndex": index},
        "length3d": 10.0,
        "orientation": "DEVELOPMENT",
        "crossSection": None,
    }


def network_doc(ramp_artifact: str = LEGACY_RAMP_ARTIFACT) -> dict[str, Any]:
    return {
        "status": "SUCCESS",
        "failureReason": None,
        "nodes": [
            {"id": "N1", "type": "PORTAL", "position": [0.0, 0.0, 100.0], "levelId": None},
            {"id": "N2", "type": "LEVEL_ENTRY", "position": [80.0, 120.0, 88.0], "levelId": "L01"},
        ],
        "edges": [
            _edge("RAMP:S01", "RAMP", ramp_artifact, 0),
            _edge("RAMP:S02", "RAMP", ramp_artifact, 1),
            _edge("LEVEL_ACCESS:L01", "LEVEL_ACCESS", LEVEL_ACCESSES_ARTIFACT, 0),
            _edge("DRIFT:L01:00", "DRIFT", LEVELS_ARTIFACT, 0),
            _edge("DRIFT:L01:01", "DRIFT", LEVELS_ARTIFACT, 1),
            _edge("CROSSCUT:L01:S+00", "CROSSCUT", LEVELS_ARTIFACT, 2),
            _edge("SHAFT:SHAFT-01:SEG00", "SHAFT", SHAFTS_ARTIFACT, 0),
            _edge("SHAFT:SHAFT-01:SEG01", "SHAFT", SHAFTS_ARTIFACT, 1),
            _edge("SHAFT_STATION_ACCESS:SHAFT-01:L01", "SHAFT_STATION_ACCESS", SHAFTS_ARTIFACT, 2),
        ],
    }


def capability_doc(status: str = "SUCCESS") -> dict[str, Any]:
    return {
        "status": status,
        "failureReason": None if status == "SUCCESS" else "EGRESS_UNSATISFIED: no route for N2",
        "capabilities": ["PERSONNEL"],
        "edges": [{"edgeId": "RAMP:S01", "capabilities": ["PERSONNEL"], "source": "DEFAULT"}],
        "nodes": [{"nodeId": "N1", "supports": ["PERSONNEL"], "surface": True}],
        "surfaceNodeIds": ["N1"],
        "requiredPaths": [],
        "egressAdvisory": None,
        "validation": None,
    }


def all_centerlines(ramp_artifact: str = LEGACY_RAMP_ARTIFACT) -> list[CenterlineEntity]:
    return (
        ramp_centerlines(ramp_doc(), ramp_artifact)
        + access_centerlines(accesses_doc())
        + level_centerlines(levels_doc())
        + shaft_centerlines(shafts_doc())
    )


def _project(
    net: dict[str, Any],
    centerlines: list[CenterlineEntity] | None = None,
    *,
    ramp: dict[str, Any] | None = None,
    ramp_artifact: str | None = LEGACY_RAMP_ARTIFACT,
    accesses: dict[str, Any] | None = None,
    levels: dict[str, Any] | None = None,
    shafts: dict[str, Any] | None = None,
    defaults: bool = True,
) -> Any:
    if defaults:
        ramp = ramp_doc() if ramp is None else ramp
        accesses = accesses_doc() if accesses is None else accesses
        levels = levels_doc() if levels is None else levels
        shafts = shafts_doc() if shafts is None else shafts
    return project_network(
        net,
        "rev-net",
        all_centerlines() if centerlines is None else centerlines,
        ramp_doc=ramp,
        ramp_artifact=ramp_artifact,
        accesses_doc=accesses,
        levels_doc=levels,
        shafts_doc=shafts,
    )


# --------------------------------------------------------------------------- #
# B1 — canonical geometryRef resolution
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("edge_id", "entity_id"),
    [
        ("RAMP:S01", "ramp:main:S01"),
        ("RAMP:S02", "ramp:main:S02"),
        ("LEVEL_ACCESS:L01", "level-access:L01"),
        ("DRIFT:L01:00", "drift:L01:00"),
        ("DRIFT:L01:01", "drift:L01:01"),
        ("CROSSCUT:L01:S+00", "crosscut:L01:S+00"),
        ("SHAFT:SHAFT-01:SEG00", "shaft:SHAFT:SHAFT-01:SEG00"),
        ("SHAFT:SHAFT-01:SEG01", "shaft:SHAFT:SHAFT-01:SEG01"),
        (
            "SHAFT_STATION_ACCESS:SHAFT-01:L01",
            "shaft-station-access:SHAFT_STATION_ACCESS:SHAFT-01:L01",
        ),
    ],
)
def test_b1_every_physical_edge_type_resolves_to_its_exported_centerline(
    edge_id: str, entity_id: str
) -> None:
    doc = _project(network_doc())
    edge = next(e for e in doc.edges if e.id == edge_id)
    assert edge.geometry_entity_id == entity_id
    assert edge.geometry_contract == "OWNING_CENTERLINE"
    assert entity_id in {c.entity_id for c in all_centerlines()}


def _single(edge: dict[str, Any]) -> dict[str, Any]:
    net = network_doc()
    net["edges"] = [edge]
    return net


def test_b1_wrong_owner_artifact_for_the_edge_type_is_typed() -> None:
    with pytest.raises(ExchangeExportError, match=r"DRIFT.*must be owned by levels\.json"):
        _project(_single(_edge("DRIFT:L01:00", "DRIFT", LEVEL_ACCESSES_ARTIFACT, 0)))
    with pytest.raises(ExchangeExportError, match=r"LEVEL_ACCESS.*must be owned by"):
        _project(_single(_edge("LEVEL_ACCESS:L01", "LEVEL_ACCESS", LEVELS_ARTIFACT, 0)))
    with pytest.raises(ExchangeExportError, match=r"SHAFT.*must be owned by shafts\.json"):
        _project(_single(_edge("SHAFT:X", "SHAFT", LEVELS_ARTIFACT, 0)))


def test_b1_out_of_range_index_is_typed() -> None:
    with pytest.raises(ExchangeExportError, match=r"out of range for levels\.json \(3 entries\)"):
        _project(_single(_edge("DRIFT:L01:09", "DRIFT", LEVELS_ARTIFACT, 9)))


@pytest.mark.parametrize("index", [-1, True, "0", 1.0, None])
def test_b1_non_integer_or_negative_index_is_typed(index: Any) -> None:
    with pytest.raises(ExchangeExportError, match="not a non-negative integer"):
        _project(_single(_edge("DRIFT:L01:00", "DRIFT", LEVELS_ARTIFACT, index)))


def test_b1_owner_artifact_absent_is_typed_never_a_key_error() -> None:
    net = _single(_edge("DRIFT:L01:00", "DRIFT", LEVELS_ARTIFACT, 0))
    with pytest.raises(ExchangeExportError, match="0 entries"):
        _project(net, levels=None, defaults=False, ramp=ramp_doc())


def test_b1_malformed_owning_centerline_is_typed() -> None:
    bad = levels_doc()
    bad["developments"][0]["centerline"]["points"] = [0.0, 1.0, 2.0, 3.0]  # not a multiple of 3
    with pytest.raises(ExchangeExportError, match="flat multiple-of-3"):
        _project(_single(_edge("DRIFT:L01:00", "DRIFT", LEVELS_ARTIFACT, 0)), levels=bad)
    nan = levels_doc()
    nan["developments"][0]["centerline"]["points"][2] = float("nan")
    with pytest.raises(ExchangeExportError, match="non-finite"):
        _project(_single(_edge("DRIFT:L01:00", "DRIFT", LEVELS_ARTIFACT, 0)), levels=nan)
    with pytest.raises(ExchangeExportError, match="geometryRef is not an object"):
        _project(_single(_edge("DRIFT:L01:00", "DRIFT", None, 0)))


def test_b1_resolved_geometry_missing_from_the_entity_map_is_typed() -> None:
    # the owning record exists and resolves, but the exporter did not emit
    # that centerline entity (an inconsistent bundle would follow): refuse
    without_shafts = ramp_centerlines(ramp_doc(), LEGACY_RAMP_ARTIFACT)
    net = _single(_edge("SHAFT:SHAFT-01:SEG00", "SHAFT", SHAFTS_ARTIFACT, 0))
    with pytest.raises(ExchangeExportError, match="not an exported centerline entity"):
        _project(net, without_shafts)


def test_b1_ramp_edge_owned_by_the_inactive_ramp_artifact_is_typed() -> None:
    # the network was built over decline_smoothed.json while the ACTIVE
    # Effective Ramp is layout_v2_selected.json: an inconsistency, refused
    net = _single(_edge("RAMP:S01", "RAMP", LEGACY_RAMP_ARTIFACT, 0))
    with pytest.raises(ExchangeExportError, match="active Effective Ramp artifact"):
        _project(
            net,
            all_centerlines(LAYOUT_V2_SELECTED_ARTIFACT),
            ramp_artifact=LAYOUT_V2_SELECTED_ARTIFACT,
        )


def test_b1_raise_has_no_owning_contract_and_is_exported_explicitly() -> None:
    doc = _project(_single(_edge("RAISE:R1", "RAISE", None, 0)))
    (edge,) = doc.edges
    assert edge.geometry_entity_id is None and edge.geometry_contract == "NONE"
    dumped = doc.model_dump(mode="json", by_alias=True)
    assert dumped["edges"][0]["geometryContract"] == "NONE"


def test_b1_projection_is_deterministic() -> None:
    a = _project(network_doc()).model_dump(mode="json", by_alias=True)
    b = _project(network_doc()).model_dump(mode="json", by_alias=True)
    assert a == b


# --------------------------------------------------------------------------- #
# builder-level bundle on a small synthetic world
# --------------------------------------------------------------------------- #


class SyntheticMine:
    def __init__(self) -> None:
        self.scenario: Scenario = small_scenario(with_fault=True)
        self.world: SyntheticWorld = generate_world(self.scenario)

    def inputs(self, **overrides: Any) -> ExchangeInputs:
        base: dict[str, Any] = dict(
            scenario=self.scenario,
            world=self.world,
            scenario_revision="s1",
            arrays_revision="a1",
            active_source="LEGACY",
            ramp=ArtifactInput(ramp_doc(), "r-ramp"),
            ramp_artifact=LEGACY_RAMP_ARTIFACT,
            accesses=None,
            levels=ArtifactInput(levels_doc(), "r-levels"),
            shafts=ArtifactInput(shafts_doc(), "r-shafts"),
            network=ArtifactInput(network_doc(), "r-net"),
            capability=ArtifactInput(capability_doc(), "r-cap"),
        )
        base.update(overrides)
        return ExchangeInputs(**base)


@pytest.fixture(scope="module")
def mine() -> SyntheticMine:
    return SyntheticMine()


def _bundle(spec: BundleSpec) -> tuple[dict[str, Any], dict[str, bytes]]:
    data, _manifest = write_bundle(spec)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        entries = {n[len(BUNDLE_ROOT) + 1 :]: zf.read(n) for n in zf.namelist()}
    return json.loads(entries["manifest.json"]), entries


def _network_without_accesses() -> dict[str, Any]:
    net = network_doc()
    net["edges"] = [e for e in net["edges"] if e["type"] != "LEVEL_ACCESS"]
    return net


@pytest.fixture(scope="module")
def full(mine: SyntheticMine) -> tuple[dict[str, Any], dict[str, bytes]]:
    return _bundle(
        build_exchange(mine.inputs(network=ArtifactInput(_network_without_accesses(), "r-net")))
    )


# -- B3 / S1 ----------------------------------------------------------------- #


def test_b3_shaft_aggregate_parent_exists_and_owns_no_geometry(
    full: tuple[dict[str, Any], dict[str, bytes]],
) -> None:
    manifest, entries = full
    ents = {e["entityId"]: e for e in manifest["entities"]}
    shaft = ents["shaft:SHAFT-01"]
    assert shaft["kind"] == "SHAFT" and shaft["sourceArtifact"] == SHAFTS_ARTIFACT
    assert shaft["sourceId"] == "SHAFT-01"
    assert shaft["sourceMemberIds"] == ["SHAFT:SHAFT-01:SEG00", "SHAFT:SHAFT-01:SEG01"]
    assert shaft["files"] == []  # no shaft solid, no centerline of its own
    for seg in ("shaft:SHAFT:SHAFT-01:SEG00", "shaft:SHAFT:SHAFT-01:SEG01"):
        assert ents[seg]["kind"] == "SHAFT_SEGMENT"
        assert ents[seg]["parentEntityId"] == "shaft:SHAFT-01"
        assert "excavations/centerlines.csv" in ents[seg]["files"]
    station = ents["shaft-station-access:SHAFT_STATION_ACCESS:SHAFT-01:L01"]
    assert station["kind"] == "SHAFT_STATION_ACCESS" and station["parentEntityId"] is None
    # every non-null parent resolves
    for e in manifest["entities"]:
        if e["parentEntityId"] is not None:
            assert e["parentEntityId"] in ents, e["entityId"]
    # no solid claims the shaft (centerline-only representation)
    solid_sources = {
        sid
        for f in manifest["files"]
        if f["semanticType"] == "EXCAVATION_SOLID"
        for sid in f["sourceEntityIds"]
    }
    assert not any(s.startswith("shaft") for s in solid_sources)
    doc = json.loads(entries["excavations/entities.json"])
    agg = next(a for a in doc["aggregates"] if a["entityId"] == "shaft:SHAFT-01")
    assert agg["ownsGeometry"] is False
    readme = entries["README.txt"].decode()
    assert "centerlines only" in readme


def test_b3_network_maps_shaft_edges_to_the_shaft_centerline_entities(
    full: tuple[dict[str, Any], dict[str, bytes]],
) -> None:
    manifest, entries = full
    net = json.loads(entries["topology/network.json"])
    by_id = {e["id"]: e for e in net["edges"]}
    assert by_id["SHAFT:SHAFT-01:SEG00"]["geometryEntityId"] == "shaft:SHAFT:SHAFT-01:SEG00"
    assert by_id["SHAFT_STATION_ACCESS:SHAFT-01:L01"]["geometryEntityId"] == (
        "shaft-station-access:SHAFT_STATION_ACCESS:SHAFT-01:L01"
    )
    ents = {e["entityId"] for e in manifest["entities"]}
    for e in net["edges"]:
        assert e["geometryContract"] == "OWNING_CENTERLINE"
        assert e["geometryEntityId"] in ents


def test_s1_aggregates_use_null_source_id_and_explicit_members(
    full: tuple[dict[str, Any], dict[str, bytes]],
) -> None:
    manifest, entries = full
    ents = {e["entityId"]: e for e in manifest["entities"]}
    ramp = ents["ramp:main"]
    assert ramp["sourceId"] is None and ramp["sourceMemberIds"] == ["S01", "S02"]
    assert ramp["sourceArtifact"] == LEGACY_RAMP_ARTIFACT
    drift = ents["drift:L01"]
    assert drift["sourceId"] is None and drift["sourceMemberIds"] == [
        "DRIFT:L01:00",
        "DRIFT:L01:01",
    ]
    assert ents["drift:L01:00"]["parentEntityId"] == "drift:L01"
    assert ents["ramp:main:S01"]["parentEntityId"] == "ramp:main"
    # non-aggregates keep their authoritative id
    assert ents["crosscut:L01:S+00"]["sourceId"] == "CROSSCUT:L01:S+00"
    assert ents["drift:L01:00"]["sourceId"] == "DRIFT:L01:00"
    doc = json.loads(entries["excavations/entities.json"])
    solid = next(s for s in doc["solids"] if s["entityId"] == "ramp:main")
    assert solid["sourceId"] is None and solid["sourceMemberIds"] == ["S01", "S02"]
    text = json.dumps(manifest) + entries["excavations/entities.json"].decode()
    assert "segments[*]" not in text


# -- B2 ------------------------------------------------------------------------ #


def test_b2_present_failed_capability_graph_is_an_explicit_omission(mine: SyntheticMine) -> None:
    spec = build_exchange(
        mine.inputs(
            network=ArtifactInput(_network_without_accesses(), "r-net"),
            capability=ArtifactInput(capability_doc("FAILED"), "r-cap"),
        )
    )
    manifest, entries = _bundle(spec)
    assert "semantics/capability.json" not in entries
    assert "topology/network.json" in entries  # partial bundle, not a failure
    om = next(o for o in manifest["omissions"] if o["group"] == "CAPABILITY")
    assert om["reasonCode"] == "SOURCE_NOT_SUCCESS"
    assert om["sourceArtifact"] == CAPABILITY_GRAPH_ARTIFACT
    assert "FAILED" in om["detail"] and "EGRESS_UNSATISFIED" in om["detail"]


def test_b2_absent_capability_graph_stays_artifact_absent(mine: SyntheticMine) -> None:
    spec = build_exchange(
        mine.inputs(network=ArtifactInput(_network_without_accesses(), "r-net"), capability=None)
    )
    manifest, _ = _bundle(spec)
    om = next(o for o in manifest["omissions"] if o["group"] == "CAPABILITY")
    assert om["reasonCode"] == "ARTIFACT_ABSENT"


# -- S2 ------------------------------------------------------------------------ #


def test_s2_present_failed_levels_and_accesses_are_explicit_omissions(mine: SyntheticMine) -> None:
    failed_levels = {
        "status": "FAILED",
        "failureReason": "LEVEL_ACCESSES_REQUIRED",
        "developments": [],
    }
    failed_accesses = {"status": "FAILED", "failureReason": "GRADE_LIMIT L02", "accesses": []}
    spec = build_exchange(
        mine.inputs(
            active_source="LAYOUT_V2",
            ramp=ArtifactInput(ramp_doc(), "r-ramp"),
            ramp_artifact=LAYOUT_V2_SELECTED_ARTIFACT,
            accesses=ArtifactInput(failed_accesses, "r-acc"),
            levels=ArtifactInput(failed_levels, "r-levels"),
            shafts=None,
            network=None,
            capability=None,
        )
    )
    manifest, _entries = _bundle(spec)
    ents = {e["entityId"] for e in manifest["entities"]}
    assert "ramp:main" in ents and not any(e.startswith("drift") for e in ents)
    exc = [o for o in manifest["omissions"] if o["group"] == "EXCAVATIONS"]
    assert {(o["reasonCode"], o["sourceArtifact"]) for o in exc} == {
        ("SOURCE_NOT_SUCCESS", LEVEL_ACCESSES_ARTIFACT),
        ("SOURCE_NOT_SUCCESS", LEVELS_ARTIFACT),
    }
    details = {o["sourceArtifact"]: o["detail"] for o in exc}
    assert "GRADE_LIMIT L02" in details[LEVEL_ACCESSES_ARTIFACT]
    assert "LEVEL_ACCESSES_REQUIRED" in details[LEVELS_ARTIFACT]
    assert manifest["sourceSnapshot"]["activeRampSource"] == "LAYOUT_V2"


def test_s2_absent_optional_sources_are_not_omissions_of_that_kind(mine: SyntheticMine) -> None:
    spec = build_exchange(mine.inputs(levels=None, shafts=None, network=None, capability=None))
    manifest, _ = _bundle(spec)
    groups = {(o["group"], o["reasonCode"]) for o in manifest["omissions"]}
    assert ("EXCAVATIONS", "SOURCE_NOT_SUCCESS") not in groups
    assert ("NETWORK", "ARTIFACT_ABSENT") in groups


# -- B4 ------------------------------------------------------------------------ #


def test_b4_file_stems_are_injective_readable_and_path_safe() -> None:
    assert entity_file_stem("a:b") != entity_file_stem("a_b")  # the old sanitizer collided
    assert entity_file_stem("ramp:main").startswith("ramp_main_")
    stem = entity_file_stem("crosscut:L01:S+00")
    assert stem == entity_file_stem("crosscut:L01:S+00")  # stable
    assert len(stem.rsplit("_", 1)[1]) == 8 and int(stem.rsplit("_", 1)[1], 16) >= 0
    assert "/" not in entity_file_stem("../x:y") and "\\" not in entity_file_stem("a\\b")


def test_b4_bundle_solid_paths_are_unique_and_resolve_through_entities(
    full: tuple[dict[str, Any], dict[str, bytes]],
) -> None:
    manifest, entries = full
    paths = [f["path"] for f in manifest["files"]]
    assert len(paths) == len(set(paths))
    for e in manifest["entities"]:
        for path in e["files"]:
            assert path in entries, (e["entityId"], path)
    solids = [f for f in manifest["files"] if f["semanticType"] == "EXCAVATION_SOLID"]
    assert {f["path"] for f in solids} == {
        f"excavations/solids/{entity_file_stem(f['sourceEntityIds'][0])}.stl" for f in solids
    }


def _entity(
    entity_id: str,
    kind: str = "CROSSCUT",
    parent: str | None = None,
    files: list[str] | None = None,
) -> ExchangeEntity:
    return ExchangeEntity(
        entity_id=entity_id,
        kind=kind,  # type: ignore[arg-type]
        source_artifact=LEVELS_ARTIFACT,
        source_id=entity_id,
        parent_entity_id=parent,
        files=files or [],
    )


def _file(path: str, sources: list[str]) -> BundleFile:
    return BundleFile(path, b"x", "EXCAVATION_CENTERLINES", "POLYLINES", sources, None, None, False)


def _spec(
    entities: list[ExchangeEntity],
    files: list[BundleFile],
    refs: list[tuple[str, str]] | None = None,
) -> BundleSpec:
    return BundleSpec(
        scenario_id="s",
        scenario_name="s",
        source_snapshot=SourceSnapshot(
            scenario_revision="r",
            arrays_revision="r",
            active_ramp_source="LEGACY",
            artifact_revisions={},
        ),
        files=files,
        entities=entities,
        omissions=[],
        notes=[],
        network_geometry_refs=refs or [],
    )


def test_b4_preflight_refuses_duplicate_entity_ids() -> None:
    with pytest.raises(ExchangeExportError, match="duplicate entity id 'crosscut:L01:S\\+00'"):
        preflight_bundle(_spec([_entity("crosscut:L01:S+00"), _entity("crosscut:L01:S+00")], []))


def test_b4_preflight_refuses_duplicate_bundle_paths() -> None:
    f = _file("excavations/centerlines.csv", ["crosscut:L01:S+00"])
    with pytest.raises(BundlePathError, match="duplicate bundle path") as info:
        preflight_bundle(_spec([_entity("crosscut:L01:S+00")], [f, f]))
    assert isinstance(info.value, ExchangeExportError)  # typed 409, not a bare ValueError


def test_b4_preflight_refuses_dangling_parent_and_missing_files() -> None:
    with pytest.raises(ExchangeExportError, match="unknown parent 'drift:L01'"):
        preflight_bundle(_spec([_entity("drift:L01:00", "DRIFT_PIECE", parent="drift:L01")], []))
    with pytest.raises(ExchangeExportError, match="references missing file"):
        preflight_bundle(
            _spec([_entity("crosscut:L01:S+00", files=["excavations/solids/x.stl"])], [])
        )
    with pytest.raises(ExchangeExportError, match="references unknown entity 'ghost'"):
        preflight_bundle(
            _spec([_entity("crosscut:L01:S+00")], [_file("excavations/centerlines.csv", ["ghost"])])
        )


def test_b4_preflight_refuses_dangling_network_geometry_reference() -> None:
    with pytest.raises(
        ExchangeExportError, match="network edge 'DRIFT:L01:00' resolves to unexported geometry"
    ):
        preflight_bundle(
            _spec([_entity("crosscut:L01:S+00")], [], refs=[("DRIFT:L01:00", "drift:L01:00")])
        )


def test_b4_preflight_refuses_unsafe_paths() -> None:
    with pytest.raises(BundlePathError):
        preflight_bundle(
            _spec([_entity("crosscut:L01:S+00")], [_file("../escape.csv", ["crosscut:L01:S+00"])])
        )


def test_b4_malformed_development_id_is_typed() -> None:
    with pytest.raises(ExchangeExportError, match="unrecognised development id 'BOGUS'"):
        development_entity_id("BOGUS")
    with pytest.raises(ExchangeExportError, match="unrecognised development id 'STOPE:L01:00'"):
        development_entity_id("STOPE:L01:00")
    bad = levels_doc()
    bad["developments"][0]["id"] = "RAISE:L01:00"
    with pytest.raises(ExchangeExportError, match="not a DRIFT / CROSSCUT development"):
        level_centerlines(bad)
    odd = shafts_doc()
    odd["centerlines"][0]["kind"] = "WINZE"
    with pytest.raises(ExchangeExportError, match="unknown centerline kind 'WINZE'"):
        shaft_centerlines(odd)
    dangling = shafts_doc()
    dangling["shafts"][0]["segmentIndices"] = [0, 7]
    with pytest.raises(ExchangeExportError, match="not a valid centerlines index"):
        shaft_aggregates(dangling)


def test_b4_builder_refuses_a_malformed_development_id_end_to_end(mine: SyntheticMine) -> None:
    bad = levels_doc()
    bad["developments"][2]["id"] = "CROSSCUT-L01-S+00"  # no kind prefix
    with pytest.raises(ExchangeExportError):
        build_exchange(
            mine.inputs(levels=ArtifactInput(bad, "r-levels"), network=None, capability=None)
        )


def test_b4_http_projection_failures_are_typed_409_never_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = _create(client)
    assert client.post(f"/api/v1/scenarios/{sid}/world/generate").status_code == 200
    assert client.post(f"/api/v1/scenarios/{sid}{EXPORT}").status_code == 200

    def broken(inputs: ExchangeInputs) -> BundleSpec:
        spec = build_exchange(inputs)
        spec.entities.append(spec.entities[0])  # a duplicated entity id
        return spec

    monkeypatch.setattr("minegen.services.exchange_service.build_exchange", broken)
    r = client.post(f"/api/v1/scenarios/{sid}{EXPORT}")
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "MINE_EXCHANGE_EXPORT_FAILED"
    assert "duplicate entity id" in detail["message"]
    monkeypatch.undo()

    def dup_path(inputs: ExchangeInputs) -> BundleSpec:
        spec = build_exchange(inputs)
        spec.files.append(spec.files[0])
        return spec

    monkeypatch.setattr("minegen.services.exchange_service.build_exchange", dup_path)
    r = client.post(f"/api/v1/scenarios/{sid}{EXPORT}")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "MINE_EXCHANGE_EXPORT_FAILED"
    assert "duplicate bundle path" in r.json()["detail"]["message"]
    monkeypatch.undo()
    assert client.post(f"/api/v1/scenarios/{sid}{EXPORT}").status_code == 200


# -- B5 ------------------------------------------------------------------------ #


def test_b5_junction_apertures_come_from_the_authoritative_report() -> None:
    opened = {
        "junctions": {
            "count": 4,
            "openedEndpointCount": 4,
            "removedTriangles": 750,
            "openings": [{}] * 4,
        }
    }
    assert junction_apertures_of(opened) is True
    assert (
        junction_apertures_of(
            {
                "junctions": {
                    "count": 0,
                    "openedEndpointCount": 0,
                    "removedTriangles": 0,
                    "openings": [],
                }
            }
        )
        is False
    )
    assert (
        junction_apertures_of(
            {"junctions": {"count": 0, "openedEndpointCount": 0, "removedTriangles": 12}}
        )
        is True
    )
    assert junction_apertures_of({"junctions": {"openings": [{"type": "RAMP_ACCESS"}]}}) is True
    assert junction_apertures_of({}) is None
    assert junction_apertures_of({"junctions": None}) is None
    assert junction_apertures_of({"junctions": {"count": "4"}}) is None
    assert junction_apertures_of({"junctions": {"count": True}}) is None
    assert junction_apertures_of({"junctions": {"count": -1}}) is None


def _tunnel_report(junctions: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "status": "SUCCESS",
        "geometricallyClosed": True,
        "watertight": True,
        "manifold": True,
        "triangleCount": 12,
    }
    if junctions is not None:
        doc["junctions"] = junctions
    return doc


@pytest.mark.parametrize(
    ("junctions", "expected"),
    [
        (
            {"count": 2, "openedEndpointCount": 2, "removedTriangles": 40, "openings": [{}, {}]},
            True,
        ),
        ({"count": 0, "openedEndpointCount": 0, "removedTriangles": 0, "openings": []}, False),
        (None, None),
    ],
)
def test_b5_copied_glb_manifest_entry_reports_apertures_and_frame_factually(
    mine: SyntheticMine, junctions: Any, expected: bool | None
) -> None:
    glb = b"glTF\x02\x00\x00\x00" + bytes(range(64))
    spec = build_exchange(
        mine.inputs(
            network=None,
            capability=None,
            tunnel_report=ArtifactInput(_tunnel_report(junctions), "r-tunnel"),
            tunnel_glb=glb,
        )
    )
    manifest, entries = _bundle(spec)
    assert entries["excavations/render/tunnel.glb"] == glb  # bytes verbatim
    f = next(x for x in manifest["files"] if x["path"] == "excavations/render/tunnel.glb")
    assert f["geometry"]["junctionApertures"] is expected
    assert f["sourceArtifact"] == TUNNEL_MESH_ARTIFACT and f["sourceRevision"] == "r-tunnel"
    assert f["glb"] == {
        "storedVertexFrame": "LOCAL_ENU_Z_UP",
        "sceneFrame": "LOCAL_ENU_Z_UP",
        "sourceFrame": "LOCAL_ENU_Z_UP",
        "transformMatrix": None,
    }
    created = next(x for x in manifest["files"] if x["path"] == "orebody/orebody.glb")
    assert created["glb"]["sceneFrame"] == "GLTF_Y_UP"
    assert created["glb"]["storedVertexFrame"] == "LOCAL_ENU_Z_UP"
    assert created["glb"]["transformMatrix"] is not None
    readme = entries["README.txt"].decode()
    assert "exporter-created GLBs" in readme and "copied production render GLBs" in readme
    assert "transformMatrix = null" in readme


def test_b5_no_source_glb_bytes_means_omission_not_a_guess(mine: SyntheticMine) -> None:
    spec = build_exchange(
        mine.inputs(
            network=None,
            capability=None,
            tunnel_report=ArtifactInput(_tunnel_report({"count": 1}), "r-tunnel"),
            tunnel_glb=None,
        )
    )
    manifest, entries = _bundle(spec)
    assert "excavations/render/tunnel.glb" not in entries
    assert ("RENDER_GLB", "ARTIFACT_ABSENT") in {
        (o["group"], o["reasonCode"]) for o in manifest["omissions"]
    }


# -- determinism of the corrected bundle ------------------------------------------ #


def test_corrected_bundle_is_deterministic(mine: SyntheticMine) -> None:
    a, _ = write_bundle(
        build_exchange(mine.inputs(network=ArtifactInput(_network_without_accesses(), "r-net")))
    )
    b, _ = write_bundle(
        build_exchange(mine.inputs(network=ArtifactInput(_network_without_accesses(), "r-net")))
    )
    assert a == b
