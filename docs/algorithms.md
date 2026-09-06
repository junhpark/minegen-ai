# Algorithms (v0.1)

This file is the index of numerical methods. Each phase appends its section.
Keep pseudocode here in sync with code; CLAUDE.md rules 21–27 are binding.

## Phase 01 — coordinate utilities

- `strike_dip_frame(strike_deg, dip_deg) -> (u, v, w)`:
  orebody-local right-handed frame; `w` points to the footwall side.
- `world_to_local / local_to_world`: rigid transform into/out of that frame.
- `gravity_aligned_frame(tangent) -> (right, forward, up)`:
  tunnel sweep frame, rule 26.
- `grade_limited_length(dz, max_gradient)`: heuristic lower bound, rule 25.

## Phase 02 / 18 — synthetic world

All fields are NumPy arrays on the numerical field lattice
(``world/field_grid.py``, ``FieldGrid``): x, y centered; z from
``base_elevation − depth`` to ``base_elevation + relief`` — the top is taken
from *configuration* so the shape is identical for every seed of a scenario
(seed-to-seed comparisons are element-wise meaningful). Cells are sampling
support only — never mining blocks or SMUs (rule 127).

### Terrain (``world/terrain.py``)
Seeded fBm value noise: ``octaves`` lattices of ``4·2^k`` cells, cubic
upsampled (``scipy.ndimage.zoom``), summed with amplitude ``0.5^k``, then
normalized so ``mean = base_elevation`` and ``max − min = relief``.
Bilinear sampling for the per-cell terrain-support fraction.

### Orebody (``world/orebody.py``, ``world/warped_vein.py``)
Three bodies in the strike/dip frame (rule 28), one honest contract split
(rule 134):

* TABULAR — analytic slab; ``contains`` is an exact half-extent test,
  ``signed_distance`` the exact oriented-box SDF, box mesh with outward CCW
  winding. ``TabularOrebody.footwall_point(u, v, offset)`` lies ``offset``
  past the footwall contact along ``+w`` (rule 29, used by Phase 03; tabular-
  only, no longer on the generic interface).
* ELLIPSOID — analytic geometric reference; exact Euclidean SDF (largest-root
  equation, deterministic bisection), analytic volume / rotated AABB, UV mesh.
* WARPED_VEIN (Phase 19) — deterministic synthetic irregular IMPLICIT body:
  ``contains := φ <= 0`` on the shape-model-1 function

      s = u/(L/2), t = v/(H/2);  g_X(s,t) = Σ wᵢ cos(π kuᵢ s/2 + φuᵢ) cos(π kvᵢ t/2 + φvᵢ) / Σ|wᵢ|
      u_c(t) = D·g_dev(0,t);  a±(t) = (L/2)(1 + I·g_out(±1,t));  b±(s) = (H/2)(1 + I·g_out(s,±1))
      ξ = (u − u_c)/a_sign(t),  η = v/b_sign(s),  P = (ξ⁴ + η⁴)^{1/4}
      w_mid = A·g_warp(s,t),  m = 1 + V·g_th(s,t)  (≥ 1 − V ≥ pinch floor),  k = 2/edgeTaper
      φ(u,v,w) = ((w − w_mid)/(T/2·m))² + P^k − 1

  i.e. ``|w − w_mid| < (T/2)·m·sqrt(1 − P^k)`` over the asymmetric planform
  ``P < 1`` — warped mid-surface, lateral centreline deviation, four
  independently modulated edges, pinch and swell, tapered terminations,
  single-valued (no overhang), one connected planform (checked at
  realization). Modes have wavenumber ≤ 3 on the body extent (rule 139).
  Bounding box = conservative analytic envelope
  ``|u| ≤ D + (L/2)(1+I), |v| ≤ (H/2)(1+I), |w| ≤ A + (T/2)(1+V)`` rotated to
  world. Volume = deterministic 2-D midpoint quadrature (1 m) of the exact
  w-extent ``2h``; tolerance 5e-3 documented, measured < 1e-4 vs 0.5 m.
  Derived (lazy, rule 138) on its own lattice (``geometryResolution`` in
  plane, ``min(res/4, floor thickness/3)`` across, padded 2 cells, ≤ 6 M
  cells else ``WarpedVeinGeometryBudgetError``): ``approximate_clearance`` =
  signed EDT of the lattice classification + trilinear query + box-distance
  outside the lattice, sign forced to agree with ``contains`` (magnitude
  capped at half a cell where they disagree); ``mesh`` = scikit-image
  marching cubes (Lewiner, ``gradient_direction="descent"`` → outward),
  welded (exact-duplicate merge, degenerate faces dropped), 1 mm rounding.
  Measured (520 × 310 × 16 m nominal, 5 m / 1.25 m lattice, 858 k cells):
  construct + bbox 9 ms, contains 0.67 M pts/s, clearance build 0.17 s,
  mesh 0.03 s → 19 k vertices / 38 k triangles, ≈ 1.2 MB of scene JSON.

### Terrain boundary policy (``world/spatial_fields.py``)
Each cell is sub-sampled ``2×2×2`` against the terrain (terrain sampled once
at every XY sub-position): ``terrain_support`` = share of sub-samples at or
below the surface, persisted as float32. Cells with support ``< 0.5`` are
"unsupported": the rock-quality field carries the ``COLUMN_TOP_FILL`` policy
(an unsupported cell takes the value of the nearest supported cell below it
in its column; the bottom layer is always supported, rule 35), so trilinear
interpolation just under the surface is never pulled toward an arbitrary
above-ground value. The support fraction is also the display mask of every
slice. Nothing classifies rock, ore or air; the analytic orebody alone
decides mineralized membership (rule 129), and ``orebody.volume()`` is the
only volume reported — there is no in-situ ore volume or tonnage
(rule 131).

### Slice display mask (``export/scene_manifest.py``)
A slice ships ``values`` plus a ``mask``. Every field is masked to
terrain-supported cells (``BELOW_TERRAIN``). The grade field is additionally
masked to cells that INTERSECT the analytic orebody solid
(``OREBODY_INTERSECTION_BELOW_TERRAIN``): ``sdf(centre) <= 0`` decides yes,
``sdf(centre) > cell_half_diagonal`` decides no, and the remainder is settled
by a deterministic ``3³`` sub-sample of the cell through ``contains``. An
intersection thinner than the sub-sample spacing is missed, which hides a
cell rather than inventing mineralization. This is a visualization mask; point
membership is ``orebody.contains`` alone (rule 129). Only the requested plane's
centers are built (``FieldGrid.plane_centers``) — never the full ~1 M-cell
``centers()`` array per slice request.

### Batch sampling (``RegularScalarField.sample``)
``sample(points N×3) → N`` float64: trilinear on the cell-center lattice,
coordinates clamped to the outermost centers (no extrapolation), pure NumPy
(rule 128). Measured: ≈ 1 M points in well under a second on the default
world (see ``backend/golden/phase18_bench_after.json``). ``sample_nearest``
serves categorical fields (fault zone).

### Correlated random fields (``world/geology.py``)
White noise → anisotropic Gaussian filter (σ_xy, σ_z) → standardize.
Correlation length L is defined as the lag at which correlation drops to 1/e;
for a Gaussian kernel this gives ``σ = L / 2`` (in voxels: ``L / 2 / spacing``).

- rock quality: ``clip(mean + std·f, min, max)``
- grade: log-normal ``mean · exp(v·f − v²/2)`` — positive, expectation
  exactly ``mean_grade``; ``grade_variability`` is the log-std. Grade uses
  its own correlation lengths (``OrebodyConfig.grade_correlation_length_xy/z``,
  defaults 80/40 m), independent of rock quality.

Each field uses its own RNG sub-stream of the scenario seed.

### Faults (``world/geology.py``)
Scenario-defined planes (not seed-generated). For plane normal ``n``:
``d = dot(p − origin, n)`` (signed). Half-widths (rule 36):
``|d| ≤ core → CORE, influence 1``; ``core < |d| ≤ influence → DAMAGE,
influence linear 1 → 0``; else ``NORMAL, 0``. Multiple faults: nearest plane
wins for ``signed_distance`` / ``nearest_index``; ``influence`` and ``zone``
take the max. ``nearest_index`` is computed but not persisted. These arrays
are measurements for visualization/diagnostics; Phase 03 cost evaluation
queries the analytic ``FaultPlane`` objects directly so per-fault penalties
are exact at arbitrary continuous points.

### Memory (default 1200×1200×600 m world, 10 m lattice)
``120 × 120 × 70 = 1,008,000`` cells, ≈ 21 MB total: float32 rock_quality,
grade, fault_signed_distance, fault_influence, terrain_support (4.0 MB
each); uint8 fault_zone (1.0 MB). ``arrays.npz`` is stamped
``field_artifact_version``; an NPZ without it (a Phase-17 block-model
artifact) is refused, never reinterpreted.
## Phase 03 — design cost evaluator & level access targets

