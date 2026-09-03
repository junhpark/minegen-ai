import type { ScenarioCreate } from '@/types/api'
import type { OrebodyType } from '@/types/enums'
import {
  addFault,
  editFault,
  editOrebody,
  editOrebodyType,
  editRockQuality,
  editWarpedVein,
  MAX_FAULTS,
  orebodyTypeOptions,
  removeFault,
} from './builder'

/**
 * Explicit scenario-parameter editor (Phase 17 acceptance, rule 124): every
 * control writes a scalar the USER typed into the realized draft. No
 * randomization and no geometry derivation happen here — the backend
 * remains the authority for both; this panel only edits the document that
 * will be persisted verbatim.
 */
const FIELD =
  'w-full rounded-sm border border-rock-700 bg-rock-900 px-1.5 py-0.5 text-[11px] text-chalk focus:border-lamp focus:outline-none'

function Num({
  label,
  value,
  onChange,
  step = 1,
}: {
  label: string
  value: number
  onChange: (v: number) => void
  step?: number
}) {
  return (
    <label className="block">
      <span className="mb-0.5 block text-[10px] text-mute">{label}</span>
      <input
        type="number"
        step={step}
        value={Number.isFinite(value) ? value : ''}
        onChange={(e) => onChange(Number(e.target.value))}
        className={`readout ${FIELD}`}
      />
    </label>
  )
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-3">
      <div className="mb-1 text-[10px] uppercase tracking-wide text-chalk-dim">{title}</div>
      {children}
    </div>
  )
}

