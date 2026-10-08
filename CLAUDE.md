# MineGen-AI Development Rules

MineGen-AI is a browser-based research platform for generative underground
mine design. Read `docs/architecture.md` and `docs/coordinate-system.md`
before touching any module.

Before coding any requested phase:

1. inspect existing repository files
2. respect current architecture
3. identify affected modules
4. implement only the requested phase
5. write tests
6. run tests
7. run lint/type checks
8. summarize changed files
9. identify remaining technical debt

Never rewrite unrelated working modules. When implementing numerical methods,
favor correctness, determinism, testability and engineering transparency over
cleverness.

## Core rules

1. Never implement the whole platform in one step.

2. Build one vertical slice at a time, in the order given in
   `docs/architecture.md` (Phase 01 … Phase 16). Do not skip phases.

3. Backend canonical coordinate system:
   X East, Y North, Z Up, meters.

4. Never introduce Three.js coordinate conventions into backend code.

5. Separate:
   domain model,
   numerical algorithm,
   API,
   rendering.

6. Large numerical arrays must use NumPy.
   Do not create millions of Python/Pydantic block objects.

7. Every random generator must accept a deterministic seed.

8. Every core algorithm requires tests before integration.

9. Do not silently relax engineering constraints.

10. If no feasible ramp exists, return a structured failure.

11. Raw A* paths must never be rendered as final engineering designs.

12. Every smoothed path must be revalidated.

13. Mine geometry and MineNetwork must remain synchronized.
    Both are derived from the same centerline; neither is derived from the other.

14. Do not use deep learning in v0.1.

15. Do not add external dependencies without explaining why.
    Add a dependency in the phase that first needs it, not before.

16. Prefer simple, transparent algorithms first.

17. Frontend rendering must not contain engineering calculations.

18. API schemas must be typed.

19. TypeScript strict mode must remain enabled.

20. Do not replace working architecture simply to reduce code length.

## Additional architecture invariants

21. A mine decline is not designed as one Portal-to-Orebody path.

    The decline is a chained sequence of engineering access targets:

        Portal
        → Level 1 access
        → Level 2 access
        → Level 3 access
        → ...

    Each level may contain multiple candidate access targets
    (`LevelAccessTargets { level_id, elevation, candidates[] }`).
    v0.1 evaluates K = 3–5 candidates per level using segment cost plus a
    next-level accessibility heuristic. Beam search / dynamic programming
    over the candidate lattice is a later refinement, not a rewrite.

22. Every ramp segment must pass its terminal continuous position and heading
    to the next segment as the start position and initial heading.

23. Hybrid A* states remain continuous:

    x, y, z and heading are floating-point engineering states.

    Discretization is used only for closed/open-set indexing
    (`closed_key = (ix, iy, iz, ih)`).

    Never snap the physical ramp trajectory to the search grid.
    The "5 m XY / 1 m Z" figures are closed-set discretization resolutions,
    not state snapping resolutions.

24. Heading discretization and turning motion primitives must be
    geometrically consistent.

    For heading-bin angle Δθ and turn radius R:

        arc_length = R × Δθ

    Vertical displacement is `dz = gradient × horizontal_arc_length`,
    accumulated as a float. It must not be rounded at each search step.

25. The ramp heuristic must include the lower bound imposed by the maximum
    gradient (gradient = vertical / horizontal):

        horizontal_min        = abs(dz) / max_gradient
        grade_limited_length  = sqrt(horizontal_min^2 + dz^2)
        h_distance            = max(euclidean_distance, grade_limited_length)

    If the search objective is monetary or weighted cost, multiply
    `h_distance` by the minimum feasible cost per meter. Non-negative
    additive penalties (fault, rock quality, sterilization) are never
    included in the heuristic.

26. Ordinary ramp, drift and crosscut tunnel profiles must use a
    gravity-aligned sweep frame, never a parallel-transport frame.

    Backend global up is `Z = (0, 0, 1)`. For centerline tangent `t`:

        forward = normalize(t)
        up      = normalize(Z − dot(Z, forward) × forward)
        right   = normalize(cross(forward, up))      # driver's right

    `(right, forward, up)` is a right-handed basis (`right × forward = up`).
    This keeps tunnel floors gravity-aligned so they do not bank along spiral
    declines. See `docs/coordinate-system.md` for the full definition.

    Parallel-transport frames are reserved for future near-vertical
    raise/shaft geometries where `|dot(t, Z)| → 1`.

27. Synthetic geology must exist before route optimization.

    Phase 02 must provide:

    - a deterministic (seeded) spatially-correlated rock-quality field
    - support for scenario-defined synthetic fault planes
      (origin, strike, dip, core_half_width, influence_half_width,
       core_penalty, damage_zone_penalty). Faults are geometric entities
      declared in the scenario document; they are NOT generated from the
      seed. Seed-driven procedural fields are terrain, rock quality and
      grade only.
    - fault signed-distance / zone / influence measurements per block
      (visualization and diagnostics)

    Phase 02 acceptance scenarios shall include at least one fault.
    Phase 03 cost evaluation must never be based only on constant
    excavation cost, and must use the analytic FaultPlane objects as the
    source of truth (per-fault penalties), not the block-model fault arrays.

28. Strike and dip convention is fixed:

    - strike is clockwise azimuth from +Y (North)
    - dip direction = strike + 90 degrees (right-hand rule)
    - orebody `height` means down-dip length, not vertical extent

29. Default footwall access offset is approximately 20 m and must remain
    configurable. Architecture must permit depth-dependent offset rules later.

30. Level drift gradient is configurable. v0.1 may default to zero for
    geometric simplicity; the schema must permit small drainage gradients.

31. The mine development timeline must support continuous chainage progress
    from 0.0 to 1.0. A DEVELOPING tunnel is not simply fully visible.

32. Frontend `TunnelMeshFactory` performs visualization assembly only.
    It may convert backend positions/normals/indices into Three.js
    `BufferGeometry` but must never perform mine-engineering geometry
    calculations.

33. Walkthrough collision geometry must be designed so individual excavation
    colliders can be enabled/disabled according to timeline state without
    rebuilding the complete physics world.

34. API and domain floats are finite. Every `ApiModel` uses
    `allow_inf_nan=False`; NaN / ±inf requests are rejected with 422.
    `+inf` is permitted only inside numerical cost fields (NumPy arrays in
    Phase 03+), never in a schema, a JSON payload or a persisted document.

35. `WorldConfig.depth` is the model depth measured **below**
    `TerrainConfig.base_elevation`. The model bottom is
    `base_elevation − depth`. It is not an absolute bottom elevation.
    Terrain relief may raise the bounding-box top above the reference.

36. Fault zone widths are perpendicular **half-widths** measured from the
    fault plane (`core_half_width`, `influence_half_width`). Classification
    uses `|signed_distance|`. Total disturbed thickness is twice the half-width.

37. Synthetic geology parameters live under `scenario.geology`
    (`rock_quality`, `faults`, and future members). Do not add geological
    fields at the scenario root.

38. Completion reports must quote the exact commands and paths that were
    executed. Do not abbreviate endpoint paths or summarize a command that
    was not run.

39. Block-model ore semantics: the analytic `Orebody` is the geometric
    source of truth and may outcrop. Persisted `ore_fraction` is the fraction
    of each block that is inside the analytic orebody AND below the terrain
    surface, from one shared sub-sample pattern; AIR/ROCK classification uses
    the same sub-samples (`solid_fraction < 0.5 → AIR`). Hence
    `orebody.volume()` is the mineralized-body volume and
    `block_model.ore_volume()` is the in-situ (below-ground) ore volume.
    Mine statistics (`faultCoreBlocks`, `rockQualityMean`, …) count rock
    blocks only; the fields themselves remain defined everywhere.

40. Replacing a scenario document invalidates ALL derived state: the
    in-memory cache, `arrays.npz` and every file under `derived/`. Until
    regeneration, world/scene/slice endpoints answer 409 WORLD_NOT_GENERATED.
    Each later phase stores its derived products under `derived/` so this
    single invalidation stays the choke point. Routers obtain services via
    FastAPI dependencies, never by calling `get_*_service()` directly.

41. Phase 03 design cost is a continuous query service
    (`DesignCostEvaluator.evaluate_points(N×3)`), not a dense search-grid
    volume. Hybrid-A* owns search discretization in Phase 04.

42. Geological measurement and engineering cost interpretation remain
    separate. Rock-quality fields are interpolated from the block model;
    fault penalties are evaluated from analytic `FaultPlane` geometry and
    per-fault parameters; orebody exclusion uses the analytic signed
    distance. Overlapping fault penalties are summed (v0.1).

43. Decline access targets are level-aware footwall targets. For each
    level, candidates share the level elevation and the perpendicular
    footwall offset `q = thickness/2 + footwall_access_offset`; only their
    along-strike coordinate varies:

        P = C + u_coord·u + v_coord·v + q·w,   v_coord = (z_level − C.z − q·w.z) / v.z

44. Invalid access candidates are retained with explicit rejection
    reasons. They are not silently deleted.

45. Phase 03 must not implement Hybrid-A* or any path search.
    `next_level_accessibility` is the admissible heuristic distance only.

46. Regenerating the world clears `derived/` first; every later derived
    product (targets, decline, network, …) is invalid once its inputs change.

47. Phase 04 Hybrid-A* physical states remain continuous.
    Closed-set discretization is 5 m XY, 1 m Z and 16 heading bins
    by default. Discretization never snaps geometry. The
    cover-established (rule 52) and profile-burial-established
    (rule 66) flags carried by the search are history-dependent
    boolean STATE LABELS on nodes and closed keys — they distinguish
    otherwise-identical poses reached with different transition
    history; they are not geometric discretization dimensions and
    have no resolution.

48. Turning primitives change heading by exactly one heading bin.
    With minimum radius R and heading-bin angle Δθ, the primitive
    horizontal arc length is R·Δθ. Straight primitives use the same
    horizontal length.

49. v0.1 decline search is monotonic downward by default.
    Grade primitives are {0, −0.5·gmax, −gmax}. Upward grades are
    reserved for a future optional mode.

50. Primitive feasibility and cost are evaluated along the complete
    primitive, not only at its endpoint. Sampling spacing must be no
    greater than min(2 m, smallest fault core half-width).

51. Phase 04 must terminate a successful segment at the exact access
    target. A geometrically valid, fully sampled goal-shot connector
    may be used; distance tolerance alone is not an acceptable final
    endpoint.

52. The portal transition is the only exception to minimum-cover
    enforcement. Before minimum cover is first achieved, shallow
    underground samples may be accepted; after it is achieved, the
    path may never violate minimum cover again.

53. Candidate chaining in v0.1 is deterministic per level with
    bounded backtracking. Every valid candidate up to K=5 is
    searched; candidates are ordered by actual segment cost plus the
    next-level admissible lower bound (ties by candidate index). The
    next segment inherits the terminal continuous position and
    heading and the cover-established and profile-burial-established
    state. Every successful NON-FINAL arrival must additionally be
    launchable: at least one legal forward/downward successor
    primitive must exist under the same envelope-aware feasibility
    contract, otherwise the candidate is demoted to INFEASIBLE
    (NEXT_LAUNCH_INFEASIBLE). When a level has no feasible candidate,
    the NEAREST ancestor level with an untried candidate advances to
    its next deterministic pick and the chain below it is
    re-searched. Each accepted backtrack consumes one unit of
    max_chain_backtracks (default 24); exhausting the budget — or
    exhausting the root level — fails the frontier level with an
    explicit INFEASIBLE result. Backtracking never relaxes any
    engineering constraint (rule 54) and never alters the per-level
    search itself.

54. Search failure never relaxes engineering constraints. Exhaustion
    returns a structured SEGMENT_INFEASIBLE result with per-candidate
    diagnostics.

55. ε-weighted Hybrid-A* search. The heuristic stays admissible:
    `h = sqrt(max(L_dubinsCS, Δz/g_max)² + Δz²) × minimum cost/m`, where
    `L_dubinsCS` is the exact turn-then-straight horizontal length with free
    final heading (plain distance when the target is inside a turning
    circle). Ordering is `(⌊(g + ε·h)/bucket⌋, docking tie-break, g + ε·h)`
    with ε = 2 and `cone` tie-break by default (standoff ring while
    descending, approach cone `|L_dock − Δz/g|` once the vertical budget is
    comparable to the distance).

    The v0.1 implementation does NOT claim a formal ε-suboptimality bound,
    because in addition to heuristic inflation it uses (1) quantized-f,
    focal-style ordering, (2) aggregation of continuous states into
    discretized closed keys, and (3) f-based cell dominance (rule 56). ε is
    a search-aggressiveness (heuristic-inflation) parameter, not a
    guarantee. Measured: ε = 1 and 1.5 exhaust 20k expansions on the small
    scenario; ε = 2 solves it in 3,152. ε, bucket, tie-break mode and the
    admissible bound `h(start)` are recorded in every search's diagnostics;
    ε = 1 and bucket = 0 restore plain (still cell-aggregated) A* ordering.
    A formal bounded-suboptimal variant (A*ε / focal search over
    `f ≤ ε·f_min`) is a future research option, not a v0.1 requirement.

56. Heuristic cell dominance: closed-set dominance is decided on
    `f = g + ε·h`, never on `g` alone. With a 1 m z bin and 0.85 m max-grade
    steps, a flat child and a descending child of one parent alias to the
    same cell; their `g` differs by < 1 % while their `h` differs by
    ≈ Δz/g_max — comparing `g` silently dropped every descent. Re-opening a
    cell with a strictly better `f` is allowed. This is an engineering
    resolution of key aliasing, not an optimality-preserving pruning rule
    (two poses sharing a key are different physical states); Pareto labels
    `(g, h)` per cell are a research-version option.

60. Long-running design operations run as asynchronous jobs. Algorithms
    emit progress through a plain callback (`ProgressCallback`) and know
    nothing about jobs, threads or WebSockets; the job service consumes the
    callback and exposes state over `GET /jobs/{id}` and `/ws/jobs/{id}`.
    The v0.1 registry is in-memory (state is lost on restart), one job per
    scenario at a time (`409 JOB_ALREADY_RUNNING`). Progress reporting must
    never change a search result.

    Stale-input protection: a design job captures an input-revision
    fingerprint (exists/size/mtime_ns of scenario.json, arrays.npz and
    targets.json) before loading its inputs, and re-verifies it under the
    per-scenario store lock immediately before persisting. Any invalidating
    mutation (scenario PUT, world regeneration, target regeneration,
    deletion) changes the fingerprint — regeneration counts as a new
    revision even when the content is byte-identical. On mismatch the job
    persists nothing and terminates FAILED with the structured error code
    `JOB_INPUTS_CHANGED`; it never reruns automatically. The same lock
    guards derived-state deletion in `WorldService.invalidate`, so a
    finishing stale job cannot write after a mutation cleared `derived/`
    (rules 40/46).

57. Turning primitives carry a curvature penalty
    (`turn_penalty_factor × L_h × min cost`, default 0.5) so declines do not
    zig-zag between equal-cost L/R/S children. The penalty is additive and
    non-negative; `h` ignores it.

58. The default portal is chosen for burial: among footwall-side surface
    candidates, maximize the minimum (terrain − max-grade entry line)
    clearance from 20 m to 120 m along the heading toward the orebody.
    A portal facing a slope that falls away faster than g_max cannot start
    a decline, whatever the search does.

59. The goal-shot window is `goal_shot_radius_primitives × L_h` (default
    5 → ≈ 35 m ≈ 2·R_min) and the connector is single-arc first, then
    arc-then-straight (minimum-radius turn until facing the target, then
    straight). Within 3·L_h a single arc with R ≥ R_min exists for < 40 % of
    poses even when aligned within 45°; the wider window with the two-piece
    connector is what makes exact docking reliable.

61. Pose-preserving smoothing. Phase 05 smooths each selected Phase 04
    decline segment while preserving every level-access position exactly and
    the prescribed boundary tangent: horizontal direction = the Phase 04
    inherited heading; boundary grade = the mean of the incoming/outgoing
    raw local grades clamped to [−g_max, 0]; adjacent segments share the
    resulting 3D tangent. Endpoint headings are enforced as explicit tangent
    boundary conditions of the spline (clamped cubic Hermite in XY), never
    by freezing the first/last two control points. z is piecewise-linear
    between smoothed control points with isotonic clamping and boundary-
    grade end intervals, so monotonic descent and |grade| ≤ g_max hold by
    construction (cubic z interpolation overshoots at grade breaks). The
    final curve stays inside the configured deviation corridor, measured as
    the minimum distance from every final sample to the raw polyline. No
    endpoint or access target may move during smoothing.

62. Full geometric and design revalidation. Every candidate smoothed curve
    is fully revalidated: design exclusions through the same
    ``DesignCostEvaluator`` sample validator Phase 04 uses (the first portal
    segment retains rule 52 cover-transition semantics via the shared
    helper), gradient = vertical/horizontal from the curve derivative,
    minimum turning radius evaluated in XY plan view (never 3D
    circumradius) with numerical tolerance R_xy ≥ R_min − 0.05 m.
    Validation sampling is no coarser than min(1 m, smallest fault core
    half-width). An invalid sample is never silently accepted.

63. Cost preservation and explicit repair/fallback. Smoothing must not undo
    Phase 04 cost-aware routing: raw and smoothed field cost
    (∫ cost/m ds, turn penalties excluded) are recomputed with the same
    evaluator; default maximum increase +5 %. Violations trigger
    deterministic local repair (blend the affected control window toward
    raw by the repair factor, then revalidate the whole segment), at most
    ``max_repairs`` times. Afterwards the segment explicitly falls back to
    its revalidated raw centerline: ``smoothed = null``,
    ``effectiveSource = RAW_FALLBACK``, reason persisted. Invalid geometry
    is never returned silently; if the raw input itself fails revalidation
    the phase result is FAILED, not a fallback.

64. The Phase 05 artifact is the Phase 06 input. Tunnel sweep may consume
    only the validated effective centerline produced by Phase 05
    (``effectiveSource = SMOOTHED | RAW_FALLBACK`` per segment), never the
    Phase 04 raw artifact directly. Dependency chain: regenerating the
    world clears derived/; regenerating targets deletes decline.json AND
    decline_smoothed.json; persisting a new decline deletes the old
    decline_smoothed.json.

65. Gravity-aligned floor-centerline sweep (Phase 06). Phase 06 consumes only
    the Phase 05 validated effective centerline. The centerline represents
    the tunnel floor centerline. Tunnel width and height come exclusively
    from ``RampConstraints``. Every ring uses the existing
    ``gravity_aligned_frame``: ``forward = normalize(t)``,
    ``up = normalize(Z − dot(Z, forward)·forward)``,
    ``right = cross(forward, up)``. The profile plane is perpendicular to
    the 3D tangent; no Frenet or parallel-transport roll is used for
    ordinary ramps. Phase 06 may linearly subdivide the validated polyline
    but may not smooth, spline-fit, move, or redesign it.

66. Excavation mesh validity (Phase 06). The logical tunnel mesh is a
    continuous closed tube with one shared ring at every Phase 05 segment
    boundary and separate removable portal/terminal cap primitives. Before
    render-vertex splitting, the logical mesh must be manifold, watertight,
    non-degenerate, consistently outward-oriented, and have zero junction
    gaps. The full excavation envelope is checked against hard spatial
    exclusions; portal terrain intersection is permitted only until the
    complete profile first becomes buried, after which terrain breakthrough
    is invalid. Mesh failure is explicit; invalid geometry is never
    persisted silently.

67. Engineering quantities and artifact contract (Phase 06). Tunnel
    dimensions and engineering quantities are computed in the backend.
    Because each gravity-aligned profile is perpendicular to the 3D
    centerline tangent, nominal excavation volume is
    ``profileArea × 3D centerline length``; no grade cosine correction is
    applied. A closed-mesh signed volume is independently calculated for
    QA. Phase 06 persists ``tunnel_mesh.glb`` plus a typed report
    containing geometry, topology, volume, surface-area and
    artifact-revision metadata. A new Phase 05 artifact invalidates both
    Phase 06 files.