### DesignCostEvaluator (``design/cost_field.py``, rules 41–42)
Continuous query ``evaluate_points(N×3)``; no dense volume.

    rock_quality     ``world.fields.rock_quality.sample(points)`` — batch
                     trilinear on cell centers, coordinates clamped to the center
                     lattice; near-surface values come from the field's
                     COLUMN_TOP_FILL terrain policy (rule 128)
    rock_penalty     w_rock · (100 − rq) / 100                      (w_rock = 2)
    fault_penalty    Σ_f analytic: core_penalty_f if |d_f| ≤ core_f;
                     damage_f · (infl_f − |d_f|)/(infl_f − core_f) in the damage zone
    orebody_distance EXACT analytic SDF (negative inside) — the evaluator accepts
                     only ``AnalyticOrebody`` (``ExactDistanceRequiredError``
                     otherwise, rule 135): an implicit body's approximate
                     clearance never drives the hard buffers
    orebody_penalty  w_ster · max(0, 1 − (sdf − buffer)/range)  (5, buffer 5, range 15)
    total            base(1) + rock + fault + orebody; +inf when invalid

Hard rejections (with reasons): OUTSIDE_WORLD (field-lattice extent),
ABOVE_TERRAIN, INSUFFICIENT_COVER, INSIDE_OREBODY, OREBODY_BUFFER,
RESTRICTED_ZONE (AABB). ``DesignContext`` carries the exclusion rules so
Phase 08 crosscuts can use a context that enters the orebody.
``minimum_cost_per_m`` (= base) is the admissible heuristic multiplier.
Throughput ≈ 0.9 M points/s on the default world.

### Levels & access candidates (``design/targets.py``, rules 43–45)
Levels: ``z_max − top_margin`` stepping down by ``sublevel_interval`` while
``≥ z_min + bottom_margin`` (z from the analytic slab corners).

Candidates per level (``candidate_count`` over ``±span/2`` along strike):

    q       = thickness/2 + footwall_access_offset
    v_coord = (z_level − C.z − q·w.z) / v.z
    P       = C + u_coord·u + v_coord·v + q·w

Exact level elevation and perpendicular offset (errors ~1e-14 m).
Dip-extent check uses the footwall *contact* at that elevation
(``(z − C.z − (t/2)·w.z)/v.z`` within ``±height/2``), not the candidate's own
``v_coord``, which projects up-dip because the offset has a vertical component.
Rejections are retained: OUTSIDE_OREBODY_STRIKE_EXTENT,
OUTSIDE_OREBODY_DIP_EXTENT plus evaluator reasons.
``next_level_accessibility`` = min over next-level candidates of
``decline_heuristic_distance`` (rule 25) — no search.

Portal: if ``scenario.portal`` is null, a placeholder on the surface
``portal_footwall_distance`` (350 m) from the orebody center against the dip
direction, clamped into the world (``portalGenerated = true``).
## Phase 04 — Chained Hybrid-A* Decline Generator

### Motion primitives (``design/motion_primitives.py``, rules 47–51)
Heading = azimuth clockwise from North; `forward = (sin θ, cos θ)`,
`right = (cos θ, −sin θ)`. 16 heading bins → Δθ = 22.5°, `L_h = R·Δθ =
7.0686 m` for every primitive. Steering {L, S, R} × grade {0, −0.5g, −g}
= 9 children; `dz = grade·L_h` (float). Samples every ≤ min(2 m, smallest
fault core half-width) including both ends. Primitives are built once as a
pose-local template and only rotated/translated in `expand()` (bit-identical
to the explicit construction).

Goal connectors (exact, last sample *is* the target): single arc
`k = 2y/(x²+y²)`, then arc-then-straight (turn on the R_min circle until the
heading points at the target — root of `azimuth(T−Q(φ)) − (θ+φ)` by scan +
bisection — then straight). Grade = Δz / total horizontal ∈ [−g_max, 0],
|heading change| ≤ 45°. `dubins_cs_length()` gives the same horizontal length
in closed form and is used as the heuristic's geometric lower bound.

### Hybrid A* (``design/astar_3d.py``, rules 52–57, 66)
State `(x, y, z, heading, cover_established, burial_established)` continuous;
key `(⌊x/5⌋, ⌊y/5⌋, ⌊z/1⌋, round(θ/Δθ) mod 16, cover, burial)`. One batched
evaluator call per expansion (45 centerline points); a primitive is rejected
if any sample is invalid; cost = trapezoid of cost/m over 3D arc length
(+ turn penalty). Cover transition: before `minimum_surface_cover` is first
reached, `INSUFFICIENT_COVER` samples are forgiven; afterwards never.

**Direction-aware excavation-envelope feasibility (rule 66).** Per primitive
sample the actual heading/grade tangent is analytic (constant curvature and
grade: `θ(s) = θ_end − κ·(L_h − s)`), and the K tunnel-profile vertices are
swept with the gravity-aligned frame via the SHARED
``design/profile.boundary_points`` — the identical geometry the Phase 06 mesh
excavates. One extra batched ``envelope_masks`` call per expansion (K × 45
points, boolean masks only): a primitive whose centerline is valid but whose
wall or roof clips a hard exclusion (world XY/bottom, orebody + buffer,
restricted zone) is rejected in the search. Above-terrain envelope points
follow the rule-66 profile-burial transition, tracked as node state: allowed
until the full ring first buries (portal roof), breakthrough afterwards
rejects; the initial state is derived from the start ring, and the exact
transition is re-verified by the Phase 06 gate. The conservative isotropic
`buffer + profileEnvelopeReach` rule is NOT used: it is a sufficient
condition only, and a hard `buffer + reach` standoff was measured to strand
footwall-approach poses at R = 18 m.

    h  = sqrt(max(L_dubinsCS, Δz/g)² + Δz²) · min_cost          (admissible)
    f  = g + ε·h                                                  (ε = 2, heuristic inflation —
                                                                   no formal ε-bound is claimed, rule 55)
    order = (⌊f / bucket⌋, tie_break(pose), f),  bucket = 2·L_h·min_cost
    tie_break (cone):  Δz/g > standoff → |d_h − standoff| (3·R ring)
                       else            → |L_dubinsCS − Δz/g|   (approach cone)

Cell dominance on f (rule 56). Goal shot attempted at pop when d_h ≤ 5·L_h.
States below `target.z − 0.5` are not expanded (monotonic decline).

### Chaining (``design/mine_designer.py``, rules 21–22, 53–54, 66)
Per level every valid candidate (K ≤ 5) is searched from the current terminal
pose; first segment heading = azimuth(portal → candidate), later segments
inherit. Selection = segment cost + next_level_accessibility × min_cost.
Structured `INFEASIBLE` / `NO_VALID_CANDIDATES` / `SKIPPED`.

**Launchability (rule 66).** Every successful non-final arrival must have at
least one legal forward/downward successor primitive under the same
envelope-aware contract; otherwise the candidate is demoted to
`INFEASIBLE` (`termination = NEXT_LAUNCH_INFEASIBLE`).

**Bounded deterministic backtracking.** An arrival can be one-step
launchable yet strand the NEXT level (measured on the default scenario: the
L10 best-scored approach heads into the footwall and kills all five L11
searches at depth 2, while two sibling L10 candidates open every L11 target).
When a level has no feasible candidate, the nearest ancestor level with an
untried candidate advances to its next deterministic pick (score order, ties
by candidate index) and the chain below is re-searched. Each accepted
backtrack consumes one unit of `max_chain_backtracks` (default 24);
exhausting the budget fails the frontier level EXPLICITLY. The search itself
is unchanged: continuous state, deterministic ordering, exact targets,
Rmin/gmax invariant. The default 13-level chain completes with 3 backtracks.

### Measured (default scenario, one fault, 13 levels, K = 5)
Under the envelope-aware contract: 13/13 levels, 3 chain backtracks, wall
63 s; smoothing 13 smoothed / 0 fallback (ΔfieldCost +0.0539 %); centerline
min orebody sdf 8.89 m — envelope-clean under the direction-aware check even
below the isotropic 10 m sufficient bound; Phase 06 SUCCESS with 0 envelope
violations and volume QA 0.31 %. (Pre-envelope baseline for reference:
65/65 searches, 51,631 expansions, wall 32 s.) Small scenario, ε = 1.0 / 1.5:
EXPANSION_LIMIT at 20k (plateau); ε = 2: 3,152 expansions.
## Phase 05 — smoothing + revalidation (`design/smoothing.py`, rules 61–64)

Per selected Phase 04 segment: lossless primitive simplification (equal
curvature+grade runs merge; endpoint/heading error < 1e-9) → junction-aligned
analytic control grid (curvature-adaptive spacing ≤ 0.09·R on arcs, ≤ 5 m on
straights) → iterative constrained smoothing of the control polygon
(J = w_b·bending + w_f·fidelity, gradient descent; endpoints AND the first/
last interior control anchored; corridor projection to the raw polyline;
isotonic z) → grade/radius feasibility projection (deterministic bisection of
the displacement field: on grade-saturated raw segments the feasible
displacement is ≈ 0 and is found up front) → curve construction → full
revalidation → deterministic local repair (blend the violating control window
toward raw by the repair factor; whole-segment revalidation each round; ≤
`maxRepairs`) → explicit RAW_FALLBACK otherwise. A raw segment that itself
fails revalidation makes the phase FAILED, never a fallback.

