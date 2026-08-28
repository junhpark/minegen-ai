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

## Phase 02 — synthetic world

All fields are NumPy arrays on the block grid (``world/voxel_grid.py``).
Grid: x, y centered; z from ``base_elevation − depth`` to
``base_elevation + relief`` — the top is taken from *configuration* so the
shape is identical for every seed of a scenario (seed-to-seed comparisons are
element-wise meaningful).

### Terrain (``world/terrain.py``)
Seeded fBm value noise: ``octaves`` lattices of ``4·2^k`` cells, cubic
upsampled (``scipy.ndimage.zoom``), summed with amplitude ``0.5^k``, then
normalized so ``mean = base_elevation`` and ``max − min = relief``.
Bilinear sampling for block-center air tests.

### Orebody (``world/orebody.py``)
Analytic slab in the strike/dip frame (rule 28); ``contains`` is an exact
half-extent test. Source of truth: never reconstructed from voxels. Box mesh
with outward CCW winding. ``footwall_point(u, v, offset)`` lies ``offset``
past the footwall contact along ``+w`` (rule 29, used by Phase 03).

### Block fractions (``world/block_model.py``)
Each block is sub-sampled ``2×2×2`` (configurable). From one shared pattern:

- ``solid_fraction`` = share of sub-samples at or below the terrain surface
  (terrain sampled once at every XY sub-position). ``< 0.5 → AIR``.
  Not persisted.
- ``ore_fraction`` = share of sub-samples inside the analytic orebody **and**
  below the terrain. ``ore_flag = fraction ≥ 0.5``. Ore ⊆ solid, so an ore
  block is never AIR. Evaluated per z-layer inside the orebody bounding box.

So ``orebody.volume()`` is the geometric mineralized body (may outcrop) and
``block_model.ore_volume()`` is in-situ ore. Buried default world: sampled
volume within 0.2 % of the analytic solid. Outcrop regression: block in-situ
volume within 1 % of a 400k-point Monte-Carlo reference.

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

### Memory (default 1200×1200×600 m world, 10 m blocks)
``120 × 120 × 70 = 1,008,000`` blocks, 22.1 MB total:
uint8 rock_type, fault_zone (1.0 MB each); bool ore_flag (1.0 MB);
float32 ore_fraction, grade, rock_quality, fault_signed_distance,
fault_influence (4.0 MB each). Generation ≈ 0.45 s.
## Phase 03 — design cost evaluator & level access targets

### DesignCostEvaluator (``design/cost_field.py``, rules 41–42)
Continuous query ``evaluate_points(N×3)``; no dense volume.

    rock_quality     trilinear (``RegularGridInterpolator``) on block centers;
                     coordinates clamped to the center lattice (no extrapolation);
                     AIR blocks pre-filled from the topmost rock block of their
                     column so near-surface values are not pulled to 0
    rock_penalty     w_rock · (100 − rq) / 100                      (w_rock = 2)
    fault_penalty    Σ_f analytic: core_penalty_f if |d_f| ≤ core_f;
                     damage_f · (infl_f − |d_f|)/(infl_f − core_f) in the damage zone
    orebody_distance analytic oriented-box SDF (negative inside)
    orebody_penalty  w_ster · max(0, 1 − (sdf − buffer)/range)  (5, buffer 5, range 15)
    total            base(1) + rock + fault + orebody; +inf when invalid

Hard rejections (with reasons): OUTSIDE_WORLD (block-grid extent),
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

The volumetric level-development mesh is deliberately DEFERRED: independent
capped tubes overlapped at T-junctions would leave false internal walls at
every crosscut mouth; junction openings belong to a later mesh/walkthrough
step. Phase 08 ships the geometry contract (`levels.json`) and the topology
contract (network) plus centerline/graph visualization only.
## Phase 09 — longhole stopes              (pending)
## Phase 06 — tunnel mesh, gravity-aligned sweep (`design/tunnel_mesh.py`, rules 65–67)

Input: the Phase 05 artifact only (rule 64) — per-segment validated effective
centerlines plus shared boundary tangents. The centerline is the tunnel FLOOR
centerline.

1. **Profile** (`build_profile`): closed horseshoe polygon, K = archSegments+3
   vertices, counter-clockwise. Width/height come exclusively from
   `RampConstraints`; `TunnelProfile` holds shape + meshing parameters only
   (wallHeight, archSegments, ringMaxSpacing, ringMaxTurnDeg, creaseAngleDeg).
   The circular crown radius is DERIVED: `rise = H − Hw`,
   `R_c = (a² + rise²) / (2·rise)`, `a = W/2` (default 5×5, wall 2.5 →
   semicircular R_c = 2.5). Legacy persisted `width`/`crownRadius` fields are
   dropped on load (deprecated migration).
