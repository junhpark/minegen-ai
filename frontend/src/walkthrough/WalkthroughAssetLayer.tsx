import { useMemo } from 'react'
import { MeshStandardMaterial, OctahedronGeometry, TetrahedronGeometry } from 'three'
import { WALKTHROUGH_INTERACTION_CONFIG } from './interactionConfig'
import type { WalkthroughInteractableAsset } from './interactableAssets'

/**
 * Walkthrough-only physical marker rendering (§11). Deliberately separate
 * from the Phase 11/12 INFRASTRUCTURE layers — communicationLayersActive()
 * and sensorLayersActive() keep their INFRASTRUCTURE-only contract and are
 * not consulted here. Markers are compact runtime symbols at backend asset
 * positions (no invented wall-mount offsets, no coverage overlays) and are
 * NEVER physics colliders (§23) — the player walks through them because
 * real mounting geometry is not modeled. One mesh per asset with the asset
 * id as key: identity never depends on instance order (rule 109).
 */
const R = WALKTHROUGH_INTERACTION_CONFIG.markerRadiusM

const ROUTER_GEOMETRY = new OctahedronGeometry(R, 0)
const SENSOR_GEOMETRY = new TetrahedronGeometry(R, 0)
const MATERIALS = {
  router: new MeshStandardMaterial({ color: '#e8a33d', emissive: '#5c3d0e' }),
  routerFocused: new MeshStandardMaterial({ color: '#ffc76b', emissive: '#a9741f' }),
  routerSelected: new MeshStandardMaterial({ color: '#ffd894', emissive: '#e8a33d' }),
  sensor: new MeshStandardMaterial({ color: '#43c6b8', emissive: '#0f4b45' }),
  sensorFocused: new MeshStandardMaterial({ color: '#7de4d8', emissive: '#1f8a7d' }),
  sensorSelected: new MeshStandardMaterial({ color: '#aef2e9', emissive: '#43c6b8' }),
}

export function WalkthroughAssetLayer({
  assets,
  focusedId,
  selectedId,
}: {
  assets: readonly WalkthroughInteractableAsset[]
  focusedId: string | null
  selectedId: string | null
}) {
  const byKind = useMemo(
    () => ({
      routers: assets.filter((a) => a.kind === 'MESH_ROUTER'),
      sensors: assets.filter((a) => a.kind === 'GAS_SENSOR'),
    }),
    [assets],
  )
  const material = (asset: WalkthroughInteractableAsset) => {
    const base = asset.kind === 'MESH_ROUTER' ? 'router' : 'sensor'
    if (asset.id === selectedId) return MATERIALS[`${base}Selected`]
    if (asset.id === focusedId) return MATERIALS[`${base}Focused`]
    return MATERIALS[base]
  }
  const scale = (asset: WalkthroughInteractableAsset) =>
    asset.id === selectedId ? 1.45 : asset.id === focusedId ? 1.25 : 1
  return (
    <>
      {byKind.routers.map((a) => (
        <mesh
          key={a.id}
          geometry={ROUTER_GEOMETRY}
          material={material(a)}
          position={a.positionThree}
          scale={scale(a)}
        />
      ))}
      {byKind.sensors.map((a) => (
        <mesh
          key={a.id}
          geometry={SENSOR_GEOMETRY}
          material={material(a)}
          position={a.positionThree}
          scale={scale(a)}
        />
      ))}
    </>
  )
}