Curve representation: XY is a clamped cubic Hermite over the 3D chord-length
parameter — boundary tangent DIRECTIONS are the Phase 04 headings (explicit
boundary conditions, never frozen points), interior directions blend the raw
analytic tangents with the centered-difference change of the deformed
polygon, and magnitudes are (1 + θ²/16)/√(1 + g²) (arc-reproduction ×
horizontal-speed correction; unit magnitudes leave a ±1.4 % plan-curvature
oscillation on R_min arcs). z is piecewise-LINEAR in the cumulative
horizontal arc length between controls, so the physical grade of every
interval equals the control secant exactly; the shared boundary grades
(clamped mean of adjacent raw grades, rule 61) are met by projecting the
interior z-profile into the feasible band implied by g_max (reconstruction
excess of O(1e-5) is spread uniformly).

Revalidation (rule 62): sampling min(1 m, smallest fault core half-width);
the same `design/validation.py` sample walk Phase 04 uses (portal rule 52
cover transition included); grade from the curve derivative within
[−g_max − 1e-5, +1e-5]; XY plan radius ≥ R_min − 0.05 m; corridor ≤ 10 m on
final samples; field cost ∫c ds (turn penalties excluded) ≤ raw × 1.05
(rule 63). Every violation counts into the segment report.

### Measured (default scenario, 13 levels, K = 5 decline → smoothing)
See the Phase 05 completion report: all segments SMOOTHED with 0 repairs and
0 fallbacks; max grade 12.0000 %, min plan radius ≥ 17.95 m, per-segment
field-cost delta ≤ +0.1 %, endpoint/heading errors 0.

## Phase 06 — gravity-aligned tunnel sweep (pending)
## Phase 07 — MineNetwork (`network/builder.py`, rules 13, 68–70)

The RAMP subgraph derived from the Phase 05 EFFECTIVE centerline — never
from the mesh. Nodes: one `PORTAL` plus one `LEVEL_ENTRY:<levelId>` per
completed level; coordinates are the effective-centerline endpoints (Phase
05 endpoint preservation makes the last point the exact selected access
target, so `targets.json` is never re-read). Edges: one physical `RAMP`
per effective segment with scalar attributes only — `length3d`,
`meanGradientSigned` (Δz / horizontal length in the canonical
portal→deeper direction, negative descending), `maxAbsGradient`, typed
`crossSection` (width/height/analyticArea), `effectiveSource`,
`fieldCost` (fieldCostSmoothed or fieldCostRaw by source), a
`geometryRef {artifact, segmentIndex}` and typed reserved `simulation`
keys (haulage/ventilation/communication/rockRisk). The polyline lives
solely in `decline_smoothed.json` (rule 68).

`networkx.MultiDiGraph` is the in-memory engine only; the persisted/API
contract is the typed deterministic `derived/network.json`
(status/sourceRevision/nodes/edges/metrics/validation/
surfacePathAdvisory) — never a raw NetworkX serialization. Edge direction
is canonical geometry orientation, not one-way travel; connectivity and
redundancy run on the undirected physical projection: the multigraph
collapses to a capacity graph (parallel physical edges accumulate
capacity) and `independentSurfacePaths` is a max-flow to a virtual
surface source behind all PORTAL-type nodes (rule 69). The
`TWO_EDGE_DISJOINT_SURFACE_PATHS` advisory reports per-level counts
(default chain: 1 everywhere) without any statutory or regulatory
compliance claim (rule 70). Weld errors > 1e-6 m between consecutive
segments or a disconnected physical component FAIL the build explicitly.

Generation is synchronous (rule 60 reserves async jobs for long-running
operations); fingerprint covers `scenario.json` + `decline_smoothed.json`;
the network and the tunnel mesh are siblings — neither invalidates the
other, a new smoothed/upstream artifact deletes both (rule 68).

Measured (default 13-level scenario, Phase 07 RAMP-only baseline —
superseded by the Phase 08 topology below): 14 nodes, 13 RAMP edges, all
`independentSurfacePaths = 1`.
## Phase 08 — levels & crosscuts (`levels/builder.py`, rules 71–74)

Deterministic analytic geometry, no path search. Per completed level, the
strike DRIFT is anchored exactly at the Phase 05 LEVEL_ENTRY (the endpoint
is never moved), aligned in plan with the orebody strike `u` and graded by
`level_drift_gradient` in the canonical +u direction:
`z(u) = z_entry − g·(u − u_entry)`. No claim is made that a graded drift
stays on the exact 3D footwall-offset plane — the actual excavation
envelope is validated with the direction-aware boundary sweep instead.

Planned CROSSCUT stations come from the ANALYTIC orebody strike extent —
never the Phase 03 candidate span (100 m by default vs a 600 m body). v0.1
pitch is `stope_length + minimum_pillar` (35 m), symmetric about `u = 0`,
with `|u| + stope_length/2 + minimum_pillar ≤ half_length` → 17 stations
per level on the default body: a deterministic planned stope-access
lattice for Phase 09, not final stope design. Crosscuts run HORIZONTALLY
(horizontal projection of the footwall→ore direction, not the 3D −w) from
the drift to the first footwall contact, solved analytically against the
footwall face plane; hard gates: start weld ≤ 1e-6 m, terminal |sdf| ≤
1e-6 m, no pre-terminal orebody breach, and `DesignContext.crosscut`
envelope validation (orebody contact permitted; world, terrain and
restricted zones retained). Invalid required development FAILs the
artifact explicitly.

The drift is emitted as PIECES split at every station/entry breakpoint, so
each MineNetwork DRIFT edge maps 1:1 onto a development in `levels.json`
(rule 73). The network is rebuilt from smoothed + levels: JUNCTION per
station (a station coincident with the LEVEL_ENTRY reuses that node),
STOPE_ACCESS per crosscut terminal, and the surface-path advisory now
covers EVERY underground physical node. Default 13-level measured: 441
developments (220 drift pieces + 221 crosscuts), network 455 nodes / 454
edges (13 RAMP + 220 DRIFT + 221 CROSSCUT), single component, max weld
1.4e-14 m, every underground node at one surface path.

## Phase 09 — stopes & mining method (`mining/`, rules 75–80)

Stope generation goes through the explicit MiningMethodStrategy factory:
v0.1 implements LONGHOLE_OPEN_STOPING; every other reserved method returns a
typed UNSUPPORTED_METHOD failure — never a silent longhole substitute
(rule 78). The generator consumes the validated Phase 08 `levels.json` ONLY
(the station lattice is never recomputed): for every adjacent completed
level pair and station index, the paired CROSSCUT terminals — gated onto the
footwall face and station plane within 1e-6 m — anchor an orebody-aligned
rectangular prism in the analytic local frame: `u ∈ stationU ±
stope_length/2`, `v` between the two terminal local-v coordinates, `w = ±
half_thickness` (rules 75–76). Missing/duplicate/mismatched pairs FAIL the
artifact; required stopes are never silently skipped.

Validation per stope (rule 77): positive dimensions, bounds inside the
analytic extent, hard world/terrain/cover/zone sampling over a deterministic
≤5 m prism lattice (crosscut context: the ore volume itself is legal),
finite metrics, strike pillar ≥ `minimum_pillar` between neighbours plus the
Phase 08 end-pillar contract; vertically adjacent stopes share their
boundary face by construction. `meanGradeProxy` (Phase 18, rule 130) is a
deterministic equal-volume midpoint quadrature (≤ 2.5 m) of the stope
prism ∩ analytic orebody ∩ below terrain, sampling `world.fields.grade`
and averaging — a planning proxy, never a reserve/resource claim, and no
longer an `ore_fraction`-weighted cell mean. Measured (default): 204
stopes = 12 intervals × 17 stations, 1.95 Mm³ / 5.47 Mt, extraction fraction
0.775, exact 5 m strike pillars, all anchors ≤ 1e-6 m; the weighted grade
proxy moved from ≈ 3.99 (Phase-17 cell weighting) to the value recorded in
`backend/golden/phase18_vs_phase17.md`. Stopes are production volumes — never MineNetwork edges; the two
STOPE_ACCESS anchors are the link (rule 76), and Phase 10 owns temporal
states beyond `plannedState = PLANNED` (rule 80).

The volumetric level-development mesh is deliberately DEFERRED: independent
capped tubes overlapped at T-junctions would leave false internal walls at
every crosscut mouth; junction openings belong to a later mesh/walkthrough
step. Phase 08 ships the geometry contract (`levels.json`) and the topology
contract (network) plus centerline/graph visualization only.
## Phase 11 — Communication OSP (rules 87–92)

`communication.json` is a deterministic connected communication placement
baseline for `MESH_ROUTER` only (all other asset types return
`UNSUPPORTED_COMMUNICATION_ASSET_TYPE`). Direct inputs are scenario +
network + owning centerlines (`decline_smoothed.json`, `levels.json`);
stopes/timeline/tunnel are NOT inputs — communication and timeline are
siblings below the network.

