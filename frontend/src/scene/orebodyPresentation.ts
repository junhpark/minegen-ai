/**
 * Analytic reference bodies are drawn with their edge wireframe (a box or a
 * coarse UV sphere reads well that way); the Phase 19 implicit body is a
 * dense backend-authored isosurface whose edge lines would only add noise,
 * so it is shaded smooth from its vertex normals. Visualization choice
 * only — the mesh itself is consumed exactly as the backend authored it.
 */
export function showOrebodyEdges(type: string): boolean {
  return type !== 'WARPED_VEIN'
}
