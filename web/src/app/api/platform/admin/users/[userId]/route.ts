import { NextResponse } from 'next/server';
import { deleteAdminUser, updateAdminUser } from '@/features/admin/api/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';

type Params = { params: Promise<{ userId: string }> };

export async function DELETE(_request: Request, { params }: Params) {
  try {
    await deleteAdminUser((await params).userId);
    return new NextResponse(null, { status: 204 });
  } catch (error) {
    return platformRouteError(error, '平台用户删除失败。');
  }
}

export async function PATCH(request: Request, { params }: Params) {
  try {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      throw new PlatformApiError(400, '用户请求不是有效的 JSON。');
    }
    return NextResponse.json(await updateAdminUser((await params).userId, body));
  } catch (error) {
    return platformRouteError(error, '平台用户更新失败。');
  }
}
