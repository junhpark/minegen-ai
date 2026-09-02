import { Suspense } from 'react'
import { API_BASE_URL } from '@/api/client'
import { Grid, Text } from '@react-three/drei'
import { mineToThree } from '@/geometry/coordinateTransform'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useSliceStore } from '@/stores/sliceStore'
import { useViewerStore } from '@/stores/viewerStore'
import { deriveVisibleLayers } from '@/walkthrough/readiness'
import { temporalActiveSegmentIds } from '@/walkthrough/temporalPlan'
import { TemporalTunnelLayer } from '@/walkthrough/TemporalTunnelLayer'
import { AccessTargetsLayer } from './AccessTargetsLayer'
import { FaultLayer } from './FaultLayer'
import { OrebodyLayer } from './OrebodyLayer'
import { RawDeclineLayer } from './RawDeclineLayer'
import { SmoothedDeclineLayer } from './SmoothedDeclineLayer'
import { TunnelMeshLayer } from './TunnelMeshLayer'
import { LevelDevelopmentLayer } from './LevelDevelopmentLayer'
import { NetworkLayer } from './NetworkLayer'
import { StopeLayer } from './StopeLayer'
import { TimelineDevelopmentLayer } from './TimelineDevelopmentLayer'
import { TimelineStopeLayer } from './TimelineStopeLayer'
import { CommunicationRouterLayer } from './CommunicationRouterLayer'
import { CommunicationCoverageLayer } from './CommunicationCoverageLayer'
import { communicationLayersActive, sensorLayersActive } from '@/infrastructure/view'
import { SensorLayer } from './SensorLayer'
import { SensorCoverageLayer } from './SensorCoverageLayer'
import { staticExcavationVisibleIn4D } from '@/timeline/evaluate'
import { RockQualitySliceLayer } from './RockQualitySliceLayer'
import { TerrainLayer } from './TerrainLayer'

/**
 * Mine scene. Layers are siblings toggled by the viewer store; each layer
 * converts mine → Three.js coordinates at its own boundary and nowhere else.
 * The reference grid sits at the terrain reference elevation and the
 * E / N / UP triad marks the world corner so coordinate errors are visible.
 */
