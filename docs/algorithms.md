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
- SWITCHBACK: `k` legs per level of equal length `ΔZ/(k·g) − π·R_min`
  joined by constant-sense minimum-radius hairpins; the pair drift of the
  footwall is absorbed by bulging the hairpin (`R_min + |drift|/2`); a
  landing straight closes the last cycle exactly on the deepest level.

Delivered-centerline diagnostics: per-edge gradient, chord-based plan
radius at interior vertices (exact for uniformly sampled arcs), unwrapped
heading change; family signature = cumulative / signed heading change,
turning length (R < 500 m), hairpin runs (same-sense runs ≥ 150°),
reversals (runs within 150°–210°), dominant folded azimuths (15° bins),
turn-direction consistency. Measured on the TABULAR reference: spirals
show ≈ 2 400–6 200° cumulative change, consistency 1.0, 0 reversals;
2-leg switchbacks 13 reversals; longitudinal ≈ 150° with ≤ 1.

Search: cheap stage on every candidate (grade ≤ g_max + 1e-9, plan radius
≥ R_min − 0.05 m, inside the world, monotonic, all serviceable levels
served), shortlist of 12 by the Phase 20B.1 D cheap LOWER BOUND of the
weighted total (`w_dev·(L/L_ideal + 0.5·meanAccess/reach) +
w_geom·(unusedGrade + 0.5·turningFrac + maxAccess/reach +
20·meanCurvature + 0.05·reversals + 0.02·hairpinRuns)`; geology, the
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
                  (Phase 20B.1 D-2: the measured family signature priced in —
                  a priori round coefficients, never reverse-engineered to
                  crown a family)
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
horizontal distance to the anchor ≤ 300 m. Connector: Dubins CSC with
R = R_min from the junction pose (ramp heading) to the anchor pose
(backbone heading, both senses); `α = θ0 − φ`, `β = θ1 − φ`, `d = |Δxy|/R`
in the Shkel–Lumelsky normalization; the shortest admissible word is
sampled every 2 m with points exactly on their circles; z is linear in
delivered chord length (constant edge gradient `Δz / Σchord`).

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
branch-to-ramp envelope separation ≥ 2 × width (10 m default) on samples
beyond the geometry-derived taper `s* = R·arccos(1 − (pillar + width)/R)`
(≈ 25.3 m for the defaults; quarter-turn + straight beyond one radius),
terminal always judged. Selection among the survivors stays
`(access_length_cost(L, P), L, junction chainage, sense)` (rule 163) — the
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

`EXACT` remains the analytic-body basis only; an implicit body is never
labelled EXACT (rule 134) — its bases are COARSE_CONSERVATIVE /
REFINED_CONSERVATIVE, both carrying their actual `latticeSpacing` and
`errorBound` in the candidate report.