Pipeline: network integrity gate (unique ids, exactly one PORTAL, resolvable
endpoints, RAMP/DRIFT/CROSSCUT only — RAISE/SHAFT return
`UNSUPPORTED_COMMUNICATION_EDGE_TYPE`) → owning-geometry resolution
(type↔artifact match, segmentIndex bounds, ≥2 finite points, recomputed
length within 1e-6 m, canonical fromNode→toNode orientation within 1e-6 m)
→ deterministic candidate/demand sampling (every node + interior edge
points at k·spacing strictly inside the edge; stable
`COMM:CAND|DEMAND:NODE:{id}` / `…:EDGE:{id}:P{k}` ids; uniform demand
weights) → network-geodesic distances → coverage/backhaul sets →
connected-greedy solve → PORTAL-rooted BFS backhaul tree → per-demand
serving assignment → §22 hard gates.

**`NETWORK_DISTANCE_THRESHOLD_V0_1` is NOT an RF propagation model.** A
candidate covers a demand iff the shortest PHYSICAL path distance through
the MineNetwork is ≤ coverageRangeM (+1e-6 m tolerance); backhaul uses the
same metric against backhaulRangeM. Two points 5 m apart through rock but
605 m apart along the tunnels have communication distance 605 m (regression
pinned). No RSSI/dBm/frequency/antenna/Fresnel/ray-tracing is computed; the
`CommunicationCoverageModel` strategy (`infrastructure/coverage.py`) owns
the distance→coverage/backhaul conversion, so a calibrated propagation
model can replace `NetworkDistanceThresholdModel` without touching the
builder. All config defaults are synthetic planning/demo assumptions.

**`CONNECTED_GREEDY_PATH_SET_COVER_V0_1` is deterministic and
feasible/connected but NOT guaranteed globally optimal**
(`optimalityClaim = false`). Starting from the mandatory PORTAL root, each
iteration adds the whole shortest candidate-hop path (multi-source BFS,
id-ordered neighbours) maximizing (gain/cost, gain, −cost, smallest id),
where gain counts newly covered demand of ALL new routers on the path — a
pure relay router can be added as part of a path to a useful downstream
router. Unmeetable targets fail typed
(`INFEASIBLE_COMMUNICATION_COVERAGE`). No RNG, no new dependencies.

Accepted default (454 edges / 15,820 m, default config): 547 candidates,
1,063 demands, 100 selected routers (connected-greedy baseline count),
coverage 1.000, serving mean 36.2 m / max 91.3 m, 99 backhaul links,
max 38 hops, ~0.4 s, byte-deterministic modulo sourceRevision.

## Phase 12 — Generic Sensor OSP (rules 93–98)

`sensors.json` is a deterministic monitoring-placement baseline for
`GAS_SENSOR` only (all other asset types return
`UNSUPPORTED_SENSOR_ASSET_TYPE`; RAISE/SHAFT edges return
`UNSUPPORTED_SENSOR_EDGE_TYPE`). Direct inputs are scenario + network +
owning centerlines — communication.json, stopes and timeline are NOT
inputs: communication, sensors and timeline are siblings below the network
(rule 97), so requiring MESH_ROUTER connectivity for a GAS_SENSOR would
silently smuggle in a second unsupported physical assumption.

Shared engineering (rule 93): `InfrastructureNetworkDomain`
(`infrastructure/network_domain.py`) owns MineNetwork integrity gates,
owning-geometry resolution (1e-6 m length sync, canonical fromNode→toNode
orientation), deterministic NODE/EDGE sampling (`SENSOR:CAND|DEMAND:...`
ids with the same endpoint-dedup contract as Phase 11) and the
network-geodesic distance machinery. Both builders consume it; neither
reimplements it.

**`NETWORK_DISTANCE_MONITORING_THRESHOLD_V0_1` is NOT a physical
gas-detection model.** A sensor candidate covers a monitoring demand iff
the shortest PHYSICAL path distance through the MineNetwork is ≤
monitoringRangeM (+1e-6 m). It is a monitoring-LAYOUT spacing proxy —
never Euclidean through rock (605 m-vs-5 m regression pinned), and no
ppm/airflow/diffusion/response-time/probability is computed. The
`SensorCoverageModel` strategy (`infrastructure/coverage.py`) owns the
distance→coverage conversion and is injectable, so a physically grounded
model can replace it without touching `SensorBuilder`.

**`GREEDY_SET_COVER_V0_1` is deterministic but not globally optimal**
(`optimalityClaim = false`). From the EMPTY set it repeatedly selects the
candidate with the highest uncovered-demand gain (unit sensor cost,
uniform demand weights — explicit v0.1 assumptions, rule 96), ties broken
by lexicographically smallest candidate id; unmeetable targets fail typed
(`INFEASIBLE_SENSOR_COVERAGE`). No connectivity requirement exists for
sensors. Assignment eligibility is strategy-owned: each covered demand is
served by its nearest covering sensor, ties by smallest sensor asset id.

Accepted default (454 edges / 15,820 m, default config — same 40/20 m
sampling as Phase 11, hence identical 547 candidates / 1,063 demands): 131
selected sensors (greedy baseline sensor count), coverage 1.000,
monitoring mean 30.1 m / max 60.0 m, ~0.2 s, byte-deterministic modulo
sourceRevision.

## Phase 10 — MineTimeline (rules 81–86)

`timeline.json` lifts the immutable geometry chain onto a relative
continuous day axis (startDay 0, no calendars). A typed `ScheduleConfig`
supplies every rate — transparent synthetic baseline defaults (ramp 4 /
drift 5 / crosscut 4 m/day, prep 5 d, stoping 1000 t/day, mucking
1500 t/day, backfill 500 m³/day, cure 7 d), never hidden constants and
never calibrated productivity claims.

Task graph: exactly one development task per network edge
(`TASK:DEVELOP:{edge.id}`; RAISE/SHAFT fail `UNSUPPORTED_DEVELOPMENT_TYPE`)
and exactly five tasks per stope (PREP → STOPING → MUCKING → BACKFILL →
CURE). RAMP tasks chain sequentially along the topology-validated
portal→deeper decline; each level's developments are rooted at LEVEL_ENTRY
via deterministic duration-weighted Dijkstra on the undirected physical
subgraph, and stope preparation depends on BOTH access crosscuts (rule 85).
The precedence-only earliest-start solve uses deterministic Kahn ordering
with stable task-ID tie-breaking; cycles fail explicitly (rule 82).

Every development carries backend-computed normalized chainage fractions
aligned 1:1 with its owning centerline points, hard-validated against
`edge.length3d` within 1e-6 m (rule 83), plus exact-boundary state
transitions (rule 84). The frontend only evaluates these contracts: partial
chainage clipping with one interpolated cut point, state-driven stope
materials, and 4D-mode suppression of static excavation layers (rule 31).

Default acceptance (accepted Phase 09 topology): 454 development tasks
(13 RAMP + 220 DRIFT + 221 CROSSCUT), 1020 stope tasks (204 × 5), 1474
total; ramp completion day ≈ 959.1, first stoping day ≈ 392.8, baseline
end day ≈ 1106.3 — the duration of the synthetic precedence-only baseline,
not a production forecast.

## Phase 20A — layout-v2 parametric family search (`layout/`, rules 141–152)

Inputs: the authoritative portal (`default_portal`, generic frame use),
the required levels of the ONE existing generator, in-plane orebody
sections at each level (world-origin-anchored 2 m grid classified by
`contains`; access distance = KD-tree nearest inside sample + 24-step
bisection along that segment → an UPPER bound, never optimistic), and a
footwall track = sample-weighted linear fit in z of the per-level footwall
edge references (an implicit body has no global strike; the fit is what
the families follow).

Families (closed form, chord-exact descent so the delivered per-edge
gradient never exceeds g):

- SPIRAL: straight approach → single arc → drifting helix of radius
  `R = ΔZ/(2π·g·n)` whose axis follows the footwall track offset by
  `standoff + R` in the rotated horizontal normal (`entryOrientation`);
  the approach gradient is tuned within `[f·g, g]` so level crossings land
  on the ore-facing angle. Non-uniform level intervals are typed
  infeasible.
- LONGITUDINAL: one-direction along-strike corridor tilted by the footwall
  drift per metre of descent, clipped to the world margin, extended at most
  `longitudinalExtension` past the body.
