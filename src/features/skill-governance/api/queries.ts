import { queryOptions } from '@tanstack/react-query';
import { fetchObservabilitySummary, fetchWorkflowDefinitions } from './service';
import type { SkillGovernanceObservability, SkillGovernanceWorkflow } from './types';

type WorkflowDefinitionsQueryFn = () => Promise<SkillGovernanceWorkflow[]>;
type ObservabilityQueryFn = () => Promise<SkillGovernanceObservability>;

export const skillGovernanceKeys = {
  all: ['skill-governance'] as const,
  workflows: () => [...skillGovernanceKeys.all, 'workflows'] as const,
  observability: (hours: number) => [...skillGovernanceKeys.all, 'observability', hours] as const
};

export function workflowDefinitionsQueryOptions(
  queryFn: WorkflowDefinitionsQueryFn = fetchWorkflowDefinitions
) {
  return queryOptions({
    queryKey: skillGovernanceKeys.workflows(),
    queryFn,
    staleTime: 60_000
  });
}

export function observabilityQueryOptions(
  hours: number,
  queryFn: ObservabilityQueryFn = () => fetchObservabilitySummary(hours)
) {
  return queryOptions({
    queryKey: skillGovernanceKeys.observability(hours),
    queryFn,
    staleTime: 30_000
  });
}
