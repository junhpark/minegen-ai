/**
 * Minimal walkthrough overlay (§17): entry prompt before pointer lock and a
 * compact control legend plus passive crosshair while walking. The
 * crosshair has NO interaction semantics — picking is Phase 14.
 *
 * The entry button is a VISUAL AFFORDANCE only: pointer lock is requested
 * by the persistent lock surface (the MineCanvas wrapper) that the button
 * click bubbles to — the HUD swaps DOM with lock state, so it must never
 * own the PointerLockControls selector target (PR #10 blocker).
 */
export function WalkthroughHUD({
  locked,
  focusedKind,
}: {
  locked: boolean
  focusedKind: 'MESH_ROUTER' | 'GAS_SENSOR' | null
}) {
  if (!locked) {
    return (
      <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
        <button
          type="button"
          className="plate pointer-events-auto rounded-sm border border-lamp bg-rock-900/80 px-6 py-3 text-[15px] text-lamp hover:bg-lamp hover:text-rock-950"
        >
          Click to enter walkthrough
        </button>
      </div>
    )
  }
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
      <div className="readout absolute bottom-3 left-3 rounded-sm bg-rock-900/70 px-3 py-2 text-[11px] leading-relaxed text-chalk-dim">
        <div>WASD&ensp;Move</div>
        <div>Mouse&ensp;Look</div>
        <div>ESC&ensp;Release mouse</div>
        <div>R&ensp;Reset</div>
        <div>E&ensp;Inspect</div>
      </div>
    </div>
  )
}
