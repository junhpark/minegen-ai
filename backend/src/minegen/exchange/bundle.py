"""Deterministic ZIP bundle + manifest integrity.

ZIP rules: lexicographic entry order, fixed entry timestamp (1980-01-01),
fixed DEFLATE settings, relative normalized paths under ``mine_exchange/``,
no absolute paths, no wall-clock values in the semantic manifest. The same
``BundleSpec`` therefore yields the same bytes.
"""

from __future__ import annotations

import hashlib
import io
import posixpath
import zipfile

from minegen.exchange.builder import BundleSpec, preflight_bundle
from minegen.exchange.errors import ExchangeExportError
from minegen.exchange.formats.json_document import dumps
from minegen.exchange.models import (
    MINE_EXCHANGE_VERSION,
    CoordinateSystem,
    ExchangeFile,
    ExchangeManifest,
)

BUNDLE_ROOT = "mine_exchange"
MANIFEST_PATH = "manifest.json"
README_PATH = "README.txt"
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


class BundlePathError(ExchangeExportError, ValueError):
    """An unsafe or duplicated bundle path — typed (409), still a ValueError
    for callers that treat path validation generically."""


def safe_relative_path(path: str) -> str:
    """Reject absolute, drive and traversal paths; normalize separators."""
    if (
        not path
        or "\\" in path
        or path.startswith("/")
        or (":" in path.split("/", 1)[0] and len(path.split("/", 1)[0]) == 2)
    ):
        raise BundlePathError(f"unsafe bundle path {path!r}")
    norm = posixpath.normpath(path)
    if norm.startswith("..") or "/../" in f"/{norm}/" or norm != path:
        raise BundlePathError(f"unsafe bundle path {path!r}")
    return norm


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_manifest(spec: BundleSpec) -> ExchangeManifest:
    files = [
        ExchangeFile(
            path=safe_relative_path(f.path),
            sha256=sha256_hex(f.data),
            media_type=f.media_type,
            semantic_type=f.semantic_type,
            representation=f.representation,
            source_entity_ids=list(f.source_entity_ids),
            source_artifact=f.source_artifact,
            source_revision=f.source_revision,
            coordinate_frame=f.coordinate_frame,
            derived=f.derived,
            geometry=f.geometry,
            glb=f.glb,
            components=f.components,
            dxf_entities=f.dxf_entities,
            notes=list(f.notes),
        )
        for f in spec.files
    ]
    return ExchangeManifest(
        mine_exchange_version=MINE_EXCHANGE_VERSION,
        scenario_id=spec.scenario_id,
        scenario_name=spec.scenario_name,
        coordinate_system=CoordinateSystem(),
        units={"length": "metre", "angle": "degree", "volume": "cubic metre"},
        source_snapshot=spec.source_snapshot,
        entities=list(spec.entities),
        files=files,
        omissions=list(spec.omissions),
        extensions={},
        notes=list(spec.notes),
    )


def readme_text(manifest: ExchangeManifest) -> str:
    groups = sorted({f.path.split("/", 1)[0] for f in manifest.files})
    lines = [
        f"MineExchange {manifest.mine_exchange_version} — MineGen scenario "
        f"{manifest.scenario_id} ({manifest.scenario_name})",
        "",
        "manifest.json is the meaning authority of this bundle: every file's coordinate frame,",
        "units, provenance, representation semantics and QA facts are declared there.",
        "",
        f"Coordinate frame: {manifest.coordinate_system.name} (X east, Y north, Z up), unit metre,",
        "CRS LOCAL_SYNTHETIC (no real-world georeference).",
        "Two kinds of GLB exist and the manifest declares which is which (files[].glb):",
        "  - exporter-created GLBs (terrain_surface.glb, orebody.glb, faults.glb):",
        "    storedVertexFrame = LOCAL_ENU_Z_UP, sceneFrame = GLTF_Y_UP; the root node",
        "    carries the mine -> glTF transform (x, y, z) -> (x, z, -y) as transformMatrix.",
        "  - copied production render GLBs (excavations/render/*.glb): the production",
        "    bytes verbatim; storedVertexFrame = sceneFrame = LOCAL_ENU_Z_UP and",
        "    transformMatrix = null (the consumer applies the rotation itself); their",
        "    junctionApertures flag comes from the source junction report (true / false /",
        "    null = unknown), never assumed.",
        "Shafts are represented by centerlines only (axis segments + station drives);",
        "a shaft:<id> entity is an aggregate parent with no geometry file of its own.",
        "",
        "Included groups: " + ", ".join(groups),
        "Omissions:",
        *[f"  - {o.group}: {o.reason_code} — {o.detail}" for o in manifest.omissions],
        "",
        "Excavation solids are individually closed but overlap at junctions and are NOT",
        "boolean-unioned; mine_multibody.stl is a concatenation for convenience only.",
        "Capability and egress content are design advisories, never statutory claims.",
        "",
    ]
    return "\n".join(lines)


def write_bundle(spec: BundleSpec) -> tuple[bytes, ExchangeManifest]:
    """→ (zip bytes, manifest). The README and manifest are added after the
    payload files; README is listed in the manifest, the manifest itself
    describes the OTHER files and is not self-listed."""
    preflight_bundle(spec)  # typed referential integrity before any byte is written
    manifest = build_manifest(spec)
    readme = readme_text(manifest).encode("utf-8")
    manifest.files.append(
        ExchangeFile(
            path=README_PATH,
            sha256=sha256_hex(readme),
            media_type="text/plain",
            semantic_type="README",
            representation="DOCUMENT",
            source_entity_ids=[],
            source_artifact=None,
            source_revision=None,
            coordinate_frame=spec.files[0].coordinate_frame if spec.files else "LOCAL_ENU_Z_UP",
            derived=True,
        )
    )
    manifest.files.sort(key=lambda f: f.path)
    payload: dict[str, bytes] = {f.path: f.data for f in spec.files}
    if len(payload) != len(spec.files):
        raise BundlePathError("duplicate bundle path")  # unreachable after preflight
    payload[README_PATH] = readme
    payload[MANIFEST_PATH] = dumps(manifest.model_dump(mode="json", by_alias=True))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path in sorted(payload):
            info = zipfile.ZipInfo(f"{BUNDLE_ROOT}/{safe_relative_path(path)}", date_time=_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o644 & 0xFFFF) << 16
            info.create_system = 3
            zf.writestr(info, payload[path], compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
    return buf.getvalue(), manifest
