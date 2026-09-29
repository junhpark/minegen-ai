"""Common engine package builder + the Unity / Unreal targets.

    <target>_package/
      adapter_manifest.json
      README.txt
      scene/assets/<bundle path with '/' -> '_'>.glb   every bundle GLB, normalized
      scene/entities.json         identity authority: entity ↔ asset ↔ network edges
      scene/network.json          topology/network.json (verbatim)
      scene/capability.json       semantics/capability.json (verbatim, when present)
      scene/timeline.json         operations/timeline.json (verbatim, when present, 1.3)
      scene/import_settings.json  per-asset frame facts + engine import notes

The engine importers convert glTF Y-up right-handed metres into the
engine's own convention (Unity: left-handed, one axis mirrored by the
importer; Unreal: Z-up left-handed centimetres); the package emits the
frame the importers expect and records which GLB kind each asset was.
"""

from __future__ import annotations

from typing import Any

from minegen.adapters.bundle_reader import MineExchangeBundle, parse_semver
from minegen.adapters.common import (
    CAPABILITY_PATH,
    MINE_EXCHANGE_1_2,
    MINE_EXCHANGE_1_3,
    NETWORK_PATH,
    PRODUCTION_GROUPS,
    TIMELINE_GROUP,
    TIMELINE_PATH,
    multi_member_group_state,
    network_document,
    not_provided,
    require_mine_exchange,
    shafts_state,
    source_state,
    timeline_document,
    version_gap_state,
)
from minegen.adapters.contracts import (
    AdapterCoordinateMapping,
    AdapterIdentityEntry,
    AdapterOmission,
    AdapterSourceState,
)
from minegen.adapters.engine.glb import GlbFormatError, add_root_transform, split_glb
from minegen.adapters.errors import AdapterConversionFailedError, MineExchangeBundleInvalidError
from minegen.adapters.package import README_PATH, AdapterPackage, PackageBuilder
from minegen.exchange.formats.glb import MINE_TO_GLTF_MATRIX
from minegen.exchange.formats.json_document import dumps
from minegen.exchange.models import COORDINATE_FRAME, GLTF_FRAME

UNITY_ADAPTER_NAME = "UNITY"
UNREAL_ADAPTER_NAME = "UNREAL"
ADAPTER_VERSION = "0.1.0"
SUPPORTED_MINE_EXCHANGE_VERSIONS = ">=1.2.0,<2.0.0"

ASSET_DIR = "scene/assets"
ENTITIES_PATH = "scene/entities.json"
NETWORK_OUT = "scene/network.json"
CAPABILITY_OUT = "scene/capability.json"
TIMELINE_OUT = "scene/timeline.json"
SETTINGS_PATH = "scene/import_settings.json"

#: what neither engine package provides (directive §43)
NOT_PROVIDED_ENGINE: tuple[tuple[str, str], ...] = (
    ("MATERIALS_AND_LIGHTING", "PBR materials, lighting, post-processing"),
    ("COLLISION_AND_PHYSICS", "collider generation, vehicle / character physics"),
    ("NAVIGATION", "NavMesh / pathfinding setup"),
    ("GAMEPLAY_AND_AI", "gameplay logic, AI agents"),
    ("VENTILATION_SIMULATION", "ventilation / gas simulation"),
    ("RUNTIME_SYNCHRONIZATION", "live synchronization with MineGen"),
    ("ANIMATION", "development-reveal / state-transition animation scripts"),
)


def _asset_path(bundle_path: str) -> str:
    return f"{ASSET_DIR}/{bundle_path.replace('/', '_')}"


