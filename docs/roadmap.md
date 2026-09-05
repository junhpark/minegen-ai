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

Active core sequence (Park, Phase 18 directive): the Hugging Face public
demo (D0) is **deferred** and is no longer the next phase.

| Phase | Purpose | Key change |
| --- | --- | --- |
| 17.1 | Scenario / viewer stabilisation | scenario isolation, 4D raw-path suppression, Field Slice toggle, Parameters UI — done |
| 18 | Spatial Field Core | remove BlockModel/SMU semantics, batch field API, replace longhole grade proxy, golden-scenario harness — done |
| 19 | Implicit Geological Orebody | WARPED_VEIN: authoritative implicit solid (φ), variable thickness, pinch & swell, warped mid-surface, asymmetric outline → derived approximate clearance → derived marching-cubes mesh; legacy layout stays TABULAR-only — done |
| 20A | Parametric Layout Family Search — families & Effective Ramp | SPIRAL / LONGITUDINAL / SWITCHBACK finite grids, numerical level service, delivered-centerline validation, EXACT / CONSERVATIVE clearance, hierarchical search + 3-group ranking, source-neutral Effective Ramp (LEGACY \| LAYOUT_V2) driving tunnel → levels → network → timeline → walkthrough for TABULAR; WARPED_VEIN candidates / ranking / rendering — done (Phase 20 NOT complete) |
| 20B | Ramp junctions, level access drives, method-aware level development | RAMP_JUNCTION → LEVEL_ACCESS → LEVEL_ENTRY topology, level-development anchors, finite deterministic access planning with hard validation, access length in ranking, `level_accesses.json`, method split (LONGHOLE lattice vs generic backbone; CUT_AND_FILL typed boundary), network / timeline / infrastructure connectivity, Phase 20A circumradius closeout — done. Closeout v3: preferred access length (6 × tunnel width planning default), stage-2 reach screen demoted to a heuristic (NO_RL_CROSSING stays hard), shortlist-starvation audit, LEVEL_ACCESS / DRIFT / CROSSCUT excavation meshes with CAP / OPEN endpoint QA, Layout v2 as the primary UX with the legacy decline chain as an Advanced section — done. Drifts / crosscuts for implicit bodies and the WARPED_VEIN walkthrough stay deferred |
| 20C | Local bounded refinement | bounded local A* / repair inside the family corridor, FIGURE_EIGHT / HYBRID families; switchback hairpin-station / straight-insert level turnouts (Phase 20B.2-A: a k1 switchback whose alternating levels were reachable only through CSC loops is NO_FEASIBLE_CANDIDATE under the one-turn CS access — GEOMETRY-STRESS golden); horizontal surface entries (adit) as a portal type distinct from the PORTAL + decline structure |
| 20D | Rulebook constraints, layout comparison & unified development mesh | explicit rulebook compliance reporting, multi-candidate comparison; boolean wall openings / exact junction CSG / all-development watertight union ("Unified Development Mesh"); legacy A* kept as baseline |
| 21A | Longhole migration | prove the new MiningMethodPlan abstraction with already-validated geometry |
| 21B | Cut & Fill | lift / cut / backfill 4D mining method |
| 21C | Room & Pillar | limestone; pillar, room, bench, double bench |
| 22 | Analysis / Economics / Compliance | production, development, cost, revenue, cashflow + rule compliance + layout comparison |
| 23 | External Simulation Bridge | Ventsim, AnyLogic, blast, support, Unreal adapters |

Follow-up S1 (Ramp / Footwall / Access Standoff Semantics Rationalization)
was executed by Phase 20B.1 commit C: the audit table lives in
`docs/algorithms.md` ("Phase 20B.1 — stand-off / clearance semantics
audit"); `RampConstraints.clearance` is documented UNWIRED/RESERVED, the
main-ramp corridor stand-off gained its own audited default
(`footwall_access_offset + 6 × tunnel_width`), the WARPED conservative
bound is narrowed only by the stage-4 local lattice refinement, and
per-method stand-off needs remain with the Phase 21 mining-method work.

Deferred deployment item (not scheduled):

| Item | Purpose | Key change |
| --- | --- | --- |
| D0 | Hugging Face public demo | single Docker Space, session isolation, TTL, prebuilt demo scenario |

Phases 01–20B are described in `docs/architecture.md`; the invariants they
established are `CLAUDE.md` rules 1–169.

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
