# External simulation results & MineGen overlay (Phase 23C)

Status: **DELIVERED as ONE phase (23C)**. CLAUDE.md rules 213–218 are the
binding invariants; `docs/external-adapters.md` §14 / §24 records the
adapter side (round-trip kits, adapters `VENTSIM 0.2.0` / `ANYLOGIC 0.2.0`).

Base: `main` `02ef481ccd23cd641004d67d2c96bc29ed50a2d6` (after PR #50,
Phase 23B). MineExchange stays **1.3.0**; MineResult is **1.0.0**.

## 1. What a MineResult is — and is not

A **MineResult** is an OBSERVATION of the mine made by an external
application over a MineExchange bundle:

* **Ventsim** — a ventilation result over the airways (VENTILATION domain,
  `sourceApplication = VENTSIM`);
* **AnyLogic** — an operations result over the network (OPERATIONS domain,
  `sourceApplication = ANYLOGIC`): vehicle samples, edge metrics, summary
  metrics.

It is bound to the exact MineExchange `sourceSnapshot` the bundle was
exported from and to stable MineExchange ids (MineNetwork edge ids). It is
**not** a mine description, not an authority for geometry, topology,
production, timeline, ranking or economics, never an input of any mine
artifact (no registry entry, no fingerprint role, no invalidation cascade)
and never exported back into a bundle or an adapter package (no feedback
loop). MineGen computes **no simulation quantity** from a result: the
backend stores, binds, normalizes and slices what the user delivered.

The input is a MineResult-compatible ZIP only — the filled round-trip kit
(`roundtrip/` of the Ventsim / AnyLogic export package). No `.vsm`, `.alp`,
Unity or `.uasset` file is parsed.