68. Centerline–network synchronization. Every physical MineNetwork edge
    is derived from the validated centerline artifact that owns that
    development and stores only a geometry reference plus scalar
    attributes; it never owns or duplicates the polyline. In Phase 07,
    all RAMP edges reference Phase 05 ``effectiveCenterline`` segments.
    Tunnel mesh and MineNetwork are sibling derivations of the same
    centerline. Future DRIFT/CROSSCUT/RAISE/SHAFT edges follow the same
    contract using their own validated centerline artifacts.

69. MineNetwork edge direction and topology. MineNetwork is a
    ``networkx.MultiDiGraph``. A physical development edge has one
    canonical direction following its centerline orientation; this
    direction does not imply one-way physical travel. Physical
    connectivity, redundancy, and surface-egress topology are evaluated
    on the undirected projection unless a later simulation explicitly
    defines directional traversal. Node and edge IDs, ordering, geometry
    references, and persisted payloads are deterministic.

70. Surface-path redundancy advisory. Phase 07 reports the number of
    edge-disjoint physical paths from every underground access node to
    any PORTAL-type surface node. The v0.1 single-decline topology is
    expected to provide one such path. A two-path criterion may be
    reported as a design advisory, but Phase 07 does not claim statutory
    or regulatory compliance and the advisory does not invalidate an
    otherwise valid network.

71. Phase 08 level-development geometry. ``levels.json`` is the
    validated centerline artifact that owns Phase 08 DRIFT and CROSSCUT
    geometry. A level drift is anchored exactly at its Phase 05
    LEVEL_ENTRY, follows the orebody strike in plan, and applies
    ``level_drift_gradient`` using the deterministic canonical +u
    direction; the access endpoint is never moved. The Phase 03
    candidate lattice does not define drift extent.

72. Crosscut layout and validation. Planned crosscut stations are
    derived from the analytic orebody strike extent, not the
    access-candidate span. v0.1 station pitch is
    ``stope_length + minimum_pillar``; this is an access-layout proxy,
    not a final stope design. Crosscuts run horizontally from the
    footwall drift toward the first orebody contact. Their design
    context permits the orebody contact/envelope while retaining world,
    terrain and restricted-zone hard constraints. Invalid required
    development fails explicitly and is never silently omitted.

73. Phase 08 MineNetwork topology. MineNetwork is rebuilt
    deterministically from the Phase 05 RAMP centerlines plus Phase 08
    level-development centerlines. DRIFT edges are split at every graph
    node. CROSSCUT starts are JUNCTION nodes unless coincident with an
    existing LEVEL_ENTRY, in which case that node is reused; CROSSCUT
    terminals are STOPE_ACCESS anchors for Phase 09 and do not imply
    that a stope already exists. Surface-path redundancy is recomputed
    for every underground physical node.

74. Phase 08 dependency contract. ``levels.json`` is downstream of the
    Phase 05 effective centerline and upstream of MineNetwork.
    Regenerating levels invalidates MineNetwork but never the Phase 06
    tunnel mesh; regenerating the Phase 05 artifact invalidates tunnel
    mesh, levels and MineNetwork. MineNetwork is always rebuilt from its
    owning centerline artifacts and is never incrementally patched from
    a stale network artifact.

75. Phase 09 stope geometry ownership. ``stopes.json`` is the validated
    geometry artifact that owns planned stope geometry. Stopes are
    orebody-aligned rectangular prisms defined in the analytic
    ``TabularOrebody`` local frame (u = strike, v = down-dip,
    w = thickness normal); the analytic orebody — never voxels — is the
    geometric source of truth, and the backend emits world-space prism
    meshes. A stope is a production volume, not a development: it is
    never a MineNetwork edge and Phase 09 never alters MineNetwork
    topology.

76. Phase 08 access-pair anchoring. Stopes are generated ONLY from the
    validated Phase 08 ``levels.json`` artifact: the station lattice is
    never recomputed from the scenario. Each stope spans an adjacent
    completed level pair at one station index, anchored by the paired
    CROSSCUT terminal points (both on the footwall face and station
    plane within 1e-6 m) and referencing its two deterministic
    STOPE_ACCESS anchor node ids. Missing, duplicated, mismatched or
    geometrically inconsistent station pairs FAIL the artifact
    explicitly; a required stope is never silently skipped.

77. Stope pillar, validity and metric contract. Every stope must have
    positive dimensions, local bounds inside the analytic orebody
    extent, hard world/terrain/minimum-cover/restricted-zone validation
    over a deterministic prism sample, and finite metrics. Neighbouring
    strike stopes must keep a clear gap of at least ``minimum_pillar``
    and the Phase 08 end-pillar contract; vertically adjacent stopes may
    share their boundary face. Volume, tonnes and ``meanGradeProxy`` are
    deterministic planning quantities and are never presented as
    reserves or resources; the grade proxy is never a hard feasibility
    criterion.

78. Explicit mining-method strategy. Stope generation goes through the
    MiningMethodStrategy factory. v0.1 implements
    LONGHOLE_OPEN_STOPING only; every other reserved method returns a
    typed explicit UNSUPPORTED_METHOD failure. Silent fallback to
    another method is forbidden, and no automatic method-selection rule
    exists until its engineering criteria are explicitly sourced.

79. Phase 09 dependency contract. ``levels.json`` is upstream of BOTH
    MineNetwork and stopes: regenerating levels deletes network and
    stopes; regenerating the Phase 05 artifact (or further upstream)
    deletes tunnel mesh, levels, network and stopes; generating stopes
    leaves tunnel and network untouched, and generating the network
    leaves stopes untouched. The stope fingerprint is
    scenario + arrays + levels.

80. Backend-only stope engineering; Phase 10 owns time. The frontend
    assembles backend world-space stope vertices only and performs no
    stope engineering calculations. Phase 09 stopes carry
    ``plannedState = PLANNED``; temporal state transitions
    (PLANNED → … → BACKFILLED), scheduling and production sequencing
    belong to Phase 10.


## Persistence (v0.1)

No database. Scenarios are stored on disk:

    data/scenarios/{scenario_id}/
        scenario.json      # Pydantic scenario document
        arrays.npz         # NumPy fields (block model, …) — deleted on PUT
        derived/           # generated design artefacts — emptied on PUT

## Naming

