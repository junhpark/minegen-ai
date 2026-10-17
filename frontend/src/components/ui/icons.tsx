/**
 * Hardening PR-3 (workspace UI) — the ribbon / flow-dock icon set.
 *
 * Inline SVG strokes on a 24-unit box, drawn with `currentColor`: no icon
 * dependency is added (rule 15), every glyph is a plain geometric signifier
 * and none carries meaning on its own — the tool LABEL beside it is the
 * contract, the icon is recognition only. Presentation, nothing else.
 */
import type { ReactNode } from 'react'

export type IconName =
  | 'scenario'
  | 'method'
  | 'access'
  | 'layout'
  | 'levels'
  | 'excavation'
  | 'shafts'
  | 'network'
  | 'capability'
  | 'production'
  | 'schedule'
  | 'communication'
  | 'sensors'
  | 'analysis'
  | 'export'
  | 'view3d'
  | 'view4d'
  | 'walk'
  | 'iso'
  | 'top'
  | 'fit'
  | 'paneLeft'
  | 'paneRight'
  | 'flow'
  | 'resetStage'
  | 'resetMine'
  | 'newMine'
  | 'open'
  | 'demos'
  | 'import'
  | 'overview'
  | 'economics'
  | 'sensitivity'
  | 'rules'
  | 'layouts'
  | 'simulation'

