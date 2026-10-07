import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { DesignJobKind } from '@/stores/scenarioStore'

/**
 * Poll one asynchronous design job (Phase 17.1 §1). The query key carries
 * the scenario epoch and the job id comes from the scenario store, so a
 * scenario change both stops the poll (the store cleared the id) and makes
 * it impossible for a cached scenario-A job record to be served to
 * scenario B under the same key.
 *
 * The record is read by the interval alone: a terminal job record never
 * changes, so it is never refetched on window focus, reconnect or remount
 * (`staleTime: Infinity`). A refetch would hand the consumer a NEW result
 * object for the same job and make it re-apply an identical artifact to the
 * scene — a spurious scene revision (PR #53 review round 3 B2: a download's
 * focus change must not move the mine).
 */
export function useJobPoll(
  kind: DesignJobKind,
  jobId: string | null,
  epoch: number,
  intervalMs: number,
) {
  return useQuery({
    queryKey: ['job', kind, epoch, jobId],
    queryFn: () => api.getJob(jobId as string),
    enabled: jobId !== null,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchInterval: (q) => {
      const s = q.state.data?.status
      return s === 'SUCCEEDED' || s === 'FAILED' ? false : intervalMs
    },
  })
}
