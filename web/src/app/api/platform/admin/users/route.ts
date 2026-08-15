import { NextResponse } from 'next/server';
import { createAdminUser, listAdminUsers } from '@/features/admin/api/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function GET() {
  try {
    return NextResponse.json(await listAdminUsers());
  } catch (error) {
    return platformRouteError(error, '平台用户加载失败。');
  }
}

export async function POST(request: Request) {
  try {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      throw new PlatformApiError(400, '用户请求不是有效的 JSON。');
    }
    return NextResponse.json(await createAdminUser(body), { status: 201 });
  } catch (error) {
    return platformRouteError(error, '平台用户创建失败。');
  }
}