- SWITCHBACK: `k` legs per level of equal length `ΔZ/(k·g) − π·R_min − s`
  joined by constant-sense minimum-radius hairpins; the pair drift of the
  footwall is absorbed by bulging the hairpin (`R_min + |drift|/2`); a
  landing straight closes the last cycle exactly on the deepest level.
  Phase 20C.1-S hairpin STATION `s`: a declared finite axis
  (`switchback.stationLengthsM`, `None` → `[0, 2 × minimumTurnoutStraightBuffer]`
  = {0, 50 m}; 50 m is a planning default — twice the turnout straight
  buffer so a turnout centred on the station keeps its ± buffer inside the
  straight — never a statutory value). With `s > 0` every hairpin is
  arc(π/2) + straight(`s`) + arc(π/2) (pieces `HAIRPIN_c_IN`, `STATION_c`,
  `HAIRPIN_c_OUT`), the station runs perpendicular to the legs so the leg
  spacing becomes `2·R_min + s` (`derived.legSpacing`), and the station's
  horizontal travel is subtracted from the leg (rule 143 coupling: a station
  makes `LEG_TOO_SHORT` earlier, exactly as the arc does). Candidate ids
  gain `-s<m>` only for `s > 0`, so every pre-20C.1 id is unchanged; station
  candidates compete on the same score with no threshold change.

  Measured (commit S, `golden/phase20c1_s_layout_v2.json`, 92 candidates,
  `phase20c1_s_vs_20b2_layout.json`): every winner, ranking and feasible
  count of the 7 golden cases is unchanged and no metric drifts; the only
  contract change besides the enumeration (68 → 92, cheap-feasible +12 per
  TABULAR case, +6 on GEOMETRY-STRESS) is the GEOMETRY-STRESS shortlist
  order. Station diagnostics are consistent with the plain hairpins they
  replace (TABULAR k1: 16 reversals / 16 hairpin runs / ≈ 3 000° for both
  `s = 0` and `s = 50`; 3D length identical because the station is taken
  from the leg). Every k2 station candidate is `LEG_TOO_SHORT`
  (ΔZ/(2·g) − π·R_min − 50 < 20 m on all cases), and on GEOMETRY-STRESS
  (15 m levels, R_min 20 m) so is every k1 station candidate at g = 0.12
  (leg 125 − 62.8 − 50 = 12.2 m). NO station candidate entered the
  production shortlist of 12 on any case: the stage-3 lower-bound proxy
  ranks it below its plain twin (the far leg sits `s` further from the
  ore, so more levels exceed the stage-2 reach heuristic), and the rule 165
  per-family slot is taken by the plain k1 switchback. The S golden
  therefore still reports GEOMETRY-STRESS = NO_FEASIBLE_CANDIDATE — a
  shortlist starvation, not a geometric constraint: the exhaustive
  diagnostic (`golden/phase20c1_s_stress_station_diagnosis.json`,
  `LayoutV2Search.run(detailed_all=True)`, 51.6 s) validates every
  switchback and finds `SWITCHBACK-k1-p+20-CW-s50-g0.100` FEASIBLE with
  21/21 level accesses (all LS connectors, max access gradient 0.1197 ≤
  0.12, min plan radius 20.0 m, min pillar 11.8 m ≥ 10 m, min plan
  separation 40.1 m ≥ 30 m, max turnout heading change 69.8° ≤ 100°,
  access lengths 43–60 m plus 100.6 m on L21, total score 8.546) — the
  first feasible layout this case has ever had. The other five g = 0.10
  station candidates fail 2–11 levels, all typed `GRADE_LIMIT` (one
  `JUNCTION_SPACING_CONFLICT`), against 8–13 failed levels on their plain
  twins (`TURNOUT_NOT_STRAIGHT` dominant), i.e. the station removes the
  turnout-straightness failure exactly as intended. Getting that candidate
  into the production result is the Phase 20C.1-Q shortlist-yield action,
  not a threshold change here.

Delivered-centerline diagnostics: per-edge gradient, chord-based plan
radius at interior vertices (exact for uniformly sampled arcs), unwrapped
heading change; family signature = cumulative / signed heading change,
turning length (R < 500 m), hairpin runs (same-sense runs ≥ 150°),
reversals (runs within 150°–210°), dominant folded azimuths (15° bins),
turn-direction consistency. Station merge (Phase 20C.1-S,
`analyze_centerline(..., station_merge_max_m)`): two same-sense runs that
are each BELOW 150° and separated only by straight edges totalling at most
the bound are ONE run, so an arc–straight–arc hairpin counts as one
reversal / hairpin run / half-turn pair like the plain hairpin it replaces
(the turning-burden score is not escaped by inserting a station). The
search passes `max(stationLengths) + sampleSpacing`; two full hairpins
around a short leg are never merged (each is already ≥ 150°); `None`
keeps the plain rule. Measured on the TABULAR reference: spirals
show ≈ 2 400–6 200° cumulative change, consistency 1.0, 0 reversals;
2-leg switchbacks 13 reversals; longitudinal ≈ 150° with ≤ 1.

Search: cheap stage on every candidate (grade ≤ g_max + 1e-9, plan radius
≥ R_min − 0.05 m, inside the world, monotonic, all serviceable levels
served), shortlist of 12 by the Phase 20B.1 D cheap LOWER BOUND of the
weighted total (`w_dev·(L/L_ideal + 0.5·meanAccess/reach) +
w_geom·(unusedGrade + 0.5·turningFrac + maxAccess/reach +
20·meanCurvature + 0.05·reversals + 0.02·hairpinRuns +
0.05·equivalentHalfTurns)`; geology, the
access length and the clearance headroom are the omitted non-negative
terms — the rule 165 corrective after the audited proxy missed exhaustive
winners at ranks 40/62 and 22/26; additionally every declared family's
best cheap-feasible candidate holds a shortlist slot, displacing the
proxy tail so the bound stays 12 and the order stays (proxy, family
order, id)), detailed stage through
`design/validation.evaluate_and_validate` + `accepted_mask` (rule 52
portal transition), clearance report under the evaluator's policy,
`design/exposure.measure_exposure`, scores:

    development = L/L_ideal + 0.5·meanAccess/reach
    geology     = 10·coreFrac + 3·damageFrac + 5·poorRockFrac + 0.1·crossings
    geometry    = unusedGrade + 0.5·turningFrac + maxAccess/reach + clearanceHeadroom
                  + 20·meanCurvature(rad/m) + 0.05·reversals + 0.02·hairpinRuns
                  + 0.05·equivalentHalfTurns
                  (Phase 20B.1 D-2: the measured family signature priced in —
                  a priori round coefficients, never reverse-engineered to
                  crown a family. Phase 20B.2-B: equivalentHalfTurns =
                  cumulative |Δheading| (rad) / π is the ABSOLUTE turning
                  burden in 180° units — the audit showed meanCurvature,
                  being length-normalized, let a 34-half-turn helix price
                  0.55 while a 17-half-turn k1 switchback paid 1.12 through
                  the absolute reversal / hairpin counts. The coefficient
                  was fixed before the sensitivity run: 180° of steering
                  costs the same 0.05 as one reversal, so a hairpin (180° +
                  reversal) and one helix loop (360°) both price 0.10. It
                  shares its measurement with meanCurvature (density vs
                  count — reported separately, never a family bonus).
                  Measured 0.5× / 1× / 2× sensitivity on the exhaustive
                  feasible sets (golden/phase20b2_turning_burden_audit.json):
                  TABULAR spiral-vs-k1 flips only above 0.077 (k1 wins at
                  0.10), WARPED-301 above 0.103 (spiral wins at 0.10);
                  at the chosen 0.05 the SPIRAL winners stand and are
                  accepted as-is; no family bonus / penalty / multiplier
                  exists)
    total       = w_dev·development + w_geo·geology + w_geom·geometry

Ranking `(feasible, round(total, 1e-9), family order, id)`. Measured
(defaults, Phase 20B.1 D golden): TABULAR reference 68 candidates,
1 feasible in the bounded search (exhaustive diagnostic: 10), winner
`SPIRAL-n1-CCW-e+0-g0.100` (4 679 m, 13/13 levels, 0 reversals,
0.0232 rad/m, total 3.85 vs 5.05 for the best k1 and 5.86 for the best k2
switchback) in ≈ 27 s; WARPED_VEIN seed 301 3 feasible (exhaustive 16),
winner `SPIRAL-n1-CCW-e+0-g0.120` (14/14 serviceable of 18 required) in
≈ 36 s; geometry-stress (15 m levels, R_min 20 m) SUCCESS with
`SWITCHBACK-k1-p+20-CCW-g0.100` (21/21 accesses, 27 reversals; the k2
variants are infeasible on this geometry); WARPED_VEIN seed 307 honestly
returns NO_FEASIBLE_CANDIDATE (all 68 typed). Shortlist audit (rule 165,
`golden/phase20b1_shortlist_audit.json`): missedWinner = False on all 7
golden cases; missedFamilies = [SWITCHBACK] persists on 4 because stage-4
access feasibility is invisible to any cheap bound (the family slot
validates the family's best cheap candidate, which can fail the detailed
gates while a costlier family member would pass) — a recorded
bounded-shortlist limitation, not relaxed and not outcome-tuned away.
Effective Ramp materialization inserts the exact level-crossing vertices
and splits there; boundary tangents are shared chord directions.

## Phase 20B — ramp junctions and level accesses (`layout/access.py`, rules 153–160)

Anchor: backbone point `E + n·standoff + t·axis` with `t` = the projection
of the ramp's level reference clamped to `[lo + 5 m, hi − 5 m]`; TABULAR
uses `footwall_candidate_position(orebody, 0, z, standoff)` and `u`,
implicit bodies the section covariance eigenvector and the footwall-side
extent along its normal.

