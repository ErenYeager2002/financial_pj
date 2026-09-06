import { NextResponse } from 'next/server';
import { listAssistantConversations } from '@/features/ai-chat/api/server';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function GET() {
  try {
    return NextResponse.json(await listAssistantConversations());
  } catch (error) {
    return platformRouteError(error, 'AI 历史会话加载失败。');
  }
}
