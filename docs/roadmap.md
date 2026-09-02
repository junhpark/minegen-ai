# MineGen-AI roadmap

## Product name and direction

**Synthetic Mine Design & Simulation Sandbox.**

MineGen-AI generates *synthetic* underground mines: a seeded geological
world, an engineering-constrained decline, level development, stopes, a
scheduling baseline and infrastructure planning, all reproducible from a
persisted scenario document.

**"Digital Twin" is reserved** for a separate future track: measured mines
captured by LiDAR / 3DGS survey of real workings. The two threads must never
share the term. A synthetic sandbox mine is not a twin of anything, and a
measured twin is not generated. Keeping the vocabulary disjoint keeps the
claims honest — nothing in this repository is calibrated against a real
mine.

## Phase order

| Phase | Purpose | Key change |
| --- | --- | --- |
| 17.1 | Scenario / viewer stabilisation | scenario isolation, 4D raw-path suppression, Field Slice toggle, Parameters UI |
| D0 | Hugging Face public demo | single Docker Space, session isolation, TTL, prebuilt demo scenario |
| 18 | Spatial Field Core | remove BlockModel/SMU semantics, batch field API, replace longhole grade proxy, golden-scenario harness |
| 19 | Implicit Geological Orebody | warped vein, variable thickness, pinch & swell; authoritative implicit solid → derived clearance field → derived mesh |
| 20 | Parametric Layout Generator v2 | deterministic layout families, bounded local A*, rulebook constraints, legacy A* kept as baseline |
| 21A | Longhole migration | prove the new MiningMethodPlan abstraction with already-validated geometry |
| 21B | Cut & Fill | lift / cut / backfill 4D mining method |
| 21C | Room & Pillar | limestone; pillar, room, bench, double bench |
| 22 | Analysis / Economics / Compliance | production, development, cost, revenue, cashflow + rule compliance + layout comparison |
| 23 | External Simulation Bridge | Ventsim, AnyLogic, blast, support, Unreal adapters |

Phases 01–17 are described in `docs/architecture.md`; the invariants they
established are `CLAUDE.md` rules 1–125.

## How this list is used

- A phase is implemented only when it is the requested phase. Nothing in
  this table authorises starting the work early.
- Phase-specific invariants land in `CLAUDE.md` **with the phase that
  implements them**, never in advance of the code they constrain.
- The order is a plan, not a contract: a phase may be re-scoped or split
  before it starts, but it is never skipped silently.

## Git workflow

Bundle delivery is retired. Local commits may be created once a scoped
implementation and all required quality gates pass; every remote write —
push, force-push, merge, PR create/update — needs a new explicit approval
for that specific action. See `CLAUDE.md` rule 126.
