import { describe, expect, it } from 'vitest'
import { WALKTHROUGH_DPR } from './config'
import { createPerfSampler } from './WalkthroughDiagnostics'

describe('walkthrough performance baseline (hotfix §12/§14/§21)', () => {
  it('walkthrough renders at DPR 1', () => {
    expect(WALKTHROUGH_DPR).toBe(1)
  })

  it('diagnostic sampler is bounded to ~2 Hz, never per frame', () => {
    const s = createPerfSampler(0.5)
    let emitted = 0
    // 120 frames at 60 fps = 2 seconds -> exactly 4 samples
    for (let i = 0; i < 120; i++) if (s.sample(1 / 60, 132000, 23) !== null) emitted += 1
    expect(emitted).toBe(4)
    const line = (() => {
      const s2 = createPerfSampler(0.5)
      for (let i = 0; i < 29; i++) expect(s2.sample(1 / 60, 1000, 5)).toBeNull()
      return s2.sample(1 / 60, 132000, 23)
    })()
    expect(line).toContain('FPS 60')
    expect(line).toContain('Triangles 132k')
    expect(line).toContain('Draw calls 23')
  })
})