Junction lattice: chainages `k·10 m` with `z_ramp − z_L ∈ [−10, +45] m` and
horizontal distance to the anchor ≤ 300 m. Connector (Phase 20B.2-A,
`build_cs_connectors`): ONE-TURN CS from the junction pose (ramp heading
θ0) to the anchor POINT P — for each sense s ∈ {L = +1, R = −1} the turning
circle `C = J − s·R·(sin θ0, −cos θ0)` (math angles), `ℓ = sqrt(|C→P|² −
R²)`, tangent-point angle `γ = atan2(P − C) − s·atan2(ℓ, R)`, sweep
`t = mod2π(s·(γ − γ0))` with `γ0 = θ0 − s·π/2`; the word is `S` when
`t < 1e-9`, `LS`/`RS` otherwise, refused (`None`) when `|C→P| < R` or
`t > MAX_TURNOUT_SWEEP = π`. Both senses are always sampled (every 2 m,
arc points exactly on the circle), a pure straight is reported once, and the
planner judges every delivered polyline. The former Dubins CSC (LSL / RSR /
LSR / RSL to the anchor POSE) forced a second, terminal arc — often a
near-loop — so that the access met the drift heading exactly; that
G1-heading weld was never an engineering requirement (a T/Y junction into
the drift is), so the terminal heading is now the actual final-straight
heading, the weld at the level entry is position-only and
`terminalHeadingMismatchDeg = ∠(terminal heading, drift AXIS) ∈ [0°, 90°]`
is reported per access (never gated). Per-access observability adds
`turnoutArcLength`, `straightLength` and `pathToChordRatio =
horizontalLength / junctionToEntryPlanSep` (a diagnostic — a ratio of 1
is NOT an acceptance criterion). z is linear in delivered chord length
(constant edge gradient `Δz / Σchord`).

Acceptance on the delivered branch: `|g| ≤ g_max + 1e-9`, circumradius
≥ R_min − 0.05 m, 15 m ≤ L ≤ 300 m, `evaluate_and_validate` with cover
established (world, terrain, cover, restricted, orebody buffer under the
policy), clearance ≥ required, profile boundary points through
`envelope_masks` (0 hard, 0 above terrain), junction spacing ≥ 40 m.
Phase 20B.1 B hard gates on every candidate (typed, never clamped):
turnout curvature — cumulative |Δheading| of the delivered ramp over
junction ± 25 m ≤ 100° (rejects a turnout inside a near-minimum-radius
turn; a true straight-insert requirement needs Phase 20C family support);
junction → entry PLAN separation ≥ 6 × width (30 m default); rock pillar —
branch-to-ramp excavation separation ≥ 2 × width (10 m default) on samples
beyond the geometry-derived taper `s* = R·arccos(1 − (pillar + width)/R)`
(≈ 25.3 m for the defaults; quarter-turn + straight beyond one radius),
terminal always judged. Since 20B.1-v2 (1.2) that separation is the
DIRECTION-AWARE sampled envelope gap (`layout/access.py::gated_separation`):
for every judged branch sample the closest-centerline pair
(`nearest_on_polyline`) gives `u` = branch → ramp, and each tunnel's
gravity-aligned cross-section contributes its support along `u`
(`profile_support`: the `ProfileShape` vertices at `x·right + y·up` in the
rule-26 frame of that tunnel's tangent) —

    gap = d_centerline − support_branch(+u) − support_ramp(−u)

Horizontal parallel drives read `width/2 + width/2` (the former fixed rule,
unchanged); a drive BELOW another reads `height + 0` (the lower profile
reaches `height` up to the upper floor centerline, which has no downward
extent), and a sloped pair reads `height·cos(slope)`. This is a cross-section
support at the sampled closest pair — not an exact swept-surface /
mesh-to-mesh distance (Phase 20D) — and a sample whose direction to the ramp
runs along its own axis (an access driving straight away from the ramp)
contributes 0 there, which the taper exclusion already covers. The isotropic
`hypot(width/2, height)` on both sides (≈ 11.2 m) is deliberately not used. Selection among the survivors stays
`(access_length_cost(L, P), L, junction chainage, sense S < LS < RS)`
(rule 163; the sense rank is `CONNECTOR_SENSE_ORDER`) — the
length cost is SECONDARY to the gates. A level that fails with junction-
spacing conflicts re-runs its search ignoring only the used spacing as the
B-5 assignment diagnostic (starvation vs geometry); nothing is relaxed for
the recorded result.

Measured (TABULAR reference, 20B.1 defaults): 68 candidates, 2 feasible
under the hard gates, winner `SWITCHBACK-k2-p+20-CW-g0.120` with 13/13
accesses — per level: pillar 10.2–16.1 m, plan separation 33.2–39.4 m,
turnout 23–52° over ± 25 m, branch 66–91 m; stage-4 total ≈ 20 s (the
pillar gate evaluates every surviving connector against the full ramp
polyline). WARPED-301: winner `SPIRAL-n1-CCW-e+0-g0.120`, 14/14 accesses,
pillar 10.1–13.8 m, turnout 81–91° (a gentle helix passes the 100° gate by
design), branch 48–97 m.

## Phase 20B.1 — stand-off / clearance semantics audit (S1) and local refinement

### C-1 distance-concept audit (roadmap item S1, executed here)

Seven DIFFERENT distance concepts, audited call-site by call-site. None is
additive with a path length (rule 168); each row names what the value is
measured FROM and applied TO.

| Concept | Default | Measured from → applied to | Read by | Kind | Finding |
| --- | --- | --- | --- | --- | --- |
| `RampConstraints.clearance` | 3.0 m | (intended: inside-profile operating clearance) | **nothing** | user schema field | UNWIRED — declared, typed in the frontend, consumed nowhere. Documented as RESERVED on the model; wire or remove deliberately (schema change), never silently repurpose. It does NOT duplicate `orebody_exclusion_buffer` in effect because it has no effect. |
| `DesignConfig.orebody_exclusion_buffer` | 5.0 m | orebody surface (signed distance under the active policy) → every centerline sample and every excavation-envelope point | `design/constraints.py` (context), `design/cost_field.py` (hard reject + sterilization ramp), `layout/search.py::required_clearance` | user engineering constraint | the ONE hard orebody buffer |
| layout-v2 required centerline clearance | `buffer + hypot(width/2, height)` ≈ 10.59 m | orebody surface → the FLOOR CENTERLINE, derived so the whole profile envelope stays outside the buffer | stage-4 validation, access planner | derived | consistent envelope basis |
| `ramp.footwall_access_offset` | 20 m | footwall footprint edge (⊥, ore side → out) → legacy rule 43 target line AND the level-development anchor plane | `design/targets.py`, anchor stand-off default | user planning value | the LEVEL-DEVELOPMENT plane |
| `layout.footwall_standoff` | None → `footwall_access_offset + 6 × tunnel_width` = 50 m | footwall footprint edge → the main-ramp CENTERLINE's ore-facing nearest approach (SWITCHBACK near-leg centerline, SPIRAL helix rim, LONGITUDINAL corridor centerline — code semantics; the old docstring said "corridor edge" and was wrong) | `layout/families.py` corridor placement | user override of a derived default | **the audited misuse**: it previously defaulted to the SAME `footwall_access_offset`, putting the permanent ramp corridor IN the level-development plane — measured envelope separation −4.9 m on 12/13 reference levels (commit O). The new default keeps explicit spatial corridor margins (`RAMP_CORRIDOR_MARGIN_WIDTHS = 6` tunnel widths: two half-spans + a two-width pillar + a three-width turnout-taper allowance `R·(1 − cos(s*/R)) ≈ 15 m`, so a post-taper access can hold the full pillar everywhere, not only at its terminal); spatial + spatial, never a path-length sum |
| `access.anchor_standoff` | None → `footwall_access_offset` (raised to `required + errorBound + 1` under a conservative basis) | footwall footprint edge → the LEVEL ENTRY point | `layout/search.py::anchor_standoff` | user override | with the stage-4 REFINED bound the raise shrinks (WARPED 301: 22.36 → 20.0 m) |
| WARPED conservative error bound | `1.5 × ‖lattice spacing‖` (10.77 m coarse / 5.39 m refined ×2) | derivation, not a distance concept: boundary discretization ≤ 1 diagonal + trilinear ≤ 0.5 diagonal | clearance policies | derived, formally conservative | narrowed ONLY by shrinking spacing (C-2), never by lowering 1.5 |
| `preferred_access_length` | None → max(15, 6 × width) = 30 m | PATH LENGTH along the branch | access selection cost | user planning default | not a spatial stand-off; never added to one (rule 168) |

### C-2 stage-4 local clearance refinement (implicit bodies)

Stages 2–3 keep the whole-body lattice (basis `COARSE_CONSERVATIVE`). For
each shortlisted candidate, stage 4 builds ONE local window — the bbox of
(a) centerline samples whose coarse certification falls below the required
clearance and (b) the level-entry corridor (preliminary anchors under the
coarse stand-off) — padded by `required + coarseBound + 2 m`, clipped to
the derived-geometry box, re-sampled at `spacing / clearance_refinement_factor`
(default 2), EDT + the SAME `1.5 × ‖spacing‖` bound (basis
`REFINED_CONSERVATIVE`). A window-boundary clamp (`min(EDT, distance to a
clamped window face)`) keeps the certificate a true lower bound against
solid outside the window; faces at or beyond the analytic local bounds are
never clamped. Outside the window every point keeps its coarse
certification (`max` of two lower bounds). Budget
`clearance_refinement_max_cells` (default 8 M) skips refinement with an
explicit per-candidate diagnostic; measured windows: WARPED-301 winner
26 × 154 × 81 = 324 k cells (~0.35 s), bound 10.77 → 5.39 m, anchor
stand-off 22.36 → 20.0 m, total access 1 025 → 611 m.

One certification per selected design (20B.1-v2 1.1). The candidate-specific
policy is NOT persisted: `LayoutV2Search.candidate_policy(result, id)`
rebuilds it deterministically from the retained stage-4 context (the same
`_candidate_policy` inputs — candidate points, serviceable levels, coarse
policy, config) and fails closed when the rebuilt refinement provenance
(applied / reason / factor / spacing / shape / cells / bound) differs from
the candidate's recorded report. `DesignService._selected_candidate_policy`
resolves the selection (`candidateId + layoutRevision`, stale → 409
`LAYOUT_V2_SELECTION_STALE`), re-runs the search on a cache miss
(`_layout_object`) and cross-checks the selection's persisted `clearance`
block (basis / bound → 409 `LAYOUT_V2_CLEARANCE_MISMATCH`). Selection
materialization, the Phase 06 tunnel sweep, the level builder and the
development sweep all take `_active_clearance_policy` — the selected
candidate's certification when LAYOUT_V2 is active, the world policy (EXACT
for analytic bodies, numerically unchanged) for LEGACY. `level_accesses.json`
reports the candidate's actual `clearanceBasis` / `clearanceErrorBound` /
`clearanceRefinement`; the catalogue's top-level `clearanceBasis` keeps its
whole-body search meaning. The shortlist bound is validated to be at least
`len(FAMILY_ORDER)` (1.3) so the per-family reserved slot never exceeds it.

