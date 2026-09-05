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
                                                     arrays.npz and derived/* (rule 40)
    POST /api/v1/scenarios/{id}/world/generate       generate terrain / orebody / spatial fields
                                                     (rock quality, grade, fault measurements);
                                                     persists arrays.npz (field_artifact_version);
                                                     returns neutral field stats
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
                                                     cache-busted meshUrl (?v=<sha16>)
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
                                                     kind, `ranges` extras → development ids);
                                                     deleted with levels.json / the ramp chain
    POST …/design/layout-v2                          Phase 20A parametric family search
                                                     (kind LAYOUT_V2) → 202 {jobId, …}; ?sync=true
                                                     runs inline. Every orebody type (EXACT or
                                                     COARSE/REFINED_CONSERVATIVE clearance). Persists
                                                     derived/layout_v2.json; deletes a stale
                                                     selection and, if LAYOUT_V2 is active, the
                                                     ramp-derived chain (rule 151)
    GET  …/design/layout-v2                          catalogue · 409 LAYOUT_V2_NOT_GENERATED
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
                                                     the summary carries the preferred length, its
                                                     source (DEFAULT_6X_TUNNEL_WIDTH | EXPLICIT) and
                                                     the mean / max |ΔP| (rule 163). Phase 20B.1 O
                                                     separation observability per access:
                                                     junctionToEntryPlanSep, junctionToEntryDist3d,
                                                     rampCenterlineDistance, excavationSeparation
                                                     (envelope-to-envelope rock pillar; branch
                                                     samples within the taper exclusion arc of the
                                                     junction excluded) and turnoutHeadingChangeDeg
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
                                                     without a selection); a change deletes every
                                                     ramp-derived artifact, never geology
    GET  …/design/ramp                               the ACTIVE Effective Ramp (rule 149):
                                                     sourceKind LEGACY_SMOOTHED |
                                                     LEGACY_RAW_FALLBACK | PARAMETRIC_V2,
                                                     owningArtifact, sourceRevision, segments[]
                                                     409 SMOOTHED_NOT_GENERATED (LEGACY) /
                                                     LAYOUT_V2_NOT_SELECTED (LAYOUT_V2)
    (tunnel, levels, network, timeline, communication and sensors all consume
     the ACTIVE Effective Ramp; the scene's smoothedDecline is that ramp and
     legacySmoothedDecline / rampSource / layoutV2 / layoutV2Selected are added)
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
