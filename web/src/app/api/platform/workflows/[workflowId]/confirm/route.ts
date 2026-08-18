import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import { platformRouteError } from '@/features/platform-api/route-handler';
import type { WorkflowRead } from '@/features/platform-api/types';

interface Params {
  params: Promise<{ workflowId: string }>;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function POST(_request: Request, { params }: Params): Promise<Response> {
  try {
    const { workflowId } = await params;
    if (!UUID.test(workflowId)) throw new PlatformApiError(400, '工作流标识格式无效。');
    const workflow = await platformServerRequest<WorkflowRead>(
      `/api/workflows/${workflowId}/confirm`,
      { method: 'POST' }
    );
    return NextResponse.json(workflow);
  } catch (error) {
    return platformRouteError(error, '确认写入失败。');
  }
}
