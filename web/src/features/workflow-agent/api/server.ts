import 'server-only';

import { listSkillCatalog } from '@/features/skills/api/server';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type { SkillDetail, WorkflowBatchRead, WorkflowRead } from '@/features/platform-api/types';

export interface WorkflowCreateInput {
  skill_id: string;
  model_connection_id: string;
  model?: string;
}

export interface WorkflowStartInput {
  skill_id: string;
  reconciliation_date: string;
  files?: Record<string, string[]>;
}

export interface WorkflowBatchStartInput {
  skill_id: string;
  reconciliation_dates: string[];
  files?: Record<string, string[]>;
}

export function listWorkflowSessions(): Promise<WorkflowRead[]> {
  return platformServerRequest<WorkflowRead[]>('/api/workflows?limit=50');
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
