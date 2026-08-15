import { NextResponse } from 'next/server';
import { platformRouteError } from '@/features/platform-api/route-handler';
import { retryRun } from '@/features/runs/api/server';

type Params = { params: Promise<{ runId: string }> };

export async function POST(_request: Request, { params }: Params) {
  try {
    const { runId } = await params;
    return NextResponse.json(await retryRun(runId), { status: 201 });
  } catch (error) {
    return platformRouteError(error, '任务重试失败。');
  }
}
