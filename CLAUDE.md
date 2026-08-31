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
