"""Phase 23B adapter core — boundary, bundle integrity, five-state mapping,
typed errors, deterministic packages (directive §3–§9, §51, §63–§64).

FAST: the synthetic consistent mine is exported through the REAL exporter
into ZIP BYTES once; every adapter is driven from those bytes only.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import pathlib
import sys
import zipfile
from typing import Any

import pytest

import minegen.adapters as adapters_pkg
from minegen.adapters import ADAPTERS, AdapterError, build_package
from minegen.adapters.bundle_reader import read_mine_exchange_bundle
from minegen.adapters.common import source_state
from minegen.adapters.errors import (
    AdapterConversionFailedError,
    AdapterTargetUnsupportedError,
    MineExchangeBundleInvalidError,
    MineExchangeVersionUnsupportedError,
    RequiredSourceAbsentError,
    RequiredSourceNotSuccessError,
)
from minegen.adapters.package import MANIFEST_PATH, PackageBuilder
from minegen.exchange.bundle import BUNDLE_ROOT
from tests.exchange_fixtures import synthetic_bundle
from tests.test_exchange_corrections import SyntheticMine

TARGETS = ("VENTSIM", "ANYLOGIC", "UNITY", "UNREAL")


@pytest.fixture(scope="module")
def mine() -> SyntheticMine:
    return SyntheticMine()


@pytest.fixture(scope="module")
def bundle(mine: SyntheticMine) -> bytes:
    return synthetic_bundle(mine)


@pytest.fixture(scope="module")
def bundle_1_2_shape(mine: SyntheticMine) -> bytes:
    """A bundle WITHOUT a timeline (the 1.2 content shape under the 1.3 version)."""
    return synthetic_bundle(mine, with_timeline=False)


def unzip(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        root = names[0].split("/", 1)[0]
        assert all(n.startswith(root + "/") for n in names)
        return {n.split("/", 1)[1]: zf.read(n) for n in names}


def manifest_of(bundle: bytes) -> dict[str, Any]:
    with zipfile.ZipFile(io.BytesIO(bundle)) as zf:
        doc: dict[str, Any] = json.loads(zf.read(f"{BUNDLE_ROOT}/manifest.json"))
    return doc


def rezip(
    data: bytes, mutate: dict[str, bytes | None], *, names: dict[str, str] | None = None
) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        entries = {n: zf.read(n) for n in zf.namelist()}
    for path, content in mutate.items():
        key = f"{BUNDLE_ROOT}/{path}"
        if content is None:
            entries.pop(key)
        else:
            entries[key] = content
    for old, new in (names or {}).items():
        entries[new] = entries.pop(f"{BUNDLE_ROOT}/{old}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n in sorted(entries):
            zf.writestr(n, entries[n])
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# §63 architecture boundary — bytes in, no MineGen service, no derived/*
# --------------------------------------------------------------------------- #

FORBIDDEN_IMPORT_PREFIXES = (
    "minegen.services",
    "minegen.api",
    "minegen.design",
    "minegen.layout",
    "minegen.levels",
    "minegen.scheduling.builder",
    "minegen.world",
    "minegen.mining",
    "minegen.analysis",
    "minegen.network.builder",
)
FORBIDDEN_TOKENS = ("ScenarioStore", "ArtifactReader", "DesignService", "derived/", "scenario.json")


def _adapter_sources() -> list[pathlib.Path]:
    root = pathlib.Path(adapters_pkg.__file__).parent
    return sorted(root.rglob("*.py"))


def test_b63_adapters_import_no_minegen_service_or_artifact_authority() -> None:
    assert _adapter_sources()
    for path in _adapter_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert not name.startswith(FORBIDDEN_IMPORT_PREFIXES), (path.name, name)
        # Prose (docstrings) may NAME the forbidden authorities to state the
        # boundary; code never references them: scan names, attributes and
        # non-docstring string constants only.
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Name | ast.Attribute):
                ident = node.id if isinstance(node, ast.Name) else node.attr
                assert ident not in FORBIDDEN_TOKENS, (path.name, ident)
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                for token in FORBIDDEN_TOKENS:
                    assert token not in node.value, (path.name, token, node.value)


def test_b63_every_adapter_builds_from_saved_bundle_bytes_without_services(
    bundle: bytes, tmp_path: pathlib.Path
) -> None:
    fixture = tmp_path / "mine_exchange_fixture.zip"
    fixture.write_bytes(bundle)
    loaded = fixture.read_bytes()
    before = {m for m in sys.modules if m.startswith("minegen.services")}
    for target in TARGETS:
        pkg = build_package(target, loaded)
        assert pkg.manifest.target_application == target
        assert pkg.manifest.adapter_name == target and pkg.manifest.adapter_version == "0.1.0"
        assert pkg.manifest.source_mine_exchange_version == "1.3.0"
    # the adapter import graph never pulled a MineGen service in
    after = {m for m in sys.modules if m.startswith("minegen.services")}
    assert after == before
    assert set(ADAPTERS) == set(TARGETS)


def test_unknown_target_is_a_typed_422(bundle: bytes) -> None:
    with pytest.raises(AdapterTargetUnsupportedError) as exc:
        build_package("VENTSIM_PRO", bundle)
    assert exc.value.code == "ADAPTER_TARGET_UNSUPPORTED" and exc.value.http_status == 422


# --------------------------------------------------------------------------- #
# §64 bundle integrity — typed refusals
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("target", TARGETS)
def test_b64_bundle_integrity_refusals(bundle: bytes, target: str) -> None:
    def refused(data: bytes, match: str) -> None:
        with pytest.raises(MineExchangeBundleInvalidError, match=match) as exc:
            build_package(target, data)
        assert exc.value.code == "ADAPTER_MINEEXCHANGE_BUNDLE_INVALID"
        assert exc.value.http_status == 409

    refused(rezip(bundle, {"excavations/centerlines.csv": b"entityId\n"}), "SHA-256 mismatch")
    refused(rezip(bundle, {"topology/network.json": None}), "not in the ZIP")
    refused(rezip(bundle, {"extra/unlisted.txt": b"x"}), "not listed in the manifest")
    refused(
        rezip(bundle, {}, names={"README.txt": f"{BUNDLE_ROOT}/../escape.txt"}), "unsafe|not a file"
    )
    refused(b"not a zip", "not a ZIP")
    broken = manifest_of(bundle)
    broken.pop("entities")
    refused(rezip(bundle, {"manifest.json": json.dumps(broken).encode()}), "malformed manifest")
    doc = manifest_of(bundle)
    doc["files"].append(dict(doc["files"][0]))  # duplicate path
    refused(rezip(bundle, {"manifest.json": json.dumps(doc).encode()}), "listed twice")


def test_b64_duplicate_zip_path_is_refused(bundle: bytes) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(bundle)) as src, zipfile.ZipFile(buf, "w") as dst:
        for n in src.namelist():
            dst.writestr(n, src.read(n))
        dst.writestr(f"{BUNDLE_ROOT}/README.txt", b"dup")
    with pytest.raises(MineExchangeBundleInvalidError, match="duplicate ZIP entry"):
        read_mine_exchange_bundle(buf.getvalue())


@pytest.mark.parametrize(
    ("target", "version"),
    [
        ("VENTSIM", "1.1.0"),
        ("VENTSIM", "2.0.0"),
        ("ANYLOGIC", "1.2.0"),
        ("UNITY", "0.9.0"),
        ("UNREAL", "1.2"),
    ],
)
def test_b64_unsupported_mine_exchange_version_is_refused(
    bundle: bytes, target: str, version: str
) -> None:
    doc = manifest_of(bundle)
    doc["mineExchangeVersion"] = version
    data = rezip(bundle, {"manifest.json": json.dumps(doc).encode()})
    with pytest.raises(MineExchangeVersionUnsupportedError) as exc:
        build_package(target, data)
    assert exc.value.code == "ADAPTER_MINEEXCHANGE_VERSION_UNSUPPORTED"
    assert exc.value.adapter == target and exc.value.subject == "manifest.mineExchangeVersion"


def test_b64_semantic_document_validated_against_its_dto(bundle: bytes) -> None:
    net = json.loads(unzip(bundle)["topology/network.json"])
    net["edges"][0]["sourceNodeId"] = "NOPE"
    data = rezip(bundle, {"topology/network.json": json.dumps(net).encode()})
    # the hash changes → integrity refusal first (the manifest is the authority)
    with pytest.raises(MineExchangeBundleInvalidError, match="SHA-256"):
        build_package("VENTSIM", data)
    # with a re-hashed manifest the DTO / referential check catches it
    doc = manifest_of(bundle)
    body = json.dumps(net).encode()
    for f in doc["files"]:
        if f["path"] == "topology/network.json":
            f["sha256"] = hashlib.sha256(body).hexdigest()
    data = rezip(bundle, {"topology/network.json": body, "manifest.json": json.dumps(doc).encode()})
    with pytest.raises(MineExchangeBundleInvalidError, match="unknown node") as exc:
        build_package("VENTSIM", data)
    assert exc.value.source_group == "NETWORK" and exc.value.subject == "RAMP:S01"


# --------------------------------------------------------------------------- #
# §6 five-state mapping + §51 error detail
# --------------------------------------------------------------------------- #


def test_five_state_source_mapping(bundle: bytes, bundle_1_2_shape: bytes) -> None:
    b = read_mine_exchange_bundle(bundle)
    assert source_state(b, "NETWORK", consumed=True, detail_when_available="x").state == "AVAILABLE"
    assert (
        source_state(b, "NETWORK", consumed=False, detail_when_available="x").state
        == "UNSUPPORTED_BY_ADAPTER"
    )
    fl = source_state(b, "FIELD_LATTICE", consumed=True, detail_when_available="x")
    assert fl.state == "NOT_EXPORTED_BY_VERSION" and fl.bundle_reason_code == "NOT_IN_V1"
    st = source_state(b, "STOPES", consumed=True, detail_when_available="x")
    assert st.state == "ARTIFACT_ABSENT" and st.bundle_reason_code == "ARTIFACT_ABSENT"
    b12 = read_mine_exchange_bundle(bundle_1_2_shape)
    tl = source_state(b12, "TIMELINE", consumed=True, detail_when_available="x")
    assert tl.state == "ARTIFACT_ABSENT"  # 1.3: never NOT_IN_V1 / never conflated with absence
    states = {s.group: s.state for s in build_package("VENTSIM", bundle).manifest.source_states}
    assert set(states.values()) <= {
        "AVAILABLE",
        "ARTIFACT_ABSENT",
        "SOURCE_NOT_SUCCESS",
        "NOT_EXPORTED_BY_VERSION",
        "UNSUPPORTED_BY_ADAPTER",
    }
    assert states["FIELD_LATTICE"] == "NOT_EXPORTED_BY_VERSION"


def test_required_source_absent_and_not_success_are_distinct_typed_errors(
    mine: SyntheticMine, bundle_1_2_shape: bytes
) -> None:
    with pytest.raises(RequiredSourceAbsentError) as absent:
        build_package("ANYLOGIC", bundle_1_2_shape)
    assert absent.value.code == "ADAPTER_REQUIRED_SOURCE_ABSENT"
    assert absent.value.adapter == "ANYLOGIC" and absent.value.source_group == "TIMELINE"
    assert "ARTIFACT_ABSENT" in absent.value.detail and "adapter=ANYLOGIC" in absent.value.detail
    from minegen.exchange.builder import ArtifactInput
    from tests.exchange_fixtures import consistent_network

    failed_net = {**consistent_network(), "status": "FAILED", "failureReason": "no ramp"}
    data = synthetic_bundle(
        mine, with_timeline=False, network=ArtifactInput(failed_net, "r-net-failed")
    )
    with pytest.raises(RequiredSourceNotSuccessError) as bad:
        build_package("VENTSIM", data)
    assert bad.value.code == "ADAPTER_SOURCE_NOT_SUCCESS" and "no ramp" in bad.value.detail
    assert bad.value.source_group == "NETWORK"


def test_error_detail_names_adapter_group_subject_reason() -> None:
    err = AdapterConversionFailedError(
        "end points detached", adapter="VENTSIM", source_group="NETWORK", subject="RAMP:S01"
    )
    assert isinstance(err, AdapterError)
    assert (
        err.detail == "adapter=VENTSIM; group=NETWORK; subject=RAMP:S01; reason=end points detached"
    )
    assert str(err).startswith("ADAPTER_CONVERSION_FAILED: ")


# --------------------------------------------------------------------------- #
# §9 deterministic package writer
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("target", TARGETS)
def test_b9_package_is_deterministic_hashed_and_wall_clock_free(bundle: bytes, target: str) -> None:
    a = build_package(target, bundle)
    b = build_package(target, bundle)
    assert a.zip_bytes == b.zip_bytes
    files = unzip(a.zip_bytes)
    manifest = json.loads(files[MANIFEST_PATH])
    listed = {f["path"]: f["sha256"] for f in manifest["generatedFiles"]}
    assert set(listed) == set(files) - {MANIFEST_PATH}
    for path, digest in listed.items():
        assert hashlib.sha256(files[path]).hexdigest() == digest, path
    text = files[MANIFEST_PATH].decode() + files["README.txt"].decode()
    assert "generatedAt" not in text and "/home/" not in text and "/tmp/" not in text
    with zipfile.ZipFile(io.BytesIO(a.zip_bytes)) as zf:
        assert {i.date_time for i in zf.infolist()} == {(1980, 1, 1, 0, 0, 0)}
        assert [i.filename for i in zf.infolist()] == sorted(i.filename for i in zf.infolist())
    assert manifest["sourceSnapshot"]["scenarioRevision"] == "s1"
    assert (
        manifest["adapterVersion"] == "0.1.0" and manifest["sourceMineExchangeVersion"] == "1.3.0"
    )


def test_b9_package_builder_refuses_duplicate_and_unsafe_paths() -> None:
    pkg = PackageBuilder(root="x_package", adapter="VENTSIM")
    pkg.add("a/b.csv", b"1", target_semantic="T", source_files=[])
    with pytest.raises(AdapterConversionFailedError, match="duplicate"):
        pkg.add("a/b.csv", b"2", target_semantic="T", source_files=[])
    with pytest.raises(AdapterConversionFailedError):
        pkg.add("../escape.csv", b"2", target_semantic="T", source_files=[])
    with pytest.raises(AdapterConversionFailedError, match="duplicate"):
        pkg.add(MANIFEST_PATH, b"{}", target_semantic="T", source_files=[])
