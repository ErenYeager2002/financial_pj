import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import { platformRouteError } from '@/features/platform-api/route-handler';
import type { WorkflowRead } from '@/features/platform-api/types';

interface Params {
  params: Promise<{ workflowId: string }>;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const ID = /^[A-Za-z0-9._-]+$/;

function requestInput(value: unknown): { files: Record<string, string[]> } {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new PlatformApiError(400, '工作流文件请求格式无效。');
  }
  const filesValue = (value as { files?: unknown }).files;
  if (!filesValue || typeof filesValue !== 'object' || Array.isArray(filesValue)) {
    throw new PlatformApiError(400, '工作流文件绑定格式无效。');
  }
  const files: Record<string, string[]> = {};
  for (const [role, idsValue] of Object.entries(filesValue)) {
    if (!ID.test(role) || !Array.isArray(idsValue) || idsValue.length > 100) {
      throw new PlatformApiError(400, '工作流文件绑定格式无效。');
    }
    files[role] = idsValue.map((fileId) => {
      if (typeof fileId !== 'string' || !UUID.test(fileId)) {
        throw new PlatformApiError(400, '文件标识格式无效。');
      }
      return fileId;
    });
  }
  return { files };
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
