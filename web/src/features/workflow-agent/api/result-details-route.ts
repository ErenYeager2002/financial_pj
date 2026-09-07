import 'server-only';

import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import { platformRouteError } from '@/features/platform-api/route-handler';
import type { ArResultPage } from '@/features/platform-api/generated';

export async function resultDetailsResponse(request: Request, kind: 'workflows' | 'workflow-batches', id: string): Promise<Response> {
  try {
    const validId = kind === 'workflow-batches'
      ? /^BAT-\d{8}-[0-9A-F]{8}$/i.test(id)
      : /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(id);
    if (!validId) {
      throw new PlatformApiError(400, '任务标识格式无效。');
    }
    const input = new URL(request.url).searchParams;
    const query = new URLSearchParams();
    for (const key of ['category', 'offset', 'limit']) {
      const value = input.get(key);
      if (value !== null) query.set(key, value);
    }
    const result = await platformServerRequest<ArResultPage>(`/api/${kind}/${id}/result-details?${query}`);
    return NextResponse.json(result, { headers: { 'Cache-Control': 'private, no-store' } });
  } catch (error) {
    return platformRouteError(error, '核销明细加载失败。');
  }
}
