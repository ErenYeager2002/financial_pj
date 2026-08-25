import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import { platformRouteError } from '@/features/platform-api/route-handler';
import type { WorkflowFetchedData } from '@/features/platform-api/types';

interface Params {
  params: Promise<{ batchId: string }>;
}
const BATCH_ID = /^BAT-\d{8}-[0-9A-F]{8}$/;

export async function GET(request: Request, { params }: Params): Promise<Response> {
  try {
    const { batchId } = await params;
    if (!BATCH_ID.test(batchId)) throw new PlatformApiError(400, '批次标识格式无效。');
    const query = new URL(request.url).searchParams;
    const search = new URLSearchParams();
    for (const key of [
      'reconciliation_date',
      'dataset',
      'offset',
      'limit',
      'query',
      'issues_only'
    ]) {
      const value = query.get(key);
      if (value) search.set(key, value);
    }
    const preview = await platformServerRequest<WorkflowFetchedData>(
      `/api/workflow-batches/${batchId}/fetched-data?${search.toString()}`
    );
    return NextResponse.json(preview);
  } catch (error) {
    return platformRouteError(error, '批次智云取数数据加载失败。');
  }
}
