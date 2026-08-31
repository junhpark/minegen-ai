import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { Physics } from '@react-three/rapier'
import { WALKTHROUGH_CONFIG } from './config'
import { createKeyState } from './movement'
import { clearTransientInput, createInspectTrigger } from './interactionRay'
import { resolveColliderPolicy, type WalkthroughContext } from './colliderPolicy'
import { navigationBody } from './navigation'
import { useViewerStore as useViewerStoreNav } from '@/stores/viewerStore'
import type { WalkthroughTelemetry } from './telemetry'
import { resolveTemporalWalkthroughPlan } from './temporalPlan'
import { FrontierBarrier } from './FrontierBarrier'
import { resolveWalkthroughSpawn } from './spawn'
import { extractTunnelRuntimeGeometry } from './tunnelRuntimeGeometry'
import { TunnelColliderSet } from './TunnelColliderSet'
import { WalkthroughControls } from './WalkthroughControls'
import { WalkthroughHeadlamp } from './WalkthroughHeadlamp'
import { WalkthroughPlayer } from './WalkthroughPlayer'
import type { WorldScene } from '@/types/scene'
import { useViewerStore } from '@/stores/viewerStore'
import { resolveWalkthroughAssets } from './interactableAssets'
import { WalkthroughAssetLayer } from './WalkthroughAssetLayer'
import { WalkthroughInteraction } from './WalkthroughInteraction'
import { WalkthroughDiagnostics } from './WalkthroughDiagnostics'

/**
 * First-person runtime owner (rules 99–104). Mounted by MineCanvas ONLY in
 * walkthrough camera mode — orbit controls never coexist with it. Collision
 * derives from the same cached GLB the visual layer renders; extraction is
 * memoized by mesh URL and never runs per frame. Player/camera state is
 * ephemeral and unmounts cleanly with the physics world.
 */