`EXACT` remains the analytic-body basis only; an implicit body is never
labelled EXACT (rule 134) — its bases are COARSE_CONSERVATIVE /
REFINED_CONSERVATIVE, both carrying their actual `latticeSpacing` and
`errorBound` in the candidate report.

## Phase 20C.1 — hairpin station, shortlist yield, WARPED seed survey

### Q — shortlist-yield audit and the geometric access screen (rule 176)

Instrument: `python -m minegen.regression layout-v2-yield` (diagnostic,
`golden/phase20c1_q_yield_before.json` on the commit-S search,
`_after.json` on the commit-Q search). For every golden case and family it
records each cheap-feasible candidate's FAMILY-INTERNAL cheap rank (stage-3
lower-bound proxy), production shortlist membership, exhaustive detailed
outcome, typed failure reasons and per-level access failure reasons, and
per family a Mann–Whitney rank AUC (proxy rank vs detailed pass), the
Spearman correlation of proxy vs detailed total among passes and the family
rank of the best feasible candidate. The decision rule was fixed BEFORE the
numbers (`YIELD_AUC_CORRELATED = 0.6`, `YIELD_MIN_PAIRS = 5`): a correlated
family gets an audited top-N reservation, an uncorrelated one gets its
proxy term fixed.

Measured on the commit-S search (7 cases, 92 candidates each), with the
CORRECTED pair-weighted within-case pooling (closeout A-1; the Q values are
kept in brackets — the pooling bug never touched a per-case AUC):

| family | pooled rank AUC | pairs | cases used | pass / fail | verdict |
|---|---|---|---|---|---|
| SPIRAL | **0.673** (Q reported 0.665) | 196 (was 1 428) | 4 of 7 | 14 / 102 | correlated |
| SWITCHBACK | **0.507** (Q reported 0.489) | 1 119 (was 8 789) | 5 of 7 | 47 / 187 | NOT correlated |
| LONGITUDINAL | — | 0 | 0 of 7 | 0 / 0 | no cheap-feasible candidate on any case |

Both verdicts, and therefore the Q action, are unchanged by the correction:
SPIRAL stays above the a priori 0.6 threshold and SWITCHBACK stays below it
(0.507 is barely better than the 0.5 of a coin). The pair counts shrink
because the discarded pooling counted every cross-case pair — comparing a
rank-1 candidate of one case with a rank-6 candidate of another, which are
different scales.

Among feasible switchbacks the proxy orders the TOTAL well (Spearman
0.93–0.98), so it is a sound score bound; what it cannot see is level-access
feasibility, which decides every switchback detailed failure
(`LEVEL_ACCESS_INFEASIBLE`: TURNOUT_NOT_STRAIGHT 65 / 67 level failures on
WARPED-301 / GEOMETRY-STRESS, GRADE_LIMIT 52 / 84, INSUFFICIENT_RAMP_PILLAR
40 on TABULAR). Consequences before the action: GEOMETRY-STRESS's only
feasible candidate (the commit-S station switchback) sat at family rank
15 / 18 (global 18 / 21) and was never validated (`winnerMissedByShortlist`
= true); WARPED-301's first feasible switchback sat at family rank 5 with 4
switchback slots (`missedFamilies = [SWITCHBACK]`, 9 feasible switchbacks
exhaustive, 0 in production); TABULAR's shortlist validated 12 candidates
of which 5 passed.

Action ("fix the proxy term" branch, no coefficient): the stage-3 order
gains an exact prefix. `geometric_access_screen` runs, for every
cheap-feasible candidate, the evaluator-free stage-4 access gates on the
delivered polyline through the SAME `_search_level` code path
(`geometric_only=True`): the junction lattice, B-3 turnout curvature, B-1
plan separation, connector availability, gradient, length, plan radius and
the B-2 direction-aware rock pillar, with the junction-spacing assignment
ignored and coarse-stand-off anchors. A level with no passing candidate is
BLOCKED. Order = `(blockedLevels, proxy, family, id)`; nothing is rejected,
the bound (12) and the per-family slot (rule 165) are unchanged,
`accessScreen` is shipped per candidate.

What BLOCKED proves is decided by the CLEARANCE POLICY, never by the orebody
type (closeout B), and every screen result declares it as
`accessScreen.authority`. `anchor_standoff` raises the stand-off above the
configured value exactly when `basis != "EXACT"`, so:

- EXACT (`ExactClearance`): the screen anchor IS the stage-4 anchor and the
  gates are the same gates — BLOCKED is a NECESSARY CONDITION, and the
  tabular test pins `blocked ⊆ failed` for every detailed candidate and
  `blocked = 0` for every FEASIBLE one.
- CONSERVATIVE (`ConservativeClearance` / `RefinedConservativeClearance`):
  the screen anchors sit at the COARSE stand-off while stage 4 may refine
  the bound, shrink the stand-off and move the entry — BLOCKED is a
  HEURISTIC. The subset contract is not applied and not tested there; the
  warped test pins only the declared authority and that the prefix still
  rejects nothing.

Measured after (`golden/phase20c1_q_layout_v2.json`,
`phase20c1_q_vs_s_layout.json`, `phase20c1_q_shortlist_audit.json`): winner
unchanged on the 6 previously decided cases with ZERO metric drift (the
KD-tree vertex pre-filter in `nearest_on_polyline` is bit-identical, tested
on random and on-vertex tie queries); GEOMETRY-STRESS becomes SUCCESS in the
PRODUCTION search with `SWITCHBACK-k1-p+20-CW-s50-g0.100` (21 / 21
accesses); feasible counts 5 → 12 (TABULAR, CUT_AND_FILL), 3 → 10
(WARPED-301), 5 → 10 (IRREGULAR); shortlist yield TABULAR 12 / 12 validated
pass (9 switchbacks), WARPED-301 10 / 12, GEOMETRY-STRESS 1 / 12;
`winnerMissedByShortlist` false 7 / 7 and `missedFamilies = []` 7 / 7
(exhaustive feasible 17 / 13 / 1 vs production 12 / 10 / 1 on TABULAR /
301 / STRESS — the remaining gap is the bound, not a missed family or
winner). The screen's family AUC numbers are unchanged by construction (the
proxy itself was not touched). Cost: the screen adds the evaluator-free gate
sweep to stage 2; TABULAR-REFERENCE production search measured 23.4 s
unloaded (stage 1+2 incl. screen 15.5 s, stage 4 7.8 s; 14.2 s before
20C.1, 12 candidates validated instead of 5) — above the ≤ 20 s report
target of the 20C.1 directive, reported as such, not gated.

### W — WARPED_VEIN multi-seed feasibility survey (diagnostic only)

Instrument: `python -m minegen.regression warped-seeds`
(`golden/phase20c1_closeout_warped_seed_survey.json`), the PRODUCTION layout-v2
search on `RANDOM_WARPED_VEIN` seeds 301–332 (32 seeds, one fault, the
fixed list `WARPED_SURVEY_SEEDS`), recording per seed the outcome, the
funnel (cheap-feasible / shortlist / detailed feasible), the dominant typed
failure with its stage (among stage-4 failures when any candidate reached
stage 4), the dominant per-level access failure, the clearance picture
(required vs the best certified conservative minimum, error bound,
COARSE / REFINED basis) and the serviceable / accessible level counts.
Nothing is tuned, changed or persisted by the survey.