def _engine_package(bundle: MineExchangeBundle, *, target: str, adapter: str) -> AdapterPackage:
    require_mine_exchange(
        bundle,
        adapter=adapter,
        minimum=MINE_EXCHANGE_1_2,
        supported=SUPPORTED_MINE_EXCHANGE_VERSIONS,
    )
    pkg = PackageBuilder(root=f"{target.lower()}_package", adapter=adapter)
    warnings: list[str] = []
    omissions: list[AdapterOmission] = []
    asset_facts: list[dict[str, Any]] = []
    asset_of_entity: dict[str, str] = {}
    glb_files = [f for f in bundle.manifest.files if f.media_type == "model/gltf-binary"]
    for entry in sorted(glb_files, key=lambda f: f.path):
        data = bundle.file(entry.path)
        frame = entry.glb
        if frame is None:
            raise MineExchangeBundleInvalidError(
                "GLB listed without a glb frame record", adapter=adapter, subject=entry.path
            )
        try:
            split_glb(data)  # every advertised GLB must be a valid container
        except GlbFormatError as exc:
            raise AdapterConversionFailedError(
                f"invalid GLB: {exc}", adapter=adapter, subject=entry.path
            ) from exc
        if frame.scene_frame == GLTF_FRAME:
            out, added = data, False
        elif frame.scene_frame == COORDINATE_FRAME and frame.transform_matrix is None:
            try:
                out = add_root_transform(data)
            except GlbFormatError as exc:
                raise AdapterConversionFailedError(
                    f"cannot re-frame GLB: {exc}", adapter=adapter, subject=entry.path
                ) from exc
            added = True
        else:
            raise AdapterConversionFailedError(
                f"unsupported GLB frame record sceneFrame={frame.scene_frame} "
                f"transformMatrix={'set' if frame.transform_matrix else 'null'}",
                adapter=adapter,
                subject=entry.path,
            )
        path = _asset_path(entry.path)
        pkg.add(
            path,
            out,
            target_semantic=f"ENGINE_ASSET:{entry.semantic_type}",
            source_files=[entry.path],
            source_entity_ids=list(entry.source_entity_ids),
        )
        for eid in entry.source_entity_ids:
            asset_of_entity.setdefault(eid, path)
        asset_facts.append(
            {
                "assetPath": path,
                "sourceFile": entry.path,
                "semanticType": entry.semantic_type,
                "representation": entry.representation,
                "storedVertexFrame": frame.stored_vertex_frame,
                "sourceSceneFrame": frame.scene_frame,
                "packageSceneFrame": GLTF_FRAME,
                "rootTransformAdded": added,
                "binaryChunkPreserved": True,
                "sourceEntityIds": list(entry.source_entity_ids),
                "junctionApertures": entry.geometry.junction_apertures if entry.geometry else None,
                "closed": entry.geometry.closed if entry.geometry else None,
            }
        )

    # -- semantics documents -------------------------------------------------- #
    network = network_document(bundle, adapter=adapter) if bundle.has(NETWORK_PATH) else None
    edges_of_entity: dict[str, list[str]] = {}
    if network is not None:
        for edge in network.edges:
            if edge.geometry_entity_id is not None:
                edges_of_entity.setdefault(edge.geometry_entity_id, []).append(edge.id)
        pkg.add(
            NETWORK_OUT,
            bundle.file(NETWORK_PATH),
            target_semantic="MINE_NETWORK",
            source_files=[NETWORK_PATH],
        )
    if bundle.has(CAPABILITY_PATH):
        pkg.add(
            CAPABILITY_OUT,
            bundle.file(CAPABILITY_PATH),
            target_semantic="CAPABILITY",
            source_files=[CAPABILITY_PATH],
        )
    timeline = timeline_document(bundle, adapter=adapter)
    if timeline is not None:
        for t in timeline.tasks:
            ref = t.target_reference
            if ref.kind == "NETWORK_EDGE" and (
                network is None or ref.id not in {e.id for e in network.edges}
            ):
                raise MineExchangeBundleInvalidError(
                    f"timeline task target edge {ref.id!r} is not in the network",
                    adapter=adapter,
                    source_group=TIMELINE_GROUP,
                    subject=t.task_id,
                )
            if ref.kind == "ENTITY" and ref.id not in bundle.entities:
                raise MineExchangeBundleInvalidError(
                    f"timeline task target entity {ref.id!r} is not a bundle entity",
                    adapter=adapter,
                    source_group=TIMELINE_GROUP,
                    subject=t.task_id,
                )
        pkg.add(
            TIMELINE_OUT,
            bundle.file(TIMELINE_PATH),
            target_semantic="MINE_TIMELINE",
            source_files=[TIMELINE_PATH],
        )
    entities_doc = {
        "targetApplication": target,
        "identitySemantics": (
            "entities.json is the identity authority of this package; importer-preserved "
            "GLB extras are a convenience, never relied on"
        ),
        "entities": [
            {
                "entityId": e.entity_id,
                "kind": e.kind,
                "levelId": e.level_id,
                "assetPath": asset_of_entity.get(e.entity_id),
                "sourceEntityId": e.entity_id,
                "sourceId": e.source_id,
                "parentEntityId": e.parent_entity_id,
                "sourceMemberIds": e.source_member_ids,
                "networkEdgeIds": edges_of_entity.get(e.entity_id, []),
                "bundleFiles": list(e.files),
            }
            for e in bundle.manifest.entities
        ],
    }
    pkg.add(
        ENTITIES_PATH,
        dumps(entities_doc),
        target_semantic="ENTITY_IDENTITY",
        source_files=["manifest.json", NETWORK_PATH] if network is not None else ["manifest.json"],
        source_entity_ids=[e.entity_id for e in bundle.manifest.entities],
    )
    render_present = any(f.semantic_type == "EXCAVATION_RENDER_SURFACE" for f in glb_files)
    for om in bundle.manifest.omissions:
        if om.group == "RENDER_GLB":
            omissions.append(
                AdapterOmission(
                    subject=f"renderGlb:{om.source_artifact or 'unknown'}",
                    reason_code=om.reason_code,
                    detail=om.detail,
                )
            )
    for e in bundle.manifest.entities:
        if e.entity_id not in asset_of_entity and not e.source_member_ids:
            omissions.append(
                AdapterOmission(
                    subject=f"entity:{e.entity_id}",
                    reason_code="NO_ENGINE_ASSET",
                    detail=f"{e.kind} carries no GLB in the bundle (centerline / semantic only)",
                )
            )
    settings = {
        "targetApplication": target,
        "packageSceneFrame": GLTF_FRAME,
        "unit": "metre",
        "handedness": "RIGHT_HANDED (glTF); the engine importer converts to its own convention",
        "rootTransformMatrixColumnMajor": list(MINE_TO_GLTF_MATRIX),
        "engineNotes": _engine_notes(target),
        "assets": asset_facts,
    }
    pkg.add(
        SETTINGS_PATH,
        dumps(settings),
        target_semantic="IMPORT_SETTINGS",
        source_files=["manifest.json"],
    )
    identity = [
        AdapterIdentityEntry(
            target_id=fact["assetPath"],
            target_kind="GLB_ASSET",
            bundle_entity_id=None,
            file=fact["sourceFile"],
        )
        for fact in asset_facts
    ] + [
        AdapterIdentityEntry(
            target_id=e.entity_id,
            target_kind="ENTITY",
            bundle_entity_id=e.entity_id,
            file=ENTITIES_PATH,
        )
        for e in bundle.manifest.entities
    ]
    major, minor, _ = parse_semver(bundle.version, adapter=adapter)
    timeline_state: AdapterSourceState = (
        version_gap_state(
            TIMELINE_GROUP,
            f"MineExchange {bundle.version} does not carry operations/timeline.json (1.3+)",
        )
        if (major, minor) < MINE_EXCHANGE_1_3[:2]
        else source_state(
            bundle, TIMELINE_GROUP, consumed=True, detail_when_available="scene/timeline.json"
        )
    )
    manifest_fields: dict[str, Any] = dict(
        adapter_name=adapter,
        adapter_version=ADAPTER_VERSION,
        target_application=target,
        supported_mine_exchange_versions=SUPPORTED_MINE_EXCHANGE_VERSIONS,
        source_mine_exchange_version=bundle.version,
        source_scenario_id=bundle.manifest.scenario_id,
        source_scenario_name=bundle.manifest.scenario_name,
        source_snapshot=bundle.manifest.source_snapshot.model_dump(mode="json", by_alias=True),
        coordinate_mapping=AdapterCoordinateMapping(
            source_frame=COORDINATE_FRAME,
            target_frame=GLTF_FRAME,
            unit="metre",
            unit_factor=1.0,
            handedness="RIGHT_HANDED",
            up_axis="Y",
            transform=list(MINE_TO_GLTF_MATRIX),
            note=(
                "every asset's scene is glTF Y-up right-handed metres: (x, y, z) -> (x, z, -y) "
                "as a ROOT NODE matrix over LOCAL_ENU_Z_UP vertices; the engine importer "
                "converts to the engine convention; semantic documents keep LOCAL_ENU_Z_UP"
            ),
        ),
        identity_map=identity,
        source_states=[
            source_state(
                bundle,
                "EXCAVATIONS",
                consumed=True,
                detail_when_available="entities + centerlines (ids)",
            ),
            multi_member_group_state(
                bundle,
                "RENDER_GLB",
                present=render_present,
                detail_when_available="normalized excavation render GLB assets",
            ),
            source_state(
                bundle, "NETWORK", consumed=True, detail_when_available="scene/network.json"
            ),
            source_state(
                bundle, "CAPABILITY", consumed=True, detail_when_available="scene/capability.json"
            ),
            *[
                source_state(bundle, g, consumed=True, detail_when_available="production solids")
                for g in PRODUCTION_GROUPS
                if bundle.omission(g) is not None
                or any(
                    f.semantic_type in ("STOPE_SOLID", "CUT_SOLID", "BENCH_SOLID", "PILLAR_SOLID")
                    for f in glb_files
                )
            ],
            shafts_state(
                bundle, consumed=True, detail_when_available="shaft centerline entities (ids)"
            ),
            timeline_state,
            source_state(bundle, "FIELD_LATTICE", consumed=False, detail_when_available=""),
        ],
        assumptions=[not_provided(kind, what, scope="SCENE") for kind, what in NOT_PROVIDED_ENGINE],
        warnings=warnings,
        omissions=omissions,
        details={
            "assetCount": len(asset_facts),
            "rootTransformsAdded": sum(1 for f in asset_facts if f["rootTransformAdded"]),
            "assetsAlreadyYUp": sum(1 for f in asset_facts if not f["rootTransformAdded"]),
            "entityCount": len(bundle.manifest.entities),
            "networkIncluded": network is not None,
            "capabilityIncluded": bundle.has(CAPABILITY_PATH),
            "timelineIncluded": timeline is not None,
        },
    )
    pkg.add(
        README_PATH,
        _readme(target, manifest_fields),
        target_semantic="README",
        source_files=["manifest.json"],
    )
    return pkg.finish(manifest_fields)


