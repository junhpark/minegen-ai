import { Suspense } from 'react'
import { API_BASE_URL } from '@/api/client'
import { Grid, Text } from '@react-three/drei'
import { mineToThree } from '@/geometry/coordinateTransform'
import { useScenarioStore } from '@/stores/scenarioStore'
import { useSliceStore } from '@/stores/sliceStore'
import { useViewerStore } from '@/stores/viewerStore'
import { AccessTargetsLayer } from './AccessTargetsLayer'
import { FaultLayer } from './FaultLayer'
import { GradeBlocksLayer } from './GradeBlocksLayer'
import { OrebodyLayer } from './OrebodyLayer'
import { RawDeclineLayer } from './RawDeclineLayer'
import { SmoothedDeclineLayer } from './SmoothedDeclineLayer'
import { TunnelMeshLayer } from './TunnelMeshLayer'
import { LevelDevelopmentLayer } from './LevelDevelopmentLayer'
import { NetworkLayer } from './NetworkLayer'
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
  const visible = useViewerStore((s) => s.visibleLayers)
  const slice = useSliceStore((s) => s.slice)

  const sizeX = scenario?.world.sizeX ?? 1200
  const sizeY = scenario?.world.sizeY ?? 1200
  const baseZ = scenario?.terrain.baseElevation ?? 300
  const activeSlice = slice ?? scene?.rockQuality.defaultSlice ?? null

  return (
    <>
      <ambientLight intensity={0.4} />
      <directionalLight position={mineToThree(-400, -600, baseZ + 900)} intensity={1.1} />
      <directionalLight position={mineToThree(500, 300, baseZ - 800)} intensity={0.25} />

      {!scene || !visible.has('terrain') ? (
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
      {scene && visible.has('gradeBlocks') ? <GradeBlocksLayer blocks={scene.oreBlocks} /> : null}
      {scene && activeSlice && visible.has('rockQuality') ? (
        <RockQualitySliceLayer slice={activeSlice} />
      ) : null}
      {scene?.accessTargets && visible.has('accessTargets') ? (
        <AccessTargetsLayer targets={scene.accessTargets} />
      ) : null}
      {scene?.tunnelMesh?.status === 'SUCCESS' &&
      scene.tunnelMesh.meshUrl &&
      visible.has('tunnelMesh') ? (
        <Suspense fallback={null}>
          <TunnelMeshLayer url={`${API_BASE_URL}${scene.tunnelMesh.meshUrl}`} />
        </Suspense>
      ) : null}
      {scene?.levels && (visible.has('levels') || visible.has('crosscuts')) ? (
        <LevelDevelopmentLayer
          levels={scene.levels}
          showDrifts={visible.has('levels')}
          showCrosscuts={visible.has('crosscuts')}
        />
      ) : null}
      {scene?.network && visible.has('network') ? <NetworkLayer network={scene.network} /> : null}
      {scene?.smoothedDecline && visible.has('smoothedDecline') ? (
        <SmoothedDeclineLayer smoothed={scene.smoothedDecline} />
      ) : null}
      {scene?.decline && visible.has('rawSearchPath') ? (
        <RawDeclineLayer decline={scene.decline} />
      ) : null}

      <AxisTriad origin={[-sizeX / 2, -sizeY / 2, baseZ]} length={150} />
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
