# Coordinate System

## Canonical mine coordinate system (backend, storage, API)

    X = East
    Y = North
    Z = Elevation / Up
    unit = meter

    +X = East, +Y = North, +Z = Up   (right-handed: X × Y = Z)

Every number that leaves the backend (JSON, GLB, NPZ) is in this system.
The string `"coordinateSystem": "ENU_Z_UP"` in scene payloads is a contract,
not a hint.

## World extent

    x ∈ [−size_x/2, +size_x/2]
    y ∈ [−size_y/2, +size_y/2]
    z ∈ [base_elevation − depth, terrain surface]

`WorldConfig.depth` is the model depth **below `TerrainConfig.base_elevation`**,
not an absolute bottom elevation. Defaults (base 300 m, depth 600 m) give a
model bottom at z = −300 m. The terrain surface may rise above the reference
elevation by up to `relief`.

## Angles

    Strike        = clockwise azimuth from +Y (North), degrees
    Dip           = angle below horizontal, degrees, 0 = flat, 90 = vertical
    Dip direction = strike + 90° (right-hand rule: dip is to the right
                    when looking along strike)
    Heading       = clockwise azimuth from +Y (North), degrees or radians
                    (same convention as strike)

Unit vectors derived from (strike, dip):

    u  (along strike)   = ( sin S,            cos S,            0 )
    v  (down dip)       = ( cos D·sin(S+90),  cos D·cos(S+90), −sin D )
                        = ( cos D·cos S,     −cos D·sin S,     −sin D )
    w  (normal)         = u × v
                        = ( −sin D·cos S,     sin D·sin S,     −cos D )

`u, v, w` form a right-handed orebody-local frame. Note that `w` points
**downward, to the footwall side** of the orebody (its z component is
`−cos D`). This is deliberate: footwall access offsets (CLAUDE.md rule 29)
are taken along `+w`, hanging-wall offsets along `−w`. For a tabular orebody:

    |u| ≤ length / 2
    |v| ≤ height / 2        (height = down-dip length)
    |w| ≤ thickness / 2

## Gradient

    gradient = vertical / horizontal     (e.g. 0.12 = 12 % = 1 : 8.33)

Never use rise/run over slope length. The grade-limited minimum centerline
length for a vertical change `dz` is

    L_grade = |dz| × sqrt(1 + g_max²) / g_max

## Gravity-aligned sweep frame (tunnels)

For ordinary ramps, drifts and crosscuts the profile frame at a centerline
sample with tangent `t` is:

    Z       = (0, 0, 1)
    forward = normalize(t)
    up      = normalize(Z − dot(Z, forward) × forward)
    right   = normalize(cross(forward, up))     # driver's right
                                                # (East when facing North)

Properties:

- `(right, forward, up)` is right-handed: `right × forward = up`.
- `up` always lies in the vertical plane containing `forward`; the tunnel
  floor is level across the section regardless of ramp gradient or curvature.
- Valid whenever `|dot(t, Z)| < 1`, i.e. for every gradient a ramp can have.
  Near-vertical raises/shafts need a different frame (v0.2).

Implementation: `backend/src/minegen/core/coordinates.py::gravity_aligned_frame`.

## Fault zones

For a fault plane with unit normal `n` through `origin`, the signed
perpendicular distance of a point `p` is `d = dot(p − origin, n)`. Zones are
classified by `|d|` against **half-widths**:

    |d| ≤ core_half_width                           core
    core_half_width < |d| ≤ influence_half_width    damage zone
    |d| > influence_half_width                      undisturbed

## Three.js mapping (frontend only)

Three.js is Y-up. The conversion happens at the rendering boundary and
nowhere else (`frontend/src/geometry/coordinateTransform.ts`):

    mineToThree(x, y, z)  = [ x,  z, −y ]
    threeToMine(x, y, z)  = [ x, −z,  y ]

This is a pure rotation (determinant +1), so handedness is preserved and no
mesh winding needs to be flipped.

Backend code must never contain this mapping (CLAUDE.md rule 4).
