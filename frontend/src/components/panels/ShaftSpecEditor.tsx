import { useState } from 'react'
import { ActionButton } from '@/components/ui/ActionButton'
import type { ShaftPlanningConfig, ShaftSpec } from '@/types/api'
import { CAPABILITIES, type Capability } from '@/types/enums'
import type { CollarSuggestion } from '@/types/scene'
import { SHAFT_SPEC_DEFAULTS, nextShaftId } from './shaftDraft'

const FIELD =
  'w-full rounded-sm border border-rock-700 bg-rock-900 px-1.5 py-0.5 text-[11px] text-chalk focus:border-lamp focus:outline-none'

const ROLE_LABEL: Record<ShaftSpec['role'], string> = {
  PRODUCTION: 'Production',
  SERVICE: 'Service',
  VENTILATION: 'Ventilation',
}
const CAPABILITY_LABEL: Record<Capability, string> = {
  PERSONNEL_ACCESS: 'Personnel',
  MATERIAL_HAULAGE: 'Haulage',
  VENTILATION_PATH: 'Ventilation',
  UTILITY_SERVICE: 'Utilities',
  EMERGENCY_EGRESS: 'Egress',
}

interface Props {
  /** the edited `scenario.shafts` section (owned by the Access card) */
  draft: ShaftPlanningConfig
  onChange: (next: ShaftPlanningConfig) => void
  /** level ids of an existing level development (the station targets); empty
   * before the layout — stations then default to every developed level */
  levelIds: readonly string[]
  pending: boolean
  enabled: boolean
  /** ask the backend for its default collar of one spec (read-only); absent
   * while no level development exists, since the planner derives the default
   * collar from it */
  onSuggestCollar?: ((spec: ShaftSpec) => Promise<CollarSuggestion>) | undefined
}

/**
 * Hardening PR-2 H2-SH / PR #54 review B3 — the shaft declaration editor,
 * CONTROLLED by the Setup › Access card. It edits the EXPLICIT
 * `scenario.shafts` parameters (role, diameter, collar, stand-off, sump,
 * station levels, capabilities, the two planning limits) and nothing else:
 * the backend plans the shaft (rule 182) and the collar suggestion is the
 * backend's default placement copied on the user's click (rule 124). The
 * owning card validates the draft, offers Apply and submits the scenario PUT
 * (rule 40 full invalidation) behind the backend reset plan.
 */
