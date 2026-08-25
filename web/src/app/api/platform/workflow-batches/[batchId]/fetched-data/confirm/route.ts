import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type { WorkflowBatchRead } from '@/features/platform-api/types';

interface Params {
  params: Promise<{ batchId: string }>;
}
const BATCH_ID = /^BAT-\d{8}-[0-9A-F]{8}$/;

export async function POST(_request: Request, { params }: Params): Promise<Response> {
  try {
    const { batchId } = await params;
    if (!BATCH_ID.test(batchId)) throw new PlatformApiError(400, '批次标识格式无效。');
    return NextResponse.json(
      await platformServerRequest<WorkflowBatchRead>(
        `/api/workflow-batches/${batchId}/fetched-data/confirm`,
        { method: 'POST' }
      )
    );
  } catch (error) {
    return platformRouteError(error, '确认批次取数数据失败。');
  }
}
