import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import { platformRouteError } from '@/features/platform-api/route-handler';
import type { WorkflowRead } from '@/features/platform-api/types';
import {
  parseWorkflowFileBindings,
  parseWorkflowReplaceRoles
} from '@/features/workflow-agent/api/file-selection-request';

const ID = /^[A-Za-z0-9._-]+$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

function parseBody(value: unknown): {
  skill_id: string;
  reconciliation_date: string;
  files: Record<string, string[]>;
  replace_roles: string[];
} {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new PlatformApiError(400, '任务请求格式无效。');
  }
  const body = value as Record<string, unknown>;
  const skillId = typeof body.skill_id === 'string' ? body.skill_id.trim() : '';
  const reconciliationDate =
    typeof body.reconciliation_date === 'string' ? body.reconciliation_date.trim() : '';
  if (!ID.test(skillId) || !DATE.test(reconciliationDate)) {
    throw new PlatformApiError(400, 'Skill 标识或核销日期格式无效。');
  }
  return {
    skill_id: skillId,
    reconciliation_date: reconciliationDate,
    files: parseWorkflowFileBindings(body.files),
    replace_roles: parseWorkflowReplaceRoles(body.replace_roles)
  };
}

export async function POST(request: Request): Promise<Response> {
  try {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      throw new PlatformApiError(400, '任务请求不是有效的 JSON。');
    }
    const input = parseBody(body);
    const workflow = await platformServerRequest<WorkflowRead>('/api/workflows/start', {
      method: 'POST',
      body: JSON.stringify(input)
    });
    return NextResponse.json(workflow, { status: 201 });
  } catch (error) {
    return platformRouteError(error, '任务启动失败。');
  }
}
