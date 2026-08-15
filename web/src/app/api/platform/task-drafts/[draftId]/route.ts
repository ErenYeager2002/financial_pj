import { NextResponse } from 'next/server';
import { deleteTaskDraft, getTaskDraft, updateTaskDraft } from '@/features/ai-chat/api/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';

type Params = { params: Promise<{ draftId: string }> };

export async function GET(_request: Request, { params }: Params) {
  try {
    return NextResponse.json(await getTaskDraft((await params).draftId));
  } catch (error) {
    return platformRouteError(error, '任务草稿加载失败。');
  }
}

export async function PATCH(request: Request, { params }: Params) {
  try {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      throw new PlatformApiError(400, '草稿请求不是有效的 JSON。');
    }
    return NextResponse.json(await updateTaskDraft((await params).draftId, body));
  } catch (error) {
    return platformRouteError(error, '任务草稿更新失败。');
  }
}

export async function DELETE(_request: Request, { params }: Params) {
  try {
    await deleteTaskDraft((await params).draftId);
    return new NextResponse(null, { status: 204 });
  } catch (error) {
    return platformRouteError(error, '任务草稿删除失败。');
  }
}
