import { useState } from 'react'
import { ActionButton } from '@/components/ui/ActionButton'
import type { ShaftPlanningConfig, ShaftSpec } from '@/types/api'
import { CAPABILITIES, type Capability } from '@/types/enums'
import type { CollarSuggestion } from '@/types/scene'
import {
  SHAFT_SPEC_DEFAULTS,
  nextShaftId,
  persistedShafts,
  reconcileShaftDraft,
  shaftDraftIsDirty,
  shaftDraftProblems,
  type ShaftDraftState,
} from './shaftDraft'

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
  /** the persisted `scenario.shafts` section (undefined → no shaft) */
  persisted: ShaftPlanningConfig | null | undefined
  /** the scenario REVISION this editor edits (`scenarioId:epoch`) */
  identity: string
  /** level ids of the current level developments (the station targets) */
  levelIds: readonly string[]
  pending: boolean
  enabled: boolean
  /** submit the edited declaration (a scenario PUT behind a confirmation) */
  onApply: (config: ShaftPlanningConfig) => void
  /** ask the backend for its default collar of one spec (read-only) */
  onSuggestCollar: (spec: ShaftSpec) => Promise<CollarSuggestion>
}

/**
 * Hardening PR-2 H2-SH — the shaft declaration editor. It edits the EXPLICIT
 * `scenario.shafts` parameters (role, diameter, collar, stand-off, sump,
 * station levels, capabilities, the two planning limits) and nothing else:
 * the backend plans the shaft (rule 182), the collar suggestion is the
 * backend's default placement copied on the user's click (rule 124), and
 * applying is the scenario PUT (rule 40 full invalidation) the owner
 * confirms with the backend reset plan. The draft is scoped to one scenario
 * revision and discarded on a scenario switch or a document replacement.
 */
export function ShaftSpecEditor({
  persisted,
  identity,
  levelIds,
  pending,
  enabled,
  onApply,
  onSuggestCollar,
}: Props) {
  const base = persistedShafts(persisted)
  const [stored, setStored] = useState<ShaftDraftState>({ identity, draft: base })
  const draft = reconcileShaftDraft(stored, identity, base).draft
  const setDraft = (update: (d: ShaftPlanningConfig) => ShaftPlanningConfig) =>
    setStored((s) => {
      const current = reconcileShaftDraft(s, identity, base).draft
      return { identity, draft: update(current) }
    })
  const [suggesting, setSuggesting] = useState<string | null>(null)
  const [suggestError, setSuggestError] = useState<string | null>(null)
  const dirty = shaftDraftIsDirty(draft, base)
  const problems = shaftDraftProblems(draft)
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
    if (!spec) return
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
      {draft.specs.length === 0 ? (
        <p className="text-[10px] text-mute">No shaft declared — the mine stays ramp-only.</p>
      ) : null}
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
            {num(`${String(index)}-d`, 'Diameter (m)', spec.diameter, (v) =>
              setSpec(index, { diameter: v ?? spec.diameter }), { step: 0.5 })}
            {num(`${String(index)}-s`, 'Collar stand-off (m)', spec.collarStandoff, (v) =>
              setSpec(index, { collarStandoff: v ?? spec.collarStandoff }))}
            {num(`${String(index)}-b`, 'Sump below lowest station (m)', spec.bottomSumpDepth, (v) =>
              setSpec(index, { bottomSumpDepth: v ?? spec.bottomSumpDepth }))}
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            {num(
              `${String(index)}-cx`,
              'Collar X (m, blank = default)',
              spec.collar?.x ?? null,
              (v) => setSpec(index, { collar: v === null ? null : { x: v, y: spec.collar?.y ?? 0 } }),
              { step: 1, optional: true },
            )}
            {num(
              `${String(index)}-cy`,
              'Collar Y (m, blank = default)',
              spec.collar?.y ?? null,
              (v) => setSpec(index, { collar: v === null ? null : { x: spec.collar?.x ?? 0, y: v } }),
              { step: 1, optional: true },
            )}
          </div>
          <div className="flex items-center gap-2">
            <ActionButton
              variant="secondary"
              disabled={!enabled || pending || suggesting !== null}
              onClick={() => void suggest(index)}
            >
              {suggesting === spec.shaftId ? 'Asking the planner…' : 'Suggest collar'}
            </ActionButton>
            <span className="text-[10px] text-mute">
              {spec.collar
                ? `explicit collar (${spec.collar.x.toFixed(1)}, ${spec.collar.y.toFixed(1)})`
                : 'default collar (planner-derived)'}
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
          setDraft((d) => ({ ...d, maximumStationAccessLength: v ?? d.maximumStationAccessLength })))}
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
      {problems.length > 0 ? (
        <ul className="list-disc pl-4 text-[10px] text-danger">
          {problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
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
        <ActionButton
          variant="secondary"
          disabled={!enabled || pending || !dirty || problems.length > 0}
          onClick={() => onApply(draft)}
        >
          {pending ? 'Applying…' : 'Apply shaft declaration'}
        </ActionButton>
      </div>
      <p className="text-[10px] text-mute">
        Applying rewrites the scenario: every derived design artifact is cleared and the world is
        regenerated from the same seed. The backend plans collar, stations and drives from these
        parameters; nothing is placed on the client.
      </p>
    </div>
  )
}
