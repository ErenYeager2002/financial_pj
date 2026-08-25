import { NextResponse } from 'next/server';
import { resetAdminUserPassword } from '@/features/admin/api/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';

type Params = { params: Promise<{ userId: string }> };

export async function POST(request: Request, { params }: Params) {
  try {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      throw new PlatformApiError(400, '密码重置请求不是有效的 JSON。');
    }
    return NextResponse.json(await resetAdminUserPassword((await params).userId, body));
  } catch (error) {
    return platformRouteError(error, '一次性密码重置失败。');
  }
}
