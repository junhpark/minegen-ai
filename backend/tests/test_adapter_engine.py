"""Phase 23B engine packages — GLB normalization + Unity / Unreal (directive
§42–§50, §67).

FAST: the GLB patcher is exercised on writer-produced GLBs (exporter frame
and copied-render frame); the packages on the synthetic bundle plus a
variant carrying a copied LOCAL_ENU_Z_UP render GLB.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pytest

from minegen.adapters import build_package
from minegen.adapters.engine.glb import (
    ROOT_NODE_NAME,
    GlbFormatError,
    add_root_transform,
    join_glb,
    scene_root_nodes,
    split_glb,
)
from minegen.adapters.engine.package import (
    CAPABILITY_OUT,
    ENTITIES_PATH,
    NETWORK_OUT,
    NOT_PROVIDED_ENGINE,
    SETTINGS_PATH,
    TIMELINE_OUT,
)
from minegen.adapters.errors import AdapterConversionFailedError
from minegen.exchange.builder import ArtifactInput
from minegen.exchange.formats.glb import MINE_TO_GLTF_MATRIX, apply_transform, write_mesh_glb
from tests.adapter_support import bundle_files, bundle_manifest, manifest, package_root, unzip
from tests.exchange_fixtures import synthetic_bundle
from tests.test_exchange_corrections import SyntheticMine

TRI = np.asarray([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
QUAD = np.asarray([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [10.0, 20.0, 5.0], [0.0, 20.0, 5.0]])


def _render_glb() -> bytes:
    """A copied-render-style GLB: LOCAL_ENU_Z_UP vertices, NO root transform."""
    return write_mesh_glb(
        QUAD,
        [("SEGMENT:S01", TRI, {"segmentId": "S01"})],
        name="tunnel",
        node_extras={"artifact": "tunnel_mesh.glb"},
        root_transform=False,
    )


def _exporter_glb() -> bytes:
    return write_mesh_glb(QUAD, [("body", TRI, {})], name="orebody", node_extras={})


@pytest.fixture(scope="module")
def mine() -> SyntheticMine:
    return SyntheticMine()


@pytest.fixture(scope="module")
def bundle(mine: SyntheticMine) -> bytes:
    return synthetic_bundle(mine)


@pytest.fixture(scope="module")
def bundle_with_render(mine: SyntheticMine) -> bytes:
    report = {
        "status": "SUCCESS",
        "geometricallyClosed": True,
        "watertight": True,
        "manifold": True,
        "triangleCount": 2,
    }
    return synthetic_bundle(
        mine, tunnel_report=ArtifactInput(report, "r-tunnel"), tunnel_glb=_render_glb()
    )


# --------------------------------------------------------------------------- #
# GLB patcher
# --------------------------------------------------------------------------- #


def test_g1_root_transform_added_once_binary_preserved() -> None:
    src = _render_glb()
    doc0, bin0 = split_glb(src)
    assert all("matrix" not in doc0["nodes"][i] for i in scene_root_nodes(doc0))
    out = add_root_transform(src)
    doc1, bin1 = split_glb(out)
    assert bin1 == bin0  # vertices / normals / indices byte-identical
    assert doc1["meshes"] == doc0["meshes"] and doc1["accessors"] == doc0["accessors"]
    assert doc1["bufferViews"] == doc0["bufferViews"]
    roots = scene_root_nodes(doc1)
    assert len(roots) == 1
    root = doc1["nodes"][roots[0]]
    assert root["name"] == ROOT_NODE_NAME and root["matrix"] == MINE_TO_GLTF_MATRIX
    assert root["children"] == scene_root_nodes(doc0)
    assert doc1["nodes"][: len(doc0["nodes"])] == doc0["nodes"]  # previous nodes untouched
    # never twice
    with pytest.raises(GlbFormatError, match="already carries"):
        add_root_transform(out)
    # deterministic
    assert add_root_transform(src) == out
    # the transform maps the mine frame into Y-up exactly
    np.testing.assert_allclose(
        apply_transform(QUAD, root["matrix"]),
        np.column_stack([QUAD[:, 0], QUAD[:, 2], -QUAD[:, 1]]),
    )


def test_g2_container_round_trip_and_invalid_glb_typed() -> None:
    doc, binary = split_glb(_exporter_glb())
    assert split_glb(join_glb(doc, binary)) == (doc, binary)
    for bad in (b"", b"glTF" + b"\x00" * 8, b"x" * 40):
        with pytest.raises(GlbFormatError):
            split_glb(bad)
    with pytest.raises(GlbFormatError, match="no nodes"):
        scene_root_nodes({"meshes": []})


# --------------------------------------------------------------------------- #
# packages
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("target", ["UNITY", "UNREAL"])
def test_g3_package_layout_identity_and_verbatim_documents(bundle: bytes, target: str) -> None:
    pkg = build_package(target, bundle)
    assert package_root(pkg.zip_bytes) == f"{target.lower()}_package"
    files = unzip(pkg.zip_bytes)
    src = bundle_files(bundle)
    assert files[NETWORK_OUT] == src["topology/network.json"]
    assert files[CAPABILITY_OUT] == src["semantics/capability.json"]
    assert files[TIMELINE_OUT] == src["operations/timeline.json"]
    entities = json.loads(files[ENTITIES_PATH])
    bm = bundle_manifest(bundle)
    assert [e["entityId"] for e in entities["entities"]] == [e["entityId"] for e in bm["entities"]]
    net = json.loads(src["topology/network.json"])
    edges_of = {}
    for e in net["edges"]:
        if e["geometryEntityId"]:
            edges_of.setdefault(e["geometryEntityId"], []).append(e["id"])
    for e in entities["entities"]:
        assert set(e) >= {"entityId", "kind", "levelId", "assetPath", "sourceEntityId"}
        assert "networkEdgeIds" in e
        assert e["networkEdgeIds"] == edges_of.get(e["entityId"], [])
        assert e["sourceEntityId"] == e["entityId"]
    # every bundle GLB is an asset; the synthetic bundle's GLBs are exporter GLBs (already Y-up)
    assets = sorted(p for p in files if p.startswith("scene/assets/") and p.endswith(".glb"))
    glbs = sorted(f["path"] for f in bm["files"] if f["mediaType"] == "model/gltf-binary")
    assert assets == [f"scene/assets/{p.replace('/', '_')}" for p in glbs]
    for bundle_path, asset in zip(glbs, assets, strict=True):
        assert files[asset] == src[bundle_path]  # already GLTF_Y_UP → copied verbatim
    m = manifest(files)
    assert m["details"]["rootTransformsAdded"] == 0 and m["details"]["assetsAlreadyYUp"] == 3
    settings = json.loads(files[SETTINGS_PATH])
    assert settings["targetApplication"] == target
    assert settings["rootTransformMatrixColumnMajor"] == MINE_TO_GLTF_MATRIX
    assert all(a["packageSceneFrame"] == "GLTF_Y_UP" for a in settings["assets"])
    assert m["coordinateMapping"]["targetFrame"] == "GLTF_Y_UP"
    assert m["coordinateMapping"]["transform"] == MINE_TO_GLTF_MATRIX
    assert m["coordinateMapping"]["upAxis"] == "Y"
    kinds = {a["kind"] for a in m["assumptions"]}
    assert kinds == {k for k, _ in NOT_PROVIDED_ENGINE}
    states = {s["group"]: s["state"] for s in m["sourceStates"]}
    assert states["RENDER_GLB"] == "ARTIFACT_ABSENT" and states["TIMELINE"] == "AVAILABLE"
    assert states["FIELD_LATTICE"] == "NOT_EXPORTED_BY_VERSION"
    # centerline-only entities are typed NO_ENGINE_ASSET omissions
    om = {o["subject"]: o["reasonCode"] for o in m["omissions"]}
    assert om.get("entity:ramp:main:S01") == "NO_ENGINE_ASSET"


def test_g4_copied_render_glb_is_reframed_exactly_once(bundle_with_render: bytes) -> None:
    src = bundle_files(bundle_with_render)
    entry = next(
        f
        for f in bundle_manifest(bundle_with_render)["files"]
        if f["path"] == "excavations/render/tunnel.glb"
    )
    assert entry["glb"]["sceneFrame"] == "LOCAL_ENU_Z_UP"
    assert entry["glb"]["transformMatrix"] is None
    for target in ("UNITY", "UNREAL"):
        files = unzip(build_package(target, bundle_with_render).zip_bytes)
        asset = files["scene/assets/excavations_render_tunnel.glb"]
        assert asset == add_root_transform(src["excavations/render/tunnel.glb"])
        _, bin_src = split_glb(src["excavations/render/tunnel.glb"])
        doc, bin_out = split_glb(asset)
        assert bin_out == bin_src
        assert sum(1 for n in doc["nodes"] if n.get("name") == ROOT_NODE_NAME) == 1
        m = manifest(files)
        assert m["details"]["rootTransformsAdded"] == 1 and m["details"]["assetsAlreadyYUp"] == 3
        facts = json.loads(files[SETTINGS_PATH])["assets"]
        fact = next(a for a in facts if a["assetPath"].endswith("tunnel.glb"))
        assert fact["rootTransformAdded"] is True and fact["sourceSceneFrame"] == "LOCAL_ENU_Z_UP"
        assert fact["binaryChunkPreserved"] is True
        entities = {e["entityId"]: e for e in json.loads(files[ENTITIES_PATH])["entities"]}
        assert entities["ramp:main"]["assetPath"] == "scene/assets/excavations_render_tunnel.glb"
        states = {s["group"]: s for s in m["sourceStates"]}
        assert states["RENDER_GLB"]["state"] == "AVAILABLE"
        # the absent development GLB is a named member omission, never conflated
        assert "development_mesh" in states["RENDER_GLB"]["detail"]
        om = {o["subject"]: o["reasonCode"] for o in m["omissions"]}
        assert om["renderGlb:development_mesh.json"] == "ARTIFACT_ABSENT"
        assert "renderGlb:tunnel_mesh.json" not in om


def test_g5_unity_and_unreal_differ_only_in_engine_notes(bundle: bytes) -> None:
    unity = unzip(build_package("UNITY", bundle).zip_bytes)
    unreal = unzip(build_package("UNREAL", bundle).zip_bytes)
    assert set(unity) == set(unreal)
    for path in unity:
        if path in ("adapter_manifest.json", "README.txt", SETTINGS_PATH, ENTITIES_PATH):
            continue
        assert unity[path] == unreal[path], path
    su = json.loads(unity[SETTINGS_PATH])
    sr = json.loads(unreal[SETTINGS_PATH])
    assert su["assets"] == sr["assets"] and su["engineNotes"] != sr["engineNotes"]
    assert "centimetre" in sr["engineNotes"]["units"] and "metres" in su["engineNotes"]["units"]
    eu = json.loads(unity[ENTITIES_PATH])["entities"]
    assert eu == json.loads(unreal[ENTITIES_PATH])["entities"]


def test_g6_world_only_bundle_yields_a_partial_package(mine: SyntheticMine) -> None:
    world_only = synthetic_bundle(
        mine,
        with_timeline=False,
        ramp=None,
        ramp_artifact=None,
        levels=None,
        shafts=None,
        network=None,
        capability=None,
    )
    files = unzip(build_package("UNITY", world_only).zip_bytes)
    assert NETWORK_OUT not in files and CAPABILITY_OUT not in files and TIMELINE_OUT not in files
    assets = [p for p in files if p.startswith("scene/assets/")]
    assert sorted(assets) == [
        "scene/assets/geology_faults.glb",
        "scene/assets/orebody_orebody.glb",
        "scene/assets/terrain_terrain_surface.glb",
    ]
    m = manifest(files)
    states = {s["group"]: s["state"] for s in m["sourceStates"]}
    assert states["NETWORK"] == "ARTIFACT_ABSENT" and states["EXCAVATIONS"] == "ARTIFACT_ABSENT"
    assert states["TIMELINE"] == "ARTIFACT_ABSENT"
    assert m["details"]["networkIncluded"] is False and m["details"]["timelineIncluded"] is False
    ents = json.loads(files[ENTITIES_PATH])["entities"]
    assert sorted(e["kind"] for e in ents) == ["FAULT", "OREBODY", "TERRAIN"]
    assert all(e["assetPath"] and e["networkEdgeIds"] == [] for e in ents)


def test_g7_invalid_glb_in_the_bundle_is_a_typed_conversion_failure(bundle: bytes) -> None:
    from tests.adapter_support import rehashed

    data = rehashed(bundle, {"orebody/orebody.glb": b"glTF" + b"\x00" * 30})
    with pytest.raises(AdapterConversionFailedError, match="invalid GLB") as exc:
        build_package("UNREAL", data)
    assert exc.value.subject == "orebody/orebody.glb" and exc.value.adapter == "UNREAL"


def test_g8_deterministic(bundle_with_render: bytes) -> None:
    for target in ("UNITY", "UNREAL"):
        a: Any = build_package(target, bundle_with_render).zip_bytes
        assert a == build_package(target, bundle_with_render).zip_bytes
