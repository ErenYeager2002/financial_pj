import { NextResponse } from 'next/server';
import { listAdminModelProviders } from '@/features/model-connections/api/server';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function GET() {
  try {
    return NextResponse.json(await listAdminModelProviders());
  } catch (error) {
    return platformRouteError(error, '模型供应商列表加载失败。');
  }
}
