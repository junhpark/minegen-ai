import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useThree } from '@react-three/fiber'
import { PointerLockControls, useGLTF } from '@react-three/drei'
import { Physics } from '@react-three/rapier'
import { WALKTHROUGH_CONFIG } from './config'
import { createKeyState } from './movement'
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
  onLockChange,
  onFocusChange,
  onGeometryError,
}: {
  meshUrl: string
  scene: WorldScene
  onLockChange: (locked: boolean) => void
  onFocusChange: (kind: 'MESH_ROUTER' | 'GAS_SENSOR' | null) => void
  onGeometryError: () => void
}) {
  const smoothed = scene.smoothedDecline!
  const gltf = useGLTF(meshUrl)
  const camera = useThree((s) => s.camera)
  const keyState = useMemo(() => createKeyState(), [])
  const lockedRef = useRef(false)
  const resetSignal = useRef(0)
  const focusedRef = useRef<string | null>(null)
  // mirror of focusedRef for rendering; updated ONLY when the id changes
  const [focusedId, setFocusedId] = useState<string | null>(null)
  const select = useViewerStore((s) => s.select)
  // rule 106: interactables come only from backend-authored placements,
  // filtered to the walkable decline domain by authoritative topology
  const interactables = useMemo(() => resolveWalkthroughAssets(scene).assets, [scene])
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
  const activeSegmentIds = useMemo(
    () => (runtime ? runtime.segments.map((s) => s.segmentId) : []),
    [runtime],
  )

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

  // defensive: unreachable geometry -> leave walkthrough cleanly (§13)
  useEffect(() => {
    if (runtime === null || spawn === null) onGeometryError()
  }, [runtime, spawn, onGeometryError])

  const handleLock = useCallback(() => {
    lockedRef.current = true
    onLockChange(true)
  }, [onLockChange])
  const handleUnlock = useCallback(() => {
    lockedRef.current = false
    keyState.clear()
    onLockChange(false)
  }, [keyState, onLockChange])
  useEffect(
    () => () => {
      lockedRef.current = false
      keyState.clear()
      if (document.pointerLockElement) document.exitPointerLock()
    },
    [keyState],
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

  if (!runtime || !spawn) return null
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
        <TunnelColliderSet geometry={runtime} activeSegmentIds={activeSegmentIds} />
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
