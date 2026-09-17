import { NextResponse } from 'next/server';
import { platformServerRequest } from '@/features/platform-api/server-client';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function POST(request: Request) {
  try {
    const body = {};
    return NextResponse.json(await platformServerRequest('/api/admin/skill-sources/install-catalog', {method: 'POST', body: JSON.stringify(body)}));
  } catch (error) {
    return platformRouteError(error, 'Gitee 安装请求失败。');
  }
}
