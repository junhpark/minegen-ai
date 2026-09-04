import type {
  CommunicationPayload,
  DevelopmentMeshReport,
  LayoutV2Catalogue,
  LevelAccessesPayload,
  LevelsPayload,
  NetworkPayload,
  RampSourceSummary,
  SensorPayload,
  SmoothedDeclinePayload,
  StopesPayload,
  TimelinePayload,
  WorldScene,
} from '@/types/scene'

/**
 * Pure frontend mirrors of the backend dependency/invalidation semantics
 * (rules 74/79/86/92). The backend deletes the stale artifacts on disk;
 * these helpers keep the in-memory scene manifest consistent without a
 * reload. Communication and timeline are SIBLINGS: stopes/timeline
 * regeneration preserves communication, and communication regeneration
 * touches nothing else.
 */

/** Upstream geometry (targets/decline/smoothed) regenerated: every
 * downstream design artifact is stale. */
export function afterUpstreamRegen(scene: WorldScene): WorldScene {
  return {
    ...scene,
    levels: null,
    developmentMesh: null,
    network: null,
    stopes: null,
    timeline: null,
    communication: null,
    sensors: null,
  }
}

/** Levels rebuilt: development mesh + network + stopes + timeline +
 * communication cascade (the development mesh is a derivative of levels +
 * level accesses, closeout v3 §4). */
export function afterLevelsRegen(scene: WorldScene, payload: LevelsPayload): WorldScene {
  return {
    ...scene,
    levels: payload,
    developmentMesh: null,
    network: null,
    stopes: null,
    timeline: null,
    communication: null,
    sensors: null,
  }
}

/** Development mesh rebuilt (closeout v3 §4): touches nothing else. */
export function afterDevelopmentMeshRegen(
  scene: WorldScene,
  payload: DevelopmentMeshReport,
): WorldScene {
  return { ...scene, developmentMesh: payload }
}

/** Network rebuilt (rules 86/92): timeline and communication are stale;
 * stopes are preserved. */
export function afterNetworkRegen(scene: WorldScene, payload: NetworkPayload): WorldScene {
  return { ...scene, network: payload, timeline: null, communication: null, sensors: null }
}

/** Stopes rebuilt (rules 79/86/92): timeline is stale, communication and
 * everything else is preserved. */
export function afterStopesRegen(scene: WorldScene, payload: StopesPayload): WorldScene {
  return { ...scene, stopes: payload, timeline: null }
}

/** Timeline rebuilt (rule 86): touches nothing else. */
export function afterTimelineRegen(scene: WorldScene, payload: TimelinePayload): WorldScene {
  return { ...scene, timeline: payload }
}

/** Communication rebuilt (rule 92): touches nothing else — sensors,
 * timeline and everything upstream are preserved. */
export function afterCommunicationRegen(
  scene: WorldScene,
  payload: CommunicationPayload,
): WorldScene {
  return { ...scene, communication: payload }
}

/** Sensors rebuilt (rule 98): touches nothing else — communication,
 * timeline and everything upstream are preserved. */
export function afterSensorsRegen(scene: WorldScene, payload: SensorPayload): WorldScene {
  return { ...scene, sensors: payload }
}

// --------------------------------------------------------------------------- //
// Phase 20A — Effective Ramp source resolution mirrors (rules 149–151). The
// backend owns the choice and deletes the stale files; these keep the
// manifest consistent until the next scene reload.
// --------------------------------------------------------------------------- //

/** Everything derived from the ACTIVE effective ramp is stale. */
function afterRampChange(scene: WorldScene): WorldScene {
  return { ...afterUpstreamRegen(scene), tunnelMesh: null }
}

/** Legacy Phase 05 artifact (re)generated. With LEGACY active it IS the
 * effective ramp (adapter view) and the downstream chain is stale; with
 * LAYOUT_V2 active the legacy artifact changes nothing downstream. */
export function afterLegacySmoothRegen(
  scene: WorldScene,
  payload: SmoothedDeclinePayload,
): WorldScene {
  const active = scene.rampSource.activeSource
  const legacy: SmoothedDeclinePayload = {
    ...payload,
    sourceKind: payload.segments.some((s) => s.effectiveSource === 'RAW_FALLBACK')
      ? 'LEGACY_RAW_FALLBACK'
      : 'LEGACY_SMOOTHED',
    owningArtifact: 'decline_smoothed.json',
    activeSource: 'LEGACY',
    candidateId: null,
    family: null,
  }
  if (active !== 'LEGACY') {
    return {
      ...scene,
      legacySmoothedDecline: legacy,
      rampSource: { ...scene.rampSource, legacyAvailable: true },
    }
  }
  return {
    ...afterRampChange(scene),
    legacySmoothedDecline: legacy,
    smoothedDecline: legacy,
    rampSource: {
      ...scene.rampSource,
      legacyAvailable: true,
      available: true,
      owningArtifact: 'decline_smoothed.json',
      sourceKind: legacy.sourceKind ?? null,
      candidateId: null,
      family: null,
      status: legacy.status,
      segmentCount: legacy.segments.length,
    },
  }
}

