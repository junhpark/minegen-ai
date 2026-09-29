"""Ventsim result importer (directive §25–§32, rule 218).

Input: the round-trip kit shape — ``result_manifest.json``,
``airway_results.csv`` and the optional ``airway_identity.csv`` crosswalk.
Identity is EXPLICIT: a row names a MineGen ``edgeId`` directly, or a
``ventsimUniqueNumber`` that the crosswalk maps to exactly one edge. No
nearest-airway / midpoint / endpoint / fuzzy spatial matching exists here
or anywhere else in this package. Values are stored in canonical SI units
(explicit conversions only), the airflow sign keeps the MineNetwork edge
sourceNodeId → targetNodeId reference axis, and the normalized form is
sorted by (time, edgeId) — input order is never an authority.
"""

from __future__ import annotations

import numpy as np

from minegen.results.errors import (
    ResultDataInvalidError,
    ResultIdentityAmbiguousError,
    ResultIdentityUnresolvedError,
    ResultPackageInvalidError,
)
from minegen.results.importers.common import EdgeIndex, ImportedResult, geometry_arrays
from minegen.results.models import (
    AIRFLOW_SIGN_CONVENTION,
    VENTILATION_METRICS,
    ResultCounts,
    ResultMetricAvailability,
    ResultPackageManifest,
    ResultTimeAxis,
)
from minegen.results.normalization import NormalizedResult, finite_or_none, str_array
from minegen.results.package import (
    MAX_UNIQUE_TIMES,
    ResultPackage,
    parse_float,
    read_csv_member,
)
from minegen.results.units import resolve_unit

RESULTS_MEMBER = "airway_results.csv"
IDENTITY_MEMBER = "airway_identity.csv"
VENTSIM_MEMBERS = frozenset({RESULTS_MEMBER, IDENTITY_MEMBER})
IDENTITY_COLUMNS = ("edgeId", "ventsimUniqueNumber")
TIME_COLUMN = "time"
_ALLOWED_COLUMNS = frozenset({*IDENTITY_COLUMNS, TIME_COLUMN, *VENTILATION_METRICS})


def _crosswalk(package: ResultPackage, index: EdgeIndex) -> dict[str, str]:
    """``ventsimUniqueNumber → edgeId`` from the EXPLICIT crosswalk; a
    number mapped to two edges is ambiguous, an unknown edge unresolved."""
    if not package.has(IDENTITY_MEMBER):
        return {}
    table = read_csv_member(package, IDENTITY_MEMBER, required_columns=IDENTITY_COLUMNS)
    col = {name: i for i, name in enumerate(table.header)}
    out: dict[str, str] = {}
    for r, row in enumerate(table.rows, start=2):
        edge_id = row[col["edgeId"]].strip()
        unique = row[col["ventsimUniqueNumber"]].strip()
        if not unique:
            continue  # a kit row the user did not fill: not a mapping
        if not edge_id:
            raise ResultIdentityUnresolvedError(
                f"row {r}: ventsimUniqueNumber {unique!r} has no edgeId", subject=IDENTITY_MEMBER
            )
        index.index_of(edge_id, subject=IDENTITY_MEMBER, row=r)
        if unique in out and out[unique] != edge_id:
            raise ResultIdentityAmbiguousError(
                f"ventsimUniqueNumber {unique!r} maps to both {out[unique]!r} and {edge_id!r}",
                subject=IDENTITY_MEMBER,
            )
        out[unique] = edge_id
    return out


