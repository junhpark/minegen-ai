"""Round-trip RESULT kits (Phase 23C, directive §58–§64, rule 217).

Every Ventsim and AnyLogic export package carries a ``roundtrip/`` folder:
a pre-filled ``result_manifest.json`` (MineResult 1.0, bound to the SAME
``sourceSnapshot`` as the export, canonical units declared) plus the empty
CSV tables the user fills from the external application and zips back for
``POST …/results/import/<application>``. The kit is additive to the adapter
package (nothing existing changes) and carries NO simulation value: MineGen
never invents a result, only the shape it can bind.
"""

from __future__ import annotations

from typing import Any

from minegen.adapters.package import PackageBuilder
from minegen.exchange.formats.csv_table import write_csv
from minegen.exchange.formats.json_document import dumps
from minegen.results.models import (
    MINE_RESULT_VERSION,
    OPERATIONS_EDGE_METRICS,
    OPERATIONS_SUMMARY_METRICS,
    VENTILATION_METRICS,
)

KIT_DIR = "roundtrip"
KIT_MANIFEST_PATH = f"{KIT_DIR}/result_manifest.json"
KIT_README_PATH = f"{KIT_DIR}/README.txt"
VENTSIM_RESULTS_PATH = f"{KIT_DIR}/airway_results.csv"
VENTSIM_IDENTITY_PATH = f"{KIT_DIR}/airway_identity.csv"
ANYLOGIC_VEHICLES_PATH = f"{KIT_DIR}/vehicle_samples.csv"
ANYLOGIC_EDGE_METRICS_PATH = f"{KIT_DIR}/edge_metrics.csv"
ANYLOGIC_SUMMARY_PATH = f"{KIT_DIR}/summary_metrics.csv"

VENTSIM_RESULT_COLUMNS = ("edgeId", "ventsimUniqueNumber", "time", *VENTILATION_METRICS)
VENTSIM_IDENTITY_COLUMNS = ("edgeId", "ventsimUniqueNumber")
ANYLOGIC_VEHICLE_COLUMNS = (
    "time",
    "agentId",
    "agentKind",
    "edgeId",
    "chainageFraction",
    "status",
    "loadTonnes",
)
ANYLOGIC_EDGE_METRIC_COLUMNS = ("time", "edgeId", *OPERATIONS_EDGE_METRICS)
ANYLOGIC_SUMMARY_COLUMNS = ("metric", "value", "unit")


def _manifest(
    *,
    domain: str,
    application: str,
    adapter_name: str,
    adapter_version: str,
    mine_exchange_version: str,
    scenario_id: str,
    source_snapshot: dict[str, Any],
    time_axis_kind: str,
    units: dict[str, str],
) -> bytes:
    return dumps(
        {
            "mineResultVersion": MINE_RESULT_VERSION,
            "resultDomain": domain,
            "sourceApplication": application,
            "sourceApplicationVersion": None,
            "sourceAdapter": adapter_name,
            "sourceAdapterVersion": adapter_version,
            "sourceMineExchangeVersion": mine_exchange_version,
            "sourceScenarioId": scenario_id,
            "sourceSnapshot": source_snapshot,
            "runLabel": "",
            "description": "",
            "timeAxis": {"kind": time_axis_kind},
            "units": units,
            "unitConversions": [],
        }
    )


def add_ventsim_kit(
    pkg: PackageBuilder,
    *,
    adapter_version: str,
    mine_exchange_version: str,
    scenario_id: str,
    source_snapshot: dict[str, Any],
    edge_ids: list[str],
) -> list[str]:
    """Ventsim kit: manifest (STATIC by default), one pre-identified row per
    airway with EMPTY metric cells, the explicit ventsimUniqueNumber
    crosswalk table (edgeId filled, number empty) and instructions."""
    pkg.add(
        KIT_MANIFEST_PATH,
        _manifest(
            domain="VENTILATION",
            application="VENTSIM",
            adapter_name="VENTSIM",
            adapter_version=adapter_version,
            mine_exchange_version=mine_exchange_version,
            scenario_id=scenario_id,
            source_snapshot=source_snapshot,
            time_axis_kind="STATIC",
            units=dict(VENTILATION_METRICS),
        ),
        target_semantic="RESULT_KIT_MANIFEST",
        source_files=["manifest.json"],
    )
    blanks = tuple(None for _ in VENTILATION_METRICS)
    pkg.add(
        VENTSIM_RESULTS_PATH,
        write_csv(
            VENTSIM_RESULT_COLUMNS, [(edge_id, None, None, *blanks) for edge_id in edge_ids]
        ).encode("utf-8"),
        target_semantic="RESULT_KIT_TABLE",
        source_files=["topology/network.json"],
    )
    pkg.add(
        VENTSIM_IDENTITY_PATH,
        write_csv(VENTSIM_IDENTITY_COLUMNS, [(edge_id, None) for edge_id in edge_ids]).encode(
            "utf-8"
        ),
        target_semantic="RESULT_KIT_IDENTITY",
        source_files=["topology/network.json"],
    )
    pkg.add(
        KIT_README_PATH,
        "\n".join(
            [
                f"MineResult {MINE_RESULT_VERSION} round-trip kit — Ventsim ventilation results",
                "",
                "Fill these files from your Ventsim run and zip the roundtrip/ folder (the",
                "folder itself or its files at the ZIP root) for",
                "  POST /api/v1/scenarios/<scenarioId>/results/import/ventsim   (application/zip)",
                "",
                "  result_manifest.json  bound to the SAME mine snapshot as this export; the",
                "                        import refuses a package of another snapshot",
                "                        (RESULT_SOURCE_SNAPSHOT_MISMATCH). Set timeAxis.kind",
                "                        to ELAPSED_SECONDS (and fill the time column, seconds",
                "                        >= 0) for a transient run; STATIC leaves time empty.",
                "                        Declare a non-canonical unit ONLY through",
                "                        unitConversions[] (metric, sourceUnit, factor, offset).",
                "  airway_results.csv    one row per airway: edgeId (pre-filled; or a",
                "                        ventsimUniqueNumber resolved through airway_identity.csv)",
                "                        and the metric values you have — leave unknown cells",
                "                        EMPTY, never 0. Canonical units: airflowM3s m3/s,",
                "                        velocityMs m/s, pressurePa / pressureLossPa Pa,",
                "                        temperatureDryC / temperatureWetC degC, airDensityKgM3",
                "                        kg/m3. Airflow sign: positive = edge sourceNodeId ->",
                "                        targetNodeId (see network/airways.csv).",
                "  airway_identity.csv   explicit crosswalk ventsimUniqueNumber -> edgeId; the",
                "                        importer never matches airways spatially.",
                "",
                "Delete rows you have no value for. A row without an identity or without any",
                "metric value is refused (typed error), never guessed.",
                "",
            ]
        ).encode("utf-8"),
        target_semantic="RESULT_KIT_README",
        source_files=[],
    )
    return [KIT_MANIFEST_PATH, VENTSIM_RESULTS_PATH, VENTSIM_IDENTITY_PATH, KIT_README_PATH]


