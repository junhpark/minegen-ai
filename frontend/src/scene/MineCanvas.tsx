import { Canvas } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { MineScene } from './MineScene'
import { CoordinateReadout } from './CoordinateReadout'
import { mineToThree } from '@/geometry/coordinateTransform'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useViewerStore } from '@/stores/viewerStore'
import { temporalWalkthroughReadiness, walkthroughReadiness } from '@/walkthrough/readiness'
import { MineViewportShell } from './MineViewportShell'
import { resolveSelectedObject } from '@/walkthrough/selectionResolver'
import { temporalSessionIdentity } from '@/walkthrough/temporalPlan'
import { WalkthroughInspector } from '@/walkthrough/WalkthroughInspector'
import { WalkthroughHUD } from '@/walkthrough/WalkthroughHUD'
import { WalkthroughRuntime } from '@/walkthrough/WalkthroughRuntime'
import { API_BASE_URL } from '@/api/client'
import { WALKTHROUGH_DPR } from '@/walkthrough/config'
import { MinimapOverlay } from '@/walkthrough/MinimapOverlay'
import { createTelemetry } from '@/walkthrough/telemetry'
import { buildMinimapModel } from '@/walkthrough/minimap'
import { resolveTeleportTargets } from '@/walkthrough/teleport'
import { temporalActiveSegmentIds } from '@/walkthrough/temporalPlan'

/**
 * R3F canvas host. Camera positions are specified in mine coordinates and
 * converted once, here, at the rendering boundary.
 *
 * Camera-control ownership (§14): EXACTLY one controller is mounted —
 * OrbitControls in orbit camera mode, the walkthrough runtime in
 * walkthrough camera mode. They never coexist.
 */
