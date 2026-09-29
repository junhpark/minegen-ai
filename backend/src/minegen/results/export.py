"""Canonical MineResult 1.0 export (directive §50, §84): a deterministic
ZIP rebuilt from the stored normalized arrays — fixed timestamps, sorted
paths, canonical units and sort order — so the same stored result always
exports byte-identical bytes, and the export is itself an importable
MineResult package (re-importing it yields the same resultId).

    mine_result/
      manifest.json          MineResultManifest (the stored one)
      result_manifest.json   the package manifest (canonical units, same sourceSnapshot)
      <domain CSV files>     airway_results.csv | vehicle_samples.csv, edge_metrics.csv,
                             summary_metrics.csv
      README.txt
"""

from __future__ import annotations

import numpy as np

from minegen.adapters.package import write_package
from minegen.exchange.formats.csv_table import write_csv
from minegen.exchange.formats.json_document import dumps
from minegen.results.models import (
    MINE_RESULT_VERSION,
    OPERATIONS_EDGE_METRICS,
    VENTILATION_METRICS,
    MineResultManifest,
)
from minegen.results.normalization import NormalizedResult

EXPORT_ROOT = "mine_result"


def _package_manifest(manifest: MineResultManifest) -> bytes:
    units: dict[str, str]
    if manifest.result_domain == "VENTILATION":
        units = {m.name: m.unit for m in manifest.metrics if m.available}
    else:
        units = {m.name: m.unit for m in manifest.metrics if m.available}
        units["loadTonnes"] = "t"
    doc = {
        "mineResultVersion": MINE_RESULT_VERSION,
        "resultDomain": manifest.result_domain,
        "sourceApplication": manifest.source_application,
        "sourceApplicationVersion": manifest.provenance.source_application_version,
        "sourceAdapter": manifest.source_adapter,
        "sourceAdapterVersion": manifest.source_adapter_version,
        "sourceMineExchangeVersion": manifest.source_mine_exchange_version,
        "sourceScenarioId": manifest.source_scenario_id,
        "sourceSnapshot": manifest.source_snapshot.model_dump(mode="json", by_alias=True),
        "runLabel": manifest.run_label,
        "description": manifest.description,
        "timeAxis": {"kind": manifest.time_axis.kind},
        "units": units,
        "unitConversions": [],
    }
    return dumps(doc)


def _cell(v: float) -> float | None:
    return None if not np.isfinite(v) else float(v)


def export_result(manifest: MineResultManifest, arrays: NormalizedResult) -> bytes:
    files: dict[str, bytes] = {
        "manifest.json": dumps(manifest.model_dump(mode="json", by_alias=True)),
        "result_manifest.json": _package_manifest(manifest),
    }
    ids = arrays["edge_ids"]
    if manifest.result_domain == "VENTILATION":
        metrics = [
            m.name for m in manifest.metrics if m.available and m.name in VENTILATION_METRICS
        ]
        times = arrays["times"]
        static = manifest.time_axis.kind == "STATIC"
        rows = []
        for ti in range(times.shape[0]):
            for ei in range(ids.shape[0]):
                values = [_cell(float(arrays[f"vent_{m}"][ti, ei])) for m in metrics]
                if all(v is None for v in values):
                    continue
                rows.append((str(ids[ei]), None if static else float(times[ti]), *values))
        files["airway_results.csv"] = write_csv(("edgeId", "time", *metrics), rows).encode("utf-8")
    else:
        agents = arrays["agent_ids"]
        kinds = arrays["agent_kinds"]
        rows = []
        for i in range(arrays["sample_time"].shape[0]):
            a = int(arrays["sample_agent"][i])
            rows.append(
                (
                    float(arrays["sample_time"][i]),
                    str(agents[a]),
                    str(kinds[a]) or None,
                    str(ids[int(arrays["sample_edge"][i])]),
                    float(arrays["sample_chainage"][i]),
                    str(arrays["sample_status"][i]) or None,
                    _cell(float(arrays["sample_load"][i])),
                )
            )
        files["vehicle_samples.csv"] = write_csv(
            ("time", "agentId", "agentKind", "edgeId", "chainageFraction", "status", "loadTonnes"),
            rows,
        ).encode("utf-8")
        if "em_time" in arrays and arrays["em_time"].shape[0]:
            metrics = [m for m in OPERATIONS_EDGE_METRICS if any(np.isfinite(arrays[f"em_{m}"]))]
            erows = []
            for i in range(arrays["em_time"].shape[0]):
                vals = [_cell(float(arrays[f"em_{m}"][i])) for m in metrics]
                if "queueCount" in metrics:
                    q = vals[metrics.index("queueCount")]
                    vals[metrics.index("queueCount")] = None if q is None else int(q)
                erows.append(
                    (float(arrays["em_time"][i]), str(ids[int(arrays["em_edge"][i])]), *vals)
                )
            files["edge_metrics.csv"] = write_csv(("time", "edgeId", *metrics), erows).encode(
                "utf-8"
            )
        if arrays["summary_names"].shape[0]:
            files["summary_metrics.csv"] = write_csv(
                ("metric", "value", "unit"),
                [
                    (str(n), float(v), str(u))
                    for n, v, u in zip(
                        arrays["summary_names"],
                        arrays["summary_values"],
                        arrays["summary_units"],
                        strict=True,
                    )
                ],
            ).encode("utf-8")
    files["README.txt"] = "\n".join(
        [
            f"MineResult {MINE_RESULT_VERSION} canonical export — {manifest.result_domain} from "
            f"{manifest.source_application} (result {manifest.result_id})",
            "",
            "This ZIP is the normalized, canonical form of an imported external simulation",
            "result: units are canonical SI, rows are sorted (time, edgeId / agentId), missing",
            "values are blank. It is itself an importable MineResult package and re-importing",
            "it into the same mine snapshot yields the same resultId.",
            "",
            "A MineResult is a non-authoritative observation bound to the MineExchange",
            f"sourceSnapshot it was produced from (scenario {manifest.source_scenario_id}); it",
            "never redesigns the mine, its topology, production plan, timeline or economics.",
            "",
        ]
    ).encode("utf-8")
    return write_package(EXPORT_ROOT, files)
