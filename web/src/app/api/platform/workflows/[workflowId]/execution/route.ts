import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import { platformRouteError } from '@/features/platform-api/route-handler';
import type { ArExecutionRead } from '@/features/platform-api/generated';

export async function GET(_request: Request, { params }: { params: Promise<{ workflowId: string }> }): Promise<Response> {
  try {
    const { workflowId } = await params;
    if (!/^[0-9a-f-]{36}$/i.test(workflowId)) throw new PlatformApiError(400, '工作流标识格式无效。');
    return NextResponse.json(await platformServerRequest<ArExecutionRead>(`/api/workflows/${workflowId}/execution`));
  } catch (error) {
    return platformRouteError(error, '执行记录加载失败。');
  }
}
