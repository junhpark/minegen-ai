"""Frame / slice builders over a normalized result (directive §51–§57).

Ventilation: hold-last — the SOURCE sample at or before the requested time
is shown; nothing is interpolated between solver samples. Operations: a
vehicle between two of ITS samples on the SAME edge is linearly
interpolated in chainage (and XYZ); across an edge change the previous
sample is held until the next one (no route is invented); a vehicle exists
from its first to its last sample. Edge metrics are hold-last per edge.
Missing values are omitted, never zero-filled.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from minegen.results.errors import ResultDataInvalidError
from minegen.results.geometry import chainage_to_xyz
from minegen.results.models import (
    AIRFLOW_SIGN_CONVENTION,
    OPERATIONS_EDGE_METRICS,
    VENTILATION_METRICS,
    EdgeValue,
    OperationsEdgeMetric,
    OperationsFrame,
    OperationsVehicle,
    Placement,
    ResultEdgeGeometry,
    ResultGeometryPayload,
    TimeAxisKind,
    VentilationFrame,
)
from minegen.results.normalization import NormalizedResult


def _held_index(times: np.ndarray, t: float) -> int | None:
    """Index of the last sample time <= t (hold-last); ``None`` before the
    first sample — nothing is held before the result starts."""
    k = int(np.searchsorted(times, t, side="right") - 1)
    return None if k < 0 else k


def geometry_payload(result_id: str, arrays: NormalizedResult) -> ResultGeometryPayload:
    ids = arrays["edge_ids"]
    offsets = arrays["geom_offsets"]
    pts = arrays["geom_points"]
    edges = [
        ResultEdgeGeometry(
            edge_id=str(ids[i]),
            edge_type=str(arrays["edge_types"][i]),
            source_node_id=str(arrays["edge_source_nodes"][i]),
            target_node_id=str(arrays["edge_target_nodes"][i]),
            points=[[float(v) for v in p] for p in pts[offsets[i] : offsets[i + 1]]],
        )
        for i in range(len(ids))
    ]
    return ResultGeometryPayload(
        result_id=result_id, coordinate_frame="LOCAL_ENU_Z_UP", edges=edges
    )


def ventilation_frame(
    result_id: str,
    arrays: NormalizedResult,
    *,
    kind: TimeAxisKind,
    metric: str,
    time: float | None,
) -> VentilationFrame:
    if metric not in VENTILATION_METRICS:
        raise ResultDataInvalidError(
            f"unknown ventilation metric {metric!r}; supported: {sorted(VENTILATION_METRICS)}",
            subject="metric",
        )
    key = f"vent_{metric}"
    if key not in arrays:
        raise ResultDataInvalidError(
            f"metric {metric!r} is not available in this result", subject="metric"
        )
    times = arrays["times"]
    ids = arrays["edge_ids"]
    row: int | None
    if kind == "STATIC":
        row, sample_time, t_out = 0, None, None
    else:
        if time is None or not np.isfinite(time):
            raise ResultDataInvalidError("a time is required for a dynamic result", subject="time")
        row = _held_index(times, float(time))
        sample_time = None if row is None else float(times[row])
        t_out = float(time)
    values = (
        arrays[key][row]
        if row is not None
        else np.full(ids.shape[0], np.nan, dtype=np.float64)  # before the first sample
    )
    present = np.isfinite(values)
    out = [EdgeValue(edge_id=str(ids[i]), value=float(values[i])) for i in np.flatnonzero(present)]
    finite = values[present]
    return VentilationFrame(
        result_id=result_id,
        metric=metric,
        unit=VENTILATION_METRICS[metric],
        time_axis_kind=kind,
        time=t_out,
        sample_time=sample_time,
        values=out,
        missing_edge_ids=[str(ids[i]) for i in np.flatnonzero(~present)],
        min=float(finite.min()) if finite.size else None,
        max=float(finite.max()) if finite.size else None,
        sign_convention=AIRFLOW_SIGN_CONVENTION if metric == "airflowM3s" else None,
    )


def _vehicle(
    arrays: NormalizedResult, i: int, *, chain: float, xyz: np.ndarray, placement: Placement
) -> OperationsVehicle:
    agent = int(arrays["sample_agent"][i])
    kind = str(arrays["agent_kinds"][agent])
    status = str(arrays["sample_status"][i])
    load = float(arrays["sample_load"][i])
    return OperationsVehicle(
        agent_id=str(arrays["agent_ids"][agent]),
        agent_kind=kind or None,
        x=float(xyz[0]),
        y=float(xyz[1]),
        z=float(xyz[2]),
        edge_id=str(arrays["edge_ids"][int(arrays["sample_edge"][i])]),
        chainage_fraction=float(chain),
        status=status or None,
        load_tonnes=load if np.isfinite(load) else None,
        placement=placement,
    )


def operations_frame(
    result_id: str, arrays: NormalizedResult, *, kind: TimeAxisKind, time: float
) -> OperationsFrame:
    if not np.isfinite(time):
        raise ResultDataInvalidError("time must be finite", subject="time")
    s_time = arrays["sample_time"]
    s_agent = arrays["sample_agent"]
    vehicles: list[OperationsVehicle] = []
    n_agents = int(arrays["agent_ids"].shape[0])
    # samples are sorted by (time, agent): gather per agent
    for a in range(n_agents):
        idx = np.flatnonzero(s_agent == a)
        if idx.size == 0:
            continue
        t_a = s_time[idx]
        if time < t_a[0] or time > t_a[-1]:
            continue  # a vehicle exists from its first to its last sample
        k = int(np.searchsorted(t_a, time, side="right") - 1)
        i_prev = int(idx[k])
        if k + 1 < idx.size and float(t_a[k]) < time:
            i_next = int(idx[k + 1])
            same_edge = int(arrays["sample_edge"][i_prev]) == int(arrays["sample_edge"][i_next])
            if same_edge:
                span = float(t_a[k + 1] - t_a[k])
                u = 0.0 if span <= 0.0 else (time - float(t_a[k])) / span
                c0 = float(arrays["sample_chainage"][i_prev])
                c1 = float(arrays["sample_chainage"][i_next])
                chain = c0 + u * (c1 - c0)
                edge = int(arrays["sample_edge"][i_prev])
                off = arrays["geom_offsets"]
                pts = arrays["geom_points"][off[edge] : off[edge + 1]]
                xyz = chainage_to_xyz(pts, chain)
                vehicles.append(
                    _vehicle(arrays, i_prev, chain=chain, xyz=xyz, placement="INTERPOLATED")
                )
                continue
        # exact sample, or held across an edge change (no route invented)
        vehicles.append(
            _vehicle(
                arrays,
                i_prev,
                chain=float(arrays["sample_chainage"][i_prev]),
                xyz=arrays["sample_xyz"][i_prev],
                placement="SAMPLE",
            )
        )
    edge_metrics: list[OperationsEdgeMetric] = []
    if "em_time" in arrays and arrays["em_time"].shape[0]:
        em_time = arrays["em_time"]
        em_edge = arrays["em_edge"]
        ids = arrays["edge_ids"]
        for e in np.unique(em_edge):
            idx = np.flatnonzero(em_edge == e)
            t_e = em_time[idx]
            if time < t_e[0]:
                continue
            i = int(idx[int(np.searchsorted(t_e, time, side="right") - 1)])
            fields: dict[str, Any] = {}
            for m in OPERATIONS_EDGE_METRICS:
                v = float(arrays[f"em_{m}"][i])
                fields[m] = None if not np.isfinite(v) else v
            edge_metrics.append(
                OperationsEdgeMetric(
                    edge_id=str(ids[int(e)]),
                    sample_time=float(em_time[i]),
                    utilization=fields["utilization"],
                    queue_count=None if fields["queueCount"] is None else int(fields["queueCount"]),
                    haulage_tonnes_per_hour=fields["haulageTonnesPerHour"],
                    travel_time_seconds=fields["travelTimeSeconds"],
                )
            )
    return OperationsFrame(
        result_id=result_id,
        time_axis_kind=kind,
        time=float(time),
        vehicles=vehicles,
        edge_metrics=edge_metrics,
    )
