import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type { WorkflowBatchRead } from '@/features/platform-api/types';

interface Params {
  params: Promise<{ batchId: string }>;
}
const BATCH_ID = /^BAT-\d{8}-[0-9A-F]{8}$/;

export async function POST(request: Request, { params }: Params): Promise<Response> {
  try {
    const { batchId } = await params;
    if (!BATCH_ID.test(batchId)) throw new PlatformApiError(400, '批次标识格式无效。');
    const body = await request.json().catch(() => ({}));
    return NextResponse.json(
      await platformServerRequest<WorkflowBatchRead>(
        `/api/workflow-batches/${batchId}/fetched-data/supplement`,
        { method: 'POST', body: JSON.stringify(body) }
      )
    );
  } catch (error) {
    return platformRouteError(error, '批次按编号补取失败。');
  }
}
