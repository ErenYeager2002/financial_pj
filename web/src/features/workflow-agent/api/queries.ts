import { queryOptions } from '@tanstack/react-query';
import { fetchWorkflowMaterialSets } from './service';

export const workflowMaterialKeys = {
  all: ['workflow-material-sets'] as const,
  skill: (skillId: string) => [...workflowMaterialKeys.all, skillId] as const
};

export function workflowMaterialSetsQueryOptions(skillId: string) {
  return queryOptions({
    queryKey: workflowMaterialKeys.skill(skillId),
    queryFn: () => fetchWorkflowMaterialSets(skillId),
    staleTime: 10_000
  });
}
