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

### Hybrid A* (``design/astar_3d.py``, rules 52–57)
State `(x, y, z, heading, cover_established)` continuous; key
`(⌊x/5⌋, ⌊y/5⌋, ⌊z/1⌋, round(θ/Δθ) mod 16, cover)`. One batched evaluator
call per expansion (45 points); a primitive is rejected if any sample is
invalid; cost = trapezoid of cost/m over 3D arc length (+ turn penalty).
Cover transition: before `minimum_surface_cover` is first reached,
`INSUFFICIENT_COVER` samples are forgiven; afterwards never.

    h  = sqrt(max(L_dubinsCS, Δz/g)² + Δz²) · min_cost          (admissible)
    f  = g + ε·h                                                  (ε = 2)
    order = (⌊f / bucket⌋, tie_break(pose), f),  bucket = 2·L_h·min_cost
    tie_break (cone):  Δz/g > standoff → |d_h − standoff| (3·R ring)
                       else            → |L_dubinsCS − Δz/g|   (approach cone)

Cell dominance on f (rule 56). Goal shot attempted at pop when d_h ≤ 5·L_h.
States below `target.z − 0.5` are not expanded (monotonic decline).

### Chaining (``design/mine_designer.py``, rules 21–22, 53–54)
Greedy per level: every valid candidate (K ≤ 5) is searched from the current
terminal pose; first segment heading = azimuth(portal → candidate), later
segments inherit. Selection = segment cost + next_level_accessibility ×
min_cost. Structured `INFEASIBLE` / `NO_VALID_CANDIDATES` / `SKIPPED`.

### Measured (default scenario, one fault, 13 levels, K = 5)
65/65 candidate searches succeeded; 51,631 expansions total (L1: 1.0k–6.5k,
lower levels mostly 40–250); raw decline 3,834.4 m vs Σ admissible bounds
3,825.2 m (each segment at the grade-limited length); generalized cost
7,221 (cost/bound 1.89 = mean cost/m); wall 32 s at ≈ 1,900 expansions/s.
Small scenario, ε = 1.0 / 1.5: EXPANSION_LIMIT at 20k (plateau); ε = 2:
3,152 expansions.
## Phase 05 — smoothing + revalidation     (pending)
## Phase 06 — gravity-aligned tunnel sweep (pending)
## Phase 07 — MineNetwork                  (pending)
## Phase 08 — levels & crosscuts           (pending)
## Phase 09 — longhole stopes              (pending)
## Phase 10 — 4D sequencing                (pending)
## Phase 11 — router OSP (greedy, CP-SAT)  (pending)
## Phase 12 — generic sensor OSP           (pending)
