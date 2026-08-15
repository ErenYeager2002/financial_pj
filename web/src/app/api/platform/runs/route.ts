import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';
import { createSafeRun } from '@/features/run-setup/api/server';
import { listRuns } from '@/features/runs/api/server';

export async function GET(request: Request) {
  try {
    const params = new URL(request.url).searchParams;
    const page = Number(params.get('page') ?? '1');
    const pageSize = Number(params.get('page_size') ?? '20');
    const state = params.get('state') ?? '';
    if (!Number.isSafeInteger(page) || page < 1) {
      throw new PlatformApiError(400, '页码必须是正整数。');
    }
    if (!Number.isSafeInteger(pageSize) || pageSize < 1 || pageSize > 100) {
      throw new PlatformApiError(400, '每页数量必须是 1 到 100 之间的整数。');
    }
    return NextResponse.json(await listRuns(page, pageSize, state));
  } catch (error) {
    return platformRouteError(error, '任务列表加载失败。');
  }
}

export async function POST(request: Request) {
  try {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      throw new PlatformApiError(400, '任务请求不是有效的 JSON。');
    }
    return NextResponse.json(await createSafeRun(body), { status: 201 });
  } catch (error) {
    return platformRouteError(error, '任务创建失败。');
  }
}