2. **Rings** (`build_ring_chain`): every polyline vertex is a ring; edges
   longer than `ringMaxSpacing` (2 m) are split LINEARLY — rings lie exactly
   on the validated polyline, which is never smoothed, spline-fitted, moved
   or redesigned (rule 65). Consecutive segments share ONE logical boundary
   ring whose tangent is the persisted shared boundary tangent; interior
   polyline vertices use the mean of adjacent chord directions, subdivision
   rings the chord direction. `maxLocalTurnDeg > ringMaxTurnDeg` (7°) →
   FAILED (Phase 05's ≤2 m output on R ≥ 18 m gives ≤ 6.4°).
3. **Sweep** (`sweep_rings`): the existing `core.coordinates.
   gravity_aligned_frame` (rule 26) at every ring — profile plane ⊥ 3D
   tangent, plumb walls, zero floor cross-slope, no roll. Profile origin =
   floor centerline point.
4. **Logical mesh** (`build_logical_mesh`): one continuous quad-strip tube
   (2 tris/quad) + PORTAL_CAP/TERMINAL_CAP fans with the apex at the profile
   CENTROID (a floor-centerline apex would degenerate the floor fan tris).
   Caps are temporary closure surfaces for standalone topology/volume QA —
   removable when crosscuts/walkthrough arrive.
5. **Topology validation** (`validate_topology`, rule 66): manifold (every
   directed edge once), watertight (every undirected edge exactly twice),
   zero degenerate triangles, outward orientation via signed volume > 0.
   Checked on the LOGICAL mesh before render splitting.
6. **Envelope validation** (`validate_envelope`, rule 66): all ring profile
   vertices against OUTSIDE_WORLD / INSIDE_OREBODY / OREBODY_BUFFER /
   RESTRICTED_ZONE (always hard) and ABOVE_TERRAIN under the portal
   profile-burial transition — terrain intersection allowed only until the
   full profile is first buried; breakthrough afterwards is a violation.
   OUTSIDE_WORLD caused solely by exceeding the world TOP is the same portal
   case and is governed by the transition. `minimum_surface_cover` is a
   centerline constraint and is NOT re-applied to the roof.
7. **Volumes** (rule 67): the profile is ⊥ the 3D tangent, so
   `nominalExcavationVolume = analyticProfileArea × length3d` with NO 1/cosθ
   correction, where `analyticProfileArea = W·H_wall + R_c²(θ − sin θ)/2`
   (θ = 2·asin(W/2R_c)) is EXACT and invariant under `archSegments`
   (blocker 2 regression). `meshEnclosedVolume = Σ v₀·(v₁×v₂)/6` over the
   closed logical mesh; `|Δ| / nominal ≤ 1 %` is a hard QA gate that now
   includes the tessellation bias (`tessellationBiasPct`, inscribed polygon,
   ~1/n²: −1.12 % at 8 segments — a legitimate QA failure — vs −0.28 % at
   the default 16).
8. **Render mesh** (`build_render_mesh`): crease-split vertices (creaseAngle
   40°, vertex 0 always split as the UV seam), normals accumulated
   angle-weighted from ACTUAL triangle geometry (not rotated 2D normals),
   u = perimeter fraction [0,1], v = 3D chainage (m). Logical vs render
   vertex counts are reported separately; `geometricallyClosed` is verified
   by position-weld on the render mesh.
9. **GLB** (`design/glb_writer.py`): minimal deterministic struct+json+numpy
   writer (no new dependency, rule 16) — one vertex set, one glTF primitive
   per segment (extras: segmentId, effectiveSource) + cap primitives
   (extras: role). Byte-identical for identical input.

Failure at any gate produces `status = FAILED` with an explicit
`failureReason`; the report is always persisted, the GLB only on SUCCESS.
Known limitations (technical debt): global self-intersection is NOT checked
(`selfIntersectionCheck = NOT_IMPLEMENTED`) and the envelope samples profile
VERTICES (violations strictly between samples can escape detection);
`RampConstraints.clearance` is not yet a hard constraint.

**Default-scenario envelope conflict — RESOLVED upstream (PR #3 blocker 1).**
The Phase 04/05 centerline formerly passed at 8.00 m minimum orebody sdf and
the excavation envelope clipped the 5 m buffer by up to 0.37 m near L11–L12
(`OREBODY_BUFFER × 9`). Resolution is structural, not a validator weakening
or buffer tune: the profile/envelope geometry was extracted to the shared
lower-level ``design/profile.py``; Phase 04 primitive feasibility became
direction-aware (actual per-sample frames sweeping the profile boundary);
launchability filters trapped arrivals; and bounded chain backtracking
escapes arrivals that strand the next level. Rejected alternatives, measured:
hard `buffer + reach` standoff (footwall-approach poses inescapable at
R = 18 m — L03 INFEASIBLE at 7 expansions) and soft-cost shaping (not a
guarantee; min sdf 7.47 m / 5.86 m across two shapings). The Phase 06 gate
is unchanged and remains the exact authority.

## Phase 10 — 4D sequencing                (pending)
## Phase 11 — router OSP (greedy, CP-SAT)  (pending)
## Phase 12 — generic sensor OSP           (pending)
