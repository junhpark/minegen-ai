/**
 * Shared rock-material/texture policy (PR #13 blocker 1 regression): one
 * material set, one texture-application path, consumed by BOTH tunnel
 * layers — pinned at the module level and by a source-level policy scan.
 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import {
  applyRockTexture,
  CAP_MATERIAL,
  TUNNEL_MATERIAL,
  TUNNEL_ROCK_MATERIALS,
} from './tunnelMaterials'

describe('shared tunnel materials', () => {
  it('applyRockTexture attaches/clears the map on EVERY rock material', () => {
    const fake = { isTexture: true } as unknown as Parameters<typeof applyRockTexture>[0]
    applyRockTexture(fake)
    for (const m of TUNNEL_ROCK_MATERIALS) expect(m.map).toBe(fake)
    applyRockTexture(null)
    for (const m of TUNNEL_ROCK_MATERIALS) expect(m.map).toBeNull()
  })

  it('exactly one tunnel + one cap material exist and both carry the policy', () => {
    expect(TUNNEL_ROCK_MATERIALS).toHaveLength(2)
    expect(TUNNEL_ROCK_MATERIALS).toContain(TUNNEL_MATERIAL)
    expect(TUNNEL_ROCK_MATERIALS).toContain(CAP_MATERIAL)
    expect(CAP_MATERIAL.transparent).toBe(true) // pre-existing cap treatment
  })

  it('BOTH layers import the shared module and define no local materials (policy scan)', () => {
    const staticSrc = readFileSync(new URL('../scene/TunnelMeshLayer.tsx', import.meta.url), 'utf8')
    const temporalSrc = readFileSync(new URL('./TemporalTunnelLayer.tsx', import.meta.url), 'utf8')
    for (const src of [staticSrc, temporalSrc]) {
      expect(src).toContain('tunnelMaterials')
      expect(src).toContain('useRockTexture')
      expect(src).toContain('applyRockTexture')
      expect(src).not.toContain('new MeshStandardMaterial') // no layer-local materials
    }
  })
})
