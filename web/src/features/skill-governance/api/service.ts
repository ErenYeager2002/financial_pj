import { platformClientRequest } from '@/features/platform-api/client';
import type { SkillGovernanceObservability, SkillGovernanceWorkflow } from './types';

export async function fetchWorkflowDefinitions(): Promise<SkillGovernanceWorkflow[]> {
  return platformClientRequest<SkillGovernanceWorkflow[]>(
    '/api/platform/admin/workflow-definitions',
    '工作流定义加载失败。'
  );
}

export async function fetchObservabilitySummary(
  hours: number
): Promise<SkillGovernanceObservability> {
  const checkedHours = Math.min(Math.max(Math.trunc(hours), 1), 24 * 90);
  return platformClientRequest<SkillGovernanceObservability>(
    `/api/platform/admin/observability/summary?hours=${checkedHours}`,
    '运行观测数据加载失败。'
  );
}
