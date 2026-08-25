import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import { platformRouteError } from '@/features/platform-api/route-handler';
import type { WorkflowRead } from '@/features/platform-api/types';
import {
  parseWorkflowFileBindings,
  parseWorkflowReplaceRoles
} from '@/features/workflow-agent/api/file-selection-request';

interface Params {
  params: Promise<{ workflowId: string }>;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function requestInput(value: unknown): {
  files: Record<string, string[]>;
  replace_roles: string[];
} {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new PlatformApiError(400, '工作流文件请求格式无效。');
  }
  const body = value as Record<string, unknown>;
  const files = parseWorkflowFileBindings(body.files, { required: true });
  const replace_roles = parseWorkflowReplaceRoles(body.replace_roles);
  return { files, replace_roles };
}

export async function PUT(request: Request, { params }: Params): Promise<Response> {
  try {
    const { workflowId } = await params;
    if (!UUID.test(workflowId)) throw new PlatformApiError(400, '工作流标识格式无效。');
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      throw new PlatformApiError(400, '工作流文件请求不是有效的 JSON。');
    }
    const workflow = await platformServerRequest<WorkflowRead>(
      `/api/workflows/${workflowId}/files`,
      { method: 'PUT', body: JSON.stringify(requestInput(body)) }
    );
    return NextResponse.json(workflow);
  } catch (error) {
    return platformRouteError(error, '工作流文件绑定失败。');
  }
}