export function AdvancedScenarioEditor({
  draft,
  onChange,
}: {
  draft: ScenarioCreate
  onChange: (next: ScenarioCreate) => void
}) {
  const ob = draft.orebody
  const rq = draft.geology.rockQuality
  const vein = ob.orebodyType === 'WARPED_VEIN' ? ob.warpedVein : null
  const nominal = vein ? 'Nominal ' : ''
  return (
    <div className="mt-2 rounded-sm border border-rock-700 bg-rock-900/40 p-2">
      <Group title="Orebody">
        <label className="mb-2 block">
          <span className="mb-0.5 block text-[10px] text-mute">Type</span>
          <select
            value={ob.orebodyType}
            onChange={(e) => onChange(editOrebodyType(draft, e.target.value as OrebodyType))}
            className={FIELD}
          >
            {orebodyTypeOptions(draft).map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        {!vein ? (
          <p className="mb-2 text-[10px] text-mute">
            An irregular WARPED_VEIN is realized by the backend from the “irregular warped vein”
            preset; its morphology is never generated here.
          </p>
        ) : null}
        <div className="mb-2 grid grid-cols-3 gap-1.5">
          <Num
            label="Center E"
            value={ob.center.x}
            onChange={(x) => onChange(editOrebody(draft, { center: { x } }))}
          />
          <Num
            label="Center N"
            value={ob.center.y}
            onChange={(y) => onChange(editOrebody(draft, { center: { y } }))}
          />
          <Num
            label="Center RL"
            value={ob.center.z}
            onChange={(z) => onChange(editOrebody(draft, { center: { z } }))}
          />
        </div>
        <div className="grid grid-cols-3 gap-1.5">
          <Num
            label="Strike °"
            value={ob.strikeDeg}
            onChange={(strikeDeg) => onChange(editOrebody(draft, { strikeDeg }))}
          />
          <Num
            label="Dip °"
            value={ob.dipDeg}
            onChange={(dipDeg) => onChange(editOrebody(draft, { dipDeg }))}
          />
          <Num
            label={`${nominal}length m`}
            value={ob.length}
            onChange={(length) => onChange(editOrebody(draft, { length }))}
          />
          <Num
            label={`${nominal}height m`}
            value={ob.height}
            onChange={(height) => onChange(editOrebody(draft, { height }))}
          />
          <Num
            label={`${nominal}thickness m`}
            value={ob.thickness}
            step={0.5}
            onChange={(thickness) => onChange(editOrebody(draft, { thickness }))}
          />
        </div>
        <p className="mt-1 text-[10px] text-mute">
          Height is the down-dip extent, not vertical.
          {vein ? ' Dimensions are nominal: the morphology below modulates them.' : ''}
        </p>
      </Group>

      {vein ? (
        <Group title="Irregular morphology (synthetic, backend-resolved)">
          <div className="grid grid-cols-3 gap-1.5">
            <Num
              label="Warp amp. m"
              value={vein.warpAmplitude}
              onChange={(warpAmplitude) => onChange(editWarpedVein(draft, { warpAmplitude }))}
            />
            <Num
              label="Centre dev. m"
              value={vein.centerlineDeviation}
              onChange={(centerlineDeviation) =>
                onChange(editWarpedVein(draft, { centerlineDeviation }))
              }
            />
            <Num
              label="Outline irreg."
              value={vein.outlineIrregularity}
              step={0.05}
              onChange={(outlineIrregularity) =>
                onChange(editWarpedVein(draft, { outlineIrregularity }))
              }
            />
            <Num
              label="Thickness var."
              value={vein.thicknessVariability}
              step={0.05}
              onChange={(thicknessVariability) =>
                onChange(editWarpedVein(draft, { thicknessVariability }))
              }
            />
            <Num
              label="Pinch floor"
              value={vein.pinchFloorRatio}
              step={0.05}
              onChange={(pinchFloorRatio) => onChange(editWarpedVein(draft, { pinchFloorRatio }))}
            />
            <Num
              label="Edge taper"
              value={vein.edgeTaper}
              step={0.05}
              onChange={(edgeTaper) => onChange(editWarpedVein(draft, { edgeTaper }))}
            />
          </div>
          <p className="mt-1 text-[10px] text-mute">
            Thickness variability must stay ≤ 1 − pinch floor. Geologically plausible synthetic
            morphology — not a measured or estimated orebody.
          </p>
          <details className="mt-1">
            <summary className="cursor-pointer text-[10px] text-chalk-dim">
              Resolved morphology modes (expert, read-only) · shape model v{vein.shapeModelVersion}
            </summary>
            <pre className="readout mt-1 max-h-40 overflow-auto whitespace-pre-wrap text-[9px] text-mute">
              {JSON.stringify(
                {
                  warpModes: vein.warpModes,
                  deviationModes: vein.deviationModes,
                  outlineModes: vein.outlineModes,
                  thicknessModes: vein.thicknessModes,
                  geometryResolution: vein.geometryResolution,
                },
                null,
                1,
              )}
            </pre>
          </details>
        </Group>
      ) : null}

      <Group title="Grade">
        <div className="grid grid-cols-3 gap-1.5">
          <Num
            label="Mean g/t"
            value={ob.meanGrade}
            step={0.1}
            onChange={(meanGrade) => onChange(editOrebody(draft, { meanGrade }))}
          />
          <Num
            label="Variability"
            value={ob.gradeVariability}
            step={0.05}
            onChange={(gradeVariability) => onChange(editOrebody(draft, { gradeVariability }))}
          />
          <Num
            label="Density t/m³"
            value={ob.density}
            step={0.1}
            onChange={(density) => onChange(editOrebody(draft, { density }))}
          />
          <Num
            label="Corr. XY m"
            value={ob.gradeCorrelationLengthXy}
            onChange={(gradeCorrelationLengthXy) =>
              onChange(editOrebody(draft, { gradeCorrelationLengthXy }))
            }
          />
          <Num
            label="Corr. Z m"
            value={ob.gradeCorrelationLengthZ}
            onChange={(gradeCorrelationLengthZ) =>
              onChange(editOrebody(draft, { gradeCorrelationLengthZ }))
            }
          />
        </div>
      </Group>

      <Group title="Rock quality (synthetic RMR-like, 0-100)">
        <div className="grid grid-cols-3 gap-1.5">
          <Num
            label="Mean"
            value={rq.mean}
            onChange={(mean) => onChange(editRockQuality(draft, { mean }))}
          />
          <Num
            label="Std"
            value={rq.std}
            onChange={(std) => onChange(editRockQuality(draft, { std }))}
          />
          <Num
            label="Minimum"
            value={rq.minimum}
            onChange={(minimum) => onChange(editRockQuality(draft, { minimum }))}
          />
          <Num
            label="Maximum"
            value={rq.maximum}
            onChange={(maximum) => onChange(editRockQuality(draft, { maximum }))}
          />
          <Num
            label="Corr. XY m"
            value={rq.correlationLengthXy}
            onChange={(correlationLengthXy) =>
              onChange(editRockQuality(draft, { correlationLengthXy }))
            }
          />
          <Num
            label="Corr. Z m"
            value={rq.correlationLengthZ}
            onChange={(correlationLengthZ) =>
              onChange(editRockQuality(draft, { correlationLengthZ }))
            }
          />
        </div>
        <p className="mt-1 text-[10px] text-mute">
          Synthetic index for demonstration; not calculated RMR or Q.
        </p>
      </Group>

      <Group title={`Faults (${draft.geology.faults.length}/${MAX_FAULTS})`}>
        {draft.geology.faults.map((f, i) => (
          <div key={i} className="mb-2 rounded-sm border border-rock-700/70 p-1.5">
            <div className="mb-1 flex items-center justify-between">
              <span className="text-[10px] text-chalk-dim">Fault {i + 1}</span>
              <button
                type="button"
                onClick={() => onChange(removeFault(draft, i))}
                className="rounded-sm border border-rock-600 px-1.5 text-[10px] text-chalk-dim hover:bg-rock-700"
              >
                Remove
              </button>
            </div>
            <div className="grid grid-cols-3 gap-1.5">
              <Num
                label="Origin E"
                value={f.origin.x}
                onChange={(x) => onChange(editFault(draft, i, { origin: { x } }))}
              />
              <Num
                label="Origin N"
                value={f.origin.y}
                onChange={(y) => onChange(editFault(draft, i, { origin: { y } }))}
              />
              <Num
                label="Origin RL"
                value={f.origin.z}
                onChange={(z) => onChange(editFault(draft, i, { origin: { z } }))}
              />
              <Num
                label="Strike °"
                value={f.strikeDeg}
                onChange={(strikeDeg) => onChange(editFault(draft, i, { strikeDeg }))}
              />
              <Num
                label="Dip °"
                value={f.dipDeg}
                onChange={(dipDeg) => onChange(editFault(draft, i, { dipDeg }))}
              />
              <Num
                label="Core ½w m"
                value={f.coreHalfWidth}
                step={0.5}
                onChange={(coreHalfWidth) => onChange(editFault(draft, i, { coreHalfWidth }))}
              />
              <Num
                label="Infl. ½w m"
                value={f.influenceHalfWidth}
                onChange={(influenceHalfWidth) =>
                  onChange(editFault(draft, i, { influenceHalfWidth }))
                }
              />
              <Num
                label="Core pen."
                value={f.corePenalty}
                onChange={(corePenalty) => onChange(editFault(draft, i, { corePenalty }))}
              />
              <Num
                label="Damage pen."
                value={f.damageZonePenalty}
                onChange={(damageZonePenalty) =>
                  onChange(editFault(draft, i, { damageZonePenalty }))
                }
              />
            </div>
          </div>
        ))}
        <button
          type="button"
          onClick={() => onChange(addFault(draft))}
          disabled={draft.geology.faults.length >= MAX_FAULTS}
          className="plate w-full rounded-sm border border-rock-600 px-2 py-1 text-[11px] text-chalk-dim hover:bg-rock-700 disabled:opacity-40"
        >
          Add fault
        </button>
      </Group>
    </div>
  )
}
