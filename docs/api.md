# API (v0.1)

Base path: `/api/v1`. All payloads are JSON, all coordinates are ENU Z-up
meters (`docs/coordinate-system.md`). Schemas live in
`backend/src/minegen/core/models.py` and are mirrored in
`frontend/src/types/`.

## Implemented

    GET  /api/v1/health                              liveness + version + coordinate system
    POST /api/v1/scenarios/realize                   Phase 17: deterministic scenario
                                                     realization; NON-persistent (see below)
    POST /api/v1/scenarios                           create scenario from ScenarioCreate
    GET  /api/v1/scenarios                           list scenario summaries
    GET  /api/v1/scenarios/{id}                      fetch scenario document
    PUT  /api/v1/scenarios/{id}                      replace scenario document; deletes
                                                     arrays.npz and derived/* (rule 40) — ONE
                                                     locked mutation (AC-01F)
    POST /api/v1/scenarios/{id}/world/generate       generate terrain / orebody / spatial fields
                                                     (rock quality, grade, fault measurements);
                                                     persists arrays.npz (field_artifact_version);
                                                     returns neutral field stats
                                                     (409 JOB_INPUTS_CHANGED if scenario.json
                                                     moved during generation — nothing persisted)
    GET  /api/v1/scenarios/{id}/world                stats (409 WORLD_NOT_GENERATED if missing;
                                                     409 WORLD_ARTIFACT_INCOMPATIBLE when arrays.npz
                                                     predates the Phase-18 field artifact)
    GET  /api/v1/scenarios/{id}/world/slice          ?field=rockQuality|grade|faultInfluence|
                                                     faultZone&axis=x|y|z&index=n → values plus a
                                                     display mask (BELOW_TERRAIN, or for grade
                                                     OREBODY_INTERSECTION_BELOW_TERRAIN — cells
                                                     intersecting the analytic solid, never a
                                                     point-membership claim)
    GET  /api/v1/scenarios/{id}/scene                web scene manifest (terrain heightmap,
                                                     orebody mesh, fault polygons, fieldGrid
                                                     lattice description, default rock-quality
                                                     slice, stats)

    Scenario documents are schemaVersion 2 (Phase 18): `fieldSampling
    {spacingX, spacingY, spacingZ}` replaces the v1 `blockModel {dx, dy, dz}`.
    A v1 document is migrated on first read (numbers carried over, derived
    artifacts discarded); a POST body may still carry `blockModel` and is
    migrated at the boundary. A document newer than the backend is a typed
    422 SCENARIO_SCHEMA_UNSUPPORTED.

    POST /api/v1/scenarios/{id}/design/targets       levels + footwall candidates; persists
                                                     derived/targets.json; 409 if no world
    GET  /api/v1/scenarios/{id}/design/targets       409 TARGETS_NOT_GENERATED if missing
    POST /api/v1/scenarios/{id}/design/cost/evaluate {"points": [[x,y,z], …]} (≤ 200k) →
                                                     per-point cost components + reasons
    POST /api/v1/scenarios/{id}/design/decline       submits a chained Hybrid-A* decline job →
                                                     202 {jobId, status: QUEUED, scenarioId, kind};
                                                     ?maxLevels=n; ?sync=true runs inline (200,
                                                     tests/CLI). 409 JOB_ALREADY_RUNNING (detail
                                                     carries jobId) while a job for the scenario
                                                     is QUEUED/RUNNING. Result persists to
                                                     derived/decline.json.
    GET  /api/v1/scenarios/{id}/design/decline       409 DECLINE_NOT_GENERATED if missing
    POST …/design/decline/smooth                     submits a smoothing + revalidation job
                                                     (kind SMOOTH) → 202 {jobId, …}; ?sync=true
                                                     runs inline. 409 DECLINE_NOT_GENERATED
                                                     without a persisted decline. Result persists
                                                     to derived/decline_smoothed.json; regenerating
                                                     the decline or targets deletes it (rule 64).
    GET  …/design/decline/smooth                     409 SMOOTHED_NOT_GENERATED if missing

    POST …/design/tunnel                             submits a tunnel-mesh job (Phase 06)
                                                     202 {jobId, kind: MESH} · ?sync=true runs inline
                                                     409 SMOOTHED_NOT_GENERATED without a smoothed decline
    GET  …/design/tunnel                             persisted mesh report (rule 67)
                                                     409 TUNNEL_NOT_GENERATED if missing
    GET  …/design/tunnel/mesh.glb                    binary glTF, model/gltf-binary,
                                                     immutable cache headers; use the report's
                                                     cache-busted meshUrl (?v=<sha16>). Every
                                                     SEGMENT primitive's extras carry
                                                     indexStride / ringIntervalCount /
                                                     ringChainageFractions (Phase 20B.2-F
                                                     progressive-reveal metadata, rule 173)
    POST …/design/development-mesh                   Phase 20B closeout: LEVEL_ACCESS / DRIFT /
                                                     CROSSCUT excavation meshes swept on their
                                                     owning centerlines (kind DEVELOPMENT_MESH)
                                                     → 202 {jobId, …}; ?sync=true runs inline.
                                                     409 LEVELS_NOT_GENERATED without levels.
                                                     Report: byKind counts / rings / triangles /
                                                     length / nominal volume, per-development
                                                     endpoint policy (CAP | OPEN) and topology
                                                     QA, profile tessellation, primitives
                                                     (draw calls), glbBytes, generationSeconds
    GET  …/design/development-mesh                   409 DEVELOPMENT_MESH_NOT_GENERATED if missing
    GET  …/design/development-mesh/mesh.glb          binary glTF (one tube + one cap primitive per
                                                     kind, `ranges` extras → development / piece
                                                     ids, each range with its own indexStride /
                                                     ringIntervalCount / ringChainageFractions,
                                                     rule 173); deleted with levels.json / the
                                                     ramp chain
    POST …/design/layout-v2                          Phase 20A parametric family search
                                                     (kind LAYOUT_V2) → 202 {jobId, …}; ?sync=true
                                                     runs inline. Every orebody type (EXACT or
                                                     COARSE/REFINED_CONSERVATIVE clearance). Persists
                                                     derived/layout_v2.json; deletes a stale
                                                     selection and, if LAYOUT_V2 is active, the
                                                     ramp-derived chain (rule 151). Phase 20C.1-S:
                                                     `scenario.layout.switchback.stationLengthsM`
                                                     (null → [0, 2 × minimumTurnoutStraightBuffer])
                                                     adds arc–straight–arc hairpin-station
                                                     candidates (`-s<m>` in the id, stationLengthM
                                                     in params, derived.stationLength / legSpacing)
    GET  …/design/layout-v2                          catalogue · 409 LAYOUT_V2_NOT_GENERATED.
                                                     Phase 20C.1-Q: every cheap-feasible candidate
                                                     carries `accessScreen` {blockedLevelIds,
                                                     blockedCount, authority, levels{blocked,
                                                     reason, rejectionCounts}} — the
                                                     evaluator-free stage-4 access gates
                                                     (rule 176), the stage-3 ordering prefix,
                                                     never a rejection. `authority` (closeout B)
                                                     is NECESSARY_CONDITION under an EXACT
                                                     clearance policy and HEURISTIC under a
                                                     conservative one, where stage-4 refinement
                                                     may still serve a blocked level (measured:
                                                     56 such false blocks). Either way the count
                                                     orders the shortlist and never removes a
                                                     candidate; feasibility is stage 4's
    POST …/design/layout-v2/select {candidateId}     materialize a FEASIBLE candidate as
                                                     derived/layout_v2_selected.json (source unchanged)
                                                     404 LAYOUT_V2_CANDIDATE_NOT_FOUND ·
                                                     422 LAYOUT_V2_CANDIDATE_INFEASIBLE
    GET  …/design/layout-v2/selected                 409 LAYOUT_V2_NOT_SELECTED if missing
    POST …/design/layout-v2/activate {candidateId}   select + set active source LAYOUT_V2
                                                     → {rampSource, selected}
    GET  …/design/level-accesses                     Phase 20B: ramp junctions + level-access
                                                     branches + development anchors of the selected
                                                     candidate (derived/level_accesses.json, written
                                                     with the selection; rule 157). Each access
                                                     carries effectivePreferredAccessLength,
                                                     lengthDeviationFromPreferred and selectionCost;
                                                     Phase 20B.2-A one-turn CS connector: connector
                                                     ∈ S | LS | RS, terminalHeadingDeg is the actual
                                                     final-straight heading (position-only weld at
                                                     the entry), terminalHeadingMismatchDeg (vs the
                                                     drift axis, 0–90, reported never gated),
                                                     turnoutArcLength, straightLength,
                                                     pathToChordRatio; summary adds
                                                     maxTerminalHeadingMismatchDeg,
                                                     maxTurnoutArcLength, maxPathToChordRatio and
                                                     connectorWords {S, LS, RS} counts;
                                                     the summary carries the preferred length, its
                                                     source (DEFAULT_6X_TUNNEL_WIDTH | EXPLICIT) and
                                                     the mean / max |ΔP| (rule 163). Phase 20B.1 O
                                                     separation observability per access:
                                                     junctionToEntryPlanSep, junctionToEntryDist3d,
                                                     rampCenterlineDistance, excavationSeparation
                                                     (direction-aware rock pillar: centerline
                                                     distance minus each gravity-aligned profile's
                                                     support along the closest-pair direction —
                                                     width/2 + width/2 for parallel drives,
                                                     height + 0 for stacked ones; a sampled
                                                     cross-section gap, not an exact swept-surface
                                                     distance; branch samples within the taper arc
                                                     of the junction excluded) and turnoutHeadingChangeDeg
                                                     (cumulative |Δheading| of the delivered main
                                                     ramp over junction ± 25 m chainage); summary
                                                     aggregates minJunctionToEntryPlanSep,
                                                     minExcavationSeparation,
                                                     maxTurnoutHeadingChangeDeg. Phase 20B.1 B
                                                     hard gates (typed, never clamped):
                                                     INSUFFICIENT_RAMP_TO_ENTRY_SEPARATION
                                                     (plan sep < min, None → 6 × width),
                                                     INSUFFICIENT_RAMP_PILLAR (excavation
                                                     separation < min, None → 2 × width, judged
                                                     beyond the geometry-derived turnout taper,
                                                     terminal always included) and
                                                     TURNOUT_NOT_STRAIGHT (cumulative |Δheading|
                                                     over junction ± minimumTurnoutStraightBuffer
                                                     above maximumTurnoutHeadingChangeDeg).
                                                     Summary carries the resolved gate values +
                                                     gateTaperArc; a level failed with spacing
                                                     conflicts carries assignmentDiagnostic
                                                     (B-5 starvation vs geometry)
                                                     409 LEVEL_ACCESSES_NOT_GENERATED if missing
    GET  …/design/ramp-source                        {activeSource, owningArtifact, available, …}
    PUT  …/design/ramp-source {activeSource}         LEGACY | LAYOUT_V2 (409 LAYOUT_V2_NOT_SELECTED
                                                     without a selection, LAYOUT_V2_SELECTION_STALE /
                                                     LAYOUT_V2_CLEARANCE_MISMATCH / ARTIFACT_MALFORMED
                                                     when the selection is present but not VALID —
                                                     AC-01F: the guards run BEFORE the write, so a
                                                     refused switch changes no byte);
                                                     a change deletes every ramp-derived artifact,
                                                     never geology
    GET  …/design/ramp                               the ACTIVE Effective Ramp (rule 149):
                                                     sourceKind LEGACY_SMOOTHED |
                                                     LEGACY_RAW_FALLBACK | PARAMETRIC_V2,
                                                     owningArtifact, sourceRevision, segments[]
                                                     409 SMOOTHED_NOT_GENERATED (LEGACY) /
                                                     LAYOUT_V2_NOT_SELECTED (LAYOUT_V2)
    (tunnel, levels, network, timeline, communication and sensors all consume
     the ACTIVE Effective Ramp; the scene's smoothedDecline is that ramp and
     legacySmoothedDecline / rampSource / layoutV2 / layoutV2Selected are added.
     With LAYOUT_V2 active, tunnel / levels / development-mesh are judged under
     the selected candidate's own stage-4 clearance certification, rebuilt from
     candidateId + layoutRevision (Phase 20B.1-v2 1.1): 409
     LAYOUT_V2_SELECTION_STALE when the selection belongs to another catalogue
     revision, 409 LAYOUT_V2_CLEARANCE_MISMATCH when the rebuilt policy
     disagrees with the recorded one. level_accesses.json carries the
     candidate's actual clearanceBasis / clearanceErrorBound /
     clearanceRefinement; the catalogue's clearanceBasis stays whole-body.)
    GET  /api/v1/jobs?scenario_id=                    job records (newest first, no result)
    (jobs fail with error.code JOB_INPUTS_CHANGED — nothing persisted — when
     scenario/world/targets were mutated while the job ran; rule 60)
    GET  /api/v1/jobs/{jobId}?includeResult=true     status QUEUED|RUNNING|SUCCEEDED|FAILED,
                                                     progress {stage, phase, level, total_levels,
                                                     candidate, total_candidates, progress,
                                                     expanded_states, …}, result, error
    WS   /ws/jobs/{jobId}                            {"type":"progress", …record…} on every
                                                     change (≤ 10 Hz), then {"type":"done"};
                                                     {"type":"error","code":"JOB_NOT_FOUND"}
    GET  …/scene                                     includes "accessTargets", "decline",
                                                     "smoothedDecline", "tunnelMesh" and
                                                     "developmentMesh" (or null)
    POST /api/v1/scenarios/{id}/design/levels        Phase 08: synchronous level developments
                                                     (typed LevelsPayload; 409 SMOOTHED_NOT_GENERATED
                                                     without a Phase 05 artifact)
    GET  /api/v1/scenarios/{id}/design/levels        Phase 08: persisted typed LevelsPayload
                                                     (409 LEVELS_NOT_GENERATED after invalidation)
                                                     Phase 20C.2A: the payload declares
                                                     developmentGeometry (TABULAR_RULE_43 |
                                                     SECTION_FOOTWALL_OFFSET_TRACE); an implicit
                                                     orebody SUCCEEDS along the curved section-trace
                                                     backbone (crosscut reports carry
                                                     terminalContactGap <= 1e-6 m; from_u / to_u /
                                                     station_u are trace CHAINAGE there); level-access
                                                     anchors carry traceChainage / traceLength /
                                                     localTangent / localNormal / oreContact /
                                                     selectedComponentId / section spacings; typed
                                                     failures: SECTION_FOOTWALL_AMBIGUOUS,
                                                     SECTION_TRACE_OFFSET_INVALID,
                                                     SECTION_TRACE_ANCHORS_REQUIRED,
                                                     SECTION_TRACE_MISMATCH,
                                                     SECTION_RESOLUTION_BUDGET_EXCEEDED,
                                                     SECTION_STANDOFF_NONPOSITIVE
    POST /api/v1/scenarios/{id}/design/stopes        Phase 09: synchronous planned stopes
                                                     (typed StopesPayload; 409 LEVELS_NOT_GENERATED
                                                     without the Phase 08 artifact; UNSUPPORTED
                                                     methods yield explicit FAILED payloads)
    GET  /api/v1/scenarios/{id}/design/stopes        Phase 09: persisted typed StopesPayload
                                                     (409 STOPES_NOT_GENERATED after invalidation)
    POST /api/v1/scenarios/{id}/design/timeline      Phase 10: synchronous deterministic
                                                     precedence-only MineTimeline baseline
                                                     (typed TimelinePayload; 409 NETWORK_NOT_GENERATED /
                                                     STOPES_NOT_GENERATED without prerequisites;
                                                     FAILED prerequisites yield typed FAILED payloads;
                                                     regeneration touches nothing upstream, rule 86)
    GET  /api/v1/scenarios/{id}/design/timeline      Phase 10: persisted typed TimelinePayload
                                                     (409 TIMELINE_NOT_GENERATED after invalidation)
                                                     20C.1-V (rule 174): every development also
                                                     carries excavationStartNode +
                                                     progressDirection (+1 / −1) beside its
                                                     geometry-ordered pointChainageFractions
    POST /api/v1/scenarios/{id}/network/generate     Phase 07/08: synchronous MineNetwork rebuild
                                                     (typed NetworkPayload; 409 SMOOTHED_NOT_GENERATED /
                                                     LEVELS_NOT_GENERATED without prerequisites)
    GET  /api/v1/scenarios/{id}/network              Phase 07: persisted typed NetworkPayload
                                                     (404 NETWORK_NOT_GENERATED after upstream
                                                     invalidation)
    POST /api/v1/scenarios/{id}/infrastructure/communication
                                                     Phase 11: synchronous deterministic connected
                                                     communication placement baseline (typed
                                                     CommunicationPayload; MESH_ROUTER only;
                                                     network-geodesic proxy, not RF prediction;
                                                     409 NETWORK_NOT_GENERATED / SMOOTHED_NOT_GENERATED /
                                                     LEVELS_NOT_GENERATED without prerequisites;
                                                     regeneration touches nothing upstream, rule 92)
    GET  /api/v1/scenarios/{id}/infrastructure/communication
                                                     Phase 11: persisted typed CommunicationPayload
                                                     (409 COMMUNICATION_NOT_GENERATED after
                                                     network/upstream invalidation)
    POST /api/v1/scenarios/{id}/infrastructure/sensors
                                                     Phase 12: synchronous deterministic monitoring
                                                     placement baseline (typed SensorPayload;
                                                     GAS_SENSOR only; network-geodesic layout proxy,
                                                     not gas dispersion or detection modelling;
                                                     communication.json is NOT required — siblings;
                                                     409 NETWORK_NOT_GENERATED / SMOOTHED_NOT_GENERATED /
                                                     LEVELS_NOT_GENERATED without prerequisites;
                                                     regeneration touches nothing else, rule 98)
    GET  /api/v1/scenarios/{id}/infrastructure/sensors
                                                     Phase 12: persisted typed SensorPayload
                                                     (409 SENSORS_NOT_GENERATED after
                                                     network/upstream invalidation)

### POST /api/v1/scenarios/realize (Phase 17)

Deterministic scenario realization: turns a preset + seed into a fully
resolved `ScenarioCreate`. **Non-persistent** — nothing is written, no
scenario id is assigned; the client inspects (and may explicitly edit)
the returned document and then submits it to `POST /api/v1/scenarios`
like any other create payload.

Request body:

    preset      BASELINE | RANDOM_TABULAR | RANDOM_ELLIPSOID
                | RANDOM_WARPED_VEIN                           (default BASELINE)
    seed        integer                                        (default 42)
    faultCount  integer 0-6 or null                            (RANDOM_* only;
                                                                BASELINE has exactly
                                                                one fixed fault)

Response `200`: a fully resolved `ScenarioCreate` (same schema as the
create payload). BASELINE performs zero random draws and reproduces the
reference mine; RANDOM_* presets draw the orebody and faults from their
own independent seed sub-streams, so the same preset + seed + faultCount
always yields byte-identical parameters, and changing the fault count
never moves the orebody (rule 121).

Errors:

    422 SCENARIO_REALIZATION_INVALID   invalid options (e.g. faultCount on
                                       BASELINE, count outside 0-6) or bounded
                                       deterministic retries exhausted without a
                                       candidate whose ACTUAL geometry fits inside
                                       the model volume (rules 122, 125)

Note that a realized non-TABULAR orebody is fully supported for world
generation and visualization, but the legacy Phase 03+ layout rejects it
with `422 UNSUPPORTED_OREBODY_FOR_LEGACY_LAYOUT` until the Phase 20
generalized layout (rule 123). For WARPED_VEIN this covers
`POST …/design/targets` AND `POST …/design/cost/evaluate` (rule 135).

#### WARPED_VEIN documents (Phase 19)

`orebody.orebodyType = "WARPED_VEIN"` requires the resolved morphology
block `orebody.warpedVein` (and the block is forbidden on any other
type):

    shapeModelVersion     1 (mandatory; unsupported versions → 422)
    warpAmplitude         m, 0–200      centerlineDeviation   m, 0–300
    outlineIrregularity   0–0.6         thicknessVariability  0–0.9
    pinchFloorRatio       (0, 1]        edgeTaper             0.1–1
    geometryResolution    m, 2–25       (DERIVED geometry lattice only)
    warpModes / deviationModes / outlineModes / thicknessModes
                          1–8 × {ku, kv (0–3), phaseU, phaseV, weight ∈ [−1, 1]}

`thicknessVariability <= 1 − pinchFloorRatio` is validated (the floor
holds by construction). `length` / `height` / `thickness` are NOMINAL.
The client never generates the mode lists: obtain them from
`POST /scenarios/realize` with `RANDOM_WARPED_VEIN`.

`POST …/world/generate` answers `422 OREBODY_GEOMETRY_BUDGET_EXCEEDED`
when an edited body's derived geometry lattice would exceed the supported
budget (the shape is never silently coarsened).

Scene / world payload additions (`orebody`):

    distanceContract      EXACT_METRIC_SDF | DERIVED_APPROXIMATE_CLEARANCE
    volumeMethod          "analytic" | {method, spacingM, relativeTolerance, semantics}
    meshVertices, meshTriangles
    nominalHalfExtents, shapeModelVersion, morphology {controls + 2-D
    diagnostics}, clearance {latticeSpacing, maxAbsErrorEstimateM, exact:false},
    geometryLattice {spacing, shape, cellCount}, bboxSemantics   (WARPED_VEIN)
    halfExtents (TABULAR) / semiAxes (ELLIPSOID)

The mesh is a backend-authored DERIVATIVE of the implicit solid for
rendering; membership is `contains` (φ ≤ 0) only. The grade slice mask
keeps `OREBODY_INTERSECTION_BELOW_TERRAIN` semantics for every type.

## Reading a persisted artifact (AC-01F)

Every persisted derived artifact is read through ONE validated read authority
(`backend/src/minegen/services/artifact_reader.py`). A read observes the files
of one scenario under the per-scenario store lock — the same lock every writer
holds across its write AND its cascade — and then classifies each artifact:

| state | meaning | direct route | `GET …/scene` |
|---|---|---|---|
| ABSENT | the artifact file does not exist | its own `*_NOT_GENERATED` code (see the drift note below) | `null` |
| VALID | exists, parses to a JSON object, satisfies its payload model / first-level shape, and passes every provenance check of the same observation | 200, unchanged bytes | the payload |
| STALE | well-shaped, but a persisted provenance field disagrees with the live revision of the upstream file it names, or a co-published pair disagrees | 409 | the whole scene is refused |
| MALFORMED | present but not a usable document: unreadable bytes, not a JSON object, a failed model / shape precondition, or an incomplete two-file unit (see the GLB note below) | 409 | the whole scene is refused |

**The missing-vs-stale contract.** ABSENT is expected and quiet. STALE and
MALFORMED are always loud, on every surface (route, builder POST, async job,
GLB route, scene): a present artifact is either projected as-is or refused
with a code that names it. There is no third outcome — no partial projection,
no fallback to raw, no repair. Repair is always an explicit user write
(regenerate the artifact, `PUT …/design/ramp-source`, regenerate the world),
never a read.

New error codes (all HTTP 409):

| code | detail | raised when |
|---|---|---|
| `ARTIFACT_MALFORMED` | `code`, `message` (names the FILE, never a path) | a present artifact is not a usable document |
| `ARTIFACT_STALE` | `code`, `message` | a provenance check failed and no rule-named stale code exists. Producers: `development_mesh.sources.rampSource` vs the active source, and (AC-01F.2 correction) a mesh pair whose INTERNAL publication sidecar does not name the report and GLB on disk — on `GET …/design/tunnel`, `GET …/design/development-mesh`, both `mesh.glb` routes and in the scene |
| `WORLD_PUBLICATION_STALE` | `code`, `message` | **AC-01F.2 correction (B1).** `arrays.npz` exists, but `derived/world.json` — the world COMMIT RECORD — does not commit THIS `scenario.json` and THIS `arrays.npz`. It is a *_STALE code in the exact sense of `SHAFTS_STALE` / `CAPABILITY_GRAPH_STALE`: a published product whose own recorded inputs no longer match the live ones. Reachable states: a writer died between the document publication and the derived invalidation (a fresh process previously served that as **200** — NEW document beside an OLD world), a generation died after publishing `arrays.npz` and before its record, an input was replaced afterwards (a content-preserving `touch` counts — rule 60 is a stat identity), or a CROSS-PROCESS reader caught a live writer between the two publications. That last case is the reason the message does NOT claim a retry never succeeds; it is deliberately NOT folded into the bounded `READ_SNAPSHOT_CHANGED` retry, which exists for inputs that moved under ONE reader. The remedy named to the client is `POST …/world/generate`. `WORLD_NOT_GENERATED` (no `arrays.npz`) and `WORLD_ARTIFACT_INCOMPATIBLE` (a Phase-17 NPZ) both keep precedence over it |
| `SCENE_ARTIFACT_INVALID` | `code`, `message`, `artifacts: [{artifact, state, code, message}]` | `GET …/scene` found at least one present-but-invalid artifact; EVERY failure of that snapshot is listed, each with its own specific code (`SHAFTS_STALE`, `LAYOUT_V2_CLEARANCE_MISMATCH`, `ARTIFACT_MALFORMED`, …). No filesystem path, traceback or exception repr is exposed |
| `READ_SNAPSHOT_CHANGED` | `code`, `message` | **live from AC-01F commit 3.** It means "a coherent read snapshot could not be acquired because the scenario / artifact set kept changing; retry the read", and it is deliberately distinct from `JOB_INPUTS_CHANGED`, which is a GENERATION whose inputs moved (nothing is built or discarded by a read). Two producers: `WorldService._bound_scenario`, bounded internally at `SNAPSHOT_ATTEMPTS` (3), when `scenario.json` moves on every attempt; and `WorldService.load_bound`, which raises on FIRST detection when EITHER of its two inputs moved across the cold load — `arrays.npz` REPLACED between its stat and its `np.load`, or `scenario.json` replaced between the bound document read and the publish re-check (Stage D B1 made the two halves symmetric: the scenario re-check used to gate the CACHE PUBLISH only, while the `return` was unconditional, so the two world routes still served a body mixing the OLD document's orebody with the NEW world's terrain and fields) — only `GET …/scene` retries that producer (bounded at 3); `GET …/world` and `GET …/world/slice` answer the code on the first mismatch (a DELETED `arrays.npz` is `WORLD_NOT_GENERATED`, not this code). The surfaces this commit adds are **`GET …/scene`** (which additionally retries the whole bound load + lock-held artifact observation and only then answers this code), **`GET …/world`**, **`GET …/world/slice`** and **`POST …/world/generate`**'s pre-read binding — the generation's own post-build re-check stays `JOB_INPUTS_CHANGED`. Every other route that loads the world goes through the same `load_bound` (the eight `DesignService` builders and `POST …/design/layout-v2`'s world guard), so it can answer this code too; all four routers map it identically through the one `guard` table. The remaining `_bound_scenario` branch — `scenario.json` appearing between the stat and the read — is unreachable through the API: only `ScenarioStore.create` writes a fresh id and no client can name one before it exists |

An existing domain-specific code always wins over a generic one: a stale shaft
artifact stays `SHAFTS_STALE`, a stale capability graph
`CAPABILITY_GRAPH_STALE`, a selection bound to another catalogue revision
`LAYOUT_V2_SELECTION_STALE`, and any defect of the selection's persisted
clearance certification `LAYOUT_V2_CLEARANCE_MISMATCH` (rule 172). Async jobs
report the same codes as the synchronous routes: `JobService` transports the
exception's `code` unchanged.

**`sourceRevision` is not a freshness token.** Every derived payload carries
`sourceRevision = sha256(fingerprint.entries)` over the registry's ordered
input list. It is provenance for humans, not an authority: the Effective Ramp
fingerprint group expands to the INACTIVE owner's files, so a
persisted-vs-recomputed mismatch is a normal state of a correct artifact. The
read authority therefore never compares it to a recomputed fingerprint.
Freshness uses only the relations that exist on disk:
`layout_v2_selected.layoutRevision` ↔ `layout_v2.json`,
`shafts.levelsRevision` ↔ `levels.json`,
`capabilityGraph.networkRevision` (plus its recorded `networkSourceRevision`)
↔ `network.json`, the selection ↔ level-access agreement (rule 157),
`development_mesh.sources.rampSource` ↔ the active source, the two-file
GLB content hash, and — added by the AC-01F.2 correction — two INTERNAL
publication records: `derived/world.json` ↔ the live `scenario.json` /
`arrays.npz`, and `derived/<mesh>.commit.json` ↔ the mesh report and GLB
beside it. Both are publication provenance — one publication's OWN recorded
identities, never a recomputed fingerprint — and neither appears in a served
payload. Where persisted evidence cannot prove freshness, the reader
claims nothing; the cascade and the rule-60 writer protocol remain the
guarantee.

**Two-file (GLB) units: what is checked where.** `tunnel_mesh.json` +
`tunnel_mesh.glb` and `development_mesh.json` + `development_mesh.glb` are one
artifact each (rule 67). The report route and `GET …/scene` check the unit's
PRESENCE: a `status: "SUCCESS"` report whose `.glb` is missing is 409
`ARTIFACT_MALFORMED` on both, instead of the old split where the report
answered 200 and its own GLB route answered 409. The GLB BYTES are hashed
against the report's own `artifactRevision` only on the binary routes
(`GET …/design/tunnel/mesh.glb`, `GET …/design/development-mesh/mesh.glb`),
where the bytes are being served anyway and a torn file used to be answered
`200 model/gltf-binary` with `Cache-Control: …immutable`. The scene and the
report GET never read tens of megabytes to answer; the bytes served on the
binary route are the bytes that were hashed (one observation, not two reads).

**`GET …/design/ramp-source`.** Expected absence stays `available: false`, for
BOTH owners:

* `activeSource = LEGACY` with no `decline_smoothed.json` — the normal
  pre-generation state;
* `activeSource = LAYOUT_V2` with no `layout_v2_selected.json` — reachable
  through the normal API, because `ramp_source.json` is in no cascade:
  regenerating the catalogue under an active LAYOUT_V2 deletes the selection
  and the level accesses while `activeSource` stays LAYOUT_V2 until the user
  re-selects and re-activates. `GET …/design/ramp` answers 409
  `LAYOUT_V2_NOT_SELECTED` there, and the scene's `rampSource` slot reports
  exactly what this endpoint reports.

A present-but-INVALID active owner is a different thing and answers its own
typed 409 — this status endpoint must never report `available: true` for a
ramp every builder refuses. Since the C5 pair read, "invalid" includes a
selection whose co-published `level_accesses.json` is missing or unusable:
that is 409 `LAYOUT_V2_SELECTION_STALE` here, not `available: false`. Only the
ABSENT selection above is the expected absence. The pair is classified in both
directions REGARDLESS of the active ramp source (A14: the scene collects every
invalid artifact of its snapshot, and a half-published pair is crash residue
whatever the source): under an active LEGACY source a deleted or unusable
`level_accesses.json` beside a selection flips `GET …/scene` from 200 to 409
`SCENE_ARTIFACT_INVALID` (measured), while `GET …/design/ramp` and the LEGACY
ramp itself are unaffected.

A corrupt `ramp_source.json` is 409
`ARTIFACT_MALFORMED`, never a silent `LEGACY`; `PUT …/design/ramp-source` is
the explicit repair, and it evaluates its guards (world, VALID selection)
BEFORE it writes, so a refused switch leaves the file byte-identical. Since
C5 that VALID-selection guard reads the pair too: `PUT …/design/ramp-source`
`{activeSource: LAYOUT_V2}` over a selection whose `level_accesses.json` is
missing or unusable answers 409 `LAYOUT_V2_SELECTION_STALE` and writes nothing
(before C5 it answered 200 and activated the half pair). A writer
that has already persisted its artifact and meets an unusable
`ramp_source.json` at its cascade deletes the UNION of both sources' closures
— strictly more, never less, and never a guessed source.

**The selection ↔ level-access pair is ONE read unit, in BOTH directions.**
`layout_v2_selected.json` and `level_accesses.json` are co-published under one
capture (rule 157) — `select_layout_candidate` writes the selection first and
the accesses second inside one lock hold, and catalogue regeneration deletes
both — so a missing or disagreeing half is crash residue of that two-write
window and never a legitimate state. EACH half's read spec observes the other
and classifies the pair; the disagreement is typed by DEFECT CLASS:

| what is wrong | code | why |
|---|---|---|
| `candidateId` | `LAYOUT_V2_CLEARANCE_MISMATCH` | a candidate-identity defect — the same class, and the same pinned AC-01D code, that a defective `clearance` block answers (rule 172) |
| the recorded certification: `clearanceBasis` / refinement provenance (together the `provenance_key`), `clearanceErrorBound`, `requiredClearance` | `LAYOUT_V2_CLEARANCE_MISMATCH` | a clearance-RECIPE defect. All FOUR keys `CandidateCertification` parses are compared, in both directions; `requiredClearance` used to be omitted, so a selection whose `requiredClearance` had been moved (measured: 10.590169943749475 → 999.0) was 200 on its own GET, 200 in the scene and 200 on `POST …/network/generate` while `POST …/design/levels` refused it 409 |
| `sourceRevision` or `layoutRevision` | `LAYOUT_V2_SELECTION_STALE` | the two halves belong to different captures: a freshness fact, not a certification defect |
| the OTHER half is absent, unreadable, or not a JSON object | `LAYOUT_V2_SELECTION_STALE` | the pair is incomplete — an orphan, in whichever direction it is read |

**Read-state labels.** A defect of an artifact's OWN certification block is
read state **MALFORMED** (a failed shape precondition of that document). A
disagreement between two parseable halves, or a co-published half that is
missing / not usable / certification-defective, is read state **STALE**. The
wire code is the one in the table either way. An aggregate row never carries
the OTHER artifact's message: the `level_accesses.json` row of a scene refused
because the SELECTION's `clearance` block is null says "its co-published
`layout_v2_selected.json` carries a defective clearance certification", not the
selection's own text.

The earlier C1 asymmetry is **gone**. A selection that is shape-valid and
revision-valid but VALUE-tampered used to answer 200 on its own
`GET …/design/layout-v2/selected` while `GET …/design/level-accesses`, the
scene and every accesses-reading builder answered 409. The selection now
carries the symmetric pair check, so the same tampering answers **409** on its
own GET, on `GET …/design/ramp`, on `GET …/design/ramp-source` under an active
LAYOUT_V2, in the scene and on the builders. Judging a selection's values
against the WORLD (the rebuilt stage-4 policy) is still a search-level check
and still lives in the four policy POSTs; what the pair read adds is the
persisted-evidence half, which needs no world.

Measured before the change, with the selection intact and its co-published
`level_accesses.json` DELETED: `GET …/design/ramp-source` **200
`available:true`**, `GET …/design/ramp` **200**, `GET …/scene` **200** with
`levelAccesses: null` — while `POST …/design/levels` and
`POST …/network/generate` both answered 409 `LEVEL_ACCESSES_NOT_GENERATED`.
That is exactly the state the status endpoint promises never to report.

**Repair is still an explicit user write, and it now writes.**
`POST …/design/layout-v2/select` treats the already-selected candidate at the
same catalogue revision as a no-op only when BOTH halves are VALID; otherwise
it falls through and rewrites both. Measured before the change: with
`level_accesses.json` deleted or replaced by `{`, `select` and `activate` both
answered 200 and restored nothing.

The pair read also moves where four builders get their answer.
`POST …/network/generate`, `POST …/design/timeline`,
`POST …/infrastructure/communication` and `POST …/infrastructure/sensors` read
`level_accesses.json` but restore no clearance policy; their
`LAYOUT_V2_CLEARANCE_MISMATCH` for a value-tampered selection now comes from
the pair read, not from a policy restore. The four builders that DO need the
selected candidate's certification (`POST …/design/levels`,
`…/design/shafts`, `…/design/tunnel`, `…/design/development-mesh`) keep their
own restore unchanged. `POST …/design/stopes` stays **200** on a stale or
tampered selection, and that is not an oversight: the registry declares its
inputs as `scenario + arrays + levels` (rule 79), so it reads no ramp at all —
giving it a ramp dependency would be an engineering change, not a read-trust
change.

**`select` / `activate` answer 404 for an unknown scenario.**
`POST …/design/layout-v2/select` and `…/activate` now call `ScenarioStore.get`
as their FIRST statement, so an unknown scenario id is **404
`SCENARIO_NOT_FOUND`** where commit 3 answered **409
`LAYOUT_V2_NOT_GENERATED`** (base `12d7725` answered the same 409). The reason
is not cosmetic: both routes used to enter `ArtifactReader.snapshot` →
`ScenarioStore.lock` before any existence check, and `ScenarioStore._locks` is
never pruned — measured, 500 distinct unknown ids on `select` left
`len(_locks) == 502` (base `12d7725`: 0). Every other scenario-scoped route
already checked first and grew nothing.

**A MALFORMED catalogue can no longer be selected.**
`POST …/design/layout-v2/select` and `…/activate` require a VALID
`layout_v2.json`. Their precondition used to be a presence probe, and the
deterministic re-run behind it rebuilds the search result from scenario +
world without ever parsing the catalogue — so a corrupt catalogue was never
noticed. Measured at HEAD `12d7725`: with `layout_v2.json` = `{`, `select`
answered **200** and wrote `layout_v2_selected.json` + `level_accesses.json`
carrying the corrupt file's own `layoutRevision`, and `activate` answered
**200** — a fully activated LAYOUT_V2 ramp bound to a document nobody can
parse. Both answer 409 `ARTIFACT_MALFORMED` now, and write nothing.

**`targets.json` has no first-level shape precondition.** No consumer
subscripts it: `_targets_object` requires a VALID document and then rebuilds
the `AccessTargetSet` deterministically. So a valid-JSON document of the wrong
shape is VALID by spec — `GET …/design/targets` answers 200 and
`POST …/design/decline` still answers 200 — while UNPARSEABLE bytes, or a document that is not a JSON object, are 409
`ARTIFACT_MALFORMED` on both. The read authority claims nothing about a shape
no consumer reads; that is the honesty limit, stated rather than papered over.

**One artifact never reports another's defect.** The capability graph records
`networkSourceRevision` and AC-01F cross-checks it against the network
payload's own `sourceRevision`. That cross-check DEFERS when `network.json`
cannot be parsed — the network's own read is the `ARTIFACT_MALFORMED` report.
The deferral is directly OBSERVABLE, and the earlier claim that the
`networkRevision` relation always catches it first is false: `file_revision` is
`sha256(name:size:mtime_ns)`, so a same-size rewrite with `st_mtime_ns`
restored leaves it identical. Measured at commit 3 (`file_revision` unchanged:
True): `GET …/network` 409 `ARTIFACT_MALFORMED`, `GET …/design/capability-graph`
**200** over a `network.json` nobody can parse, `GET …/scene` 409
`SCENE_ARTIFACT_INVALID`. The deferral itself is the contract (A12: one
artifact never reports another's defect, and the scene collects both rows); it
is the PROTECTION that was overstated, not the rule.

The same applies to the OTHER two-artifact deferral — and it does NOT: when
the ACTIVE RAMP SOURCE cannot be resolved at all (`ramp_source.json` present
but unreadable or unparseable), `development_mesh.json` does not defer. Its
provenance check cannot run without an active source, so the read is refused
with 409 `ARTIFACT_MALFORMED` NAMING `ramp_source.json`. Two answers changed
with Stage D S1. The UNREADABLE half (its stat succeeds, its bytes do not)
silently skipped the check, so `GET …/design/development-mesh` and its GLB
route answered **200** for a mesh whose own writer refused the same state with
409. The UNPARSEABLE half was refused, but with the wrong code and the wrong
file: 409 `ARTIFACT_STALE` naming `development_mesh.json`. Both are now 409
`ARTIFACT_MALFORMED` naming `ramp_source.json` — one artifact never reports
another's defect. A `rampSource` MISMATCH, which needs a RESOLVED source to be
a mismatch at all, remains the mesh's OWN `ARTIFACT_STALE`.

**Q-WORLD-GUARD: the world guard is DISK-authoritative on every derived read.**
A derived artifact is never trusted without a world (the snapshot's own
`arrays.npz` stat, not the in-memory world cache and not a per-reader probe).
Two observable consequences:

* with the world cached in memory and `arrays.npz` deleted, `GET …/scene` used
  to answer **200** with a full manifest (Stage A probe 2 §4.9) and now answers
  409 `WORLD_NOT_GENERATED`;
* on a scenario CREATED but not yet world-generated, every derived read route
  answers 409 `WORLD_NOT_GENERATED` instead of its own absence code. Measured
  over the 21 derived read routes (HEAD `12d7725` → AC-01F commit 2): 11
  answers change, of which 4 change STATUS.

| route | HEAD `12d7725` | AC-01F commit 2 |
|---|---|---|
| `GET …/design/targets` | 409 `WORLD_NOT_GENERATED` | unchanged |
| `GET …/design/decline` | 409 `WORLD_NOT_GENERATED` | unchanged |
| `GET …/design/decline/smooth` | 409 `WORLD_NOT_GENERATED` | unchanged |
| `GET …/design/layout-v2` | 409 `WORLD_NOT_GENERATED` | unchanged |
| `GET …/design/ramp` | 409 `WORLD_NOT_GENERATED` | unchanged |
| `GET …/design/tunnel` | 409 `WORLD_NOT_GENERATED` | unchanged |
| `GET …/design/tunnel/mesh.glb` | 409 `WORLD_NOT_GENERATED` | unchanged |
| `GET …/design/development-mesh` | 409 `WORLD_NOT_GENERATED` | unchanged |
| `GET …/design/development-mesh/mesh.glb` | 409 `WORLD_NOT_GENERATED` | unchanged |
| `GET …/scene` | 409 `WORLD_NOT_GENERATED` | unchanged |
| `GET …/design/layout-v2/selected` | 409 `LAYOUT_V2_NOT_SELECTED` | 409 `WORLD_NOT_GENERATED` |
| `GET …/design/level-accesses` | 409 `LEVEL_ACCESSES_NOT_GENERATED` | 409 `WORLD_NOT_GENERATED` |
| `GET …/design/levels` | 409 `LEVELS_NOT_GENERATED` | 409 `WORLD_NOT_GENERATED` |
| `GET …/design/stopes` | 409 `STOPES_NOT_GENERATED` | 409 `WORLD_NOT_GENERATED` |
| `GET …/design/timeline` | 409 `TIMELINE_NOT_GENERATED` | 409 `WORLD_NOT_GENERATED` |
| `GET …/infrastructure/communication` | 409 `COMMUNICATION_NOT_GENERATED` | 409 `WORLD_NOT_GENERATED` |
| `GET …/infrastructure/sensors` | 409 `SENSORS_NOT_GENERATED` | 409 `WORLD_NOT_GENERATED` |
| `GET …/design/ramp-source` | **200** (summary) | **409** `WORLD_NOT_GENERATED` |
| `GET …/design/shafts` | **404** `SHAFTS_NOT_GENERATED` | **409** `WORLD_NOT_GENERATED` |
| `GET …/network` | **404** `NETWORK_NOT_GENERATED` | **409** `WORLD_NOT_GENERATED` |
| `GET …/design/capability-graph` | **404** `CAPABILITY_GRAPH_NOT_GENERATED` | **409** `WORLD_NOT_GENERATED` |

The recorded 404/409 absence drift below is unchanged for a scenario that HAS
a world; these four rows are the no-world state only, where the world guard
answers first. The frontend already generates the world before it reads any
derived route.

**`scene.levelAccesses` is not gated by the active source**: it is the
level-access artifact OF THE SELECTION, rendered as a preview before
activation. It is validated like every other slot.

**Migration-on-read** (`ScenarioStore.get`, Phase 18) stays the ONE documented
exception to "a read must not write": reading a scenario document of an older
schema version migrates it, persists it and clears every derived artifact
(rules 40/46). The read authority adds no migration and no repair of its own.
From AC-01F commit 3 the document read that wraps it is BOUND
(`WorldService._bound_scenario`, C4), so the rewrite is absorbed by a re-read
rather than reported as a race; what the repeated read then finds decides the
answer — where the migration's `clear_derived` removed a world, 409
`WORLD_NOT_GENERATED` (regenerate is the explicit repair); where there was
none to remove, the read simply succeeds.

**`JOB_INPUTS_CHANGED` on the three generation guards.** `StaleInputsError`
now answers its own canonical code — the one the `?sync=true` branches and the
async job path already answered — on `api/design.py`, `api/network.py` and
`api/infrastructure.py`. It replaces three untested literals that reported
`code: "STALE_INPUTS"` with the messages `"inputs changed during generation;
retry"` (design), `"network inputs changed during generation; retry"`
(network) and `"inputs changed while generating; retry"` (infrastructure); the
status (409) is unchanged and the message is now the exception's own.
`POST …/design/targets` gained this path: it is the last derived writer to
adopt the rule-60 capture/re-check protocol.

**`POST …/world/generate` gained the same guard (AC-01F commit 3).** The world
writer binds the scenario document through `WorldService._bound_scenario`,
runs `generate_world` OUTSIDE the store lock, and publishes (`arrays.npz` +
`derived/world.json` + the in-memory cache) under the lock only if the document
has not moved since that binding; otherwise 409 `JOB_INPUTS_CHANGED` and
nothing is written. At HEAD `12d7725` a scenario PUT landing inside
`generate_world` left `arrays.npz` and the cache holding a world built for the
REPLACED document while `GET …/world` answered **200** (Stage A §7.5 case A).

**A world is trusted only while it is a COMMITTED generation (AC-01F.2
correction, B1).** `derived/world.json` — until this commit an unread
statistics snapshot — is the world COMMIT RECORD: `{"publication": {scenarioId,
scenarioRevision, arraysRevision}, "stats": …}`, published LAST by
`WorldService._save`, after `arrays.npz`, so that publication is the COMMIT
POINT of a generation. Both revisions are the existing rule-60 stat identity
(no content hash is introduced) and both are the values the PUBLISHER owns: the
scenario revision `POST …/world/generate` verified under the store lock, and
the arrays revision `publish_npz` installed, taken from its own file descriptor
rather than from a stat of the path afterwards — across processes such a stat
can name a file another generation installed. A world whose record does not
name the two live files is refused with 409 `WORLD_PUBLICATION_STALE` at five
enforcement points that share ONE definition
(`ArtifactReader.require_world`): every direct derived read
(`ArtifactReader._read_bound`), `WorldService.load_bound` (`GET …/world`,
`GET …/world/slice`, `GET …/scene` and every builder that loads the world),
`GET …/design/ramp` + `GET …/design/ramp-source`
(`DesignService._ramp_snapshot`), `PUT …/design/ramp-source` and the
`POST …/design/layout-v2/select` idempotency probe. In `load_bound` the record
is checked AFTER the arrays load, so a Phase-17 NPZ keeps its strictly more
specific `WORLD_ARTIFACT_INCOMPATIBLE`. Consequence for an existing store: a
world generated before this commit has no record and answers the 409 until it
is regenerated once.

**A mesh pair commits itself with an INTERNAL sidecar (AC-01F.2 correction,
B3).** `artifactRevision` is a content hash and can only be checked where the
bytes are in hand — the binary routes. A republication that died between the
GLB and its report (GLB G2 beside report G1) was therefore 200 on
`GET …/design/tunnel`, `GET …/design/development-mesh` and in the scene. Worse,
a mesh rebuild is DETERMINISTIC, so that crash installs IDENTICAL bytes and the
content hash AGREES: it cannot see the mixture on any route at all.

The discriminator is the publication IDENTITY, recorded in
`derived/<mesh>.commit.json` — `{reportRevision, glbRevision}`, the rule-60
identities the publication itself installed — published LAST, so its
publication is the COMMIT POINT of a mesh generation. **The served report and
the scene are unchanged**: their success payload carries no new field, because
publication provenance is internal evidence, not a public projection. The
reader compares the sidecar against the report and GLB stats it already takes
in the same snapshot; nothing is hashed on the report route or in the scene.

A FAILED report has no GLB contract — the binary routes refuse a non-SUCCESS
report outright — so a leftover GLB beside one is ignored, and the FAILED path
publishes its sidecar BEFORE unlinking that GLB (the generation is committed by
the report + sidecar; the unlink is housekeeping no reader depends on). The
sidecar is UNREGISTERED: in no fingerprint and in no cascade, exactly like
`derived/world.json`, so one left beside a cascade-deleted report is inert. A
mesh published before this commit has no sidecar and is refused until
regenerated.

**Every persisted file is published atomically (AC-01F.2).** `scenario.json`,
`arrays.npz` and every file under `derived/` are written to a temp sibling,
fsynced and installed with `os.replace`
(`backend/src/minegen/core/publication.py`), so a torn file can no longer be
produced by this process — a reader, in this process or another, observes the
whole previous file or the whole new one. A torn **`scenario.json` or
`arrays.npz`** left by an EXTERNAL writer is still an unmapped **500**
(`json.JSONDecodeError` / `zipfile.BadZipFile` escapes the read), unchanged; a
torn REGISTERED artifact under `derived/` left by an external writer is the
typed 409 `ARTIFACT_MALFORMED` the read authority already answers (AC-01F). A
PAIR is two atomic publications, not one atomic pair: the write ORDER is fixed
(on SUCCESS the GLB before its report, `level_accesses.json` before
`layout_v2_selected.json`, `arrays.npz` before `derived/world.json`) so a crash
between them leaves the half the read authority classifies most conservatively
— an ABSENT artifact or the typed forward orphan, never a `SUCCESS` report
whose GLB is missing or a selection whose level accesses are gone. The FAILED
mesh path is the deliberate exception: the FAILED report is published FIRST and
the stale GLB unlinked after it, so a failure there leaves the previous SUCCESS
pair whole (200 on the report, the GLB and the scene) instead of a SUCCESS
report with no GLB.

**The document read is itself bound (C4), so the migration is not a race.**
`_bound_scenario` reads `scenario.json` as stat → `ScenarioStore.get` →
re-stat and REPEATS while the revision moves (at most `SNAPSHOT_ATTEMPTS` = 3
attempts; exhaustion is a READ that could not be bound → 409
`READ_SNAPSHOT_CHANGED`, never `JOB_INPUTS_CHANGED`). Capturing only *before*
`ScenarioStore.get` would make the Phase 18 migration-on-read (above — the ONE
documented read that writes) look like a concurrent mutation; capturing only
*after* would leave the read itself outside the guarded window, so a PUT
between `get` and the stat would bind an OLD document to the NEW revision.
Re-reading absorbs the migration: the second attempt parses the already
migrated document and its revision holds. **`POST …/world/generate` on a
schemaVersion-1 document therefore answers 200** and publishes a world bound
to the migrated revision, exactly as at HEAD `12d7725`; an intermediate
commit-3 draft answered 409 `JOB_INPUTS_CHANGED` on that first call, and that
consequence no longer exists. The post-build re-check stays
`StaleInputsError` / `JOB_INPUTS_CHANGED` and is now only ever *true*: a
document that moved after the binding really was replaced by someone else.

**`GET …/world` and `GET …/world/slice` are DISK-authoritative too (AC-01F
commit 3).** The in-memory world cache entry carries the `scenario.json` and
`arrays.npz` revisions the world was built at and is served only while BOTH
still match, so:

* deleting `arrays.npz` with the world warm in memory makes both routes answer
  409 `WORLD_NOT_GENERATED`; at HEAD both answered **200** (probe 2 §4.9) —
  "is the world there?" depended on process state;
* a scenario PUT can no longer be observed half-applied. `PUT /scenarios/{id}`
  is ONE locked section (document write + derived invalidation + cache drop);
  an in-flight `GET …/scene` either completes as a consistent OLD snapshot or
  sees the post-PUT state. At HEAD an in-flight scene answered **200**
  describing a world the PUT had already deleted (R3b), and a PUT plus a world
  regeneration produced ONE response whose `world.depth` /
  `referenceElevation` / `bottomElevation` came from the OLD document and
  whose `terrain.zMax` came from the NEW world (R3d);
* the cold-load window — `arrays.npz` stat → lock (cache probe) → `np.load` —
  has two TYPED outcomes instead of an exception escaping the service. The
  file **deleted** in that window (a scenario PUT, a world regeneration in
  flight) → 409 `WORLD_NOT_GENERATED`; **replaced** in it → 409
  `READ_SNAPSHOT_CHANGED`, because the world in hand cannot be attested to the
  revision the read captured. `GET …/scene` repeats the whole bound load in
  the replaced case and normally answers a consistent 200. Measured on the
  intermediate commit-3 draft with the load paused: the deleted case answered
  **500 Internal Server Error**, the replaced case answered **200** for a
  world loaded from a file the reader had never stat'ed;
* the SCENARIO half of that window has the SAME outcome (Stage D B1). A
  `PUT /scenarios/{id}` **plus** a world regeneration landing between the
  bound document read and the publish re-check moves `scenario.json` too, and
  `load_bound` refuses the triple instead of returning it: 409
  `READ_SNAPSHOT_CHANGED` on `GET …/world` and `GET …/world/slice`, a retry on
  `GET …/scene`. Commit 3 re-stat'ed the document but let the result through
  and gated only the cache entry, so the R3d body it claims to have made
  impossible was still served on those two routes — measured with the read
  paused inside `load_bound`: ONE **200** carrying `orebody.center
  [40.0, 20.0, -50.0]` from the OLD document beside `terrain.zMax
  116.367159085105` and `rockQuality.mean 64.97196970309594` from the NEW
  world, a body equal to neither the before nor the after state.

No wire shape changes: `PUT /scenarios/{id}` keeps its request and response
exactly as before.

**`WORLD_ARTIFACT_INCOMPATIBLE` is now uniform across the four routers
(intended unification).** `WorldArtifactIncompatibleError` is a subclass of
`WorldNotGeneratedError`, and at HEAD `12d7725` each router's own ladder gave
it a different answer: design 409 `WORLD_ARTIFACT_INCOMPATIBLE`
(`api/design.py:88-94`), world 409 `WORLD_ARTIFACT_INCOMPATIBLE`
(`api/world.py:38-44`), network 409 `WORLD_NOT_GENERATED` (no specific row —
the base-class row at `api/network.py:44-49` won) and infrastructure 500
`INTERNAL_ERROR` (no row at all — the `api/infrastructure.py:74` catch-all).
The single `api/errors.guard` table answers 409 `WORLD_ARTIFACT_INCOMPATIBLE`
on all four. The two changed rows need a Phase-17 `arrays.npz` beside a
current document (upgrade / crash residue), no route on those two routers is
exercised with it today and no test pinned either answer; the new answer is
strictly more specific than both, and a 500 for a recognisable, recoverable
state was the defect AC-01F set out to remove. The four HEAD rows are frozen
in `backend/tests/test_api_errors.py::HEAD_WORLD_ARTIFACT_INCOMPATIBLE` with
their `file:line` provenance.

That record and this paragraph BACK-FILL a **commit-2** behaviour change: the
unified `guard` table shipped in commit 2, so the two changed answers
(network 409 `WORLD_NOT_GENERATED` → 409 `WORLD_ARTIFACT_INCOMPATIBLE`,
infrastructure 500 `INTERNAL_ERROR` → 409 `WORLD_ARTIFACT_INCOMPATIBLE`) have
been live since that commit and were simply not written down until commit 3.
Nothing about them changes in commit 3.

**Recorded 404/409 drift (AC-01I owns it).** Absence answers 409 for fourteen
routes and 404 for three: `GET …/design/shafts` (`SHAFTS_NOT_GENERATED`),
`GET …/design/capability-graph` (`CAPABILITY_GRAPH_NOT_GENERATED`) and
`GET …/network` (`NETWORK_NOT_GENERATED` — the same exception answers 409 from
the design and infrastructure routers). AC-01F preserves this drift
deliberately; normalizing it is AC-01I's, together with the frontend.

## Planned
    GET  /api/v1/scenarios/{id}/design                  Phase 04+

## Conventions

- Request/response field names are camelCase on the wire; Pydantic models use
  `alias_generator=to_camel` with `populate_by_name=True`.
- Errors: `{"detail": {"code": "...", "message": "...", ...}}`.
  Schema violations return HTTP 422 with `code = "VALIDATION_ERROR"` and an
  `errors[]` list (`loc`, `msg`, `type`). The offending input is not echoed.
- All floats must be finite. `NaN`, `Infinity`, `-Infinity` are rejected with
  422 at the boundary (rule 34).
  Infeasible engineering results (e.g. no feasible decline) are structured
  failures with HTTP 422, never silently relaxed constraints.
- Long-running operations return `{"jobId": "..."}` and stream progress over
  WebSocket.
