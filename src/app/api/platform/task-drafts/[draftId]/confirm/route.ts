import { NextResponse } from 'next/server';
import { confirmTaskDraft } from '@/features/ai-chat/api/server';
import { platformRouteError } from '@/features/platform-api/route-handler';

type Params = { params: Promise<{ draftId: string }> };

export async function POST(_request: Request, { params }: Params) {
  try {
    return NextResponse.json(await confirmTaskDraft((await params).draftId), { status: 201 });
  } catch (error) {
    return platformRouteError(error, '任务草稿确认失败。');
  }
}