def _engine_notes(target: str) -> dict[str, str]:
    if target == "UNITY":
        return {
            "importer": "glTFast (com.unity.cloud.gltfast) or UnityGLTF — glTF 2.0 / GLB",
            "axes": (
                "Unity is Y-up LEFT-handed; the glTF importer mirrors one axis on import — "
                "do not pre-mirror"
            ),
            "units": "Unity units = metres; keep the import scale at 1",
            "identity": (
                "resolve objects through scene/entities.json (entityId -> assetPath), not "
                "node names"
            ),
        }
    return {
        "importer": "Interchange (glTF / GLB, 'Import Into Level') — no Datasmith required",
        "axes": (
            "Unreal is Z-up LEFT-handed; the glTF importer converts from glTF Y-up — do not "
            "pre-rotate"
        ),
        "units": (
            "Unreal units = centimetres; the glTF importer applies the metre -> cm scale (100)"
        ),
        "identity": (
            "resolve actors through scene/entities.json (entityId -> assetPath), not asset names"
        ),
    }


def _readme(target: str, fields: dict[str, Any]) -> bytes:
    d = fields["details"]
    notes = _engine_notes(target)
    lines = [
        f"{target} import package — {fields['adapter_name']} adapter {ADAPTER_VERSION} over "
        f"MineExchange {fields['source_mine_exchange_version']} (scenario "
        f"{fields['source_scenario_id']} '{fields['source_scenario_name']}')",
        "",
        "Geometry import package + mine semantic identity package. It packages the mine's",
        "geometry and semantics for the engine; it is NOT a mine-design or simulation",
        "authority and adds no gameplay, physics, NavMesh, ventilation, AI, animation or",
        "runtime synchronization. adapter_manifest.json is the meaning authority.",
        "",
        "Files (scene/)",
        f"  assets/*.glb          {d['assetCount']} GLB assets, every scene glTF Y-up metres",
        f"                        ({d['rootTransformsAdded']} render GLBs re-framed with ONE root",
        f"                        node, {d['assetsAlreadyYUp']} already Y-up, copied verbatim;",
        "                        mesh bytes untouched)",
        "  entities.json         IDENTITY AUTHORITY: entityId, kind, levelId, assetPath,",
        "                        sourceEntityId, networkEdgeIds[] — never rely on importer-kept",
        "                        extras",
        "  network.json          MineExchange topology (nodes / edges, LOCAL_ENU_Z_UP metres)",
        "  capability.json       typed may / may-not tags (when present; capability != capacity)",
        "  timeline.json         MineExchange 1.3 operations timeline (when present): development",
        "                        progress + production state machines — implement reveal / state",
        "                        visuals yourself; no animation script is generated",
        "  import_settings.json  per-asset frame facts (storedVertexFrame, sourceSceneFrame,",
        "                        rootTransformAdded) and engine import notes",
        "",
        "Engine notes",
        f"  importer: {notes['importer']}",
        f"  axes:     {notes['axes']}",
        f"  units:    {notes['units']}",
        f"  identity: {notes['identity']}",
        "",
        "Coordinates: assets are glTF Y-up ((x, y, z) -> (x, z, -y) root matrix over",
        "LOCAL_ENU_Z_UP vertices); the semantic documents keep LOCAL_ENU_Z_UP metres.",
        f"No proprietary {target.title()} project file is produced.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def build_unity_package(bundle: MineExchangeBundle) -> AdapterPackage:
    return _engine_package(bundle, target="UNITY", adapter=UNITY_ADAPTER_NAME)


def build_unreal_package(bundle: MineExchangeBundle) -> AdapterPackage:
    return _engine_package(bundle, target="UNREAL", adapter=UNREAL_ADAPTER_NAME)
