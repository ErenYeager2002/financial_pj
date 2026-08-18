import { NextResponse } from 'next/server';
import { getLatestAssistantConversation } from '@/features/ai-chat/api/server';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function GET() {
  try {
    return NextResponse.json(await getLatestAssistantConversation());
  } catch (error) {
    return platformRouteError(error, 'AI 会话记录加载失败。');
  }
}