The core design algorithm is the **Chained Hybrid-A\* Decline Generator**
("level-aware chained Hybrid-A* for engineering-constrained underground
decline generation"). Use this name in code, docs and API descriptions
instead of "constrained A* ramp generator".

## Tooling

Backend: `cd backend && pytest && ruff check . && ruff format --check . && mypy src`
Frontend: `cd frontend && npm run typecheck && npm run lint && npm test && npm run build`

All four backend commands and all four frontend commands must pass before a
phase is considered complete.

Verification tiers (VA-01, `scripts/verify.py`): `fast` is the inner loop
(static checks + unmarked tests + cached canaries), `feature` adds the clean
canaries, `full` is the authoritative closeout (every gate above, pytest
UNFILTERED, plus the mechanical coverage proof) and `benchmark` is runtime
observation only. Raw logs and `verification-summary.json` live under
`backend/.verification/` (git-ignored). Read the summary, not the log.

81. **MineTimeline temporal ownership**: `derived/timeline.json` owns time,
    tasks and state ONLY — never geometry. Geometry remains owned by
    `decline_smoothed.json` (RAMP), `levels.json` (DRIFT/CROSSCUT) and
    `stopes.json` (stope prisms); the timeline references them by stable
    IDs/geometryRef and overlays temporal state on the immutable Phase 09
    geometry.

82. **Deterministic precedence-only task DAG**: the schedule is an
    earliest-start baseline (`startDay = max(dependency endDay)`,
    `endDay = startDay + durationDays`) over a validated DAG with stable
    task-ID tie-breaking — no hidden resource constraints, no optimization,
    no hidden rate constants (all rates come from typed
    `scenario.schedule`). Cycles fail explicitly. The result is a synthetic
    planning baseline, never a production forecast.

83. **Continuous development chainage**: the backend resolves every
    development's geometryRef against its OWNING centerline and persists
    normalized cumulative chainage fractions (first 0, last 1, monotonic,
    total length matching `edge.length3d` within 1e-6 m). A DEVELOPING
    excavation is only ever rendered partially (rule 31); the timeline
    never copies geometry coordinates.

84. **Stope state-machine contract**:
    PLANNED → DEVELOPING → ACTIVE → MINED → VOID → BACKFILLED → CLOSED with
    binding exact-boundary semantics — `state(day)` is the latest
    transition whose `transition.day <= day`. State changes visualization
    only; geometry never changes between states in Phase 10.

85. **Physical-access precedence**: RAMP tasks follow the topology-validated
    portal→deeper decline chain; each level's development is rooted at its
    LEVEL_ENTRY via deterministic duration-weighted Dijkstra on the
    undirected physical subgraph (one accessible endpoint suffices;
    canonical edge direction is geometry, not operational one-way travel);
    stope preparation requires BOTH Phase 09 STOPE_ACCESS crosscuts.
    Unreachable required development fails explicitly.

86. **Timeline dependency and frontend responsibility**:
    network + stopes + owning centerline artifacts → timeline; regenerating
    network or stopes deletes the timeline, upstream regeneration cascades
    through it, and timeline regeneration touches NOTHING upstream. The
    frontend evaluates backend-generated temporal contracts (state lookup,
    progress windows, chainage clipping between existing vertices) and
    performs visualization assembly only.

87. **Communication artifact ownership**:
    communication.json owns placement/coverage planning state only; mine
    geometry and topology remain owned by centerline artifacts and
    MineNetwork.

88. **Network-geodesic communication contract**:
    Phase 11 coverage and backhaul use physical shortest path through
    MineNetwork, never Euclidean through-rock distance; the v0.1 model is
    an explicit planning proxy, not calibrated RF prediction.

89. **Deterministic infrastructure sampling**:
    communication candidate and demand locations are generated from backend
    owning centerlines using stable node/edge-chainage references; frontend
    never creates placement candidates.

90. **Connected placement contract**:
    every selected MESH_ROUTER is connected through the selected backhaul
    graph to the unique PORTAL root. Phase 11 uses a deterministic
    connected-greedy baseline and makes no global-optimality claim.

91. **Static infrastructure scope**:
    Phase 11 represents final-layout communication planning only. Router
    installation timing and 4D activation are not modeled.

92. **Communication dependency/frontend responsibility**:
    scenario + network + owning centerlines → communication;
    network/upstream regeneration invalidates communication, while
    stopes/timeline do not. Frontend only assembles backend placement and
    coverage results and performs no communication engineering.
93. **Shared infrastructure network domain**:
    MineNetwork integrity, owning-centerline resolution, backend
    NetworkLocation sampling, and physical network-geodesic distance are
    shared infrastructure-domain responsibilities. Communication and sensor
    builders must not independently reimplement these engineering
    calculations.

94. **Sensor artifact ownership**:
    sensors.json owns sensor-placement planning state only: candidates,
    monitoring demands, selected sensors, assignments and metrics. It never
    owns or mutates mine geometry, MineNetwork, communication or time.

95. **Sensor monitoring proxy**:
    Phase 12 sensor coverage is a network-geodesic monitoring-layout proxy.
    It is never Euclidean through rock and does not represent gas
    transport, sensor response, detection probability or calibrated
    sensing range.

96. **Deterministic sensor placement**:
    Phase 12 uses deterministic GREEDY_SET_COVER_V0_1 with stable ID
    tie-breaking and makes no global-optimality claim. Uniform demand and
    unit sensor cost are explicit v0.1 assumptions.

97. **Independent static sensor scope**:
    Phase 12 sensors are static final-layout monitoring placements.
    Communication feasibility, power feasibility and installation timing
    are not modeled. communication.json, timeline.json and sensors.json
    remain independent sibling derived artifacts unless a later phase
    explicitly defines a coupling model.

98. **Sensor dependency/frontend responsibility**:
    scenario + network + owning centerlines → sensors. Network/upstream
    regeneration invalidates sensors; stopes, timeline and communication
    regeneration do not. Frontend only assembles backend sensor
    placement/coverage results and performs no sensor engineering.

99. **Walkthrough runtime boundary**:
    Phase 13 walkthrough is ephemeral frontend runtime state over existing
    backend-authored mine geometry. Camera/player/physics state is never an
    engineering source of truth and is never persisted.

100. **Walkthrough collision ownership**:
    Collision geometry is derived only from the validated Phase 06
    tunnel_mesh.glb triangles with the canonical mineToThree transform.
    Frontend must never reconstruct tunnel engineering geometry for
    collision.

101. **Walkthrough player contract**:
    First-person locomotion uses an upright collision-constrained Rapier
    capsule under gravity. No fly, noclip, normal-movement teleport or
    jump. Mouse pitch affects view only; walking remains
    gravity-horizontal.

102. **Walkthrough spawn contract**:
    Initial player pose is deterministically derived from the
    authoritative effective decline at the portal end, slightly inside the
    tunnel and above its floor. Arbitrary world-origin fallback is
    forbidden.

103. **Static walkthrough scope**:
    Phase 13 traverses the static final-layout Phase 06 decline only. It
    does not infer volumetric DRIFT/CROSSCUT geometry and does not apply
    MineTimeline state, infrastructure installation time or 4D excavation
    visibility. Those are later-phase responsibilities.

104. **Temporal collider readiness**:
    Physical tunnel colliders are represented as stable independently
    addressable excavation-segment units so a future Phase 15 can activate
    or deactivate individual colliders without rebuilding the complete
    physics world. Phase 13 keeps all supported decline segments active.

105. **Walkthrough interaction boundary**:
    Walkthrough interaction is ephemeral frontend inspection state over
    backend-authored objects. It never changes engineering artifacts,
    scenario data or device state.

106. **Authoritative interactable assets**:
    Phase 14 interactables are only backend-authored MESH_ROUTER and
    GAS_SENSOR selected assets resolved through their authoritative
    candidate/network references. Frontend may not invent devices or
    placements.

107. **Center-ray line-of-sight**:
    Interaction uses the first-person camera center ray, bounded runtime
    interaction distance and authoritative tunnel occlusion. Through-rock
    or distance-only interaction is forbidden.

108. **Static planned-asset semantics**:
    Phase 14 infrastructure shown in walkthrough is a static planned
    layout. Installation timing, power, telemetry, operational state and
    physical sensing/RF performance are not modeled.

109. **Selection identity**:
    selectedObjectId remains the canonical global object selection
    identity. Focus is transient. Instance indices are render
    implementation details and must never become persisted object
    identity.

110. **Phase 14 / Phase 15 separation**:
    Phase 14 interaction is time-independent. MineTimeline/currentDay must
    not control walkthrough asset visibility or interaction until
    Phase 15.

111. **Walkthrough temporal context**:
    Walkthrough has explicit STATIC_FINAL and TIMELINE_SNAPSHOT runtime
    contexts. Entering Walk from 4D captures a MineTimeline day; other
    entry paths preserve static final-layout walkthrough semantics.

112. **Snapshot immutability**:
    A temporal walkthrough captures currentDay at entry. The snapshot day,
    segment collider set and temporal physical topology remain immutable
    for the lifetime of that walkthrough session. Time is changed only by
    returning to 4D and re-entering.

113. **Timeline-authoritative RAMP mapping**:
    Temporal decline availability is resolved only through each RAMP
    DevelopmentTimeline.geometryRef to decline_smoothed.json segmentIndex,
    with exact runtime segment identity validation. Positional or lexical
    inference is forbidden.

114. **Conservative volumetric walkability**:
    Normal 4D visualization may show continuous DEVELOPING centerline
    progress, but first-person volumetric traversal exposes only ACTIVE,
    fully completed Phase 05/06 decline segments. Frontend must not invent
    partially excavated tunnel volume.

115. **Temporal frontier boundary**:
    A partial ACTIVE decline prefix is closed by one ephemeral runtime
    traversal barrier at the exact authoritative active-segment endpoint.
    This barrier is access-control geometry, not engineering excavation
    geometry, and is never persisted or exported.

116. **Temporal infrastructure non-inference**:
    Communication and sensor installation timing is not modeled; therefore
    planned MESH_ROUTER/GAS_SENSOR assets are suppressed in
    TIMELINE_SNAPSHOT walkthrough. Excavation completion must never be
    used to infer installation, power or operational state.

117. **Fail-closed temporal walkthrough**:
    Missing, malformed, incomplete or identity-inconsistent timeline-to-
    decline mappings make temporal walkthrough unavailable. The frontend
    never guesses a temporal segment association.

118. **Static walkthrough regression**:
    Phase 15 temporal integration must not change Phase 13/14 STATIC_FINAL
    collision, spawn, pointer-lock, locomotion or planned-asset inspection
    semantics.
119. Scenario realization vs world generation (Phase 17): every stochastic
     PARAMETER draw happens in the explicit, non-persistent realization
     step (`POST /scenarios/realize`, `services/scenario_realizer.py`);
     the persisted ScenarioCreate is fully resolved and `generate_world`
     stays a pure function of it with zero hidden randomness. A persisted
     scenario alone must reproduce its world forever.
120. Orebody implementations are ONE solid: `contains`, `signed_distance`
     (exact Euclidean), `volume`, `bounding_box` and `mesh` must describe
     the same geometry (mesh vertices exactly on the analytic surface,
     mesh bounds inside the analytic AABB, sdf/contains sign agreement).
     A shape that cannot satisfy this (e.g. free-form noise solids without
     a metric SDF) is deferred, never approximated silently — engineering
     buffers consume the SDF.
121. Randomization RNG domains are independent named sub-streams of the
     scenario seed (orebody 0x0B0D17, faults 0xFA0117, alongside the
     existing terrain 0x7E44A1, rock 0x20C4, grade 0x6A4D): changing one
     domain's draw count must never shift another domain's draws. New
     domains get NEW keys; existing keys are frozen.
122. Realized faults must actually cut the model volume (FaultPlane
     clip_to_box non-empty) within a bounded deterministic retry budget;
     exhaustion is a typed failure (SCENARIO_REALIZATION_INVALID), never a
     silent drop or an out-of-world plane.
123. Non-TABULAR orebodies are first-class for world generation and
     visualization, but the legacy Phase 03+ layout is TABULAR-only until
     the Phase 20 generalized layout: design entry points fail typed
     (UNSUPPORTED_OREBODY_FOR_LEGACY_LAYOUT, 422) — never 500, never a
     partial layout on unsupported geometry.
124. The backend owns stochastic scenario realization and ALL orebody and
     fault engineering geometry. The frontend may edit explicit
     ScenarioCreate PARAMETERS, and only from direct user input: it must
     never generate stochastic geological parameters (no client-side
     randomness) nor independently derive orebody or fault geometry. The
     final explicit ScenarioCreate the user submits is the authoritative
     persisted scenario — a realization seeds the editable draft and is
     never silently re-run over user edits; changing preset, seed or fault
     count invalidates the draft instead.
125. Randomized orebody acceptance is judged on the ACTUAL analytic solid,
     never on its centre: build the candidate and test
     `build_orebody(cfg).bounding_box()` against the world bounds
     (horizontal safety margin 80 m, top cover margin 40 m, above the model
     floor). Strike/dip rotation means a centre-only test proves nothing.
     Invalid candidates are rejected whole and retried from the same
     deterministic sub-stream — never clamped, never clipped — and
     exhaustion is a typed SCENARIO_REALIZATION_INVALID failure.

133. Implicit membership authority (Phase 19). For an implicit orebody
     (WARPED_VEIN) the smooth implicit function φ defines the solid:
     `contains(x) := φ(x) <= 0` and nothing else. The derived render mesh,
     the derived clearance field, the numerical field lattice and grade
     values never define, refine or override membership.
134. Distance honesty. `EXACT_METRIC_SDF` (TABULAR, ELLIPSOID —
     `AnalyticOrebody.signed_distance`, exact Euclidean) and
     `DERIVED_APPROXIMATE_CLEARANCE` (WARPED_VEIN —
     `ImplicitOrebody.approximate_clearance`, lattice EDT + trilinear,
     explicit spacing / error metadata) are distinct contracts declared by
     `Orebody.distance_contract`. φ is never called or used as an SDF; an
     approximate clearance is never labelled exact; its sign is forced to
     agree with `contains` and membership wins on disagreement.
135. No approximate hard buffer in a SEARCH. The exact-only boundary is
     the legacy Hybrid-A* search chain (access targets → decline →
     smoothing) and the TABULAR-frame level layout (drift / crosscut
     design, stopes): these CHOOSE geometry against the hard orebody
     exclusion buffer, so an approximate buffer could steer a design into
     the body. They accept only `AnalyticOrebody`; `DesignCostEvaluator`
     with no explicit policy raises `ExactDistanceRequiredError` and every
     such entry point answers UNSUPPORTED_OREBODY_FOR_LEGACY_LAYOUT (422),
     never 500 (rule 123). WARPED_VEIN → approximate clearance → Hybrid-A*
     is forbidden.

     A SWEEP is different (closeout v5). The Phase 06 ramp tunnel mesh and
     the Phase 20B development mesh do not choose geometry: they sweep a
     centerline that was already validated under the layout-v2 clearance
     policy and judge the resulting excavation envelope. They build their
     evaluator with `clearance_policy_for(world.orebody)` — for an
     `AnalyticOrebody` that is the very same `ExactClearance` the default
     constructor yields (bit-identical numerics); for an implicit body it
     is the conservative basis (COARSE_CONSERVATIVE), which can only reject
     more of the envelope than an exact check would, never admit more. A sweep therefore never
     relaxes rule 135; it applies the buffer the centerline was designed
     under.
136. Resolved morphology. Every stochastic shape control AND every mode
     coefficient of a WARPED_VEIN is drawn in `scenario_realizer.py`
     (orebody sub-stream 0x0B0D17, no new key) and persisted resolved in
     `orebody.warpedVein`; `build_orebody` / `generate_world` contain zero
     hidden shape randomness. Invalid candidates are rejected whole and
     retried deterministically; exhaustion is SCENARIO_REALIZATION_INVALID.
     The frontend never generates coefficients: WARPED_VEIN is entered only
     through the RANDOM_WARPED_VEIN preset and leaving it discards the
     morphology.
137. Shape-model versioning. `orebody.warpedVein.shapeModelVersion` pins
     the mathematical interpretation of the persisted coefficients
     (currently 1 = `world/warped_vein.py` shape model 1). A basis,
     normalization or formula change gets a NEW version; unsupported
     versions are rejected explicitly (422) and never reinterpreted. The
     global Scenario `schemaVersion` stays 2 (the block is additive).
138. Derived mesh. The orebody render mesh is a deterministic derivative
     of the same implicit solid (marching cubes on the derived geometry
     lattice, welded, watertight, outward, inside the conservative
     bounding box, vertices on φ = 0 within lattice resolution). It is
     never an independent visual deformation and never authored on the
     client. `contains`, `volume` (deterministic 2-D quadrature of the
     morphology, documented tolerance), `bounding_box` (conservative
     analytic envelope) and `mesh` describe ONE solid (rule 120).
139. Geological smoothness. Synthetic irregularity is low-frequency
     (harmonic modes with wavenumber ≤ 3 on the body extent, bounded
     amplitudes), one connected principal planform, single-valued over
     the strike/dip frame (no overhangs), tapered terminations, a
     guaranteed interior thickness floor (`V ≤ 1 − pinchFloorRatio`, no
     clamping) and a verified pinch/swell, warp and asymmetry range at
     realization. No mesh noise, no voxel morphology, no disconnected
     blobs. It is "geologically plausible synthetic morphology" — never a
     measured, estimated, kriged or imported orebody. Derived geometry uses
     its own lattice (`geometryResolution`, budget-capped, explicit
     failure), never `fieldSampling`.
140. Legacy design boundary. WARPED_VEIN is world / visualization / field
     slice / persistence only until the Phase 20 generalized layout. Design
     entry points fail typed with the Phase 20 explanation; the grade slice
     mask stays OREBODY_INTERSECTION_BELOW_TERRAIN decided by `contains`
     with a conservative bounding-box prefilter (never the approximate
     clearance as an exact bound).

## Roadmap

Product name and direction, and the phases after 17.1 (D0, 18–23), live in
`docs/roadmap.md`. "Digital Twin" is reserved for the future measured-mine
(LiDAR / 3DGS) track and is never used for the synthetic sandbox.

## Architecture consolidation baseline (AC)

`docs/consolidation-baseline.md` fixes the reviewed baseline for the AC
sequence: the baseline SHA, the verified module / artifact-lifecycle map, the
scope index of the rules below (which rule carries the CURRENT authority for a
subject, and which rules describe a legacy path or record a past measurement),
and the change prohibitions every consolidation step accepts. It is a map, not
an authority: it adds no rule, deletes none, reinterprets none, and every rule
below keeps its number and its text. When it and a rule disagree about the
code, the code and the rule win and the map is corrected.

126. Claude Code MAY create local commits after the scoped implementation
     and all required quality gates pass. Claude Code MUST NOT push,
     force-push, merge, create or update pull requests, or perform any
     other remote write without Park's explicit approval for THAT
     SPECIFIC action — a previous approval never authorizes a later push.
     Before requesting approval, report branch, parent SHA, new local
     HEAD, git status, diff --stat, backend gate results, frontend gate
     results, and manual browser acceptance status. Force push is
     prohibited.
127. No block / SMU core semantics (Phase 18). The synthetic world is
     terrain + authoritative orebody solid + a NUMERICAL field lattice
     (`FieldGrid`) carrying `SpatialFieldSet` scalar fields. Lattice cells
     are sampling support only — never mining blocks, SMUs, ore blocks,
     resource blocks or reserve units — and no engineering quantity
     (tonnes, ore/waste membership, grade inventory) is attached to a cell.
     `scenario.fieldSampling` is numerical spacing, never a block size.
     Active production code must not consume BlockModel / RockType /
     ore_fraction / ore_flag / rock_type / oreBlocks / gradeBlocks
     (`tests/test_no_block_semantics.py`, `frontend/src/semantics.test.ts`);
     the names may appear only in the explicit v1→v2 migration and
     legacy-artifact detection paths.
128. Spatial-field public queries are batch-first and vectorized:
     `RegularScalarField.sample(points: ndarray[N, 3]) -> ndarray[N]`
     (trilinear on the center lattice, coordinates clamped, pure NumPy,
     no Python loop per point, no per-sample Pydantic objects, no
     mesh/triangle-distance lookups). A scalar `field(x, y, z)` is never
     the primary interface. `DesignCostEvaluator` obtains rock quality
     ONLY through `world.fields.rock_quality.sample`; near-surface
     behaviour is the field's `COLUMN_TOP_FILL` terrain boundary policy
     (cells with terrain support < 0.5 take the nearest supported value
     below them), not an AIR classification.
129. The analytic orebody solid is the ONLY authority for
     mineralized-domain membership. The grade field is a synthetic
     planning field defined everywhere on the lattice; outside the
     orebody it has no mineral-resource meaning, and every consumer
     applies the orebody geometry itself. A slice of the grade field is
     shipped with an explicit backend display `mask`; the lattice is never
     presented as ore blocks. That mask marks display CELLS that INTERSECT
     the analytic solid (`OREBODY_INTERSECTION_BELOW_TERRAIN`), decided by
     the solid's own signed distance plus a deterministic sub-sample of the
     cell — a proximity or intersection test is never named or exposed as
     membership, which is `orebody.contains` and nothing else.
130. The longhole planning grade proxy is
     `stope prism ∩ orebody solid ∩ below terrain` sampled by a
     deterministic equal-volume midpoint quadrature (spacing ≤ 2.5 m) of
     `GradeField.sample`, averaged. It never uses ore_fraction, cell
     weighting or stochastic integration, and it remains a PLANNING proxy —
     not a resource, reserve or feasibility grade. Stope tonnes stay
     `excavation volume × density`.
131. World-level field statistics are neutral diagnostics (lattice shape /
     spacing / memory, rock-quality field statistics over
     terrain-supported cells, fault count). They never claim resources,
     reserves, in-situ ore tonnage, ore-block counts or a "mean ore grade";
     the orebody payload reports geometric volume only. Future production
     tonnes (Phase 22) mean planned mined tonnes from excavation geometry.
132. Golden-scenario regression is required before AND after any
     core-representation migration. `python -m minegen.regression run`
     records the fixed 22-case suite (HARD CONTRACT: stage outcomes and
     integer structure; QUALITY metrics: lengths, costs, gradients,
     radii, fault exposure, poor-rock length, tonnage, grade proxy;
     runtime advisory only) and `compare` reports every difference; the
     committed baseline lives under `backend/golden/`. A contract
     regression blocks acceptance; an intentional metric change is
     documented in the comparison, never hidden. The smoke subset runs in
     CI (`tests/test_golden_smoke.py`).

141. Required levels are ONE definition. Layout-v2 (Phase 20A) reuses
     `generate_level_elevations(orebody, sublevel_interval, top_margin,
     bottom_margin)` and the `L01…` id convention for every orebody type;
     no second elevation generator exists. A required level with no orebody
     section at its elevation (conservative bounding box of an implicit body)
     is reported (`hasOrebodySection = false`, NO_OREBODY_SECTION_AT_LEVEL)
     and excluded from the serviceable set, never silently dropped or
     re-derived. Serviceable = orebody section exists AND a footwall contact
     exists (hardening H0 §3.1): for a TABULAR body the rule 43 footwall
     line at `z_level` must meet the body, `|footwall_contact_v_coord| <=
     half_height` (`design/targets.py::has_footwall_contact`, the legacy
     chain's own guard); otherwise the level is
     NO_FOOTWALL_CONTACT_AT_LEVEL with `overshootM = |v| − half_height` and
     `minimumTopMiningMarginM = thickness·cos(dip)` (the smallest
     `top_mining_margin` that restores contact). The layout-v2 catalogue's
     `requiredLevels[]` WIRE SHAPE is unchanged (`levelId / index /
     elevation / hasOrebodySection`; the guard moves only
     `serviceableLevelCount` and the candidates' level service — the
     persisted layout_v2 contract under the AC-01G characterization freeze
     is never widened by a hardening change); the typed reason, overshoot
     and hint are reported ONLY in `levels.json` (`excludedLevels[]`,
     `unservedIntervals[]`). The level builder re-derives the TABULAR
     exclusion analytically with the same helper (READ ≠ TRUST — the
     catalogue's `hasOrebodySection == false` is adopted only as the
     non-TABULAR section exclusion) and fails typed when asked to develop
     an excluded level. Changing a margin is the user's explicit edit, never a
     silent clamp.
142. Finite declared enumeration. Layout-v2 candidates come only from the
     typed `scenario.layout` grids (SPIRAL, LONGITUDINAL, SWITCHBACK ×
     target gradients) in a frozen order (family order, then declared
     field order, gradient innermost); candidate ids encode their
     parameters. No optimizer, no random sampling, no hidden parameter;
     the enumerated count is reported. FIGURE_EIGHT / HYBRID are reserved
     names, not implemented.
143. Derived coupling, never free parameters. SPIRAL radius is
     `R = ΔZ / (2π·g·n)` (infeasible below R_min or outside the world;
     non-uniform level intervals are LEVEL_INTERVAL_NONUNIFORM);
     SWITCHBACK straight leg is `ΔZ/(k·g) − π·R_min` (LEG_TOO_SHORT below
     `minStraightLength`); LONGITUDINAL plan direction is coupled to the
     footwall drift with depth. Every candidate starts at the authoritative
     portal with continuous position and heading.
144. Only the DELIVERED discretized centerline is judged: gradient
     (vertical/horizontal per edge), chord-based plan radius, world bounds,
     monotonic descent, cover, restricted zones, orebody clearance and
     level service are all measured on the sampled polyline
     (`sampleSpacing`), never on analytic intent. Level service is the
     first z-crossing by segment interpolation (no elevation tolerance) and
     `d_access = min horizontal distance to the footprint (contains) at zL`
     ≤ `accessReach`, with per-level typed unserved reasons.
145. Family-signature diagnostics are quantitative: cumulative / signed
     heading change, hairpin runs and reversals (same-sense runs of
     150°–210°), dominant azimuths, turn-direction consistency, min plan
     radius. A SPIRAL has a large consistent cumulative change and zero
     reversals; a SWITCHBACK has repeated reversals; a LONGITUDINAL has one
     dominant axis. WARPED_VEIN level access is measured on the authoritative
     solid, never from a global strike.
146. Clearance policy is explicit. `DesignCostEvaluator` accepts a
     `ClearancePolicy`: EXACT (analytic SDF, legacy numerics unchanged and
     still the only policy the Hybrid-A* search chain constructs; never the
     name of an implicit body's basis) or a conservative basis
     (`safe = certifiedClearance − errorBound`, errorBound = 1.5 × the
     lattice diagonal — a DERIVED factor: boundary discretization ≤ 1
     diagonal + trilinear interpolation of a 1-Lipschitz field ≤ 0.5;
     empirical error ratios are reference metrics and never lower it).
     Phase 20B.1: the whole-body lattice is COARSE_CONSERVATIVE; stage 4
     may build ONE local refined window per shortlisted candidate
     (REFINED_CONSERVATIVE, same 1.5 × ‖spacing‖ on `spacing / factor`,
     window-boundary clamped, coarse fallback outside, explicit cell
     budget) — the bound narrows ONLY by shrinking the spacing. Layout-v2
     and the downstream sweeps (Phase 06 tunnel mesh, Phase 20B development
     mesh) take `clearance_policy_for(world.orebody)`. Layout-v2 reports
     clearanceBasis, certified / approximate minimum clearance, the ACTUAL
     latticeSpacing and errorBound used, refinement diagnostics and the
     required clearance (`buffer + hypot(width/2, height)`); WARPED_VEIN is
     first-class in layout-v2 and its sweeps, and still refused by the
     Hybrid-A* search chain (rule 135).
147. Hard constraints stay hard. Layout-v2 stages are enumerate → cheap
     evaluation → bounded shortlist → detailed validation through the shared
     `DesignCostEvaluator` sample validator → deterministic ranking; a
     violated hard constraint makes the candidate INFEASIBLE with typed
     reasons and is never converted into a score penalty. Every candidate
     stays inspectable with its status.
148. Three score groups only. Development, Geology and Geometry are the
     user-facing objective; each is a documented combination of module
     constants (`layout/search.py`), only the three group weights are
     configurable, and ranking is `(feasible, total within 1e-9, family
     order, candidate id)`. Scores are planning comparators — not an
     optimality claim and not a cost estimate.
149. Effective Ramp contract. Downstream phases consume one source-neutral
     ramp (`status, sourceKind ∈ {LEGACY_SMOOTHED, LEGACY_RAW_FALLBACK,
     PARAMETRIC_V2}, owningArtifact, sourceRevision, portal, segments[]` in
     the Phase 05 shape). The legacy artifact is exposed through an adapter
     (geometry untouched); a layout-v2 ramp is the validated candidate
     centerline split EXACTLY at its level connection points, never forced
     through the Phase 05 smoother and never forged as `decline.json`.
     `layout_v2.json` (catalogue, geometry only for shortlisted candidates)
     and `layout_v2_selected.json` (materialized winner) are separate,
     revision-aware, backend-authored artifacts.
150. Active-source resolution is explicit and backend-owned:
     `derived/ramp_source.json` (`LEGACY` default | `LAYOUT_V2`) decides
     which artifact the tunnel, levels, network, timeline, communication and
     sensor builders read (`GET …/design/ramp`); the scene's
     `smoothedDecline` IS the active Effective Ramp. RAMP `geometryRef`s
     point at the owning artifact (`decline_smoothed.json` or
     `layout_v2_selected.json`); the frontend resolves them through
     `rampOwningArtifact`, never by position or name.
151. Layout lifecycle invalidation. Scenario mutation / world regeneration
     clears the catalogue, selection, source switch and everything below;
     regenerating the catalogue deletes the selection; selecting or
     activating a candidate, or switching the source, deletes tunnel,
     levels, network, stopes, timeline, communication and sensors. Legacy
     regeneration invalidates only a LEGACY-derived chain and layout-v2
     regeneration only a LAYOUT_V2-derived chain. Geology is never
     invalidated by layout operations.
152. Phase 20A scope boundary. Drifts / crosscuts for non-TABULAR bodies,
     the layout-v2 walkthrough for WARPED_VEIN, FIGURE_EIGHT / HYBRID
     families, local bounded A* refinement and rulebook compliance belong to
     Phase 20B–20D. The frontend edits only explicit layout parameters and
     performs no layout engineering (no client-side enumeration, scoring or
     geometry).

153. A main-ramp RL crossing is a RAMP LEVEL REFERENCE, never a level entry
     (Phase 20B). The physical route is PORTAL → RAMP → RAMP_JUNCTION
     (turnout) → LEVEL_ACCESS → LEVEL_ENTRY → level development → production
     access. `RAMP_LEVEL_REFERENCE == LEVEL_ENTRY` is never assumed; the
     Phase 20A crossing / footprint-reach predicate survives only as the
     stage-2 ACCESS-POTENTIAL SCREEN (`withinReach`), never as "served".
154. LEVEL_ENTRY is owned by the terminal of a validated Level Access. The
     level drift is anchored there (`entrySource = LEVEL_ACCESS`); a
     PARAMETRIC_V2 ramp whose segments end at turnouts is refused by the
     level builder without the level-access artifact
     (LEVEL_ACCESSES_REQUIRED). LEGACY keeps its Phase 05 segment ends as
     entries behind the same builder (`entrySource = LEGACY_RAMP_SEGMENT`).
155. Level Access is separate geometry from the Effective Ramp. The main
     ramp is split EXACTLY at its ramp junctions (plus the `RAMP_END` tail);
     access branches are never ramp segments and never inflate ramp totals.
     Artifact ownership: `layout_v2_selected.json` (main ramp),
     `level_accesses.json` (junctions + branches + anchors, written with the
     selection under the same revision), `levels.json` (level / production
     development). No polyline is duplicated across artifacts.
156. Final "level served" means explicit physical access: a valid ramp
     junction, a validated branch welded to the ramp (≤ 1e-6 m) reaching the
     authoritative level-development anchor, hard constraints passed, and a
     connected network path from the portal to the level entry. A layout-v2
     candidate is FEASIBLE only when EVERY serviceable required level has a
     valid access (LEVEL_ACCESS_INFEASIBLE otherwise, with per-level typed
     reasons). Development score = main ramp + total access length; access
     failures are never score penalties.
157. Level-access planning is finite and deterministic: junction candidates
     on a `junctionSearchSpacing` chainage lattice inside the
     `junctionWindowAbove/Below` elevation window; a G1 ONE-TURN CS
     connector (Phase 20B.2-A: S, L+S or R+S — one turnout arc of
     R = minTurnRadius tangent to the ramp heading, then one straight to
     the anchor POINT; no terminal arc, no ARC+STRAIGHT+ARC, sweep ≤ π so
     loops are structurally impossible; a target inside the turning circle
     is CONNECTOR_UNAVAILABLE) with the rule-188 vertical profile
     (ramp-floor follow through the plan overlap, then one constant
     chord gradient to the entry). The
     anchor heading stays the drift direction; the access's
     `terminalHeading` is the ACTUAL final-straight heading and the weld at
     the level entry is position-only (`terminalHeadingMismatchDeg` is
     reported, never gated). Selection = min (selection cost, length,
     junction chainage, connector sense S < LS < RS);
     `minimumRampJunctionSpacing` is a hard rule (JUNCTION_SPACING_CONFLICT). Every candidate branch is judged on
     the DELIVERED polyline (gradient, circumradius, world, cover,
     restricted zones, clearance under the evaluator's policy, excavation
     envelope). Nothing is clamped; an impossible access is typed.
158. Level-development anchors are backend engineering geometry: the
     footwall backbone at `anchorStandoff` from the footwall edge (exact
     rule 43 line for TABULAR; the numerical level section's principal axis
     and footwall-side extent for implicit bodies), entry placed by the
     explicit `entryPolicy` (NEAREST_TO_RAMP), terminal heading along the
     backbone. Under a CONSERVATIVE clearance policy the stand-off is raised
     so the entry itself satisfies `required + errorBound`. The frontend
     never reconstructs access or anchor geometry.
159. Generic level access never encodes LONGHOLE production geometry. The
     level builder always develops the generic backbone drift; the longhole
     crosscut station lattice exists only for LONGHOLE_OPEN_STOPING.
     CUT_AND_FILL (and every other reserved method) gets ramp junctions,
     level accesses and the backbone drift, and reports
     `productionDevelopment.status = UNSUPPORTED_METHOD` for its production
     portion — never a silent longhole substitute. The generic backbone
     extent is the orebody strike extent minus a fixed end clearance
     (`GENERIC_BACKBONE_END_CLEARANCE`, shared with the anchor placement);
     `stope_length` / `minimum_pillar` are LONGHOLE production parameters
     and never change generic level development.
160. MineNetwork preserves physical truck connectivity: RAMP edges end at
     RAMP_JUNCTION / RAMP_END nodes, LEVEL_ACCESS edges (owned by
     `level_accesses.json`) join a RAMP_JUNCTION to its LEVEL_ENTRY, and
     DRIFT / CROSSCUT never touch a ramp node. Scheduling roots each level's
     development at the access task (which depends on the ramp task reaching
     its junction); infrastructure and timeline resolve LEVEL_ACCESS
     geometry through its owning artifact. No frontend shortcut exists.
161. Plan radius on a delivered centerline is the three-point circumradius
     `|p_{i+1} − p_{i−1}| / (2·sin δ_i)` (exact for any sampling of a circular
     arc; ∞ for collinear triples; RADIUS_TOLERANCE 0.05 m covers only
     floating-point noise). A true R_min hairpin sampled at 5 m is accepted.
162. Level-access lifecycle: `level_accesses.json` is invalidated with the
     layout selection (catalogue regeneration, re-selection, scenario /
     world change) and is a fingerprint input of levels, network, timeline,
     communication and sensors; switching the ramp source keeps it (it
     belongs to the selection). Geology is never invalidated by a level
     access. Approximate WARPED_VEIN clearance stays explicitly conservative
     and the legacy pipeline stays behind its compatibility path.

163. Preferred access length (Phase 20B closeout v3). `minimumAccessLength`
     (15 m) stays the HARD floor and `maximumAccessLength` the hard ceiling;
     `LevelAccessConfig.preferredAccessLength` is a mine-PLANNING default,
     never a statutory value or a mandatory minimum. `None` resolves to
     `max(minimumAccessLength, 6 × tunnel_width)` (30 m for the 5 m default
     tunnel); an explicit value must lie inside [min, max] — validated,
     never clamped. Among VALID junction / connector candidates the planner
     minimizes `(|L − P| + LONG_ACCESS_COEF · max(0, L − P), L, junction
     chainage, sense)`; `LONG_ACCESS_COEF` (0.5) is a documented deterministic
     module constant in `layout/access.py` — provisional, not a user weight
     and not an engineering invariant. Every access reports
     `effectivePreferredAccessLength`, `lengthDeviationFromPreferred` and
     `selectionCost`. The topology (RAMP_JUNCTION → LEVEL_ACCESS →
     LEVEL_ENTRY → drift) is unchanged: no LEVEL_STATION node, no new
     junction semantic.
164. Stage-2 access-potential screen semantics. `withinReach` /
     ACCESS_REACH_EXCEEDED (same-RL crossing → orebody footprint distance)
     is a HEURISTIC: it feeds the stage-3 cheap proxy (mean access
     distance) and stays inspectable per level, but it NEVER rejects a
     candidate. Only NO_RL_CROSSING — the main ramp does not vertically
     cover the level, so no junction lattice can exist — remains a hard
     stage-2 failure (`level_screen_problems`). Stage 4
     (`plan_level_accesses`) is the final service authority; gradient,
     radius, clearance, envelope and world hard constraints are never
     relaxed. TABULAR and WARPED golden results MAY change under this rule;
     every change is explained in the golden comparison, and no partial
     reach gate is kept to preserve an old winner.
165. Shortlist starvation is audited, not assumed. The production search
     keeps the bounded shortlist; `LayoutV2Search.run(detailed_all=True)`
     is a DIAGNOSTIC mode (never a config or API option) and
     `python -m minegen.regression layout-v2-audit` records, per golden
     case, the feasible candidates the shortlist never validated and whether
     the exhaustive winner or a feasible family is missed. A family-diverse
     shortlist or a cheap lower bound is added only when that audit shows
     a missed winner / family — which the Phase 20B.1-D audit did (under
     the rule 171 gates the old length-only proxy missed exhaustive winners
     at cheap ranks 40/62 and 22/26): the stage-3 proxy is now the cheap
     LOWER BOUND of the weighted total (development without the
     non-negative access length + the full geometry group without the
     non-negative clearance headroom; geology ≥ 0 omitted), AND every
     declared family's best cheap-feasible candidate holds a shortlist
     slot (bound unchanged: the proxy tail is displaced, order stays
     (proxy, family order, id)). The re-run audit is the acceptance
     instrument.
166. Development excavation meshes (closeout v3 §4). LEVEL_ACCESS / DRIFT /
     CROSSCUT are swept by `design/development_mesh.py` through the SAME
     Phase 06 machinery (`build_ring_chain` / `build_logical_mesh` /
     `build_render_mesh`) and gravity-aligned profile frame on their
     authoritative centerlines (`level_accesses.json`, `levels.json`) —
     never re-designed, moved or decimated; only the RENDER tessellation is
     coarser (arch segments halved, subdivision spacing doubled). Endpoint
     policy is explicit: CAP closes an isolated end (drift extremities, the
     crosscut face), OPEN leaves the ring boundary open where a development
     joins another excavation (access at the turnout and at the entry,
     crosscut start). QA is split: CAP-CAP tubes keep the closed-solid
     contract (manifold, watertight, outward, signed volume); OPEN tubes are
     manifolds with boundary (finite, valid indices, non-degenerate,
     orientation-consistent, exactly K boundary edges per open end on the
     end rings, ring/centerline correspondence, envelope) and are never
     asked for a closed signed volume. Render batching is one tube
     primitive + one cap primitive per kind with `ranges` extras mapping
     back to development / piece ids; materials are shared by role.
     `development_mesh.{json,glb}` is invalidated with `levels.json`.
     Boolean wall openings, exact junction CSG and an all-development
     watertight union are Phase 20D ("Unified Development Mesh"); so is
     walkthrough / collider integration — the Phase 13–15 walkthrough
     traverses the Phase 06 ramp tunnel only and does NOT enter the
     level-access, drift or crosscut excavation meshes. Without CSG the
     OPEN ends leave the neighbouring tube's inner shell visible at a
     turnout; that is the recorded Phase 20D limitation, never patched in
     Phase 20B.
167. Legacy decline UX boundary. The primary workflow is World → Layout v2
     → select / activate → level access → level development → excavation
     meshes → network → stopes → timeline. The Phase 03–05 chain (access
     targets, Hybrid-A* decline, smoothing) and the explicit LEGACY ⇄
     LAYOUT_V2 source switch are ONE collapsed "Legacy decline (Hybrid-A*)
     — Advanced" section that auto-expands only when `activeSource ==
     LEGACY AND hasLegacyWork` (an access-target, decline or legacy smoothed
     artifact exists); the `accessTargets` / `rawSearchPath` layers default
     OFF and are hidden when a layout-v2 candidate is activated. Legacy
     backend, API, artifacts, schema, tests and goldens are untouched and
     the source-neutral Effective Ramp stays.
168. Standoff / clearance semantics are AUDITED (Phase 20B.1 commit C
     executed roadmap item S1; the call-site table lives in
     `docs/algorithms.md`). `RampConstraints.clearance` (UNWIRED/RESERVED),
     `DesignConfig.orebody_exclusion_buffer`, the layout-v2 required
     centerline clearance (`buffer + hypot(width/2, height)`),
     `footwall_access_offset`, the level-access anchor stand-off, the WARPED
     conservative error bound and the preferred access length are DIFFERENT
     distance concepts, and
     `ramp_standoff >= level_entry_standoff + preferred_access_length` is
     STILL not an invariant (a spatial stand-off and a centerline path
     length are not additive in general) — the audited corridor default
     (rule 170) sums SPATIAL margins only.

169. Effective Ramp IDENTITY decides downstream preservation — never
     `activeSource` alone. The identity is (active source, selected layout
     candidate, layout revision): switching LEGACY ⇄ LAYOUT_V2 AND replacing
     the selected candidate under an already-active LAYOUT_V2 both change it
     and invalidate tunnel mesh, development mesh, levels, network, stopes,
     timeline, communication and sensors; re-selecting or re-activating the
     same candidate at the same revision is idempotent. The frontend keeps
     ONE comparison per half — `afterLayoutSelect` owns the candidate /
     revision half, `afterRampSourceChange` the source half — and activate
     composes them (`afterLayoutActivate`); the comparison is never
     duplicated. The level accesses owned by the activated selection
     (rule 157) survive the composition.


170. Main-ramp corridor stand-off is separated from the level-development
     plane (Phase 20B.1 C, the audited S1 misuse). `layout.footwallStandoff`
     positions the main-ramp CENTERLINE's ore-facing nearest approach
     (SWITCHBACK near-leg centerline / SPIRAL helix rim / LONGITUDINAL
     corridor centerline) and defaults to `ramp.footwall_access_offset +
     RAMP_CORRIDOR_MARGIN_WIDTHS × tunnel_width` (6 widths: two lateral
     half-spans + a two-width rock pillar + a three-width turnout-taper
     allowance, the lateral offset a minimum-radius turnout develops inside
     its own geometric taper — spatial planning margins, never statutory,
     never a path-length term). The level-development
     anchor plane stays at `footwall_access_offset` (raised only by the
     conservative-clearance honesty rule). The pre-audit behaviour — both
     defaulting to the same 20 m, making the permanent ramp collinear with
     every level drift (measured envelope separation −4.9 m) — must not be
     reintroduced.

171. Level-access separation gates are HARD (Phase 20B.1 B). Every access
     candidate passes, typed and never clamped: junction → entry PLAN
     separation ≥ `minimumRampToEntryPlanSeparation` (None → 6 × width);
     branch-to-ramp excavation separation (rock pillar) ≥
     `minimumExcavationSeparation` (None → 2 × width), judged
     on the delivered branch beyond the geometry-derived turnout taper
     `s* = R·arccos(1 − (pillar + width)/R)` with the terminal always
     included; and turnout curvature — cumulative |Δheading| of the
     delivered main ramp over junction ± `minimumTurnoutStraightBuffer`
     ≤ `maximumTurnoutHeadingChangeDeg` (100° default: rejects turnouts in
     near-minimum-radius turns, family-neutral; a TRUE straight-insert
     turnout needs Phase 20C family support and this v0.1 gate does not
     claim it). Length cost stays the secondary ordering. A level failing
     with junction-spacing conflicts records the B-5 assignment diagnostic
     (the same search re-run ignoring only the used spacing) so greedy
     starvation is distinguishable from geometric infeasibility; the
     diagnostic never relaxes a constraint and never changes the result.
     These are engineering planning defaults, never statutory values.

172. Direction-aware rock pillar and one certification per selected design
     (Phase 20B.1-v2). The B-2 excavation separation is the DIRECTION-AWARE
     sampled envelope gap: at every post-taper branch sample the
     closest-centerline pair is found, `u` = branch → ramp, and each tunnel's
     gravity-aligned cross-section (`ProfileShape`, `gravity_frames`)
     contributes its support along `u` — `gap = d − support_branch(+u) −
     support_ramp(−u)` — so horizontal parallel drives read
     `width/2 + width/2` (unchanged) and a drive below another reads
     `height + 0`. It is a cross-section support at the sampled closest
     pair, never claimed as an exact swept-surface / mesh-to-mesh distance;
     the isotropic `hypot(width/2, height)` on both sides is forbidden. The
     taper `s*` is unchanged. Separately, the selected Effective Ramp, its
     level accesses, the tunnel sweep and the development sweep are judged
     under the SAME candidate-specific clearance certification that made the
     candidate FEASIBLE in stage 4 (`LayoutV2Search.candidate_policy`,
     rebuilt deterministically from `candidateId + layoutRevision` — no new
     persisted field); LEGACY keeps the world policy. A stale selection or a
     reconstruction that disagrees with the recorded stage-4 report fails
     closed (409 `LAYOUT_V2_SELECTION_STALE` /
     `LAYOUT_V2_CLEARANCE_MISMATCH`). `level_accesses.json` reports the
     candidate's ACTUAL basis / bound / refinement; the catalogue's
     `clearanceBasis` stays the whole-body search basis. The shortlist bound
     is never smaller than `len(FAMILY_ORDER)` (schema-validated, sized from
     the enumeration, never a literal), so the bound and the per-family
     reserved slot (rule 165) hold together.

173. Progressive excavation reveal is VISUALIZATION over shared buffers
     (Phase 20B.2-F). Every SEGMENT primitive of the Phase 06 ramp GLB and
     every batched piece range of the Phase 20B development GLB is emitted
     ring interval by ring interval in chainage order and carries
     `indexStride`, `ringIntervalCount` and `ringChainageFractions`; the 4D
     view shows a DEVELOPING excavation as the index PREFIX of its last
     COMPLETED ring for the Phase 10 progress (a draw range on a per-segment
     primitive, draw groups on a batched primitive) over geometry that
     shares the loaded vertex / index buffers. Nothing is re-swept,
     re-generated or copied per day or per frame, the cached GLB scene is
     never mutated, and the walkthrough / static layers are untouched. The
     mapping is timeline-authoritative through each `geometryRef`'s OWNING
     artifact (RAMP → primitive `segmentId`, LEVEL_ACCESS → piece
     `LEVEL_ACCESS:<levelId>`, DRIFT / CROSSCUT → the levels.json
     development id) and fails CLOSED per development: an unmapped
     development keeps its centerline rendering, never a guessed mesh. The
     revealed volume is a display cut aligned to backend rings — not
     engineering excavation geometry and never persisted (rule 115 analogue).
     Batched caps are shown only once every piece of their kind is complete.

174. Excavation direction contract (Phase 20C.1-V). Every
     `DevelopmentTimeline` names the network node it is excavated FROM
     (`excavationStartNode`: the portal side of a ramp segment, the junction
     of a level access, the endpoint reached first from the level entry for
     drifts / crosscuts) and `progressDirection ∈ {+1, −1}` along the OWNING
     centerline's point order: progress p reveals chainage fractions [0, p]
     for +1 and [1 − p, 1] for −1. Chainage fraction 0 of PROGRESS is always
     the start end and 1 the face; the reveal grows monotonically start →
     face. `pointChainageFractions` stay geometry-ordered (rule 83) and the
     centerline geometry is never reordered (colliders, mesh extras and
     network edge direction depend on it) — the direction lives in the
     fraction-semantics layer, and lines, meshes and future face
     calculations inherit it. A start node that is not welded to a
     centerline endpoint fails the timeline explicitly; the frontend never
     decides direction from the camera or by patching individual edges.
175. Switchback hairpin station (Phase 20C.1-S). The station length is a
     DECLARED finite grid axis (`layout.switchback.stationLengthsM`, `None`
     → `[0, 2 × access.minimumTurnoutStraightBuffer]`; 50 m is a planning
     default, never statutory) enumerated between turn sense and gradient
     (family order frozen, ids of station-0 candidates unchanged, `-s<m>`
     appended for a station). A station hairpin is arc(π/2) + straight(s) +
     arc(π/2) at the minimum radius with leg spacing `2·R_min + s` and the
     station subtracted from the derived leg (rule 143); it competes on the
     unchanged score under every unchanged hard constraint — no threshold,
     coefficient, buffer or gate changes with it. Diagnostics treat one
     arc–straight–arc hairpin as ONE reversal / hairpin run (station merge,
     bounded by `max(stations) + sampleSpacing`, merging only sub-150° runs)
     so the turning-burden score cannot be escaped by a station. A level
     that still fails with a station is a real constraint, reported with
     the per-level typed reason and numbers, never a relaxed gate.
176. Geometric access screen as the stage-3 ORDER, never a gate (Phase
     20C.1-Q). The shortlist-yield audit (`python -m minegen.regression
     layout-v2-yield`, a priori rule: pooled rank AUC ≥ 0.6 over ≥ 5 pairs =
     "correlated") showed the rule 165 lower-bound proxy predicts SPIRAL
     detailed outcomes (pooled AUC 0.673) but not SWITCHBACK ones (0.507 —
     the closeout A-1 pair-weighted within-case values; the Q commit quoted
     0.665 / 0.489 from a pooling that concatenated per-case ranks, and both
     verdicts are unchanged by the correction): the
     proxy bounds the SCORE and cannot see level-access feasibility. The
     corrective is not a coefficient: every cheap-feasible candidate runs the
     evaluator-free stage-4 access gates (`geometric_access_screen` —
     the SAME `_search_level` code path with `geometric_only=True`: junction
     lattice, B-3 turnout curvature, B-1 plan separation, connector
     availability, gradient, length, plan radius, B-2 rock pillar; junction
     spacing ignored) and a level with no passing candidate is BLOCKED —
     never a rejection. Stage-3 order is `(blockedLevels, proxy, family
     order, id)`; the shortlist bound, the per-family slot (rule 165) and
     stage 4 as the final authority are unchanged, and `accessScreen` stays
     inspectable per candidate. The B-2 pillar keeps its exact
     direction-aware semantics (rule 172); the KD-tree vertex pre-filter in
     `nearest_on_polyline` is a proven-identical cost reduction, not an
     approximation.

     What a BLOCKED level PROVES is decided by the CLEARANCE POLICY's
     distance contract, never by the orebody type (Phase 20C.1 closeout B),
     and every screen result declares it as `accessScreen.authority`:

     - EXACT contract (`ExactClearance`, currently the analytic bodies): the
       screen anchors sit at the SAME stand-off stage 4 uses
       (`anchor_standoff` raises it only when `basis != "EXACT"`) and the
       gates are the same gates, so BLOCKED is a NECESSARY CONDITION —
       `blocked ⊆ stage-4 failed` holds and is tested.
     - CONSERVATIVE contract (`ConservativeClearance` /
       `RefinedConservativeClearance`, currently WARPED_VEIN): the screen
       anchors sit at the COARSE stand-off while stage 4 may refine the
       bound, shrink the stand-off and move the entry, so BLOCKED is a
       HEURISTIC. It is never called "provably unservable" or a necessary
       condition, and the `blocked ⊆ failed` contract is NOT applied (nor
       tested) there. Three separate statements, none of which implies
       another:
       (i) the screen never REMOVES a candidate, under either contract;
       (ii) BLOCKED is not a FEASIBILITY authority — stage 4 decides, and a
       coarse-blocked level can still be served;
       (iii) `screen_blocked` IS nevertheless used as the primary key of the
       current bounded search's stage-3 order — a NON-AUTHORITATIVE ORDERING
       HEURISTIC, exactly as `_shortlist_key` implements it.
       The reason it is kept is not that it is free: the closeout-B
       measurement (`golden/phase20c1_closeout_screen_audit.json`,
       `python -m minegen.regression layout-v2-screen-audit`) found 56 false
       blocks on the conservative side (WARPED-301 27, WARPED-307 2,
       IRREGULAR 27), 6 of them on candidates the production shortlist had
       validated, against 0 on every EXACT case. It is kept because removing
       it REGRESSES the family-yield acceptance of the current golden suite
       (measured: WARPED-301 `missedFamilies` [] → ['SWITCHBACK'], production
       feasible 10 → 3), and that false-block behaviour stays a documented
       Phase 20C.2 limitation. Any change to this ordering must preserve
       `missedFamilies = []` and `winnerMissedByShortlist` false on every
       golden case.

177. Authoritative section(z) geometry (Phase 20C.2A A1,
     `layout/sections.py`). The horizontal section of ANY orebody at a
     required-level elevation is measured on a world-origin-anchored
     occupancy grid whose only membership authority is `Orebody.contains`
     — never WARPED control points, a nominal strike, bounding-box edges,
     mesh vertices or the frontend. Components are 4-connected
     (`scipy.ndimage`, no diagonals); ONE dominant component is selected
     by (sampleCount desc, centroid.x asc, centroid.y asc), ignored
     components are recorded and never merged, deleted or developed. The
     marching-squares outer contour (largest |shoelace area|,
     CCW-normalized) is a grid-resolution boundary — never called an
     exact ore contact; hole loops are diagnostics. Resolution contract:
     `effective_section_spacing <= base_anchor_standoff /
     SECTION_TRACE_SAMPLES_PER_STANDOFF` (4), base stand-off = explicit
     `access.anchorStandoff` else `ramp.footwallAccessOffset`,
     power-of-two refinement only, a non-positive base stand-off is a
     typed SECTION_STANDOFF_NONPOSITIVE (never a schema change). Cell
     budgets `SECTION_MAX_GRID_CELLS_PER_LEVEL` = 2,000,000 and
     `SECTION_MAX_GRID_CELLS_TOTAL` = 16,000,000 (documented from the
     Gate 0 32-seed measurements: worst default scenario ≈ 2.97 M cells,
     one /2 refinement ≈ 11.9 M) are validated from the PROJECTED grid
     shape before any allocation (SECTION_RESOLUTION_BUDGET_EXCEEDED);
     occupancy is evaluated with a deterministic chunked `contains`
     sweep. Section geometry is candidate-independent, built lazily once
     per level and cached (`LevelSections.geometry`).

178. Footwall trace and offset development backbone (Phase 20C.2A A2/A3).
     The dominant FootwallTrace is the footwall-side arc of the outer
     contour: local tangents from a ± baseStandoff/2 windowed secant
     estimator, outward normals VERIFIED against contains() probes, and
     `track.w_h` used ONLY as the orientation seed deciding which side is
     the footwall. No decisive orientation or no footwall run ≥ 4 grid
     spacings is a typed SECTION_FOOTWALL_AMBIGUOUS — the whole-section
     principal-axis (PCA) backbone is GONE and must not return. The
     offset development backbone is the level set of the DESIGN CLEARANCE
     POLICY (`signed_clearance`) at the anchor stand-off ON THE LEVEL
     PLANE — never a 2-D in-plane offset of the section (measured on
     WARPED-301 L03: 82 % of the in-plane-EDT trace sat below the
     required 3-D clearance because the body leans over the level plane).
     The delivered trace is uniform-chainage resampled, box-smoothed at
     the stand-off scale (sub-stand-off wiggles — including the
     piecewise-trilinear field's level-set corners — are below the trace
     resolution contract), resampled again, and RE-VALIDATED: finite,
     minimum length, no self-intersection, and clearance ≥ the required
     design clearance (the hard floor; the stand-off stays the PLANNING
     target, reported as a diagnostic). Smoothing never hides a
     hard-clearance violation and the unchanged hard gates still judge
     every delivered development. Traces are cached per (level, w_h,
     stand-off, clearance-policy token); the tokens are deterministic
     (world policy vs candidate id), so a trace is never reused across
     clearance fields.

179. Curved anchors and typed level failures (Phase 20C.2A A3). For every
     non-TABULAR orebody `build_anchor` yields the curved anchor: entry
     policy NEAREST_TO_RAMP as the plan-closest ADMISSIBLE chainage on
     the offset backbone (end margins on chainage, ties to the lowest
     chainage), preferred heading = the local trace tangent toward the
     longer usable side (tie: trace orientation), payload extended with
     traceChainage, traceLength, localTangent, inward localNormal,
     oreContact, selectedComponentId and the section spacings. TABULAR
     keeps the exact rule 43 line unchanged. A section-geometry failure
     travels as a typed AnchorFailure and receives IDENTICAL treatment in
     the geometric access screen and stage 4 (the two differ ONLY in
     clearance policy and stand-off); the rule 176 screen-authority
     contract and stage-3 ordering are unchanged. `required_clearance`
     has ONE definition in `design.profile` (re-exported by
     `layout.search`).

180. Curved level development (Phase 20C.2A A4). The level builder
     dispatches by the AVAILABLE development-geometry contract — entries
     carrying curved anchors (non-null traceChainage) — never by orebody
     isinstance; a non-TABULAR body without curved anchors is a typed
     SECTION_TRACE_ANCHORS_REQUIRED and mixed contracts are a typed
     MIXED_DEVELOPMENT_GEOMETRY. The builder rebuilds the offset backbone
     deterministically under the SELECTED candidate's certified clearance
     policy (rule 172) and the persisted entry must reproduce on it at
     its recorded chainage within 1e-6 m (typed SECTION_TRACE_MISMATCH,
     fail closed — never a re-anchor). The curved DRIFT follows the
     backbone with `level_drift_gradient` applied along chainage from the
     entry (the entry never moves); LONGHOLE stations use the
     `stope_length + minimum_pillar` pitch on CURVED drift chainage,
     symmetric about the trace midpoint with the stope + end-pillar
     margin inside the span; CROSSCUTS run horizontally along the LOCAL
     inward normal — the ± horizontal perpendicular of the offset trace's
     local tangent at the station, the ore side decided by bounded
     deterministic contains() probes. A station inside the ore or with ore
     on BOTH perpendiculars is a typed per-station failure, never a
     nearest-cell fallback; a station where NEITHER perpendicular finds
     ore within the probe budget (the level set wraps around the body's
     tapered ends) is reported and EXCLUDED from the REQUIRED lattice
     (NO_PERPENDICULAR_ORE_SUPPORT, rule 141 precedent — recorded per
     level, never silently dropped; a level whose stations are ALL
     excluded fails typed). Confirmed crosscuts end with a
     contains()-bisection ore-contact terminal — the terminal is the
     OUTSIDE end of a ≤ 1e-6 m bracket (`terminalContactGap`). Every
     development passes the SAME hard validation as the TABULAR path;
     `levels.json` declares `developmentGeometry` (TABULAR_RULE_43 |
     SECTION_FOOTWALL_OFFSET_TRACE) and the TABULAR path is
     bit-compatible. WARPED stope geometry stays the explicit typed
     Phase 09 boundary (rule 75); STOPE_ACCESS crosscut terminals are the
     future anchors.

181. Verification tiers never weaken FULL (VA-01). Tests are FAST by
     default; heavy groups carry the registered markers `slow`, `golden`,
     `survey`, `e2e`, `legacy_regression`, `benchmark` (assigned centrally
     in `backend/tests/conftest.py` from explicit tables; `--strict-markers`
     rejects typos) and `canary` marks the representative clean-scenario
     detectors. FULL runs pytest UNFILTERED and proves
     `collected(FULL) == collected(unfiltered)` and
     `excludedFromFast ⊆ FULL` mechanically (`scripts/verify.py
     collect-full`, `tests/test_verification_tiers.py`). Session-shared
     upstream fixtures (`warped_301`, `warped_301_search`) are READ-ONLY
     (content fingerprint re-checked at teardown); a cached verification
     fixture (`backend/tests/fixtures/verification/`, generated only by
     `scripts/generate_verification_fixtures.py`, content-fingerprinted) is
     development acceleration, never release authority — FULL regenerates
     the artifact cleanly and a fingerprint mismatch is an explicit STALE
     VERIFICATION FIXTURE failure, never auto-rewritten. A FULL result is
     merge evidence only for the exact HEAD it ran on. Faster verification
     never changes a production threshold, golden expectation or hard gate.
     The guided-workflow browser e2e (`tests/test_shell_e2e.py`) is a
     REQUIRED release gate (`pytest-e2e`, `RELEASE_E2E_GATES`): the CI
     `full-e2e` component runs it under `MINEGEN_E2E_REQUIRED=1`, where a
     missing toolchain or browser FAILS instead of skipping and the gate
     refuses a run that executed nothing or skipped anything — a skipped
     e2e inside the unfiltered backend pytest is counted, never evidence,
     and `Release Authority` needs all three components.

182. Shaft = infrastructure primitive, never a layout family (Phase 20C.2B).
     `scenario.shafts.specs` declares explicit vertical shafts (empty =
     no shaft; every no-shaft artifact is unchanged and the ramp always
     coexists — shaft-only mines are out of scope). The backend plans them
     deterministically: collar plan position explicit or the documented
     default (`collarStandoff` beyond the footwall-most level-development
     extent along the away-from-ore direction through the target-level
     entry centroid — clear of every development by construction), collar
     elevation always from the terrain,
     one SHAFT_STATION per REQUIRED level (every listed level is required —
     one infeasible station fails the shaft), sump bottom. No placement
     optimization, no LLM-placed geometry; the frontend never derives shaft
     geometry (the Shafts card edits EXPLICIT `scenario.shafts` parameters
     only — "Suggest collar" copies the planner's own default from
     `POST …/design/shafts/suggest-collar` on click; applying is the rule 40
     scenario PUT behind the shared reset-plan confirmation). Hardening PR-2
     (H2-SH): the VERTICAL shaft excavation mesh is implemented —
     `derived/shaft_mesh.json` + `.glb`, a separate leaf artifact
     (`design/shaft_mesh.py`) swept from the shafts.json axis segments with
     ONE constant right-handed frame (right +X, up +Y, forward −Z — the
     gravity frame is undefined for a vertical tangent) through the Phase 06
     ring machinery: circular barrel (K = 2 × archSegments), collar + sump
     caps under the CAP–CAP closed-solid QA, the excavation envelope judged
     under `DesignContext.shaft` with the planner's own collar zone, one
     OPEN–OPEN station drive per level swept with the secondary profile
     through the Phase 20B development-mesh path; batched render primitives
     (SHAFT / SHAFT_STATION_ACCESS tubes whose `ranges` carry the shafts.json
     centerline ids with the rule-173 reveal metadata, SHAFT_COLLAR_CAP /
     SHAFT_SUMP_CAP). Lifecycle: inputs = shafts.json + its inputs, deleted
     with the shafts / levels / ramp chain, invalidates NOTHING, bound to
     `shaftsRevision` (409 SHAFT_MESH_STALE), typed FAILED (no GLB) for a
     FAILED plan or any topology / envelope defect. Inclined shafts /
     winzes, a parallel-transport frame and cage physics stay deferred
     (rule 26 reserves the parallel-transport frame).
183. Shaft geometry ownership and validation. `derived/shafts.json` is the
     ONLY owner of shaft axes, stations and station drives (one flat
     `centerlines` list; `GeometryRef{artifact, segmentIndex}` unchanged).
     A station drive is a straight, validated line from the axis to the
     EXISTING level node nearest in plan (LEVEL_ENTRY or drift breakpoint,
     welded through the network builder's breakpoint logic) — level
     geometry is never rebuilt and no new production crosscut is created.
     Axis and circular envelope pass the shared `DesignCostEvaluator`
     gates under `DesignContext.shaft` (permanent shaft: orebody
     penetration forbidden via the exclusion buffer; restricted zones and
     world bounds hard; terrain break-through only inside the collar zone;
     `minimum_surface_cover` not applied — a shaft breaks the surface by
     definition) under the ACTIVE ramp's clearance policy (rule 172).
     Failures are typed (`ShaftFailureCode`) and nothing is clamped.
184. Shaft lifecycle and network integration. levels → shafts → network:
     `levelsRevision` binds shafts.json to the levels it was planned on
     (409 SHAFTS_STALE fail-closed); regenerating levels deletes shafts,
     regenerating shafts deletes network / timeline / communication /
     sensors / capability graph, and nothing upstream. MineNetwork adds
     SHAFT_COLLAR / SHAFT_STATION / SHAFT_BOTTOM nodes, VERTICAL `SHAFT`
     edges (`orientation = VERTICAL`, null gradients, `verticalDrop`,
     CIRCULAR cross-section) and `SHAFT_STATION_ACCESS` edges; it
     references shafts.json and never owns the geometry. PORTAL ∪
     SHAFT_COLLAR is the surface set of the rule-70 advisory. The timeline
     sinks the shaft from the collar segment by segment and drives each
     station FROM the shaft once sinking reaches it (rule 174); level
     development stays ramp-rooted (rule 85). Communication / sensor
     domains treat both edge types as physical tunnel geometry; RAISE
     stays the only unsupported type.
185. GEOMETRY ≠ TOPOLOGY ≠ CAPABILITY, and capability ≠ capacity.
     `derived/capability_graph.json` references MineNetwork node / edge
     ids only (no geometry, no topology of its own). Every edge's
     capability set has an EXPLICIT source — the declared / default set per
     edge type (`scenario.capability`) or the owning shaft's declared
     `ShaftSpec.capabilities` (role-seeded, persisted resolved) — never
     inferred from geometry alone; node `supports` derive from incident
     edges. The graph is bound to `network.json`'s file revision (409
     CAPABILITY_GRAPH_STALE; network regeneration deletes it), validates
     references / duplicates, evaluates required capability paths (portal →
     level entries, collar → stations for shafts declaring personnel /
     haulage, one EMERGENCY_EGRESS route for every personnel-reachable
     underground node — unsatisfied = explicit FAILED) and reports the
     edge-disjoint egress advisory with no statutory or compliance claim
     (Phase 20D). `can_reach(source, target, capability)` reports physical
     and capability reachability separately. The five v0.1 capabilities are
     typed may / may-not tags; tonnes/hour, people/hour, airflow and hoist
     cycles are never modelled here.

186. Construction ServiceReference (Phase 20C.4 — "align the reference, not
     the threshold"). The layout-v2 ramp corridor and the level-development
     anchors share ONE spacing reference. A candidate's ore-facing corridor
     lateral is `footwall_edge(z)·n + footwallStandoff + delta(z)`, where
     `delta` (`layout/reference.py`, built once per search from the
     WORLD-policy offset traces stage 4 already caches under the token
     `"WORLD"`, trace interior only) is `max(0, support +
     RAMP_CORRIDOR_MARGIN_WIDTHS × width − current lateral)` over the
     reference points inside the ramp's OWN along-extent — SPIRAL: the rim
     `R` about the axis; SWITCHBACK: `leg/2 + R_min` about the shared leg
     centre, consumed through ONE vertical window DERIVED from the stacking
     mechanics (`switchback_corridor_profile`): `delta` is applied EXACTLY
     at every near-leg start (an outward step widens the away hairpin, an
     inward step is carried into the next toward hairpin; never below
     R_min), so the near leg starting at z sits at `legacy + delta(z)` and
     honours the ABSOLUTE requirement `support + margin` of every level
     inside `[z − drop − dz/2, z + dz/2]` (the planes its span occupies)
     with the legacy base subtracted — the track edge at z for a near-first
     stack, the ore-ward edge of `z ± drop` for a far-first stack whose
     first pair lags one cycle — no second band, no undeclared width (the
     pre-follow-up double ± 2·drop band folded into the interleaved edge
     drift is the recorded red-test evidence). The SPIRAL profile is
     piecewise-linear in z, constant beyond the levels; every profile is
     never negative: the corridor is only ever moved OUTWARD, an empty
     footprint is 0 (never a whole-trace fallback), and the lateral
     projection can only over-shoot the perpendicular need on an oblique
     backbone. It is a CONSERVATIVE
     CONSTRUCTION reference, not the candidate's stage-4 field: the REFINED
     candidate backbone never lies outward of it (dominance, tested against
     the section grid resolution). Inactive — `delta` exactly `0.0`,
     geometry bit-identical — on TABULAR (analytic path) and for an explicit
     `layout.footwallStandoff`; LONGITUDINAL is unchanged (deferred). No
     hard gate, threshold, score coefficient, screen semantic or
     access-planner authority changes with it: the access planner still
     decides service and typed failures stay typed. Every candidate reports
     `derived.corridorCorrection` and the search reports
     `performance.serviceReference`. Ramp ↔ level-drift proximity is
     measured by no gate (Gate C step 0 observation); a separation
     DIAGNOSTIC, never a gate, is a follow-up.

187. STATIC_FINAL walkthrough collision authority is the emitted excavation
     GLBs (Phase 20D.2). Ramp and development collision reuse the exact GLB
     triangle / index topology under the canonical mine→Three transform
     (`toThreePositions`, one authority): `walkthrough/tunnelRuntimeGeometry.ts`
     for `tunnel_mesh.glb`, `walkthrough/developmentRuntimeGeometry.ts` for
     `development_mesh.glb` — DEVELOPMENT tubes per kind with their
     validated `ranges` (contiguous, gap-free, in-bounds, triangle-aligned,
     unique piece ids, reveal metadata through the shared reader) and only
     the emitted `<KIND>_CAP` caps, one fixed trimesh per batched primitive,
     piece identity kept for a later time-aware activation. No centerline
     resweep, proxy tunnel, frontend junction reconstruction, invisible
     bridge / floor patch, collision-only geometry, body / gravity / autostep
     tuning or physics-material tuning is permitted: typed junction
     apertures are traversed exactly as emitted, an emitted cap is a real
     dead end and an OPEN endpoint gets no invented cap. Composition
     (`resolveWalkthroughComposition`): a missing / failed development
     artifact keeps the ramp-only walkthrough (rule 103 baseline); an
     advertised SUCCESS + meshUrl development GLB is mandatory and is loaded
     and validated BEFORE the physics world mounts — a contract violation
     fails the static walkthrough closed, never a silent ramp-only fallback.
     Walkthrough visibility is the AUTHORITY set, never an intersection with
     the stored layer toggles (`walkthroughAuthorityLayers`): exactly the
     excavation whose collision is mounted is shown (ramp always,
     development iff its physics is mounted), so "collider without
     geometry" and "toggle off → boundary gone" cannot occur. A drift end
     cap that a declared DRIFT_CROSSCUT junction occupies (a station on the
     drift extremity puts the crosscut axis IN the DRIFT_CAP plane; measured
     on the acceptance fixtures, every such cap obstructed the drift ↔
     crosscut traffic line) is cut by the same typed local rule as the
     child floor — inside-or-on fan triangles omitted, straddling fans
     clipped at the child envelope, `design/junctions.py::cut_cap` — so the
     end wall stays on the rock side and nothing stands inside the mouth;
     caps no junction reaches are bit-identical and crosscut faces are never
     cut. The same L-junction (20D.2.1, PR #42 review): a crosscut station
     on a drift EXTREMITY has the drift ending AT the station, so the half
     of the crosscut's OPEN start ring beyond the drift end would face
     unexcavated rock with no surface (measured: TABULAR 8 / 20 stations,
     WARPED-301 28 / 187; interior stations none). The backend closes it
     with the typed CHILD MOUTH CAP — `design/junctions.py::cut_mouth_cap`,
     the mirror of `cut_cap`: the child's start-ring cap fan judged against
     the PARENT envelope, inside-or-on fans omitted (the mouth stays OPEN
     into the drift), outside fans kept, straddling fans clipped at the
     drift boundary, emitted render-only as a `<KIND>_CAP` primitive with
     `junctionMouthCap` — for the typed DRIFT_CROSSCUT junction only. An
     interior T-junction (ring wholly inside its parent) gets nothing and
     stays bit-identical, crosscut faces are never touched, the logical
     mesh and the OPEN topology QA are unchanged, and no general Boolean is
     introduced; the walkthrough still adds no collider of its own.
     TIMELINE_SNAPSHOT keeps its ramp-only temporal collider contract
     (rules 112–118) and closes every RAMP_ACCESS aperture the ramp GLB
     declares with ephemeral wall-line barrier pieces on the active segments
     (`walkthrough/apertureBarrier.ts`, a rule 115 analogue: never persisted,
     never engineering geometry); apertures declared but not locatable from
     the authoritative level accesses fail the temporal session closed.
     Final development geometry never leaks into a snapshot and temporal
     branch traversal is deferred. Minimap, ramp-chainage teleport, branch
     teleport / routing and branch infrastructure interaction are unchanged
     / later scope.

188. RAMP_ACCESS vertical continuity (Phase 20B.x). A level-access branch leaves
     the main ramp INSIDE the ramp's own floor, so its vertical profile is
     assigned on the delivered stations in two regimes, one geometric rule
     for every orebody type and family
     (`layout/access.py::ramp_follow_vertical`): RAMP-FLOOR FOLLOW — while
     the branch centerline is closer than one tunnel width (plan) to the
     ramp centerline and its projection is interior to the ramp, each
     station takes the ramp floor elevation beneath it (the nearest ramp
     centerline point's elevation; the gravity-aligned ramp floor is
     horizontal across its width; the nearest-point query is restricted
     to the junction's own ramp run, `[junction − width, junction +
     2·taper + width]`, because a SPIRAL stacks its turns on one plan
     circle) — then a parabolic VERTICAL CURVE of `VERTICAL_CURVE_K × |Δg|`
     metres (K = 100 m per unit grade difference: at most 1 % grade change
     per metre, so the 3-D ring turn of a minimum-radius turnout stays
     inside the sweep's 7° faceting contract; closed form
     `vertical_curve_tail`, whole-tail parabola when the tail is shorter)
     and a CONSTANT TAIL to the EXACT entry. The junction, the entry, every plan
     sample, the ramp centerline and the level / drift / crosscut topology
     are unchanged (only interior z moves); the hard gradient gate judges
     the MAXIMUM delivered edge gradient and nothing is clamped or relaxed:
     a level whose access can no longer reach the entry inside `g_max`
     once the branch starts ON the ramp floor is a typed GRADE_LIMIT (the
     old feasibility of such a level was the unphysical floor step itself
     — measured on the GEOMETRY-STRESS golden, whose old winner served 9
     such levels; its gradient-passing alternatives fail the rock pillar).
     No level-id, family or orebody-type branch, and no
     `max(ramp_z, access_z)` render patch: the persisted branch IS the
     surface. Honesty bound: an un-banked branch profile can coincide with
     the inclined ramp floor only along ONE curve — it is matched along the
     traffic centerline (seam step 0 at the hand-off), while the retained
     child floor beyond the ramp wall sits above the ramp floor by
     `g·(λ − w/2)·tan φ` (0 where the centerline crosses the wall, ≈ 0.2 m
     at the far end of the opening for a 12 % ramp, R = 18 m, w = 5 m);
     an exact wall-line match needs `g·(sec φ + (λ − w/2)/(R cos² φ))`,
     above `g_max` past φ ≈ 20°, so the gradient gate forbids it by
     construction. A banked junction floor is Phase 20D (unified
     development mesh) scope; the 20D.1.2 child-floor clipping is neither
     relaxed nor replaced by this rule.

189. Design assessment is a READ-ONLY projection (Phase 20D.3). The design
     assessment (`assessment/`, `GET …/design/assessment`) projects existing
     authoritative results — the layout-v2 catalogue (ranking, statuses,
     scores), the selection, the active ramp source and the capability
     graph (required capability paths, egress advisory) — into typed
     engineering checks and a candidate comparison, computed per request
     from ONE validated snapshot and persisted nowhere (no
     `design_assessment.json`). It never creates geometry, changes
     feasibility, re-ranks candidates, recomputes a score, generates a
     missing artifact or infers a missing fact: an absent selection /
     capability graph makes the dependent checks NOT_EVALUATED (never a
     pass), and a STALE or MALFORMED artifact raises its own typed refusal
     through the validated reader (LAYOUT_V2_SELECTION_STALE,
     CAPABILITY_GRAPH_STALE, ARTIFACT_MALFORMED — never a fallback). READ ≠
     TRUST holds at the assessment's OWN boundary too: every catalogue field
     the projection consumes is validated once with its JSON path
     (`assessment/builder.py::validate_catalogue_shape`) and a structural
     defect the shared reader precondition cannot see — a missing
     candidateId / requiredLevels, a malformed scores block, a ranking that
     names an unknown, unscored or non-FEASIBLE candidate, a duplicated id —
     is refused as 409 ARTIFACT_MALFORMED, never a bare 500; legitimate
     engineering states (NO_FEASIBLE_CANDIDATE, INFEASIBLE / NOT_VALIDATED
     rows, permitted null optional blocks) are never shape errors. The
     ACTIVE ramp source is resolved from the same snapshot FIRST: under
     LAYOUT_V2 the catalogue is required (absent → LAYOUT_V2_NOT_GENERATED);
     under LEGACY it is optional — a LEGACY-only design keeps its generic
     network / capability / egress assessment (`layoutScope = NONE`, layout
     checks NOT_APPLICABLE, comparison empty) and a dormant catalogue /
     selection is reported with explicit `INACTIVE_LAYOUT_V2` scope
     (`activeDesignCandidateId` null), never as the active design. Candidate comparison preserves
     the Layout V2 ranking and scores exactly (rows = the winner + the top
     FEASIBLE alternatives in `ranking` order, bounded, the selection always
     a row; INFEASIBLE / NOT_VALIDATED are never alternatives; deltas are
     plain `candidate − winner` subtraction). Every check declares its
     authority — HARD_DESIGN_RULE, DERIVED_VALIDATION, ADVISORY or
     INFORMATIONAL — and physical / capability reachability of a required
     path stay two separate recorded facts (rule 185). Dual-egress remains
     an explicitly labelled DESIGN ADVISORY derived from the capability-graph
     authority: no LEGAL / REGULATORY / STATUTORY COMPLIANCE, CERTIFIED,
     SAFE or UNSAFE wording anywhere in the payload or the UI, and a
     satisfied advisory is never rendered as a certification badge. Economic
     quantities (cost, NPV, travel time, capacity, ventilation demand) are
     never estimated here (Phase 22 / external).

190. MineExchange is a versioned, read-only projection of existing
     authoritative MineGen state (Phase 23A, `exchange/`,
     `POST …/export/mine-exchange`, `docs/mine-exchange.md`). It never
     redesigns the mine, changes ranking, invents engineering semantics,
     or promotes a derived representation into a stronger authority.
     Geometry, topology and capability remain separate. Every exported
     file declares its coordinate frame, units, provenance and
     representation semantics; individual excavation STL bodies are
     closed but not boolean-unioned. The bundle is built from ONE
     validated snapshot (READ_SNAPSHOT_CHANGED on drift), is
     deterministic (same snapshot → same bytes), is never a persisted
     derived artifact, and reuses the production sweep helpers
     (`ramp_logical_sweep`, `closed_sweep`) rather than a second
     geometry algorithm; absent optional artifacts are manifest
     omissions (ARTIFACT_ABSENT), present-but-FAILED optional artifacts
     are explicit SOURCE_NOT_SUCCESS omissions, present STALE / MALFORMED
     artifacts are typed refusals, and a mandatory entity failing its
     closed-solid QA fails the whole export. Every network geometryRef is
     resolved through the canonical `resolve_owning_centerline` (per edge
     type; RAISE alone carries no owning contract and any other unknown
     type fails closed) and verified against the exported entities;
     aggregate entities list `sourceMemberIds` (synthetic ramp / drift
     aggregates carry `sourceId = null`, the authoritative shaft aggregate
     carries its `shaftId`) and a shaft aggregate owns no geometry
     (centerlines only); file stems are collision-resistant (sanitized id +
     short hash) with final uniqueness enforced by the bundle preflight,
     which refuses duplicate ids / paths and dangling references; a copied
     GLB's `junctionApertures` reflects aperture OUTCOMES (opened endpoints /
     removed triangles), never the mere existence of junctions; every
     projection defect is a typed 409 MINE_EXCHANGE_EXPORT_FAILED, never a
     bare 500 or a silent null.

191. Guided workflow shell (hardening H1 §4, replaces the Phase 20E left-
     panel structure; its principles are inherited). ORDER IS THE SCREEN:
     the ribbon lists the seven steps `1 Setup · 2 Design · 3 Network ·
     4 Mining · 5 Systems · 6 Analysis · 7 Export`, the stepper under it
     lists every stage (`Scenario · Method | Layout · Levels · Excavation ·
     Shafts | Network · Capability | Production · Schedule | Communication
     · Sensors | Analysis | Export`) with one glyph each (✓ done · ● next ·
     ○ waiting · ✗ failed · ↻ running · – optional), and at most ONE stage
     is NEXT: the first stage whose prerequisite is done (Excavation waits
     for Levels; Analysis follows the last Systems stage and Export follows
     Analysis, so the guided flow has no dead end); when a FAILED stage
     blocks the chain no stage is NEXT and the failed stage is the focus.
     Analysis and Export own no artifact and are completed by the viewer —
     Analysis once its centre workspace was actually SHOWN (mounted over a
     scene; a stage click alone never completes it, and opening it from a
     4D / Walk view leaves that view explicitly), Export once a package was
     downloaded — BOUND to the scene revision they were made on
     (`scenarioStore.sceneRevision`, advanced by every accepted scene
     write): a completion of another revision counts for nothing, so a
     reset or regeneration never revives an old ✓; counted only while their
     prerequisite chain is done. The glyph is a presentation of the
     artifact the stage owns (`StatusBadge` semantics — the backend status,
     no new vocabulary); a stage hosting several cards aggregates their
     reported tones per card instance (RUNNING wins, no overwrite);
     nothing in the shell decides whether an action is ENABLED, every
     feature keeps its own prerequisite logic. Three panes: CONTROLS (left)
     holds the current stage's parameters and its ONE primary action plus
     "Reset from here"; STATUS & RESULTS (right) holds the current step's
     stage statuses, key metrics, backend `failureReason` and `Details ▸`,
     above the VIEW panel (camera presets, Visibility tree, field slice —
     viewer-local) and the Inspector; the status bar holds the World ·
     Ramp · Levels · Network · Timeline chips and the 4D control in the 4D
     view. At most one enabled primary button exists in the DOM at any
     time (`button[data-variant="primary"]`, e2e-asserted). `3D | 4D |
     Walk` are VIEW modes of the viewport (a switcher over the canvas,
     never ribbon steps; Walk keeps its readiness gate and its entry
     semantics, rules 111–118); Analysis is a centre workspace, never a
     column. Setup = Scenario ("Create mine" = create + world in one step;
     Randomize and Advanced are secondary; saved mines under File › Open)
     then Method (decided BEFORE the layout; a later change is the rule 40
     scenario PUT behind a confirmation that lists the backend
     `reset-plan?from=WORLD` verbatim). Layout candidates read "Option n"
     in rank order; the candidate id, family parameters and scores stay in
     Details (rule 142 enumeration unchanged). Export is reachable from the
     ribbon AND File › Export — two paths, one implementation; File › Import
     results opens Analysis › Simulation Results. Every staged card keeps
     the `title + ⓘ` / status / key metrics / action / `Details ▸` layout:
     status, key metrics and any backend `failureReason` are ALWAYS visible,
     technical explanations live in the ⓘ popover (a portal with viewport
     clamp, never a control inside it, never hover-only), only legacy or
     diagnostic controls live in `Advanced`, and implementation-phase and
     rule numbers stay out of user-facing copy. A stage change is a
     presentation event: stage and tab identity are frontend-local viewer
     state, never persisted to a scenario, and perform no generation,
     mutation, regeneration or layer reset — every feature panel stays
     MOUNTED in one container (its cards render into the two columns
     through portals, `CardLayoutContext`), so each job poll, query and
     effect keeps its lifetime. The API, DTOs, artifacts, invalidation
     chain, geometry and goldens are untouched by the shell.

192. Mining-method registry is the single dispatch authority (Phase 21A).
     `mining/methods/registry.py::plan_for(method)` resolves EVERY
     `MiningMethodType` member explicitly to a `MiningMethodPlan`
     (`methods/contracts.py`): `LongholeOpenStopingPlan` (IMPLEMENTED) or an
     `UnsupportedMethodPlan` (UNSUPPORTED_METHOD) — never `None`, never a
     silent fallback to longhole geometry, an unregistered member a typed
     `UnknownMiningMethodError`. The plan owns WHAT: the declarative
     production-development intent (`production_development`), the station
     lattice (`ProductionLattice(pitch = stope_length + minimum_pillar,
     margin = stope_length / 2 + minimum_pillar)`, `None` for a method
     without production development) and production generation
     (`generate_production`). Level development
     (`levels/builder.py::LevelDevelopmentBuilder`) consumes that intent and
     owns WHERE and validity (anchors, backbone, hard validation); it never
     tests the method itself, and `services/design_service.py` dispatches
     stope generation only through `plan_for`. Geometry ownership is
     unchanged: `levels.json` owns level / production development,
     `stopes.json` owns stope prisms; no `mining_method_plan.json` exists and
     `Stope.method` stays the `LONGHOLE_OPEN_STOPING` literal. Reserved
     methods (CUT_AND_FILL, ROOM_AND_PILLAR, SUBLEVEL_CAVING,
     SHRINKAGE_STOPING) receive the generic footwall backbone, a typed
     `productionDevelopment.status = UNSUPPORTED_METHOD` and a FAILED
     `stopes.json` with the rule 78 reason — explicitly, never longhole
     geometry under another name; a new method enters ONLY as its own
     registered plan. The longhole algorithm is a migration target, never
     rewritten: its `levels.json` / `stopes.json` outputs match the
     committed pre-migration parity fixture
     (`tests/fixtures/phase21a/longhole_parity.json`, captured on the pinned
     HEAD, `tests/test_mining_method_parity.py`) under a TWO-TIER gate —
     HARD: status, method, ids, counts, station indices, ordering, topology
     and every string / int / bool exact; NUMERIC: lengths, coordinates,
     volumes, tonnes, grade within 1e-10 (relative and absolute), orders
     below any engineering resolution and above the measured cross-CI-runner
     last-digit float noise (≈ 3e-13); the full canonical-JSON digests are
     an ADVISORY record, never a gate — and goldens are unchanged. A
     longhole golden or parity change under this rule is BLOCKING, never
     regenerated and never absorbed by widening the tolerance.
     MineExchange 1.1 PROJECTS the method and the stopes, it never creates
     them: `semantics/mining_method.json` (registry status, always present),
     `production/stopes.json` + one authoritative closed prism per stope with
     independent QA, the `STOPE` entity kind, STOPES `ARTIFACT_ABSENT` /
     `SOURCE_NOT_SUCCESS` omissions (TIMELINE stays NOT_IN_V1), and a typed
     refusal when the scenario, `levels.json` and `stopes.json` method
     authorities disagree. The frontend renders the registry's status
     read-only (Mining method card, export contents rows) and offers no
     method selector: an unsupported method is a feature boundary, not a
     mine failure.

193. Cut & Fill and Room & Pillar are first-class registered methods
     (Phase 21B/C). The registry table is LONGHOLE_OPEN_STOPING IMPLEMENTED,
     CUT_AND_FILL IMPLEMENTED (`methods/cut_fill.py::CutFillPlan`),
     ROOM_AND_PILLAR IMPLEMENTED (`methods/room_pillar.py::RoomPillarPlan`),
     SUBLEVEL_CAVING / SHRINKAGE_STOPING UNSUPPORTED_METHOD. `plan_for` stays
     the ONLY method authority: the level builder consumes the plan's
     `production_access_pattern()` (a `StationLatticeAccessPattern` for
     Longhole — the exact Phase 08 arithmetic — or a `FixedAccessPattern`
     with one central production CROSSCUT per level at offset 0 for Cut &
     Fill / Room & Pillar; `None` for reserved methods), the timeline
     builder consumes `production_identity()` / `production_schedule()`, the
     scene projects `mining_method_summary` and MineExchange dispatches on
     the TYPED payload class; no `if method ==` branch exists in levels,
     DesignService, scheduling, scene or exchange (the source scan in
     `tests/test_mining_method_registry.py` is the gate). The new methods are
     NEW implementations (`methods/solids.py` shared prism helpers): the
     longhole algorithm is untouched and its `levels.json`, `stopes.json`,
     `network.json` and `timeline.json` outputs are proven unchanged against
     `tests/fixtures/phase21bc/longhole_baseline.json` (captured on the
     pinned pre-migration HEAD 7052606 by
     `scripts/phase21bc_capture_baseline.py`, which refuses any other HEAD;
     `tests/test_longhole_baseline_21bc.py`, two-tier gate of rule 192;
     the ONE classified cross-runner artefact is a sampled `pointCount` /
     `fractionCount` flipping by exactly one where a piece's
     `length3d / SAMPLE_SPACING` sits within 1e-9 of an integer — measured
     on PR #47 CI, recorded as a test property, never widened) —
     a Longhole change under this rule is BLOCKING, never regenerated. The
     rule 192 parity fixture is never regenerated either; its CUT_AND_FILL
     case is a historical record of the reserved boundary, explicitly
     superseded by `tests/test_mining_method_parity.py`.
194. ONE active production artifact, method-typed. `derived/stopes.json` is
     the legacy PATH of the active production artifact for every method
     (documented compatibility; no `cut_fill.json` / `room_pillar.json`,
     no second registry key). Its payload is the discriminated union
     `ProductionPayload = StopesPayload | CutFillPayload |
     RoomPillarPayload` (`mining/models.py::parse_production_payload`, by
     `method`); `Stope.method` keeps its Longhole literal and Cut & Fill /
     Room & Pillar geometry never enters the `Stope` model. The
     `ArtifactReader` parses it through the generic `ReadSpec.parser`
     (structural only; READ ≠ TRUST). `POST/GET …/design/production` is the
     method-generic route; `…/design/stopes` stays the Longhole-only route
     and answers 409 PRODUCTION_METHOD_MISMATCH for any other active
     method. `MiningConfig.methodParameters` is the typed union
     `CutFillParameters | RoomPillarParameters` (canonical defaults resolve
     when omitted, a block for a method without one is 422, a mismatched
     kind is 422; omitted from serialization for Longhole so its document is
     unchanged). Cut & Fill lifts / cuts and Room & Pillar bands are EQUAL
     PARTITIONS (`n = ceil(span / target)`, `actual = span / n`) — never a
     residual sliver. A production count above `MAX_PRODUCTION_SOLIDS`
     (8000, measured: default-scenario Room & Pillar 7,322) is the typed
     PRODUCTION_COMPLEXITY_LIMIT failure, never a silent decimation.
195. Cut & Fill / Room & Pillar geometry contract. Both are TABULAR-only in
     v0.1: any other orebody is the typed METHOD_GEOMETRY_NOT_IMPLEMENTED
     failure, never a fallback. Cut & Fill (hardening PR-2 H2-CF block /
     panel structure): the strike extent is partitioned equally into PANELS
     of ≈ `panelLengthM` (rule 194 partition, default 60 m) with one
     production access CROSSCUT per panel and level (`PanelAccessPattern`,
     station index = panel index); a level interval is a stope BLOCK and
     block × panel is the schedule unit; inside it lifts partition the
     interval to ≈ `liftHeightM` VERTICAL (dip-aware, `dv = liftHeight /
     |v_z|`) and cuts partition the panel's MINED span to ≈ `cutLengthM`,
     OVERHAND lifts bottom → top and cuts along strike in a snake (even
     lifts-in-block −u → +u, odd +u → −u). `ribPillarWidthM` > 0 carves
     RETAINED rib pillars out of the panel partition (the Room & Pillar
     PILLAR semantics: geometry + `tonnesEquivalent`, never scheduled,
     never planned tonnes; 0 = none). Under `blockOrder = SHALLOW_TO_DEEP`
     the bottom lift of every block mined above an unmined block is a
     CEMENTED sill mat (`backfill.cemented = true`); every other fill is
     plain. Every cut is an 8-corner prism under the Phase 09 hard QA
     (closed solid, volume agreement, hard samples, finite) with the rule
     130 grade proxy; backfills are 1:1 SEMANTIC records referencing
     `sourceCutId` (no duplicate geometry: the backfill IS the cut void);
     the payload carries `sequencing` (resolved assumptions + the
     deterministic block / panel start orders), `blocks[]`, `panels[]`,
     `ribPillars[]`, per-cut `blockId / panelId / liftIndexInBlock`, and
     `integrity.py` re-verifies block / panel / cemented / start-order
     relations (READ ≠ TRUST); no partial SUCCESS. Panel length, rib
     pillar, concurrency and cure are registry canonical PLANNING defaults
     (never fill-strength, binder or geotechnical values). Room & Pillar:
     alternating room / pillar bands along u and v with pitch `roomWidth +
     pillarWidth`, u = 0 / v = 0 a ROOM band, the panel inset by
     `boundaryPillarM`, a cell is ROOM iff its u-band OR v-band is a room
     band, else PILLAR; non-overlapping cells; a `RoomCell` is a semantic
     parent (no geometry) of its extraction units HEADING / BENCH_1 /
     BENCH_2 (a heading ≥ thickness → one HEADING); pillars are retained
     material with geometry and `tonnesEquivalent`, never scheduled and
     never a geotechnical design or certification — every suitability text
     is advisory. Volume / tonnes / grade proxy stay planning quantities.
196. Plan-driven production schedule; Longhole timeline unchanged. The
     timeline builder keeps the development schedule and executes the
     plan's `ProductionScheduleSpec` (tasks with transparent `TaskBasis`
     from `scenario.schedule` rates, per-unit state transitions bound to
     task boundaries, `tasks_per_unit` aggregate contract); the Longhole
     spec is the Phase 10 stope chain moved VERBATIM (ids, order, bases,
     dependencies, states — bytes unchanged, rule 193 gate). Cut & Fill
     (hardening PR-2 H2-CF — two declared sequencing axes, valid
     combinations only): `stopingDirection ∈ {OVERHAND, UNDERHAND}` ×
     `blockOrder ∈ {SHALLOW_TO_DEEP, DEEP_TO_SHALLOW}`; OVERHAND +
     SHALLOW_TO_DEEP (default, cemented sill mats) and OVERHAND +
     DEEP_TO_SHALLOW (no sill mat needed) are implemented, UNDERHAND is a
     schema-valid axis that production generation AND the schedule refuse
     with the typed UNSUPPORTED_STOPING_DIRECTION failure — never a silent
     fallback to OVERHAND, and "top-down / bottom-up" vocabulary appears
     nowhere in code or UI. The schedule is EXPLICIT PRECEDENCE (rule 82,
     never a resource solver): PREP → STOPING → MUCKING → BACKFILL → CURE
     per cut, cuts serial INSIDE a panel (previous CURE → next PREP, lifts
     bottom → top, snake), every PREP after the panel's own production
     access crosscut on the lower level (hence, through the development DAG,
     the level drift, the level access and the ramp reaching that
     junction); panel k + N starts after panel k's last CURE
     (N = `maxConcurrentPanels`, default 2; global start order = block
     order, then centre-out with the −u tie-break); vertical gates per
     panel index — SHALLOW_TO_DEEP: the lower block's TOP lift waits for
     every cemented sill-mat CURE of the block above; DEEP_TO_SHALLOW: a
     block's bottom lift waits for the last CURE of the block below; a
     cemented fill cures for `sillMatCureDays` (default 28), every other
     fill for `schedule.backfillCureDays`; rib pillars receive no task;
     states PLANNED → ACTIVE → MINED → VOID → BACKFILLED, `targetKind =
     CUT`. Measured on the small scenario (`docs/findings/h2cf-cut-fill-
     characterization.md`): first STOPING day 404.45 → 298.18 against ramp
     completion 371.46, max open cuts 1 → 2, end day 5204.5 → 3293.7,
     volume / tonnes unchanged — the C&F fixture is an INTENTIONAL
     regeneration with that comparison record; the Longhole baseline is
     byte-identical (BLOCKING). Room & Pillar:
     PREP → STOPING → MUCKING per extraction unit, HEADING → BENCH_1 →
     BENCH_2 inside a cell, cells outward from the central cell by
     Manhattan index distance then row then column, a single front (next
     unit after the previous MUCKING), states PLANNED → ACTIVE → MINED →
     VOID, `targetKind = ROOM_EXTRACTION`, pillars never scheduled. The
     payload carries the generic `production {method, targetKind, units}`
     block and `production*` metrics ONLY for a non-Longhole method; the
     Longhole payload keeps `stopes` and gains no null field. The frontend
     renders both blocks through one adapter (`scene/production.ts`) and
     computes no state itself. MineExchange 1.2.0 (additive): typed method
     parameter DTOs, `production/cut_fill.json` + `cut_fill/cuts/<id>.*`
     (CUT solids, BACKFILL semantic entities without geometry files),
     `production/room_pillar.json` + `room_pillar/{benches,pillars}/<id>.*`
     (ROOM semantic parents, BENCH and PILLAR solids), exactly ONE
     production omission group per bundle (STOPES / CUT_FILL / ROOM_PILLAR
     — the active method's), the authority guard extended to the payload
     SHAPE (a Longhole-shaped document under a Cut & Fill scenario is a
     typed 409) and the rule 192 crosscut guard now applying to reserved
     methods only. The frontend method card edits explicit parameters only
     (defaults from the registry table in the scene, never a client
     constant); applying is the scenario PUT (rule 40 full invalidation)
     followed by world regeneration from the same seed (rule 119). Not
     implemented: Sublevel Caving, Shrinkage Stoping, WARPED_VEIN
     production geometry, production-room walkthrough colliders, any
     geotechnical pillar design.

     PR #47 review round (binding): (a) READ ≠ TRUST at the SCHEDULE too —
     `production_schedule` verifies the method-specific SEMANTIC integrity
     of the persisted payload at its entry (`mining/methods/integrity.py`:
     unique cut / backfill ids, exactly one backfill per cut with a
     bijective `sourceCutId`, backfill volume == cut volume; unique room /
     extraction-unit / pillar ids and an EXACT two-way `RoomCell.
     extractionUnitIds` ↔ `ExtractionUnit.roomId` membership) and a
     violation is a typed FAILED timeline — the plan never invents a task
     from the surviving half of a relation and a duplicate id is never a
     silent dict overwrite. (b) A scenario PUT under the same id is a new
     scenario REVISION for the frontend: `activateScenarioRevision` ALWAYS
     advances the epoch and clears the scene, the in-flight job ids, the
     slice, the 4D cursor and the scenario-scoped viewer state, so a result
     computed for the previous revision is dropped; plain re-selection of
     the same id stays a refresh. (c) The method card's draft is scoped to
     the scenario revision identity (`scenarioId:epoch`,
     `reconcileMiningDraft`): a pending, unapplied edit never survives a
     scenario switch or a document replacement. (d) Production RENDERING
     is batched (`scene/productionBatches.ts`, `mergeSolids`): one merged
     geometry + one material per (kind, validity) in the static layer and
     per visual state (plus RETAINED pillars) in 4D — a concatenation of
     the persisted triangles with offset indices, never new geometry
     (measured on the default 7,322-solid Room & Pillar: 14,797 → 157 draw
     calls per frame in Design, 14,744 → 106 in 4D). The 4D merged
     geometries are keyed by the STATE REVISION (`stateRevisionAt` over the
     sorted transition days: membership is constant between two transition
     days), so a playback frame that crosses no transition rebuilds nothing,
     and every replaced or unmounted merged geometry is `dispose()`d —
     never a per-animation-frame rebuild, never a leaked buffer. (e) A reserved method
     has `productionKind = null` in the scene (never STOPES): the card
     edits the shared sublevel interval only and the Production action
     reads "Not implemented" and stays disabled. (f) MineExchange refuses a
     ragged / non-numeric flat coordinate list as a typed export error
     before any `reshape` (never a bare NumPy ValueError → 500).

197. Mine analysis is a READ-ONLY downstream projection (Phase 22A,
     `analysis/`, `GET …/analysis`). Its authorities are the persisted
     artifacts — `scenario.json`, `network.json` (development), the active
     production artifact `stopes.json`, `timeline.json` — read through the
     validated `ArtifactReader` from ONE snapshot: the scenario document is
     the bound read (`ScenarioStore.get_bound`, stat → get → re-stat — the
     same protocol `WorldService` uses, never a second implementation) and
     the artifact snapshot is taken with `expect_scenario_revision` = that
     revision, so the document object and every observation are one
     revision (a same-id PUT in between is READ_SNAPSHOT_CHANGED, never an
     old document projected beside new artifacts); the whole consumed set —
     scenario, arrays, the world commit record, the three artifacts and
     `economics.json` — is re-observed after the projection
     (READ_SNAPSHOT_CHANGED on any movement). It never generates, regenerates, repairs or persists a mine
     artifact (no `derived/analysis.json`), runs synchronously (no job) and
     re-verifies every cross-artifact relation it derives a number from
     (unique ids, endpoints, finite positive lengths / areas, declared
     `NetworkMetrics` ↔ edge sums, persisted production `metrics` ↔ the
     entity records (counts, level intervals, lift partition, volumes,
     tonnes, weighted grade proxy, extraction fraction), timeline targets ↔
     edges / production objects, scenario ↔ production ↔ timeline method,
     task basis ↔ geometric quantity — STOPING / MUCKING tonnes AND the
     BACKFILL volume): a disagreement is the typed 409
     ANALYSIS_SOURCE_INCONSISTENT,
     a present unusable document ARTIFACT_MALFORMED, never a bare 500. An
     ABSENT or FAILED source is a NORMAL partial 200 — the section reads
     NOT_AVAILABLE with the backend reason. A SUCCESS timeline whose network
     or production owner is absent is inconsistent, not partial.
198. Tonnage authority. "Planned mined tonnes" come ONLY from production
     geometry (stope / cut / extraction-unit solids × density, the persisted
     `tonnes`); pillars are retained material and backfill is a semantic
     record — both reported separately, never production. No resource /
     reserve / recoverable tonnage is ever derived from the orebody, and the
     words reserve, resource, recoverable, proven, economic grade and
     optimized schedule appear nowhere in the analysis payload or UI. The
     development volume is `Σ length3d × analyticArea`, named GROSS
     (junction overlap is not unioned); the declared network metrics are
     cross-checked, never overwritten.
199. Grade is never a revenue authority. `weightedMeanGradeProxy` is the
     tonnage-weighted Phase 09 planning proxy, informational only; the ONE
     v0.1 revenue model is `plannedMinedTonnes × grossRevenuePerMinedTonne`
     (`revenueModel = GROSS_REVENUE_PER_MINED_TONNE`). No metal price,
     recovery, payability, smelter charge, grade unit or commodity exists.
200. `economics.json` is a user-authored assumption document beside
     `scenario.json` (`data/scenarios/{id}/economics.json`), NEVER a derived
     artifact: it has no registry entry, no fingerprint role and no cascade —
     writing it (`PUT …/analysis/economics-config`, validated → atomic
     publication → `sha256(canonical JSON)` revision, no timestamp) leaves
     every mine artifact byte- and stat-identical, and a scenario PUT does
     not delete it. No scenario field carries an economic assumption and no
     hidden default exists: an absent document is NOT_CONFIGURED, the
     frontend's "Use demo assumptions" fills the editor only on an explicit
     click and is labelled DEMO / SYNTHETIC ASSUMPTIONS. An economics change
     is not a viewer revision (no epoch bump, no scene clear); the editor
     draft is scoped to `scenarioId:economicsRevision`.
201. Planning economics status. Every economics payload carries the fixed
     disclaimer "Synthetic planning economics. Not a resource/reserve
     estimate or feasibility study." and the names are "Planning Cashflow"
     and "Baseline Planning NPV" — never feasibility, bankable, investment,
     optimized, certified or statutory wording. Economics is AVAILABLE only
     when the config AND development AND production AND schedule are
     available (NOT_CONFIGURED / SOURCE_NOT_AVAILABLE otherwise); an NPV is
     never produced without a timeline. Hardening PR-2 (H3 §8): the
     economics payload carries the TYPED "Planning IRR" (`planningIrr`,
     `analysis/irr.py`) — the annual rate under EXACTLY the Baseline
     Planning NPV timing (mid-bucket, `midDay / 365.25`), deterministic
     bisection on the bounded bracket [−0.99, 10]; DEFINED only when the
     bucket net cashflows change sign exactly once AND the NPV function has
     a root in the bracket, otherwise NOT_DEFINED with the reason
     NO_SIGN_CHANGE | MULTIPLE_SIGN_CHANGES, or NOT_CONFIGURED; never NaN /
     Infinity (rule 34), never a bankable or feasibility figure. The
     read-only sensitivity grid (`GET …/analysis/sensitivity`, nine declared
     parameters — gross revenue per mined tonne, development / mining /
     processing / backfill cost, initial capital, discount rate (economic:
     the Planning Cashflow ledger is rescaled) and development / mining
     rate (schedule: `MineTimelineBuilder` is rerun IN MEMORY on the bound
     artifacts) — at ±10 / 20 / 30 % by default) and the explicit what-if
     (`POST …/analysis/what-if`, one multiplicative factor per parameter)
     are projections: nothing is persisted, timeline.json / economics.json
     are never modified, no job runs, no optimizer exists, and every
     outcome (Planning NPV, Planning IRR, mine duration, first production
     day, deltas) carries the label "WHAT-IF OVERRIDE — NOT SCENARIO VALUE".
     The revenue authority is still exactly "Gross revenue per mined tonne":
     no metal price, grade, recovery, payability, royalty, tax,
     depreciation or inflation model exists, and only the ACTIVE design is
     analysed (no candidate what-if). The Analysis workspace is
     full-window (ANALYSIS mode unmounts the canvas; "Show 3D context" is an
     explicit split view), heads every tab (Overview · Economics ·
     Sensitivity · Schedule · Rules · Layouts · Simulation Results) with the
     Planning NPV / Planning IRR / mine life / first production KPI tiles,
     renders the cashflow and cost charts from backend buckets (Recharts,
     presentation only — a missing value is never converted to zero), and
     keeps the PR #53 completion rule (shown workspace, bound to the scene
     revision).
202. Geometry is the quantity authority, the timeline the timing authority
     (Phase 22B). Development cost = `length3d × rate(edge type)` spread
     linearly over the edge's development task (`basis.quantity ≈ length3d`,
     unit "m", verified) — every `EdgeType` member has a rate, RAISE
     included, so a typed edge is priced and never refused; production mining cost = tonnes × the ACTIVE
     method's rate over STOPING, processing cost and gross revenue over
     MUCKING, Cut & Fill backfill cost = backfill volume × rate over BACKFILL
     (0 for every other method); PREP / CURE carry nothing; fixed operating
     cost = mineDurationDays × rate linear over `[startDay, endDay]`; initial
     capital in bucket 0. Buckets are fixed `cashflowBucketDays` intervals
     from day 0 (the last one closed at the mine end), amounts allocated by
     overlap fraction, a zero-length interval a point event; `net = revenue −
     Σ costs`, cumulative running, `npv = Σ net / (1 + annualRate)^(midDay /
     365.25)` (MID_BUCKET_MIDPOINT — rate 0 ⇒ NPV = undiscounted net). Bucket
     columns reconcile exactly with the summary; the summary's `totalCost`
     is the sum of its six components. Every check is deterministic (same
     state + config → identical JSON).

203. Design Rulebook authority (Phase 22C). The Rules tab is a PRESENTATION
     of the Phase 20D.3 design assessment (`GET …/design/assessment`, rule
     189): it consumes the existing `DesignAssessmentPayload` and renders
     every check with its recorded status, authority and scope. No second
     rule evaluator exists (no `analysis/rule_engine.py`,
     `compliance_engine.py` or `rulebook_engine.py`, no client-side rule
     logic). HARD_DESIGN_RULE / DERIVED_VALIDATION show ✓ SATISFIED /
     ✗ NOT SATISFIED / ? NOT EVALUATED / — NOT APPLICABLE verbatim; an
     ADVISORY is "Advisory satisfied / not satisfied" with "Design advisory —
     not a statutory compliance determination" and never the ✓ pass mark; an
     INFORMATIONAL row has no pass / fail; NOT_EVALUATED is never coerced
     to a failure; no overall compliance score, percentage, "compliant" or
     certification exists. A LEGACY-active scenario with a dormant catalogue
     is labelled INACTIVE_LAYOUT_V2, never the active design.
204. Candidate economics use ONLY persisted candidate quantities (Phase 22C,
     `analysis/layout_comparison.py`). `mainRampLengthM` is
     `layout_v2.json candidates[].diagnostics.length3d` and
     `levelAccessLengthM` is `candidates[].access.totalAccessLength`; the
     backend never re-sweeps, re-sums a centerline or re-plans, and the
     frontend never sums a centerline or derives a cost. No per-candidate
     levels / production / network / timeline artifact is generated or
     imagined. The consumer-specific `validate_layout_economics_shape`
     extends the shared `validate_catalogue_shape` grammar (finite,
     non-negative lengths for every ranked candidate) without making those
     fields required for the design assessment; a defect is 409
     ARTIFACT_MALFORMED, never a bare 500. The comparison is served from ONE
     bound scenario read + artifact snapshot + `economics.json` observation,
     re-observed after the projection (READ_SNAPSHOT_CHANGED on movement).
205. Comparable Layout Development Cost is `mainRampLengthM × rampPerM +
     levelAccessLengthM × levelAccessPerM` and nothing else
     (`comparisonBasis.included = [RAMP, LEVEL_ACCESS]`, every other kind —
     DRIFT, CROSSCUT, RAISE, SHAFT, SHAFT_STATION_ACCESS, PRODUCTION,
     PROCESSING, BACKFILL, FIXED_OPEX, CAPITAL, REVENUE, NPV — explicitly
     `excluded`). It keeps the word "Comparable" and is never called a total
     mine development cost; it is not project economics, not NPV, not
     profitability, not feasibility. Without `economics.json` the endpoint
     is NOT_CONFIGURED with the geometry rows and `null` costs — never a
     hidden demo rate. No candidate what-if quantity (drift, crosscut,
     shaft, tonnage, production, processing, backfill, fixed opex, revenue,
     duration, NPV) is ever estimated per candidate.
206. No economic selection authority. `ranking`, `winnerId`, `scores` and
     the selection are owned by the layout authority (rules 148 / 149);
     `GET …/analysis/layout-comparison` returns rows in the persisted ranking
     order, carries no cost rank, no "cheapest", "economic winner", "best
     option", "recommended" or "optimal" marker, combines no engineering
     score with a cost, never modifies `layout_v2.json` or the selection and
     never auto-selects. The UI keeps "Engineering rank #n" and "Comparable
     development cost" as separate readouts, and a ranking / cost
     disagreement is shown as it is.

207. MineExchange is the ONLY adapter input boundary (Phase 23B,
     `adapters/`, `docs/external-adapters.md`). An external adapter consumes
     a MineExchange bundle as ZIP BYTES through the manifest-driven reader
     (`adapters/bundle_reader.py`: safe paths under the bundle root, SHA-256
     of every listed file, no unlisted entry, DTO validation on demand,
     `LOCAL_ENU_Z_UP` metre contract, every file / entity / DXF handle /
     omission looked up through `manifest.json` — a file name is never
     guessed and a DXF handle is never re-derived by parsing) — never
     `derived/*`, `scenario.json`, `timeline.json`, `network.json`,
     `stopes.json`, `ScenarioStore`, `ArtifactReader`, `DesignService` or
     the exporter's in-memory objects (`tests/test_adapters_core.py` scans
     the adapter import graph and code strings). `AdapterService` composes
     ONLY `ExchangeService.export` → `adapters.build_package(target, bytes)`,
     so the API path and an offline bundle produce byte-identical packages.
     Every consumed bundle group is reported in exactly one of FIVE states —
     AVAILABLE / ARTIFACT_ABSENT / SOURCE_NOT_SUCCESS /
     NOT_EXPORTED_BY_VERSION (the bundle's `NOT_IN_V1`, or a group this
     MineExchange version cannot carry) / UNSUPPORTED_BY_ADAPTER — a
     bundle-side absence is never conflated with a version gap or an
     adapter gap, and a production group is listed ONLY when the bundle
     carries or omits it (one active method per bundle, rule 196 — an
     inactive method's group is never a source); every value the target needs that no MineGen authority
     owns is NOT_PROVIDED, USER_REQUIRED or ADAPTER_DEFAULT_EXPLICIT (value,
     unit, scope, documented source, userOverride), and a number in a
     package that is neither in the bundle nor in `assumptions[]` is a
     defect. Failures are typed (`ADAPTER_MINEEXCHANGE_BUNDLE_INVALID`,
     `ADAPTER_MINEEXCHANGE_VERSION_UNSUPPORTED`,
     `ADAPTER_REQUIRED_SOURCE_ABSENT`, `ADAPTER_SOURCE_NOT_SUCCESS`,
     `ADAPTER_CONVERSION_FAILED`, `ADAPTER_TARGET_UNSUPPORTED` — each with
     adapter / source group / subject / reason), never a bare 500; adapter
     versions (VENTSIM, ANYLOGIC, UNITY, UNREAL 0.1.0) and
     `supportedMineExchangeVersions` are independent of the MineExchange
     version. `adapters/registry.py::ADAPTERS` is a plain table of four
     `bytes → AdapterPackage` builders, not a plugin runtime.
208. MineExchange 1.3 timeline is a PROJECTION of MineTimeline only
     (`operations/timeline.json` = `ExchangeTimeline`, `operations/tasks.csv`,
     `TIMELINE_ARTIFACT` in the export snapshot). Every task keeps its
     MineGen `targetId` as provenance and gains an EXTERNAL
     `targetReference` — `NETWORK_EDGE` = the exported edge id for
     development, `ENTITY` = `stope:<id>` / `cut:<id>` / `bench:<unitId>`
     for production (BACKFILL / CURE target the CUT; pillars are never a
     target); development progress copies `edgeId`, `geometryRef`,
     `pointChainageFractions`, `excavationStartNode`, `progressDirection`
     and the transitions; production states map to exported entity ids. The
     bundle preflight refuses (409 MINE_EXCHANGE_EXPORT_FAILED) duplicate
     task ids, unresolved dependencies, a development target that is not an
     exported edge, a geometry reference that does not resolve to the
     exported centerline, and a production target / state whose entity is
     not exported. 1.3 is additive: every 1.2 file is byte-identical, the
     geometry binaries are untouched, and the TIMELINE omission is
     `ARTIFACT_ABSENT` / `SOURCE_NOT_SUCCESS` (no longer `NOT_IN_V1`;
     `FIELD_LATTICE` stays the only `NOT_IN_V1`). The exporter never
     reschedules, re-times or invents a task.
209. Adapter outputs are read-only, deterministic and non-authoritative.
     An export generates nothing, persists nothing (no `derived/*` write, no
     registry entry, no invalidation) and leaves `scenario.json`,
     `arrays.npz`, `derived/*` and `economics.json` byte- and stat-identical;
     the same bundle bytes yield the same package bytes (fixed ZIP
     timestamps, sorted paths, SHA-256 per file in `adapter_manifest.json`,
     the manifest written last and never self-hashed, no wall-clock value,
     duplicate / unsafe package paths refused). Every package carries
     `adapter_manifest.json` (adapter name / version / target,
     supported and source MineExchange versions, `sourceSnapshot` copied
     from the bundle, `coordinateMapping`, `generatedFiles[]`,
     `identityMap[]`, `sourceStates[]`, `assumptions[]`, `warnings[]`,
     `omissions[]`) as its meaning authority. A package is a disposable
     projection for the target application: it never becomes a MineGen
     authority, is never imported back, and the frontend's compact export
     selector (MineExchange / Ventsim / AnyLogic / Unity / Unreal) triggers
     the download only — no scene mutation, no epoch bump, no generation.
210. Ventsim SEED (`VENTSIM 0.1.0`, `POST …/export/ventsim`) invents no
     physics. It requires EXCAVATION_CENTERLINES + MINE_NETWORK, copies the
     bundle DXF byte for byte (FULL FIDELITY, no simplification — the
     earlier Douglas-Peucker option is gone), takes DXF handles from
     `manifest.files[].dxfEntities`, verifies (never repairs) that each
     edge's polyline ends on its topology nodes (1e-4 m) and measures its
     declared length, and delivers `network/nodes.csv`, `network/airways.csv`
     (edge, entity, nodes, type, length, width, height, shape, orientation,
     dxfHandle, levelId, vertexCount — bundle facts only) and
     `identity/entity_map.csv`. No friction, resistance, fan, regulator,
     door, leakage, heat, diesel, airflow, pressure or density field exists;
     all are NOT_PROVIDED. The CSV is an authoritative handoff / QA table
     for the DOCUMENTED USER WORKFLOW (DXF import → Convert Centrelines →
     dimensions per handle / layer); no official automated attribute import
     is claimed, and no `.vsm` is produced.
211. AnyLogic operational data package (`ANYLOGIC 0.1.0`,
     `POST …/export/anylogic`) invents no fleet or dispatch. It requires
     MineExchange ≥ 1.3, MINE_NETWORK and MINE_TIMELINE (production
     optional) and hands over normalized tables only — `data/nodes.csv`,
     `edges.csv` (storage direction, never one-way traffic),
     `centerline_points.csv`, `capabilities.csv` (capability ≠ capacity),
     `production_units.csv` (STOPE / CUT / BACKFILL / BENCH / PILLAR with
     `retained` and `backfill` flags: a pillar is retained material and a
     backfill is a semantic record — neither is planned tonnes),
     `tasks.csv`, `development_progress.csv`, `production_states.csv`
     (explicit `initialState`) — plus `templates/simulation_inputs.csv`
     whose columns (fleet, speeds, cycle times, calendar, priority,
     dispatch, capacities) are BLANK. No speed, fleet size, cycle time or
     dispatch policy is ever written or defaulted, and no `.alp` is produced.
212. Unity / Unreal packages (`UNITY` / `UNREAL 0.1.0`,
     `POST …/export/unity|unreal`) package geometry + semantics and are not
     authorities. Every bundle GLB becomes `scene/assets/<path>.glb` in
     glTF Y-up right-handed metres: an exporter GLB (already `GLTF_Y_UP`
     under its root matrix) is copied verbatim; a copied
     `LOCAL_ENU_Z_UP` render GLB with no root transform gets EXACTLY ONE
     deterministic root node carrying `(x, y, z) → (x, z, −y)` that parents
     the previous scene roots, with the binary chunk (vertices, normals,
     indices) preserved byte for byte — never re-swept, never transformed
     twice, and a GLB already carrying the root node is refused.
     `scene/entities.json` is the identity authority (entityId, kind,
     levelId, assetPath, sourceEntityId, networkEdgeIds[]);
     `network.json`, `capability.json` and `timeline.json` (1.3) are the
     bundle documents verbatim; `import_settings.json` records per-asset
     frame facts and the engine import notes. No materials, lighting,
     collision, physics, NavMesh, gameplay, AI, animation or runtime
     synchronization is generated (all NOT_PROVIDED), and no
     `.unitypackage` / `.uasset` is produced. A world-only scenario yields a
     partial package (geology assets only) with ARTIFACT_ABSENT states.

213. MineResult 1.0 is the ONLY external-result input contract (Phase 23C,
     `results/`, `docs/simulation-results.md`). A result is an OBSERVATION
     an external application (Ventsim ventilation, AnyLogic operations)
     made over a MineExchange bundle: `MINE_RESULT_VERSION = "1.0.0"` is
     independent of MineExchange (which stays 1.3.0 — results are not a
     mine description and are never exported back into a bundle or an
     adapter package, so no feedback loop exists). The importer reads a
     MineResult-compatible ZIP only (`result_manifest.json` + the domain
     CSV tables — the filled round-trip kit); no `.vsm` / `.alp` / Unity /
     `.uasset` parsing exists. A result never redesigns the mine, never
     changes ranking, feasibility, topology, production, timeline or
     economics, and MineGen computes NO simulation quantity from it: the
     backend stores, binds, normalizes and slices what the user delivered.
214. Exact source-snapshot binding. A result package names the scenario
     (`sourceScenarioId`) and the EXACT MineExchange `sourceSnapshot`
     (scenarioRevision, arraysRevision, activeRampSource,
     artifactRevisions — the Phase 23B manifest grammar, produced by ONE
     observation helper `ExchangeService.observe_source_snapshot` /
     `observe_edge_centerlines`, never a second fingerprint calculator or a
     second artifact list). Import is observe → parse → validate →
     re-observe under the scenario lock → compare → atomic publish: another
     scenario is RESULT_SOURCE_SCENARIO_MISMATCH (409), another snapshot
     RESULT_SOURCE_SNAPSHOT_MISMATCH (409), a mine that moved during the
     import READ_SNAPSHOT_CHANGED (409); a result is never re-bound. Every
     stored result is judged COMPATIBLE / STALE against the CURRENT
     snapshot on every read: a STALE result stays listed, inspectable,
     exportable and deletable, but its overlay (geometry / frames) is
     refused with RESULT_STALE (409) and the UI shows "STALE — this result
     was generated from an older mine snapshot". No mine operation
     (scenario PUT, world / design regeneration) deletes a result.
215. Results live OUTSIDE derived/: `data/scenarios/{id}/results/<resultId>/`
     `{manifest.json, normalized.npz, source.zip}` (the original ZIP kept
     byte for byte with its SHA-256). Publication is atomic (temporary
     sibling directory, fsync, rename); reading is READ ≠ TRUST (manifest
     validation, folder / id agreement, normalized digest reproduction —
     RESULT_PACKAGE_INVALID otherwise). `resultId` is deterministic:
     `sha256(canonical normalized content + sourceSnapshot + domain +
     sourceApplication)[:16]`, so the same package imported twice is ONE
     result (idempotent: 201 created / 200 existing) and the canonical
     export (`GET …/results/{id}/export`, `mine_result/` ZIP: fixed
     timestamps, sorted paths, canonical units, canonical row order) is
     byte-identical for the same stored result and is itself importable to
     the same identity. Results have no registry entry, no fingerprint
     role and no invalidation cascade.
216. Explicit identity, canonical units, declared time axis. Identity binds
     ONLY to MineNetwork edge ids of the source snapshot (Ventsim: `edgeId`
     directly or `ventsimUniqueNumber` through the explicit
     `airway_identity.csv` crosswalk; AnyLogic: `edgeId` +
     `chainageFraction ∈ [0, 1]` along sourceNodeId → targetNodeId): no
     nearest-airway, midpoint, endpoint or fuzzy spatial matching exists
     (RESULT_IDENTITY_UNRESOLVED / RESULT_IDENTITY_AMBIGUOUS, 409). Values
     are stored in canonical SI units (airflowM3s m3/s, velocityMs m/s,
     pressurePa / pressureLossPa Pa, temperatureDryC / temperatureWetC degC,
     airDensityKgM3 kg/m3; loadTonnes t; utilization fraction, queueCount
     count, haulageTonnesPerHour t/h, travelTimeSeconds s) converted ONLY
     through an explicit `unitConversions[]` declaration
     (RESULT_UNIT_UNSUPPORTED, 422, otherwise); the airflow sign convention
     is positive = edge sourceNodeId → targetNodeId (the edge direction is
     the sign reference axis, never a traffic direction). The time axis is
     DECLARED (`timeAxis.kind` STATIC | ELAPSED_SECONDS for ventilation,
     ELAPSED_SECONDS | MINE_DAY for operations), never inferred. NaN / Inf /
     non-numeric cells, out-of-range values, duplicate samples and
     undeclared columns are typed RESULT_DATA_INVALID / RESULT_PACKAGE_INVALID
     (422); explicit input budgets (upload 64 MiB, 32 members, 256 MiB
     uncompressed, 1 M rows, 5 000 agents, 100 000 times, 64 KiB lines) are
     RESULT_LIMIT_EXCEEDED (413); ZIP traversal, absolute members, nested
     directories, duplicates, unknown members and declaration mismatches are
     refused. Missing values are OMITTED, never zero-filled.
217. Round-trip kits are ADDITIVE adapter output. The Ventsim and AnyLogic
     export packages (adapters `VENTSIM 0.2.0`, `ANYLOGIC 0.2.0`; Unity /
     Unreal stay 0.1.0) carry a `roundtrip/` folder: a pre-filled
     `result_manifest.json` bound to the SAME sourceSnapshot as the export
     with canonical units declared, the EMPTY domain tables (Ventsim:
     `airway_results.csv` one pre-identified row per airway with blank
     metric cells + `airway_identity.csv`; AnyLogic: `vehicle_samples.csv`,
     `edge_metrics.csv`, `summary_metrics.csv` header rows) and a README.
     The kit carries NO simulation value and changes nothing in the
     existing package files; the adapter manifest lists the kit files
     (hashed like every other file) under `details.roundTripKit`.
218. Frames are backend slices; the overlay is separate geometry. The API
     serves `GET …/results/{id}/ventilation?metric&time` (hold-last: the
     sample at or before the time; nothing before the first sample; missing
     edges listed) and `GET …/results/{id}/operations/frame?time` (vehicles
     with backend-projected XYZ along the source centerline — interpolated
     ONLY between two samples of the same agent on the SAME edge, the
     previous sample held across an edge change, a vehicle existing from
     its first to its last sample; edge metrics hold-last per edge) from the
     stored normalized arrays; no hidden background processing. The
     frontend (Analysis › Simulation Results — no new AppMode) renders the
     frames over the source-snapshot edge centerlines as SEPARATE line /
     marker geometry (`ventilationResult`, `operationsHeatmap`,
     `operationsVehicles` layers; the base tunnel / centerline layers are
     never recoloured), colours by the backend metric extent or a manual
     display range with a legend (name, unit, min, max), keeps a missing
     value neutral, draws optional airflow arrows from the sign, keeps a
     RESULT CLOCK separate from the MineTimeline day cursor (MINE_DAY reads
     "Mine day 123.4"), holds the active result ids in frontend-only state
     that resets on every scenario transition, refreshes ONLY the results
     list on import / delete (no epoch bump, no scene reload), never shows
     results in the walkthrough and never invents a route, a value or a
     collider.
219. Reset is a registry-closure deletion with ONE authority (hardening H1
     §4.4). The backend artifact registry's `invalidated_by` closure
     (`services/workflow_stages.py`: stage → owned artifacts) decides what
     "Reset from here" removes; `GET …/design/reset-plan?from=<stage>` is
     the read-only preview and `DELETE …/design/stages/<stage>` the
     execution, both the output of the SAME function (`reset_plan` /
     `reset_from`) under the per-scenario store lock, cache entries popped
     with the files. STALE / MALFORMED artifacts are deletable (a recovery
     path); `ramp_source.json` is the root and is never touched (rule 162);
     a stage with no owned artifact is 404 RESET_TARGET_NOT_GENERATED and
     a non-deletable stage (WORLD — the scenario document is regenerated,
     not reset) is 409 RESET_STAGE_NOT_DELETABLE. A reset never races a
     job: a job's stale-input guard fingerprints its UPSTREAM inputs only
     (rule 60), never its own output, so the preview and the delete ask the
     job registry under the same scenario lock (`JobService.running_job`,
     the predicate `submit` uses; passed by the router, the design service
     knows no jobs) and answer 409 RESET_JOB_RUNNING (`jobId`) while the
     scenario has a QUEUED / RUNNING job — nothing deleted, the job never
     cancelled. The DELETE accepts the previewed `willDelete` the user
     confirmed (`expectedWillDelete`); a plan that differs under the lock is
     409 RESET_PLAN_CHANGED with the fresh plan and nothing deleted. The
     frontend has NO dependency graph of its own: it sends a stage id and
     the confirmed list, disables the button while any mounted card reports
     a running job, shows `willDelete` verbatim in the confirmation,
     re-reads and re-shows the plan on RESET_PLAN_CHANGED, empties exactly
     the scene slots the response's `deleted[]` names
     (`scene/artifactSlots.ts`, a file → slot presentation mapping, never a
     mirror closure), then re-reads the scene manifest;
     `scene/invalidation.ts` keeps only the two Effective-Ramp identity
     halves (rule 169). A mining-method change is the rule 40 scenario PUT,
     not a reset — its confirmation displays the `from=WORLD` plan, read
     afresh on every opening (per-opening query key, nothing cached), and
     enables Apply only once that read completed with no fetch in flight.
220. Walkthrough "Go To" authority is the ramp junction chainage
     (hardening H0 §3.2, `walkthrough/teleport.ts`). Teleport targets are
     the portal plus every main-ramp turnout, placed by backend chainage
     in this explicit fallback order and never by position guessing:
     NETWORK_RAMP_JUNCTION (`network.json` RAMP_JUNCTION nodes' ramp
     chainage) → LEVEL_ACCESS_JUNCTION (`level_accesses.json`
     `rampJunctionChainage`) → RAMP_SEGMENT_BOUNDARY (the effective ramp's
     segment ends — the LEGACY level entries) → NONE (portal only). The
     resolved authority is reported with the targets; a chainage outside
     the walkable centerline extent is dropped, ids are deduplicated and
     the list is sorted by chainage, so a failed level development never
     hides a turnout that the ramp already has. Branch teleport stays later
     scope (rule 187).

221. Analysis time series and 4D playback (hardening PR-2 H3 §6–7). `GET
     …/analysis/timeseries?bucketDays=<n>` is a READ-ONLY projection of the
     rule 197 family (`analysis/timeseries.py`): ONE bound snapshot
     (`AnalysisService._bound_inputs`, re-observed → READ_SNAPSHOT_CHANGED),
     nothing persisted, no job. Quantities come from geometry and timing from
     the MineTimeline, allocated LINEARLY over each task window (the
     Planning Cashflow convention): per bucket and cumulative
     `developmentLengthM`, `developmentExcavationM3` (vocabulary "Excavated
     development rock", never "waste"), `developmentTonnes` ONLY when
     `scenario.geology.hostRockDensity` is declared (OPTIONAL, NO default —
     absent → NOT_CONFIGURED / null cells, never 2.7 t/m³ or any constant),
     `productionTonnes` (STOPING window), `backfillM3` / `cementedBackfillM3`
     (BACKFILL window), retained pillar TOTALS (never per bucket), and the
     cost / revenue / netCashflow / cumulativeCashflow columns that ARE the
     economics ledger at the requested resolution (`economics_ledger`, same
     numbers as the analysis; NOT_CONFIGURED without economics.json).
     `bucketDays` defaults to the configured `cashflowBucketDays`, else 30
     (a display default); ≤ 0 is 422. The 4D view's Restart / Play / Pause /
     Loop (restart at the start day and continue) / 1× 5× 20× drive the
     day cursor only — no animation clock ever modifies the MineTimeline —
     and the 4D STATUS & RESULTS card and the Schedule tab render that
     series as given: the frontend never re-sums timeline tasks, and a
     `null` cell is a gap / "—", never zero.
222. Baked demos are READ-ONLY scenarios served in place (hardening PR-2 H4).
     `scripts/bake_demos.py` (`minegen/demos/bake.py`) bakes the three demo
     recipes — TABULAR Longhole (full workflow incl. one production shaft),
     TABULAR Cut & Fill, WARPED_VEIN world + layout-v2 + curved levels +
     excavation meshes — into `data/demos/{id}/` THROUGH THE APPLICATION'S
     OWN HTTP ROUTES from their preset + seed realization (rule 119,
     deterministic re-bake), with the DEMO / SYNTHETIC planning-economics
     assumptions, and writes `data/demos/index.json` (the commit it was
     baked from, no timestamp). `data/` stays git-ignored: baking is a
     deployment step. The scenario store resolves a demo id IN PLACE when no
     saved scenario carries it (a saved scenario always wins, so a clone is
     never shadowed) — no derived copy, every revision binding intact — and
     refuses every write (replace, delete, derived clearing, migration-on-
     read) with the typed 409 DEMO_READ_ONLY; ONE router dependency
     (`api/demo_guard.py`) answers the same code to every mutating request
     on a demo id before the route body runs, the read-only POSTs (export/*,
     analysis/what-if, design/cost/evaluate, design/shafts/suggest-collar)
     pass, no job is ever submitted for a demo and the demo directory stays
     byte- and stat-identical. `GET /demos` is READ ≠ TRUST on every read
     (malformed index → 409 DEMO_INDEX_MALFORMED; an entry whose directory
     is missing, shadowed or disagrees in seed / orebody / method / world is
     `available = false` with its reason, never dropped, never served);
     `GET /scenarios` lists saved scenarios only. The frontend opens a demo
     through the ordinary scenario + scene reads (File › Demos) as ONE
     scenario-identity transition that records the demo fact, enters
     viewer-only demo mode — no generation controls, no "Reset from here",
     the DEMO · SYNTHETIC badge, Auto tour over the View panel's own camera
     presets (off in Walk and in the Analysis workspace), 4D Loop on — while
     3D / 4D / Walk, Analysis and Export stay available; "Clone to edit" is
     an ordinary `POST /scenarios` of the demo document without its identity
     plus world regeneration from the same seed. The hidden controls are a
     presentation of the backend contract, never its only enforcement. A
     demo is a baked synthetic sandbox mine — never a measured, estimated or
     imported orebody — and the Hugging Face deployment (D0) stays a
     separate, deferred item.
