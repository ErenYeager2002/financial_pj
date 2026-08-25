import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type { WorkflowRead } from '@/features/platform-api/types';

interface Params { params: Promise<{ workflowId: string }> }
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function POST(request: Request, { params }: Params): Promise<Response> {
  try {
    const { workflowId } = await params;
    if (!UUID.test(workflowId)) throw new PlatformApiError(400, '工作流标识格式无效。');
    const body = await request.json().catch(() => ({}));
    return NextResponse.json(await platformServerRequest<WorkflowRead>(
      `/api/workflows/${workflowId}/fetched-data/supplement`,
      { method: 'POST', body: JSON.stringify(body) }
    ));
  } catch (error) {
    return platformRouteError(error, '按编号补取失败。');
  }
}
