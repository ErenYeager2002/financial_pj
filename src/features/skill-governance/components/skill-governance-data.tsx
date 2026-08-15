'use client';

import { useSuspenseQuery } from '@tanstack/react-query';
import { ObservabilitySummary } from '@/features/admin/components/observability-summary';
import { WorkflowTopology } from '@/features/skills/components/workflow-topology';
import { observabilityQueryOptions, workflowDefinitionsQueryOptions } from '../api/queries';

interface SkillGovernanceDataProps {
  hours: number;
}

export function SkillGovernanceData({ hours }: SkillGovernanceDataProps): React.JSX.Element {
  const { data: definitions } = useSuspenseQuery(workflowDefinitionsQueryOptions());
  const { data: summary } = useSuspenseQuery({
    ...observabilityQueryOptions(hours),
    refetchInterval: 60_000,
    refetchIntervalInBackground: false
  });

  return (
    <>
      <WorkflowTopology definitions={definitions} />
      <ObservabilitySummary summary={summary} />
    </>
  );
}
