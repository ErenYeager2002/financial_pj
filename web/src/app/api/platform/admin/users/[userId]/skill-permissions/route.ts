import { NextResponse } from 'next/server';
import { replaceAdminUserPermissions } from '@/features/admin/api/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';

type Params = { params: Promise<{ userId: string }> };

export async function PUT(request: Request, { params }: Params) {
  try {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      throw new PlatformApiError(400, '权限请求不是有效的 JSON。');
    }
    return NextResponse.json(await replaceAdminUserPermissions((await params).userId, body));
  } catch (error) {
    return platformRouteError(error, 'Skill 权限保存失败。');
  }
}