export function MineScene() {
  const scenario = useScenarioStore((s) => s.scenario)
  const scene = useScenarioStore((s) => s.scene)
  const storedVisible = useViewerStore((s) => s.visibleLayers)
  const mode = useViewerStore((st) => st.mode)
  // §15: walkthrough derives an immersive view; stored layers are untouched
  const visible = deriveVisibleLayers(mode, storedVisible)
  const walkthroughActive = mode === 'WALKTHROUGH'
  const walkthroughContext = useViewerStore((st) => st.walkthroughContext)
  const walkthroughSnapshotDay = useViewerStore((st) => st.walkthroughSnapshotDay)
  // §13: TIMELINE_SNAPSHOT never renders the full static tunnel GLB
  const temporalWalk = walkthroughActive && walkthroughContext === 'TIMELINE_SNAPSHOT'
  const temporalIds =
    temporalWalk && walkthroughSnapshotDay !== null
      ? temporalActiveSegmentIds(scene?.timeline, scene?.smoothedDecline, walkthroughSnapshotDay)
      : null
  const timelineActive = mode === '4D' && scene?.timeline?.status === 'SUCCESS'
  // rules 88/91: INFRASTRUCTURE mode only; routers are never shown as
  // time-valid installed assets in 4D (installation timing is not modeled)
  const communicationActive = communicationLayersActive(mode, scene?.communication ?? null)
  // rules 97/98: INFRASTRUCTURE mode only; sensors are never shown as
  // time-valid installed assets in 4D (installation timing is not modeled)
  const sensorsActive = sensorLayersActive(mode, scene?.sensors ?? null)
  const showStatic = staticExcavationVisibleIn4D(timelineActive)
  const slice = useSliceStore((s) => s.slice)

  const sizeX = scenario?.world.sizeX ?? 1200
  const sizeY = scenario?.world.sizeY ?? 1200
  const baseZ = scenario?.terrain.baseElevation ?? 300
  const activeSlice = slice ?? scene?.rockQuality.defaultSlice ?? null

  return (
    <>
      <ambientLight intensity={walkthroughActive ? 0.32 : 0.4} />
      {walkthroughActive ? <hemisphereLight args={['#8f99a3', '#3a332b', 0.4]} /> : null}
      {walkthroughActive ? null : (
        <>
          <directionalLight position={mineToThree(-400, -600, baseZ + 900)} intensity={1.1} />
          <directionalLight position={mineToThree(500, 300, baseZ - 800)} intensity={0.25} />
        </>
      )}

      {!walkthroughActive && (!scene || !visible.has('terrain')) ? (
        <group position={mineToThree(0, 0, baseZ)}>
          <Grid
            args={[sizeX, sizeY]}
            cellSize={50}
            sectionSize={250}
            cellColor="#2c353e"
            sectionColor="#3c4751"
            fadeDistance={4000}
            fadeStrength={1}
            infiniteGrid={false}
          />
        </group>
      ) : null}

      {scene && visible.has('terrain') ? <TerrainLayer terrain={scene.terrain} /> : null}
      {scene && visible.has('orebody') ? <OrebodyLayer orebody={scene.orebody} /> : null}
      {scene && visible.has('faults') ? <FaultLayer faults={scene.faults} /> : null}
      {scene && activeSlice && visible.has('rockQuality') ? (
        <RockQualitySliceLayer slice={activeSlice} />
      ) : null}
      {scene?.accessTargets && visible.has('accessTargets') ? (
        <AccessTargetsLayer targets={scene.accessTargets} />
      ) : null}
      {scene?.tunnelMesh?.status === 'SUCCESS' &&
      scene.tunnelMesh.meshUrl &&
      visible.has('tunnelMesh') ? (
        temporalWalk ? (
          temporalIds !== null ? (
            <Suspense fallback={null}>
              <TemporalTunnelLayer
                url={`${API_BASE_URL}${scene.tunnelMesh.meshUrl}`}
                activeSegmentIds={temporalIds}
                allSegmentsActive={
                  temporalIds.length === (scene.smoothedDecline?.segments.length ?? -1)
                }
              />
            </Suspense>
          ) : null
        ) : showStatic ? (
          <Suspense fallback={null}>
            <TunnelMeshLayer url={`${API_BASE_URL}${scene.tunnelMesh.meshUrl}`} />
          </Suspense>
        ) : null
      ) : null}
      {showStatic && scene?.levels && (visible.has('levels') || visible.has('crosscuts')) ? (
        <LevelDevelopmentLayer
          levels={scene.levels}
          showDrifts={visible.has('levels')}
          showCrosscuts={visible.has('crosscuts')}
        />
      ) : null}
      {scene?.network && visible.has('network') ? <NetworkLayer network={scene.network} /> : null}
      {communicationActive && scene?.communication && visible.has('routers') ? (
        <CommunicationRouterLayer communication={scene.communication} />
      ) : null}
      {communicationActive && scene?.communication && visible.has('coverage') ? (
        <CommunicationCoverageLayer communication={scene.communication} />
      ) : null}
      {sensorsActive && scene?.sensors && visible.has('sensors') ? (
        <SensorLayer sensors={scene.sensors} />
      ) : null}
      {sensorsActive && scene?.sensors && visible.has('sensorCoverage') ? (
        <SensorCoverageLayer sensors={scene.sensors} />
      ) : null}
      {timelineActive && scene?.timeline && scene.smoothedDecline && scene.levels ? (
        <TimelineDevelopmentLayer
          timeline={scene.timeline}
          smoothed={scene.smoothedDecline}
          levels={scene.levels}
        />
      ) : null}
      {timelineActive && scene?.timeline && scene.stopes ? (
        <TimelineStopeLayer timeline={scene.timeline} stopes={scene.stopes} />
      ) : null}
      {showStatic && scene?.stopes && visible.has('stopes') ? (
        <StopeLayer stopes={scene.stopes} />
      ) : null}
      {showStatic && scene?.smoothedDecline && visible.has('smoothedDecline') ? (
        <SmoothedDeclineLayer smoothed={scene.smoothedDecline} />
      ) : null}
      {scene?.decline && visible.has('rawSearchPath') ? (
        <RawDeclineLayer decline={scene.decline} />
      ) : null}

      {walkthroughActive ? null : (
        <AxisTriad origin={[-sizeX / 2, -sizeY / 2, baseZ]} length={150} />
      )}
    </>
  )
}

interface AxisTriadProps {
  origin: [number, number, number]
  length: number
}

/** E / N / Up triad, drawn in mine coordinates and converted at the boundary. */
function AxisTriad({ origin, length }: AxisTriadProps) {
  const [ox, oy, oz] = origin
  const axes: { label: string; end: [number, number, number]; color: string }[] = [
    { label: 'E', end: [ox + length, oy, oz], color: '#d9655a' },
    { label: 'N', end: [ox, oy + length, oz], color: '#4fb3a5' },
    { label: 'UP', end: [ox, oy, oz + length], color: '#f0b84a' },
  ]
  const o = mineToThree(ox, oy, oz)
  return (
    <group>
      {axes.map((a) => {
        const e = mineToThree(...a.end)
        return (
          <group key={a.label}>
            <line>
              <bufferGeometry>
                <bufferAttribute
                  attach="attributes-position"
                  args={[new Float32Array([...o, ...e]), 3]}
                />
              </bufferGeometry>
              <lineBasicMaterial color={a.color} />
            </line>
            <Text position={e} fontSize={18} color={a.color} anchorX="center" anchorY="middle">
              {a.label}
            </Text>
          </group>
        )
      })}
    </group>
  )
}
