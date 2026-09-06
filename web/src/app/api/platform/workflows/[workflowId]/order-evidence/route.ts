import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import { platformRouteError } from '@/features/platform-api/route-handler';
import type { OrderEvidencePage } from '@/features/workflow-agent/order-evidence';

interface Params {
  params: Promise<{ workflowId: string }>;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function GET(request: Request, { params }: Params): Promise<Response> {
  try {
    const { workflowId } = await params;
    if (!UUID.test(workflowId)) throw new PlatformApiError(400, '工作流标识格式无效。');
    const query = new URL(request.url).searchParams;
    const search = new URLSearchParams();
    for (const key of ['offset', 'limit', 'query', 'record_id', 'detail_offset', 'fingerprint']) {
      const value = query.get(key);
      if (value) search.set(key, value);
    }
    const result = await platformServerRequest<OrderEvidencePage>(
      `/api/workflows/${workflowId}/order-evidence?${search.toString()}`
    );
    return NextResponse.json(result);
  } catch (error) {
    return platformRouteError(error, '逐单判断依据加载失败。');
  }
}
