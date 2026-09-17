import { NextResponse } from 'next/server';
import { platformServerRequest } from '@/features/platform-api/server-client';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function POST(request: Request) {
  try {
    const body = await request.json();
    return NextResponse.json(await platformServerRequest('/api/admin/skill-sources/prepare-install', {method: 'POST', body: JSON.stringify(body)}));
  } catch (error) {
    return platformRouteError(error, 'Gitee 安装请求失败。');
  }
}
