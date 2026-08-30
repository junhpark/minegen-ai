# MineGen-AI v0.1

MineGen-AI is a research prototype for **generative underground mine
design**: from a synthetic geology it deterministically derives access
targets, a constrained decline, tunnel geometry, level development, stopes,
a 4D mining sequence and infrastructure placement baselines — all viewable
in a browser-based 3D client.

    Synthetic geology / orebody
             ↓
    Access targets
             ↓
    Hybrid-A* decline
             ↓
    Smoothing + tunnel
             ↓
    Levels + crosscuts
             ↓
    MineNetwork
             ↓
    Stopes
             ↓
       ┌─────┼───────────────┐
       │     │               │
   Timeline Communication   Sensors
       │     │               │
       └─────┴───────────────┘
             ↓
      Web 3D / future
      Unity / Unreal clients

Unity/Unreal are **future integration targets**, not implemented features —
see `docs/engine-integration.md`.

## Status

| Phase | Scope | State |
| --- | --- | --- |
| 01 | scaffold / coordinate contracts | done |
| 01.1 | hygiene / finite values / schema corrections | done |
| 02 | synthetic geology/world | done |
| 02.1 | world semantics / invalidation corrections | done |
| 03 | access target generation | done |
| 04 | chained Hybrid-A* decline | done |
| 04.5 | async jobs + CI | done |
| 05 | smoothing + revalidation | done |
| 06 | tunnel mesh | done |
| 07 | MineNetwork | done |
| 08 | level development | done |
| 09 | stopes / mining method | done |
| 10 | 4D MineTimeline | done |
| 11 | Communication OSP | done |
| 12 | Generic Sensor OSP | current |
| 13 | First-person walkthrough | planned |
| 14 | Interaction | planned |
| 15 | 4D walkthrough | planned |
| 16 | Integrated demonstration | planned |

## Core principles

- **Research prototype / proof of concept** — no claim of replacing
  commercial mine-planning software, RF surveys or certified designs.
- **Backend engineering authority**: all geometry, graph, time and
  placement calculations live in the Python backend; the frontend performs
  visualization assembly only.
- **Deterministic generation** wherever the phase contract specifies it —
  same inputs, byte-identical derived artifacts (modulo `sourceRevision`).
- **Canonical coordinates**: ENU Z-up metres in every persisted artifact.
- **Stable derived-artifact dependency model**: regenerating upstream data
  deletes dependent artifacts (see `docs/architecture.md`).
- **Explicit planning proxies**: communication and sensor coverage use
  network-geodesic distance thresholds — deliberately not calibrated RF
  prediction, gas dispersion or detection modelling.

## Current features

**Mine generation** — synthetic terrain/geology/orebody, access-target
generation, constrained chained Hybrid-A* decline, smoothing/revalidation,
excavated tunnel geometry, levels/crosscuts, planned longhole stopes.

**Mine intelligence** — typed MineNetwork, deterministic 4D mining
sequence (`timeline.json`), connected communication placement baseline
(`communication.json`), sensor monitoring placement baseline
(`sensors.json`).

**Visualization** — browser-based Three.js / React Three Fiber viewer with
DESIGN, INFRASTRUCTURE and 4D modes; walkthrough integration is future
work.

**Interoperability** — typed JSON semantic artifacts, GLB mesh where
applicable, engine-neutral contracts for future Unity/Unreal adapters.

## Architecture

    ┌────────────────────────────────────────┐
    │        Python / FastAPI Backend        │
    │ geometry · graph · time · OSP          │
    └───────────────────┬────────────────────┘
                        │
             typed JSON │ GLB
                        │
    ┌───────────────────▼────────────────────┐
    │      React / Three.js Web Client       │
    └────────────────────────────────────────┘
                        │
                  future adapters
                 ┌──────┴───────┐
               Unity          Unreal

## Artifact pipeline

Major persisted derived artifacts per scenario:

    scenario.json          configuration (geology, design, schedule, infrastructure)
    decline.json           raw Hybrid-A* decline
    decline_smoothed.json  smoothed centerline (owns RAMP geometry)
    tunnel mesh (GLB)      excavated tube geometry
    levels.json            level/crosscut development (owns DRIFT/CROSSCUT geometry)
    network.json           typed MineNetwork graph
    stopes.json            planned longhole stopes
    timeline.json          deterministic 4D mining sequence
    communication.json     connected MESH_ROUTER placement baseline
    sensors.json           GAS_SENSOR monitoring placement baseline

Regenerating any upstream artifact invalidates its dependents (timeline,
communication and sensors are siblings below the network). The full
dependency specification lives in `docs/architecture.md`.

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

## Quick verification

Full quality gates (identical to CI):

    cd backend  && pytest && ruff check . && ruff format --check . && mypy src
    cd frontend && npm run typecheck && npm run lint && npm test && npm run build

Historical per-phase manual smoke walkthroughs were moved to
`docs/smoke-tests.md`.

## Continuous integration

`.github/workflows/ci.yml` runs the full backend gate (ruff check, ruff
format --check, mypy strict, pytest) and frontend gate (typecheck, eslint,
prettier --check, vitest, build) on every push to `main` and every pull
request.

## API

API families (authoritative endpoint reference: `docs/api.md`):

    /api/v1/health
    /api/v1/scenarios
    /api/v1/scenarios/{id}/world
    /api/v1/scenarios/{id}/design/...
    /api/v1/scenarios/{id}/network...
    /api/v1/scenarios/{id}/infrastructure/communication
    /api/v1/scenarios/{id}/infrastructure/sensors
    /api/v1/jobs

## Documentation map

    CLAUDE.md                    binding implementation rules
    docs/architecture.md         system architecture / phase dependency
    docs/coordinate-system.md    coordinate conventions
    docs/algorithms.md           numerical methods
    docs/api.md                  REST contracts
    docs/engine-integration.md   future Unity / Unreal interoperability
    docs/smoke-tests.md          historical phase smoke walkthroughs

## Documentation policy

Whenever a phase changes project status, a major user-visible capability,
a top-level artifact, a public API family, a supported visualization mode
or an interoperability target, README.md must be reviewed and updated in
the same PR. "No README change required" is acceptable only if explicitly
stated in the phase completion report with a reason.
