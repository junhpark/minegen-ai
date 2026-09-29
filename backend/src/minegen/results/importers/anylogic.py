"""AnyLogic result importer (directive §33–§41, rule 218).

Input: the round-trip kit shape — ``result_manifest.json``,
``vehicle_samples.csv`` (required), ``edge_metrics.csv`` and
``summary_metrics.csv`` (optional). Vehicle positions are
``edgeId + chainageFraction`` on the SOURCE snapshot's edge centerline and
are projected to XYZ deterministically (a visualization derivative);
``agentId`` is simulation-local identity. The importer computes NO
simulation quantity: no dispatch, speed, cycle time, fleet or queue model —
it reads the external output and validates it.
"""

from __future__ import annotations

import numpy as np

from minegen.results.errors import (
    ResultDataInvalidError,
    ResultIdentityAmbiguousError,
    ResultPackageInvalidError,
)
from minegen.results.geometry import chainage_to_xyz
from minegen.results.importers.common import EdgeIndex, ImportedResult, geometry_arrays
from minegen.results.models import (
    OPERATIONS_EDGE_METRICS,
    OPERATIONS_SUMMARY_METRICS,
    ResultCounts,
    ResultMetricAvailability,
    ResultPackageManifest,
    ResultSummaryMetric,
    ResultTimeAxis,
)
from minegen.results.normalization import NormalizedResult, finite_or_none, str_array
from minegen.results.package import (
    MAX_AGENTS,
    MAX_UNIQUE_TIMES,
    ResultPackage,
    parse_float,
    parse_int,
    read_csv_member,
)
from minegen.results.units import require_canonical_unit

VEHICLES_MEMBER = "vehicle_samples.csv"
EDGE_METRICS_MEMBER = "edge_metrics.csv"
SUMMARY_MEMBER = "summary_metrics.csv"
ANYLOGIC_MEMBERS = frozenset({VEHICLES_MEMBER, EDGE_METRICS_MEMBER, SUMMARY_MEMBER})
VEHICLE_REQUIRED = ("time", "agentId", "edgeId", "chainageFraction")
VEHICLE_OPTIONAL = ("agentKind", "status", "loadTonnes")
_VEHICLE_COLUMNS = frozenset({*VEHICLE_REQUIRED, *VEHICLE_OPTIONAL})
_EDGE_COLUMNS = frozenset({"time", "edgeId", *OPERATIONS_EDGE_METRICS})
_SUMMARY_COLUMNS = ("metric", "value", "unit")


def _time(cell: str, *, name: str, row: int) -> float:
    t = parse_float(cell, name=name, row=row, column="time")
    if t is None:
        raise ResultDataInvalidError(f"row {row}: time is required", subject=name)
    if t < 0.0:
        raise ResultDataInvalidError(f"row {row}: time {t} < 0", subject=name)
    return t


