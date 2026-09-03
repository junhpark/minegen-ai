"""Phase 19 — WARPED_VEIN world-only geometry regression suite.

A lightweight companion of the golden design-pipeline harness: fixed seeds
of the RANDOM_WARPED_VEIN preset are realized, their world is generated
and the DERIVED geometry is measured. Nothing here runs the legacy decline
pipeline — the typed Phase 20 deferral of that pipeline for implicit bodies
is the correct Phase 19 result and is checked separately by the API tests.

HARD CONTRACT (exact): realization success, shape-model version, planform
connectivity, lattice shape, mesh vertex / triangle counts, mesh
watertightness and orientation.

QUALITY metrics (tolerance, reported): bounding box, geometric volume,
min / max sampled thickness, morphology diagnostics, scene payload size.

RUNTIME (advisory): realization, world generation, contains throughput,
clearance build, mesh build.

    python -m minegen.regression warped-vein --label phase19_warped_vein --out golden
    python -m minegen.regression warped-vein-compare golden/a.json golden/b.json
"""

from __future__ import annotations

import csv
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from minegen.core.enums import ScenarioPreset
from minegen.core.models import Scenario
from minegen.export.scene_manifest import build_scene
from minegen.services.scenario_realizer import ScenarioRealizationError, realize_scenario
from minegen.world.synthetic_world import generate_world
from minegen.world.warped_vein import WarpedVeinOrebody

SUITE_VERSION = 1
#: fixed seeds of the world-only suite (12 cases, each ≈ 1–2 s)
SEEDS: tuple[int, ...] = (301, 302, 303, 304, 305, 306, 307, 308, 309, 310, 311, 312)
#: representative subset for CI
SMOKE_SEEDS: tuple[int, ...] = (301, 307)
#: contains-throughput probe size
CONTAINS_PROBE_POINTS = 500_000


@dataclass(frozen=True)
class WarpedVeinCase:
    seed: int
    fault_count: int = 1

    @property
    def key(self) -> str:
        return f"RANDOM_WARPED_VEIN-{self.seed}"


def suite(name: str) -> list[WarpedVeinCase]:
    seeds = SEEDS if name == "full" else SMOKE_SEEDS if name == "smoke" else None
    if seeds is None:
        raise ValueError(f"unknown suite {name!r}")
    return [WarpedVeinCase(s) for s in seeds]


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def run_case(case: WarpedVeinCase) -> dict[str, Any]:
    contract: dict[str, Any] = {}
    metrics: dict[str, Any] = {}
    runtime: dict[str, float | None] = {}
    record: dict[str, Any] = {
        "key": case.key,
        "seed": case.seed,
        "faultCount": case.fault_count,
        "contract": contract,
        "metrics": metrics,
        "runtime": runtime,
        "notes": [],
    }
    t0 = time.perf_counter()
    try:
        create = realize_scenario(ScenarioPreset.RANDOM_WARPED_VEIN, case.seed, case.fault_count)
    except ScenarioRealizationError as exc:  # a failure IS a result
        contract["realized"] = False
        record["notes"].append(str(exc))
        runtime["total"] = time.perf_counter() - t0
        return record
    runtime["realize"] = time.perf_counter() - t0
    contract["realized"] = True
    vein = create.orebody.warped_vein
    assert vein is not None
    contract["shapeModelVersion"] = vein.shape_model_version
    metrics["nominalLength"] = create.orebody.length
    metrics["nominalHeight"] = create.orebody.height
    metrics["nominalThickness"] = create.orebody.thickness
    metrics["warpAmplitude"] = vein.warp_amplitude
    metrics["centerlineDeviation"] = vein.centerline_deviation
    metrics["outlineIrregularity"] = vein.outline_irregularity
    metrics["thicknessVariability"] = vein.thickness_variability
    metrics["pinchFloorRatio"] = vein.pinch_floor_ratio
    metrics["edgeTaper"] = vein.edge_taper

    scenario = Scenario(**create.model_dump())
    t1 = time.perf_counter()
    world = generate_world(scenario)
    runtime["world"] = time.perf_counter() - t1
    ob = world.orebody
    assert isinstance(ob, WarpedVeinOrebody)

    lo, hi = ob.bounding_box()
    metrics["bboxMin"] = lo.tolist()
    metrics["bboxMax"] = hi.tolist()
    metrics["volumeM3"] = ob.volume()
    d = ob.morphology.diagnostics()
    contract["planformConnectedComponents"] = d["planformConnectedComponents"]
    metrics["minInteriorThickness"] = _f(d["minInteriorThickness"])
    metrics["maxInteriorThickness"] = _f(d["maxInteriorThickness"])
    metrics["midSurfaceRange"] = _f(d["midSurfaceMax"] - d["midSurfaceMin"])
    metrics["centerlineShiftRange"] = _f(d["centerlineShiftMax"] - d["centerlineShiftMin"])
    metrics["strikeEdgeAsymmetry"] = _f(d["strikeEdgeAsymmetry"])
    metrics["dipEdgeAsymmetry"] = _f(d["dipEdgeAsymmetry"])
    metrics["planformAreaM2"] = _f(d["planformAreaM2"])
    contract["latticeShape"] = list(ob.lattice.shape)
    metrics["latticeSpacing"] = ob.lattice.spacing.tolist()
    metrics["clearanceMaxAbsErrorEstimateM"] = ob.derived_clearance_metadata()[
        "maxAbsErrorEstimateM"
    ]

    rng = np.random.default_rng(case.seed)
    pts = rng.uniform(lo, hi, size=(CONTAINS_PROBE_POINTS, 3))
    t2 = time.perf_counter()
    inside = ob.contains(pts)
    dt = time.perf_counter() - t2
    runtime["containsProbe"] = dt
    metrics["containsPointsPerSecond"] = CONTAINS_PROBE_POINTS / dt if dt > 0 else None
    metrics["probeInsideFraction"] = float(inside.mean())

    t3 = time.perf_counter()
    _ = ob.derived.clearance_values
    runtime["clearance"] = time.perf_counter() - t3
    sign_ok = bool(np.all((ob.approximate_clearance(pts[:50_000]) <= 0.0) == inside[:50_000]))
    contract["clearanceSignAgreesWithContains"] = sign_ok

    t4 = time.perf_counter()
    verts, faces = ob.mesh()
    runtime["mesh"] = time.perf_counter() - t4
    contract["meshVertices"] = int(verts.shape[0])
    contract["meshTriangles"] = int(faces.shape[0])
    edges = np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    contract["meshWatertight"] = bool(np.all(counts == 2))
    rel = verts[faces] - ob.center
    signed = float(np.sum(np.einsum("ij,ij->i", rel[:, 0], np.cross(rel[:, 1], rel[:, 2])))) / 6
    contract["meshOutward"] = signed > 0
    metrics["meshSignedVolumeM3"] = signed
    metrics["meshVolumeRelError"] = abs(signed - metrics["volumeM3"]) / metrics["volumeM3"]
    contract["meshInsideBbox"] = bool(np.all(verts >= lo - 1e-6) and np.all(verts <= hi + 1e-6))

    t5 = time.perf_counter()
    scene = build_scene(scenario, world)
    runtime["scene"] = time.perf_counter() - t5
    payload = json.dumps(scene)
    metrics["scenePayloadBytes"] = len(payload)
    metrics["orebodyPayloadBytes"] = len(json.dumps(scene["orebody"]))
    metrics["geometryArrayBytes"] = int(
        ob.derived.level_values.nbytes + ob.derived.clearance_values.nbytes + verts.nbytes
    )
    runtime["total"] = time.perf_counter() - t0
    return record


