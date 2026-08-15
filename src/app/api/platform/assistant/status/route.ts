import { NextResponse } from 'next/server';
import { getAssistantStatus } from '@/features/ai-chat/api/server';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function GET() {
  try {
    return NextResponse.json(await getAssistantStatus());
  } catch (error) {
    return platformRouteError(error, 'AI 助手状态加载失败。');
  }
}
