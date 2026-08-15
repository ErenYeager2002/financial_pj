import { queryOptions } from '@tanstack/react-query';
import { fetchRun, fetchRunApprovals, fetchRunSteps } from './service';
import type { PlatformRunApproval, PlatformRunDetail, PlatformRunStep } from './types';

type RunQueryFn = () => Promise<PlatformRunDetail>;
type RunStepsQueryFn = () => Promise<PlatformRunStep[]>;
type RunApprovalsQueryFn = () => Promise<PlatformRunApproval[]>;

export const runKeys = {
  all: ['platform-runs'] as const,
  detail: (runId: string) => [...runKeys.all, 'detail', runId] as const,
  steps: (runId: string) => [...runKeys.all, 'steps', runId] as const,
  approvals: (runId: string) => [...runKeys.all, 'approvals', runId] as const
};

export function runQueryOptions(runId: string, queryFn: RunQueryFn = () => fetchRun(runId)) {
  return queryOptions({
    queryKey: runKeys.detail(runId),
    queryFn,
    staleTime: 10_000
  });
}

export function runStepsQueryOptions(
  runId: string,
  queryFn: RunStepsQueryFn = () => fetchRunSteps(runId)
) {
  return queryOptions({
    queryKey: runKeys.steps(runId),
    queryFn,
    staleTime: 5_000
  });
}

export function runApprovalsQueryOptions(
  runId: string,
  queryFn: RunApprovalsQueryFn = () => fetchRunApprovals(runId)
) {
  return queryOptions({
    queryKey: runKeys.approvals(runId),
    queryFn,
    staleTime: 10_000
  });
}
