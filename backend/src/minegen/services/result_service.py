"""MineResult service (Phase 23C, directive §11–§24, §45–§57, rules 213–218).

Import is ``observe → parse → validate → re-observe → compare → publish``:

1. observe the current ``sourceSnapshot`` and the edge identity space
   through ``ExchangeService.observe_edge_centerlines`` (the SAME projection
   the bundle was exported with — no second fingerprint calculator, no
   second artifact list);
2. read and validate the package (budgets, manifest, version, domain);
3. bind: the package must name THIS scenario and carry EXACTLY the observed
   ``sourceSnapshot`` (a result of an older mine is refused, never
   re-bound); resolve every identity explicitly; normalize;
4. under the scenario lock re-observe the snapshot — a mine that moved
   during the import is ``READ_SNAPSHOT_CHANGED`` — and publish the result
   folder atomically.

A stored result is judged COMPATIBLE or STALE against the CURRENT snapshot
on every read; a STALE result stays listed, inspectable, exportable and
deletable but its overlay frames are refused (``RESULT_STALE``). No mine
operation deletes a result and no result influences any mine artifact.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from minegen.exchange.formats.json_document import dumps
from minegen.exchange.models import SourceSnapshot
from minegen.results.errors import (
    ResultDataInvalidError,
    ResultLimitExceededError,
    ResultPackageInvalidError,
    ResultSourceScenarioMismatchError,
    ResultSourceSnapshotMismatchError,
    ResultStaleError,
)
from minegen.results.export import export_result
from minegen.results.frames import geometry_payload, operations_frame, ventilation_frame
from minegen.results.importers import (
    ANYLOGIC_MEMBERS,
    VENTSIM_MEMBERS,
    ImportedResult,
    import_anylogic,
    import_ventsim,
)
from minegen.results.importers.common import EdgeIndex
from minegen.results.models import (
    MINE_RESULT_VERSION,
    Compatibility,
    MineResultManifest,
    OperationsFrame,
    ResultDetail,
    ResultFile,
    ResultGeometryPayload,
    ResultImportPayload,
    ResultListPayload,
    ResultProvenance,
    ResultSummary,
    SourceApplication,
    VentilationFrame,
)
from minegen.results.normalization import content_sha256, npz_bytes, result_id_for
from minegen.results.package import MAX_UPLOAD_BYTES, ResultPackage, read_result_package
from minegen.results.store import ResultStore, StoredResult
from minegen.services.artifact_errors import (
    ReadSnapshotChangedError,
    WorldNotGeneratedError,
    WorldPublicationStaleError,
)
from minegen.services.exchange_service import ExchangeService, safe_scenario_id
from minegen.services.scenario_service import ScenarioStore

_MEMBERS: dict[SourceApplication, frozenset[str]] = {
    "VENTSIM": VENTSIM_MEMBERS,
    "ANYLOGIC": ANYLOGIC_MEMBERS,
}
_MEDIA_TYPES = {".json": "application/json", ".csv": "text/csv", ".txt": "text/plain"}


@dataclass(frozen=True)
class ResultExport:
    zip_bytes: bytes
    filename: str
    result_id: str


def snapshot_differences(expected: SourceSnapshot, current: SourceSnapshot) -> list[str]:
    """Human-readable list of the fields on which two snapshots differ."""
    out: list[str] = []
    if expected.scenario_revision != current.scenario_revision:
        out.append("scenarioRevision")
    if expected.arrays_revision != current.arrays_revision:
        out.append("arraysRevision")
    if expected.active_ramp_source != current.active_ramp_source:
        out.append("activeRampSource")
    names = sorted(set(expected.artifact_revisions) | set(current.artifact_revisions))
    for name in names:
        if expected.artifact_revisions.get(name) != current.artifact_revisions.get(name):
            out.append(f"artifactRevisions.{name}")
    return out


def compatibility_of(stored: SourceSnapshot, current: SourceSnapshot | None) -> Compatibility:
    return "COMPATIBLE" if current is not None and stored == current else "STALE"


class ResultService:
    def __init__(self, store: ScenarioStore, exchange: ExchangeService) -> None:
        self.store = store
        self.exchange = exchange
        self.results = ResultStore(store)

    # -- current binding -------------------------------------------------- #

    def current_snapshot(self, scenario_id: str) -> SourceSnapshot | None:
        """The snapshot a bundle exported NOW would carry, or ``None`` when
        the scenario has no valid world (every result is then STALE). A
        missing scenario propagates (404)."""
        try:
            return self.exchange.observe_source_snapshot(scenario_id)
        except (WorldNotGeneratedError, WorldPublicationStaleError):
            return None

    # -- import ----------------------------------------------------------- #

    def import_result(
        self, scenario_id: str, application: SourceApplication, data: bytes
    ) -> ResultImportPayload:
        self.store.get(scenario_id)
        if len(data) > MAX_UPLOAD_BYTES:
            raise ResultLimitExceededError(
                f"upload of {len(data)} bytes exceeds the {MAX_UPLOAD_BYTES}-byte limit",
                subject="upload",
            )
        if not data:
            raise ResultPackageInvalidError("the upload is empty", subject="upload")
        # 1. observe the binding FIRST (the identity space of the current mine)
        before, edges = self.exchange.observe_edge_centerlines(scenario_id)
        # 2. parse
        package = read_result_package(data, allowed_members=_MEMBERS[application])
        manifest = package.manifest
        if manifest.source_application != application:
            raise ResultPackageInvalidError(
                f"the package declares sourceApplication {manifest.source_application!r}; "
                f"this import route accepts {application}",
                subject="result_manifest.json",
            )
        # 3. bind
        if manifest.source_scenario_id != scenario_id:
            raise ResultSourceScenarioMismatchError(
                f"the package was produced for scenario {manifest.source_scenario_id!r}, "
                f"not {scenario_id!r}",
                subject="result_manifest.json",
            )
        differences = snapshot_differences(manifest.source_snapshot, before)
        if differences:
            raise ResultSourceSnapshotMismatchError(
                "the package sourceSnapshot does not match the current mine snapshot "
                f"(differs on {', '.join(differences)}); export a fresh MineExchange "
                "bundle, re-run the simulation on it and import that result",
                subject="result_manifest.json",
            )
        index = EdgeIndex(edges)
        if not index.ids:
            raise ResultDataInvalidError(
                "the current mine has no MineNetwork edge with geometry to bind a result to",
                subject="network.json",
            )
        imported = import_ventsim(package, index) if application == "VENTSIM" else None
        if imported is None:
            imported = import_anylogic(package, index)
        # 4. normalize + identity
        result_manifest, normalized = self._manifest(scenario_id, package, imported, data, before)
        manifest_bytes = dumps(result_manifest.model_dump(mode="json", by_alias=True))
        # 5. re-observe under the scenario lock, then publish atomically
        with self.store.lock(scenario_id):
            after = self.exchange.observe_source_snapshot(scenario_id)
            if after != before:
                raise ReadSnapshotChangedError(
                    scenario_id, "the mine snapshot changed while the result was imported"
                )
            created = self.results.publish(
                scenario_id,
                result_manifest.result_id,
                manifest_bytes=manifest_bytes,
                normalized_bytes=normalized,
                source_bytes=data,
            )
        stored = self.results.read_manifest(scenario_id, result_manifest.result_id)
        return ResultImportPayload(
            created=created, result=self._detail(stored, compatibility_of(before, after))
        )

    def _manifest(
        self,
        scenario_id: str,
        package: ResultPackage,
        imported: ImportedResult,
        data: bytes,
        snapshot: SourceSnapshot,
    ) -> tuple[MineResultManifest, bytes]:
        pm = package.manifest
        normalized_sha = content_sha256(imported.arrays)
        result_id = result_id_for(normalized_sha, snapshot, pm.result_domain, pm.source_application)
        files = [
            ResultFile(
                path=name,
                sha256=hashlib.sha256(package.files[name]).hexdigest(),
                media_type=_MEDIA_TYPES.get(name[name.rfind(".") :], "application/octet-stream"),
                semantic=(
                    "RESULT_MANIFEST"
                    if name == "result_manifest.json"
                    else "RESULT_DATA"
                    if name in imported.imported_file_names
                    else "DOCUMENTATION"
                ),
            )
            for name in sorted(package.files)
        ]
        manifest = MineResultManifest(
            mine_result_version=MINE_RESULT_VERSION,
            result_id=result_id,
            result_domain=pm.result_domain,
            source_application=pm.source_application,
            source_adapter=pm.source_adapter,
            source_adapter_version=pm.source_adapter_version,
            source_mine_exchange_version=pm.source_mine_exchange_version,
            source_scenario_id=scenario_id,
            source_snapshot=snapshot,
            run_label=pm.run_label,
            description=pm.description,
            time_axis=imported.time_axis,
            files=files,
            metrics=imported.metrics,
            summary_metrics=imported.summary_metrics,
            counts=imported.counts,
            provenance=ResultProvenance(
                source_application=pm.source_application,
                source_application_version=pm.source_application_version or "",
                source_adapter_name=pm.source_adapter,
                source_adapter_version=pm.source_adapter_version,
                source_mine_exchange_version=pm.source_mine_exchange_version,
                source_scenario_id=pm.source_scenario_id,
                original_file_sha256=hashlib.sha256(data).hexdigest(),
                imported_file_names=list(imported.imported_file_names),
            ),
            import_source_sha256=hashlib.sha256(data).hexdigest(),
            normalized_sha256=normalized_sha,
            sign_convention=imported.sign_convention,
            notes=list(imported.notes),
        )
        return manifest, npz_bytes(imported.arrays)

    # -- read ------------------------------------------------------------- #

    @staticmethod
    def _summary(stored: StoredResult, compatibility: Compatibility) -> ResultSummary:
        m = stored.manifest
        return ResultSummary(
            result_id=m.result_id,
            domain=m.result_domain,
            source_application=m.source_application,
            run_label=m.run_label,
            description=m.description,
            compatibility=compatibility,
            source_snapshot=m.source_snapshot,
            time_axis=m.time_axis,
            metrics=m.metrics,
            counts=m.counts,
            mine_result_version=m.mine_result_version,
        )

    @staticmethod
    def _detail(stored: StoredResult, compatibility: Compatibility) -> ResultDetail:
        m = stored.manifest
        return ResultDetail(
            **ResultService._summary(stored, compatibility).model_dump(),
            provenance=m.provenance,
            summary_metrics=m.summary_metrics,
            files=m.files,
            sign_convention=m.sign_convention,
            notes=m.notes,
            import_source_sha256=m.import_source_sha256,
            normalized_sha256=m.normalized_sha256,
        )

    def list_results(self, scenario_id: str) -> ResultListPayload:
        self.store.get(scenario_id)
        current = self.current_snapshot(scenario_id)
        results = [
            self._summary(stored, compatibility_of(stored.manifest.source_snapshot, current))
            for stored in (
                self.results.read_manifest(scenario_id, rid)
                for rid in self.results.list_ids(scenario_id)
            )
        ]
        return ResultListPayload(scenario_id=scenario_id, results=results)

    def get_result(self, scenario_id: str, result_id: str) -> ResultDetail:
        self.store.get(scenario_id)
        stored = self.results.read_manifest(scenario_id, result_id)
        current = self.current_snapshot(scenario_id)
        return self._detail(stored, compatibility_of(stored.manifest.source_snapshot, current))

    def delete_result(self, scenario_id: str, result_id: str) -> None:
        self.store.get(scenario_id)
        with self.store.lock(scenario_id):
            self.results.delete(scenario_id, result_id)

    def export(self, scenario_id: str, result_id: str) -> ResultExport:
        """The canonical MineResult 1.0 ZIP (deterministic bytes); allowed
        for a STALE result too — it is evidence, not an overlay."""
        self.store.get(scenario_id)
        stored = self.results.read_manifest(scenario_id, result_id)
        arrays = self.results.read_normalized(stored)
        return ResultExport(
            zip_bytes=export_result(stored.manifest, arrays),
            filename=(
                f"minegen_{safe_scenario_id(scenario_id)}_mineresult_"
                f"{stored.manifest.result_domain.lower()}_{result_id}.zip"
            ),
            result_id=result_id,
        )

    # -- overlay frames (COMPATIBLE results only) ---------------------------- #

    def _compatible(self, scenario_id: str, result_id: str) -> StoredResult:
        self.store.get(scenario_id)
        stored = self.results.read_manifest(scenario_id, result_id)
        current = self.current_snapshot(scenario_id)
        if compatibility_of(stored.manifest.source_snapshot, current) != "COMPATIBLE":
            differences = (
                snapshot_differences(stored.manifest.source_snapshot, current)
                if current is not None
                else ["world"]
            )
            raise ResultStaleError(
                "this result was generated from an older mine snapshot (differs on "
                f"{', '.join(differences)}); it can be listed, inspected, exported and "
                "deleted but not overlaid",
                subject=result_id,
            )
        return stored

    def geometry(self, scenario_id: str, result_id: str) -> ResultGeometryPayload:
        stored = self._compatible(scenario_id, result_id)
        return geometry_payload(result_id, self.results.read_normalized(stored))

    def ventilation(
        self, scenario_id: str, result_id: str, *, metric: str, time: float | None
    ) -> VentilationFrame:
        stored = self._compatible(scenario_id, result_id)
        if stored.manifest.result_domain != "VENTILATION":
            raise ResultDataInvalidError(
                f"result {result_id} is a {stored.manifest.result_domain} result, not a "
                "ventilation result",
                subject=result_id,
            )
        return ventilation_frame(
            result_id,
            self.results.read_normalized(stored),
            kind=stored.manifest.time_axis.kind,
            metric=metric,
            time=time,
        )

    def operations(self, scenario_id: str, result_id: str, *, time: float) -> OperationsFrame:
        stored = self._compatible(scenario_id, result_id)
        if stored.manifest.result_domain != "OPERATIONS":
            raise ResultDataInvalidError(
                f"result {result_id} is a {stored.manifest.result_domain} result, not an "
                "operations result",
                subject=result_id,
            )
        return operations_frame(
            result_id,
            self.results.read_normalized(stored),
            kind=stored.manifest.time_axis.kind,
            time=time,
        )