export function WalkthroughRuntime({
  meshUrl,
  scene,
  context,
  snapshotDay,
  ramp,
  perfRef,
  telemetry,
  onFocusChange,
  onGeometryError,
}: {
  meshUrl: string
  scene: WorldScene
  context: WalkthroughContext
  snapshotDay: number | null
  ramp: { tunnelWidth: number; tunnelHeight: number } | null
  perfRef: { current: HTMLDivElement | null }
  telemetry: WalkthroughTelemetry
  onFocusChange: (kind: 'MESH_ROUTER' | 'GAS_SENSOR' | null) => void
  onGeometryError: () => void
}) {
  const smoothed = scene.smoothedDecline!
  const temporal = context === 'TIMELINE_SNAPSHOT'
  // rule 112 (PR #12 blocker 2): the temporal plan consumes the artifacts
  // captured at MOUNT, never live scene updates — a replaced artifact can
  // only trigger the MineCanvas identity gate (clean exit to 4D), never a
  // re-snapshot of the running physics topology
  const frozenRef = useRef<{
    timeline: WorldScene['timeline']
    smoothed: NonNullable<WorldScene['smoothedDecline']>
  } | null>(null)
  if (temporal && frozenRef.current === null) {
    frozenRef.current = { timeline: scene.timeline, smoothed }
  }
  const planTimeline = temporal ? frozenRef.current!.timeline : scene.timeline
  const planSmoothed = temporal ? frozenRef.current!.smoothed : smoothed
  const gltf = useGLTF(meshUrl)
  const camera = useThree((s) => s.camera)
  const keyState = useMemo(() => createKeyState(), [])
  // owned here so EVERY lifecycle exit can reach it (PR #11 blocker 1)
  const inspectTrigger = useMemo(() => createInspectTrigger(), [])
  const resetSignal = useRef(0)
  const focusedRef = useRef<string | null>(null)
  // mirror of focusedRef for rendering; updated ONLY when the id changes
  const [focusedId, setFocusedId] = useState<string | null>(null)
  const select = useViewerStore((s) => s.select)
  // rule 106: interactables come only from backend-authored placements,
  // filtered to the walkable decline domain by authoritative topology.
  // rule 116: TIMELINE_SNAPSHOT suppresses ALL planned infrastructure —
  // installation timing is not modeled, so nothing may be shown/inspected
  const interactables = useMemo(
    () => (temporal ? [] : resolveWalkthroughAssets(scene).assets),
    [scene, temporal],
  )
  const focusById = useMemo(() => new Map(interactables.map((a) => [a.id, a])), [interactables])
  const selectedId = useViewerStore((s) => s.selectedObjectId)

  const runtime = useMemo(() => {
    try {
      return extractTunnelRuntimeGeometry(gltf.scene)
    } catch {
      return null
    }
  }, [gltf])
  const navigationMode = useViewerStoreNav((s) => s.navigationMode)
  // mode-specific deterministic spawn (§30): floor reference stays
  // authoritative; only the body dimensions differ per mode
  const spawn = useMemo(() => {
    const nav = navigationBody(navigationMode)
    return resolveWalkthroughSpawn(planSmoothed, {
      ...WALKTHROUGH_CONFIG,
      bodyHeightM: nav.bodyHeightM,
    })
  }, [planSmoothed, navigationMode])
  // rule 112: the temporal plan is resolved ONCE per snapshot and the
  // physical topology stays immutable for the session
  const plan = useMemo(
    () =>
      temporal && runtime && snapshotDay !== null
        ? resolveTemporalWalkthroughPlan(planTimeline, planSmoothed, runtime, snapshotDay)
        : null,
    [temporal, runtime, planTimeline, planSmoothed, snapshotDay],
  )
  const policy = useMemo(
    () =>
      runtime
        ? resolveColliderPolicy(
            context,
            runtime.segments.map((s) => s.segmentId),
            plan,
          )
        : null,
    [runtime, context, plan],
  )
  const frontierSegment = useMemo(() => {
    if (!plan || plan.status !== 'VALID' || plan.lastActiveSegmentIndex === null) return null
    return planSmoothed.segments[plan.lastActiveSegmentIndex] ?? null
  }, [plan, planSmoothed])

  // near plane suited for standing 0.3 m from a wall; restored on unmount
  useEffect(() => {
    const prev = camera.near
    camera.near = 0.05
    camera.updateProjectionMatrix()
    return () => {
      camera.near = prev
      camera.updateProjectionMatrix()
    }
  }, [camera])

  // defensive: unreachable geometry OR an invalid/fail-closed temporal
  // mapping -> leave walkthrough cleanly (§13, rule 117)
  // PR #12 blocker 3: a temporal frontier must use Scenario-authored ramp
  // dimensions — guessed defaults are forbidden, so an unusable ramp fails
  // the whole temporal session closed
  const rampUsable =
    ramp !== null &&
    Number.isFinite(ramp.tunnelWidth) &&
    ramp.tunnelWidth > 0 &&
    Number.isFinite(ramp.tunnelHeight) &&
    ramp.tunnelHeight > 0
  const temporalInvalid =
    temporal && (snapshotDay === null || !rampUsable || (plan !== null && plan.status !== 'VALID'))
  useEffect(() => {
    if (runtime === null || spawn === null || temporalInvalid) onGeometryError()
  }, [runtime, spawn, temporalInvalid, onGeometryError])

  useEffect(
    () => () => {
      clearTransientInput(keyState, inspectTrigger)
    },
    [inspectTrigger, keyState],
  )
  const reset = useCallback(() => {
    resetSignal.current += 1
  }, [])
  const setNavigationMode = useViewerStoreNav((s) => s.setNavigationMode)
  const switchMode = useCallback(
    (m: Parameters<typeof setNavigationMode>[0]) => {
      // §4: mode switching clears transient keys; the player remount
      // (key=mode) resets to the deterministic mode-specific spawn (§29)
      keyState.clear()
      setNavigationMode(m)
    },
    [keyState, setNavigationMode],
  )
  const inspect = useCallback(() => {
    // E latches the currently focused asset into the canonical global
    // selection (rule 109); no focus -> no-op
    if (focusedRef.current) select(focusedRef.current)
  }, [select])
  const handleFocusChange = useCallback(
    (id: string | null) => {
      setFocusedId(id)
      onFocusChange(id ? (focusById.get(id)?.kind ?? null) : null)
    },
    [focusById, onFocusChange],
  )

  if (!runtime || !spawn || !policy || temporalInvalid) return null
  return (
    <>
      <WalkthroughControls
        keyState={keyState}
        inspectTrigger={inspectTrigger}
        allowInspect={!temporal}
        onReset={reset}
        onInspect={inspect}
        onNavigationMode={switchMode}
      />
      <WalkthroughDiagnostics targetRef={perfRef} />
      <WalkthroughAssetLayer assets={interactables} focusedId={focusedId} selectedId={selectedId} />
      <WalkthroughInteraction
        geometry={runtime}
        assets={interactables}
        focusedRef={focusedRef}
        onFocusChange={handleFocusChange}
      />
      <WalkthroughHeadlamp config={WALKTHROUGH_CONFIG} />
      <Physics gravity={[0, -WALKTHROUGH_CONFIG.gravityMps2, 0]}>
        <TunnelColliderSet
          geometry={runtime}
          activeSegmentIds={policy.segmentIds}
          includePortalCap={policy.includePortalCap}
          includeTerminalCap={policy.includeTerminalCap}
        />
        {policy.frontierSegmentId && frontierSegment ? (
          <FrontierBarrier
            segment={frontierSegment}
            lastActiveSegmentId={policy.frontierSegmentId}
            ramp={ramp!}
          />
        ) : null}
        <WalkthroughPlayer
          key={navigationMode}
          mode={navigationMode}
          config={WALKTHROUGH_CONFIG}
          spawn={spawn}
          keyState={keyState}
          resetSignal={resetSignal}
          telemetry={telemetry}
        />
      </Physics>
    </>
  )
}
