# Engine integration — future Unity / Unreal interoperability

**Status: ARCHITECTURE PLACEHOLDER.** No Unity or Unreal integration is
implemented. This document freezes the engine-neutral contracts (rules
99–100) that keep future engine clients possible without ever making an
engine the source of truth.

## 1. Canonical coordinate system

Every persisted engineering artifact uses the MineGen-AI canonical system:
**X = East, Y = North, Z = Up, unit = metre** (see
`docs/coordinate-system.md`). No artifact stores Three.js-, Unity- or
Unreal-native coordinates.

## 2. Backend is the source of truth

                 MineGen-AI backend
                        │
                canonical artifacts
                        │
        ┌───────────────┼────────────────┐
        │               │                │
   Web / Three.js      Unity           Unreal
        │               │                │
   adapter only      adapter only     adapter only

Engineering calculations (geometry, graph, time, placement) remain
backend-authoritative. Engine clients may provide interaction and
rendering only.

## 3. Current Three.js adapter boundary

The web client converts backend ENU Z-up coordinates to renderer space
exclusively through `mineToThree` at the rendering boundary. This is the
model for all future adapters: one explicit, tested transformation at the
client edge, nothing engine-specific upstream of it.

## 4–5. Intended Unity / Unreal adapter boundaries

Future Unity and Unreal clients must each implement their own explicit
coordinate adapter. **No axis mapping or handedness convention is frozen
here** — Unity (left-handed, Y-up) and Unreal (left-handed, Z-up,
centimetres) conventions must not be assumed implicitly. When adapters are
implemented they require explicit regression tests for: axis mapping,
handedness, determinant/winding implications, metre-to-engine-unit
scaling, normal orientation, triangle winding, and round-trip point
transformation.

## 6. Stable object identity

Engine clients must reference stable backend IDs (network node/edge ids,
stope ids, task ids, communication asset ids, sensor asset ids) — never
array indices, Three.js UUIDs, Unity GameObject instance IDs or Unreal
Actor runtime pointers/names. Engine runtime objects exist only behind a
temporary `backendStableId -> engineRuntimeObject` mapping.

## 7. JSON + GLB division of responsibilities

    geometry:        GLB / typed geometry payloads (tunnel mesh already GLB)
    semantics/graph: typed JSON with stable IDs (network, stopes, ...)
    time:            timeline.json
    infrastructure:  communication.json, sensors.json

Do not encode the whole digital twin into one mesh file; do not bake
engine-specific coordinates into GLB; FBX is not a source-of-truth format.

## 8. Timeline / infrastructure consumption

Engine clients consume `timeline.json` for 4D state (via the same
state/chainage contracts the web client evaluates) and
`communication.json` / `sensors.json` for placement semantics. Placement
payloads contain planning semantics only — no prefab names, asset paths,
materials or decorative mesh references (semantic/visual separation).

## 9. Self-description / export envelope

Artifacts carry explicit status, model/solver identifiers, stable IDs and
`sourceRevision`. A future export envelope (adding `schemaVersion`,
`coordinateSystem: ENU_Z_UP`, `units: m` at artifact level where missing)
is the intended contract for external-engine consumption; it will be
introduced as a wrapping/export concern rather than churning historical
Phase 01–11 artifact schemas.

## 10. Future integration candidates

REST snapshot consumption → WebSocket incremental updates → MQTT / OPC-UA
bridges for digital-twin synchronization. All of these are **FUTURE WORK**;
none is implemented, and Phase 12 introduces no engine SDK dependency.
