"""Phase 23A — MineExchange format writers, coordinate contract and bundle
integrity (directive §M, §C, §T and the geometry QA helpers).

Every writer is pure; every round-trip below reads the written bytes back
with an INDEPENDENT reader (own STL / OBJ / ASC / CSV / DXF parsers, the
Phase 06 ``read_glb`` container reader) — never the writer's own state.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from typing import Any, cast

import numpy as np
import pytest

from minegen.design.glb_writer import read_glb
from minegen.exchange.builder import BundleFile, BundleSpec
from minegen.exchange.bundle import (
    BUNDLE_ROOT,
    BundlePathError,
    build_manifest,
    safe_relative_path,
    write_bundle,
)
from minegen.exchange.formats.asc import read_esri_ascii_grid, write_esri_ascii_grid
from minegen.exchange.formats.csv_table import read_csv, write_csv
from minegen.exchange.formats.dxf import (
    DxfDocument,
    DxfPolygon,
    DxfPolyline,
    read_dxf_entities,
    write_dxf,
)
from minegen.exchange.formats.glb import (
    MINE_TO_GLTF_MATRIX,
    apply_transform,
    inverse_transform,
    write_mesh_glb,
)
from minegen.exchange.formats.json_document import dumps
from minegen.exchange.formats.obj import read_obj, write_obj
from minegen.exchange.formats.stl import (
    concatenate_stl_triangles,
    read_binary_stl,
    write_binary_stl,
)
from minegen.exchange.geometry.qa import mesh_qa
from minegen.exchange.geometry.terrain import terrain_grid_rows, terrain_surface
from minegen.exchange.models import COORDINATE_FRAME, ExchangeEntity, SourceSnapshot
from minegen.world.terrain import Terrain

CANONICAL = np.array([[10.0, 20.0, 30.0]])


def _cube() -> tuple[np.ndarray, np.ndarray]:
    """Unit cube, outward-oriented, 12 triangles."""
    p = np.array(
        [
            [0, 0, 0],
            [1, 0, 0],
            [1, 1, 0],
            [0, 1, 0],
            [0, 0, 1],
            [1, 0, 1],
            [1, 1, 1],
            [0, 1, 1],
        ],
        dtype=np.float64,
    )
    t = np.array(
        [
            [0, 2, 1],
            [0, 3, 2],  # bottom (-z)
            [4, 5, 6],
            [4, 6, 7],  # top (+z)
            [0, 1, 5],
            [0, 5, 4],  # front (-y)
            [1, 2, 6],
            [1, 6, 5],  # right (+x)
            [2, 3, 7],
            [2, 7, 6],  # back (+y)
            [3, 0, 4],
            [3, 4, 7],  # left (-x)
        ],
        dtype=np.int64,
    )
    return p, t


# --------------------------------------------------------------------------- #
# C — coordinate contract
# --------------------------------------------------------------------------- #


def test_c1_stl_stores_canonical_coordinates_and_round_trips() -> None:
    p = np.array([[10.0, 20.0, 30.0], [11.0, 20.0, 30.0], [10.0, 21.0, 30.0]])
    t = np.array([[0, 1, 2]])
    data = write_binary_stl(p, t, header="minegen")
    tris, normals = read_binary_stl(data)
    assert tris.shape == (1, 3, 3)
    np.testing.assert_array_equal(tris[0], p)  # float32-exact for these values
    np.testing.assert_allclose(normals[0], [0.0, 0.0, 1.0])
    assert len(data) == 84 + 50 * 1


def test_c1_obj_and_csv_and_dxf_store_canonical_coordinates() -> None:
    p, t = _cube()
    p = p + CANONICAL
    text = write_obj(p, t, "cube")
    rp, rt, name = read_obj(text)
    np.testing.assert_array_equal(rp, p)
    np.testing.assert_array_equal(rt, t)
    assert name == "cube"

    csv_text = write_csv(["x", "y", "z"], [[10.0, 20.0, 30.0]])
    header, rows = read_csv(csv_text)
    assert header == ["x", "y", "z"] and [float(v) for v in rows[0]] == [10.0, 20.0, 30.0]

    doc = DxfDocument(polylines=[DxfPolyline("ramp:main", "RAMP", CANONICAL)])
    dxf_text, _mapping = write_dxf(doc)
    ents = read_dxf_entities(dxf_text)
    assert len(ents) == 1 and ents[0]["type"] == "POLYLINE"
    np.testing.assert_array_equal(ents[0]["points"], CANONICAL)


def test_c2_glb_root_transform_maps_canonical_to_y_up() -> None:
    np.testing.assert_allclose(
        apply_transform(CANONICAL, MINE_TO_GLTF_MATRIX), [[10.0, 30.0, -20.0]]
    )


def test_c3_glb_inverse_transform_round_trips_and_stored_vertices_are_canonical() -> None:
    p, t = _cube()
    p = p + CANONICAL
    glb = write_mesh_glb(
        p, [("body", t, {"entityId": "x"})], name="x", node_extras={"entityId": "x"}
    )
    raw, blob = read_glb(glb)
    doc = cast(dict[str, Any], raw)
    nodes = doc["nodes"]
    assert isinstance(nodes, list) and nodes[0]["matrix"] == MINE_TO_GLTF_MATRIX
    assert nodes[0]["extras"]["entityId"] == "x"
    accessors = doc["accessors"]
    views = doc["bufferViews"]
    prim = doc["meshes"][0]["primitives"][0]
    acc = accessors[prim["attributes"]["POSITION"]]
    view = views[acc["bufferView"]]
    off = view["byteOffset"] + acc.get("byteOffset", 0)
    stored = np.frombuffer(blob[off : off + acc["count"] * 12], dtype=np.float32).reshape(-1, 3)
    np.testing.assert_array_equal(stored.astype(np.float64), p)  # canonical, untransformed
    world = apply_transform(stored.astype(np.float64), nodes[0]["matrix"])
    np.testing.assert_allclose(inverse_transform(world, nodes[0]["matrix"]), p, atol=1e-12)
    # the transform is a proper rotation (det +1): the mesh stays right-handed
    m = np.asarray(MINE_TO_GLTF_MATRIX).reshape(4, 4).T
    assert np.isclose(np.linalg.det(m[:3, :3]), 1.0)


def test_glb_without_root_transform_has_no_matrix() -> None:
    p, t = _cube()
    glb = write_mesh_glb(p, [("b", t, {})], name="b", node_extras={}, root_transform=False)
    raw, _ = read_glb(glb)
    assert "matrix" not in cast(dict[str, Any], raw)["nodes"][0]


# --------------------------------------------------------------------------- #
# T — terrain grid
# --------------------------------------------------------------------------- #


def _four_corner_terrain() -> Terrain:
    # SW = 11, SE = 22, NW = 33, NE = 44 (x east, y north); nx = ny = 2
    z = np.array([[11.0, 33.0], [22.0, 44.0]])  # z[i, j] with i → x, j → y
    return Terrain(x0=-5.0, y0=-5.0, spacing=10.0, z=z)


def test_t1_terrain_csv_round_trip_is_lossless() -> None:
    t = Terrain(x0=-7.5, y0=3.25, spacing=2.5, z=np.random.default_rng(3).normal(size=(4, 3)))
    rows = terrain_grid_rows(t)
    text = write_csv(["i", "j", "x", "y", "z"], rows)
    header, parsed = read_csv(text)
    assert header == ["i", "j", "x", "y", "z"] and len(parsed) == 12
    z = np.zeros((4, 3))
    for i, j, x, y, zz in parsed:
        ii, jj = int(i), int(j)
        assert float(x) == t.x0 + ii * t.spacing and float(y) == t.y0 + jj * t.spacing
        z[ii, jj] = float(zz)
    np.testing.assert_array_equal(z, t.z)  # repr() floats: exact


def test_t2_asc_four_corner_orientation() -> None:
    t = _four_corner_terrain()
    text = write_esri_ascii_grid(t.x0, t.y0, t.spacing, t.z)
    body = [ln for ln in text.splitlines() if not ln[:1].isalpha()]
    # first data row is the NORTH-most row, left → right = west → east
    assert [float(v) for v in body[0].split()] == [33.0, 44.0]
    assert [float(v) for v in body[1].split()] == [11.0, 22.0]
    x0, y0, sp, z = read_esri_ascii_grid(text)
    assert (x0, y0, sp) == (-5.0, -5.0, 10.0)
    assert z[0, 0] == 11 and z[1, 0] == 22 and z[0, 1] == 33 and z[1, 1] == 44


def test_t3_asc_shape_spacing_origin_round_trip() -> None:
    t = Terrain(x0=-12.5, y0=100.0, spacing=12.5, z=np.random.default_rng(1).normal(size=(6, 4)))
    text = write_esri_ascii_grid(t.x0, t.y0, t.spacing, t.z)
    head = dict(ln.split() for ln in text.splitlines()[:6])
    assert head["ncols"] == "6" and head["nrows"] == "4" and head["cellsize"] == "12.5"
    assert "xllcenter" in head and "yllcenter" in head
    x0, y0, sp, z = read_esri_ascii_grid(text)
    assert (x0, y0, sp) == (t.x0, t.y0, t.spacing) and z.shape == (6, 4)
    np.testing.assert_array_equal(z, t.z)


def test_t4_t5_terrain_tin_vertices_are_the_nodes_and_the_surface_is_open() -> None:
    t = Terrain(x0=0.0, y0=0.0, spacing=1.0, z=np.arange(12, dtype=np.float64).reshape(4, 3))
    positions, triangles = terrain_surface(t)
    np.testing.assert_array_equal(positions, t.positions_flat())
    assert triangles.shape == (2 * 3 * 2, 3)  # 2 triangles per cell
    qa = mesh_qa(positions, triangles)
    assert qa.finite and qa.valid_indices and qa.degenerate_triangles == 0
    assert qa.manifold and not qa.watertight and qa.consistent_orientation
    assert qa.boundary_edges == 2 * (3 + 2)  # perimeter edges of a 3×2-cell grid
    # every triangle faces +Z (counter-clockwise seen from above)
    a, b, c = positions[triangles[:, 0]], positions[triangles[:, 1]], positions[triangles[:, 2]]
    assert np.all(np.cross(b - a, c - a)[:, 2] > 0)


# --------------------------------------------------------------------------- #
# mesh QA
# --------------------------------------------------------------------------- #


def test_mesh_qa_closed_cube_and_open_square() -> None:
    p, t = _cube()
    qa = mesh_qa(p, t)
    assert qa.closed_solid and qa.watertight and qa.manifold and qa.consistent_orientation
    assert np.isclose(qa.signed_volume, 1.0) and qa.triangle_count == 12 and qa.vertex_count == 8
    open_qa = mesh_qa(p, t[2:])  # bottom removed → boundary
    assert not open_qa.watertight and not open_qa.closed_solid and open_qa.boundary_edges == 4
    flipped = t.copy()
    flipped[0] = flipped[0][::-1]
    bad = mesh_qa(p, flipped)
    assert not bad.consistent_orientation and not bad.closed_solid
    inverted = mesh_qa(p, t[:, ::-1])
    assert inverted.watertight and inverted.signed_volume < 0 and not inverted.closed_solid
    nan = mesh_qa(np.array([[np.nan, 0, 0], [1, 0, 0], [0, 1, 0]]), np.array([[0, 1, 2]]))
    assert not nan.finite and not nan.closed_solid


def test_stl_multibody_concatenation_keeps_component_ranges() -> None:
    p, t = _cube()
    positions, triangles, ranges = concatenate_stl_triangles([(p, t), (p + 5.0, t[:4])])
    assert ranges == [(0, 12), (12, 4)] and triangles.shape == (16, 3)
    assert positions.shape == (16, 3) and triangles.max() == 15
    tris, _ = read_binary_stl(write_binary_stl(positions, triangles))
    assert tris.shape == (16, 3, 3)
    np.testing.assert_array_equal(tris[12], p[t[0]] + 5.0)


# --------------------------------------------------------------------------- #
# DXF — independent parser
# --------------------------------------------------------------------------- #


def test_dxf_polylines_layers_and_handle_mapping_round_trip() -> None:
    a = np.array([[0.0, 0.0, 0.0], [10.0, 0.0, -1.0], [10.0, 10.0, -2.0]])
    b = np.array([[1.5, 2.5, 3.5], [4.5, 5.5, 6.5]])
    tri = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [-1.0, 1.0, 0.0]])
    doc = DxfDocument(
        polylines=[DxfPolyline("ramp:main:S01", "RAMP", a), DxfPolyline("drift:L01", "DRIFT", b)],
        polygons=[DxfPolygon("fault:F01", "FAULT", tri)],
    )
    text, mapping = write_dxf(doc)
    assert text.startswith("  0\nSECTION") and text.rstrip().endswith("  0\nEOF")
    ents = read_dxf_entities(text)
    polys = [e for e in ents if e["type"] == "POLYLINE"]
    faces = [e for e in ents if e["type"] == "3DFACE"]
    assert len(polys) == 2 and len(faces) == 2  # 4-gon → 2 fan triangles
    np.testing.assert_array_equal(polys[0]["points"], a)
    np.testing.assert_array_equal(polys[1]["points"], b)
    assert polys[0]["layer"] == "RAMP" and polys[1]["layer"] == "DRIFT" and polys[0]["flags"] == 8
    by_handle = {m["handle"]: m for m in mapping}
    assert by_handle[polys[0]["handle"]]["entityId"] == "ramp:main:S01"
    assert by_handle[polys[1]["handle"]]["entityId"] == "drift:L01"
    assert all(by_handle[f["handle"]]["entityId"] == "fault:F01" for f in faces)
    assert len({m["handle"] for m in mapping}) == len(mapping)  # unique handles
    # the layer table declares every layer used
    assert "\nRAMP\n" in text and "\nDRIFT\n" in text and "\nFAULT\n" in text


def test_dxf_writer_is_deterministic_and_ascii() -> None:
    doc = DxfDocument(polylines=[DxfPolyline("x", "RAMP", CANONICAL)])
    t1, m1 = write_dxf(doc)
    t2, m2 = write_dxf(doc)
    assert t1 == t2 and m1 == m2
    t1.encode("ascii")


# --------------------------------------------------------------------------- #
# M — bundle determinism, integrity, no hidden files, path safety
# --------------------------------------------------------------------------- #


def _spec() -> BundleSpec:
    p, t = _cube()
    return BundleSpec(
        scenario_id="abc123",
        scenario_name="unit",
        source_snapshot=SourceSnapshot(
            scenario_revision="r1",
            arrays_revision="r2",
            active_ramp_source="LEGACY",
            artifact_revisions={},
        ),
        files=[
            BundleFile(
                "orebody/orebody.stl",
                write_binary_stl(p, t),
                "OREBODY",
                "DERIVED_SURFACE_OF_SOLID",
                ["orebody:primary"],
                None,
                None,
                True,
            ),
            BundleFile(
                "terrain/terrain_grid.csv",
                write_csv(["i"], [[1]]).encode(),
                "TERRAIN_GRID",
                "NODE_GRID",
                ["terrain:surface"],
                None,
                None,
                False,
            ),
        ],
        entities=[
            ExchangeEntity(
                entity_id="orebody:primary",
                kind="OREBODY",
                source_artifact="scenario.json",
                source_id="orebody",
                files=["orebody/orebody.stl"],
            ),
            ExchangeEntity(
                entity_id="terrain:surface",
                kind="TERRAIN",
                source_artifact="arrays.npz",
                source_id="terrain",
                files=["terrain/terrain_grid.csv"],
            ),
        ],
        omissions=[],
        notes=[],
    )


def test_m1_bundle_bytes_are_deterministic() -> None:
    z1, m1 = write_bundle(_spec())
    z2, m2 = write_bundle(_spec())
    assert z1 == z2
    assert m1.model_dump() == m2.model_dump()
    with zipfile.ZipFile(io.BytesIO(z1)) as zf:
        infos = zf.infolist()
        assert [i.filename for i in infos] == sorted(i.filename for i in infos)
        assert all(i.date_time == (1980, 1, 1, 0, 0, 0) for i in infos)
        assert all(i.filename.startswith(f"{BUNDLE_ROOT}/") for i in infos)
    manifest_text = json.dumps(m1.model_dump(mode="json", by_alias=True))
    assert "generatedAt" not in manifest_text and "/home/" not in manifest_text


def test_m2_m3_manifest_hashes_match_and_no_unlisted_files() -> None:
    z, manifest = write_bundle(_spec())
    with zipfile.ZipFile(io.BytesIO(z)) as zf:
        entries = {n[len(BUNDLE_ROOT) + 1 :]: zf.read(n) for n in zf.namelist()}
    listed = {f.path: f for f in manifest.files}
    assert "README.txt" in listed and "manifest.json" not in listed
    for path, f in listed.items():
        assert path in entries, path
        assert hashlib.sha256(entries[path]).hexdigest() == f.sha256
    assert set(entries) - set(listed) == {"manifest.json"}
    doc = json.loads(entries["manifest.json"])
    assert doc["mineExchangeVersion"] == "1.0.0"
    assert doc["coordinateSystem"]["name"] == COORDINATE_FRAME
    assert doc["coordinateSystem"]["crs"] == "LOCAL_SYNTHETIC"
    assert doc["units"]["length"] == "metre"
    assert {f["path"] for f in doc["files"]} == set(listed)


@pytest.mark.parametrize(
    "bad",
    ["../x.stl", "/abs/x.stl", "a/../../x", "a\\b.stl", "C:/x", "", "a//b", "./a"],
)
def test_m4_unsafe_bundle_paths_are_refused(bad: str) -> None:
    with pytest.raises(BundlePathError):
        safe_relative_path(bad)


def test_m4_safe_paths_pass_and_duplicates_are_refused() -> None:
    assert (
        safe_relative_path("excavations/solids/ramp_main.stl") == "excavations/solids/ramp_main.stl"
    )
    spec = _spec()
    spec.files.append(spec.files[0])
    with pytest.raises(BundlePathError):
        write_bundle(spec)
    spec = _spec()
    spec.files[0].path = "../escape.stl"
    with pytest.raises(BundlePathError):
        build_manifest(spec)


def test_json_document_is_canonical_and_finite() -> None:
    assert dumps({"b": 1, "a": [1.5, "x"]}) == dumps({"a": [1.5, "x"], "b": 1})
    with pytest.raises(ValueError):
        dumps({"x": float("nan")})
