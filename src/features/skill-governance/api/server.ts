import 'server-only';

import { platformServerRequest } from '@/features/platform-api/server-client';
import type { SkillGovernanceObservability, SkillGovernanceWorkflow } from './types';

export function listWorkflowDefinitions(): Promise<SkillGovernanceWorkflow[]> {
  return platformServerRequest<SkillGovernanceWorkflow[]>('/api/admin/workflow-definitions');
}

export function getObservabilitySummary(hours = 24): Promise<SkillGovernanceObservability> {
  const checkedHours = Math.min(Math.max(Math.trunc(hours), 1), 24 * 90);
  return platformServerRequest<SkillGovernanceObservability>(
    `/api/admin/observability/summary?hours=${checkedHours}`
  );
}