## 2. Package contract (MineResult 1.0)

    result_manifest.json      REQUIRED
    airway_results.csv        Ventsim: REQUIRED
    airway_identity.csv       Ventsim: optional (ventsimUniqueNumber → edgeId crosswalk)
    vehicle_samples.csv       AnyLogic: REQUIRED
    edge_metrics.csv          AnyLogic: optional
    summary_metrics.csv       AnyLogic: optional
    README.txt, manifest.json optional (ignored / the canonical export's stored manifest)

Members sit at the ZIP root or under exactly ONE top-level directory (the
`roundtrip/` folder zipped as-is works); nested directories, traversal,
absolute paths, duplicates and unknown members are refused.

`result_manifest.json`:

    mineResultVersion          "1.0.0"                       (anything else: RESULT_VERSION_UNSUPPORTED)
    resultDomain               VENTILATION | OPERATIONS
    sourceApplication          VENTSIM | ANYLOGIC            (must match the import route)
    sourceApplicationVersion   optional string
    sourceAdapter / sourceAdapterVersion / sourceMineExchangeVersion   (provenance, recorded)
    sourceScenarioId           the scenario the bundle was exported from
    sourceSnapshot             {scenarioRevision, arraysRevision, activeRampSource, artifactRevisions}
    runLabel, description      free text
    timeAxis.kind              STATIC | ELAPSED_SECONDS (ventilation) · ELAPSED_SECONDS | MINE_DAY (operations)
    units                      declared unit per delivered metric column
    unitConversions[]          {metric, sourceUnit, factor, offset}: canonical = value × factor + offset

The kit ships this manifest pre-filled (bound to the export's snapshot,
canonical units declared); the user edits the axis / label and fills the
tables.

### 2.1 Ventsim — `airway_results.csv`

Columns: `edgeId`, `ventsimUniqueNumber`, `time`, and any of
`airflowM3s` (m3/s), `velocityMs` (m/s), `pressurePa` (Pa),
`pressureLossPa` (Pa), `temperatureDryC` (degC), `temperatureWetC`
(degC), `airDensityKgM3` (kg/m3). Identity is EXPLICIT: `edgeId`
directly, or `ventsimUniqueNumber` resolved through `airway_identity.csv`
(`edgeId,ventsimUniqueNumber`; a number mapped to two edges is
RESULT_IDENTITY_AMBIGUOUS, an unknown / missing mapping is
RESULT_IDENTITY_UNRESOLVED). No spatial matching exists. STATIC rows leave
`time` empty; ELAPSED_SECONDS rows carry `time ≥ 0`. One sample per
(time, edge); at least one metric value per row; empty cells are MISSING
(never zero). **Airflow sign**: positive = MineNetwork edge sourceNodeId →
targetNodeId (the edge direction is the sign reference axis, never a
traffic direction).

### 2.2 AnyLogic — `vehicle_samples.csv`, `edge_metrics.csv`, `summary_metrics.csv`

`vehicle_samples.csv`: required `time`, `agentId`, `edgeId`,
`chainageFraction` (0 … 1 along sourceNodeId → targetNodeId); optional
`agentKind` (constant per agent), `status`, `loadTonnes` (t, ≥ 0 — a
delivered value requires the explicit `units.loadTonnes = "t"`
declaration, RESULT_UNIT_UNSUPPORTED otherwise; blank cells need none). One
sample per (agent, time). The backend projects XYZ along the SOURCE
snapshot centerline by arc length — a visualization derivative, never an
authority.

`edge_metrics.csv`: `time`, `edgeId`, any of `utilization` (fraction,
0 … 1), `queueCount` (integer ≥ 0), `haulageTonnesPerHour` (t/h, ≥ 0),
`travelTimeSeconds` (s, ≥ 0). One row per (time, edge).

`summary_metrics.csv`: long form `metric,value,unit`; known metrics
(`totalHauledTonnes` t, `meanCycleTimeSeconds` s, `meanUtilization`
fraction, `simulatedDurationSeconds` s, `vehicleCount` count) are promoted
to typed fields in their canonical unit; unknown names are recorded by
name only and carry no authority.

### 2.3 Units and time axes

Values are stored in canonical SI units. A delivered column must declare its
unit in `units`; a non-canonical unit is accepted ONLY through an explicit
`unitConversions[]` entry (ventilation metrics), otherwise
RESULT_UNIT_UNSUPPORTED. Operations metrics accept the canonical unit only.
The time axis is declared, never inferred; MINE_DAY values are planning
days of the MineTimeline scale, ELAPSED_SECONDS model seconds.

### 2.4 Validation and budgets

NaN / Inf / non-numeric cells, out-of-range values, negative times,
duplicate samples, an agent changing kind, an empty result, unknown
columns and a missing identity are typed RESULT_DATA_INVALID /
RESULT_PACKAGE_INVALID (422); a member the ZIP library cannot decode
(unsupported compression method) is RESULT_PACKAGE_INVALID, never a bare
500. Budgets (RESULT_LIMIT_EXCEEDED, 413): upload 64 MiB — a MEMORY budget,
enforced while the body streams in (a chunked / undeclared-length upload is
refused the moment the received bytes exceed it, never buffered first) —
32 members, 256 MiB declared uncompressed, 128 MiB per member,
1 000 000 rows per file, 5 000 agents, 100 000 distinct times, 64 KiB CSV
lines; a member whose payload disagrees with its declaration is refused
(ZIP bomb / truncation).

## 3. Binding, identity and compatibility

Import is `observe → parse → validate → re-observe → compare → publish`:

1. `ExchangeService.observe_edge_centerlines` observes the CURRENT
   `sourceSnapshot` (the Phase 23B manifest grammar, promoted from the
   export path — no second fingerprint calculator, no second artifact list)
   and the edge identity space through the SAME `assemble_centerlines` /
   `project_network` the bundle uses;
2. the package is read (§2) and must name THIS scenario
   (RESULT_SOURCE_SCENARIO_MISMATCH, 409) and EXACTLY the observed snapshot
   (RESULT_SOURCE_SNAPSHOT_MISMATCH, 409, naming the differing fields);
3. every identity is resolved explicitly, the values normalized;
4. under the scenario lock the snapshot is re-observed — a mine that moved
   during the import is READ_SNAPSHOT_CHANGED (409) and nothing is
   published — and the result folder is renamed into place atomically.

`resultId = sha256(canonical normalized content + sourceSnapshot + domain
+ sourceApplication)[:16]`: the same package imported twice is ONE result
(`created: false`, HTTP 200); a different snapshot yields a different
identity even for identical data.

On every read a stored result is judged against the CURRENT snapshot:
**COMPATIBLE** (identical) or **STALE**. A STALE result stays listed,
inspectable, exportable and deletable; its geometry and frames are refused
with RESULT_STALE (409) and the UI shows "STALE — this result was generated
from an older mine snapshot". Mine regeneration (scenario PUT, world /
design / network / timeline regeneration) NEVER deletes a result — only
`DELETE …/results/{id}` does.

