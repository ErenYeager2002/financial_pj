import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import { platformRouteError } from '@/features/platform-api/route-handler';
import type { WorkflowRead } from '@/features/platform-api/types';

interface Params {
  params: Promise<{ workflowId: string }>;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function requestInput(value: unknown): { content: string } {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new PlatformApiError(400, '工作流确认请求格式无效。');
  }
  const content = (value as { content?: unknown }).content;
  if (typeof content !== 'string' || !content.trim() || content.length > 4000) {
    throw new PlatformApiError(400, '确认内容必须为 1 到 4000 个字符。');
  }
  return { content: content.trim() };
}

export async function POST(request: Request, { params }: Params): Promise<Response> {
  try {
    const { workflowId } = await params;
    if (!UUID.test(workflowId)) throw new PlatformApiError(400, '工作流标识格式无效。');
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      throw new PlatformApiError(400, '工作流确认请求不是有效的 JSON。');
    }
    const workflow = await platformServerRequest<WorkflowRead>(
      `/api/workflows/${workflowId}/messages`,
      { method: 'POST', body: JSON.stringify(requestInput(body)) }
    );
    return NextResponse.json(workflow);
  } catch (error) {
    return platformRouteError(error, '工作流确认失败。');
  }
}