/** path data per glyph (stroke only; `fill` is added where a dot is drawn) */
const GLYPHS: Record<IconName, ReactNode> = {
  scenario: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M3.5 12h17M12 3.5c3 3 3 14 0 17M12 3.5c-3 3-3 14 0 17" />
    </>
  ),
  method: (
    <>
      <path d="M4 20l9-9" />
      <path d="M11 9c2.5-2.5 6-3 9-2-1 3-1.5 6.5-4 9" />
      <path d="M10 8l6 6" />
    </>
  ),
  access: (
    <>
      <path d="M4 20V11a8 8 0 0 1 16 0v9" />
      <path d="M8 20v-7a4 4 0 0 1 8 0v7" />
      <path d="M12 10v4" />
    </>
  ),
  layout: (
    <>
      <path d="M12 12c0-1.5 1-2.5 2.5-2.5S17 10.5 17 12c0 2.5-2 4.5-5 4.5S6.5 14.5 6.5 11.5 9.5 5.5 13 5.5s7 3 7 7.5" />
    </>
  ),
  levels: (
    <>
      <path d="M4 7h10M7 12h10M10 17h10" />
      <path d="M4 7l3 5 3 5" />
    </>
  ),
  excavation: (
    <>
      <path d="M4 20v-8a8 8 0 0 1 16 0v8" />
      <path d="M4 20h16" />
      <path d="M9 20v-5a3 3 0 0 1 6 0v5" />
    </>
  ),
  shafts: (
    <>
      <path d="M9 5v15M15 5v15" />
      <path d="M5 5h14" />
      <path d="M9 10h6M9 15h6" />
      <path d="M9 20h6" />
    </>
  ),
  network: (
    <>
      <circle cx="5" cy="6" r="2" />
      <circle cx="19" cy="6" r="2" />
      <circle cx="12" cy="18" r="2" />
      <path d="M7 6h10M6.2 7.6l4.8 8.8M17.8 7.6L13 16.4" />
    </>
  ),
  capability: (
    <>
      <path d="M12 3l8 3v6c0 4.5-3.5 7.5-8 9-4.5-1.5-8-4.5-8-9V6z" />
      <path d="M8.5 12l2.5 2.5 4.5-5" />
    </>
  ),
  production: (
    <>
      <path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z" />
      <path d="M4 7.5l8 4.5 8-4.5M12 12v9" />
    </>
  ),
  schedule: (
    <>
      <rect x="4" y="5" width="16" height="15" rx="1.5" />
      <path d="M4 10h16M8 3v4M16 3v4" />
      <path d="M8 14h3v3H8z" />
    </>
  ),
  communication: (
    <>
      <path d="M12 21v-9" />
      <circle cx="12" cy="10" r="2" />
      <path d="M7.5 5.5a6.5 6.5 0 0 0 0 9M16.5 5.5a6.5 6.5 0 0 1 0 9" />
      <path d="M5 3a10 10 0 0 0 0 14M19 3a10 10 0 0 1 0 14" />
    </>
  ),
  sensors: (
    <>
      <circle cx="12" cy="13" r="2" fill="currentColor" stroke="none" />
      <path d="M8 9a5.5 5.5 0 0 0 0 8M16 9a5.5 5.5 0 0 1 0 8" />
      <path d="M12 3v3M4 20h16" />
    </>
  ),
  analysis: (
    <>
      <path d="M4 20h16" />
      <path d="M6 17v-5M11 17V7M16 17v-8" />
      <path d="M4 5l5 4 4-5 7 3" />
    </>
  ),
  export: (
    <>
      <path d="M4 14v5a1.5 1.5 0 0 0 1.5 1.5h13A1.5 1.5 0 0 0 20 19v-5" />
      <path d="M12 15V4M7.5 8.5L12 4l4.5 4.5" />
    </>
  ),
  view3d: (
    <>
      <path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z" />
      <path d="M4 7.5l8 4.5 8-4.5M12 12v9" />
    </>
  ),
  view4d: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7v5l3.5 2" />
    </>
  ),
  walk: (
    <>
      <circle cx="13" cy="4.5" r="1.8" />
      <path d="M9 21l2.5-7-2-2.5L7 14" />
      <path d="M11.5 14L15 17l1 4" />
      <path d="M10 9l3-1 3 3.5 2.5 1" />
    </>
  ),
  iso: (
    <>
      <path d="M12 4l7 4v8l-7 4-7-4V8z" />
      <path d="M12 12l7-4M12 12v8M12 12L5 8" />
    </>
  ),
  top: (
    <>
      <rect x="5" y="5" width="14" height="14" rx="1" />
      <circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none" />
    </>
  ),
  fit: (
    <>
      <path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5" />
      <rect x="9" y="9" width="6" height="6" rx="0.5" />
    </>
  ),
  paneLeft: (
    <>
      <rect x="3.5" y="5" width="17" height="14" rx="1.5" />
      <path d="M9.5 5v14" />
    </>
  ),
  paneRight: (
    <>
      <rect x="3.5" y="5" width="17" height="14" rx="1.5" />
      <path d="M14.5 5v14" />
    </>
  ),
  flow: (
    <>
      <rect x="3" y="4" width="6" height="5" rx="1" />
      <rect x="15" y="4" width="6" height="5" rx="1" />
      <rect x="9" y="15" width="6" height="5" rx="1" />
      <path d="M9 6.5h6M6 9v4h6v2M18 9v4h-6" />
    </>
  ),
  resetStage: (
    <>
      <path d="M5 12a7 7 0 1 1 2.5 5.4" />
      <path d="M5 7v5h5" />
    </>
  ),
  resetMine: (
    <>
      <path d="M19 12a7 7 0 1 1-2.5-5.4" />
      <path d="M19 5v5h-5" />
      <path d="M9 12l2 2 4-4" />
    </>
  ),
  newMine: (
    <>
      <path d="M13 3H7a1.5 1.5 0 0 0-1.5 1.5v15A1.5 1.5 0 0 0 7 21h10a1.5 1.5 0 0 0 1.5-1.5V8.5z" />
      <path d="M13 3v5.5h5.5M12 12v6M9 15h6" />
    </>
  ),
  open: (
    <>
      <path d="M3.5 6.5A1.5 1.5 0 0 1 5 5h4.5l2 2.5H19a1.5 1.5 0 0 1 1.5 1.5V18A1.5 1.5 0 0 1 19 19.5H5A1.5 1.5 0 0 1 3.5 18z" />
      <path d="M3.5 11h17" />
    </>
  ),
  demos: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M10 8.5l5.5 3.5-5.5 3.5z" fill="currentColor" />
    </>
  ),
  import: (
    <>
      <path d="M4 14v5a1.5 1.5 0 0 0 1.5 1.5h13A1.5 1.5 0 0 0 20 19v-5" />
      <path d="M12 4v11M7.5 10.5L12 15l4.5-4.5" />
    </>
  ),
  overview: (
    <>
      <rect x="4" y="4" width="7" height="7" rx="1" />
      <rect x="13" y="4" width="7" height="7" rx="1" />
      <rect x="4" y="13" width="7" height="7" rx="1" />
      <rect x="13" y="13" width="7" height="7" rx="1" />
    </>
  ),
  economics: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 6.5v11M14.5 9.5c0-1.2-1.1-2-2.5-2s-2.5.8-2.5 2 1.1 1.8 2.5 2.2 2.5 1 2.5 2.3-1.1 2-2.5 2-2.5-.8-2.5-2" />
    </>
  ),
  sensitivity: (
    <>
      <path d="M4 7h16M4 12h16M4 17h16" />
      <circle cx="9" cy="7" r="1.8" fill="currentColor" />
      <circle cx="15" cy="12" r="1.8" fill="currentColor" />
      <circle cx="7" cy="17" r="1.8" fill="currentColor" />
    </>
  ),
  rules: (
    <>
      <path d="M4 6.5l1.5 1.5 3-3M4 12.5l1.5 1.5 3-3M4 18.5l1.5 1.5 3-3" />
      <path d="M11 6.5h9M11 12.5h9M11 18.5h9" />
    </>
  ),
  layouts: (
    <>
      <rect x="4" y="4" width="4" height="16" rx="0.8" />
      <rect x="10" y="8" width="4" height="12" rx="0.8" />
      <rect x="16" y="11" width="4" height="9" rx="0.8" />
    </>
  ),
  simulation: (
    <>
      <path d="M3 12c2-5 4-5 6 0s4 5 6 0 4-5 6 0" />
      <path d="M3 17h18" />
    </>
  ),
}

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      focusable="false"
      data-icon={name}
    >
      {GLYPHS[name]}
    </svg>
  )
}

export const ICON_NAMES = Object.keys(GLYPHS) as IconName[]
