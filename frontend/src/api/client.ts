// Typed fetch client. Thin: no engineering logic, no coordinate conversion.

import type {
  HealthResponse,
  Scenario,
  ScenarioCreate,
  ScenarioRealizeRequest,
  ScenarioSummary,
  ShaftSpec,
} from '@/types/api'
import type {
  EconomicsConfig,
  EconomicsConfigResponse,
  LayoutComparisonPayload,
  MineAnalysisPayload,
} from '@/types/analysis'
import type { Capability } from '@/types/enums'
import type {
  OperationsFrame,
  ResultDetail,
  ResultGeometryPayload,
  ResultImportPayload,
  ResultListPayload,
  SourceApplication,
  VentilationFrame,
} from '@/types/results'
import type { AdapterTarget } from '@/components/panels/exportContents'
import type {
  AccessTargetsPayload,
  CapabilityGraphPayload,
  CapabilityPathQuery,
  CommunicationPayload,
  CostEvaluationRow,
  DeclinePayload,
  DesignAssessmentPayload,
  DevelopmentMeshReport,
  JobRecord,
  JobSubmission,
  LayoutV2Catalogue,
  LevelAccessesPayload,
  LevelsPayload,
  NetworkPayload,
  ProductionPayload,
  RampSource,
  RampSourceSummary,
  ResetPlan,
  ResetResult,
  SensorPayload,
  ShaftsPayload,
  ShaftMeshReport,
  CollarSuggestion,
  SliceAxis,
  SliceField,
  SlicePayload,
  SmoothedDeclinePayload,
  StopesPayload,
  TimelinePayload,
  TunnelMeshReport,
  WorkflowStage,
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
    /** the backend `ErrorDetail` beyond code / message (a reset refusal's
     * `jobId` or fresh `plan`, a scene's `artifacts[]`), verbatim — data to
     * display, never a decision */
    public readonly detail: Record<string, unknown> | null = null,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

/** Map a failed response to the typed `ApiError` (backend `ErrorDetail`). */
async function apiErrorOf(res: Response): Promise<ApiError> {
  let code = 'HTTP_ERROR'
  let message = `${res.status} ${res.statusText}`
  let detail: Record<string, unknown> | null = null
  try {
    const body = (await res.json()) as { detail?: unknown }
    const d = body.detail
    if (d && typeof d === 'object' && 'code' in d && 'message' in d) {
      code = String((d as { code: unknown }).code)
      message = String((d as { message: unknown }).message)
      detail = d
    } else if (typeof d === 'string') {
      message = d
    } else if (Array.isArray(d)) {
      code = 'VALIDATION_ERROR'
      message = 'Request failed validation'
    }
  } catch {
    // body was not JSON
  }
  return new ApiError(res.status, code, message, detail)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${API_PREFIX}${path}`, {
    headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })
  if (!res.ok) throw await apiErrorOf(res)
  return (await res.json()) as T
}

/** A downloaded file: the raw bytes plus the server-declared filename. */
export interface FileDownload {
  blob: Blob
  filename: string
}

/** `attachment; filename="x.zip"` → `x.zip` (RFC 6266 plain form; the
 * backend never emits the `filename*` encoded form). Falls back when the
 * header is absent or malformed. */
export function parseAttachmentFilename(header: string | null, fallback: string): string {
  if (!header) return fallback
  const m = /filename="([^"\\]+)"/i.exec(header) ?? /filename=([^;\s]+)/i.exec(header)
  const name = m?.[1]?.trim()
  return name && !name.includes('/') && !name.includes('..') ? name : fallback
}

async function requestFile(
  path: string,
  init: RequestInit,
  fallback: string,
): Promise<FileDownload> {
  const res = await fetch(`${API_BASE_URL}${API_PREFIX}${path}`, init)
  if (!res.ok) throw await apiErrorOf(res)
  return {
    blob: await res.blob(),
    filename: parseAttachmentFilename(res.headers.get('content-disposition'), fallback),
  }
}

/** An upload of raw bytes (a MineResult ZIP): the body is sent as-is under
 * the declared media type; a typed refusal travels as `ApiError`. */
async function requestUpload<T>(
  path: string,
  body: Blob,
  mediaType: string,
): Promise<{ status: number; payload: T }> {
  const res = await fetch(`${API_BASE_URL}${API_PREFIX}${path}`, {
    method: 'POST',
    headers: { 'content-type': mediaType },
    body,
  })
  if (!res.ok) throw await apiErrorOf(res)
  return { status: res.status, payload: (await res.json()) as T }
}

/** A request whose success answer carries no body (204). */
async function requestNoContent(path: string, init: RequestInit): Promise<void> {
  const res = await fetch(`${API_BASE_URL}${API_PREFIX}${path}`, init)
  if (!res.ok) throw await apiErrorOf(res)
}

export const api = {
  health: () => request<HealthResponse>('/health'),
  listScenarios: () => request<ScenarioSummary[]>('/scenarios'),
  getScenario: (id: string) => request<Scenario>(`/scenarios/${id}`),
  /** Phase 17: deterministic preset+seed realization — non-persistent
   * preview; submit the returned ScenarioCreate to createScenario. */
  realizeScenario: (payload: ScenarioRealizeRequest) =>
    request<ScenarioCreate>('/scenarios/realize', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
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
  /** Closeout v3 §4: submits the asynchronous development-mesh job (202, kind DEVELOPMENT_MESH). */
  submitDevelopmentMesh: (id: string) =>
    request<JobSubmission>(`/scenarios/${id}/design/development-mesh`, { method: 'POST' }),
  getDevelopmentMesh: (id: string) =>
    request<DevelopmentMeshReport>(`/scenarios/${id}/design/development-mesh`),
  /** Phase 20A: submits the asynchronous layout-v2 search (202, kind LAYOUT_V2). */
  submitLayoutV2: (id: string) =>
    request<JobSubmission>(`/scenarios/${id}/design/layout-v2`, { method: 'POST' }),
  getLayoutV2: (id: string) => request<LayoutV2Catalogue>(`/scenarios/${id}/design/layout-v2`),
  /** Materialize a FEASIBLE candidate as the layout-v2 effective ramp. */
  selectLayoutCandidate: (id: string, candidateId: string) =>
    request<SmoothedDeclinePayload>(`/scenarios/${id}/design/layout-v2/select`, {
      method: 'POST',
      body: JSON.stringify({ candidateId }),
    }),
  /** Select + make LAYOUT_V2 the active ramp source (rule 151 invalidation). */
  activateLayoutCandidate: (id: string, candidateId: string) =>
    request<{ rampSource: RampSourceSummary; selected: SmoothedDeclinePayload }>(
      `/scenarios/${id}/design/layout-v2/activate`,
      { method: 'POST', body: JSON.stringify({ candidateId }) },
    ),
  getLayoutSelected: (id: string) =>
    request<SmoothedDeclinePayload>(`/scenarios/${id}/design/layout-v2/selected`),
  /** Phase 20B: ramp junctions + level accesses of the selected candidate. */
  getLevelAccesses: (id: string) =>
    request<LevelAccessesPayload>(`/scenarios/${id}/design/level-accesses`),
  getRampSource: (id: string) => request<RampSourceSummary>(`/scenarios/${id}/design/ramp-source`),
  /** Phase 20D.3 (rule 189): the READ-ONLY design assessment + candidate comparison. */
  /** Phase 23A: the MineExchange v1 bundle (application/zip). Read-only on
   * the backend — nothing is generated or persisted by this request. */
  exportMineExchange: (id: string) =>
    requestFile(
      `/scenarios/${id}/export/mine-exchange`,
      { method: 'POST' },
      `minegen_${id}_mineexchange_v1.zip`,
    ),
  /** Phase 23B: an external adapter package (VENTSIM | ANYLOGIC | UNITY |
   * UNREAL) built on the backend from the MineExchange bundle; typed 409
   * refusals (ADAPTER_REQUIRED_SOURCE_ABSENT, …) travel as ApiError. */
  exportAdapter: (id: string, target: AdapterTarget) =>
    requestFile(
      `/scenarios/${id}/export/${target.toLowerCase()}`,
      { method: 'POST' },
      `minegen_${id}_${target.toLowerCase()}.zip`,
    ),
  getDesignAssessment: (id: string) =>
    request<DesignAssessmentPayload>(`/scenarios/${id}/design/assessment`),
  // -- Phase 23C: external simulation results (MineResult 1.0) ------------- //
  /** Import a MineResult ZIP (the filled round-trip kit) for VENTSIM or
   * ANYLOGIC; 201 when stored, 200 when the identical result already exists.
   * The backend binds it to the CURRENT mine snapshot and computes nothing. */
  importSimulationResult: (id: string, application: SourceApplication, file: Blob) =>
    requestUpload<ResultImportPayload>(
      `/scenarios/${id}/results/import/${application.toLowerCase()}`,
      file,
      'application/zip',
    ),
  listSimulationResults: (id: string) => request<ResultListPayload>(`/scenarios/${id}/results`),
  getSimulationResult: (id: string, resultId: string) =>
    request<ResultDetail>(`/scenarios/${id}/results/${resultId}`),
  deleteSimulationResult: (id: string, resultId: string) =>
    requestNoContent(`/scenarios/${id}/results/${resultId}`, { method: 'DELETE' }),
  exportSimulationResult: (id: string, resultId: string) =>
    requestFile(
      `/scenarios/${id}/results/${resultId}/export`,
      { method: 'GET' },
      `minegen_${id}_mineresult_${resultId}.zip`,
    ),
  getSimulationResultGeometry: (id: string, resultId: string) =>
    request<ResultGeometryPayload>(`/scenarios/${id}/results/${resultId}/geometry`),
  getVentilationFrame: (id: string, resultId: string, metric: string, time: number | null) =>
    request<VentilationFrame>(
      `/scenarios/${id}/results/${resultId}/ventilation?` +
        new URLSearchParams(time === null ? { metric } : { metric, time: String(time) }).toString(),
    ),
  getOperationsFrame: (id: string, resultId: string, time: number) =>
    request<OperationsFrame>(
      `/scenarios/${id}/results/${resultId}/operations/frame?` +
        new URLSearchParams({ time: String(time) }).toString(),
    ),
  setRampSource: (id: string, activeSource: RampSource) =>
    request<RampSourceSummary>(`/scenarios/${id}/design/ramp-source`, {
      method: 'PUT',
      body: JSON.stringify({ activeSource }),
    }),
  /** The ACTIVE effective ramp in the source-neutral contract. */
  getEffectiveRamp: (id: string) => request<SmoothedDeclinePayload>(`/scenarios/${id}/design/ramp`),
  /** Synchronous Phase 08 level developments (rules 71–74). */
  /** Hardening H1 §4.4: read-only preview of "Reset from here" — the backend's
   * registry closure, never a frontend dependency graph */
  getResetPlan: (id: string, stage: WorkflowStage) =>
    request<ResetPlan>(`/scenarios/${id}/design/reset-plan?from=${stage}`),
  /** Hardening H1 §4.4: delete the stage's artifacts + closure (same function
   * as the plan). `expectedWillDelete` is the previewed list the user
   * confirmed: the backend deletes only if its plan under the lock still
   * lists exactly it (409 RESET_PLAN_CHANGED otherwise; 409 RESET_JOB_RUNNING
   * while a job of the scenario is running). */
  resetStage: (id: string, stage: WorkflowStage, expectedWillDelete?: readonly string[]) =>
    request<ResetResult>(`/scenarios/${id}/design/stages/${stage}`, {
      method: 'DELETE',
      ...(expectedWillDelete ? { body: JSON.stringify({ expectedWillDelete }) } : {}),
    }),
  generateLevels: (id: string) =>
    request<LevelsPayload>(`/scenarios/${id}/design/levels`, { method: 'POST' }),
  getLevels: (id: string) => request<LevelsPayload>(`/scenarios/${id}/design/levels`),
  /** Synchronous Phase 09 planned stopes (rules 75–80) — the Longhole-only
   * route; any other active method answers a typed 409. */
  generateStopes: (id: string) =>
    request<StopesPayload>(`/scenarios/${id}/design/stopes`, { method: 'POST' }),
  getStopes: (id: string) => request<StopesPayload>(`/scenarios/${id}/design/stopes`),
  /** Phase 21B/C: the method-generic production route — the ACTIVE method's
   * typed payload (stopes / cuts + backfills / rooms + benches + pillars). */
  generateProduction: (id: string) =>
    request<ProductionPayload>(`/scenarios/${id}/design/production`, { method: 'POST' }),
  getProduction: (id: string) => request<ProductionPayload>(`/scenarios/${id}/design/production`),
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
  /** Phase 20C.2B shaft planning (rules 182–184): synchronous, optional. */
  generateShafts: (id: string) =>
    request<ShaftsPayload>(`/scenarios/${id}/design/shafts`, { method: 'POST' }),
  getShafts: (id: string) => request<ShaftsPayload>(`/scenarios/${id}/design/shafts`),
  /** hardening PR-2 H2-SH: the planner's default collar for one declared spec (read-only) */
  suggestShaftCollar: (id: string, spec: ShaftSpec) =>
    request<CollarSuggestion>(`/scenarios/${id}/design/shafts/suggest-collar`, {
      method: 'POST',
      body: JSON.stringify(spec),
    }),
  /** hardening PR-2 H2-SH: synchronous shaft excavation sweep (barrel + caps + drives) */
  generateShaftMesh: (id: string) =>
    request<ShaftMeshReport>(`/scenarios/${id}/design/shaft-mesh`, { method: 'POST' }),
  getShaftMesh: (id: string) => request<ShaftMeshReport>(`/scenarios/${id}/design/shaft-mesh`),
  /** Phase 20C.2B capability graph (rule 185): synchronous semantic layer. */
  generateCapabilityGraph: (id: string) =>
    request<CapabilityGraphPayload>(`/scenarios/${id}/design/capability-graph`, {
      method: 'POST',
    }),
  getCapabilityGraph: (id: string) =>
    request<CapabilityGraphPayload>(`/scenarios/${id}/design/capability-graph`),
  capabilityPath: (id: string, source: string, target: string, capability: Capability) =>
    request<CapabilityPathQuery>(
      `/scenarios/${id}/design/capability-graph/path?${new URLSearchParams({ source, target, capability }).toString()}`,
    ),
  /** Synchronous Phase 07 network generation (reserved /network namespace). */
  /** Phase 22A/B: the READ-ONLY mine analysis projection (no job, no
   * persistence) and the user-authored planning-economics assumptions. */
  getAnalysis: (id: string) => request<MineAnalysisPayload>(`/scenarios/${id}/analysis`),
  getEconomicsConfig: (id: string) =>
    request<EconomicsConfigResponse>(`/scenarios/${id}/analysis/economics-config`),
  putEconomicsConfig: (id: string, config: EconomicsConfig) =>
    request<EconomicsConfigResponse>(`/scenarios/${id}/analysis/economics-config`, {
      method: 'PUT',
      body: JSON.stringify(config),
    }),
  /** Phase 22C: READ-ONLY comparable layout development cost per ranked
   * layout-v2 candidate (persisted lengths × configured rates; no job, no
   * persistence, no ranking change). */
  getLayoutComparison: (id: string) =>
    request<LayoutComparisonPayload>(`/scenarios/${id}/analysis/layout-comparison`),
  generateNetwork: (id: string) =>
    request<NetworkPayload>(`/scenarios/${id}/network/generate`, { method: 'POST' }),
  getNetwork: (id: string) => request<NetworkPayload>(`/scenarios/${id}/network`),
  evaluateCost: (id: string, points: [number, number, number][]) =>
    request<{ count: number; results: CostEvaluationRow[] }>(
      `/scenarios/${id}/design/cost/evaluate`,
      { method: 'POST', body: JSON.stringify({ points }) },
    ),
}
