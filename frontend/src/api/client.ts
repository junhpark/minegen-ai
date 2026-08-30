// Typed fetch client. Thin: no engineering logic, no coordinate conversion.

import type { HealthResponse, Scenario, ScenarioCreate, ScenarioSummary } from '@/types/api'
import type {
  AccessTargetsPayload,
  CommunicationPayload,
  CostEvaluationRow,
  DeclinePayload,
  JobRecord,
  JobSubmission,
  LevelsPayload,
  NetworkPayload,
  SensorPayload,
  SliceAxis,
  SliceField,
  SlicePayload,
  SmoothedDeclinePayload,
  StopesPayload,
  TimelinePayload,
  TunnelMeshReport,
  WorldScene,
  WorldStats,
} from '@/types/scene'

export const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000'

const API_PREFIX = '/api/v1'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${API_PREFIX}${path}`, {
    headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })
  if (!res.ok) {
    let code = 'HTTP_ERROR'
    let message = `${res.status} ${res.statusText}`
    try {
      const body = (await res.json()) as { detail?: unknown }
      const d = body.detail
      if (d && typeof d === 'object' && 'code' in d && 'message' in d) {
        code = String((d as { code: unknown }).code)
        message = String((d as { message: unknown }).message)
      } else if (typeof d === 'string') {
        message = d
      } else if (Array.isArray(d)) {
        code = 'VALIDATION_ERROR'
        message = 'Request failed validation'
      }
    } catch {
      // body was not JSON
    }
    throw new ApiError(res.status, code, message)
  }
  return (await res.json()) as T
}

export const api = {
  health: () => request<HealthResponse>('/health'),
  listScenarios: () => request<ScenarioSummary[]>('/scenarios'),
  getScenario: (id: string) => request<Scenario>(`/scenarios/${id}`),
  createScenario: (payload: Partial<ScenarioCreate>) =>
    request<Scenario>('/scenarios', { method: 'POST', body: JSON.stringify(payload) }),
  replaceScenario: (id: string, payload: ScenarioCreate) =>
    request<Scenario>(`/scenarios/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),

  generateWorld: (id: string) =>
    request<WorldStats>(`/scenarios/${id}/world/generate`, { method: 'POST' }),
  getWorld: (id: string) => request<WorldStats>(`/scenarios/${id}/world`),
  getScene: (id: string) => request<WorldScene>(`/scenarios/${id}/scene`),
  getSlice: (id: string, field: SliceField, axis: SliceAxis, index: number) =>
    request<SlicePayload>(
      `/scenarios/${id}/world/slice?field=${field}&axis=${axis}&index=${String(index)}`,
    ),

  generateTargets: (id: string) =>
    request<AccessTargetsPayload>(`/scenarios/${id}/design/targets`, { method: 'POST' }),
  getTargets: (id: string) => request<AccessTargetsPayload>(`/scenarios/${id}/design/targets`),
  /** Submits an asynchronous decline job (202). Poll `getJob` or use `jobSocketUrl`. */
  submitDecline: (id: string, maxLevels?: number) =>
    request<JobSubmission>(
      `/scenarios/${id}/design/decline${maxLevels ? `?maxLevels=${String(maxLevels)}` : ''}`,
      { method: 'POST' },
    ),
  getJob: (jobId: string) => request<JobRecord>(`/jobs/${jobId}`),
  jobSocketUrl: (jobId: string) => `${API_BASE_URL.replace(/^http/, 'ws')}/ws/jobs/${jobId}`,
  getDecline: (id: string) => request<DeclinePayload>(`/scenarios/${id}/design/decline`),
  /** Submits an asynchronous smoothing job (202, kind SMOOTH). */
  submitSmooth: (id: string) =>
    request<JobSubmission>(`/scenarios/${id}/design/decline/smooth`, { method: 'POST' }),
  getSmoothedDecline: (id: string) =>
    request<SmoothedDeclinePayload>(`/scenarios/${id}/design/decline/smooth`),
  /** Submits an asynchronous tunnel-mesh job (202, kind MESH). */
  submitTunnel: (id: string) =>
    request<JobSubmission>(`/scenarios/${id}/design/tunnel`, { method: 'POST' }),
  getTunnel: (id: string) => request<TunnelMeshReport>(`/scenarios/${id}/design/tunnel`),
  /** Synchronous Phase 08 level developments (rules 71–74). */
  generateLevels: (id: string) =>
    request<LevelsPayload>(`/scenarios/${id}/design/levels`, { method: 'POST' }),
  getLevels: (id: string) => request<LevelsPayload>(`/scenarios/${id}/design/levels`),
  /** Synchronous Phase 09 planned stopes (rules 75–80). */
  generateStopes: (id: string) =>
    request<StopesPayload>(`/scenarios/${id}/design/stopes`, { method: 'POST' }),
  getStopes: (id: string) => request<StopesPayload>(`/scenarios/${id}/design/stopes`),
  /** Synchronous Phase 12 sensor baseline (rules 93–98). */
  generateSensors: (id: string) =>
    request<SensorPayload>(`/scenarios/${id}/infrastructure/sensors`, { method: 'POST' }),
  getSensors: (id: string) => request<SensorPayload>(`/scenarios/${id}/infrastructure/sensors`),
  /** Synchronous Phase 11 communication baseline (rules 87–92). */
  generateCommunication: (id: string) =>
    request<CommunicationPayload>(`/scenarios/${id}/infrastructure/communication`, {
      method: 'POST',
    }),
  getCommunication: (id: string) =>
    request<CommunicationPayload>(`/scenarios/${id}/infrastructure/communication`),
  /** Synchronous Phase 10 timeline baseline (rules 81–86). */
  generateTimeline: (id: string) =>
    request<TimelinePayload>(`/scenarios/${id}/design/timeline`, { method: 'POST' }),
  getTimeline: (id: string) => request<TimelinePayload>(`/scenarios/${id}/design/timeline`),
  /** Synchronous Phase 07 network generation (reserved /network namespace). */
  generateNetwork: (id: string) =>
    request<NetworkPayload>(`/scenarios/${id}/network/generate`, { method: 'POST' }),
  getNetwork: (id: string) => request<NetworkPayload>(`/scenarios/${id}/network`),
  evaluateCost: (id: string, points: [number, number, number][]) =>
    request<{ count: number; results: CostEvaluationRow[] }>(
      `/scenarios/${id}/design/cost/evaluate`,
      { method: 'POST', body: JSON.stringify({ points }) },
    ),
}
