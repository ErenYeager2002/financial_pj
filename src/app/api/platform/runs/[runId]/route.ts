import { NextResponse } from 'next/server';
import { platformRouteError } from '@/features/platform-api/route-handler';
import { getRun } from '@/features/runs/api/server';

type Params = { params: Promise<{ runId: string }> };

export async function GET(_request: Request, { params }: Params) {
  try {
    const { runId } = await params;
    return NextResponse.json(await getRun(runId));
  } catch (error) {
    return platformRouteError(error, '任务详情加载失败。');
  }
}
