import { NAVIGATION_MODES, type WalkthroughNavigationMode } from './navigation'
import type { TeleportTarget } from './teleport'
import { VEHICLE_PRESETS, isVehiclePresetId, type VehiclePresetId } from './vehicle'
import { tr } from '@/i18n/t'

/**
 * Compact walkthrough overlay (Phase 16 §31–34, PR-4 third person): center
 * crosshair (the avatar's eye-ray), a pointer-enabled mode selector (1/2/3
 * keys mirror it) with the truck-class select in VEHICLE mode (V cycles it),
 * a per-mode keyboard legend bottom-left, temporal snapshot info top-right
 * and the DEV perf readout bottom-right. Mode/speed and the minimap live in
 * the separate MinimapOverlay (top-left).
 */
const LEGENDS: Record<WalkthroughNavigationMode, [string, string][]> = {
  PERSON: [
    ['WASD', 'Move'],
    ['IJKL', 'Camera'],
    ['Shift', 'Run'],
    ['R', 'Reset'],
  ],
  VEHICLE: [
    ['W/S', 'Drive'],
    ['A/D', 'Steer'],
    ['IJKL', 'Camera'],
    ['V', 'Truck class'],
    ['Shift', 'Boost'],
    ['R', 'Reset'],
  ],
  DRONE: [
    ['WASD', 'Fly'],
    ['Space / C', 'Up / Down'],
    ['IJKL', 'Camera'],
    ['Shift', 'Boost'],
    ['R', 'Reset'],
  ],
}

const MODE_LABEL: Record<WalkthroughNavigationMode, string> = {
  PERSON: 'Person',
  VEHICLE: 'Vehicle',
  DRONE: 'Drone',
}

export function WalkthroughHUD({
  focusedKind,
  snapshotDay = null,
  navigationMode,
  onNavigationMode,
  vehiclePreset,
  onVehiclePreset,
  teleportTargets = [],
  onTeleport,
  perfRef,
}: {
  focusedKind: 'MESH_ROUTER' | 'GAS_SENSOR' | null
  snapshotDay?: number | null
  navigationMode: WalkthroughNavigationMode
  onNavigationMode: (mode: WalkthroughNavigationMode) => void
  /** PR-4 W2: the truck class driven in VEHICLE mode */
  vehiclePreset?: VehiclePresetId
  onVehiclePreset?: (preset: VehiclePresetId) => void
  /** ramp stations and level entries for the teleport select */
  teleportTargets?: readonly TeleportTarget[]
  onTeleport?: (target: TeleportTarget) => void
  perfRef?: { current: HTMLDivElement | null }
}) {
  const temporal = snapshotDay !== null
  const cross = focusedKind ? 'bg-lamp' : 'bg-chalk/50'
  const preset = VEHICLE_PRESETS.find((p) => p.id === vehiclePreset) ?? null
  return (
    <div className="pointer-events-none absolute inset-0">
      <div className="absolute left-1/2 top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2">
        <div className={`absolute left-1/2 top-0 h-full w-px -translate-x-1/2 ${cross}`} />
        <div className={`absolute left-0 top-1/2 h-px w-full -translate-y-1/2 ${cross}`} />
      </div>
      {focusedKind ? (
        <div className="readout absolute left-1/2 top-1/2 -translate-x-1/2 translate-y-4 rounded-sm bg-rock-900/80 px-2 py-1 text-center text-[11px] text-lamp">
          <div>{focusedKind}</div>
          <div className="text-chalk-dim">{tr('E Inspect')}</div>
        </div>
      ) : null}
      <div className="pointer-events-auto absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1">
        {teleportTargets.length > 0 && onTeleport ? (
          <select
            aria-label={tr('Teleport to level')}
            className="plate rounded-sm bg-rock-900/80 px-1.5 py-0.5 text-[11px] text-chalk-dim"
            value=""
            onChange={(e) => {
              const t = teleportTargets.find((x) => x.id === e.target.value)
              if (t) onTeleport(t)
              e.target.value = ''
            }}
          >
            <option value="" disabled>
              {tr('Go to…')}
            </option>
            {teleportTargets.map((t) => (
              <option key={t.id} value={t.id}>
                {t.kind === 'LEVEL_ENTRY'
                  ? `${t.label} · RL ${t.elevation.toFixed(0)} m`
                  : `${t.label} · CH ${t.chainageM.toFixed(0)} m`}
              </option>
            ))}
          </select>
        ) : null}
        {NAVIGATION_MODES.map((m, i) => (
          <button
            key={m}
            type="button"
            onClick={() => onNavigationMode(m)}
            aria-pressed={m === navigationMode}
            className={[
              'plate rounded-sm px-2 py-0.5 text-[11px]',
              m === navigationMode
                ? 'bg-rock-700 text-lamp shadow-[inset_0_-2px_0_0_var(--color-lamp)]'
                : 'bg-rock-900/70 text-chalk-dim hover:bg-rock-700/60',
            ].join(' ')}
          >
            {i + 1} {tr(MODE_LABEL[m])}
          </button>
        ))}
        {navigationMode === 'VEHICLE' && onVehiclePreset ? (
          <select
            aria-label={tr('Truck class')}
            className="plate rounded-sm bg-rock-900/80 px-1.5 py-0.5 text-[11px] text-chalk-dim"
            value={preset?.id ?? ''}
            onChange={(e) => {
              if (isVehiclePresetId(e.target.value)) onVehiclePreset(e.target.value)
            }}
          >
            {VEHICLE_PRESETS.map((p) => (
              <option key={p.id} value={p.id}>
                {`${p.label} · ${p.lengthM.toFixed(1)} × ${p.widthM.toFixed(1)} × ${p.heightM.toFixed(1)} m`}
              </option>
            ))}
          </select>
        ) : null}
      </div>
      {navigationMode === 'VEHICLE' && preset ? (
        <div className="readout absolute bottom-11 left-1/2 -translate-x-1/2 rounded-sm bg-rock-900/70 px-2 py-0.5 text-[10px] text-mute">
          {tr(preset.classNote)} · {tr('representative class dimensions, not a specification')}
        </div>
      ) : null}
      {temporal ? (
        <div className="readout absolute right-3 top-3 rounded-sm bg-rock-900/80 px-3 py-2 text-right text-[11px] leading-relaxed">
          <div className="text-lamp">Day {snapshotDay.toFixed(1)}</div>
          <div className="text-chalk-dim">{tr('Timeline snapshot')}</div>
          <div className="text-chalk-dim">{tr('Completed excavation only')}</div>
          <div className="mt-1 text-mute">{tr('Return to 4D to change time')}</div>
        </div>
      ) : null}
      {import.meta.env.DEV ? (
        <div
          ref={perfRef}
          className="readout absolute bottom-3 right-3 whitespace-pre rounded-sm bg-rock-900/70 px-2 py-1 text-[10px] text-chalk-dim"
        />
      ) : null}
      <div className="readout absolute bottom-3 left-3 rounded-sm bg-rock-900/70 px-3 py-2 text-[11px] leading-relaxed text-chalk-dim">
        {LEGENDS[navigationMode].map(([k, v]) => (
          <div key={k}>
            {k}&ensp;{tr(v)}
          </div>
        ))}
        {temporal ? null : <div>E&ensp;{tr('Inspect')}</div>}
      </div>
    </div>
  )
}
