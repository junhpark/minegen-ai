"""Shared helpers for the Phase 23C MineResult tests: a FAST real LEGACY
design chain (the one ``test_network_api`` builds), the exported round-trip
kits and MineResult ZIP builders."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from minegen.services.scenario_service import ScenarioStore
from tests.test_exchange_bundle import TabularStack
from tests.test_smoothing_api import _decline, _prepare
from tests.test_tunnel_api import _smooth

KIT_DIR = "roundtrip"
VEHICLE_HEADER = (
    "time",
    "agentId",
    "agentKind",
    "edgeId",
    "chainageFraction",
    "status",
    "loadTonnes",
)


def write_doc(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def persisted_mine(client: TestClient, store: ScenarioStore, *, with_timeline: bool = True) -> str:
    """A REAL LEGACY design chain on the small scenario (the FAST chain
    ``test_network_api`` uses): world → access targets → Hybrid-A* decline →
    smoothing → levels → stopes → network (→ timeline). Every artifact is a
    validated backend product, so the export snapshot, the kits and the
    imports bind to genuine MineExchange ids."""
    sid = _prepare(client)
    _decline(client, sid)
    _smooth(client, sid)
    r = client.post(f"/api/v1/scenarios/{sid}/design/levels")
    assert r.status_code == 200 and r.json()["status"] == "SUCCESS", r.text
    r = client.post(f"/api/v1/scenarios/{sid}/design/stopes")
    assert r.status_code == 200 and r.json()["status"] == "SUCCESS", r.text
    r = client.post(f"/api/v1/scenarios/{sid}/network/generate")
    assert r.status_code == 200 and r.json()["status"] == "SUCCESS", r.text
    if with_timeline:
        r = client.post(f"/api/v1/scenarios/{sid}/design/timeline")
        assert r.status_code == 200 and r.json()["status"] == "SUCCESS", r.text
    assert store.derived_dir(sid).is_dir()
    return sid


def unzip(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return {n: zf.read(n) for n in zf.namelist()}


def export_kit(client: TestClient, sid: str, target: str) -> dict[str, bytes]:
    """The ``roundtrip/`` files of a live adapter export, keyed by bare name."""
    r = client.post(f"/api/v1/scenarios/{sid}/export/{target}")
    assert r.status_code == 200, r.text
    files = unzip(r.content)
    root = next(iter(files)).split("/")[0]
    prefix = f"{root}/{KIT_DIR}/"
    kit = {n[len(prefix) :]: b for n, b in files.items() if n.startswith(prefix)}
    assert "result_manifest.json" in kit, sorted(files)
    return kit


def zip_bytes(files: dict[str, bytes], *, prefix: str = KIT_DIR) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(files):
            zf.writestr(f"{prefix}/{name}" if prefix else name, files[name])
    return buf.getvalue()


def csv_text(header: list[str], rows: list[list[Any]]) -> bytes:
    lines = [",".join(header)]
    for row in rows:
        lines.append(",".join("" if v is None else str(v) for v in row))
    return ("\n".join(lines) + "\n").encode("utf-8")


def manifest_of(kit: dict[str, bytes]) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(kit["result_manifest.json"])
    return doc


def with_manifest(kit: dict[str, bytes], manifest: dict[str, Any]) -> dict[str, bytes]:
    out = dict(kit)
    out["result_manifest.json"] = json.dumps(manifest).encode("utf-8")
    return out


def post_zip(client: TestClient, sid: str, application: str, data: bytes) -> Any:
    return client.post(
        f"/api/v1/scenarios/{sid}/results/import/{application}",
        content=data,
        headers={"content-type": "application/zip"},
    )


def ventsim_package(
    kit: dict[str, bytes],
    rows: list[list[Any]],
    *,
    header: list[str] | None = None,
    manifest: dict[str, Any] | None = None,
    identity_rows: list[list[Any]] | None = None,
) -> bytes:
    files = {
        "result_manifest.json": kit["result_manifest.json"],
        "airway_results.csv": csv_text(
            header or ["edgeId", "time", "airflowM3s", "pressurePa"], rows
        ),
    }
    if identity_rows is not None:
        files["airway_identity.csv"] = csv_text(["edgeId", "ventsimUniqueNumber"], identity_rows)
    if manifest is not None:
        files = with_manifest(files, manifest)
    return zip_bytes(files)


def anylogic_package(
    kit: dict[str, bytes],
    vehicles: list[list[Any]],
    *,
    vehicle_header: list[str] | None = None,
    edge_rows: list[list[Any]] | None = None,
    edge_header: list[str] | None = None,
    summary_rows: list[list[Any]] | None = None,
    manifest: dict[str, Any] | None = None,
) -> bytes:
    files = {
        "result_manifest.json": kit["result_manifest.json"],
        "vehicle_samples.csv": csv_text(
            vehicle_header
            or [
                "time",
                "agentId",
                "agentKind",
                "edgeId",
                "chainageFraction",
                "status",
                "loadTonnes",
            ],
            vehicles,
        ),
    }
    if edge_rows is not None:
        files["edge_metrics.csv"] = csv_text(
            edge_header or ["time", "edgeId", "utilization", "queueCount"], edge_rows
        )
    if summary_rows is not None:
        files["summary_metrics.csv"] = csv_text(["metric", "value", "unit"], summary_rows)
    if manifest is not None:
        files = with_manifest(files, manifest)
    return zip_bytes(files)


class ResultsStack(TabularStack):
    """A module-scoped app + store with the FAST legacy chain persisted."""

    def build_legacy_chain(self, *, with_timeline: bool = True) -> None:
        self.sid = persisted_mine(self.client, self.store, with_timeline=with_timeline)


def scenario_state(root: Path) -> dict[str, tuple[int, int]]:
    """(size, mtime_ns) of every file under a scenario directory EXCEPT the
    results/ folder — the read-only / no-generation oracle."""
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*"))
        if p.is_file() and "results" not in p.relative_to(root).parts
    }