Measured (commit W): 32 / 32 seeds realize; **9 / 32 SUCCESS** (301, 305,
317, 318, 319, 326, 328, 329, 332 — 6 spiral winners, 3 switchback) and
23 NO_FEASIBLE_CANDIDATE. Every seed reaches stage 4 with 3–59 cheap-feasible
candidates (12 shortlisted, 3 on seed 302 whose ramps leave the world), so
the funnel is never starved at stage 2. Dominant stage-4 failure on the 23
failing seeds: `LEVEL_ACCESS_INFEASIBLE` 18, `ABOVE_TERRAIN` 5 (the main
ramp breaks the surface — bodies that sit high under relief); the dominant
level-access reason is `GRADE_LIMIT` 17 and `INSUFFICIENT_RAMP_PILLAR` 4
(2 seeds have no access failure at all because no candidate survived the
centerline stage). Clearance is NEVER the binding constraint: the best
certified conservative minimum is 22.7–116.8 m against the 10.59 m
requirement on every seed, with the stage-4 REFINED_CONSERVATIVE basis
(error bound 5.39 m) applied on all 32. Serviceable levels are 7–14 of
9–18 required (implicit bodies leave 1–6 required levels without an
orebody section, reported and excluded per rule 141); the best candidate
reaches 0–14 accessible levels, and on 9 failing seeds it serves all but
1–3 levels. Reading: for irregular bodies the loss is concentrated in the
level-access connector (a one-turn CS branch with a chord-exact gradient
from a junction lattice inside the elevation window to a footwall anchor
placed on the numerical section's principal axis) — the entry's elevation
and horizontal offset from the ramp exceed what 0.12 can bridge inside the
window on 17 seeds. That points at the Phase 20C.2 WARPED level-development
contract (section(z) local frame, anchor placement following the local
trace) and NOT at clearance, the shortlist or the ramp families; no
threshold, policy or default is changed by this phase.

### Closeout B — the screen's authority is the clearance policy's, and it was measured

`python -m minegen.regression layout-v2-screen-audit`
(`golden/phase20c1_closeout_screen_audit.json`) validates EVERY cheap-feasible
candidate (`detailed_all=True`) and counts the levels the stage-2 screen
reported BLOCKED that stage 4 then SERVED — a FALSE BLOCK. Measured:

| case | basis | authority | validated | false blocks | inside the production shortlist |
|---|---|---|---|---|---|
| TABULAR-REFERENCE | EXACT | NECESSARY_CONDITION | 57 | 0 | 0 |
| GEOMETRY-STRESS | EXACT | NECESSARY_CONDITION | 21 | 0 | 0 |
| ACCESS-INFEASIBLE | EXACT | NECESSARY_CONDITION | 57 | 0 | 0 |
| CUT_AND_FILL | EXACT | NECESSARY_CONDITION | 57 | 0 | 0 |
| WARPED_VEIN-301 | COARSE_CONSERVATIVE | HEURISTIC | 48 | 27 | 3 |
| WARPED_VEIN-307 | COARSE_CONSERVATIVE | HEURISTIC | 35 | 2 | 0 |
| IRREGULAR-REACH-EXCEEDED | COARSE_CONSERVATIVE | HEURISTIC | 48 | 27 | 3 |

Zero on every exact case is the necessary-condition contract holding; 56 on
the conservative side is the coarse stand-off being wrong about levels the
refined stage-4 policy can reach. The claim "provably unservable" is
therefore removed from the conservative side of rule 176 and from the code,
`accessScreen.authority` declares which contract applies, and the
`blocked ⊆ failed` test is applied only under EXACT.

Dropping the prefix on the conservative side was then ATTEMPTED (the key
becomes proxy → family → id there) and REVERTED: it fails the family-yield
acceptance
(`golden/phase20c1_closeout_ordering_attempt_shortlist_audit.json`) —
WARPED-301 loses the SWITCHBACK family again (`missedFamilies` [] →
['SWITCHBACK'], production feasible 10 → 3), exactly the regression the Q
screen was introduced to fix; the other three acceptance items held
(`winnerMissedByShortlist` false 7 / 7, GEOMETRY-STRESS SUCCESS with 21 / 21
accesses, the six decided winners unchanged). The heuristic prefix is kept
on the conservative side as an ORDERING HEURISTIC ONLY. Ordering that side
without a mis-blocking heuristic — by improving the stage-3 proxy so it can
see level-access feasibility — is a Phase 20C.2 candidate, recorded, not
attempted here. Post-revert the production search is bit-identical to the
merged 20C.1 baseline (`phase20c1_closeout_vs_q_layout.json`: 0 contract
regressions, 0 metric drift).

### Closeout A — the pooled AUC was mis-pooled, and the shortlist test proved nothing

A-1. `audit_yield` concatenated each family's per-case rank lists and scored
one Mann–Whitney AUC over the union. Family-internal ranks restart at 1 in
every case, so that compares different scales (case A's pass rank 2 against
case B's fail rank 5). `pooled_rank_auc` now pools PAIR-WEIGHTED WITHIN CASE
(`Σ wins / Σ pairs` over per-case counts), records `casesUsed` /
`casesWithoutPairs` / `rankPairs`, and is unit-tested against a fixture where
two internally PERFECT cases (AUC 1.0 each) pool to 1.0 correctly while the
concatenated statistic answers 0.75. The corrected numbers are in the table
above: the Q conclusion holds.

A-2. `phase20c1_q_yield_before.json` / `_after.json` are historical artifacts
(the commit-S and commit-Q searches). Re-running the production search now
would fold closeout B into them, so `python -m minegen.regression.repool`
recomputes ONLY the `pooled` block from each file's own per-case rows —
`familyRank` and `detailedPass` are all the Mann–Whitney counts need — and
stamps `pooledCorrection`. Verified: `cases[]` is byte-identical before and
after, the only key changes are `pooled` and the added `pooledCorrection`.

A-3. `test_shortlist_is_ordered_by_screen_then_proxy` ended in
`assert (...) >= worst or c.params.family is not None`; every candidate has a
family, so the clause was always true and the test constrained nothing. It is
replaced by `test_shortlist_is_exactly_the_reconstructed_bounded_selection`,
which re-implements stage 3 from the candidate results (policy-aware key,
bound, rule 165 family reservation, re-sort) and compares candidate ids
exactly, plus a RED-FIXTURE PROOF: with the key reduced to the id, to the
proxy alone, or with the screen prefix inverted — or with the bound off by
one — the same assertion fails.

### Closeout R — the 32-seed survey re-run on the closeout tree

`python -m minegen.regression warped-seeds` was re-run on the closeout-B tree
over the same fixed seeds 301–332
(`golden/phase20c1_closeout_warped_seed_survey.json`, compared in
`phase20c1_closeout_warped_seed_before_after.json`). Closeout B reverted its
ordering change, so the production search is unchanged and an identical
result is the expected — and confirming — outcome. Measured: **32 / 32 seeds
identical** on every tracked field (status, winner, cheap-feasible /
shortlist / detailed-feasible counts, dominant failure and its stage,
dominant level-access reason, serviceable vs accessible levels, clearance
basis / bound / required, per-seed level-access reason histogram). Aggregates
therefore also hold: 9 / 32 SUCCESS, dominant stage-4 failure
`LEVEL_ACCESS_INFEASIBLE` 18 / `ABOVE_TERRAIN` 5, level-access reasons
`GRADE_LIMIT` 695 · `INSUFFICIENT_RAMP_PILLAR` 256 · `TURNOUT_NOT_STRAIGHT`
84 · `OREBODY_CLEARANCE` 55 · `CONNECTOR_UNAVAILABLE` 7 ·
`JUNCTION_SPACING_CONFLICT` 3. Because nothing moved, there is no
`GRADE_LIMIT` change to attribute — and had there been one, the first
explanation would have been a change in which candidates reached stage 4,
not a change in refinement, which closeout B does not touch.

Clearance (R-4, confirmation not suspicion): all 32 seeds report
`bestClearanceBasis = REFINED_CONSERVATIVE` with `refinement.applied = true`,
factor 2, resolved lattice spacing (2.5, 2.5, 0.625) m and per-seed cell
counts spanning 74 400 – 1 251 292. The identical `errorBound` 5.3855 m on
every seed is the CONSEQUENCE of one factor and one resolved spacing, not a
sign that refinement was skipped. No seed is COARSE-only and none has
`applied = false`.

Runtime: the survey took 1 048 s before and 707 s now. Since the search is
byte-identical, that is machine load, not a code effect — the W baseline ran
concurrently with the PR #22 gate and the 22-case legacy golden on the same
four cores. TABULAR-REFERENCE re-measured on the closeout tree: **15.8 s**
unloaded (stage 1 + 2 including the screen 10.1 s), against 23.4 s measured
under load during 20C.1-Q; both are the same code, so the ≤ 20 s target is
not claimed as met by any change in this closeout — runtime work stays a
Phase 20C.2 item.
