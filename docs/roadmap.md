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
| 20B.3 | Viewer cleanup + robustness + golden policy | material-level brightness (single shared material path, walkthrough rebalanced), independent 4D ramp / development mesh toggles, fail-closed reveal metadata (centerline fallback never disappears), golden retention policy (latest full JSON only; legacy 22-case lock never deleted) — done |
| 20C.1 | Switchback hairpin station + shortlist yield + WARPED diagnosis | hairpin arc–straight–arc level station as a declared finite grid axis (`switchback_station_length_m ∈ {0, 2 × minimum_turnout_straight_buffer}`) competing on score, no threshold change — GEOMETRY-STRESS must recover or its remaining constraint be proven; shortlist yield audit (family-internal cheap rank vs detailed pass) before any reservation change; WARPED multi-seed feasibility diagnosis (≥ 30 seeds, diagnostic only); runtime report ≤ 20 s on TABULAR-REFERENCE |
| 20C.2 | WARPED level development (section(z)) + shaft / capability graph | implicit-orebody horizontal section contract (z-slice polylines → local tangent / normal / footwall side / span / ore contact) so level drifts follow the local trace; shaft + capability graph (who may use which edge) ahead of 20D compliance |
| 20C.3 | Bounded local repair + FIGURE_EIGHT / HYBRID | bounded local A* / repair inside the family corridor (no real failure case yet — deferred until one exists), FIGURE_EIGHT / HYBRID families; horizontal surface entries (adit) |
| 20D | Rulebook compliance + unified development mesh + branch walkthrough | explicit rulebook compliance reporting ("two independent escape routes" once the capability graph defines shared edges), multi-candidate comparison; typed-junction minimum union (not a general Boolean engine), branch walkthrough; legacy A* kept as baseline |
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
| D0 | Hugging Face public demo | single Docker Space, session isolation, TTL, prebuilt demo scenario; demo mode (viewer-only: OrbitControls autoRotate roundview paused on input, 20× looping 4D playback reusing the timeline clock, one "Demo" HUD toggle, disabled in walkthrough) |

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
