import { NextResponse } from 'next/server';
import { platformRouteError } from '@/features/platform-api/route-handler';
import { getRunSteps } from '@/features/runs/api/server';

type Params = { params: Promise<{ runId: string }> };

export async function GET(_request: Request, { params }: Params): Promise<NextResponse> {
  try {
    const { runId } = await params;
    return NextResponse.json(await getRunSteps(runId));
  } catch (error) {
    return platformRouteError(error, '任务步骤加载失败。');
  }
}
