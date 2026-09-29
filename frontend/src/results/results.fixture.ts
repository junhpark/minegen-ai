import type {
  OperationsFrame,
  ResultGeometryPayload,
  ResultSummary,
  VentilationFrame,
} from '@/types/results'

export const SNAPSHOT = {
  scenarioRevision: 'abcdef0123456789',
  arraysRevision: '0123456789abcdef',
  activeRampSource: 'LEGACY' as const,
  artifactRevisions: { 'network.json': 'n1' },
}

export const VENT_SUMMARY: ResultSummary = {
  resultId: 'a6ef4d1e72966320',
  domain: 'VENTILATION',
  sourceApplication: 'VENTSIM',
  runLabel: 'Base case',
  description: '',
  compatibility: 'COMPATIBLE',
  sourceSnapshot: SNAPSHOT,
  timeAxis: { kind: 'STATIC', unit: null, sampleCount: 1, start: null, end: null },
  metrics: [
    { name: 'airflowM3s', unit: 'm3/s', available: true, sampleCount: 2, min: -8.5, max: 25 },
    { name: 'pressurePa', unit: 'Pa', available: false, sampleCount: 0, min: null, max: null },
  ],
  counts: { edgeCount: 2, timeCount: 1, sampleCount: 2, vehicleCount: 0, edgeMetricSampleCount: 0 },
  mineResultVersion: '1.0.0',
}

/** a valid result that carries PRESSURE only — airflow is NOT selectable */
export const VENT_PRESSURE_ONLY: ResultSummary = {
  ...VENT_SUMMARY,
  resultId: 'd9116f41a5c99653',
  runLabel: 'Pressure survey',
  metrics: [
    { name: 'airflowM3s', unit: 'm3/s', available: false, sampleCount: 0, min: null, max: null },
    { name: 'pressurePa', unit: 'Pa', available: true, sampleCount: 2, min: 900, max: 1200 },
  ],
}

export const VENT_STALE: ResultSummary = {
  ...VENT_SUMMARY,
  resultId: 'b7ff5e2f83a77431',
  runLabel: '',
  compatibility: 'STALE',
}

export const OPS_SUMMARY: ResultSummary = {
  resultId: 'c8005f3094b88542',
  domain: 'OPERATIONS',
  sourceApplication: 'ANYLOGIC',
  runLabel: 'Fleet 4',
  description: 'four trucks',
  compatibility: 'COMPATIBLE',
  sourceSnapshot: SNAPSHOT,
  timeAxis: { kind: 'MINE_DAY', unit: 'day', sampleCount: 40, start: 0, end: 30 },
  metrics: [
    { name: 'utilization', unit: 'fraction', available: true, sampleCount: 9, min: 0.1, max: 0.9 },
  ],
  counts: {
    edgeCount: 3,
    timeCount: 40,
    sampleCount: 160,
    vehicleCount: 4,
    edgeMetricSampleCount: 9,
  },
  mineResultVersion: '1.0.0',
}

export const GEOMETRY: ResultGeometryPayload = {
  resultId: VENT_SUMMARY.resultId,
  coordinateFrame: 'LOCAL_ENU_Z_UP',
  edges: [
    {
      edgeId: 'RAMP:L01',
      edgeType: 'RAMP',
      sourceNodeId: 'PORTAL',
      targetNodeId: 'LEVEL_ENTRY:L01',
      points: [
        [0, 0, 100],
        [30, 0, 100],
        [30, 40, 100],
      ],
    },
    {
      edgeId: 'DRIFT:L01:00',
      edgeType: 'DRIFT',
      sourceNodeId: 'LEVEL_ENTRY:L01',
      targetNodeId: 'JUNCTION:L01:A',
      points: [
        [30, 40, 100],
        [30, 40, 90],
      ],
    },
  ],
}

export const VENT_FRAME: VentilationFrame = {
  resultId: VENT_SUMMARY.resultId,
  metric: 'airflowM3s',
  unit: 'm3/s',
  timeAxisKind: 'STATIC',
  time: null,
  sampleTime: null,
  values: [{ edgeId: 'RAMP:L01', value: -8.5 }],
  missingEdgeIds: ['DRIFT:L01:00'],
  min: -8.5,
  max: -8.5,
  signConvention:
    'positive airflow flows from the MineNetwork edge sourceNodeId toward its targetNodeId',
}

export const OPS_FRAME: OperationsFrame = {
  resultId: OPS_SUMMARY.resultId,
  timeAxisKind: 'MINE_DAY',
  time: 12.5,
  vehicles: [
    {
      agentId: 'T1',
      agentKind: 'TRUCK',
      x: 15,
      y: 0,
      z: 100,
      edgeId: 'RAMP:L01',
      chainageFraction: 0.5,
      status: 'LOADED',
      loadTonnes: 30,
      placement: 'INTERPOLATED',
    },
  ],
  edgeMetrics: [
    {
      edgeId: 'RAMP:L01',
      sampleTime: 12,
      utilization: 0.4,
      queueCount: 1,
      haulageTonnesPerHour: null,
      travelTimeSeconds: null,
    },
  ],
}
