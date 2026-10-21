import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { Physics } from '@react-three/rapier'
import { WALKTHROUGH_CONFIG } from './config'
import { createModeScopedKeyStates } from './movement'
import { clearTransientInput, createInspectTrigger } from './interactionRay'
import {
  resolveColliderPolicy,
  resolveWalkthroughComposition,
  type WalkthroughContext,
} from './colliderPolicy'
import { chaseFor, navigationBody } from './navigation'
import { useViewerStore as useViewerStoreNav } from '@/stores/viewerStore'
import type { WalkthroughTelemetry } from './telemetry'
import { resolveTemporalWalkthroughPlan } from './temporalPlan'
import { FrontierBarrier } from './FrontierBarrier'
import {
  polylineLength,
  resolveBodySpawn,
  resolveSpawnAtChainage,
  resolveSpawnOnPolyline,
  type WalkthroughSpawn,
} from './spawn'
import type { TeleportTarget } from './teleport'
import { nextVehiclePreset } from './vehicle'
import { Vector3 } from 'three'
import { extractTunnelRuntimeGeometry } from './tunnelRuntimeGeometry'
import { TunnelColliderSet } from './TunnelColliderSet'
import {
  developmentPieceIdentities,
  extractDevelopmentRuntimeGeometry,
  type DevelopmentColliderSelection,
  type DevelopmentKind,
  type DevelopmentRuntimeGeometry,
} from './developmentRuntimeGeometry'
import { DevelopmentColliderSet } from './DevelopmentColliderSet'
import { PlugBarrierSet } from './PlugBarrierSet'
import { resolveTemporalDevelopmentPlan } from './temporalDevelopmentPlan'
import { WalkthroughControls } from './WalkthroughControls'
import { WalkthroughHeadlamp } from './WalkthroughHeadlamp'
import { WalkthroughPlayer } from './WalkthroughPlayer'
import type { TunnelJunctionSummary, WorldScene } from '@/types/scene'
import { resolveApertureContainment } from './apertureBarrier'
import { ApertureBarrierSet } from './ApertureBarrierSet'
import { useViewerStore } from '@/stores/viewerStore'
import { resolveWalkthroughAssets } from './interactableAssets'
import { WalkthroughAssetLayer } from './WalkthroughAssetLayer'
import { WalkthroughInteraction } from './WalkthroughInteraction'
import { WalkthroughDiagnostics } from './WalkthroughDiagnostics'

/** a level-entry teleport lands this far back inside the access, facing the
 * drift (clear of the entry's temporal plug and the drift wall) */
const LEVEL_ENTRY_SETBACK_M = 3.0

/**
 * Phase 20D.2 (rule 187): development collision from the emitted
 * `development_mesh.glb` (STATIC_FINAL: the final layout; TIMELINE_SNAPSHOT,
 * PR-4 W1a: the ACTIVE pieces of the temporal plan). This wrapper OWNS the
 * development URL so the hook order of the core runtime never depends on
 * whether a development mesh exists: it suspends on the same drei-cached
 * GLB the visual layer renders (one buffer for visual and collision
 * geometry), validates the writer contract ONCE per loaded scene and only
 * then mounts the core — the physics world never exists without the
 * development colliders it was promised. A contract violation fails the
 * walkthrough closed through `onGeometryError` (the composition contract,
 * never a silent ramp-only fallback).
 */
function DevelopmentRuntime(props: WalkthroughRuntimeProps & { developmentMeshUrl: string }) {
  const gltf = useGLTF(props.developmentMeshUrl)
  const developmentGeometry = useMemo(() => {
    try {
      return extractDevelopmentRuntimeGeometry(gltf.scene)
    } catch {
      return null
    }
  }, [gltf])
  const composition = resolveWalkthroughComposition(
    props.context,
    props.scene.developmentMesh,
    developmentGeometry ? 'VALID' : 'MALFORMED',
  )
  const { onGeometryError } = props
  useEffect(() => {
    if (composition.failClosed) onGeometryError()
  }, [composition.failClosed, onGeometryError])
  if (composition.failClosed || !developmentGeometry) return null
  return <WalkthroughRuntimeCore {...props} developmentGeometry={developmentGeometry} />
}

