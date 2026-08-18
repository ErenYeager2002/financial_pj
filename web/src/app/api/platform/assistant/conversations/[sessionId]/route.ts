import { NextResponse } from 'next/server';
import { getAssistantConversation } from '@/features/ai-chat/api/server';
import { platformRouteError } from '@/features/platform-api/route-handler';

type Params = { params: Promise<{ sessionId: string }> };

export async function GET(_request: Request, { params }: Params) {
  try {
    const { sessionId } = await params;
    return NextResponse.json(await getAssistantConversation(sessionId));
  } catch (error) {
    return platformRouteError(error, 'AI 会话记录加载失败。');
  }
}
