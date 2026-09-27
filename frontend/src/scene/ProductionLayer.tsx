import { useMemo } from 'react'
import * as THREE from 'three'
import { productionSolids, type ProductionSolidKind } from '@/scene/production'
import { solidGeometry } from '@/scene/solidGeometry'
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
 */
export function ProductionLayer({ production }: { production: ProductionPayload }) {
  const meshes = useMemo(
    () =>
      productionSolids(production).map((s) => ({
        key: s.id,
        geometry: solidGeometry(s.geometry),
        style: KIND_STYLE[s.kind],
        valid: s.valid,
      })),
    [production],
  )

  return (
    <group>
      {meshes.map((m) => (
        <mesh key={m.key} geometry={m.geometry}>
          <meshStandardMaterial
            color={m.valid ? m.style.color : INVALID_COLOR}
            transparent
            opacity={m.style.opacity}
            side={THREE.DoubleSide}
            depthWrite={false}
          />
        </mesh>
      ))}
    </group>
  )
}
