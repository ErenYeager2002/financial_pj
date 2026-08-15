import { NextResponse } from 'next/server';
import {
  configureAdminAssistantProfile,
  getAdminAssistantProfile,
  removeAdminAssistantProfile
} from '@/features/ai-chat/api/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function GET() {
  try {
    return NextResponse.json(await getAdminAssistantProfile());
  } catch (error) {
    return platformRouteError(error, '助手模型配置加载失败。');
  }
}

export async function PUT(request: Request) {
  try {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      throw new PlatformApiError(400, '配置请求不是有效的 JSON。');
    }
    return NextResponse.json(await configureAdminAssistantProfile(body));
  } catch (error) {
    return platformRouteError(error, '助手模型配置保存失败。');
  }
}

export async function DELETE() {
  try {
    await removeAdminAssistantProfile();
    return new NextResponse(null, { status: 204 });
  } catch (error) {
    return platformRouteError(error, '助手模型配置删除失败。');
  }
}
