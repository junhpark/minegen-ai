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
    POST /api/v1/scenarios/{id}/design/decline       chained Hybrid-A* decline (raw centerline);
                                                     ?maxLevels=n; persists derived/decline.json;
                                                     synchronous (≈ 30 s default scenario)
    GET  /api/v1/scenarios/{id}/design/decline       409 DECLINE_NOT_GENERATED if missing
    GET  …/scene                                     includes "accessTargets" and "decline" (or null)

## Planned
    GET  /api/v1/scenarios/{id}/design                  Phase 04+
    GET  /api/v1/scenarios/{id}/network                 Phase 07
    POST /api/v1/scenarios/{id}/sequence/generate       Phase 10
    GET  /api/v1/scenarios/{id}/timeline                Phase 10
    POST /api/v1/scenarios/{id}/infrastructure/optimize Phase 11
    WS   /ws/jobs/{jobId}                               Phase 04+ (async jobs)

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
