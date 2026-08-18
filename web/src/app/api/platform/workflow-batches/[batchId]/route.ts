import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import { platformRouteError } from '@/features/platform-api/route-handler';
import type { WorkflowBatchRead } from '@/features/platform-api/types';

interface Params {
  params: Promise<{ batchId: string }>;
}

const ID = /^[A-Za-z0-9._-]+$/;

export async function GET(_request: Request, { params }: Params): Promise<Response> {
  try {
    const { batchId } = await params;
    if (!ID.test(batchId)) throw new PlatformApiError(400, '批次标识格式无效。');
    const batch = await platformServerRequest<WorkflowBatchRead>(
      `/api/workflow-batches/${batchId}`
    );
    return NextResponse.json(batch);
  } catch (error) {
    return platformRouteError(error, '批次状态加载失败。');
  }
}
