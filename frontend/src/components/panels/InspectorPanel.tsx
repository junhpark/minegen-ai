import { PanelSection } from '@/components/layout/PanelSection'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'
import { fmtMeters } from '@/utils/format'
import {
  INSTALLATION_TIMING_NOTE,
  PLANNED_LAYOUT_LABEL,
  resolveSelectedObject,
  SENSOR_PROXY_DISCLAIMER,
} from '@/walkthrough/selectionResolver'

/**
 * Inspector. Values come from scene payloads / API responses; nothing is
 * computed here (CLAUDE.md rule 17).
 */
export function InspectorPanel() {
  const selected = useViewerStore((s) => s.selectedObjectId)
  const mode = useViewerStore((s) => s.mode)
  const scenario = useScenarioStore((s) => s.scenario)
  const scene = useScenarioStore((s) => s.scene)
  const st = scene?.stats
  const bm = st?.blockModel
  const candidate =
    selected && scene?.accessTargets
      ? (scene.accessTargets.levels.flatMap((l) => l.candidates).find((c) => c.id === selected) ??
        null)
      : null
  const resolvedAsset = candidate ? null : resolveSelectedObject(scene, selected)

  return (
    <>
      <PanelSection title="Inspector" tag={mode}>
        {candidate ? (
          <dl className="readout grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px]">
            <dt className="text-mute">Candidate</dt>
            <dd className={candidate.valid ? 'text-lamp' : 'text-danger'}>
              {candidate.id} · {candidate.valid ? 'valid' : 'rejected'}
            </dd>
            <dt className="text-mute">Position</dt>
            <dd>
              E {candidate.position[0].toFixed(1)} N {candidate.position[1].toFixed(1)} Z{' '}
              {candidate.position[2].toFixed(1)}
            </dd>
            <dt className="text-mute">Along strike</dt>
            <dd>{candidate.uCoord.toFixed(1)} m</dd>
            <dt className="text-mute">Footwall offset</dt>
            <dd>{candidate.footwallOffset.toFixed(1)} m</dd>
            <dt className="text-mute">Rock quality (RMR-like)</dt>
            <dd>{candidate.rockQuality?.toFixed(1) ?? '—'}</dd>
            <dt className="text-mute">Fault penalty</dt>
            <dd>{candidate.faultPenalty?.toFixed(2) ?? '—'}</dd>
            <dt className="text-mute">Cost / m</dt>
            <dd>{candidate.pointCostPerM?.toFixed(2) ?? '∞'}</dd>
            <dt className="text-mute">Next level h</dt>
            <dd>
              {candidate.nextLevelAccessibility !== null
                ? `${candidate.nextLevelAccessibility.toFixed(0)} m`
                : 'last level'}
            </dd>
            {candidate.rejectionReasons.length > 0 ? (
              <>
                <dt className="text-mute">Rejected</dt>
                <dd className="text-danger">{candidate.rejectionReasons.join(', ')}</dd>
              </>
            ) : null}
          </dl>
        ) : resolvedAsset && resolvedAsset.kind !== 'ACCESS_CANDIDATE' ? (
          <dl className="readout grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px]">
            <dt className="text-mute">Asset</dt>
            <dd className="text-lamp">
              {resolvedAsset.asset.id} · {resolvedAsset.asset.assetType}
            </dd>
            <dt className="text-mute">Position</dt>
            <dd>
              E {resolvedAsset.asset.position[0].toFixed(1)} N{' '}
              {resolvedAsset.asset.position[1].toFixed(1)} Z{' '}
              {resolvedAsset.asset.position[2].toFixed(1)}
            </dd>
            <dt className="text-mute">Candidate</dt>
            <dd>{resolvedAsset.asset.candidateId}</dd>
            {resolvedAsset.kind === 'MESH_ROUTER' ? (
              <>
                <dt className="text-mute">Hop count</dt>
                <dd>{resolvedAsset.asset.hopCount}</dd>
                <dt className="text-mute">Backhaul</dt>
                <dd>{resolvedAsset.asset.backhaulParentAssetId ?? 'gateway'}</dd>
                <dt className="text-mute">Source</dt>
                <dd>Communication OSP</dd>
              </>
            ) : (
              <>
                <dt className="text-mute">Source</dt>
                <dd>Sensor OSP</dd>
              </>
            )}
            <dt className="text-mute">Layout</dt>
            <dd>{PLANNED_LAYOUT_LABEL}</dd>
            <dt className="text-mute">Note</dt>
            <dd className="text-mute">
              {INSTALLATION_TIMING_NOTE}
              {resolvedAsset.kind === 'GAS_SENSOR' ? ` ${SENSOR_PROXY_DISCLAIMER}` : ''}
            </dd>
          </dl>
        ) : selected ? (
          <p className="readout text-[11px] text-chalk">{selected}</p>
        ) : (
          <p className="text-[11px] text-mute">
            Nothing selected. Click an access candidate in the viewer.
          </p>
        )}
      </PanelSection>

      <PanelSection title="World" tag={scene ? 'generated' : undefined}>
        {st && bm ? (
          <dl className="readout grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px]">
            <dt className="text-mute">Terrain</dt>
            <dd>
              {st.terrain.nx} × {st.terrain.ny} · z {st.terrain.zMin.toFixed(0)}–
              {st.terrain.zMax.toFixed(0)} m
            </dd>
            <dt className="text-mute">Orebody</dt>
            <dd>
              {(st.orebody.volumeM3 / 1e6).toFixed(2)} Mm³ · {(st.orebody.tonnes / 1e6).toFixed(2)}{' '}
              Mt
            </dd>
            <dt className="text-mute">Ore z</dt>
            <dd>
              {st.orebody.bboxMin[2].toFixed(0)} … {st.orebody.bboxMax[2].toFixed(0)} m
            </dd>
            <dt className="text-mute">Blocks</dt>
            <dd>
              {bm.shape.join(' × ')} = {bm.nBlocks.toLocaleString()}
            </dd>
            <dt className="text-mute">Ore blocks</dt>
            <dd>
              {bm.nOreBlocks.toLocaleString()} · {(bm.oreTonnes / 1e6).toFixed(2)} Mt sampled
            </dd>
            <dt className="text-mute">Mean grade</dt>
            <dd>{bm.meanOreGrade.toFixed(2)}</dd>
            <dt className="text-mute">Rock quality (RMR-like)</dt>
            <dd>{bm.rockQualityMean.toFixed(1)} mean</dd>
            <dt className="text-mute">Fault blocks</dt>
            <dd>
              {bm.faultCoreBlocks.toLocaleString()} core · {bm.faultDamageBlocks.toLocaleString()}{' '}
              damage
            </dd>
            <dt className="text-mute">Memory</dt>
            <dd>{bm.totalMB.toFixed(1)} MB</dd>
          </dl>
        ) : scenario ? (
          <p className="text-[11px] text-mute">
            World not generated yet. Use “Generate world” to build terrain, orebody, block model and
            geology.
          </p>
        ) : (
          <p className="text-[11px] text-mute">Generation results appear here.</p>
        )}
      </PanelSection>

      {scene ? (
        <PanelSection title="Faults">
          {scene.faults.length === 0 ? (
            <p className="text-[11px] text-mute">No faults in this scenario.</p>
          ) : (
            <ul className="readout flex flex-col gap-1 text-[11px]">
              {scene.faults.map((f) => (
                <li key={f.id} className="flex justify-between">
                  <span className="text-danger">{f.id}</span>
                  <span className="text-chalk-dim">
                    {f.strikeDeg}° / {f.dipDeg}° · core {fmtMeters(f.coreHalfWidth, 1)} · zone{' '}
                    {fmtMeters(f.influenceHalfWidth, 0)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </PanelSection>
      ) : null}
    </>
  )
}
