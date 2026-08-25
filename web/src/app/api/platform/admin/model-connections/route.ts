import { NextResponse } from 'next/server';
import {
  createAdminModelConnection,
  listAdminModelConnections
} from '@/features/model-connections/api/server';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function GET() {
  try {
    return NextResponse.json(await listAdminModelConnections());
  } catch (error) {
    return platformRouteError(error, '模型连接加载失败。');
  }
}

export async function POST(request: Request) {
  try {
    return NextResponse.json(await createAdminModelConnection(await request.json()), {
      status: 201
    });
  } catch (error) {
    return platformRouteError(error, '模型连接保存失败。');
  }
}
