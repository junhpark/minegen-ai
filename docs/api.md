# API (v0.1)

Base path: `/api/v1`. All payloads are JSON, all coordinates are ENU Z-up
meters (`docs/coordinate-system.md`). Schemas live in
`backend/src/minegen/core/models.py` and are mirrored in
`frontend/src/types/`.

## Implemented

    GET  /api/v1/health                              liveness + version + coordinate system
    POST /api/v1/scenarios                           create scenario from ScenarioCreate
    GET  /api/v1/scenarios                           list scenario summaries
    GET  /api/v1/scenarios/{id}                      fetch scenario document
    PUT  /api/v1/scenarios/{id}                      replace scenario document; deletes
                                                     arrays.npz and derived/* (rule 40)
    POST /api/v1/scenarios/{id}/world/generate       generate terrain / orebody / block model /
                                                     geology; persists arrays.npz; returns stats
    GET  /api/v1/scenarios/{id}/world                stats (409 WORLD_NOT_GENERATED if missing)
    GET  /api/v1/scenarios/{id}/world/slice          ?field=rockQuality|grade|faultInfluence|
                                                     faultZone|oreFraction&axis=x|y|z&index=n
    GET  /api/v1/scenarios/{id}/scene                web scene manifest (terrain heightmap,
                                                     orebody mesh, fault polygons, ore blocks,
                                                     default rock-quality slice, stats)

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
    GET  …/scene                                     includes "accessTargets", "decline" and
                                                     "smoothedDecline" (or null)
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
