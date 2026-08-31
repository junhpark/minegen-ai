import { useEffect, useMemo } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import {
  BufferAttribute,
  BufferGeometry,
  DoubleSide,
  Group,
  Mesh,
  MeshBasicMaterial,
  Raycaster,
  Vector3,
} from 'three'
import { WALKTHROUGH_INTERACTION_CONFIG } from './interactionConfig'
import { computeFocus } from './interactionRay'
import type { WalkthroughInteractableAsset } from './interactableAssets'
import type { TunnelRuntimeGeometry } from './tunnelRuntimeGeometry'
import { buildColliderUnits } from './tunnelRuntimeGeometry'

const DIR = new Vector3()

/**
 * Center-crosshair targeting (rule 107). Every frame while pointer lock is
 * active: cast the exact camera-forward ray, take the authoritative tunnel
 * occlusion distance from the SAME Phase 06 GLB triangles (a detached
 * double-sided raycast mesh built once from the proven runtime geometry —
 * §8 option A, no reconstruction), then run the pure focus math with the
 * runtime range and hit proxies. Focus is reported ONLY when the focused
 * id actually changes — never per-frame state churn (§13).
 */
export function WalkthroughInteraction({
  geometry,
  assets,
  lockedRef,
  focusedRef,
  onFocusChange,
}: {
  geometry: TunnelRuntimeGeometry
  assets: readonly WalkthroughInteractableAsset[]
  lockedRef: { current: boolean }
  focusedRef: { current: string | null }
  onFocusChange: (id: string | null) => void
}) {
  const camera = useThree((s) => s.camera)

  // detached occlusion mesh: exact GLB triangles in canonical Three
  // coordinates, double-sided so interior/exterior winding cannot leak rays
  const occluder = useMemo(() => {
    // identical triangle set to the Phase 13 physics colliders: built from
    // the same collider units (shared vertex buffer, exact source indices)
    const group = new Group()
    const material = new MeshBasicMaterial({ side: DoubleSide })
    for (const unit of buildColliderUnits(geometry)) {
      const g = new BufferGeometry()
      g.setAttribute('position', new BufferAttribute(unit.vertices, 3))
      g.setIndex(new BufferAttribute(unit.indices, 1))
      group.add(new Mesh(g, material))
    }
    return group
  }, [geometry])
  useEffect(
    () => () => {
      occluder.children.forEach((c) => (c as Mesh).geometry.dispose())
    },
    [occluder],
  )

  const raycaster = useMemo(() => {
    const r = new Raycaster()
    r.far = WALKTHROUGH_INTERACTION_CONFIG.maxInteractionDistanceM + 5
    return r
  }, [])

  useFrame(() => {
    let next: string | null = null
    if (lockedRef.current && assets.length > 0) {
      camera.getWorldDirection(DIR)
      raycaster.set(camera.position, DIR)
      const wallHit = raycaster.intersectObject(occluder, true)[0]
      next = computeFocus(
        [camera.position.x, camera.position.y, camera.position.z],
        [DIR.x, DIR.y, DIR.z],
        assets,
        wallHit ? wallHit.distance : null,
        WALKTHROUGH_INTERACTION_CONFIG,
      )
    }
    if (next !== focusedRef.current) {
      focusedRef.current = next
      onFocusChange(next)
    }
  })
  return null
}
