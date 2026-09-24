import { EXPORT_HELPER_TEXT, STATE_TEXT, type ExportLayer } from './exportContents'

const MARK: Record<ExportLayer['state'], string> = {
  INCLUDED: '✓',
  NOT_GENERATED: '—',
  FAILED: '✕',
}

const TONE: Record<ExportLayer['state'], string> = {
  INCLUDED: 'text-chalk',
  NOT_GENERATED: 'text-mute',
  FAILED: 'text-danger',
}

/**
 * Presentational "Current export contents" readout (S3): a list of layers
 * with their read-only state and the partial-export helper text. It renders
 * what `describeExportContents` reports and computes nothing.
 */
export function ExportContents({ layers }: { layers: ExportLayer[] }) {
  return (
    <div
      data-testid="export-contents"
      className="mt-2 rounded-sm border border-rock-700/60 bg-rock-900/60 px-2 py-1.5 text-[11px]"
    >
      {layers.length > 0 ? (
        <>
          <span className="mb-1 block text-chalk-dim">Current export contents</span>
          <ul className="mb-1 flex flex-col gap-y-0.5">
            {layers.map((l) => (
              <li
                key={l.key}
                data-state={l.state}
                className={`flex items-baseline gap-1 ${TONE[l.state]}`}
                title={`${l.label}: ${STATE_TEXT[l.state]}`}
              >
                <span aria-hidden="true" className="readout w-3 shrink-0">
                  {MARK[l.state]}
                </span>
                <span className="truncate">
                  {l.label}
                  {l.state === 'INCLUDED' ? null : (
                    <span className="text-mute"> ({STATE_TEXT[l.state]})</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <p className="text-mute">{EXPORT_HELPER_TEXT}</p>
    </div>
  )
}
