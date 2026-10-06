import type {
  ExcludedLevel,
  LayoutRequiredLevel,
  LayoutV2Catalogue,
  LevelExclusionReason,
  LevelsPayload,
  UnservedInterval,
} from '@/types/scene'

/**
 * Hardening H0 §3.1 — presentation of the backend's level-coverage report
 * (rule 141): which REQUIRED levels received no development and why. Every
 * number here is echoed from `levels.json` / the layout-v2 catalogue; nothing
 * is computed on the client (no geometry, no hint arithmetic).
 */

const REASON_TEXT: Record<LevelExclusionReason, string> = {
  NO_FOOTWALL_CONTACT_AT_LEVEL: 'footwall contact above orebody top',
  NO_OREBODY_SECTION_AT_LEVEL: 'no orebody section at this elevation',
  NO_LEVEL_ENTRY: 'no level entry from the active ramp',
}

export function exclusionReasonText(reason: LevelExclusionReason): string {
  return REASON_TEXT[reason]
}

const m2 = (v: number): string => `${v.toFixed(2)} m`

/** one line per excluded level, e.g.
 * "Top level L01 excluded — footwall contact above orebody top (2.12 m). Minimum topMiningMargin for L01: 11.87 m" */
export function excludedLevelLine(e: ExcludedLevel): string {
  const where = e.index === 0 ? 'Top level' : 'Level'
  let text = `${where} ${e.levelId} excluded — ${exclusionReasonText(e.reason)}`
  if (e.overshootM !== null && e.overshootM !== undefined) text += ` (${m2(e.overshootM)})`
  text += '.'
  if (e.minimumTopMiningMarginM !== null && e.minimumTopMiningMarginM !== undefined) {
    text += ` Minimum topMiningMargin for ${e.levelId}: ${m2(e.minimumTopMiningMarginM)}`
  }
  return text
}

export function unservedIntervalLine(i: UnservedInterval): string {
  return `No production interval ${i.upperLevelId}–${i.lowerLevelId} (${exclusionReasonText(i.reason)})`
}

/** the Level development card notice lines; empty when nothing is excluded */
export function levelCoverageLines(levels: LevelsPayload | null): string[] {
  if (!levels) return []
  const excluded = levels.excludedLevels ?? []
  const intervals = levels.unservedIntervals ?? []
  return [...excluded.map(excludedLevelLine), ...intervals.map(unservedIntervalLine)]
}

/**
 * The catalogue's wire shape is the Phase 20A one: `hasOrebodySection` is
 * the only per-level flag. A TABULAR level excluded by the footwall-contact
 * guard still HAS a section (ore above it), so it is counted out of
 * `serviceableLevelCount` here and explained — with its reason, overshoot
 * and margin hint — by `levels.json` once level development runs.
 */
export function isServiceable(lv: LayoutRequiredLevel): boolean {
  return lv.hasOrebodySection
}

/** "12/13 levels serviceable" — the catalogue's own count, never recounted */
export function catalogueLevelSummary(c: LayoutV2Catalogue): string {
  return `${String(c.serviceableLevelCount)}/${String(c.requiredLevels.length)} levels serviceable`
}

/** one line per required level the catalogue marks without an orebody section */
export function catalogueExcludedLines(c: LayoutV2Catalogue): string[] {
  return c.requiredLevels
    .filter((lv) => !isServiceable(lv))
    .map((lv) => `${lv.levelId} excluded — ${exclusionReasonText('NO_OREBODY_SECTION_AT_LEVEL')}`)
}
