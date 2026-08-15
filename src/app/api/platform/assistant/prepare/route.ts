import { NextResponse } from 'next/server';
import { prepareAssistantDraft } from '@/features/ai-chat/api/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function POST(request: Request) {
  try {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      throw new PlatformApiError(400, '任务请求不是有效的 JSON。');
    }
    return NextResponse.json(await prepareAssistantDraft(body), { status: 201 });
  } catch (error) {
    return platformRouteError(error, 'AI 助手生成草稿失败。');
  }
}
