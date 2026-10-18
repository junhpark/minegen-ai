# Finding PR-5 — junction seam: wedges in the mouth and slits along the rim

Status: **FIXED in hardening PR-5** (`design/junctions.py`, `design/tunnel_mesh.py`,
`design/development_mesh.py` — a geometry change at the junction cut, not a
material / lighting change). Rule 227 records the contract; the instruments
are `backend/tests/test_junction_seam.py` (seam) and
`backend/tests/test_junction_passability.py` (traffic section, ramp caps
included since PR-5).

## What Park saw

A level entry seen from inside the access (PR-4 review screenshot):
wedge-shaped fragments of the DRIFT wall standing into the access, and black
slivers where the two tubes meet. The truck-view question raised in the same
message is PR-6.

## What was measured before the fix (TABULAR verification fixture)

| instrument | result |
| --- | --- |
| WEDGE — parent render triangles whose centroid lies inside the child envelope beyond one tolerance | 94 triangles, deepest 1.923 m |
| HOLE — eye rays leaving the union (back-face first hit, PR-5 draft criterion) | 149 of 67,840 |

Root causes, each confirmed on the geometry dump:

1. **Whole-quad parent vote.** The Phase 20D.1.1 rule kept a parent quad
   whole unless ≥ 6 of 9 surface samples were inside the child, so quads the
   child covered less than two thirds stood in the mouth (the wedges).
2. **Two tolerance surfaces.** The child was cut at `+tol` (its remainder
   began 0.1 m OUTSIDE the parent wall) while the parent was cut at `−tol`
   (its rim ended 0.1 m INSIDE the child wall): a tol-wide slit ran along
   every seam, and a ray hugging the child wall slipped behind the step into
   rock.
3. **Caps.** The ramp's PORTAL / TERMINAL caps were never cut — the fixture's
   ramp ends 1.9 m after its L04 turnout and stood its whole terminal cap
   across the access (the PR-4 doorway probe excluded caps and never saw
   it); drift end caps were cut at `+tol`, leaving a tol-wide ring notch
   around a crosscut piercing the cap at an extremity station.
4. **Sills.** PR-2's sill was ONE quad between the two chord ends oriented
   away from the parent; where the parent wall stands to the chord height at
   the jambs (within tol of the chord ends) the quad collapsed and the whole
   tol-high riser strip stayed open — the floor-seam escapes at the level
   entries; a flat strip could not be oriented at all.

## Fix (rule 227)

Parent judged exactly at `−tol` on the floor-lowered child (walls, roof,
drift end caps, ramp caps); child judged at the parent's exact surface
(`CHILD_JUDGE_LEVEL`) on the floor-lowered parent; sills as sampled risers
from the parent floor boundary (side edges and the floor's end edges),
oriented into the rock by the step direction; render-scale cleaning of
every remainder (`_clean_render_loop`).

## After the fix

| instrument | result |
| --- | --- |
| HOLE — rays reaching rock before the first front-face hit | 0 of 67,840 (back-face hits, diagnostic: 26 (all the parent's −tol lip, role DRIFT)) |
| WEDGE — beyond 1 × tol / beyond the 3 × tol construction bound | 44 / 0, deepest 0.167 m |
| doorway probe (ramp caps included) | 0 hits |
| ramp L04 terminal cap | L04 터미널 캡: 팬 7 생략 · 12 클립 · 대체 삼각형 22(캡 삼각형 19 → 22), 램프 벽 쿼드 15 클립 · 0 미클립 · 대체 31; 통행 탐침 명중 0 |

Residual, recorded: the parent's one-tolerance lip at every jamb (0.1 m for
the 5 m tunnel) and the chord sag inside the clip band (≤ 2 × tol); a banked
junction floor and a watertight all-development union remain Phase 20D.

## Round 2 — the default scenario failed (found by the PR-6 acceptance tour)

The default "Create mine" scenario (13 levels, 247 declared junctions — 13
RAMP_ACCESS, 13 ACCESS_DRIFT, 221 DRIFT_CROSSCUT) built its ramp tunnel mesh
but FAILED its development mesh under the PR-5 commit `4b6236e`:
`JUNCTION_CLIP_TOPOLOGY: JUNCTION:L01:S-08: floor quad (1, 10) boundary not
representable after 10 subdivisions (… corner sd [inf, inf, inf, inf] …)`.
The guided-workflow e2e builds that mesh, so FULL would have failed at its
e2e component; the TABULAR fixture's 8 extremity stations had passed by
luck.

Cause: a crosscut on a drift EXTREMITY has its floor centre line IN the
drift's end plane. The judging envelope reported every point beyond its
ring span as +inf, so points ON the plane read "5 m inside" (the
floor-lowered drift) or "outside" at floating-point whim, and a quad EDGE
lying in the plane never converged under subdivision.

Fix (PR-5 round 2): (1) `TubeEnvelope.with_end_planes` — a judging envelope
declares the REAL ends that are surfaces of the solid it stands for (the
parent's two ends on the child side; the child's far end on the parent
side; never the child's OPEN junction end, where a lip would stand a fin of
parent cap in the mouth), and a declared end plane joins the profile's
half-planes so the field is continuous and exactly 0 on the plane; (2) a
chord-fidelity sample that fails ON a remaining jump (a window edge, an open
end) is re-judged one vertex-merge distance toward the loop interior.

| measurement | before round 2 | after |
| --- | --- | --- |
| default scenario development mesh | FAILED at L01:S-08 | SUCCESS: 247 junctions opened; parent wall quads clipped 4,015 / unclipped 0 / replacement 8,472; child floor quads clipped 703, child wall quads clipped 4,788 / unclipped 0 / replacement 12,131; 150.3 s on the 4-CPU session box |
| default scenario ramp tunnel mesh | SUCCESS (4,570 removed · 597 clipped · 1,248 replacement) | identical |
| TABULAR seam probe | 0 escapes / 0.1674 m deepest intrusion | identical |
| typed-junction · RT-42 · doorway probe tests | 45 passed | 45 passed |
