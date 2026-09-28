import type { AssessmentCheck } from '@/types/scene'

/**
 * Phase 22C — Design Rulebook presentation helpers (rule 203). Pure mappings
 * of a backend `AssessmentCheck` to display text: no evaluation, no
 * aggregation, no inferred status.
 */

export const CATEGORY_LABEL: Record<AssessmentCheck['category'], string> = {
  LAYOUT: 'Layout',
  ACCESS: 'Access',
  CLEARANCE: 'Clearance',
  GEOMETRY: 'Geometry',
  CAPABILITY: 'Capability',
  EGRESS: 'Egress',
}

export const AUTHORITY_LABEL: Record<AssessmentCheck['authority'], string> = {
  HARD_DESIGN_RULE: 'Hard design rule',
  DERIVED_VALIDATION: 'Design validation',
  ADVISORY: 'Design advisory',
  INFORMATIONAL: 'Informational',
}

export const SCOPE_LABEL: Record<AssessmentCheck['scope'], string> = {
  ACTIVE_DESIGN: 'Active design',
  INACTIVE_LAYOUT_V2: 'Inactive layout-v2',
}

export interface RulebookStatus {
  /** the glyph shown before the status text; '' for an informational row */
  glyph: string
  text: string
  className: string
}

/**
 * The status cell of one check. Hard design rules and derived validations
 * use ✓ / ✗ / ? / —; an advisory is spelled out as an advisory and never
 * receives the ✓ pass glyph; an informational fact has no pass / fail at all.
 */
export function rulebookStatus(c: AssessmentCheck): RulebookStatus {
  if (c.authority === 'INFORMATIONAL') {
    return { glyph: '', text: 'Info', className: 'text-chalk-dim' }
  }
  if (c.status === 'NOT_EVALUATED')
    return { glyph: '?', text: 'NOT EVALUATED', className: 'text-mute' }
  if (c.status === 'NOT_APPLICABLE') {
    return { glyph: '—', text: 'NOT APPLICABLE', className: 'text-mute' }
  }
  if (c.authority === 'ADVISORY') {
    return c.status === 'SATISFIED'
      ? { glyph: '', text: 'Advisory satisfied', className: 'text-chalk-dim italic' }
      : { glyph: '', text: 'Advisory not satisfied', className: 'text-danger italic' }
  }
  return c.status === 'SATISFIED'
    ? { glyph: '✓', text: 'SATISFIED', className: 'text-lamp' }
    : { glyph: '✗', text: 'NOT SATISFIED', className: 'text-danger' }
}

/** compact `key: value` evidence readout, backend values only */
export function evidenceText(c: AssessmentCheck): string {
  const parts = Object.entries(c.evidence).map(([k, v]) => {
    if (v === null) return `${k}: —`
    if (Array.isArray(v)) return `${k}: ${v.length === 0 ? '[]' : v.join(', ')}`
    if (typeof v === 'number') return `${k}: ${Number.isInteger(v) ? String(v) : v.toFixed(3)}`
    return `${k}: ${String(v)}`
  })
  return parts.length === 0 ? '—' : parts.join(' · ')
}