def import_ventsim(package: ResultPackage, index: EdgeIndex) -> ImportedResult:
    manifest: ResultPackageManifest = package.manifest
    if manifest.result_domain != "VENTILATION" or manifest.source_application != "VENTSIM":
        raise ResultPackageInvalidError(
            "a Ventsim result package declares resultDomain VENTILATION and "
            "sourceApplication VENTSIM",
            subject="result_manifest.json",
        )
    kind = manifest.time_axis.kind
    if kind not in ("STATIC", "ELAPSED_SECONDS"):
        raise ResultDataInvalidError(
            f"timeAxis.kind {kind!r} is not supported for a ventilation result "
            "(STATIC | ELAPSED_SECONDS)",
            subject="result_manifest.json",
        )
    if not package.has(RESULTS_MEMBER):
        raise ResultPackageInvalidError("missing required file", subject=RESULTS_MEMBER)
    table = read_csv_member(package, RESULTS_MEMBER, required_columns=())
    unknown = sorted(set(table.header) - _ALLOWED_COLUMNS)
    if unknown:
        raise ResultPackageInvalidError(
            f"unknown columns {unknown}; supported: {sorted(_ALLOWED_COLUMNS)}",
            subject=RESULTS_MEMBER,
        )
    col = {name: i for i, name in enumerate(table.header)}
    if "edgeId" not in col and "ventsimUniqueNumber" not in col:
        raise ResultPackageInvalidError(
            "an identity column is required (edgeId or ventsimUniqueNumber)",
            subject=RESULTS_MEMBER,
        )
    metric_names = [m for m in VENTILATION_METRICS if m in col]
    if not metric_names:
        raise ResultPackageInvalidError(
            f"no result metric column; supported: {sorted(VENTILATION_METRICS)}",
            subject=RESULTS_MEMBER,
        )
    conversions = {
        m: resolve_unit(manifest, m, VENTILATION_METRICS[m], subject=RESULTS_MEMBER)
        for m in metric_names
    }
    crosswalk = _crosswalk(package, index)

    # -- rows → (time, edge index, values) ------------------------------------ #
    samples: dict[tuple[float, int], dict[str, float]] = {}
    for r, row in enumerate(table.rows, start=2):
        edge_id = row[col["edgeId"]].strip() if "edgeId" in col else ""
        unique = row[col["ventsimUniqueNumber"]].strip() if "ventsimUniqueNumber" in col else ""
        if edge_id:
            if unique and crosswalk.get(unique, edge_id) != edge_id:
                raise ResultIdentityAmbiguousError(
                    f"row {r}: edgeId {edge_id!r} disagrees with the crosswalk of "
                    f"ventsimUniqueNumber {unique!r} ({crosswalk[unique]!r})",
                    subject=RESULTS_MEMBER,
                )
        elif unique:
            if not crosswalk:
                raise ResultIdentityUnresolvedError(
                    f"row {r}: ventsimUniqueNumber {unique!r} needs the explicit "
                    f"{IDENTITY_MEMBER} crosswalk (ventsimUniqueNumber -> edgeId); none was "
                    "provided",
                    subject=RESULTS_MEMBER,
                )
            if unique not in crosswalk:
                raise ResultIdentityUnresolvedError(
                    f"row {r}: ventsimUniqueNumber {unique!r} is not in the crosswalk",
                    subject=RESULTS_MEMBER,
                )
            edge_id = crosswalk[unique]
        else:
            raise ResultIdentityUnresolvedError(
                f"row {r}: neither edgeId nor ventsimUniqueNumber", subject=RESULTS_MEMBER
            )
        k = index.index_of(edge_id, subject=RESULTS_MEMBER, row=r)
        time_cell = row[col[TIME_COLUMN]].strip() if TIME_COLUMN in col else ""
        if kind == "STATIC":
            if time_cell:
                raise ResultDataInvalidError(
                    f"row {r}: a STATIC result carries no time value ({time_cell!r})",
                    subject=RESULTS_MEMBER,
                )
            t = 0.0
        else:
            tv = parse_float(time_cell, name=RESULTS_MEMBER, row=r, column=TIME_COLUMN)
            if tv is None:
                raise ResultDataInvalidError(
                    f"row {r}: an ELAPSED_SECONDS result needs a time value",
                    subject=RESULTS_MEMBER,
                )
            if tv < 0.0:
                raise ResultDataInvalidError(f"row {r}: time {tv} < 0", subject=RESULTS_MEMBER)
            t = tv
        values: dict[str, float] = {}
        for m in metric_names:
            v = parse_float(row[col[m]], name=RESULTS_MEMBER, row=r, column=m)
            if v is not None:
                factor, offset = conversions[m]
                values[m] = v * factor + offset
        if not values:
            raise ResultDataInvalidError(
                f"row {r}: no result metric value in the row", subject=RESULTS_MEMBER
            )
        key = (t, k)
        if key in samples:
            raise ResultDataInvalidError(
                f"row {r}: duplicate sample for edge {edge_id!r} at time {t} (ambiguous)",
                subject=RESULTS_MEMBER,
            )
        samples[key] = values
    if not samples:
        raise ResultDataInvalidError("the result carries no sample row", subject=RESULTS_MEMBER)

    # -- canonical arrays: times sorted, (T, E) per metric, NaN = missing ------ #
    times = sorted({t for t, _ in samples})
    if len(times) > MAX_UNIQUE_TIMES:
        raise ResultDataInvalidError(
            f"{len(times)} distinct times; the limit is {MAX_UNIQUE_TIMES}", subject=RESULTS_MEMBER
        )
    t_index = {t: i for i, t in enumerate(times)}
    n_edges = len(index.ids)
    arrays: NormalizedResult = geometry_arrays(index)
    arrays["times"] = np.asarray(times, dtype=np.float64)
    arrays["metric_names"] = str_array(metric_names)
    metric_arrays = {
        m: np.full((len(times), n_edges), np.nan, dtype=np.float64) for m in metric_names
    }
    for (t, k), values in samples.items():
        for m, v in values.items():
            metric_arrays[m][t_index[t], k] = v
    metrics: list[ResultMetricAvailability] = []
    for m in metric_names:
        arr = metric_arrays[m]
        arrays[f"vent_{m}"] = arr
        finite = arr[np.isfinite(arr)]
        metrics.append(
            ResultMetricAvailability(
                name=m,
                unit=VENTILATION_METRICS[m],
                available=bool(finite.size),
                sample_count=int(finite.size),
                min=finite_or_none(float(finite.min())) if finite.size else None,
                max=finite_or_none(float(finite.max())) if finite.size else None,
            )
        )
    for m in VENTILATION_METRICS:
        if m not in metric_names:
            metrics.append(
                ResultMetricAvailability(
                    name=m,
                    unit=VENTILATION_METRICS[m],
                    available=False,
                    sample_count=0,
                    min=None,
                    max=None,
                )
            )
    sample_edges = {k for _, k in samples}
    time_axis = ResultTimeAxis(
        kind=kind,
        unit=None if kind == "STATIC" else "s",
        sample_count=len(times),
        start=None if kind == "STATIC" else times[0],
        end=None if kind == "STATIC" else times[-1],
    )
    counts = ResultCounts(
        edge_count=len(sample_edges), time_count=len(times), sample_count=len(samples)
    )
    files = [RESULTS_MEMBER] + ([IDENTITY_MEMBER] if package.has(IDENTITY_MEMBER) else [])
    notes = [
        "identity: explicit edgeId / ventsimUniqueNumber crosswalk only; no spatial matching",
        "values in canonical SI units (m3/s, m/s, Pa, degC, kg/m3); missing values are omitted",
    ]
    if crosswalk:
        notes.append(f"crosswalk: {len(crosswalk)} ventsimUniqueNumber -> edgeId mappings")
    return ImportedResult(
        arrays=arrays,
        time_axis=time_axis,
        metrics=metrics,
        counts=counts,
        notes=notes,
        imported_file_names=files,
        sign_convention=AIRFLOW_SIGN_CONVENTION,
    )
