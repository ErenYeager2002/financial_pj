import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import { platformRouteError } from '@/features/platform-api/route-handler';
import type { WorkflowRead } from '@/features/platform-api/types';

const ID = /^[A-Za-z0-9._-]+$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

function parseFiles(value: unknown): Record<string, string[]> {
  if (value === undefined) return {};
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new PlatformApiError(400, '文件绑定格式无效。');
  }
  const files: Record<string, string[]> = {};
  for (const [role, ids] of Object.entries(value)) {
    if (!ID.test(role) || !Array.isArray(ids) || ids.length > 100) {
      throw new PlatformApiError(400, '文件绑定格式无效。');
    }
    files[role] = ids.map((fileId) => {
      if (typeof fileId !== 'string' || !UUID.test(fileId)) {
        throw new PlatformApiError(400, '文件标识格式无效。');
      }
      return fileId;
    });
  }
  return files;
}

function parseBody(value: unknown): {
  skill_id: string;
  reconciliation_date: string;
  files: Record<string, string[]>;
} {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new PlatformApiError(400, '后台任务请求格式无效。');
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
    files: parseFiles(body.files)
  };
}

export async function POST(request: Request): Promise<Response> {
  try {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      throw new PlatformApiError(400, '后台任务请求不是有效的 JSON。');
    }
    const input = parseBody(body);
    const workflow = await platformServerRequest<WorkflowRead>('/api/workflows/start', {
      method: 'POST',
      body: JSON.stringify(input)
    });
    return NextResponse.json(workflow, { status: 201 });
  } catch (error) {
    return platformRouteError(error, '后台任务启动失败。');
  }
}
