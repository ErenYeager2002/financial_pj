import { NextResponse } from 'next/server';
import { listAdminAuditEventPage } from '@/features/admin/api/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function GET(request: Request) {
  try {
    const params = new URL(request.url).searchParams;
    const limit = Number(params.get('limit') ?? '20');
    const beforeIdValue = params.get('before_id');
    const beforeId = beforeIdValue ? Number(beforeIdValue) : undefined;
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100) {
      throw new PlatformApiError(400, '审计每页数量必须是 1 到 100 之间的整数。');
    }
    if (beforeId !== undefined && (!Number.isSafeInteger(beforeId) || beforeId < 1)) {
      throw new PlatformApiError(400, '审计翻页标识无效。');
    }
    return NextResponse.json(
      await listAdminAuditEventPage({
        action: params.get('action')?.trim() ?? '',
        actorId: params.get('actor_id')?.trim() ?? '',
        resourceType: params.get('resource_type')?.trim() ?? '',
        resourceId: params.get('resource_id')?.trim() ?? '',
        createdFrom: params.get('created_from')?.trim() ?? '',
        createdTo: params.get('created_to')?.trim() ?? '',
        limit,
        beforeId
      })
    );
  } catch (error) {
    return platformRouteError(error, '审计事件加载失败。');
  }
}