def run_suite(cases: list[WarpedVeinCase], label: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    records = [run_case(c) for c in cases]
    return {
        "suiteVersion": SUITE_VERSION,
        "label": label,
        "semantics": (
            "world-only geometry of the deterministic synthetic WARPED_VEIN implicit "
            "solid; geometric volumes only — never resources, reserves or ore tonnage"
        ),
        "caseCount": len(records),
        "totalRuntimeSeconds": time.perf_counter() - t0,
        "cases": records,
    }


CONTRACT_COLUMNS = (
    "realized",
    "shapeModelVersion",
    "planformConnectedComponents",
    "latticeShape",
    "meshVertices",
    "meshTriangles",
    "meshWatertight",
    "meshOutward",
    "meshInsideBbox",
    "clearanceSignAgreesWithContains",
)
METRIC_COLUMNS = (
    "nominalLength",
    "nominalHeight",
    "nominalThickness",
    "warpAmplitude",
    "thicknessVariability",
    "pinchFloorRatio",
    "volumeM3",
    "minInteriorThickness",
    "maxInteriorThickness",
    "midSurfaceRange",
    "meshVolumeRelError",
    "scenePayloadBytes",
    "containsPointsPerSecond",
)
RUNTIME_COLUMNS = ("realize", "world", "clearance", "mesh", "scene", "total")


def write_report(report: dict[str, Any], out_dir: Path, name: str) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{name}.json"
    csv_path = out_dir / f"{name}.csv"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "key",
                "seed",
                *(f"contract.{c}" for c in CONTRACT_COLUMNS),
                *(f"metric.{m}" for m in METRIC_COLUMNS),
                *(f"runtime.{r}" for r in RUNTIME_COLUMNS),
            ]
        )
        for rec in report["cases"]:
            row: list[Any] = [rec["key"], rec["seed"]]
            row += [rec["contract"].get(c) for c in CONTRACT_COLUMNS]
            row += [rec["metrics"].get(m) for m in METRIC_COLUMNS]
            row += [rec["runtime"].get(r) for r in RUNTIME_COLUMNS]
            w.writerow(["" if v is None else v for v in row])
    return json_path, csv_path


def load_report(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def compare_reports(
    baseline: dict[str, Any], current: dict[str, Any], rel: float = 1e-9
) -> dict[str, Any]:
    """Exact contract comparison; metric drift reported with tolerance.
    Runtime is never compared."""
    base = {c["key"]: c for c in baseline["cases"]}
    cur = {c["key"]: c for c in current["cases"]}
    regressions: list[str] = []
    drifts: list[str] = []
    for key in sorted(set(base) | set(cur)):
        if key not in base or key not in cur:
            regressions.append(f"{key}: present in only one report")
            continue
        for c in CONTRACT_COLUMNS:
            if base[key]["contract"].get(c) != cur[key]["contract"].get(c):
                regressions.append(
                    f"{key}.{c}: {base[key]['contract'].get(c)!r} -> "
                    f"{cur[key]['contract'].get(c)!r}"
                )
        for m in METRIC_COLUMNS:
            a, b = base[key]["metrics"].get(m), cur[key]["metrics"].get(m)
            if isinstance(a, int | float) and isinstance(b, int | float):
                if not math.isclose(float(a), float(b), rel_tol=rel, abs_tol=1e-9):
                    drifts.append(f"{key}.{m}: {a} -> {b}")
            elif a != b:
                drifts.append(f"{key}.{m}: {a!r} -> {b!r}")
    return {
        "baseline": baseline["label"],
        "current": current["label"],
        "contractRegressions": regressions,
        "metricDrift": drifts,
    }
