import { useEffect, useMemo } from 'react'
import * as THREE from 'three'
import { productionSolids, type ProductionSolidKind } from '@/scene/production'
import { staticBatches } from '@/scene/productionBatches'
import { mergeSolids, prepareSolid } from '@/scene/solidGeometry'
import type { ProductionPayload } from '@/types/scene'

/** Visual-only kind palette — never an engineering classification. */
const KIND_STYLE: Record<ProductionSolidKind, { color: string; opacity: number }> = {
  STOPE: { color: '#c9a4de', opacity: 0.28 },
  CUT: { color: '#7ec8c3', opacity: 0.3 },
  BENCH: { color: '#e0a35a', opacity: 0.32 },
  // retained material: denser and greyer than the mined volumes
  PILLAR: { color: '#8d8f96', opacity: 0.5 },
}
const INVALID_COLOR = '#d9655a'

/**
 * Static production layer (Phase 09 stopes → Phase 21B/C cuts, benches,
 * pillars): translucent prisms from the ACTIVE production payload. Every
 * solid is PLANNED here; temporal states belong to the 4D layer. The kind
 * decides the colour only — the backend decided the geometry and the QA.
 *
 * Rendering is BATCHED (review item 5): one merged geometry + one material
 * per (kind, validity), so a ≈ 7,300-solid Room & Pillar panel is a handful
 * of draw calls instead of thousands. Batching concatenates the persisted
 * triangles verbatim; it computes no geometry.
 */
export function ProductionLayer({ production }: { production: ProductionPayload }) {
  const batches = useMemo(
    () =>
      staticBatches(productionSolids(production)).map((b) => ({
        key: b.key,
        geometry: mergeSolids(b.solids.map((s) => prepareSolid(s.geometry))),
        style: KIND_STYLE[b.kind],
        valid: b.valid,
        count: b.solids.length,
      })),
    [production],
  )
  // release the merged buffers when the payload changes or the layer unmounts
  useEffect(() => {
    return () => {
      for (const b of batches) b.geometry.dispose()
    }
  }, [batches])

  return (
    <group>
      {batches.map((b) => (
        <mesh key={b.key} geometry={b.geometry} userData={{ batch: b.key, solids: b.count }}>
          <meshStandardMaterial
            color={b.valid ? b.style.color : INVALID_COLOR}
            transparent
            opacity={b.style.opacity}
            side={THREE.DoubleSide}
            depthWrite={false}
          />
        </mesh>
      ))}
    </group>
  )
}
