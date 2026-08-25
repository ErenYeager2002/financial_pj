import { NextResponse } from 'next/server';
import { retryTaskDiscoveryCheck } from '@/features/task-reminders/api/server';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ checkId: string }> }
) {
  try {
    return NextResponse.json(await retryTaskDiscoveryCheck((await params).checkId), {
      status: 202
    });
  } catch (error) {
    return platformRouteError(error, '任务检查重试失败。');
  }
}
