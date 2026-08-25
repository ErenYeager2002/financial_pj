import { NextResponse } from 'next/server';
import { refreshAdminModelConnection } from '@/features/model-connections/api/server';
import { platformRouteError } from '@/features/platform-api/route-handler';

type RouteContext = { params: Promise<{ connectionId: string }> };

export async function POST(_request: Request, context: RouteContext) {
  try {
    const { connectionId } = await context.params;
    return NextResponse.json(await refreshAdminModelConnection(connectionId));
  } catch (error) {
    return platformRouteError(error, '模型连接验证失败。');
  }
}