def import_anylogic(package: ResultPackage, index: EdgeIndex) -> ImportedResult:
    manifest: ResultPackageManifest = package.manifest
    if manifest.result_domain != "OPERATIONS" or manifest.source_application != "ANYLOGIC":
        raise ResultPackageInvalidError(
            "an AnyLogic result package declares resultDomain OPERATIONS and "
            "sourceApplication ANYLOGIC",
            subject="result_manifest.json",
        )
    kind = manifest.time_axis.kind
    if kind not in ("ELAPSED_SECONDS", "MINE_DAY"):
        raise ResultDataInvalidError(
            f"timeAxis.kind {kind!r} is not supported for an operations result "
            "(ELAPSED_SECONDS | MINE_DAY); the axis is declared, never inferred",
            subject="result_manifest.json",
        )
    if not package.has(VEHICLES_MEMBER):
        raise ResultPackageInvalidError("missing required file", subject=VEHICLES_MEMBER)
    if "loadTonnes" in manifest.units:
        require_canonical_unit(manifest, "loadTonnes", "t", subject=VEHICLES_MEMBER)

    # -- vehicle samples -------------------------------------------------------- #
    table = read_csv_member(package, VEHICLES_MEMBER, required_columns=VEHICLE_REQUIRED)
    unknown = sorted(set(table.header) - _VEHICLE_COLUMNS)
    if unknown:
        raise ResultPackageInvalidError(
            f"unknown columns {unknown}; supported: {sorted(_VEHICLE_COLUMNS)}",
            subject=VEHICLES_MEMBER,
        )
    col = {name: i for i, name in enumerate(table.header)}
    kinds: dict[str, str] = {}
    rows: dict[tuple[str, float], tuple[int, float, str, float | None]] = {}
    for r, row in enumerate(table.rows, start=2):
        agent = row[col["agentId"]].strip()
        if not agent:
            raise ResultDataInvalidError(f"row {r}: agentId is empty", subject=VEHICLES_MEMBER)
        t = _time(row[col["time"]], name=VEHICLES_MEMBER, row=r)
        edge_id = row[col["edgeId"]].strip()
        k = index.index_of(edge_id, subject=VEHICLES_MEMBER, row=r)
        f = parse_float(
            row[col["chainageFraction"]], name=VEHICLES_MEMBER, row=r, column="chainageFraction"
        )
        if f is None or f < 0.0 or f > 1.0:
            raise ResultDataInvalidError(
                f"row {r}: chainageFraction {row[col['chainageFraction']]!r} is not in [0, 1]",
                subject=VEHICLES_MEMBER,
            )
        agent_kind = row[col["agentKind"]].strip() if "agentKind" in col else ""
        if agent_kind and kinds.setdefault(agent, agent_kind) != agent_kind:
            raise ResultDataInvalidError(
                f"row {r}: agent {agent!r} changes agentKind ({kinds[agent]!r} -> {agent_kind!r})",
                subject=VEHICLES_MEMBER,
            )
        status = row[col["status"]].strip() if "status" in col else ""
        load = (
            parse_float(row[col["loadTonnes"]], name=VEHICLES_MEMBER, row=r, column="loadTonnes")
            if "loadTonnes" in col
            else None
        )
        if load is not None and load < 0.0:
            raise ResultDataInvalidError(f"row {r}: loadTonnes {load} < 0", subject=VEHICLES_MEMBER)
        key = (agent, t)
        if key in rows:
            raise ResultIdentityAmbiguousError(
                f"row {r}: agent {agent!r} has two samples at time {t} (ambiguous)",
                subject=VEHICLES_MEMBER,
            )
        rows[key] = (k, f, status, load)
    if not rows:
        raise ResultDataInvalidError(
            "the result carries no vehicle sample", subject=VEHICLES_MEMBER
        )
    # explicit units only (rule 216): a delivered loadTonnes VALUE is accepted
    # solely under an explicit ``units.loadTonnes = "t"`` declaration — a
    # column with values and no declaration is never read as tonnes
    if any(v[3] is not None for v in rows.values()):
        require_canonical_unit(manifest, "loadTonnes", "t", subject=VEHICLES_MEMBER)
    agents = sorted({a for a, _ in rows})
    if len(agents) > MAX_AGENTS:
        raise ResultDataInvalidError(
            f"{len(agents)} agents; the limit is {MAX_AGENTS}", subject=VEHICLES_MEMBER
        )
    sample_times = sorted({t for _, t in rows})
    if len(sample_times) > MAX_UNIQUE_TIMES:
        raise ResultDataInvalidError(
            f"{len(sample_times)} distinct times; the limit is {MAX_UNIQUE_TIMES}",
            subject=VEHICLES_MEMBER,
        )
    agent_index = {a: i for i, a in enumerate(agents)}
    ordered = sorted(rows.items(), key=lambda kv: (kv[0][1], kv[0][0]))  # (time, agentId)
    n = len(ordered)
    s_time = np.zeros(n, dtype=np.float64)
    s_agent = np.zeros(n, dtype=np.int64)
    s_edge = np.zeros(n, dtype=np.int64)
    s_chain = np.zeros(n, dtype=np.float64)
    s_load = np.full(n, np.nan, dtype=np.float64)
    s_status: list[str] = []
    s_xyz = np.zeros((n, 3), dtype=np.float64)
    for i, ((agent, t), (k, f, status, load)) in enumerate(ordered):
        s_time[i] = t
        s_agent[i] = agent_index[agent]
        s_edge[i] = k
        s_chain[i] = f
        s_status.append(status)
        if load is not None:
            s_load[i] = load
        s_xyz[i] = chainage_to_xyz(index.edges[k].points, f)

    arrays: NormalizedResult = geometry_arrays(index)
    arrays["agent_ids"] = str_array(agents)
    arrays["agent_kinds"] = str_array([kinds.get(a, "") for a in agents])
    arrays["sample_time"] = s_time
    arrays["sample_agent"] = s_agent
    arrays["sample_edge"] = s_edge
    arrays["sample_chainage"] = s_chain
    arrays["sample_status"] = str_array(s_status)
    arrays["sample_load"] = s_load
    arrays["sample_xyz"] = s_xyz

    # -- edge metrics (optional) ------------------------------------------------ #
    metrics: list[ResultMetricAvailability] = []
    em_count = 0
    em_times: list[float] = []
    present_metrics: list[str] = []
    if package.has(EDGE_METRICS_MEMBER):
        etable = read_csv_member(package, EDGE_METRICS_MEMBER, required_columns=("time", "edgeId"))
        unknown = sorted(set(etable.header) - _EDGE_COLUMNS)
        if unknown:
            raise ResultPackageInvalidError(
                f"unknown columns {unknown}; supported: {sorted(_EDGE_COLUMNS)}",
                subject=EDGE_METRICS_MEMBER,
            )
        ecol = {name: i for i, name in enumerate(etable.header)}
        present_metrics = [m for m in OPERATIONS_EDGE_METRICS if m in ecol]
        if not present_metrics:
            raise ResultPackageInvalidError(
                f"no edge metric column; supported: {sorted(OPERATIONS_EDGE_METRICS)}",
                subject=EDGE_METRICS_MEMBER,
            )
        for m in present_metrics:
            require_canonical_unit(
                manifest, m, OPERATIONS_EDGE_METRICS[m], subject=EDGE_METRICS_MEMBER
            )
        erows: dict[tuple[float, int], dict[str, float]] = {}
        for r, row in enumerate(etable.rows, start=2):
            t = _time(row[ecol["time"]], name=EDGE_METRICS_MEMBER, row=r)
            k = index.index_of(row[ecol["edgeId"]].strip(), subject=EDGE_METRICS_MEMBER, row=r)
            values: dict[str, float] = {}
            if "utilization" in ecol:
                u = parse_float(
                    row[ecol["utilization"]], name=EDGE_METRICS_MEMBER, row=r, column="utilization"
                )
                if u is not None:
                    if u < 0.0 or u > 1.0:
                        raise ResultDataInvalidError(
                            f"row {r}: utilization {u} is not in [0, 1]",
                            subject=EDGE_METRICS_MEMBER,
                        )
                    values["utilization"] = u
            if "queueCount" in ecol:
                q = parse_int(
                    row[ecol["queueCount"]], name=EDGE_METRICS_MEMBER, row=r, column="queueCount"
                )
                if q is not None:
                    if q < 0:
                        raise ResultDataInvalidError(
                            f"row {r}: queueCount {q} < 0", subject=EDGE_METRICS_MEMBER
                        )
                    values["queueCount"] = float(q)
            for m in ("haulageTonnesPerHour", "travelTimeSeconds"):
                if m in ecol:
                    v = parse_float(row[ecol[m]], name=EDGE_METRICS_MEMBER, row=r, column=m)
                    if v is not None:
                        if v < 0.0:
                            raise ResultDataInvalidError(
                                f"row {r}: {m} {v} < 0", subject=EDGE_METRICS_MEMBER
                            )
                        values[m] = v
            if not values:
                raise ResultDataInvalidError(
                    f"row {r}: no metric value in the row", subject=EDGE_METRICS_MEMBER
                )
            if (t, k) in erows:
                raise ResultDataInvalidError(
                    f"row {r}: duplicate edge-metric sample for edge index {k} at time {t}",
                    subject=EDGE_METRICS_MEMBER,
                )
            erows[(t, k)] = values
        eordered = sorted(erows.items())
        em_count = len(eordered)
        em_time = np.asarray([t for (t, _), _ in eordered], dtype=np.float64)
        em_edge = np.asarray([k for (_, k), _ in eordered], dtype=np.int64)
        arrays["em_time"] = em_time
        arrays["em_edge"] = em_edge
        for m in OPERATIONS_EDGE_METRICS:
            arr = np.full(em_count, np.nan, dtype=np.float64)
            for i, (_, values) in enumerate(eordered):
                if m in values:
                    arr[i] = values[m]
            arrays[f"em_{m}"] = arr
            finite = arr[np.isfinite(arr)]
            metrics.append(
                ResultMetricAvailability(
                    name=m,
                    unit=OPERATIONS_EDGE_METRICS[m],
                    available=bool(finite.size),
                    sample_count=int(finite.size),
                    min=finite_or_none(float(finite.min())) if finite.size else None,
                    max=finite_or_none(float(finite.max())) if finite.size else None,
                )
            )
        em_times = sorted({t for (t, _), _ in eordered})
    else:
        for m in OPERATIONS_EDGE_METRICS:
            metrics.append(
                ResultMetricAvailability(
                    name=m,
                    unit=OPERATIONS_EDGE_METRICS[m],
                    available=False,
                    sample_count=0,
                    min=None,
                    max=None,
                )
            )

    # -- summary metrics (optional, long form) ---------------------------------- #
    summary: list[ResultSummaryMetric] = []
    notes: list[str] = [
        "identity: explicit MineNetwork edgeId only; agentId is simulation-local",
        "vehicle XYZ is a deterministic projection of edgeId + chainageFraction on the source "
        "snapshot centerline (visualization derivative, not an authority)",
        "no simulation quantity is computed by MineGen (external output only)",
    ]
    if package.has(SUMMARY_MEMBER):
        stable = read_csv_member(package, SUMMARY_MEMBER, required_columns=_SUMMARY_COLUMNS)
        scol = {name: i for i, name in enumerate(stable.header)}
        seen: set[str] = set()
        ignored: list[str] = []
        for r, row in enumerate(stable.rows, start=2):
            name = row[scol["metric"]].strip()
            unit = row[scol["unit"]].strip()
            if not name:
                raise ResultDataInvalidError(
                    f"row {r}: summary metric name is empty", subject=SUMMARY_MEMBER
                )
            if name in seen:
                raise ResultDataInvalidError(
                    f"row {r}: summary metric {name!r} repeated", subject=SUMMARY_MEMBER
                )
            seen.add(name)
            value = parse_float(row[scol["value"]], name=SUMMARY_MEMBER, row=r, column="value")
            if value is None:
                raise ResultDataInvalidError(
                    f"row {r}: summary metric {name!r} has no value", subject=SUMMARY_MEMBER
                )
            canonical = OPERATIONS_SUMMARY_METRICS.get(name)
            if canonical is None:
                ignored.append(name)
                continue
            if unit != canonical:
                raise ResultDataInvalidError(
                    f"row {r}: summary metric {name!r} unit {unit!r} is not the canonical "
                    f"{canonical!r}",
                    subject=SUMMARY_MEMBER,
                )
            summary.append(ResultSummaryMetric(name=name, value=value, unit=unit))
        if ignored:
            notes.append(
                "summary metrics not promoted (unknown to MineResult 1.0, no authority): "
                + ", ".join(sorted(ignored))
            )
    arrays["summary_names"] = str_array([s.name for s in summary])
    arrays["summary_values"] = np.asarray([s.value for s in summary], dtype=np.float64)
    arrays["summary_units"] = str_array([s.unit for s in summary])

    all_times = sorted(set(sample_times) | set(em_times))
    time_axis = ResultTimeAxis(
        kind=kind,
        unit="s" if kind == "ELAPSED_SECONDS" else "day",
        sample_count=len(all_times),
        start=all_times[0],
        end=all_times[-1],
    )
    counts = ResultCounts(
        edge_count=len({int(k) for k in s_edge} | {int(k) for k in arrays.get("em_edge", [])}),
        time_count=len(all_times),
        sample_count=n,
        vehicle_count=len(agents),
        edge_metric_sample_count=em_count,
    )
    files = [VEHICLES_MEMBER] + [m for m in (EDGE_METRICS_MEMBER, SUMMARY_MEMBER) if package.has(m)]
    return ImportedResult(
        arrays=arrays,
        time_axis=time_axis,
        metrics=metrics,
        counts=counts,
        summary_metrics=summary,
        notes=notes,
        imported_file_names=files,
        sign_convention=None,
    )
