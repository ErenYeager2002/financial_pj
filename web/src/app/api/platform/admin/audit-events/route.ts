import { NextResponse } from 'next/server';
import { listAdminAuditEvents } from '@/features/admin/api/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function GET(request: Request) {
  try {
    const params = new URL(request.url).searchParams;
    const limit = Number(params.get('limit') ?? '100');
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > 500) {
      throw new PlatformApiError(400, '审计数量必须是 1 到 500 之间的整数。');
    }
    return NextResponse.json(
      await listAdminAuditEvents(
        params.get('action')?.trim() ?? '',
        params.get('actor_id')?.trim() ?? '',
        limit
      )
    );
  } catch (error) {
    return platformRouteError(error, '审计事件加载失败。');
  }
}
