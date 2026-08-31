/**
 * Minimal walkthrough overlay (§6): passive crosshair, keyboard control
 * legend and the Phase 15 temporal snapshot label. The walkthrough is
 * keyboard-only — no pointer lock, no entry click, no mouse look — so the
 * HUD renders identically for the whole session. The crosshair still has
 * no interaction semantics of its own; E inspects the focused asset in
 * STATIC_FINAL only.
 */
export function WalkthroughHUD({
  focusedKind,
  snapshotDay = null,
  perfRef,
}: {
  focusedKind: 'MESH_ROUTER' | 'GAS_SENSOR' | null
  /** captured MineTimeline day for TIMELINE_SNAPSHOT, null when static */
  snapshotDay?: number | null
  /** DEV-only performance readout target (unused in production) */
  perfRef?: { current: HTMLDivElement | null }
}) {
  const temporal = snapshotDay !== null
  const cross = focusedKind ? 'bg-lamp' : 'bg-chalk/50'
  return (
    <div className="pointer-events-none absolute inset-0">
      <div className="absolute left-1/2 top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2">
        <div className={`absolute left-1/2 top-0 h-full w-px -translate-x-1/2 ${cross}`} />
        <div className={`absolute left-0 top-1/2 h-px w-full -translate-y-1/2 ${cross}`} />
      </div>
      {focusedKind ? (
        <div className="readout absolute left-1/2 top-1/2 -translate-x-1/2 translate-y-4 rounded-sm bg-rock-900/80 px-2 py-1 text-center text-[11px] text-lamp">
          <div>{focusedKind}</div>
          <div className="text-chalk-dim">E Inspect</div>
        </div>
      ) : null}
      {temporal ? (
        <div className="readout absolute right-3 top-3 rounded-sm bg-rock-900/80 px-3 py-2 text-right text-[11px] leading-relaxed">
          <div className="text-lamp">Day {snapshotDay.toFixed(1)}</div>
          <div className="text-chalk-dim">Timeline snapshot</div>
          <div className="text-chalk-dim">Completed decline only</div>
          <div className="mt-1 text-mute">Return to 4D to change time</div>
        </div>
      ) : null}
      {import.meta.env.DEV ? (
        <div
          ref={perfRef}
          className="readout absolute left-3 top-3 whitespace-pre rounded-sm bg-rock-900/70 px-2 py-1 text-[10px] text-chalk-dim"
        />
      ) : null}
      <div className="readout absolute bottom-3 left-3 rounded-sm bg-rock-900/70 px-3 py-2 text-[11px] leading-relaxed text-chalk-dim">
        <div>WASD&ensp;Move</div>
        <div>IJKL&ensp;Look</div>
        <div>R&ensp;Reset</div>
        {temporal ? null : <div>E&ensp;Inspect</div>}
      </div>
    </div>
  )
}