## 4. Persistence

    data/scenarios/{id}/results/<resultId>/
        manifest.json      MineResultManifest (identity, snapshot, provenance, availability, digests)
        normalized.npz     canonical arrays (sorted samples, NaN = missing, string columns)
        source.zip         the imported ZIP, byte for byte (SHA-256 in the manifest)

`results/` is a sibling of `derived/`, never inside it. Publication is
atomic (temporary sibling directory, fsync, rename; a concurrent identical
import keeps ONE folder). Reading is READ ≠ TRUST: a manifest that does not
validate, a folder whose id disagrees with its manifest, or a normalized
container that does not reproduce `normalizedSha256` is
RESULT_PACKAGE_INVALID. Deletion renames the folder away first.

## 5. API

    POST   /api/v1/scenarios/{id}/results/import/ventsim     application/zip → 201 {created: true, result} | 200 {created: false, result}
    POST   /api/v1/scenarios/{id}/results/import/anylogic
    GET    /api/v1/scenarios/{id}/results                     {scenarioId, results[]}   (summary + compatibility per result)
    GET    /api/v1/scenarios/{id}/results/{resultId}          ResultDetail (metadata only, no samples)
    DELETE /api/v1/scenarios/{id}/results/{resultId}          204
    GET    /api/v1/scenarios/{id}/results/{resultId}/export   application/zip — canonical MineResult 1.0 (deterministic bytes, re-importable)
    GET    /api/v1/scenarios/{id}/results/{resultId}/geometry ResultGeometryPayload (source-snapshot edge centerlines, LOCAL_ENU_Z_UP) — STALE refused
    GET    /api/v1/scenarios/{id}/results/{resultId}/ventilation?metric=&time=   VentilationFrame — STALE refused
    GET    /api/v1/scenarios/{id}/results/{resultId}/operations/frame?time=      OperationsFrame — STALE refused

Every route is read-only over the mine: none generates, regenerates or
mutates a mine artifact, and no background job exists. Errors:

    RESULT_PACKAGE_INVALID           422   RESULT_VERSION_UNSUPPORTED        422
    RESULT_SOURCE_SCENARIO_MISMATCH  409   RESULT_SOURCE_SNAPSHOT_MISMATCH   409
    RESULT_IDENTITY_UNRESOLVED       409   RESULT_IDENTITY_AMBIGUOUS         409
    RESULT_UNIT_UNSUPPORTED          422   RESULT_DATA_INVALID               422
    RESULT_LIMIT_EXCEEDED            413   RESULT_NOT_FOUND                  404
    RESULT_STALE                     409   RESULT_PUBLICATION_FAILED         500
    READ_SNAPSHOT_CHANGED            409   (mine moved during the import)
    SCENARIO_NOT_FOUND 404 · WORLD_NOT_GENERATED 409 (the existing ladder)

Frames are slices of the stored arrays: ventilation is **hold-last** (the
sample at or before the requested time; before the first sample nothing is
held; STATIC ignores `time`; edges without a value are listed in
`missingEdgeIds`, never zero-filled); operations places every vehicle that
exists at the time (first … last sample) — interpolated ONLY between two
samples of the same agent on the SAME edge (`placement = INTERPOLATED`),
otherwise the previous sample held (`SAMPLE`); edge metrics hold-last per
edge.