export function MineCanvas() {
  const scenario = useScenarioStore((s) => s.scenario)
  const scene = useScenarioStore((s) => s.scene)
  const cameraMode = useViewerStore((s) => s.cameraMode)
  const mode = useViewerStore((s) => s.mode)
  const setMode = useViewerStore((s) => s.setMode)
  const baseZ = scenario?.terrain.baseElevation ?? 300
  const [target, setTarget] = useState<[number, number, number]>(mineToThree(0, 0, baseZ))
  const perfRef = useRef<HTMLDivElement | null>(null)
  const telemetry = useMemo(() => createTelemetry(), [])
  const teleportFn = useRef<((chainageM: number) => void) | null>(null)
  const registerTeleport = useCallback((fn: ((chainageM: number) => void) | null) => {
    teleportFn.current = fn
  }, [])
  const navigationMode = useViewerStore((s) => s.navigationMode)
  const setNavigationMode = useViewerStore((s) => s.setNavigationMode)
  const walkthroughContext = useViewerStore((s) => s.walkthroughContext)
  const walkthroughSnapshotDay = useViewerStore((s) => s.walkthroughSnapshotDay)
  const walkthroughReturnMode = useViewerStore((s) => s.walkthroughReturnMode)
  const walkthroughSnapshotIdentity = useViewerStore((s) => s.walkthroughSnapshotIdentity)
  const [focusedKind, setFocusedKind] = useState<'MESH_ROUTER' | 'GAS_SENSOR' | null>(null)
  const selectedObjectId = useViewerStore((s) => s.selectedObjectId)
  const select = useViewerStore((s) => s.select)

  // re-aim at the orebody when a world arrives
  useEffect(() => {
    if (scene) setTarget(mineToThree(...scene.orebody.center))
  }, [scene])

  // defensive gate (§13/§25): if walkthrough prerequisites disappear while
  // the mode is active, release cleanly back to the entry mode — no crash.
  // TIMELINE_SNAPSHOT additionally requires a valid temporal mapping.
  const temporal = walkthroughContext === 'TIMELINE_SNAPSHOT'
  const readiness =
    temporal && walkthroughSnapshotDay !== null
      ? temporalWalkthroughReadiness(scene, walkthroughSnapshotDay, scenario?.ramp ?? null)
      : walkthroughReadiness(scene)
  // rule 112: a temporal session never re-snapshots — if the captured
  // artifact identity no longer matches the live scene, exit to 4D
  const sessionStale =
    temporal &&
    walkthroughSnapshotIdentity !== null &&
    temporalSessionIdentity(scene) !== walkthroughSnapshotIdentity
  useEffect(() => {
    if (mode === 'WALKTHROUGH' && (readiness !== 'READY' || sessionStale)) {
      setMode(temporal ? walkthroughReturnMode : 'DESIGN')
    }
  }, [mode, readiness, sessionStale, setMode, temporal, walkthroughReturnMode])
  useEffect(() => {
    if (cameraMode !== 'walkthrough') setFocusedKind(null)
  }, [cameraMode])
  // §28 stale-selection cleanup (frontend only): if artifact regeneration
  // or a scenario change removes the selected object, clear the canonical
  // selection so no card can show data from a vanished asset
  const resolvedSelection = resolveSelectedObject(scene, selectedObjectId)
  useEffect(() => {
    if (selectedObjectId && resolvedSelection === null) select(null)
  }, [selectedObjectId, resolvedSelection, select])
  const leaveWalkthrough = useCallback(
    () => setMode(temporal ? walkthroughReturnMode : 'DESIGN'),
    [setMode, temporal, walkthroughReturnMode],
  )

  const walkActiveIds =
    temporal && walkthroughSnapshotDay !== null && scene?.smoothedDecline
      ? temporalActiveSegmentIds(scene.timeline, scene.smoothedDecline, walkthroughSnapshotDay)
      : null
  // level teleport targets over the currently walkable centerline
  const teleportTargets = useMemo(() => {
    if (!scene?.smoothedDecline) return []
    const model = buildMinimapModel(scene.smoothedDecline, walkActiveIds)
    return resolveTeleportTargets(scene, model.chainagePoints)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene, temporal, walkthroughSnapshotDay])
  const walkable =
    cameraMode === 'walkthrough' &&
    readiness === 'READY' &&
    scene?.tunnelMesh?.meshUrl &&
    scene.smoothedDecline

  return (
    <MineViewportShell
      overlayContent={
        cameraMode === 'walkthrough' &&
        walkthroughContext !== 'TIMELINE_SNAPSHOT' &&
        resolvedSelection &&
        resolvedSelection.kind !== 'ACCESS_CANDIDATE' ? (
          <WalkthroughInspector selection={resolvedSelection} onClear={() => select(null)} />
        ) : null
      }
      lockSurfaceContent={
        <>
          <Canvas
            camera={{
              position: mineToThree(-900, -1100, baseZ + 700),
              fov: 45,
              near: 1,
              far: 20000,
            }}
            dpr={cameraMode === 'walkthrough' ? WALKTHROUGH_DPR : [1, 2]}
            gl={{ antialias: true }}
          >
            <color attach="background" args={['#0f1316']} />
            <MineScene />
            {walkable ? (
              <WalkthroughRuntime
                meshUrl={`${API_BASE_URL}${scene.tunnelMesh!.meshUrl}`}
                scene={scene}
                context={temporal ? 'TIMELINE_SNAPSHOT' : 'STATIC_FINAL'}
                snapshotDay={walkthroughSnapshotDay}
                ramp={scenario?.ramp ?? null}
                perfRef={perfRef}
                telemetry={telemetry}
                registerTeleport={registerTeleport}
                onFocusChange={setFocusedKind}
                onGeometryError={leaveWalkthrough}
              />
            ) : cameraMode === 'orbit' ? (
              <OrbitControls
                makeDefault
                target={target}
                enableDamping
                dampingFactor={0.08}
                onChange={(e) => {
                  const t = e?.target.target
                  if (t) setTarget([t.x, t.y, t.z])
                }}
              />
            ) : null}
          </Canvas>
          {cameraMode === 'walkthrough' ? (
            <>
              <WalkthroughHUD
                focusedKind={temporal ? null : focusedKind}
                snapshotDay={temporal ? walkthroughSnapshotDay : null}
                navigationMode={navigationMode}
                onNavigationMode={setNavigationMode}
                teleportTargets={teleportTargets}
                onTeleport={(ch) => teleportFn.current?.(ch)}
                perfRef={perfRef}
              />
              {scene?.smoothedDecline ? (
                <MinimapOverlay
                  smoothed={scene.smoothedDecline}
                  activeSegmentIds={walkActiveIds}
                  telemetry={telemetry}
                />
              ) : null}
            </>
          ) : (
            <CoordinateReadout threeTarget={target} />
          )}
        </>
      }
    />
  )
}
