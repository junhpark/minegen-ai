import { describe, expect, it } from 'vitest'
import { showOrebodyEdges } from './orebodyPresentation'

describe('orebody layer presentation (Phase 19)', () => {
  it('draws edge wireframes for analytic reference bodies only', () => {
    expect(showOrebodyEdges('TABULAR')).toBe(true)
    expect(showOrebodyEdges('ELLIPSOID')).toBe(true)
    // the dense backend-authored isosurface is shaded smooth; its edges
    // would only add visual noise (the mesh itself is consumed as-is)
    expect(showOrebodyEdges('WARPED_VEIN')).toBe(false)
  })
})
