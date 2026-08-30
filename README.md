# MineGen-AI v0.1

Web-based AI generative underground mine design and virtual mine research
platform. Research prototype / proof of concept.

> Read `CLAUDE.md` (binding development rules) and `docs/architecture.md`
> before contributing. The canonical coordinate system is **X East, Y North,
> Z Up, meters**; see `docs/coordinate-system.md`.

## Status

| Phase | Scope                                                        | State |
| ----- | ------------------------------------------------------------ | ----- |
| 01    | Repository scaffold, health API, schemas, coordinate utils   | done  |
| 01.1  | Hygiene: finite floats, depth semantics, geology schema, fault half-widths | done  |
| 02.1  | Derived-state invalidation, in-situ ore semantics, rock-only stats, grade continuity | done  |
| 02    | Synthetic world: terrain, orebody, block model, rock quality, faults | done  |
| 03    | Design cost evaluator & level-aware footwall access targets  | done  |
| 04    | Chained Hybrid-A* decline generator (raw centerline)         | done  |
| 04.5  | Async job infrastructure, WebSocket progress, GitHub CI      | done  |
| 05    | Ramp smoothing + revalidation                                | done  |
| 06    | Tunnel mesh                                                  | done  |
| 07    | MineNetwork                                                  | done  |
| 08    | Level development                                            | done  |
| 09    | Stopes / mining method                                       | done  |
| 10    | 4D MineTimeline                                              | done  |
| 11    | Communication OSP                                            | done  |
| 12    | Generic Sensor OSP                                           | done  |
| 13    | First-person walkthrough                                     | current |
| 14–16 | See `docs/architecture.md`                                   | planned |

## Layout

    backend/    Python 3.12 · FastAPI · Pydantic · NumPy        (src/minegen)
    frontend/   React 19 · TypeScript (strict) · Vite · R3F · Zustand · Tailwind
    docs/       architecture, coordinate system, API, algorithms
    data/       on-disk scenario storage (git-ignored)

## Run locally

