import { NextResponse } from 'next/server';
import { platformRouteError } from '@/features/platform-api/route-handler';
import { confirmCreatedRun } from '@/features/run-setup/api/server';

type Params = { params: Promise<{ runId: string }> };

export async function POST(_request: Request, { params }: Params) {
  try {
    const { runId } = await params;
    return NextResponse.json(await confirmCreatedRun(runId));
  } catch (error) {
    return platformRouteError(error, '任务确认失败。');
  }
}