/** Legacy upstream (targets / raw decline) regenerated: the legacy smoothed
 * artifact is gone; the LEGACY effective ramp with it, and its chain. */
export function afterLegacyUpstreamRegen(scene: WorldScene): WorldScene {
  const active = scene.rampSource.activeSource
  const base = active === 'LEGACY' ? afterRampChange(scene) : scene
  return {
    ...base,
    legacySmoothedDecline: null,
    smoothedDecline: active === 'LEGACY' ? null : scene.smoothedDecline,
    rampSource: {
      ...scene.rampSource,
      legacyAvailable: false,
      ...(active === 'LEGACY'
        ? { available: false, sourceKind: null, status: null, segmentCount: 0 }
        : {}),
    },
  }
}

/** Layout-v2 catalogue regenerated: any selection is stale; with LAYOUT_V2
 * active the effective ramp and its whole chain are gone too. */
export function afterLayoutRegen(scene: WorldScene, catalogue: LayoutV2Catalogue): WorldScene {
  const active = scene.rampSource.activeSource
  const base = active === 'LAYOUT_V2' ? afterRampChange(scene) : scene
  return {
    ...base,
    layoutV2: catalogue,
    layoutV2Selected: null,
    levelAccesses: null,
    smoothedDecline: active === 'LAYOUT_V2' ? null : scene.smoothedDecline,
    rampSource: {
      ...scene.rampSource,
      layoutV2Available: true,
      layoutV2Selected: false,
      ...(active === 'LAYOUT_V2'
        ? {
            available: false,
            sourceKind: null,
            candidateId: null,
            family: null,
            status: null,
            segmentCount: 0,
          }
        : {}),
    },
  }
}

/** A candidate was selected (materialized). Inert unless LAYOUT_V2 is the
 * active source, in which case it becomes the effective ramp and the chain
 * is stale. */
export function afterLayoutSelect(
  scene: WorldScene,
  selected: SmoothedDeclinePayload,
  accesses: LevelAccessesPayload | null = null,
): WorldScene {
  const active = scene.rampSource.activeSource
  // rule 157: the level-access artifact is owned by the selection
  const levelAccesses = accesses ?? scene.levelAccesses
  if (active !== 'LAYOUT_V2') {
    return {
      ...scene,
      layoutV2Selected: selected,
      levelAccesses,
      rampSource: { ...scene.rampSource, layoutV2Selected: true },
    }
  }
  if (
    scene.smoothedDecline?.candidateId === selected.candidateId &&
    scene.smoothedDecline?.layoutRevision === selected.layoutRevision
  ) {
    return { ...scene, layoutV2Selected: selected, levelAccesses }
  }
  return {
    ...afterRampChange(scene),
    layoutV2Selected: selected,
    levelAccesses,
    smoothedDecline: { ...selected, activeSource: 'LAYOUT_V2' },
    rampSource: rampSourceFor(scene.rampSource, 'LAYOUT_V2', selected),
  }
}

/** The active source switched (explicit backend response). The effective
 * ramp changes identity, so every ramp-derived artifact is stale. */
export function afterRampSourceChange(
  scene: WorldScene,
  rampSource: RampSourceSummary,
  selected: SmoothedDeclinePayload | null = scene.layoutV2Selected,
): WorldScene {
  const effective =
    rampSource.activeSource === 'LAYOUT_V2'
      ? selected
        ? { ...selected, activeSource: 'LAYOUT_V2' as const }
        : null
      : scene.legacySmoothedDecline
  if (rampSource.activeSource === scene.rampSource.activeSource) {
    return { ...scene, rampSource, layoutV2Selected: selected, smoothedDecline: effective }
  }
  return {
    ...afterRampChange(scene),
    rampSource,
    layoutV2Selected: selected,
    smoothedDecline: effective,
  }
}

function rampSourceFor(
  base: RampSourceSummary,
  active: 'LAYOUT_V2',
  selected: SmoothedDeclinePayload,
): RampSourceSummary {
  return {
    ...base,
    activeSource: active,
    owningArtifact: 'layout_v2_selected.json',
    available: true,
    layoutV2Selected: true,
    sourceKind: 'PARAMETRIC_V2',
    sourceRevision: selected.sourceRevision ?? null,
    candidateId: selected.candidateId ?? null,
    family: selected.family ?? null,
    status: selected.status,
    segmentCount: selected.segments.length,
  }
}
