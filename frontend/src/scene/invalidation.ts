import type {
  CommunicationPayload,
  LevelsPayload,
  NetworkPayload,
  WorldScene,
  StopesPayload,
  TimelinePayload,
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
    network: null,
    stopes: null,
    timeline: null,
    communication: null,
  }
}

/** Levels rebuilt: network + stopes + timeline + communication cascade. */
export function afterLevelsRegen(scene: WorldScene, payload: LevelsPayload): WorldScene {
  return {
    ...scene,
    levels: payload,
    network: null,
    stopes: null,
    timeline: null,
    communication: null,
  }
}

/** Network rebuilt (rules 86/92): timeline and communication are stale;
 * stopes are preserved. */
export function afterNetworkRegen(scene: WorldScene, payload: NetworkPayload): WorldScene {
  return { ...scene, network: payload, timeline: null, communication: null }
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

/** Communication rebuilt (rule 92): touches nothing else. */
export function afterCommunicationRegen(
  scene: WorldScene,
  payload: CommunicationPayload,
): WorldScene {
  return { ...scene, communication: payload }
}
