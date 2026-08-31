import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useThree } from '@react-three/fiber'
import { PointerLockControls, useGLTF } from '@react-three/drei'
import { Physics } from '@react-three/rapier'
import { WALKTHROUGH_CONFIG } from './config'
import { createKeyState } from './movement'
import { clearTransientInput, createInspectTrigger } from './interactionRay'
import { resolveColliderPolicy, type WalkthroughContext } from './colliderPolicy'
import { resolveTemporalWalkthroughPlan } from './temporalPlan'
import { FrontierBarrier } from './FrontierBarrier'
import { WALKTHROUGH_LOCK_SURFACE_SELECTOR } from './lockSurface'
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
  onLockChange,
  onFocusChange,
  onGeometryError,
}: {
  meshUrl: string
  scene: WorldScene
  context: WalkthroughContext
  snapshotDay: number | null
  ramp: { tunnelWidth: number; tunnelHeight: number }
  onLockChange: (locked: boolean) => void
  onFocusChange: (kind: 'MESH_ROUTER' | 'GAS_SENSOR' | null) => void
  onGeometryError: () => void
}) {
  const smoothed = scene.smoothedDecline!
  const temporal = context === 'TIMELINE_SNAPSHOT'
  const gltf = useGLTF(meshUrl)
  const camera = useThree((s) => s.camera)
  const keyState = useMemo(() => createKeyState(), [])
  // owned here so EVERY lifecycle exit can reach it (PR #11 blocker 1)
  const inspectTrigger = useMemo(() => createInspectTrigger(), [])
  const lockedRef = useRef(false)
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
  const spawn = useMemo(() => resolveWalkthroughSpawn(smoothed, WALKTHROUGH_CONFIG), [smoothed])
  // rule 112: the temporal plan is resolved ONCE per snapshot and the
  // physical topology stays immutable for the session
  const plan = useMemo(
    () =>
      temporal && runtime && snapshotDay !== null
        ? resolveTemporalWalkthroughPlan(scene.timeline, smoothed, runtime, snapshotDay)
        : null,
    [temporal, runtime, scene.timeline, smoothed, snapshotDay],
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
    return smoothed.segments[plan.lastActiveSegmentIndex] ?? null
  }, [plan, smoothed])

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
  const temporalInvalid =
    temporal && (snapshotDay === null || (plan !== null && plan.status !== 'VALID'))
  useEffect(() => {
    if (runtime === null || spawn === null || temporalInvalid) onGeometryError()
  }, [runtime, spawn, temporalInvalid, onGeometryError])

  const handleLock = useCallback(() => {
    lockedRef.current = true
    onLockChange(true)
  }, [onLockChange])
  const handleUnlock = useCallback(() => {
    lockedRef.current = false
    clearTransientInput(keyState, inspectTrigger)
    onLockChange(false)
  }, [inspectTrigger, keyState, onLockChange])
  useEffect(
    () => () => {
      lockedRef.current = false
      clearTransientInput(keyState, inspectTrigger)
      if (document.pointerLockElement) document.exitPointerLock()
    },
    [inspectTrigger, keyState],
  )
  const reset = useCallback(() => {
    resetSignal.current += 1
  }, [])
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
      <PointerLockControls
        selector={WALKTHROUGH_LOCK_SURFACE_SELECTOR}
        onLock={handleLock}
        onUnlock={handleUnlock}
      />
      <WalkthroughControls
        keyState={keyState}
        lockedRef={lockedRef}
        inspectTrigger={inspectTrigger}
        onReset={reset}
        onInspect={inspect}
      />
      <WalkthroughAssetLayer assets={interactables} focusedId={focusedId} selectedId={selectedId} />
      <WalkthroughInteraction
        geometry={runtime}
        assets={interactables}
        lockedRef={lockedRef}
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
            ramp={ramp}
          />
        ) : null}
        <WalkthroughPlayer
          config={WALKTHROUGH_CONFIG}
          spawn={spawn}
          keyState={keyState}
          lockedRef={lockedRef}
          resetSignal={resetSignal}
        />
      </Physics>
    </>
  )
}