## 6. Frontend

Analysis › **Simulation Results** (no new AppMode; the fifth Analysis tab,
a separate container beside the read panel, mounted for every tab per
Phase 20E §19):

* import: `.zip` picker + source select (Ventsim | AnyLogic), loading state,
  typed refusal shown verbatim, notice on success (created / identical);
* list: every result with its compatibility badge (Compatible / Stale +
  the STALE sentence), domain · application · time axis · counts, Show /
  Hide overlay (disabled for STALE), Export, Delete, Details;
* the active result's controls: the metric selector (it offers ONLY the
  metrics the result carries — `metrics[].available` from the backend
  manifest; activation keeps the current metric when the result carries it,
  else the first available one; a frame is committed to the overlay only for
  the active result AND the selected metric, so a previous metric's frame is
  never shown under a new metric's label, not even as a placeholder), the
  RESULT CLOCK (its own
  axis — "Mine day 123.4" for MINE_DAY, "t = 123 s" for seconds, none for
  STATIC; play / pause / speed for operations), the legend (name, unit,
  min, max), a manual display range, the airflow-arrow toggle;
* `resultsStore` (frontend-only, reset on every scenario transition) holds
  `activeVentilationResultId` / `activeOperationsResultId`, the metric,
  range and clock choices and the last backend frames;
  `SimulationOverlayController` (outside the canvas) fetches geometry once
  and frames per (metric, quantized time) under the React Query keys
  `['simulation-results', scenarioId]`, `['simulation-result', scenarioId,
  resultId, 'geometry']`, `['simulation-result-frame', scenarioId,
  resultId, metric, time]`; import / delete invalidate the results list
  ONLY (no epoch bump, no scene reload).
* overlays: `VentilationResultLayer` (line segments over the source
  centerlines coloured by the frame, missing = neutral, optional arrows
  from the sign) and `OperationsResultLayer` (edge heatmap by the chosen
  metric + vehicle markers with an agentId / kind / status / load
  tooltip), layers `ventilationResult`, `operationsHeatmap`,
  `operationsVehicles` (default ON, Layers › Simulation results). Both
  overlays may show simultaneously; they are never mounted in the
  walkthrough, are never colliders and never recolour the base mesh.

## 7. Round-trip kits (adapters 0.2.0)

See `docs/external-adapters.md` §24. The Ventsim and AnyLogic export
packages carry `roundtrip/` with the pre-filled manifest, the empty tables
(Ventsim: one pre-identified row per airway; AnyLogic: header rows) and a
README; the adapter manifest lists them under `details.roundTripKit`.
Unity / Unreal packages are unchanged (0.1.0).

## 8. Tests

* `tests/test_results_contract.py` — MR-1…9: versions, package security /
  budgets, normalization / identity, chainage projection, units, atomic
  store, error table, frame builders, canonical export;
* `tests/test_results_ventsim.py` — V-1…11 over the FAST real LEGACY chain;
* `tests/test_results_anylogic.py` — A-1…11;
* `tests/test_results_api.py` — lifecycle, upload guards, binding, STALE
  survival across network / world / scenario regeneration, read-only /
  no-generation / no-feedback proofs, scenario scoping, export
  determinism and re-import identity, race protection, corrupt-folder
  refusals, folder layout;
* `tests/test_results_e2e.py` (e2e) — the layout-v2 Longhole chain;
* adapter tests cover the kits (`test_adapters_core`, per-adapter);
* frontend: `results/*.test.ts`, `stores/resultsStore.test.ts`,
  `stores/scenarioSession.test.ts`, `SimulationResultsBody.test.tsx`,
  `simulationResultsIsolation.test.ts`.

## 9. Not in scope

Vendor file parsing, automatic Ventsim / AnyLogic execution, result-driven
redesign or ranking, results inside MineExchange / adapter packages,
walkthrough overlays, interpolation across edges, ventilation or haulage
physics of any kind, calibration, statutory ventilation compliance.