Backend (http://localhost:8000, OpenAPI at `/docs`):

    cd backend
    python -m venv .venv && source .venv/bin/activate
    pip install -e ".[dev]"
    uvicorn minegen.main:app --reload --app-dir src

Frontend (http://localhost:5173):

    cd frontend
    npm install
    npm run dev

Set `VITE_API_BASE_URL` if the backend is not on `localhost:8000`.

Or both with Docker: `docker compose up`.

## Continuous integration

`.github/workflows/ci.yml` runs the full backend gate (ruff check, ruff
format --check, mypy strict, pytest) and frontend gate (typecheck, eslint,
prettier --check, vitest, build) on every push to `main` and every pull
request.

## Quality gates

Every phase must pass all of these before it is considered complete:

    cd backend  && pytest && ruff check . && ruff format --check . && mypy src
    cd frontend && npm run typecheck && npm run lint && npm test && npm run build

## Phase 06 smoke test

1. With a smoothed decline persisted, click **Generate tunnel mesh
   (Phase 06)**. A MESH job runs the gravity-aligned sweep of the effective
   centerline (rules 65–67).
2. The **Tunnel mesh** layer shows the excavated tube (arched horseshoe
   profile, plumb walls, welded segment junctions, removable portal/terminal
   caps).
3. The design panel reports nominal excavation volume, mesh/nominal volume
   difference (QA gate ≤ 1 %), wall surface area, ring/triangle counts and
   the watertight/manifold/closed verdicts — all backend-computed.
4. Regenerating the smoothed decline (or anything upstream) deletes
   `tunnel_mesh.json`/`tunnel_mesh.glb`; the mesh URL is revision-busted with
   `?v=<sha16>` of the GLB SHA-256.
5. The full 13-level DEFAULT scenario meshes end-to-end: the former
   L11–L12 orebody-buffer conflict was resolved upstream by the
   direction-aware Phase 04 envelope feasibility contract with
   launchability and bounded chain backtracking (see docs/algorithms.md,
   Phase 04/06). Expect `chainBacktracks: 3` in the decline payload and
   0 envelope violations in the tunnel report.

## Phase 05 smoke test

1. With a decline generated, click **Smooth decline (Phase 05)**. A SMOOTH
   job runs (progress per segment); on success the mint **Smoothed /
   effective decline** layer appears: one solid centerline per segment
   (red + label = RAW_FALLBACK, never hidden).
2. The Design panel shows `N segments · N smoothed · 0 fallback`, the
   effective length, total field-cost delta and minimum plan radius, plus a
   per-segment list (repairs, Δcost %, min R).
3. The raw search path stays available as its own layer for comparison.
4. Regenerating the decline, targets or world deletes the smoothed artifact
   (rule 64); the panel and layer clear accordingly.

## Phase 04 smoke test

1. With access targets generated, click **Generate decline (Hybrid-A*)**.
   A job is submitted; the panel shows a progress bar with level / candidate
   counters and expanded states (polled every 0.5 s from `GET /jobs/{id}`;
   `/ws/jobs/{id}` streams the same records). Clicking again while it runs is
   refused with `JOB_ALREADY_RUNNING`.
2. An amber/chalk polyline (alternating per level) runs from the portal cone
   through every level's selected candidate; faint red lines are the other
   successful candidates. Labels show `Lnn Cxx <length> m`.
3. The Design panel lists per level the selected candidate and a ●/○/×
   summary (selected / other success / failed) plus totals.
4. Regenerating access targets or the world discards the decline.

## Phase 03 smoke test

1. With a generated world, click **Generate access targets** (Design panel).
2. Amber spheres (valid) / smaller red spheres (rejected) appear on the
   footwall side, one row per level joined by a line and labelled
   `Lnn  <elevation> m`; a chalk cone marks the portal.
3. Click a sphere: the Inspector shows its level, along-strike coordinate,
   footwall offset, rock quality, fault penalty, cost/m and next-level
   heuristic, plus rejection reasons if any.
4. Regenerate the world: targets disappear (derived state invalidated).

## Phase 02 smoke test

1. Start backend and frontend, click **New synthetic mine** (leave "one fault" on).
2. Click **Generate world** (≈ 0.5 s). Terrain, the teal orebody slab, amber
   grade blocks, a red fault polygon and a horizontal rock-quality slice
   through the orebody center appear; the orbit target jumps to the orebody.
3. In **Field slice** switch field (rock quality / grade / fault influence /
   fault zone / ore fraction), axis and index. The legend shows the slice range.
4. Create a second scenario with seed 43 and generate: terrain and the
   rock-quality pattern change, the orebody and fault do not.
5. Inspector → World shows block counts, sampled tonnes vs analytic orebody
   tonnes, rock-quality mean, fault core/damage block counts and memory.

## Phase 01 smoke test

1. Start backend and frontend.
2. The top bar shows `backend 0.1.0 · ENU_Z_UP` with an amber dot.
3. Click **New synthetic mine**. A scenario is written to
   `data/scenarios/<id>/scenario.json` and its parameters appear in the left
   panel and the inspector.
4. Orbit the viewer: the E / N / UP triad at the world corner and the
   readout at the bottom-right show mine coordinates (Z up), not Three.js
   coordinates.

## API

See `docs/api.md` for the authoritative endpoint reference. Phase 12 adds
the sensor placement baseline alongside Phase 11 communication:

    POST/GET /api/v1/scenarios/{id}/infrastructure/communication
    POST/GET /api/v1/scenarios/{id}/infrastructure/sensors

Phase 01 exposes:

    GET  /api/v1/health
    POST /api/v1/scenarios
    GET  /api/v1/scenarios
    GET  /api/v1/scenarios/{id}
    PUT  /api/v1/scenarios/{id}
