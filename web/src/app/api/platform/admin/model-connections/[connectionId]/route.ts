import { NextResponse } from 'next/server';
import {
  deleteAdminModelConnection,
  updateAdminModelConnection
} from '@/features/model-connections/api/server';
import { platformRouteError } from '@/features/platform-api/route-handler';

type RouteContext = { params: Promise<{ connectionId: string }> };

export async function PATCH(request: Request, context: RouteContext) {
  try {
    const { connectionId } = await context.params;
    return NextResponse.json(await updateAdminModelConnection(connectionId, await request.json()));
  } catch (error) {
    return platformRouteError(error, '默认模型保存失败。');
  }
}

export async function DELETE(_request: Request, context: RouteContext) {
  try {
    const { connectionId } = await context.params;
    await deleteAdminModelConnection(connectionId);
    return new NextResponse(null, { status: 204 });
  } catch (error) {
    return platformRouteError(error, '模型连接删除失败。');
  }
}
