import { NextResponse } from 'next/server';
import { platformRouteError } from '@/features/platform-api/route-handler';
import { getRunApprovals } from '@/features/runs/api/server';

type Params = { params: Promise<{ runId: string }> };

export async function GET(_request: Request, { params }: Params): Promise<NextResponse> {
  try {
    const { runId } = await params;
    return NextResponse.json(await getRunApprovals(runId));
  } catch (error) {
    return platformRouteError(error, '任务审批记录加载失败。');
  }
}