def add_anylogic_kit(
    pkg: PackageBuilder,
    *,
    adapter_version: str,
    mine_exchange_version: str,
    scenario_id: str,
    source_snapshot: dict[str, Any],
) -> list[str]:
    """AnyLogic kit: manifest (ELAPSED_SECONDS by default) and the three
    EMPTY tables (header rows only)."""
    units = {
        "loadTonnes": "t",
        **OPERATIONS_EDGE_METRICS,
        **OPERATIONS_SUMMARY_METRICS,
    }
    pkg.add(
        KIT_MANIFEST_PATH,
        _manifest(
            domain="OPERATIONS",
            application="ANYLOGIC",
            adapter_name="ANYLOGIC",
            adapter_version=adapter_version,
            mine_exchange_version=mine_exchange_version,
            scenario_id=scenario_id,
            source_snapshot=source_snapshot,
            time_axis_kind="ELAPSED_SECONDS",
            units=units,
        ),
        target_semantic="RESULT_KIT_MANIFEST",
        source_files=["manifest.json"],
    )
    for path, columns in (
        (ANYLOGIC_VEHICLES_PATH, ANYLOGIC_VEHICLE_COLUMNS),
        (ANYLOGIC_EDGE_METRICS_PATH, ANYLOGIC_EDGE_METRIC_COLUMNS),
        (ANYLOGIC_SUMMARY_PATH, ANYLOGIC_SUMMARY_COLUMNS),
    ):
        pkg.add(
            path,
            write_csv(columns, []).encode("utf-8"),
            target_semantic="RESULT_KIT_TABLE",
            source_files=[],
        )
    pkg.add(
        KIT_README_PATH,
        "\n".join(
            [
                f"MineResult {MINE_RESULT_VERSION} round-trip kit — AnyLogic operations results",
                "",
                "Fill these files from your AnyLogic run and zip the roundtrip/ folder for",
                "  POST /api/v1/scenarios/<scenarioId>/results/import/anylogic  (application/zip)",
                "",
                "  result_manifest.json  bound to the SAME mine snapshot as this export; set",
                "                        timeAxis.kind to ELAPSED_SECONDS (model seconds) or",
                "                        MINE_DAY (planning days) — declare it, MineGen never",
                "                        infers the axis.",
                "  vehicle_samples.csv   required: time, agentId, edgeId (data/edges.csv id),",
                "                        chainageFraction in [0, 1] along the edge from its",
                "                        sourceNodeId (0) to its targetNodeId (1); optional:",
                "                        agentKind, status, loadTonnes (t, >= 0). MineGen",
                "                        projects XYZ along the edge centerline; between two",
                "                        samples on the SAME edge the position is interpolated,",
                "                        across an edge change the previous sample is held —",
                "                        no route is invented.",
                "  edge_metrics.csv      optional per (time, edgeId): utilization [0, 1],",
                "                        queueCount (integer >= 0), haulageTonnesPerHour (>= 0),",
                "                        travelTimeSeconds (>= 0); empty cells are missing.",
                "  summary_metrics.csv   optional long form (metric, value, unit); known metrics",
                "                        (totalHauledTonnes t, meanCycleTimeSeconds s,",
                "                        meanUtilization fraction, simulatedDurationSeconds s,",
                "                        vehicleCount count) are promoted, others recorded by",
                "                        name only.",
                "",
                "MineGen computes no simulation quantity from these tables; it stores, binds",
                "and visualizes what you deliver.",
                "",
            ]
        ).encode("utf-8"),
        target_semantic="RESULT_KIT_README",
        source_files=[],
    )
    return [
        KIT_MANIFEST_PATH,
        ANYLOGIC_VEHICLES_PATH,
        ANYLOGIC_EDGE_METRICS_PATH,
        ANYLOGIC_SUMMARY_PATH,
        KIT_README_PATH,
    ]