interface WalkthroughRuntimeProps {
  meshUrl: string
  /** Phase 20D.2: STATIC_FINAL development GLB (null = ramp-only walkthrough) */
  developmentMeshUrl: string | null
  scene: WorldScene
  context: WalkthroughContext
  snapshotDay: number | null
  ramp: { tunnelWidth: number; tunnelHeight: number } | null
  perfRef: { current: HTMLDivElement | null }
  telemetry: WalkthroughTelemetry
  /** MineCanvas registers the HUD-facing teleport executor here */
  registerTeleport: (fn: ((target: TeleportTarget) => void) | null) => void
  onFocusChange: (kind: 'MESH_ROUTER' | 'GAS_SENSOR' | null) => void
  onGeometryError: () => void
}

/**
 * Entry point: the development URL decides WHICH component tree renders
 * (never which hooks a component calls). With a development mesh the
 * loader wrapper suspends first; without one the core mounts directly on
 * the ramp-only baseline (rule 103).
 */
export function WalkthroughRuntime(props: WalkthroughRuntimeProps) {
  if (props.developmentMeshUrl !== null) {
    return <DevelopmentRuntime {...props} developmentMeshUrl={props.developmentMeshUrl} />
  }
  return <WalkthroughRuntimeCore {...props} developmentGeometry={null} />
}

/**
 * First-person runtime owner (rules 99–104). Mounted by MineCanvas ONLY in
 * walkthrough camera mode — orbit controls never coexist with it. Collision
 * derives from the same cached GLB the visual layer renders; extraction is
 * memoized by mesh URL and never runs per frame. Player/camera state is
 * ephemeral and unmounts cleanly with the physics world.
 */
