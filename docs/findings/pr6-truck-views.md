# Finding PR-6 — the chased truck hides the way ahead

Status: **ADDRESSED in hardening PR-6** (`frontend/src/walkthrough/cameraView.ts`,
`avatars.tsx`, `vehicle.ts::truckLayout`, `WalkthroughPlayer.tsx`, the HUD and
the viewer store — presentation only; no body, physics, spawn or chase
resolution change). Rule 228 records the contract; the instrument is the
frame-coverage test in `frontend/src/walkthrough/cameraView.test.ts`.

## What Park saw

PR-4 review, the same message as the seam finding: "트럭의 경우 앞을 너무
가려서 실제로 의미가 없는데 … 트럭을 투명도 높여서 표현하거나 3/1인칭 전환이
가능하도록 해야할까" — in the third-person truck view the body fills the
frame and the drive ahead cannot be read. Park chose both remedies.

## What was measured before the change

Instrument: 320 × 190 pixel-centre rays through the MineCanvas camera (45°
vertical field of view, 1600 × 950) at the PR-4 default tail line (5 m back,
0.9 m right, −18°, aimed one body length ahead), unobstructed, against the
truck's planning boxes (`truckLayout`). "Forward lane" = the central quarter
of the frame width between 20 % and 60 % of its height — where the floor
ahead sits when the line aims one body length ahead.

| class | whole frame | central third | forward lane |
| --- | --- | --- | --- |
| UG ADT 45 t | 18.0 % | 24.9 % | 50.9 % |
| UG ADT 60 t | 21.3 % | 27.6 % | 58.3 % |
| RDT 40 t | 22.3 % | 31.7 % | 61.9 % |

More than half of the forward lane sits behind the body in every class.

## What changed

1. **Ghost body (chase view).** The VEHICLE avatar is drawn translucent
   (`GHOST_OPACITY` 0.32, depth write off) with its planning-box edges
   outlined, so the lane reads through the body while the envelope stays
   legible. Geometry unchanged: the same coverage, at 32 % opacity.
2. **Cab view.** F (or the HUD toggle) switches the ephemeral
   `viewerStore.walkCameraView` to CAB: the camera sits at the body's
   first-person eye — the driver's seat inside the cab box (≈ 2.41 / 2.80 /
   2.75 m above the floor for the 45 t / 60 t / RDT), the miner's 1.6 m eye,
   the drone front — rotated by the body yaw, looking along the orbit
   (pitch clamped to [−60°, +45°], level at the switch). The cab shell and
   windscreen are not drawn from inside; person / drone avatars are hidden.
3. **One layout authority.** `vehicle.ts::truckLayout` now yields the boxes
   the avatar is built from AND the cab eye; the 45 t numbers reproduce the
   PR-4 avatar exactly (tested).
4. **Lamp point.** The headlamp beam leaves the body's lamp point in either
   view (`lampOffset`: the truck's headlights on its bumper, the cap lamp,
   the drone's front). Found on the first acceptance tour: with the beam
   at the cab seat, looking down in the cab view lit the own hood from
   0.9 m and the frame blew out to the lamp colour.
5. **Ghost in the cab view too.** Found on the second tour: even with the
   beam moved, a SOLID hood filled the lower half of the frame with one
   flat lamp-lit plane when the driver looked down. The truck stays the
   ghost in the cab view (cab shell hidden), so the own hood reads as an
   outline over the floor.

## What was measured after

| view | measurement |
| --- | --- |
| CAB, level pitch, every class | 0 % of the frame, 0 % of the forward lane |
| CAB, 20° down | own bumper at the frame bottom: 45 t 17.2 %, 60 t 11.9 %, RDT 0 %; forward lane 0 % |
| CHASE ghost | coverage as above, drawn at 32 % opacity with outlined edges |

## Residual

No cab interior (dashboard, pillars) is modelled — the avatars stay
procedural primitives without assets (rule 15). The ghost is an X-ray style
blend (overlapping parts mix, opacity constant). No mirrors or rear camera
in the cab view. Locomotion, colliders, spawn and the chase occlusion rule
are PR-4's, unchanged.
