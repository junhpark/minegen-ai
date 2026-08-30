import type { ResolvedSelection } from './selectionResolver'
import {
  INSTALLATION_TIMING_NOTE,
  PLANNED_LAYOUT_LABEL,
  SENSOR_PROXY_DISCLAIMER,
} from './selectionResolver'

/**
 * Compact walkthrough inspection card (§17, rule 108): backend-authored
 * facts only — no telemetry, no device state, no installation timing. The
 * card sits lower-right and never obscures the central walking view.
 */
function Row({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-mute">{label}</dt>
      <dd className="text-chalk">{value}</dd>
    </>
  )
}

function positionText(p: [number, number, number]): string {
  return `E ${p[0].toFixed(1)}  N ${p[1].toFixed(1)}  Z ${p[2].toFixed(1)}`
}

export function WalkthroughInspector({
  selection,
  onClear,
}: {
  selection: ResolvedSelection
  onClear: () => void
}) {
  if (selection.kind === 'ACCESS_CANDIDATE') return null
  const isRouter = selection.kind === 'MESH_ROUTER'
  return (
    <div className="pointer-events-auto absolute bottom-3 right-3 w-72 rounded-sm border border-rock-700 bg-rock-900/90 p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="plate text-[12px] text-lamp">
          {isRouter ? 'Mesh router' : 'Gas sensor'}
        </span>
        <button
          type="button"
          onClick={onClear}
          className="plate rounded-sm px-2 py-0.5 text-[11px] text-chalk-dim hover:bg-rock-700"
        >
          Close
        </button>
      </div>
      <dl className="readout grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px]">
        <Row label="ID" value={selection.asset.id} />
        <Row label="Asset type" value={selection.asset.assetType} />
        <Row label="Position" value={positionText(selection.asset.position)} />
        <Row label="Candidate" value={selection.asset.candidateId} />
        {isRouter ? (
          <>
            <Row label="Hop count" value={String(selection.asset.hopCount)} />
            <Row
              label="Backhaul parent"
              value={selection.asset.backhaulParentAssetId ?? 'gateway'}
            />
            <Row label="Source" value="Communication OSP" />
          </>
        ) : (
          <Row label="Source" value="Sensor OSP" />
        )}
        <Row label="Layout status" value={PLANNED_LAYOUT_LABEL} />
        {selection.model ? (
          <>
            <Row label="Planning model" value={selection.model.coverageModel} />
            {isRouter && selection.kind === 'MESH_ROUTER' ? (
              <>
                <Row
                  label="Coverage range"
                  value={`${selection.model.coverageRangeM.toFixed(0)} m`}
                />
                <Row
                  label="Backhaul range"
                  value={`${selection.model.backhaulRangeM.toFixed(0)} m`}
                />
              </>
            ) : selection.kind === 'GAS_SENSOR' ? (
              <Row
                label="Monitoring range"
                value={`${selection.model.monitoringRangeM.toFixed(0)} m`}
              />
            ) : null}
          </>
        ) : null}
      </dl>
      <p className="mt-2 text-[10px] leading-snug text-mute">
        {INSTALLATION_TIMING_NOTE}
        {isRouter ? null : (
          <>
            <br />
            {SENSOR_PROXY_DISCLAIMER}
          </>
        )}
      </p>
    </div>
  )
}