function WalkthroughRuntimeCore({
  meshUrl,
  scene,
  context,
  snapshotDay,
  ramp,
  perfRef,
  telemetry,
  registerTeleport,
  onFocusChange,
  onGeometryError,
  developmentGeometry,
}: WalkthroughRuntimeProps & { developmentGeometry: DevelopmentRuntimeGeometry | null }) {
  const smoothed = scene.smoothedDecline!
  const temporal = context === 'TIMELINE_SNAPSHOT'
  // rule 112 (PR #12 blocker 2): the temporal plan consumes the artifacts
  // captured at MOUNT, never live scene updates — a replaced artifact can
  // only trigger the MineCanvas identity gate (clean exit to 4D), never a
  // re-snapshot of the running physics topology
  const frozenRef = useRef<{
    timeline: WorldScene['timeline']
    smoothed: NonNullable<WorldScene['smoothedDecline']>
    // Phase 20D.2: the aperture containment inputs are frozen with the plan
    levelAccesses: WorldScene['levelAccesses']
    tunnelJunctions: TunnelJunctionSummary | null
    // PR-4 W1a: the development plan inputs are frozen with it too
    levels: WorldScene['levels']
    network: WorldScene['network']
  } | null>(null)
  if (temporal && frozenRef.current === null) {
    frozenRef.current = {
      timeline: scene.timeline,
      smoothed,
      levelAccesses: scene.levelAccesses,
      tunnelJunctions: scene.tunnelMesh?.junctions ?? null,
      levels: scene.levels,
      network: scene.network,
    }
  }
  const planTimeline = temporal ? frozenRef.current!.timeline : scene.timeline
  const planSmoothed = temporal ? frozenRef.current!.smoothed : smoothed
  const planAccesses = temporal ? frozenRef.current!.levelAccesses : scene.levelAccesses
  const planJunctions = temporal
    ? frozenRef.current!.tunnelJunctions
    : (scene.tunnelMesh?.junctions ?? null)
  const planLevels = temporal ? frozenRef.current!.levels : scene.levels
  const planNetwork = temporal ? frozenRef.current!.network : scene.network
  const gltf = useGLTF(meshUrl)
  const camera = useThree((s) => s.camera)
  const navigationMode = useViewerStoreNav((s) => s.navigationMode)
  const vehiclePreset = useViewerStoreNav((s) => s.vehiclePreset)
  const setVehiclePreset = useViewerStoreNav((s) => s.setVehiclePreset)
  // PR-6: chase ⇄ cab view — a camera presentation choice, never a body
  // change (no remount, no spawn, no collider change)
  const cameraView = useViewerStoreNav((s) => s.walkCameraView)
  const toggleCameraView = useViewerStoreNav((s) => s.toggleWalkCameraView)
  // PR-4 W2: a preset change is a body change — same remount-at-spawn
  // contract as a mode change (§29), one key for both
  const bodyKey = `${navigationMode}:${vehiclePreset}`
  // PR #13 blocker 2: KeyState is MODE-SCOPED — recreated for every
  // navigationMode value, so both the 1/2/3 keyboard path and the HUD
  // buttons (which mutate the store directly) start the new mode with an
  // empty movement/look/action state through the same mechanism
  const keyStates = useMemo(() => createModeScopedKeyStates(), [])
  const keyState = useMemo(() => keyStates.forMode(bodyKey), [keyStates, bodyKey])
  // the avatar's eye point (Three coordinates), written by the player each
  // frame and read by the interaction ray and the headlamp (rule 107)
  const eyeRef = useRef(new Vector3())
  // PR-6: the body's lamp point (the headlamp beam origin) — the truck's
  // headlights, the miner's cap lamp, the drone's front
  const lampRef = useRef(new Vector3())
  // owned here so EVERY lifecycle exit can reach it (PR #11 blocker 1)
  const inspectTrigger = useMemo(() => createInspectTrigger(), [])
  const resetSignal = useRef(0)
  const teleportRef = useRef<WalkthroughSpawn | null>(null)
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
  // mode-specific deterministic spawn (§30): floor reference stays
  // authoritative; the body dimensions differ per mode and the body starts
  // its chase line deeper than the entry reference (`bodySpawnChainageM`)
  const spawn = useMemo(() => {
    const nav = navigationBody(navigationMode, vehiclePreset)
    return resolveBodySpawn(
      planSmoothed,
      { ...WALKTHROUGH_CONFIG, bodyHeightM: nav.bodyHeightM },
      chaseFor(navigationMode, vehiclePreset),
    )
  }, [planSmoothed, navigationMode, vehiclePreset])
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
  // PR-4 W1a: which development pieces are present at the snapshot day and
  // where the ACTIVE excavation opens onto a not-yet-active development
  const devPlan = useMemo(
    () =>
      temporal && developmentGeometry && policy && snapshotDay !== null
        ? resolveTemporalDevelopmentPlan(
            planTimeline,
            planLevels,
            planAccesses,
            planNetwork,
            planSmoothed,
            developmentPieceIdentities(developmentGeometry),
            snapshotDay,
            policy.segmentIds,
          )
        : null,
    [
      temporal,
      developmentGeometry,
      policy,
      snapshotDay,
      planTimeline,
      planLevels,
      planAccesses,
      planNetwork,
      planSmoothed,
    ],
  )
  const devSelection = useMemo<DevelopmentColliderSelection | null>(
    () =>
      devPlan && devPlan.status === 'VALID'
        ? {
            pieceIds: new Set(devPlan.activePieceIds),
            capKinds: new Set<DevelopmentKind>(devPlan.activeKinds),
          }
        : null,
    [devPlan],
  )
  const openLevelIds = useMemo(
    () => new Set(devPlan && devPlan.status === 'VALID' ? devPlan.openAccessLevelIds : []),
    [devPlan],
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
  // Phase 20D.2 (rule 187): every RAMP_ACCESS aperture the ramp GLB carries
  // is closed on the active segments by ephemeral wall-line barriers; an
  // aperture that cannot be located fails the temporal session closed
  const containment = useMemo(
    () =>
      temporal && policy && rampUsable
        ? resolveApertureContainment(
            planJunctions,
            planAccesses,
            planSmoothed,
            policy.segmentIds,
            ramp,
            openLevelIds,
          )
        : null,
    [temporal, policy, rampUsable, planJunctions, planAccesses, planSmoothed, ramp, openLevelIds],
  )
  const temporalInvalid =
    temporal &&
    (snapshotDay === null ||
      !rampUsable ||
      (plan !== null && plan.status !== 'VALID') ||
      (containment !== null && containment.status === 'INVALID') ||
      (devPlan !== null && devPlan.status === 'INVALID'))
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
  // teleport (hotfix 2, PR-4 W3): the same deterministic spawn rules at a
  // chosen ramp chainage, or — when the level's access excavation is
  // collided — on the level's access centerline 3 m short of its entry
  // (facing the drift); invalid targets are ignored, never guessed
  const navBodyHeight = navigationBody(navigationMode, vehiclePreset).bodyHeightM
  useEffect(() => {
    registerTeleport((target: TeleportTarget) => {
      const cfg = { ...WALKTHROUGH_CONFIG, bodyHeightM: navBodyHeight }
      let pose: WalkthroughSpawn | null = null
      if (target.kind === 'RAMP') {
        pose = resolveSpawnAtChainage(planSmoothed, cfg, target.chainageM)
      } else {
        const access = planAccesses?.accesses.find(
          (a) => a.levelId === target.levelId && a.status === 'OK' && a.centerline !== null,
        )
        const pts = access?.centerline?.points
        if (Array.isArray(pts)) {
          const length = polylineLength(pts)
          pose = resolveSpawnOnPolyline(pts, cfg, Math.max(length - LEVEL_ENTRY_SETBACK_M, 0))
        }
      }
      if (pose) {
        teleportRef.current = pose
        resetSignal.current += 1
      }
    })
    return () => registerTeleport(null)
  }, [registerTeleport, planSmoothed, planAccesses, navBodyHeight])
  const cycleVehiclePreset = useCallback(
    () => setVehiclePreset(nextVehiclePreset(vehiclePreset)),
    [setVehiclePreset, vehiclePreset],
  )
  // both keyboard and HUD funnel through the store; the mode-scoped
  // KeyState above owns the transient-input lifecycle (§29 spawn remount
  // via key={navigationMode} is unchanged)
  const setNavigationMode = useViewerStoreNav((s) => s.setNavigationMode)
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
        onNavigationMode={setNavigationMode}
        onCycleVehiclePreset={cycleVehiclePreset}
        onToggleCameraView={toggleCameraView}
      />
      <WalkthroughDiagnostics targetRef={perfRef} />
      <WalkthroughAssetLayer assets={interactables} focusedId={focusedId} selectedId={selectedId} />
      <WalkthroughInteraction
        geometry={runtime}
        assets={interactables}
        focusedRef={focusedRef}
        onFocusChange={handleFocusChange}
        eyeRef={eyeRef}
      />
      <WalkthroughHeadlamp config={WALKTHROUGH_CONFIG} eyeRef={eyeRef} beamRef={lampRef} />
      <Physics gravity={[0, -WALKTHROUGH_CONFIG.gravityMps2, 0]}>
        <TunnelColliderSet
          geometry={runtime}
          activeSegmentIds={policy.segmentIds}
          includePortalCap={policy.includePortalCap}
          includeTerminalCap={policy.includeTerminalCap}
        />
        {developmentGeometry && !temporal ? (
          <DevelopmentColliderSet geometry={developmentGeometry} />
        ) : null}
        {developmentGeometry && temporal && devSelection ? (
          <DevelopmentColliderSet geometry={developmentGeometry} selection={devSelection} />
        ) : null}
        {temporal && containment && containment.pieces.length > 0 ? (
          <ApertureBarrierSet pieces={containment.pieces} />
        ) : null}
        {temporal && devPlan && devPlan.status === 'VALID' && devPlan.plugs.length > 0 ? (
          <PlugBarrierSet plugs={devPlan.plugs} />
        ) : null}
        {policy.frontierSegmentId && frontierSegment ? (
          <FrontierBarrier
            segment={frontierSegment}
            lastActiveSegmentId={policy.frontierSegmentId}
            ramp={ramp!}
          />
        ) : null}
        <WalkthroughPlayer
          key={bodyKey}
          mode={navigationMode}
          vehiclePresetId={vehiclePreset}
          config={WALKTHROUGH_CONFIG}
          spawn={spawn}
          keyState={keyState}
          resetSignal={resetSignal}
          teleportRef={teleportRef}
          telemetry={telemetry}
          eyeRef={eyeRef}
          lampRef={lampRef}
          cameraView={cameraView}
        />
      </Physics>
    </>
  )
}
