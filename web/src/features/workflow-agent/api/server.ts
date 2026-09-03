import 'server-only';

import { listSkillCatalog } from '@/features/skills/api/server';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type {
  SkillDetail,
  WorkflowBatchRead,
  WorkflowMaterialSet,
  WorkflowRead,
  WorkflowReusableFilesRead
} from '@/features/platform-api/types';

export interface WorkflowCreateInput {
  skill_id: string;
  model_connection_id: string;
  model?: string;
  execution_mode?: 'workflow' | 'pi_harness';
}

export interface WorkflowStartInput {
  skill_id: string;
  reconciliation_date: string;
  files?: Record<string, string[]>;
  replace_roles?: string[];
  execution_mode?: 'workflow' | 'pi_harness';
}

export interface WorkflowBatchStartInput {
  skill_id: string;
  reconciliation_dates: string[];
  files?: Record<string, string[]>;
  replace_roles?: string[];
  rerun_successful_dates?: boolean;
  rerun_reason?: string;
  execution_mode?: 'workflow' | 'pi_harness';
}

export function listWorkflowSessions(): Promise<WorkflowRead[]> {
  return platformServerRequest<WorkflowRead[]>('/api/workflows?limit=50');
}

export function listWorkflowBatches(): Promise<WorkflowBatchRead[]> {
  return platformServerRequest<WorkflowBatchRead[]>('/api/workflow-batches?limit=50');
}

export function listWorkflowReusableFiles(skillId: string): Promise<WorkflowReusableFilesRead> {
  return platformServerRequest<WorkflowReusableFilesRead>(
    `/api/workflows/reusable-files?skill_id=${encodeURIComponent(skillId)}`
  );
}

export function listWorkflowMaterialSets(skillId: string): Promise<WorkflowMaterialSet[]> {
  return platformServerRequest<WorkflowMaterialSet[]>(
    `/api/workflows/material-sets?skill_id=${encodeURIComponent(skillId)}`
  );
}

export function restoreWorkflowMaterialSet(
  skillId: string,
  materialSetId: string
): Promise<WorkflowMaterialSet> {
  return platformServerRequest<WorkflowMaterialSet>(
    `/api/workflows/material-sets/${encodeURIComponent(materialSetId)}/restore?skill_id=${encodeURIComponent(skillId)}`,
    { method: 'POST' }
  );
}

export async function listWorkflowSkills(): Promise<SkillDetail[]> {
  const skills = await listSkillCatalog();
  return skills.filter((skill) => skill.execution_mode === 'guided_workflow');
}

export function createWorkflow(input: WorkflowCreateInput): Promise<WorkflowRead> {
  return platformServerRequest<WorkflowRead>('/api/workflows', {
    method: 'POST',
    body: JSON.stringify(input)
  });
}

export function startWorkflow(input: WorkflowStartInput): Promise<WorkflowRead> {
  return platformServerRequest<WorkflowRead>('/api/workflows/start', {
    method: 'POST',
    body: JSON.stringify(input)
  });
}

export function startWorkflowBatch(input: WorkflowBatchStartInput): Promise<WorkflowBatchRead> {
  return platformServerRequest<WorkflowBatchRead>('/api/workflow-batches/start', {
    method: 'POST',
    body: JSON.stringify(input)
  });
}