export function ShaftSpecEditor({
  draft,
  onChange,
  levelIds,
  pending,
  enabled,
  onSuggestCollar,
}: Props) {
  const setDraft = (update: (d: ShaftPlanningConfig) => ShaftPlanningConfig) =>
    onChange(update(draft))
  const [suggesting, setSuggesting] = useState<string | null>(null)
  const [suggestError, setSuggestError] = useState<string | null>(null)
  const setSpec = (index: number, patch: Partial<ShaftSpec>) =>
    setDraft((d) => ({
      ...d,
      specs: d.specs.map((s, i) => (i === index ? { ...s, ...patch } : s)),
    }))
  const num = (
    key: string,
    label: string,
    value: number | null,
    set: (v: number | null) => void,
    opts: { step?: number; optional?: boolean } = {},
  ) => (
    <label key={key} className="block">
      <span className="mb-0.5 block text-[10px] text-mute">{label}</span>
      <input
        type="number"
        className={FIELD}
        value={value ?? ''}
        step={opts.step ?? 1}
        min={0}
        placeholder={opts.optional ? 'default' : undefined}
        disabled={!enabled || pending}
        onChange={(e) => {
          if (e.target.value === '' && opts.optional) {
            set(null)
            return
          }
          const v = Number(e.target.value)
          if (Number.isFinite(v)) set(v)
        }}
      />
    </label>
  )
  const suggest = async (index: number) => {
    const spec = draft.specs[index]
    if (!spec || !onSuggestCollar) return
    setSuggesting(spec.shaftId)
    setSuggestError(null)
    try {
      const s = await onSuggestCollar(spec)
      if (s.status === 'OK' && s.collar) {
        const [x, y] = s.collar
        setSpec(index, { collar: { x, y } })
      } else {
        setSuggestError(`${s.failureCode ?? 'FAILED'}: ${s.failureReason ?? 'no collar suggested'}`)
      }
    } catch (e) {
      setSuggestError(e instanceof Error ? e.message : String(e))
    } finally {
      setSuggesting(null)
    }
  }
  return (
    <div className="flex flex-col gap-1.5" data-testid="shaft-editor">
      {draft.specs.map((spec, index) => (
        <fieldset
          key={index}
          className="flex flex-col gap-1 rounded-sm border border-rock-700 p-1.5"
          data-testid="shaft-spec"
        >
          <div className="grid grid-cols-2 gap-1.5">
            <label className="block">
              <span className="mb-0.5 block text-[10px] text-mute">Shaft id</span>
              <input
                type="text"
                className={FIELD}
                value={spec.shaftId}
                disabled={!enabled || pending}
                onChange={(e) => setSpec(index, { shaftId: e.target.value.toUpperCase() })}
              />
            </label>
            <label className="block">
              <span className="mb-0.5 block text-[10px] text-mute">Role</span>
              <select
                className={FIELD}
                value={spec.role}
                disabled={!enabled || pending}
                onChange={(e) =>
                  // the role seeds the default capability set on the backend:
                  // an explicit set is kept, a role default is re-resolved
                  setSpec(index, { role: e.target.value as ShaftSpec['role'] })
                }
              >
                {(Object.keys(ROLE_LABEL) as ShaftSpec['role'][]).map((r) => (
                  <option key={r} value={r}>
                    {ROLE_LABEL[r]}
                  </option>
                ))}
              </select>
            </label>
            {num(
              `${String(index)}-d`,
              'Diameter (m)',
              spec.diameter,
              (v) => setSpec(index, { diameter: v ?? spec.diameter }),
              { step: 0.5 },
            )}
            {num(`${String(index)}-s`, 'Collar stand-off (m)', spec.collarStandoff, (v) =>
              setSpec(index, { collarStandoff: v ?? spec.collarStandoff }),
            )}
            {num(`${String(index)}-b`, 'Sump below lowest station (m)', spec.bottomSumpDepth, (v) =>
              setSpec(index, { bottomSumpDepth: v ?? spec.bottomSumpDepth }),
            )}
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            {num(
              `${String(index)}-cx`,
              'Collar X (m, blank = default)',
              spec.collar?.x ?? null,
              (v) =>
                setSpec(index, { collar: v === null ? null : { x: v, y: spec.collar?.y ?? 0 } }),
              { step: 1, optional: true },
            )}
            {num(
              `${String(index)}-cy`,
              'Collar Y (m, blank = default)',
              spec.collar?.y ?? null,
              (v) =>
                setSpec(index, { collar: v === null ? null : { x: spec.collar?.x ?? 0, y: v } }),
              { step: 1, optional: true },
            )}
          </div>
          <div className="flex items-center gap-2">
            {onSuggestCollar ? (
              <ActionButton
                variant="secondary"
                disabled={!enabled || pending || suggesting !== null}
                onClick={() => void suggest(index)}
              >
                {suggesting === spec.shaftId ? 'Asking the planner…' : 'Suggest collar'}
              </ActionButton>
            ) : null}
            <span className="text-[10px] text-mute">
              {spec.collar
                ? `explicit collar (${spec.collar.x.toFixed(1)}, ${spec.collar.y.toFixed(1)})`
                : onSuggestCollar
                  ? 'default collar (planner-derived)'
                  : 'default collar — the planner derives it from the level development at Plan shafts'}
            </span>
          </div>
          <div>
            <span className="mb-0.5 block text-[10px] text-mute">
              Station levels (none checked = every developed level)
            </span>
            <div className="flex flex-wrap gap-x-2 gap-y-0.5">
              {levelIds.length === 0 ? (
                <span className="text-[10px] text-mute">generate levels to pick stations</span>
              ) : null}
              {levelIds.map((lid) => (
                <label key={lid} className="flex items-center gap-1 text-[10px] text-chalk-dim">
                  <input
                    type="checkbox"
                    checked={spec.levelIds.includes(lid)}
                    disabled={!enabled || pending}
                    onChange={(e) =>
                      setSpec(index, {
                        levelIds: e.target.checked
                          ? [...spec.levelIds, lid].sort()
                          : spec.levelIds.filter((x) => x !== lid),
                      })
                    }
                  />
                  {lid}
                </label>
              ))}
            </div>
          </div>
          <div>
            <span className="mb-0.5 block text-[10px] text-mute">
              Capabilities (none checked = role default)
            </span>
            <div className="flex flex-wrap gap-x-2 gap-y-0.5">
              {CAPABILITIES.map((c) => (
                <label key={c} className="flex items-center gap-1 text-[10px] text-chalk-dim">
                  <input
                    type="checkbox"
                    checked={spec.capabilities?.includes(c) ?? false}
                    disabled={!enabled || pending}
                    onChange={(e) => {
                      const current = spec.capabilities ?? []
                      const next = e.target.checked
                        ? [...current, c]
                        : current.filter((x) => x !== c)
                      setSpec(index, { capabilities: next.length ? next : null })
                    }}
                  />
                  {CAPABILITY_LABEL[c]}
                </label>
              ))}
            </div>
          </div>
          <ActionButton
            variant="secondary"
            disabled={!enabled || pending}
            onClick={() =>
              setDraft((d) => ({ ...d, specs: d.specs.filter((_, i) => i !== index) }))
            }
          >
            Remove {spec.shaftId}
          </ActionButton>
        </fieldset>
      ))}
      <div className="grid grid-cols-2 gap-1.5">
        {num('max-access', 'Max station drive (m)', draft.maximumStationAccessLength, (v) =>
          setDraft((d) => ({
            ...d,
            maximumStationAccessLength: v ?? d.maximumStationAccessLength,
          })),
        )}
        {num(
          'separation',
          'Min shaft separation (m, blank = 2 × width)',
          draft.minimumShaftSeparation,
          (v) => setDraft((d) => ({ ...d, minimumShaftSeparation: v })),
          { optional: true },
        )}
      </div>
      {suggestError ? (
        <p role="alert" className="text-[10px] text-danger">
          Collar suggestion: {suggestError}
        </p>
      ) : null}
      <div className="flex gap-2">
        <ActionButton
          variant="secondary"
          disabled={!enabled || pending}
          onClick={() =>
            setDraft((d) => ({
              ...d,
              specs: [...d.specs, { shaftId: nextShaftId(d.specs), ...SHAFT_SPEC_DEFAULTS }],
            }))
          }
        >
          Add shaft
        </ActionButton>
      </div>
      <p className="text-[10px] text-mute">
        The backend plans collar, stations and drives from these parameters in Design › Shafts;
        nothing is placed on the client.
      </p>
    </div>
  )
}
