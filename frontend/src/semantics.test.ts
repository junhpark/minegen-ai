/**
 * Phase 18 acceptance guard (rule 127) for the frontend: production code
 * must not reintroduce block / SMU / ore-block semantics. Test files are
 * excluded (they may describe the prohibition), everything else under src/
 * is scanned as text.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { describe, expect, it } from 'vitest'

const ROOT = join(__dirname)
const BANNED = [
  'gradeBlocks',
  'GradeBlocks',
  'oreBlocks',
  'OreBlocks',
  'blockGrid',
  'BlockGrid',
  'BlockModel',
  'blockModel',
  'oreFraction',
  'nOreBlocks',
  'nBlocks',
  'oreTonnes',
  'meanOreGrade',
  'faultCoreBlocks',
]

function* walk(dir: string): Generator<string> {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) yield* walk(p)
    else if (/\.(ts|tsx)$/.test(name) && !/\.test\.(ts|tsx)$/.test(name)) yield p
  }
}

describe('no block semantics in frontend production code', () => {
  it('finds none of the banned identifiers outside tests', () => {
    const offenders: string[] = []
    for (const file of walk(ROOT)) {
      const text = readFileSync(file, 'utf8')
      for (const token of BANNED) {
        const re = new RegExp(`\\b${token}\\b`, 'g')
        let m: RegExpExecArray | null
        while ((m = re.exec(text)) !== null) {
          const line = text.slice(0, m.index).split('\n').length
          offenders.push(`${relative(ROOT, file)}:${line}: ${token}`)
        }
      }
    }
    expect(offenders).toEqual([])
  })
})
