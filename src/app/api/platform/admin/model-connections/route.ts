import { NextResponse } from 'next/server';
import { listAdminModelConnections } from '@/features/ai-chat/api/server';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function GET() {
  try {
    return NextResponse.json(await listAdminModelConnections());
  } catch (error) {
    return platformRouteError(error, '模型连接加载失败。');
  }
}
