import { platformClientRequest } from '@/features/platform-api/client';
import type { WorkflowFetchedSnapshot, WorkflowMaterialSet } from '@/features/platform-api/types';

export function fetchWorkflowFetchedSnapshots(skillId: string): Promise<WorkflowFetchedSnapshot[]> {
  return platformClientRequest<WorkflowFetchedSnapshot[]>(
    `/api/platform/workflows/fetched-snapshots?skill_id=${encodeURIComponent(skillId)}`,
    '取数快照加载失败。'
  );
}

export function fetchWorkflowMaterialSets(skillId: string): Promise<WorkflowMaterialSet[]> {
  return platformClientRequest<WorkflowMaterialSet[]>(
    `/api/platform/workflows/material-sets?skill_id=${encodeURIComponent(skillId)}`,
    '业务材料版本加载失败。'
  );
}

export function restoreWorkflowMaterialSetVersion(
  skillId: string,
  materialSetId: string
): Promise<WorkflowMaterialSet> {
  return platformClientRequest<WorkflowMaterialSet>(
    `/api/platform/workflows/material-sets/${encodeURIComponent(materialSetId)}/restore?skill_id=${encodeURIComponent(skillId)}`,
    '业务材料历史版本恢复失败。',
    { method: 'POST' }
  );
}
