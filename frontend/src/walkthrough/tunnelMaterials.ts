/**
 * Single shared tunnel material set (PR #13 blocker 1): BOTH the static
 * TunnelMeshLayer and the temporal TemporalTunnelLayer consume these two
 * module-level materials, so the deterministic scenario-seeded rock/joint
 * texture policy cannot diverge between contexts and no per-segment or
 * per-layer material duplication can appear (draw calls unchanged; the
 * pre-existing cap treatment — translucent 0.55 — was already identical
 * in both layers). Visibility semantics are owned by the layers, never by
 * this module.
 */
import { DoubleSide, MeshStandardMaterial, type Texture } from 'three'

export const TUNNEL_MATERIAL = new MeshStandardMaterial({
  color: '#e2dbcf', // 20B.3: '#c9c2b6' → '#e2dbcf' (material × texture was too dark in ORBIT / 4D)
  roughness: 0.95,
  metalness: 0.0,
  side: DoubleSide, // visible from inside the void too
})

export const CAP_MATERIAL = new MeshStandardMaterial({
  color: '#a99f91', // 20B.3: '#8f877a' → '#a99f91'
  roughness: 1.0,
  metalness: 0.0,
  side: DoubleSide,
  transparent: true,
  opacity: 0.55,
})

/** every material that must carry the shared rock texture */
export const TUNNEL_ROCK_MATERIALS: readonly MeshStandardMaterial[] = [
  TUNNEL_MATERIAL,
  CAP_MATERIAL,
]

/** idempotently attach (or clear) the shared rock texture on ALL tunnel
 * materials — the single texture-application path for both layers. */
export function applyRockTexture(map: Texture | null): void {
  for (const material of TUNNEL_ROCK_MATERIALS) {
    if (material.map !== map) {
      material.map = map
      material.needsUpdate = true
    }
  }
}
