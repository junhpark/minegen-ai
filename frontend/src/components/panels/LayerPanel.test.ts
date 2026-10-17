import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { VIEW_LAYER_TOOLS } from '@/components/layout/ribbonModel'
import { LAYER_IDS } from '@/types/enums'
import { LAYER_GROUPS } from './layerGroups'

const scene = readFileSync(join(__dirname, '..', '..', 'scene', 'MineScene.tsx'), 'utf8')
const treeIds = LAYER_GROUPS.flatMap((g) => g.rows.map((r) => r.id))

describe('Visibility tree (PR-3 round 3)', () => {
  it('every row toggles a layer the scene actually reads — a dead checkbox is a defect', () => {
    for (const id of treeIds) {
      expect(scene, `MineScene never reads visible.has('${id}')`).toContain(`visible.has('${id}')`)
    }
  })

  it('row ids are unique LayerIds', () => {
    const known = new Set<string>(LAYER_IDS)
    expect(new Set(treeIds).size).toBe(treeIds.length)
    for (const id of treeIds) expect(known.has(id)).toBe(true)
  })

  it('the ribbon View › Layers tools cover tree rows only (the band defines no layer of its own)', () => {
    const rows = new Set<string>(treeIds)
    for (const t of VIEW_LAYER_TOOLS) for (const l of t.layers) expect(rows.has(l)).toBe(true)
  })
})
