import { NextResponse } from 'next/server';
import { listApprovals } from '@/features/admin/api/approvals';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function GET(request: Request) {
  try {
    const status = new URL(request.url).searchParams.get('status') ?? '';
    return NextResponse.json(await listApprovals(status));
  } catch (error) {
    return platformRouteError(error, '审批列表加载失败。');
  }
}
